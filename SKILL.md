---
name: cryptobrain
description: "AI trading brain for BTC, ETH, and XAUUSD/GOLD. Read-only signal engine, multi-source market context, and a strict human-approval gate. NEVER places exchange orders — machine proposes, human approves, paper-runner executes."
---

# CryptoBrain — AI Trading Brain

You are reading this because an operator wants you to **use** CryptoBrain
to assist their BTC/ETH/GOLD trading decisions. CryptoBrain is a
quant-grade signal engine plus a Model Context Protocol (MCP) server
plus a web dashboard. This file tells you what you can call, what you
**must not** call, and how to behave.

> **One rule above all:** you never place a real exchange order. You
> read data, run scans, ask grounded questions, request briefings, and
> hand any action back to the human. If the operator asks you to trade
> autonomously, refuse and explain that CryptoBrain is
> research + decision-support, never execution.

## When to use this

| Operator says | You do |
|---|---|
| "Is BTC bullish right now?" | `python main.py brief --symbols BTCUSDT` (or `agent morning`) |
| "What setups have positive expectancy in ranging markets?" | `python main.py ask "which setups have positive expectancy in ranging markets?"` |
| "Run a 15-minute scan on ETH" | `python main.py scan --symbol ETHUSDT --tf 15m --json` |
| "Give me the desk report" | `python main.py intelligence --symbol BTCUSDT --tf 15m` |
| "Is the risk gate open? Am I cleared to trade?" | `python main.py risk` and `python main.py health` |
| "Read the latest crypto news" | `python main.py sources` |
| "Review this closed trade" | `python main.py postreview <scan_id>` |
| "Am I ready for live micro-trading?" | `python main.py agent ask "am i ready for micro?"` |
| "Why did the engine say BUY?" | `python main.py coach <scan_id>` |

## Install (one-time)

Tell the operator to run:

```bash
git clone https://github.com/Azimshawon/SKY.git
cd SKY
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then edit — everything is optional, the engine works offline with DEMO_MODE=1
```

For deeper setup (LLM, Discord, CryptoDada credentials) see
`docs/agent_install.md`.

## Readiness check

Before doing anything else:

```bash
python main.py doctor         # text report
python main.py doctor --json  # machine-readable
python main.py health         # legacy alias for doctor
```

A healthy engine reports OK on: data feeds, database, risk gate, MCP
ready, no behavioral flags, no calibration drift.

## The full tool surface

Every tool below is **read-only / research-only**. There is no tool
that places an order, approves a signal on the operator's behalf, or
bypasses the risk gate. The deny list is enforced at the top of
`mcp_server.py` — the engine physically cannot be asked to trade.

| Tool | CLI command | MCP name | What you get |
|---|---|---|---|
| Scan | `python main.py scan --symbol BTCUSDT --tf 15m` | (use `intelligence` for the desk variant) | Raw signal + plans (JSON) |
| **Desk report** | `python main.py intelligence --symbol BTCUSDT` | `intelligence` | Institutional desk view: strict NO-TRADE filter, scenarios, risk, IF/THEN logic |
| Watch | `python main.py watch --symbol BTC --interval 120` | — | Continuous loop (operator runs in their terminal) |
| **Brief** | `python main.py brief` | `brief` | Cross-asset morning brief: BTC, ETH, GOLD |
| **Ask** | `python main.py ask "..."` | `ask` | Grounded RAG answer with **required citations** (you must keep `[cited: ...]` in any reply that paraphrases the engine) |
| Post-review | `python main.py postreview <scan_id>` | `postreview` | Closed-trade post-mortem: R, MAE/MFE, rule compliance |
| Health | `python main.py health` / `python main.py doctor` | `health` | Immune-system diagnostic: stale data, DB integrity, risk limits, behavioral flags |
| Risk gate | `python main.py risk` | `risk` | Open/closed status, daily/weekly P&L, progression ladder |
| Trader state | `python main.py tradestate` | `tradestate` | Behavioral flags: angry/tired/revenge/chasing — operator-controlled |
| Paper watch | `python main.py paper --watch` | — | Live-market paper-trade monitor (does **not** touch any exchange) |
| Sources | `python main.py sources` | — | CryptoDada + Discord + RSS news snapshot |
| Stats | `python main.py stats` | — | What the engine has learned from graded backtests + paper trades |
| Learn | `python main.py learn` | — | Recompute self-improvement calibration (advisory) |
| Coach | `python main.py coach <scan_id>` | — | Why the engine said what it said; teaching mode |
| Agent ask | `python main.py agent ask "am i ready for micro?"` | — | Natural-language desk query (graduation gate) |
| Agent all | `python main.py agent all` | — | One desk run: health + brief + graduation |
| Channels | `python main.py channels` | `channels` | Ordered-backend registry (cryptodada / discord / news / llm) — same data the dashboard "CHANNELS" card shows |
| Correlation | `python main.py correlation` | `correlation` | BTC/ETH/GOLD correlation matrix + ETH/BTC beta |
| Hidden | `python main.py hidden chart_read BTCUSDT` | `hidden_chart_read` | HMM regime + CVD order flow + Kelly (advisory) |
| Hidden | `python main.py hidden analytics mae` | `hidden_analytics_mae` | MAE/MFE summary per setup |
| Hidden | `python main.py hidden analytics mc --samples 2000` | `hidden_analytics_mc` | Monte Carlo equity / drawdown distribution |

