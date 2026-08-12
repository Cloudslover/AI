# ARCHITECTURE.md — CryptoBrain / SKY

> **Purpose:** the module map + invariants a new Arena session reads
> to understand the codebase without re-deriving it. Companion to
> `SESSION_STATE.md` (current state) and `TODO.md` (next work).
> **Update when:** the module map or the invariants change.
> **Read when:** starting work on a module you haven't touched in
> ≥1 session.

**Last updated:** 2026-08-11
**Stack:** Python 3.10+, Flask 3, SQLite, stdlib JSON-RPC MCP server.
**Single-process, single-user, single-machine.**

---

## Module map (one-line each)

### Top level
| File | Purpose |
|---|---|
| `main.py` | argparse CLI dispatcher (~30 `cmd_*` subcommands) |
| `config.py` | Env-driven config; `VERSION = "2.1.0"`; exports market/risk settings and explicit operator-approved scoring weights |
| `mcp_server.py` | Zero-dep stdio JSON-RPC 2.0 MCP server (read-only tool permission map) |
| `SKILL.md` | Agent-facing skill file (the one AI agents read first) |
| `SESSION_STATE.md` | Handoff memory between Arena sessions |
| `TODO.md` | Prioritised remaining work |
| `ARCHITECTURE.md` | This file |
| `CHANGELOG.md` | Versioned shipped behavior and migration notes |
| `BLUEPRINT.md` | The 4-step path from paper to real capital |
| `PROFESSIONAL_PLAN_DECISIONS.md` | The 18-phase professional plan + D-list |
| `ROADMAP_AGENT_REACH_UPGRADE.md` | The P7/P8/P9 Agent-Reach-inspired plan |
| `MERGE_NOTES.md` | Provenance of the Cloudslover + cloudshome merge |
| `docs/adr/0001-functional-core-and-decision-layers.md` | Boundary redesign rationale and trade-offs |
| `AI_ANATOMY_ROADMAP.md` | Live status of P1–P9 |

### `brain/` — the desk brain
| Module | Purpose | Used by |
|---|---|---|
| `agent.py` | Health, morning briefing, graduation report, and grounded desk questions | `cmd_health`, `cmd_agent`, `cmd_doctor` |
| `agents.py` | Autonomous desk agents (morning, watchdog, paper-reviewer, weekly-review), audit-logged to `agent_runs` | `cmd_agent` |
| `analytics.py` | MAE/MFE summary, Monte Carlo equity/drawdown | `hidden analytics mae/mc` |
| `ask.py` | RAG query with grounded citations | `cmd_ask`, MCP `ask` |
| `brief.py` | Cross-asset morning brief + post-trade reviews | `cmd_brief`, `cmd_postreview`, `cmd_agent morning` |
| `calibrator.py` | Self-improvement profile from graded backtests | `cmd_learn` |
| `channels.py` | **NEW (P8)** ordered-backend router for cryptodada / discord / news / llm | `cmd_doctor`, `cmd_channels` |
| `coach.py` | Why-the-engine-said-what teaching mode | `cmd_coach` |
| `context.py` | Macro, FOMC/CPI/NFP, fear&greed, BTC dominance, equities | `analyze_full` |
| `decision.py` | Playbook/portfolio/risk-gated BUY/SELL/NO_TRADE desk verdict | `analyze_full` |
| `decision_service.py` | Three layers: watch items / active candidate / desk verdict; confidence ≠ fill probability | `analyze_full`, CLI/web queue |
| `full_pipeline.py` | Imperative shell: fetches I/O/state then calls the pure core | `cmd_scan`, `cmd_intelligence` |
| `context_providers.py` | Standard `fetch_context(symbol)` provider interface + completeness reporting | `context.collect` |
| `meta_learner.py` | Offline advisory grid over scoring weights; never auto-activates | `cmd_meta_learn` |
| `immune.py` | Staleness, DB integrity, risk gates, behavioral flags, calibration drift | `cmd_health`, `cmd_doctor` |
| `institutional_score.py` | Institutional desk-style scoring | `intelligence` |
| `journal.py` | Professional trading journal | `cmd_journal` |
| `library.py` | RAG knowledge index | `ask` |
| `metrics.py` | Win-rate, expectancy, profit factor, drawdown, streaks | `agents`, `metrics` |
| `playbooks.py` | Per-asset playbooks (BTC / ETH / GOLD) | `library`, `ask` |
| `portfolio.py` | Portfolio-level risk (BTC+ETH = one bucket) | `intelligence` |
| `risk_gate.py` | **The gate.** Kelly-advisory, daily/weekly stop, progression ladder | `cmd_approve`, `cmd_risk` |
| `state_memory.py` | 8D state fingerprint + historical similarity | `cmd_state` |
| `styles.py` | Scalp/Day/Swing/Momentum/Position style routing | `analyze_full` |
| `trading_intelligence.py` | The institutional desk report | `cmd_intelligence`, `cmd_card` |

