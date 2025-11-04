# fetches crypto markets from kalshi and filters for good trading opportunities
# picks the next closing event per series and keeps liquid markets with tight spreads

import json
import time
from datetime import datetime
from typing import Dict, List, Tuple

import requests

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# crypto series we trade
SERIES = ["KXETHD", "KXETH", "KXBTCD", "KXBTC", "KXXRPD", "KXXRP"]

# filters
MAX_SPREAD_CENTS = 30       # both yes and no spreads must be under this
MIN_LIQUIDITY_CENTS = 1000  # at least $10 in the order book
TOP_N_LIQUID_PER_EVENT = 50  # keep top 50 most liquid per event
MIN_TIME_BUFFER_MINUTES = 5  # events must close at least 5 min in future


def parse_iso_utc(s: str) -> float:
    """converts iso timestamp to epoch seconds, returns inf if invalid"""
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except Exception:
        return float("inf")


def get_open_markets_for_series(series_ticker: str, limit: int = 1000) -> List[Dict]:
    """fetches all open markets for a series, handles pagination"""
    markets, cursor = [], None
    while True:
        params = {"series_ticker": series_ticker, "status": "open", "limit": limit}
        if cursor:
            params["cursor"] = cursor

        r = requests.get(f"{BASE_URL}/markets", params=params, timeout=25)
        r.raise_for_status()
        data = r.json()

        markets.extend(data.get("markets", []))
        cursor = data.get("cursor")
        if not cursor:
            break

    return markets


def group_by_event(markets: List[Dict]) -> Dict[str, List[Dict]]:
    """groups markets by event ticker
    one event = one hourly card, contains many strikes
    """
    by_evt: Dict[str, List[Dict]] = {}
    for m in markets:
        evt = m.get("event_ticker")
        if not evt:
            continue
        by_evt.setdefault(evt, []).append(m)
    return by_evt


def pick_soonest_future_event(by_event: Dict[str, List[Dict]]) -> Tuple[str, List[Dict]]:
    """picks the event that closes soonest in the future (with time buffer)"""
    if not by_event:
        return None, []

    now_ts = time.time()
    min_close_ts = now_ts + (MIN_TIME_BUFFER_MINUTES * 60)
    best_evt, best_close = None, float("inf")

    # pass 1: events with buffer
    for evt, group in by_event.items():
        ct = min((parse_iso_utc(g.get("close_time", "")) for g in group), default=float("inf"))
        if ct >= min_close_ts and ct < best_close:
            best_evt, best_close = evt, ct

    # pass 2: events without buffer (fallback)
    if best_evt is None:
        for evt, group in by_event.items():
            ct = min((parse_iso_utc(g.get("close_time", "")) for g in group), default=float("inf"))
            if ct >= now_ts and ct < best_close:
                best_evt, best_close = evt, ct

    # pass 3: any event (emergency fallback)
    if best_evt is None:
        for evt, group in by_event.items():
            ct = min((parse_iso_utc(g.get("close_time", "")) for g in group), default=float("inf"))
            if ct < best_close:
                best_evt, best_close = evt, ct

    return best_evt, by_event.get(best_evt, [])


def yes_spread(m: Dict) -> float:
    """calculates yes spread (ask - bid)
    returns inf if missing or if market is dead (0/0 or 100/100)
    """
    yb, ya = m.get("yes_bid"), m.get("yes_ask")
    if isinstance(yb, (int, float)) and isinstance(ya, (int, float)):
        # filter dead markets
        if (yb == 0 and ya == 0) or (yb == 100 and ya == 100):
            return float("inf")
        return float(ya - yb)
    return float("inf")


def no_spread(m: Dict) -> float:
    """calculates no spread (ask - bid)
    returns inf if missing or if market is dead
    """
    nb, na = m.get("no_bid"), m.get("no_ask")
    if isinstance(nb, (int, float)) and isinstance(na, (int, float)):
        if (nb == 0 and na == 0) or (nb == 100 and na == 100):
            return float("inf")
        return float(na - nb)
    return float("inf")


def build_pool() -> List[Dict]:
    """builds pool of tradeable markets
    
    for each series:
    - picks next closing event
    - filters by spread and liquidity
    - keeps top n most liquid
    
    returns flat list of markets ready for trading
    """
    pool: List[Dict] = []

    for series in SERIES:
        # fetch all open markets
        mkts = get_open_markets_for_series(series)

        # group by event and pick soonest
        by_evt = group_by_event(mkts)
        evt_ticker, ladder = pick_soonest_future_event(by_evt)
        if not evt_ticker or not ladder:
            print(f"{series}: no open event found")
            continue

        # filter by spread and liquidity
        filtered = []
        for m in ladder:
            ys = yes_spread(m)
            ns = no_spread(m)
            liq = m.get("liquidity", 0)
            
            if ys < MAX_SPREAD_CENTS and ns < MAX_SPREAD_CENTS and liq >= MIN_LIQUIDITY_CENTS:
                m = dict(m)  # copy
                m["_yes_spread"] = ys
                m["_no_spread"] = ns
                m["_event_ticker"] = evt_ticker
                filtered.append(m)

        if not filtered:
            print(f"{series} | {evt_ticker}: filtered out all strikes (spreads too wide or liquidity too low)")
            continue

        # keep top n by liquidity
        filtered.sort(key=lambda x: x.get("liquidity", 0), reverse=True)
        if TOP_N_LIQUID_PER_EVENT:
            filtered = filtered[:TOP_N_LIQUID_PER_EVENT]

        pool.extend(filtered)

        # print summary
        close_time_str = filtered[0].get('close_time', '') if filtered else ''
        close_ts = parse_iso_utc(close_time_str)
        minutes_until_close = (close_ts - time.time()) / 60 if close_ts != float("inf") else 0
        
        print(f"\nSeries: {series} | Event: {evt_ticker} | kept={len(filtered)}")
        print(f"  Closes in: {minutes_until_close:.1f} minutes ({close_time_str})")
        for m in filtered[:8]:
            print(
                f"  {m['ticker']} | "
                f"YES {m.get('yes_bid')}/{m.get('yes_ask')} (spread {m['_yes_spread']})  "
                f"NO {m.get('no_bid')}/{m.get('no_ask')} (spread {m['_no_spread']})  "
                f"| liq=${float(m.get('liquidity_dollars','0') or '0'):,.0f}"
            )

    return pool


if __name__ == "__main__":
    # standalone mode: build pool and save to json
    pool = build_pool()

    out_path = "pool.json"
    with open(out_path, "w") as f:
        json.dump(pool, f, indent=2)

    print(f"\n{'='*70}")
    print(f"wrote pool with {len(pool)} markets -> {out_path}")
    print(f"{'='*70}")
    print(f"\nto trade from this pool, run:")
    print(f"  python buy.py")
    print(f"\nor run both in one command:")
    print(f"  python main.py")