## How to answer with CryptoBrain

1. **Prefer the desk report over the raw scan.** The desk report
   (`intelligence`) is the only output the operator should act on
   directly. Raw scans are research.
2. **Always carry the citation.** When you paraphrase an `ask`
   answer, keep the `[cited: backtest_results]` style marker so the
   operator can verify the grounding.
3. **State the confidence and the time horizon.** Every signal carries
   `confidence` (0–100) and `timeframe`. Don't drop these.
4. **Respect the risk gate.** If `python main.py risk` reports
   `closed: daily loss limit reached` or `weekly stop reached`, you
   must NOT propose any new entry. The engine's gate is the gate.
5. **Respect behavioral flags.** If `tradestate` shows
   `angry: true` or `tired: true` or `revenge: true` or `chasing: true`,
   recommend NO TRADE regardless of what the scan says.
6. **Honour the progression ladder.** `PROGRESSION=student` /
   `researcher` blocks any approval (no live trading). `simulator` is
   paper-only. `micro` is the first real-money tier (0.5% risk per
   trade). Promotion requires the graduation gate: PF ≥ 1.5,
   expectancy ≥ +0.50R, win rate > 55%, rule compliance ≥ 90%, ≥ 100
   backtest + ≥ 20 paper per primary setup.

## How **not** to behave

- ❌ Do not try to call any `approve | reject | execute | close` tool —
  they are not exposed via MCP by design. The human owns those.
- ❌ Do not invent a "place_order" tool. There is none, and there
  never will be one in this engine.
- ❌ Do not bypass the risk gate by reading the DB and writing to it
  directly. The gate is not in the DB; it is in `brain/risk_gate.py`
  and is consulted on every approval.
- ❌ Do not present a raw scan as a recommendation. Use
  `intelligence` (desk report) instead, or use `ask` to get a
  grounded narrative.
- ❌ Do not change `PROGRESSION` to `micro`/`consistent`/`scale` on
  the operator's behalf. It is a human-promotion decision gated on
  the graduation statistics.

## Behavioural example

Operator: *"ETH looks weak — should I short it?"*

```bash
python main.py intelligence --symbol ETHUSDT --tf 15m --json
python main.py risk
python main.py tradestate
python main.py agent ask "is shorting ETH aligned with the current BTC regime and the risk gate?"
```

Then **summarise** the desk report (not the raw scan), include
`[cited: …]` for any `ask` paraphrase, and state the action exactly as
the engine stated it: `BUY` / `SELL` / `NO TRADE` / `PENDING_REVIEW`
(awaiting human approval).

## Reference

- README: <https://github.com/Azimshawon/SKY>
- Install one-pager: `docs/agent_install.md` in this repo
- Architecture: `AI_ANATOMY_ROADMAP.md`
- Roadmap: `ROADMAP_AGENT_REACH_UPGRADE.md`
- Inspired by: [`Panniantong/Agent-Reach`](https://github.com/Panniantong/Agent-Reach) —
  the operational patterns (SKILL / doctor / install) are adopted;
  the web-scraping surface is not.
