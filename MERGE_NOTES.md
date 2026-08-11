# 🔀 Merge Notes — Consolidated Production Build

**Date:** 2026-08-10
**Consolidated repo:** [`Azimshawon/SKY`](https://github.com/Azimshawon/SKY) (this repository)
**Sources merged:**

| Source | HEAD at merge | Role |
|---|---|---|
| [`Cloudslover/AI`](https://github.com/Cloudslover/AI) | `ea50e54` (`main`, PR #4) | **Base** — newest engine + professional/quant layer |
| [`cloudshome/AI`](https://github.com/cloudshome/AI) | `ba7a35c` (`main`, PR #9) | **Grafted** — AI anatomy suite + zero-dep MCP server |

Both projects were verified clean, offline-capable, and fully covered by
tests before merging.  The result passes **259 test items (258 passed, 1
conditional skip) 100% offline** (`DEMO_MODE=1 python -m pytest tests/ -q`).

---

## 1. What each source contributed

### Base — Cloudslover/AI (kept whole)
- Hidden-alpha quant layer (`engine/hidden_alpha.py`): Markov-smoothed latent
  regimes, CVD order flow (absorption/exhaustion), Bayesian fractional Kelly,
  8D state fingerprint + historical similarity search.
- Realistic execution model (`engine/execution.py`, `EXECUTION_MODEL=simple`)
  wired into the walk-forward backtester.
- Risk/execution analytics (`brain/analytics.py`): MAE/MFE summaries and
  Monte Carlo equity/drawdown resampling of the real paper book.
- Enforced risk gate with **Kelly advisory** (`brain/risk_gate.py`),
  institutional-grade trading intelligence (`brain/trading_intelligence.py`),
  dashboard panels (Kelly advisory, MAE/MFE columns, regime badges).

### Grafted — cloudshome/AI
- `brain/library.py` + `brain/ask.py` — RAG knowledge index + grounded Q&A
  with strict citations.
- `brain/brief.py` — cross-asset morning brief + post-trade reviews with
  MAE/MFE + rule-compliance headline.
- `brain/agents.py` — autonomous desk agents (morning brief, watchdog,
  paper reviewer, weekly review), audit-logged.
- `brain/immune.py` — system diagnostics (staleness, DB integrity, risk gates,
  behavioral flags, calibration).
- `mcp_server.py` (**zero-dependency** root MCP server, newline JSON-RPC 2.0).
- `AI_ANATOMY_ROADMAP.md` — architecture/status tracker (paths updated).

## 2. File-level decisions on shared modules

| File | Kept | Why |
|---|---|---|
| `ai/llm_brain.py` | cloudshome | adds `complete()` (needed by the RAG LLM path) |
| `brain/metrics.py` | cloudshome | superset: current streaks, rolling-window fallback, `compute_business_metrics` alias (used by `brain/agents.py`); drawdown read from the risk gate |
| `brain/risk_gate.py` | cloudslover + graft | Kelly advisory retained; grafted `"open"`/`"progression"` keys + `evaluate_risk_gate()` alias so the anatomy suite's interface is satisfied |
| `data/database.py` | cloudslover + graft | cloudslover schema (agent-ready indexes etc.) + grafted `agent_runs` table, `record_agent_run()`, `latest_agent_runs()` |
| `engine/hidden_alpha.py` | cloudslover | 3× deeper (true Markov smoothing, similarity search) |
| `brain/trading_intelligence.py`, `main.py`, `web/app.py`, `data/backtester.py`, `brain/agent.py`, `brain/full_pipeline.py`, `config.py`, `tests/test_hidden_alpha.py` | cloudslover | strict supersets of the cloudshome variants |

## 3. New in this consolidated build

- `engine/correlation.py` + `python main.py correlation` — measured rolling
  BTC/ETH/GOLD correlation matrix and ETH/BTC beta, with an explicit check of
  the static "BTC+ETH = one bucket" portfolio rule.  Read-only analytics with
  honest timestamp-vs-positional alignment labelling (DEMO-mode safe).
- CLI parity with `AI_ANATOMY_ROADMAP.md`: top-level `ask` (RAG library with
  citations), `postreview <scan_id>`, and `agent watchdog | paper-reviewer |
  weekly-review` (autonomous agents, audit-logged to `agent_runs`).
- `tests/test_correlation.py`, `tests/test_mcp_stdio.py` (root MCP server:
  handshake, tool permission map, trader-state round-trip, health check),
  `tests/test_web_api.py` — Flask endpoint regression tests; caught and fixed
  a real production bug present in BOTH sources: `/api/scan` and
  `/api/intelligence` returned HTTP 500 ("Object of type bool is not JSON
  serializable") whenever numpy scalars from the quant layer leaked into the
  payload.  All engine endpoints now pass through `_sanitize_for_json`.
- `.env.example` documents `EXECUTION_MODEL` and `KELLY_MAX_RISK_PCT`.

## 4. Verification run (this build)

```
DEMO_MODE=1 python -m pytest tests/ -q
→ 258 passed, 1 skipped (SDK-already-installed fallback test), ~60s

python main.py health         # OK — sample feeds, DB, risk gate open, MCP ready
python main.py brief          # 3-asset desk briefing + narrative
python main.py agent all      # health + briefing + graduation gate
python main.py correlation    # measured matrix + bucket-rule confirmation
python main.py hidden ...     # chart_read / analytics mae / analytics mc
python main.py ask "..."      # grounded answers with citations
python mcp_server.py          # zero-dep stdio MCP handshake OK
```

---

### Safety statement (unchanged, enforced)

No module in this repository can place, route, or relay orders to any
exchange.  Execution requires an explicit human approval (CLI or dashboard)
and the enforced risk & discipline gate (`ENFORCE_RISK_LIMITS=true`,
progression ladder, behavioral flags).  All analytics (Kelly, correlation,
Monte Carlo, HMM regimes) are advisory-only.
