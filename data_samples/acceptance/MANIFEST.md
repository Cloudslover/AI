# Offline acceptance fixtures

- `../../btcusdt_15m_sample.csv` is the repository's committed recorded BTC sample.
- `ethusdt_15m.csv` and `xauusd_15m.csv` are frozen deterministic market-shaped
  fixtures used only to exercise symbol/playbook branches without network access.
  They are **not live, exchange, backtest, or calibration evidence**.

The acceptance suite compares structural output signatures, never profitability.
