# 🧠 AI Trading Brain Anatomy Roadmap & Status Tracker

```
Progress: [████████████████████████████████████████] 100% (Phases P1–P6 Complete)
Tests:    259 Items (258 Passed, 1 Conditional Skip — 100% Pass Rate)
Status:   Production-Ready Institutional Desk & Autonomous Architecture
Note:     This repo consolidates Cloudslover/AI + cloudshome/AI (see MERGE_NOTES.md)
```

---

## 🏛️ System Architecture Overview

```
                          ┌──────────────────────────────────────────────┐
                          │            User & External Clients          │
                          │   CLI / Dashboard / MCP Client (Claude, etc) │
                          └──────────────────────┬───────────────────────┘
                                                 │
                                     ┌───────────┴───────────┐
                                     │   JSON-RPC MCP Server │
                                     │      mcp_server.py    │
                                     └───────────┬───────────┘
                                                 │
  ┌──────────────────────────────────────────────┼──────────────────────────────────────────────┐
  │                                              │                                              │
┌─▼──────────────────────────┐     ┌─────────────▼────────────┐     ┌──────────────────────────▼─┐
│     P1: RAG Library        │     │    P2: LLM Reasoning     │     │     P3: Autonomous Hands   │
│  brain/library.py          │     │    brain/brief.py        │     │     brain/agents.py        │
│  brain/ask.py              │     │    ai/llm_brain.py       │     │     agent_runs (DB)        │
│  Grounded Q&A + Citations  │     │    Morning Brief/Review  │     │     Brief / Watchdog / etc │
└─────────────┬──────────────┘     └─────────────┬────────────┘     └─────────────┬──────────────┘
              │                                  │                                │
              └──────────────────────────────────┼────────────────────────────────┘
                                                 │
                                   ┌─────────────▼────────────┐
                                   │   P5: Immune System      │
                                   │   brain/immune.py        │
                                   │   Staleness/Risk Alarms  │
                                   └─────────────┬────────────┘
                                                 │
                                   ┌─────────────▼────────────┐
                                   │   Risk Gate & Playbooks  │
                                   │   SQLite Learning Store  │
                                   └──────────────────────────┘
```

---

## 📊 Phase Matrix & Live Verification

| Phase | Layer | Implemented Modules | Capabilities & Proof | Status |
|---|---|---|---|:---:|
| **P1** | **RAG — Library** | `brain/library.py`<br>`brain/ask.py` | Grounded retrieval with strict source citations:<br>`ask "which setups have positive expectancy in ranging markets?"`<br>↳ *"Buy Pullback: bt n=120 exp=+0.88R (win 75%) — cited: backtest_results"* | ✅ Complete |
| **P2** | **LLM — Reasoning** | `brain/brief.py`<br>`ai/llm_brain.py` | Pre-market briefing + post-mortem reasoning:<br>`postreview <scan_id>`<br>↳ *"TP_HIT · 1.5R · MAE 30.0 · MFE 1200.0 · Followed rules: YES"* | ✅ Complete |
| **P3** | **Agents — Hands** | `brain/agents.py`<br>`data/database.py` (`agent_runs`) | Autonomous desk agents:<br>• `MorningBriefAgent`: BTC/ETH/GOLD posture + session windows<br>• `WatchdogAgent`: Paper trade monitoring & stale cleanup<br>• `PaperReviewerAgent`: Post-mortem aggregation<br>• `WeeklyReviewAgent`: Metrics & change detection | ✅ Complete |
| **P4** | **MCP — Nervous System** | `mcp_server.py` | Zero-dependency stdio JSON-RPC MCP server:<br>`initialize` ↔ `tools/list` ↔ `tools/call ask`<br>Enforced security: Read-only & analysis tools only (no order placement or approval bypass). | ✅ Complete |
| **P5** | **Immune System** | `brain/immune.py` | Real-time diagnostic alarms & staleness detection:<br>`health`<br>↳ Catches stale candle data (>2 days old), DB corruption, risk limit breaches, behavioral blocks (angry/tired/revenge/chasing). | ✅ Complete |
| **P6** | **Hidden Alpha & Variance** | `engine/hidden_alpha.py`<br>`engine/execution.py`<br>`engine/correlation.py`<br>`brain/analytics.py` | • Markov-smoothed HMM latent regimes (Bull/Bear/Range/Expansion)<br>• CVD order flow: absorption & exhaustion detection<br>• Bayesian fractional Kelly sizing (`NEGATIVE_EDGE_STAND_ASIDE`)<br>• 8D state fingerprint + historical similarity search<br>• Realistic spread/slippage execution model (`EXECUTION_MODEL=simple`)<br>• Monte Carlo equity + drawdown distribution (`hidden analytics mc`)<br>• Measured BTC/ETH/GOLD correlation matrix + ETH/BTC beta (`correlation`) | ✅ Complete |

---

## 💻 Complete CLI Command Reference

### Quantitative Alpha & Risk Variance
```bash
# Monte Carlo resampling of realized paper outcomes (terminal equity + drawdown):
python main.py hidden analytics mc --samples 2000

# MAE/MFE summary per setup (are stops too tight? targets unreachable?):
python main.py hidden analytics mae

# HMM latent regimes + CVD order flow + Bayesian Kelly + 8D fingerprint:
python main.py hidden chart_read BTC

# Measured rolling BTC/ETH/GOLD correlation matrix + ETH/BTC beta:
python main.py correlation
```

