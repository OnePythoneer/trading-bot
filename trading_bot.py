"""
NullPointer Trading System
===========================
Strategy: EMA Crossover (9/21) filtered by RSI
Markets: Crypto + Stocks (via yfinance)
Mode: Paper trading — simulated P&L only

SETUP:
  pip install yfinance pandas ta schedule colorama pyyaml

CONFIG:
  Edit config.yaml to change watchlist, capital, strategy params, and risk settings.
  No need to touch this file.

RUN:
  python trading_bot.py
"""

import csv
import logging
import os
import time
import yaml
from datetime import datetime

import pandas as pd
import ta
import yfinance as yf

CONFIG_FILE = "config.yaml"

# ─────────────────────────────────────────────
# COLORS (terminal output)
# ─────────────────────────────────────────────
try:
    from colorama import init, Fore, Style
    init()
    GREEN  = Fore.GREEN
    RED    = Fore.RED
    YELLOW = Fore.YELLOW
    CYAN   = Fore.CYAN
    RESET  = Style.RESET_ALL
    BOLD   = Style.BRIGHT
except ImportError:
    GREEN = RED = YELLOW = CYAN = RESET = BOLD = ""


# ─────────────────────────────────────────────
# CONFIG & LOGGING
# ─────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(log_file: str) -> logging.Logger:
    logger = logging.getLogger("trading-bot")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


config = load_config()
logger = setup_logging(config["log_file"])

WATCHLIST       = config["watchlist"]
EMA_FAST        = config["strategy"]["ema_fast"]
EMA_SLOW        = config["strategy"]["ema_slow"]
RSI_PERIOD      = config["strategy"]["rsi_period"]
RSI_OVERBOUGHT  = config["strategy"]["rsi_overbought"]
RSI_OVERSOLD    = config["strategy"]["rsi_oversold"]
POSITION_PCT    = config["risk"]["position_size_pct"]
STOP_LOSS_PCT   = config["risk"]["stop_loss_pct"]
TAKE_PROFIT_PCT = config["risk"]["take_profit_pct"]
DATA_PERIOD     = config["data"]["period"]
DATA_INTERVAL   = config["data"]["interval"]
SCAN_INTERVAL   = config["scan_interval"]
TRADES_LOG      = config["trades_log"]

PAPER_PORTFOLIO = {
    "cash": float(config["portfolio"]["starting_capital"]),
    "positions": {},
}


# ─────────────────────────────────────────────
# CORE FUNCTIONS
# ─────────────────────────────────────────────

def fetch_data(ticker: str) -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, period=DATA_PERIOD, interval=DATA_INTERVAL,
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 30:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        logger.error("Failed to fetch %s: %s", ticker, e)
        return None


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"].squeeze()
    df["ema_fast"] = ta.trend.EMAIndicator(close, window=EMA_FAST).ema_indicator()
    df["ema_slow"] = ta.trend.EMAIndicator(close, window=EMA_SLOW).ema_indicator()
    df["rsi"]      = ta.momentum.RSIIndicator(close, window=RSI_PERIOD).rsi()
    df["ema_cross_up"]   = (df["ema_fast"] > df["ema_slow"]) & (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1))
    df["ema_cross_down"] = (df["ema_fast"] < df["ema_slow"]) & (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1))
    return df


def get_signal(df: pd.DataFrame) -> str:
    last       = df.iloc[-1]
    rsi        = float(last["rsi"])
    cross_up   = bool(last["ema_cross_up"])
    cross_down = bool(last["ema_cross_down"])

    if cross_up and rsi < RSI_OVERBOUGHT:
        return "BUY"
    elif cross_down and rsi > RSI_OVERSOLD:
        return "SELL"
    return "HOLD"


def get_portfolio_value() -> float:
    total = PAPER_PORTFOLIO["cash"]
    for ticker, pos in PAPER_PORTFOLIO["positions"].items():
        df = fetch_data(ticker)
        if df is not None:
            total += pos["qty"] * float(df["Close"].iloc[-1])
    return total


