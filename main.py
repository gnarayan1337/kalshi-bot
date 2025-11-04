# builds pool of markets and trades from it
# everything happens in memory, no files involved
# run once every 30 minutes via cron

import os
from dotenv import load_dotenv

from pool_builder import build_pool
from buy import buy_from_pool


def main():
    print("=" * 70)
    print("KALSHI TRADING BOT")
    print("=" * 70)
    
    # grab credentials from .env
    load_dotenv()
    key_id = os.environ.get("KALSHI_ACCESS_KEY_ID", "")
    
    # try loading pem from env var first, then from file
    private_pem = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "")
    if not private_pem:
        key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
        if key_path and os.path.exists(key_path):
            with open(key_path, "r") as f:
                private_pem = f.read()
    
    if not key_id or not private_pem:
        print("missing credentials in .env file")
        print("need: KALSHI_ACCESS_KEY_ID and KALSHI_PRIVATE_KEY_PATH")
        return
    
    # build pool
    print("\nbuilding market pool...")
    print("-" * 70)
    
    pool = build_pool()
    
    if not pool:
        print("no markets found. exiting.")
        return
    
    print(f"\npool built: {len(pool)} markets ready")
    
    # execute trades
    print("\nexecuting trades...")
    print("-" * 70)
    
    # config:
    # choose="one_random" picks one market, "all" trades everything
    # side_strategy="random" picks yes/no randomly
    # use_market_orders=False means limit orders (recommended)
    
    results = buy_from_pool(
        pool=pool,
        kalshi_key_id=key_id,
        private_key_pem=private_pem,
        choose="one_random",
        side_strategy="random",
        use_market_orders=False,
    )
    
    print("\n" + "=" * 70)
    print(f"complete: {len(results)} order(s) placed")
    print("=" * 70)


if __name__ == "__main__":
    main()