### RAG & Intelligence
```bash
# Ask questions grounded in backtests, playbooks, risk rules, and SMC concepts:
python main.py ask "which setups have positive expectancy in ranging markets?"
python main.py ask "what is the ETH playbook rule?"
python main.py ask "what are the daily and weekly loss limits?"
```

### Briefing & Post-Trade Reviews
```bash
# Generate cross-asset morning brief (BTC, ETH, GOLD):
python main.py brief

# Run post-trade review on a closed trade:
python main.py postreview <scan_id>
```

### Autonomous Desk Agents
```bash
# Run all agents or an individual agent:
python main.py agent all
python main.py agent morning
python main.py agent watchdog
python main.py agent paper-reviewer
python main.py agent weekly-review
```

### Immune Diagnostics & Health
```bash
# Run full system diagnostic check:
python main.py health
python main.py health --json
```

### Model Context Protocol (MCP) Server
```bash
# Start stdio MCP JSON-RPC server (connect via Claude Desktop or MCP Client):
python mcp_server.py
```

---

## 🔄 Repository Consolidation & Ownership

This repository is the **consolidated production build** of the same project
ecosystem, merged from both of the author's repositories:

1. [`https://github.com/Cloudslover/AI`](https://github.com/Cloudslover/AI) —
   engine + professional mode (hidden-alpha quant layer, execution model,
   analytics, risk gate).
2. [`https://github.com/cloudshome/AI`](https://github.com/cloudshome/AI) —
   the AI Anatomy layer (RAG library, ask, brief, agents, immune, MCP).

Canonical consolidated repo: [`https://github.com/Azimshawon/SKY`](https://github.com/Azimshawon/SKY).
The merge strategy, file-level provenance and verification results are in
`MERGE_NOTES.md`.  Both upstream repos remain as read-only history sources.

---

## 🚀 HOW WE CONTINUE — Durable Handoff Protocol

When continuing in a new session or machine:

1. **5-Minute Orientation Recipe**:
   ```bash
   # 1. Recreate virtual environment (.venv is excluded from persistent snapshots)
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt

   # 2. Verify all tests pass
   .venv/bin/pytest

   # 3. Check immune system
   .venv/bin/python main.py health
   ```

2. **Remaining Progression Ladder**:
   - **Step 1: Live Market Feed**: Connect Binance live API keys or run against live BTC/ETH/GOLD WebSocket/REST feed.
   - **Step 2: Collect 100–200 Paper Samples**: Run `python main.py paper --watch` in `PROGRESSION=simulator` mode to accumulate statistical sample size.
   - **Step 3: Self-Calibration**: Run `python main.py learn` to update proven setups from real paper-trade outcomes.
   - **Step 4: Transition to Micro**: Set `PROGRESSION=micro` in `.env` once setup expectancy is mathematically proven.
   - **Step 5: Dashboard Expansion**: Embed RAG chat panel and Agent activity log into `web/app.py`.

3. **Core Operating Rules**:
   - 🛡️ **Never bypass the human approval gate**: Machine proposes, Human approves, Paper-runner executes.
   - 📚 **Grounded answers only**: Every query response must carry explicit citations (`[cited: ...]`).
   - 🧪 **Test-driven integrity**: Keep all 171+ tests passing across all changes.

---

## 🛰️ Next Phases — Agent-Reach-Inspired Upgrade (P7–P9)

Adopting the **operational patterns** of
[`Panniantong/Agent-Reach`](https://github.com/Panniantong/Agent-Reach)
(70.5k★, MIT) — *not* its web-scraping surface — so any AI agent
(Claude, Cursor, Arena, MCP client) can discover, install, doctor, and
route commands through CryptoBrain.

| Phase | Theme | Deliverables | Status |
|---|---|---|:---:|
| **P7** | **Agent surface** | `SKILL.md` (≤ 250 lines) · `python main.py doctor` (alias of `health`) · `python main.py skill --install` · `docs/agent_install.md` | 🟡 Spec-only — see `ROADMAP_AGENT_REACH_UPGRADE.md` §2 |
| **P8** | **Source channels** | `brain/channels.py` ordered-backend router (CryptoDada/Discord/news/LLM) · `python main.py channels` · dashboard "Channels" panel | 🟡 Spec-only |
| **P9** | **Capability endpoints** | Extended MCP `tools/list` (13 read-only tools, deny list visible) · CI wheel-gate · `desk_status()` advisory | 🟡 Spec-only |

**Out of scope (deliberate):** web scraping, social-platform logins,
cookie extraction, audio transcription, third-party CLIs (`gh`,
`mcporter`, `twitter-cli`, `rdt-cli`, `bili-cli`, `OpenCLI`,
`ffmpeg`). CryptoBrain's universe is exchange market data + private
CryptoDada + private Discord + RSS news. The 8 social-platform
cookie formats Agent-Reach manages are *never used* by a trading
engine.

**Invariant preserved in every phase:** the engine can never place a
real exchange order. Deny list enforced at the top of
`mcp_server.handle_tool_call()`; the human-approval gate remains
between the machine and any action.

**Full planning document:** [`ROADMAP_AGENT_REACH_UPGRADE.md`](./ROADMAP_AGENT_REACH_UPGRADE.md)
— includes honest alignment check, per-phase risk + rollback,
definition-of-done per phase, and the D1–D5 decision list to
confirm before coding starts.