def execute_paper_buy(ticker: str, price: float, portfolio_value: float):
    if ticker in PAPER_PORTFOLIO["positions"]:
        return
    trade_value = portfolio_value * POSITION_PCT
    if trade_value > PAPER_PORTFOLIO["cash"]:
        logger.warning("Not enough cash for %s — skipping", ticker)
        print(f"{YELLOW}  [SKIP] Not enough cash for {ticker}{RESET}")
        return
    qty = trade_value / price
    PAPER_PORTFOLIO["cash"] -= trade_value
    PAPER_PORTFOLIO["positions"][ticker] = {
        "qty": qty,
        "entry_price": price,
        "entry_time": datetime.now().isoformat(),
        "stop_loss": price * (1 - STOP_LOSS_PCT),
        "take_profit": price * (1 + TAKE_PROFIT_PCT),
    }
    log_trade(ticker, "BUY", price, qty, trade_value)
    logger.info("BUY  %s @ $%.4f | qty=%.6f | value=$%.2f", ticker, price, qty, trade_value)
    print(f"{GREEN}  ✓ PAPER BUY  {ticker} @ ${price:,.4f} | Qty: {qty:.6f} | Value: ${trade_value:,.2f}{RESET}")


def execute_paper_sell(ticker: str, price: float, reason: str = "signal"):
    if ticker not in PAPER_PORTFOLIO["positions"]:
        return
    pos     = PAPER_PORTFOLIO["positions"][ticker]
    qty     = pos["qty"]
    entry   = pos["entry_price"]
    proceeds = qty * price
    pnl     = proceeds - (qty * entry)
    pnl_pct = (pnl / (qty * entry)) * 100

    PAPER_PORTFOLIO["cash"] += proceeds
    del PAPER_PORTFOLIO["positions"][ticker]

    log_trade(ticker, f"SELL ({reason})", price, qty, proceeds, pnl, pnl_pct)
    logger.info("SELL %s @ $%.4f | P&L $%.2f (%.2f%%) [%s]", ticker, price, pnl, pnl_pct, reason)
    color = GREEN if pnl >= 0 else RED
    print(f"{color}  ✓ PAPER SELL {ticker} @ ${price:,.4f} | P&L: {'+' if pnl>=0 else ''}{pnl:.2f} ({pnl_pct:+.2f}%) [{reason}]{RESET}")


def check_stop_take(ticker: str, current_price: float):
    if ticker not in PAPER_PORTFOLIO["positions"]:
        return
    pos = PAPER_PORTFOLIO["positions"][ticker]
    if current_price <= pos["stop_loss"]:
        execute_paper_sell(ticker, current_price, reason="stop_loss")
    elif current_price >= pos["take_profit"]:
        execute_paper_sell(ticker, current_price, reason="take_profit")


def log_trade(ticker, action, price, qty, value, pnl=None, pnl_pct=None):
    file_exists = os.path.exists(TRADES_LOG)
    with open(TRADES_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "ticker", "action", "price", "qty", "value", "pnl", "pnl_pct"])
        writer.writerow([
            datetime.now().isoformat(), ticker, action,
            round(price, 6), round(qty, 8), round(value, 2),
            round(pnl, 2) if pnl is not None else "",
            round(pnl_pct, 2) if pnl_pct is not None else "",
        ])


def print_dashboard():
    portfolio_value = get_portfolio_value()
    os.system("cls" if os.name == "nt" else "clear")
    print(f"\n{BOLD}{CYAN}{'─'*55}")
    print(f"  NullPointer Trading System — Paper Mode")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'─'*55}{RESET}")
    print(f"  {BOLD}Portfolio Value:{RESET} ${portfolio_value:,.2f}")
    print(f"  {BOLD}Cash:{RESET}            ${PAPER_PORTFOLIO['cash']:,.2f}")
    print(f"  {BOLD}Open Positions:{RESET}  {len(PAPER_PORTFOLIO['positions'])}")

    if PAPER_PORTFOLIO["positions"]:
        print(f"\n  {BOLD}Open Positions:{RESET}")
        for ticker, pos in PAPER_PORTFOLIO["positions"].items():
            df = fetch_data(ticker)
            if df is not None:
                curr = float(df["Close"].iloc[-1])
                pnl  = (curr - pos["entry_price"]) / pos["entry_price"] * 100
                color = GREEN if pnl >= 0 else RED
                print(f"    {ticker:<12} entry=${pos['entry_price']:.4f}  now=${curr:.4f}  {color}{pnl:+.2f}%{RESET}")
                print(f"    {'':12} SL=${pos['stop_loss']:.4f}  TP=${pos['take_profit']:.4f}")
    print(f"\n{BOLD}{CYAN}{'─'*55}{RESET}\n")


