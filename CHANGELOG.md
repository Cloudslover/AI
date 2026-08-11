# Changelog

All notable changes to **CryptoBrain / SKY** are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> **Note:** this changelog was created on 2026-08-11. Pre-v2.0.0 history
> lives in the `MERGE_NOTES.md` provenance document. `config.VERSION` is the
> current version source of truth; this file documents what shipped.

---

## [Unreleased]

### Planned
- Version the eventual removal of the legacy top-level `signal` adapter.
- Add out-of-sample folds and multiple-comparison controls before expanding
  the scoring meta-learner beyond its small advisory grid.

---

## [2.1.0] — 2026-08-11 · branch `arena/019ff0d9-ai`

### Changed — architectural boundary redesign
- Synchronized canonical [`Azimshawon/SKY`](https://github.com/Azimshawon/SKY)
  `main` at `4216448` into the current CryptoBrain branch.
- Added `engine/pipeline.py`: deterministic functional core with immutable
  feature/score/plan/output stage records; `engine/signal_engine.py` is now a
  compatibility facade.
- Added `brain/decision_service.py`: explicit `watch_items`,
  `active_candidate`, and risk-gated `desk_verdict`. Conditional confidence no
  longer masquerades as an immediate signal.
- Added `engine/policy.py`: setup-family authorization occurs after all plans
  are generated and calibrated, preserving research visibility.
- MTF now carries 1W/1D/4H/1H order blocks and FVGs into execution plans.
- Added `brain/context_providers.py` and `context_completeness`; CryptoDada and
  Discord are optional, exception-isolated enrichers.
- Calibration now stores trigger/fill probability separately from expectancy;
  fixed persistence of the existing `filtered` flag.
- Added `brain/meta_learner.py` and `python main.py meta-learn`: offline
  scoring-profile advice with mandatory manual activation through
  `SCORING_WEIGHTS_JSON`.
- Added BTC/ETH/GOLD full-desk acceptance snapshots, an activation-ready
  scheduled-workflow template under `docs/workflows/`, and ADR-0001. The Arena
  GitHub App cannot write `.github/workflows/`, so activation remains manual.

### Safety
- No exchange-order path was added.
- Human approval, progression controls, and risk gates remain mandatory.
- Meta-learning never mutates active configuration.

---

## Legacy SKY plan before 2.1.0 (superseded by current `TODO.md`)

### Previously planned
- TODO-3: CI wheel-gate job in `.github/workflows/ci.yml`.
- TODO-4: `brain/agent.desk_status()` advisory.
- TODO-6: Answer D1–D5 decision list in
  `ROADMAP_AGENT_REACH_UPGRADE.md` §4.

---

## [2.0.4] — 2026-08-11 · branch `arena/019ff045-sky`

### Added — PR #5 conflict resolution (this session)

PR #5 (`feat(agent-surface): P7+P8+P9 — SKILL, channels, MCP
capability endpoints`) was `CONFLICTING` because `main` was
independently updated (commit `0940452` modern-dashboard) while the
P7/P8/P9 work was in flight. This session resolves the conflicts.

**main.py** (4 conflict hunks):
- Kept BOTH sides' additions: branch's `cmd_doctor / channels /
  skill` AND main's `cmd_preflight` + the preflight gate in
  `cmd_paper --watch`.
- Default banner updated to list all new commands.

**web/app.py** (3 conflict hunks):
- Took main's full modern tabbed dashboard wholesale (the branch's
  old `html += card(...)` block was obsolete; main's tabbed
  architecture IS the design).
- Re-applied the branch's `loadChannels()` JS function.
- Re-added the `/api/channels` and `/api/doctor` Flask endpoints
  (main did not have them — they were a P8 deliverable on the
  branch).
- Added the CHANNELS card to the system tab.
- Added a 5-minute diagnostic auto-refresh (channels + mcp),
  distinct from the existing 30s scan tick.

### Test count
- 285 → **306 pass / 1 skip** (+21 from main's modern-dashboard work
  including `tests/test_preflight.py`).
- 0 regressions on the branch side.

### Live verification
After resolving the conflicts, started `python main.py web` and
hit every new endpoint via curl:
- `/` → 200
- `/api/health` → 200
- `/api/channels` → 200 (returns proper JSON with 4 channels)
- `/api/doctor` → 200
- `/api/mcp` → 200

### PR status
PR #5 went from `CONFLICTING` to `MERGEABLE`. Reviewer can now merge.

### Pushed
- Branch `arena/019ff045-sky` → `origin`. No new PR (PR #5 already
  exists).

---

## [2.0.3] — 2026-08-11 · branch `arena/019ff045-sky`

### Added — P9 MCP capability endpoints (TODO-2 complete)

`mcp_server.py` (the zero-dep stdio JSON-RPC server) now exposes 5
new read-only tools, bringing the total from 6 to 11:

| Tool | Wraps | What you get |
|---|---|---|
| `channels` | `brain.channels.list_channels(as_json=True)` | Ordered-backend registry (cryptodada / discord / news / llm) — same data the dashboard "CHANNELS" card and `python main.py channels --json` return |
| `correlation` | `engine.correlation.fetch_report` | Measured BTC/ETH/GOLD rolling correlation matrix + ETH/BTC beta |
| `hidden_chart_read` | `engine.hidden_alpha.hidden_alpha_report` | HMM latent regime + CVD order flow + Bayesian Kelly for one symbol |
| `hidden_analytics_mae` | `brain.analytics.mae_mfe_summary` | MAE/MFE summary per setup from the paper-trade DB |
| `hidden_analytics_mc` | `brain.analytics.monte_carlo_equity` | Monte Carlo equity + drawdown distribution from realized paper outcomes |

### Changed
- `mcp_server.py:SERVER_VERSION` bumped `1.0.0 → 1.1.0` (capability
  surface expansion).
- `mcp_server.py` docstring now explicitly names the deny list
  (`approve | reject | execute | close | place_order | sign |
  withdraw | transfer`) so the invariant is self-documenting.
- `SKILL.md` tool table updated: 5 rows that previously had `—` in
  the MCP column now list the new tool name.
- `tests/test_mcp_stdio.py:ROOT_TOOLS` extended to 11 names.

### Tests
- 6 new tests in `tests/test_mcp_stdio.py`:
  - `test_root_mcp_channels_tool`
  - `test_root_mcp_correlation_tool`
  - `test_root_mcp_hidden_chart_read_tool`
  - `test_root_mcp_hidden_analytics_mae_tool`
  - `test_root_mcp_hidden_analytics_mc_tool`
  - `test_root_mcp_deny_list_still_enforced` — checks 8 forbidden
    names both in `tools/list` AND by direct call
- Test count: 289 → **295 pass / 1 skip** (0 regressions).

### Self-reflection (in-session)
- The previous session's end-of-session `SESSION_STATE.md` update
  recorded new SHAs but left two pre-existing inconsistencies
  unrepaired (a `<new-sha>` placeholder and a stale "P8 dashboard
  panel pending" status line). The refined rule: when updating
  `SESSION_STATE.md`, do a full-document reconciliation pass — not
  just append new sections.
- TODO-2 followed the **library-function-not-subprocess** design
  pattern. The existing tools (`ask`, `risk`, `health`, etc.) all
  call library functions directly, not `cmd_*` functions via
  subprocess; the new tools follow the same pattern. This keeps the
  surface consistent and avoids the overhead of a process per call.

### Pushed
- Branch `arena/019ff045-sky` → `origin`. No PR opened.

---

## [2.0.2] — 2026-08-11 · branch `arena/019ff045-sky`

### Added — P8 dashboard "Channels" panel (TODO-1 complete)
- **`GET /api/channels`** in `web/app.py` — JSON endpoint wrapping
  `brain.channels.probe_all()`. Exception-isolated (a broken probe
  in one channel cannot crash the endpoint); goes through
  `_sanitize_for_json` to preserve the numpy-leak fix from
  `MERGE_NOTES.md`. Returns `{channels: {name: {status, active,
  backends: [...]}, ...}}`.
- **`GET /api/doctor`** — JSON-wrapped text report. Same output
  as `python main.py doctor`; the dashboard panel could call it
  but uses `/api/channels` directly for the structured view.
- **Dashboard HTML: new "CHANNELS — ordered-backend registry (P8)"
  full-width card.** Renders a status pill row (one per channel:
  `cryptodada / discord / news / llm`) plus a per-channel table
  with `configured / ok / detail / (active)` columns. Visual design
  matches the existing `MCP SERVER` card.
- **JS: `loadChannels()`** — fetches `/api/channels`, renders the
  card. Wired into the post-render init block.
- **Separate 5-minute auto-refresh for diagnostic panels** (channels
  + MCP), distinct from the 30s signal-scan tick. Channels are
  diagnostic state, not signal state, so a slower cadence is
  correct.
- **4 new tests** in `tests/test_web_api.py`:
  `test_channels_endpoint_returns_registry`,
  `test_channels_endpoint_is_json_serializable_under_numpy_leak`,
  `test_channels_endpoint_isolates_probe_exceptions`,
  `test_doctor_endpoint_returns_text_report`.

### Test count
- 285 → **289 pass / 1 skip** (0 regressions).

### Self-reflection (in-session)
This session caught a stale handoff: the previous session's
`SESSION_STATE.md` said "Last commit: b0fe82f" but the actual HEAD
was already `498d753` (the docs commit). The handoff memory went
stale inside the same chat. The lesson: **update SESSION_STATE.md
at the START of every session, not just at the end.** This entry
is the first to be documented with the rule.

### Pushed
- Branch `arena/019ff045-sky` → `origin`. No PR opened.

---

## [2.0.1] — 2026-08-11 · branch `arena/019ff045-sky`

### Added — Agent-Reach-inspired surface (P7 + P8 code layer)
- **`SKILL.md`** at repo root — the 155-line agent-facing skill file
  that any AI agent (Claude, Cursor, Arena, MCP client) can read to
  learn the tool surface, the safety contract, and the citation
  pattern. Mirrors the Agent-Reach pattern of "one URL the agent
  reads."
- **`ROADMAP_AGENT_REACH_UPGRADE.md`** — the P7/P8/P9 plan with
  per-phase risk + rollback + definition-of-done + D1–D5 decision
  list. Honest about what is *adopted* (operational patterns) and
  what is *not adopted* (web scraping, social logins, audio
  transcription, third-party CLIs).
- **`docs/agent_install.md`** — the one-pager an agent fetches when
  told "install CryptoBrain."
- **`brain/channels.py`** — the ordered-backend router. Four channels
  (`cryptodada`, `discord`, `news`, `llm`), each with a primary →
  fallback chain ending in an always-available tail (`none` or
  `rule_based`). Probes are exception-isolated so a broken channel
  can't crash `doctor`.
- **`python main.py doctor`** — the non-mutating readiness report
  (channels layer + immune system).
- **`python main.py channels`** — compact per-source backend
  registry listing.
- **`python main.py skill`** — print / install / uninstall the
  `SKILL.md` (default inspect-only; `--system` required for
  `$HOME` writes).
- **`tests/test_channels.py`** — 27 new tests covering registry
  shape, probe isolation, fallback ordering, each source's "off"
  state, SKILL.md content contract, every new CLI subcommand
  including the `--install` / `--system` / `--dry-run` safety
  postures.

### Changed
- **`main.py`** — three new subcommands (`cmd_doctor`, `cmd_channels`,
  `cmd_skill`); default banner updated. +184 lines, additive only.
- **`AI_ANATOMY_ROADMAP.md`** — short P7/P8/P9 summary table linked
  to the new planning document. +34 lines, additive only.

### Test count
- 258 pass / 1 skip → **285 pass / 1 skip**. 0 regressions.

### Pushed
- Branch `arena/019ff045-sky` → `origin`. No PR opened (user
  explicitly chose Option B: branch only).

### Notes
- Inspired by [`Panniantong/Agent-Reach`](https://github.com/Panniantong/Agent-Reach)
  (v1.5.0, 70.5k★, MIT). Operational patterns adopted; web-scraping
  surface explicitly not adopted per
  `ROADMAP_AGENT_REACH_UPGRADE.md` §5.

---

## [2.0.0] — 2026-08-10 · commits `35ad758…99ace0d`

### Added — Consolidated production build (merged Cloudslover/AI + cloudshome/AI)
- **Engine layer (`Cloudslover/AI` @ `ea50e54`):**
  - Hidden-alpha quant: Markov-smoothed HMM latent regimes
    (Bull/Bear/Range/Expansion).
  - CVD order flow: absorption & exhaustion detection.
  - Bayesian fractional Kelly sizing (`NEGATIVE_EDGE_STAND_ASIDE`).
  - 8D state fingerprint + historical similarity search.
  - Realistic spread/slippage execution model (`EXECUTION_MODEL=simple`).
  - Monte Carlo equity + drawdown distribution.
- **Anatomy layer (`cloudshome/AI` @ `ba7a35c`):**
  - `brain/library.py` + `brain/ask.py` — RAG knowledge index +
    grounded Q&A with strict citations.
  - `brain/brief.py` — cross-asset morning brief + post-trade
    reviews (MAE/MFE + rule-compliance headline).
  - `brain/agents.py` — autonomous desk agents (morning brief,
    watchdog, paper reviewer, weekly review), audit-logged to
    `agent_runs`.
  - `brain/immune.py` — system diagnostics (staleness, DB integrity,
    risk gates, behavioral flags, calibration drift).
  - `mcp_server.py` — **zero-dependency** stdio JSON-RPC 2.0
    server.
  - `AI_ANATOMY_ROADMAP.md` — architecture/status tracker.
- **`engine/correlation.py`** + `python main.py correlation` —
  measured rolling BTC/ETH/GOLD correlation matrix and ETH/BTC
  beta, with explicit check of the static "BTC+ETH = one bucket"
  portfolio rule.
- **CLI parity with `AI_ANATOMY_ROADMAP.md`:** top-level `ask` (RAG
  library with citations), `postreview <scan_id>`, and
  `agent watchdog | paper-reviewer | weekly-review` (autonomous
  agents, audit-logged).
- **Tests:** 38 test modules. `tests/test_correlation.py`,
  `tests/test_mcp_stdio.py` (root MCP server: handshake, tool
  permission map, trader-state round-trip, health check),
  `tests/test_web_api.py` — Flask endpoint regression tests.

### Changed
- **Grafted modules:** `ai/llm_brain.py`, `brain/metrics.py`,
  `brain/risk_gate.py`, `data/database.py`. See `MERGE_NOTES.md` §2
  for the file-level decisions.
- **Production bug fix:** `/api/scan` and `/api/intelligence`
  returned HTTP 500 ("Object of type bool is not JSON serializable")
  whenever numpy scalars from the quant layer leaked into the
  payload. All engine endpoints now pass through `_sanitize_for_json`.

### Test count
- Pre-merge: 171 / 258 / 0 across the two sources (per source READMEs).
- Post-merge: **258 pass, 1 skip, 100% offline** (`DEMO_MODE=1
  python -m pytest tests/ -q`).

### Pushed
- Branches `arena/019febaf-sky` and `arena/019fefc9-sky` → `main`
  via PRs #1–#4 (all merged). The CI workflow file was renamed to
  `.github/workflows/ci.yml` (commit `8b16923`) to activate it —
  but see TODO-7 for the manual activation step.

### Notes
- Canonical consolidated repo:
  [`https://github.com/Azimshawon/SKY`](https://github.com/Azimshawon/SKY).
- Both upstream repos remain as read-only history sources.

---

## Pre-2.0.0 history

The pre-2.0.0 history lives in the two source repositories:

- [`Cloudslover/AI`](https://github.com/Cloudslover/AI) — engine +
  professional mode (hidden-alpha quant layer, execution model,
  analytics, risk gate).
- [`cloudshome/AI`](https://github.com/cloudshome/AI) — AI anatomy
  layer (RAG library, ask, brief, agents, immune, MCP).

File-level provenance of the merge is in
[`MERGE_NOTES.md`](./MERGE_NOTES.md).

---

## Versioning policy

- **MAJOR** bump for breaking changes to the engine JSON contract
  (`output/signal_schema.py`) or the MCP `tools/list` interface.
- **MINOR** bump for additive, backwards-compatible features (new
  CLI subcommands, new brain modules, new MCP tools, new
  dashboard panels).
- **PATCH** bump for bug fixes, test additions, documentation,
  refactors with no API change.

The current `pyproject.toml` (when added — see TODO-3) will be the
source of truth for the version number; this changelog is the
source of truth for *what* shipped.