### `data/` — sources + persistence
| Module | Purpose |
|---|---|
| `binance_client.py` | Public market data (OHLCV, funding, OI, L/S, liq) with geo-friendly fallbacks |
| `sample_client.py` | Offline deterministic synthetic data (DEMO_MODE=1) |
| `database.py` | SQLite schema (scans, plans, backtest_results, paper_trades, agent_runs, journal_entries, trader_state); `SignalDB` context manager |
| `backtester.py` | Walk-forward grading of plans at +1h/+4h/+24h |
| `paper_trading.py` | Approved-signal lifecycle: monitor + auto-close at SL/TP1 (no real orders) |
| `simulator.py` | The paper-sample grind (100/20 sample proof); `graduation_status` |
| `symbols.py` | Alias resolution (BTC → BTCUSDT, ETH → ETHUSDT, GOLD → XAUUSD) |
| `sources/cryptodada_website.py` | Connector for the private CryptoDada site (api/browser modes) |
| `sources/discord_reader.py` | Connector for the private Discord group (read + webhook push) |
| `sources/news.py` | RSS headlines from CoinTelegraph / CoinDesk / Decrypt + naive sentiment |

### `engine/` — quant layer
| Module | Purpose |
|---|---|
| `indicators.py` | RSI, MACD, EMA/SMA stack, Supertrend, ADX, Stochastic, WaveTrend, Bollinger, ATR, ROC, VWAP, POC, OBV, volume spike |
| `structure.py` | Fractal swings, BOS/CHOCH, order blocks, FVGs, liquidity sweeps, equal highs/lows, premium/discount |
| `features.py` | Labeled market snapshot (HTF bias, LTF setup, alignment score) |
| `scorer.py` | Validated 100-point weight profiles; default Trend +15, Structure +15, OB/FVG +20, Liquidity +15, Volume +10, Divergence +10, Momentum +10, Location +5 |
| `rules.py` | Policy-agnostic IF/THEN plan generation, HTF SMC levels, confidence + distinct fill probability |
| `policy.py` | Post-generation setup-family authorization; research plans remain visible |
| `pipeline.py` | Pure functional core with immutable Feature/Score/Plan/BrainOutput stages |
| `signal_engine.py` | Compatibility facade for `engine.pipeline`; legacy import path remains stable |
| `regime.py` | Volatility / trend regime classification |
| `mtf.py` | Multi-timeframe (Monthly → 1M) alignment |
| `lifecycle.py` | Signal status transitions (CREATED → PENDING_REVIEW → APPROVED → EXECUTED → CLOSED) |
| `execution.py` | Realistic spread/slippage execution model (`EXECUTION_MODEL=simple`) |
| `hidden_alpha.py` | Markov-smoothed HMM regimes, CVD order flow, Bayesian Kelly, 8D fingerprint + similarity search |
| `correlation.py` | Measured BTC/ETH/GOLD rolling correlation + ETH/BTC beta |
| `calibration_hook.py` | Plugs the `brain/calibrator` into the engine output |

