# trading-bot

A paper trading bot for crypto and stocks. Uses EMA crossover (9/21) filtered by RSI to generate buy and sell signals with simulated pnl. 

## Setup

```bash
pip install yfinance pandas ta-lib schedule colorama
```

## Run

```bash
python trading_bot.py
```

## What it does

Fetches hourly OHLCV data for a configurable watchlist, computes EMA9, EMA21 and RSI14, then generates signals every 5 minutes. Trades are logged to `paper_trades.csv` and a live dashboard prints to the terminal each cycle.

## Strategy

- **BUY** — EMA fast crosses above EMA slow and RSI is below 70
- **SELL** — EMA fast crosses below EMA slow and RSI is above 30
- **Stop loss** at 3%, take profit at 6%

## Configuration

Edit the top section of `trading_bot.py`:

```python
WATCHLIST = { ... }        # tickers to track
POSITION_SIZE_PCT = 0.05   # 5% of portfolio per trade
SCAN_INTERVAL = 300        # seconds between scans
```

## Notes

- Paper mode only, no brokerage connection.
- Runs until stopped with Ctrl+C.
- Logs all trades to `paper_trades.csv` in the same folder.


 [NullPointer](https://nullpointer-consulting.netlify.app) · hire.nullpointer@proton.me
