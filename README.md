# 🧠 CryptoBrain — AI Trading Brain (Signal Engine)

**Multi-source, multi-indicator, conditional-signal engine for crypto futures.**

CryptoBrain is the engine behind the "AI Brain Agent Assistant" concept: instead
of following one indicator (or copying one signal service), it reads **many
indicators + market structure (ICT/SMC) at the same time**, scores them, and
emits **multiple conditional trade plans** — the way a professional
discretionary trader thinks:

> *IF price sweeps buy-side liquidity AND prints bearish CHOCH → SELL.*
>
> *IF price pulls back to the bullish order block AND rejects → BUY.*

It is a **companion / evolution** of the [Cloudslover/CryptoDashboard](https://github.com/Cloudslover/CryptoDashboard)
market dashboard: that project is the *situational awareness screen* (macro,
news, funding, order-flow, LLM brief), this project is the *signal generation
brain* (indicators → structure → scoring → JSON signals + conditional plans),
with connectors for your **private CryptoDada website** and **Discord group**.

---

## ✨ What it does

| Capability | Description |
|---|---|
| **Indicator engine** | RSI, MACD, EMA/SMA stack, Supertrend, ADX, Stochastic, WaveTrend, Bollinger, ATR, ROC, VWAP (session-anchored), Volume Profile (POC), OBV, volume spike |
| **Structure engine (ICT/SMC)** | Fractal swings, **BOS / CHOCH**, **order blocks**, **fair value gaps** (filled/unfilled), **liquidity sweeps**, equal highs/lows, premium/discount zone |
| **Scoring brain** | Weighted condition scoring (Trend +15, Structure +15, OB/FVG +20, Liquidity +15, Volume +10, Divergence +10, Momentum +10, Location +5 = 100) → `HIGH / MEDIUM / LOW / NO TRADE` |
| **Multi-condition plans** | Immediate entry, pullback at OB/FVG, breakout, sweep-reversal, FVG retest — each with entry/SL/TP ladder, R:R, confidence, and a human-readable IF condition |
| **JSON signals** | Exact schema requested — `signal_id`, `timestamp`, `asset`, `action`, `entry`, `stop_loss`, `take_profit`, `risk_reward`, `confidence`, `timeframe`, `reason` — plus validation |
| **CryptoDada website** | Connector for the private membership site (volume-spike screener, market radar, analyst notes, historical signals) via hidden-API probe or Playwright login |
| **Discord group** | Channel reader (bot/self token) that parses analyst "market update" posts into structured bias notes + sentiment; webhook push for outbound alerts |
| **News** | RSS headlines with naive sentiment tally (CoinTelegraph, CoinDesk, Decrypt) |
| **LLM narrative** | Optional AI Brain briefing (OpenAI-compatible / Gemini) that turns the numbers into plain English; rule-based fallback when no key is configured |
| **Notifiers** | Telegram + Discord webhook push of signals |
| **Backtester** | Walk-forward grading of every plan at +1h/+4h/+24h → win-rate, avg R, expectancy by plan type / confidence / action |
| **Signal database** | SQLite learning store — every scan + every graded outcome, queried via `python main.py stats` |
| **CI** | GitHub Actions runs the offline test suite on every push |
| **Web dashboard** | Single-file Flask dashboard with live scan, plans, feature snapshot, score breakdown |

---

## 🏗 Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │                 SOURCES                      │
                    │  Binance (OHLCV, funding, OI, L/S, liq)      │
                    │  CryptoDada website (volume screener, radar, │
                    │    analyst, historical signals)              │
                    │  Discord (market updates, news, chat, polls) │
                    │  RSS news feeds                              │
                    └───────────────┬──────────────────────────────┘
                                    ▼
                    ┌──────────────────────────────────────────────┐
                    │            ENGINE (this repo)                │
                    │  indicators.py   → RSI MACD EMA VWAP ADX …   │
                    │  structure.py    → BOS/CHOCH OB FVG liquidity│
                    │  features.py     → labeled market snapshot   │
                    │  scorer.py       → weighted condition score  │
                    │  rules.py        → IF/THEN conditional plans │
                    │  signal_engine.py→ final JSON + best signal  │
                    └───────────────┬──────────────────────────────┘
                                    ▼
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
      ┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
      │  CLI (main)  │     │ Web dashboard│     │ Notifiers        │
      │  scan/watch  │     │ /api/scan    │     │ Telegram/Discord │
      └──────────────┘     └──────────────┘     └──────────────────┘
```

```
Binance klines → add_all_indicators() → analyze_structure()
     → build_snapshot() → score_bullish() / score_bearish()
     → build_plans()    → build_best_signal()
     → JSON {signal, plans, snapshot, market_context, validation}
```

---

## 🚀 Quickstart

```bash
# 1. install
pip install -r requirements.txt

# 2. one-shot scan (live Binance data, no keys needed)
python main.py scan --symbol BTCUSDT --tf 15m --json

# 3. multi-symbol
python main.py scan --symbols BTCUSDT,ETHUSDT,SOLUSDT --tf 1h

# 4. continuous watch + notify (once you configure .env)
python main.py watch --symbol BTCUSDT --interval 120 --notify

# 5. web dashboard
python main.py web          # http://localhost:8050

# 6. backtest: grade every plan at +1h/+4h/+24h and store the outcomes
python main.py backtest --symbol BTCUSDT --tf 15m --bars 300 --horizons 1,4,24 --save

# 7. what the engine has learned (scans + backtest win-rates)
python main.py stats

# 8. run tests
python -m pytest tests/ -q
```

**Offline demo** (no network): use the committed sample dataset —

```python
import pandas as pd
from engine.signal_engine import analyze_frame

df = pd.read_csv("data_samples/btcusdt_15m_sample.csv")
out = analyze_frame(df, symbol="BTCUSDT", timeframe="15m")
print(out.best_signal)
```

---

## 📦 Output format

The engine emits **exactly** the requested signal schema, plus the conditional
plans array:

```json
{
  "signal": {
    "signal_id": "BTCUSDT_20260804_0654",
    "timestamp": 1785826483752,
    "asset": "BTCUSDT",
    "action": "SELL",
    "entry": 63670.0,
    "stop_loss": 63861.01,
    "take_profit": 63287.98,
    "risk_reward": 2.5,
    "confidence": "MEDIUM",
    "timeframe": "15m",
    "reason": "price below VWAP + Buyside liquidity swept + sellside targets below + Momentum aligned (RSI<50, MACD histogram falling)"
  },
  "plans": [
    {
      "id": "reversal_sell",
      "type": "Sweep Reversal Sell",
      "action": "SELL",
      "condition": "IF buyside liquidity was swept at 64023.61 AND price shows bearish CHOCH / rejection",
      "trigger_level": 64023.61,
      "entry": 63670.0,
      "stop_loss": 63861.01,
      "take_profits": [63287.98, 62905.96],
      "risk_reward": 2.5,
      "confidence": 62,
      "confidence_label": "MEDIUM",
      "reasons": ["Bearish structure (bos_down)", "Buyside stop hunt detected"],
      "status": "active"
    }
  ],
  "snapshot": { "features": { "...60 labeled conditions..." }, "scores": { "bull": {...}, "bear": {...} } },
  "market_context": { "funding_rate_pct": null, "open_interest": null, "long_short_ratio": null },
  "validation": { "ok": true, "errors": [], "warnings": [] }
}
```

`signal.signal_type` is `SIGNAL` when a plan crosses the confidence threshold,
otherwise `MONITOR` (read the `plans` array for setups to wait for).
See `examples/example_signal.json` for a full live capture.

---

## 🔌 Connecting your private sources

### CryptoDada website (screenshots 1–5)

Copy `.env.example` → `.env` and fill:

```
CRYPTODADA_MODE=auto                 # auto | api | browser
CRYPTODADA_BASE_URL=https://your-cryptodada-site
CRYPTODADA_EMAIL=you@example.com
CRYPTODADA_PASSWORD=********
```

* `api` — probes the dashboard's hidden JSON endpoints (find them in DevTools
  → Network tab; the connector tries `/api/signals`, `/api/volume-spikes`,
  `/api/radar`, `/api/analyst`, …). Fastest.
* `browser` — Playwright login + scrape (`pip install playwright &&
  playwright install chromium`).
* `auto` — try `api`, fall back to `browser`.

Then: `python main.py sources` → the volume-spike screener rows become
**candidate signals that the engine independently cross-scores** with funding /
OI / structure before you act on them.

### Discord group (screenshots 6–8)

* **Read** analyst posts / market updates:
  ```
  DISCORD_TOKEN=your_bot_or_self_token
  DISCORD_CHANNEL_IDS=123456789,987654321
  ```
  `python main.py sources` parses "Market Update" messages into `{bias, levels,
  raw}` notes and tallies chat sentiment.
  ⚠️ Automating a **user** account can violate Discord's ToS — prefer a bot
  account added by the server admin, and review the ToS yourself.
* **Push** signals into the group (safe, recommended):
  ```
  DISCORD_ANNOUNCE_WEBHOOK=https://discord.com/api/webhooks/...
  ```
  then `python main.py watch --notify`.

---

## 🧠 LLM AI Brain narrative (optional)

```
LLM_PROVIDER=openai        # auto | openai | gemini | off
OPENAI_API_KEY=sk-...
# any OpenAI-compatible endpoint works, e.g. Groq:
# OPENAI_BASE_URL=https://api.groq.com/openai/v1
# OPENAI_MODEL=openai/gpt-oss-120b
```

`python main.py scan --symbol BTCUSDT --llm` appends a plain-English analyst
brief to the JSON. With no key, a deterministic rule-based narrative is used —
the output is never empty.

---

## 🧪 Tests

```bash
python -m pytest tests/ -q      # 33 tests, fully offline (synthetic data)
```

Covers: indicator math & no-look-ahead, structure detection (BOS/CHOCH, FVG,
sweeps), score bounds, plan generation (SL below entry for BUY etc.), full
pipeline, JSON schema validation, the backtester grader, and the database.

On every push, GitHub Actions runs this suite automatically
(`.github/workflows/ci.yml`) plus an offline smoke test on the sample data.

---

## 📊 Backtester — the learning loop

`python main.py backtest --symbol BTCUSDT --tf 15m --bars 300 --horizons 1,4,24 --save`

Walks the engine forward bar-by-bar (data up to each bar only — no look-ahead),
then grades every plan it produced at each horizon:

* **WIN / PARTIAL_WIN / FULL_WIN** — TP1 (and TP2) hit before SL
* **LOSS** — SL hit before TP1
* **OPEN** — neither level touched within the horizon
* **NOT_TRIGGERED** — the conditional plan's entry level was never reached

Output aggregates **win-rate, average R and expectancy** by plan type, by
confidence bucket and by action. Example (real BTCUSDT 15m, 300 bars):

```
by plan type:
  Buy Pullback        exec 137  win 73.0%  avgR +1.50
  FVG Retest Buy      exec  80  win 60.0%  avgR +1.19
  Breakout Buy        exec 271  win  8.5%  avgR -0.70
```

This is how the engine discovers *its own* edge map — which setups to trust
and which to filter out. `--save` stores every graded outcome in the signal
database.

---

## 🗄 Signal database — the memory

Every `scan` and `watch` tick is saved by default to `data/cryptobrain.db`
(SQLite, no extra deps) — signal, plans, feature snapshot, market context.
Backtest outcomes land in the same store.

```bash
python main.py stats    # scans + plan distribution + backtest win-rates
```

Tables: `scans`, `plans`, `backtest_results`. Use `--no-save` to skip DB
writes. This store is the foundation for future confidence calibration
(e.g. dampen a plan type the engine has measured as negative-expectancy).

---

## 🔄 CI

`.github/workflows/ci.yml` runs on every push / PR to `main`:
Python 3.12 → install deps → `compileall` → `pytest` → offline smoke test on
`data_samples/btcusdt_15m_sample.csv`. All tests are network-free, so CI is
fast and deterministic.

---

## 📁 Project layout

```
crypto-brain/
├── main.py                  # CLI: scan / watch / sources / backtest / stats / web
├── config.py                # env-driven configuration
├── engine/
│   ├── indicators.py        # RSI MACD EMA VWAP ADX BB Supertrend WaveTrend …
│   ├── structure.py         # swings, BOS/CHOCH, OB, FVG, liquidity, sweeps
│   ├── features.py          # labeled market snapshot (60 conditions)
│   ├── scorer.py            # weighted condition scoring → confidence
│   ├── rules.py             # IF/THEN conditional plan generator
│   └── signal_engine.py     # orchestrator → final JSON
├── data/
│   ├── binance_client.py    # geo-aware Binance market data
│   ├── database.py          # SQLite learning store (scans/plans/backtests)
│   ├── backtester.py        # walk-forward plan grader (+1h/+4h/+24h)
│   └── sources/
│       ├── cryptodada_website.py  # private-site connector (api/browser)
│       ├── discord_reader.py      # Discord reader + webhook push
│       └── news.py                # RSS headlines + sentiment
├── ai/llm_brain.py          # optional LLM narrative (OpenAI/Gemini/offline)
├── output/
│   ├── signal_schema.py     # JSON validation
│   └── notifiers.py         # Telegram + Discord push
├── web/app.py               # Flask dashboard
├── tests/                   # offline test-suite (33 tests)
├── .github/workflows/ci.yml # auto test-runner on push
├── examples/example_signal.json
└── data_samples/btcusdt_15m_sample.csv
```

---

## 📤 Publishing to GitHub

The repo is git-initialised and committed locally. To publish:

```bash
cd crypto-brain
git remote add origin https://github.com/YOUR_USERNAME/crypto-brain.git
git push -u origin main
```

(or create a repo on GitHub first — empty, no README — then run the two lines above.)

---

## ⚠️ Disclaimer

This software is for **research and education**. Outputs are risk-advice only,
not financial advice. Crypto derivatives are high-risk; always use stop-losses
and never risk money you cannot afford to lose. Always respect the ToS and rate
limits of any service you connect to (Binance, Discord, CryptoDada, LLM APIs).
