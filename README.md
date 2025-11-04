# kalshi trading bot

randomly trades crypto hourly markets on kalshi. picks liquid markets with tight spreads and places small $1 orders.

## what it does

1. fetches btc/eth/xrp hourly markets from kalshi api
2. filters for open markets with good spreads and liquidity
3. picks one random market and buys yes or no randomly
4. places limit order at ask+2cents to improve fills

basically just automated random trading on crypto prediction markets.

## setup

install dependencies:
```bash
pip install -r requirements.txt
```

create `.env` file with your kalshi api credentials:
```env
KALSHI_ACCESS_KEY_ID=your-key-id-here
KALSHI_PRIVATE_KEY_PATH=/path/to/private_key.pem
```

## usage

just run it:
```bash
python main.py
```

it builds the pool in memory and places one trade. no files created.

## how it works

**main.py** - entry point, runs everything in one go

**pool_builder.py** - fetches markets and filters them:
- only open markets
- spreads under 30 cents on both sides
- minimum $10 liquidity
- closes at least 5 min in the future
- keeps top 50 most liquid per event

**buy.py** - places the orders:
- picks random market from pool
- picks random yes/no
- limit order at ask+2cents
- good-til-cancelled so it sits in book

## filters

edit these in `pool_builder.py`:
```python
MAX_SPREAD_CENTS = 30        # max spread
MIN_LIQUIDITY_CENTS = 1000   # min $10 liquidity  
TOP_N_LIQUID_PER_EVENT = 50  # keep top 50
MIN_TIME_BUFFER_MINUTES = 5  # min time til close
```

## automation

run every 30 min with cron:
```bash
*/30 * * * * cd /path/to/project && python main.py >> logs/trading.log 2>&1
```

## trade economics

- buys 1 contract per trade
- costs whatever the market price is (capped at $1 max)
- pays $1 if you win
- the 2 cent buffer above ask helps with fills but costs a bit more

example: if ask is 48 cents, you pay 50 cents for a contract worth $1 if you win.

## notes

- this is random trading with no edge, you're basically gambling
- picks randomly from filtered markets
- always takes liquidity (pays the spread)
- no position tracking or risk management
- each trade capped at $1 so you can't blow up too bad

use at your own risk. this is for learning/experimenting, not serious trading.

## requirements

- python 3.7+
- requests
- python-dotenv  
- cryptography

## license

do whatever you want with it