# ─────────────────────────────────────────────
# MAIN SCAN LOOP
# ─────────────────────────────────────────────

def scan():
    print_dashboard()
    print(f"  Scanning {len(WATCHLIST)} tickers...\n")
    portfolio_value = get_portfolio_value()

    for ticker, meta in WATCHLIST.items():
        print(f"  {BOLD}[{meta['type'].upper()}] {ticker} — {meta['name']}{RESET}")
        df = fetch_data(ticker)
        if df is None:
            logger.warning("No data for %s — skipping", ticker)
            print(f"  {YELLOW}  No data — skipping{RESET}")
            continue

        df     = compute_indicators(df)
        signal = get_signal(df)
        price  = float(df["Close"].iloc[-1])
        rsi    = float(df["rsi"].iloc[-1])
        ema_f  = float(df["ema_fast"].iloc[-1])
        ema_s  = float(df["ema_slow"].iloc[-1])

        print(f"  Price: ${price:,.4f}  |  EMA{EMA_FAST}: {ema_f:.4f}  EMA{EMA_SLOW}: {ema_s:.4f}  |  RSI: {rsi:.1f}")
        logger.info("%s  price=%.4f  EMA%d=%.4f  EMA%d=%.4f  RSI=%.1f  signal=%s",
                    ticker, price, EMA_FAST, ema_f, EMA_SLOW, ema_s, rsi, signal)

        check_stop_take(ticker, price)

        if signal == "BUY":
            print(f"  {GREEN}→ SIGNAL: BUY{RESET}")
            execute_paper_buy(ticker, price, portfolio_value)
        elif signal == "SELL":
            print(f"  {RED}→ SIGNAL: SELL{RESET}")
            execute_paper_sell(ticker, price, reason="signal")
        else:
            print(f"  {YELLOW}→ SIGNAL: HOLD{RESET}")
        print()

    print(f"  {BOLD}Next scan in {SCAN_INTERVAL//60} minutes...{RESET}\n")


def main():
    print(f"""
{BOLD}{CYAN}
  ███╗   ██╗██╗   ██╗██╗     ██╗     
  ████╗  ██║██║   ██║██║     ██║     
  ██╔██╗ ██║██║   ██║██║     ██║     
  ██║╚██╗██║██║   ██║██║     ██║     
  ██║ ╚████║╚██████╔╝███████╗███████╗
  ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝╚══════╝
  TRADING SYSTEM — PAPER MODE
{RESET}
  Strategy:   EMA({EMA_FAST}/{EMA_SLOW}) Crossover + RSI({RSI_PERIOD}) Filter
  Markets:    {len(WATCHLIST)} tickers (Crypto + Stocks)
  Capital:    ${PAPER_PORTFOLIO['cash']:,.2f} (simulated)
  Risk/trade: {POSITION_PCT*100:.0f}% | SL: {STOP_LOSS_PCT*100:.0f}% | TP: {TAKE_PROFIT_PCT*100:.0f}%
  Interval:   Every {SCAN_INTERVAL//60} minutes
  Config:     {CONFIG_FILE}
  Log:        {config['log_file']}

  Press Ctrl+C to stop.
{BOLD}{'─'*55}{RESET}
""")
    logger.info("Trading bot started — %d tickers, $%.2f capital", len(WATCHLIST), PAPER_PORTFOLIO["cash"])
    time.sleep(2)

    while True:
        try:
            scan()
            time.sleep(SCAN_INTERVAL)
        except KeyboardInterrupt:
            final = get_portfolio_value()
            logger.info("Stopped by user. Final portfolio value: $%.2f", final)
            print(f"\n{BOLD}Stopping. Final portfolio value: ${final:,.2f}{RESET}")
            break
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            time.sleep(30)


if __name__ == "__main__":
    main()