### `output/` — rendering + delivery
| Module | Purpose |
|---|---|
| `signal_schema.py` | The exact JSON contract (`signal_id`, `timestamp`, `asset`, `action`, `entry`, `stop_loss`, `take_profit`, `risk_reward`, `confidence`, `timeframe`, `reason`) + `validate_output` |
| `notifiers.py` | Telegram + Discord webhook push |

### `web/` — Flask dashboard
| Module | Purpose |
|---|---|
| `app.py` | Flask app factory `make_app()`, all `/api/*` routes, `serve()` runner |

### `tests/` — 41 test modules, 317 pass / 1 skip
- Most modules have a matching `test_*.py`.
- `tests/test_web_api.py` — Flask endpoint regression tests (catches the
  `_sanitize_for_json` numpy-bool-500 bug fixed in the consolidated
  build per `MERGE_NOTES.md`).
- `tests/test_mcp_stdio.py` — Root MCP server handshake, tool
  permission map, trader-state round-trip, health check.
- `tests/test_channels.py` — **NEW (P8)** 27 tests for the channels
  router + SKILL.md content contract + new CLI subcommands.

### `docs/`
- `agent_install.md` — **NEW (P7)** the one-pager an agent fetches when
  told "install CryptoBrain."
- `.github/workflows/ci.yml` — offline unit/integration CI.
- `docs/workflows/acceptance.yml` — scheduled full-desk workflow template;
  copy to `.github/workflows/` with workflow-scoped credentials.

---

## Invariants (do NOT break these)

1. **The engine never places a real exchange order.** Enforced in
   `mcp_server.handle_tool_call()` (no `approve | reject | execute |
   close | place_order` tool in `ALLOWED_TOOLS`) and in
   `data/paper_trading.py` (paper-only). The human-approval gate is
   mandatory and is enforced on every approval via
   `brain.risk_gate.evaluate_risk_gate`.

2. **MCP `tools/list` is a permission map, not a feature list.** Adding
   a tool = expanding what the agent can do. New tools must be
   read-only. Mutation paths go through the CLI / dashboard only.

3. **The risk gate is consulted on every approval.** Even if an agent
   fabricates a signal, `brain/risk_gate.evaluate_risk_gate` blocks
   approval when daily/weekly loss limits are reached, when
   `trader_state` shows behavioral flags, or when the progression
   ladder is at `student` / `researcher`.

4. **BTC + ETH = one correlated crypto-risk bucket.** Enforced in
   `brain/portfolio.py` and verified by
   `python main.py correlation`. The `engine/correlation.py` module
   measures the actual rolling correlation and reports whether the
   bucket rule is being honoured.

5. **The `ask` tool must always produce a citation.** Every answer
   carries `[cited: ...]` markers (enforced in `brain/ask.py`). This
   is the only way the operator can verify the engine's reasoning.

6. **The default install/setup is non-mutating.** Mirrors
   Agent-Reach's safety posture. `python main.py doctor`,
   `python main.py channels`, `python main.py skill --print` are all
   read-only. `python main.py skill --install` requires
   `--system` to write under `$HOME`.

7. **Tests must stay ≥ 317 pass / 1 skip.** The 1 skip is the
   SDK-already-installed fallback (pre-existing, per `MERGE_NOTES.md`).
   Any new feature must add at least as many tests as it adds source
   lines of complexity (rule of thumb: ≥ 1 test per non-trivial
   branch).

8. **Commits are checkpoints.** Every commit is a safe point a future
   Arena session can roll back to. Don't bundle unrelated changes
   into one commit.

9. **SESSION_STATE.md is updated at the end of every session.**
   See "End-of-session checklist" in SESSION_STATE.md.

