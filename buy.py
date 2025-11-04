# places orders on kalshi markets
# loads markets from pool and executes limit orders at ask+2cents

import base64
import json
import os
import random
import time
from typing import Dict, List, Tuple

import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import load_dotenv

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


def sign_request(method: str, path: str, body: str, timestamp_ms: str, key_id: str, private_key_pem: str) -> str:
    """signs api requests with rsa-pss
    
    kalshi wants: timestamp + method + path (no query params or body)
    returns base64 encoded signature
    """
    # load private key
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode('utf-8'),
        password=None
    )
    
    # strip query params if any
    path_without_query = path.split('?')[0]
    
    # make the message string
    message_string = timestamp_ms + method + path_without_query
    message_bytes = message_string.encode('utf-8')
    
    # sign it
    signature = private_key.sign(
        message_bytes,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    
    return base64.b64encode(signature).decode('utf-8')


def _choose_side(side_strategy: str) -> str:
    """picks yes or no based on strategy"""
    if side_strategy == "yes":
        return "yes"
    if side_strategy == "no":
        return "no"
    # default random
    return random.choice(["yes", "no"])


def _limit_price_cents_for_buy(side: str, market: Dict, price_buffer_cents: int = 2) -> int:
    """calculates limit price for buy orders
    
    sets price at ask + buffer (default 2 cents)
    helps with fills when market moves slightly
    """
    if side == "yes":
        ask = market.get("yes_ask")
    else:
        ask = market.get("no_ask")

    if not isinstance(ask, (int, float)):
        ask = 50  # fallback if missing

    # add buffer
    price_with_buffer = ask + price_buffer_cents
    
    # clamp to 1-99
    price_with_buffer = int(max(1, min(99, round(price_with_buffer))))
    return price_with_buffer


def _headers_for_kalshi(key_id: str, signature_b64: str, timestamp_ms: str) -> Dict[str, str]:
    """returns kalshi auth headers"""
    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": signature_b64,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
    }


def _post_create_order(order_body: Dict, key_id: str, private_key_pem: str) -> Dict:
    """posts order to kalshi api with proper auth"""
    path = "/trade-api/v2/portfolio/orders"
    url = f"https://api.elections.kalshi.com{path}"

    body_text = json.dumps(order_body, separators=(",", ":"))
    timestamp_ms = str(int(time.time() * 1000))

    # sign the request
    signature_b64 = sign_request(
        method="POST",
        path=path,
        body=body_text,
        timestamp_ms=timestamp_ms,
        key_id=key_id,
        private_key_pem=private_key_pem,
    )

    headers = _headers_for_kalshi(key_id, signature_b64, timestamp_ms)

    r = requests.post(url, data=body_text, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def buy_from_pool(
    pool: List[Dict],
    kalshi_key_id: str,
    private_key_pem: str,
    choose: str = "one_random",
    side_strategy: str = "random",
    use_market_orders: bool = False,
) -> List[Tuple[str, Dict]]:
    """places buy orders from the pool
    
    choose: "one_random" picks one market, "all" trades everything
    side_strategy: "random", "yes", or "no"
    use_market_orders: False = limit orders (recommended), True = market orders
    
    returns list of (ticker, response) tuples
    """
    if not pool:
        print("pool is empty, nothing to buy")
        return []

    # decide which markets to trade
    if choose == "one_random":
        targets = [random.choice(pool)]
    else:
        targets = list(pool)

    results: List[Tuple[str, Dict]] = []

    for m in targets:
        ticker = m["ticker"]
        side = _choose_side(side_strategy)

        # build order (1 contract, gtc)
        body = {
            "ticker": ticker,
            "side": side,
            "action": "buy",
            "count": 1,
            "time_in_force": "GTC",  # good til cancelled
        }

        if use_market_orders:
            body["type"] = "market"
        else:
            # limit order at ask + buffer
            body["type"] = "limit"
            if side == "yes":
                body["yes_price"] = _limit_price_cents_for_buy("yes", m)
            else:
                body["no_price"] = _limit_price_cents_for_buy("no", m)

        try:
            resp = _post_create_order(order_body=body, key_id=kalshi_key_id, private_key_pem=private_key_pem)
            print(f"ORDER OK  | {ticker} | side={side} | resp_status={resp.get('order',{}).get('status')}")
            results.append((ticker, resp))
        except requests.HTTPError as e:
            try:
                error_msg = e.response.text[:200]
                print(f"ORDER HTTP ERROR | {ticker} | {e.response.status_code} | {error_msg}")
                
                # helpful hint for insufficient volume
                if "insufficient_resting_volume" in error_msg.lower():
                    print(f"  note: market has no liquidity at your price level")
                    print(f"  tip: don't spam the script, liquidity needs time to replenish")
                    
            except Exception:
                print(f"ORDER HTTP ERROR | {ticker} | {e}")
        except Exception as e:
            print(f"ORDER ERROR | {ticker} | {e}")

    return results


# standalone usage: load pool from json and trade
if __name__ == "__main__":
    load_dotenv()
    
    if not os.path.exists("pool.json"):
        print("pool.json not found. run pool_builder.py first.")
        raise SystemExit(1)

    with open("pool.json", "r") as f:
        pool = json.load(f)

    # load creds
    key_id = os.environ.get("KALSHI_ACCESS_KEY_ID", "")
    
    private_pem = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "")
    if not private_pem:
        key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
        if key_path and os.path.exists(key_path):
            with open(key_path, "r") as f:
                private_pem = f.read()
    
    if not key_id or not private_pem:
        print("missing credentials. check .env file")
        raise SystemExit(1)

    buy_from_pool(
        pool=pool,
        kalshi_key_id=key_id,
        private_key_pem=private_pem,
        choose="one_random",
        side_strategy="random",
        use_market_orders=False,
    )