10. **No web scraping of social platforms.** Out of scope per
    `ROADMAP_AGENT_REACH_UPGRADE.md` §5. Don't add dependencies on
    `browser-cookie3`, `playwright` (only for the CryptoDada
    connector, which already exists), `yt-dlp`, `ffmpeg`, or any
    Twitter/Reddit/Bilibili/Xiaohongshu/Facebook/Instagram/LinkedIn
    API/CLI.

---

## Data flow (end-to-end)

```
Binance (or sample) OHLCV
   ↓
engine/indicators.py → RSI MACD EMA VWAP ADX ...
   ↓
engine/structure.py → BOS/CHOCH OB FVG liquidity
   ↓
engine/regime.py + engine/mtf.py → HTF bias + LTF setup
   ↓
engine/features.py → labeled market snapshot
   ↓
engine/scorer.py → weighted condition score
   ↓
engine/rules.py → IF/THEN conditional plans
   ↓
engine/signal_engine.py → final JSON signal
   ↓
brain/decision.py → BUY/SELL/NO_TRADE
   ↓
brain/risk_gate.py → open/closed + position size
   ↓
brain/trading_intelligence.py → institutional desk report
   ↓
   ┌──────────────┬──────────────┬──────────────┐
   ↓              ↓              ↓              ↓
CLI scan/    Dashboard       Notifier       DB (scans table)
intelligence (web/app.py)    (Telegram/     → PENDING_REVIEW
                             Discord)         → human approves
                                             → paper_trading.py monitors
                                             → auto-close at SL/TP1
                                             → brain/analytics.py grades
                                             → brain/calibrator.py learns
```

The MCP server (`mcp_server.py`) and the `ask` RAG layer
(`brain/ask.py` over `brain/library.py`) are read-only side-channels
into the same DB and engine — they never write.

---

## Configuration cheatsheet

The full env-var list is in `.env.example`. The most commonly
touched ones:

| Var | Default | Purpose |
|---|---|---|
| `DEMO_MODE` | `0` | `1` = offline deterministic data; `0` = live Binance |
| `SYMBOLS` | `BTCUSDT,ETHUSDT,XAUUSD` | Dashboard watchlist |
| `TIMEFRAME` | `15m` | Default scan timeframe |
| `BARS` | `500` | Default history length |
| `MIN_CONFIDENCE` | `55` | Raw plan confidence floor |
| `INTELLIGENCE_MIN_CONFIDENCE` | `80` | Desk report confidence floor (stricter) |
| `INTELLIGENCE_MIN_RR` | `2.0` | Desk report R:R floor |
| `MAX_RISK_PCT` | `1.0` | Hard ceiling risk per trade |
| `KELLY_MAX_RISK_PCT` | `0.5` | Kelly-advisory ceiling |
| `MAX_DAILY_LOSS_PCT` | `1.5` | Daily stop |
| `MAX_WEEKLY_LOSS_PCT` | `3.0` | Weekly stop |
| `PROGRESSION` | `student` | `student → researcher → simulator → micro → consistent → scale` |
| `DESK_DEFAULT` | `true` | Desk-first output (raw engine plans visible as research) |
| `EXECUTION_MODEL` | (unset) | `simple` = realistic spread/slippage in backtests |

---

## Testing cheatsheet

```bash
# Full suite, offline
DEMO_MODE=1 python -m pytest tests/ -q

# Just the new channels layer
DEMO_MODE=1 python -m pytest tests/test_channels.py -v

# Just the dashboard regression tests
DEMO_MODE=1 python -m pytest tests/test_web_api.py -v

# The MCP server round-trip
DEMO_MODE=1 python -m pytest tests/test_mcp_stdio.py -v

# One module in isolation
DEMO_MODE=1 python -m pytest tests/test_risk_gate.py -v

# Coverage (optional, requires pytest-cov)
DEMO_MODE=1 python -m pytest tests/ --cov=brain --cov=engine --cov=data
```

The expected baseline is **317 pass, 1 skip**. Any new feature must
maintain or increase this count.
