# 🛰️ Agent-Reach → CryptoBrain Upgrade Roadmap

**Date:** 2026-08-11
**Source inspiration:** [`Panniantong/Agent-Reach`](https://github.com/Panniantong/Agent-Reach) (canonical, v1.5.0, 70.5k★) — also mirrored at `Cloudslover/Agent-Reach`.
**Target repo:** `Azimshawon/SKY` (this repository, CryptoBrain v2.0.0).
**Status:** Review document — no code changes required to **plan**; this file
documents what *would* be built in P7–P9.

> **One-line purpose:** turn CryptoBrain from "a Python engine + dashboard
> that *one* user invokes" into "an installable **capability layer** that
> *any* AI agent (Claude, Cursor, Arena, MCP client) can discover, install,
> doctor, and route commands through", the way Agent-Reach does for
> Twitter/Reddit/YouTube/etc.

---

## 0. Why this upgrade

Agent-Reach solves a single problem: **AI agents have lots of web capability
options, no one tells them which one to use, and every platform has a
different setup story**. It answers with three things CryptoBrain does not
(yet) have:

| Agent-Reach pattern | What it does | CryptoBrain today | Gap |
|---|---|---|---|
| `SKILL.md` | One markdown file a coding agent reads to learn how to call your tool. | None. A coding agent pointed at SKY has to read `README.md` (42 KB) and guess. | **Largest single gap** — the README is for humans, the SKILL is for agents. |
| `doctor` / `install` / `configure` / `setup` / `skill` CLI | A non-mutating default ("just check"), with `--system` opt-in to actually change the system. | Has `health` (immune system, read-only ✅) and `mcp` (server, run-only ✅). No `install`, `configure`, `setup`, `skill`, `doctor`. | A uniform install/configure/doctor flow on the 3 data sources (CryptoDada/Discord/news) would make the engine reachable by agents. |
| **Ordered backend candidates with fallbacks** | First backend = preferred; doctor surfaces which one is *actually* serving. Sources never block the agent. | `data/sources/cryptodada_website.py` and `discord_reader.py` have a `mode` switch but no ordered fallback chain. `news.py` has no fallback at all. | Add a `channels.py` router that tries primary → fallback → returns whatever worked. |

Agent-Reach is **~370 commits, 275 tests, MIT, 15 platforms, zero data sent
to a central service** — i.e., the operational discipline and "trust the
local config" stance is a near-perfect match for CryptoBrain's
"machine proposes, human approves, never sends exchange orders" stance.

It is *not* a copy. CryptoBrain is a quant engine + dashboard, not a
web-reading router. What we adopt are the **install/doctor/SKILL patterns**
and the **backend-candidate routing**. We do **not** adopt web scraping,
social platform logins, cookie extraction, or audio transcription —
CryptoBrain is offline-first and exchange-data only.

---

## 1. Honest alignment check (what is *already* there)

Before adding anything, the existing code already does ~40% of what
Agent-Reach does:

- **Read-only/never-mutates-stuff default** — `python main.py health` is
  read-only; `python main.py simulator --dry-run` exists; sources return
  empty lists when not configured. ✅ same as `agent-reach install` default.
- **MCP server with explicit tool permission map** — `mcp_server.py` only
  exposes `ask | tradestate | risk | health | brief | postreview`. No
  order-placement tool, no approval-bypass tool. ✅ stronger than most
  agent tools.
- **Immune system** — `brain/immune.py` already catches stale candle data,
  DB corruption, risk limit breaches, behavioral blocks
  (angry/tired/revenge/chasing), calibration drift. ✅ matches Agent-Reach's
  "doctor" intent.
- **Atomic config writes, no symlinks, no private-IP fetches** — the
  `.env`/DB writes already follow the same hygiene.
- **Per-feature test coverage** — 38 test modules, 171+ tests, CI on
  Python 3.10–3.13 + Windows.

The upgrade is therefore an **additive** layer, not a rewrite.

---

## 2. The three new phases (P7–P9)

### **P7 — Agent Surface (the SKILL + CLI)** — *smallest, biggest payoff*

Goal: a coding agent that has never seen CryptoBrain can install it, learn
its tool surface, and call it — by reading a single short markdown file.

**Deliverables:**

1. **`SKILL.md`** at repo root — a ≤ 200-line "how to use CryptoBrain
   from an AI agent" file. Mirrors Agent-Reach's pattern of giving the
   agent one URL to read, then letting the agent call the CLI. Contains:
   - the install line (`pip install -e .` or `git clone … && pip install -r
     requirements.txt`),
   - the readiness check (`python main.py doctor`),
   - the full tool surface mapped 1:1 to MCP `tools/list` (`scan`,
     `intelligence`, `brief`, `ask`, `postreview`, `health`, `risk`,
     `paper`, `agent morning`, `sources`, `state`, `correlation`,
     `hidden chart_read`, `hidden analytics mae|mc`),
   - the **read-only/never-trades** guarantee and a one-line citation
     pattern requirement (every answer must carry a citation),
   - the human-approval-gate statement (machine proposes, human approves,
     paper-runner executes — never places a real exchange order).
2. **`python main.py doctor`** — alias/wrapper around `health`, with
   text/json output and a clear "what works, what's missing, what to do"
   three-column report. Backed by `brain/channels.py` (P9).
3. **`python main.py skill --install | --uninstall | --print`** —
   print the SKILL.md to stdout (default), install it into the agent's
   skills directory (Claude Code `~/.claude/skills/`, Cursor
   `~/.cursor/skills/`, Arena root) under a deliberate `--system` flag.
   Default is inspect-only (mirrors Agent-Reach's safety posture).
4. **`docs/agent_install.md`** — the one-pager the agent is told to
   fetch: `https://raw.githubusercontent.com/Azimshawon/SKY/main/docs/agent_install.md`.

**Why this is the highest-leverage single change:** an MCP server only
helps clients that already know to look for it. A `SKILL.md` makes the
engine discoverable by every agent that reads a README. Agent-Reach got
~70k★ mainly by being "the thing the agent can read in one shot."

**Tests to add:** `tests/test_skill.py` (SKILL.md exists, contains the
expected tool names, ≤ 250 lines, contains the safety guarantee), and
`tests/test_main_cli.py` (new `doctor`/`skill` subcommands dispatch).

---

### **P8 — Source Channels (the backend router)** — *medium effort*

Goal: turn the three data sources (CryptoDada website, Discord, news) and
the optional LLM/Kelly/execution layers into a single `channels.py`
router, so the agent and the dashboard see a uniform "channel health /
active backend" picture and a primary → fallback chain.

**Deliverables:**

1. **`brain/channels.py`** — a small registry:
   - `Channel` dataclass: `name`, `backends: list[Backend]`, `configured()`,
     `probe()`, `active_backend`.
   - `Backend` dataclass: `name`, `module`, `probe_fn`, `fetch_fn`,
     `requires: list[str]`.
   - Per-source backend candidates, in preference order, with the existing
     modes as the first entry:
     - `cryptodada`: `[api, browser, none]` — `api` = hidden JSON probe
       (current `cryptodada_website.CryptoDadaConnector` with
       `mode="api"`), `browser` = Playwright login
       (`mode="browser"`), `none` = empty result (the current
       `auto`-mode fallback when no creds).
     - `discord`: `[webhook, bot_token, self_token, none]` — most
       conservative first. Currently the connector silently uses
       `DISCORD_TOKEN` if present; a router with explicit ordering
       stops accidental privileged-token use.
     - `news`: `[rss_parallel, rss_sequential, none]` — only
       failure-tolerance change, the current implementation is already
       threaded; the router formalises the three-tries-then-empty
       behaviour.
     - `llm`: `[groq, openai, gemini, rule_based]` — the four backends
       `ai/llm_brain.py` already cycles through; the router surfaces
       which one is actually active right now.
2. **`python main.py channels`** — list every channel with
   `configured | active | backends | prescription`. Pure read-only.
3. **`doctor` becomes a thin presentation layer over `channels.probe_all()`
   + `brain/immune.run_health_check()`.** Same data, agent-friendly
   layout.
4. **`web/app.py`** dashboard: add a "Channels" panel showing the
   per-source status, with a one-line "what to do to enable more"
   prescription per disabled channel.

**Why this matters:** Agent-Reach's biggest reliability lesson is that
"which()" (does the binary exist on PATH?) is **not** a working
integration test — it produced false-positives like
`bili-cli 可用` on broken shims, misleading xiaohongshu `连接失败`,
rdt `OSError` crashing the doctor. The fix there was to **really
execute** the upstream command and time it out. CryptoBrain's three
sources don't have the same blunt-instrument problem (no shims, no
network at all in the existing `data/sources/*`), but adding an
**ordered, timed, exception-isolated probe** is cheap insurance and
makes the engine more honest about which path is actually serving.

**Tests to add:** `tests/test_channels.py` (registry construction,
configured/active reporting, fallback ordering, exception isolation,
each of the three existing source modules' "off" state returns
"none" not "error").

**Things we are *not* copying from Agent-Reach here:**
- no `which()` checks (irrelevant — pure Python),
- no cookie extraction,
- no browser login (CryptoDada's Playwright path stays where it is;
  the router just enumerates the existing modes).

---

### **P9 — Capability Endpoints (the agent-facing execution)** — *largest*

Goal: make the engine *operable* by an agent end-to-end, not just
readable. The agent should be able to: ask a grounded question, get a
brief, run a scan, request a paper-trade lifecycle, ask for the
graduation gate verdict, and (always via human approval) record
approvals/rejections.

**Deliverables:**

1. **MCP `tools/list` extension** — add the read-only `channels`,
   `correlation`, `hidden.chart_read`, `hidden.analytics_mae`,
   `hidden.analytics_mc`, and the already-existing `ask | brief |
   postreview | health | risk | tradestate`. Keep the explicit deny
   list of `approve | reject | execute | close | place_order` (already
   enforced in `mcp_server.py`).
2. **`docs/agent_install.md`** — a one-pager an agent can read, exactly
   the Agent-Reach pattern: "tell your agent *this* and it will set
   itself up."
3. **`python main.py agent ask "am i ready for micro?"`** — already
   exists; document the **graduation gate** explicitly in the SKILL
   (PF ≥ 1.5, expectancy ≥ +0.50R, win rate > 55%, rule compliance ≥
   90%, ≥ 100 backtest + ≥ 20 paper per primary setup).
4. **`brain/agent.py`** — add a `desk_status()` that returns the
   current risk-gate open/closed status, today's P&L, the
   graduation-gate verdict, the next scheduled agent, and a
   "what would a professional do right now?" suggestion. Expose via
   MCP.
5. **Wheel gate** (Agent-Reach has this; SKY does not). Add a CI job
   that builds the package wheel, verifies no duplicate entries,
   installs it into a clean venv, and smoke-tests the CLI. Cheap to
   add with `pyproject.toml` + `build` step in `.github/workflows/`.

**Tests to add:**
- `tests/test_channels.py` (P8) extended with `doctor` presentation,
- `tests/test_skill.py` (P7) verifying the SKILL exposes the new
  tools,
- new `tests/test_skill_install.py` for the `skill --install` path
  using a tmpdir (no real `$HOME` mutation).

**Things we are *not* copying from Agent-Reach here:**
- no `setup --system` (CryptoBrain has no system-level mutation
  story — there is no `mcporter` to wire, no `gh` to auth, no
  `browser-cookie3` to install),
- no "ordered backend that is a binary" — the existing Python
  module is the backend,
- no cookie extraction, no audio transcription, no social platform
  logins (out of scope for a trading engine).

---

## 3. Phase-by-phase risk and rollback

| Phase | Risk to existing 100% pass rate | Rollback if it breaks |
|---|---|---|
| **P7** | Very low — `SKILL.md` is new; `doctor` is a wrapper around existing `health`; `skill` subcommand is additive. New tests are pure additions. | Delete `SKILL.md`; remove the 3 new `sub.add_parser` blocks; drop `tests/test_skill.py`. |
| **P8** | Low — `brain/channels.py` is a new module; the existing 3 source modules are imported unchanged; `doctor` continues to call `immune.run_health_check()`. | Delete `brain/channels.py`; revert `doctor` to a 5-line alias. |
| **P9** | Medium — MCP tool surface grows; must keep the "no order placement" deny list visible. | The deny list is enforced in `mcp_server.py` at the top of `handle_tool_call()`; tightening it is a one-line change. |

**Invariant maintained in every phase:** the engine can never place a
real exchange order. This is documented in `MERGE_NOTES.md` and
re-stated in `SKILL.md` and the deny list. Any phase that compromises
this is rejected.

---

## 4. Decisions to confirm before coding

Following the repo's own `PROFESSIONAL_PLAN_DECISIONS.md` "decision list"
style, here are the choices:

* **D1 — scope of P7**: `SKILL.md` + `doctor` + `skill` CLI + `docs/agent_install.md` **(recommended)**, or just `SKILL.md` only (cheapest)?
* **D2 — `doctor` name**: keep as `health` and add a `doctor` alias, or rename (the docs/Agent-Reach community expects `doctor`).
* **D3 — channels scope**: only the 3 data sources + LLM (`recommended`), or also wrap risk gate, calibrator, journal, etc. (broader)?
* **D4 — wheel-gate CI**: yes (matches Agent-Reach; catches duplicate-wheel bugs), or no (keep CI simple).
* **D5 — `docs/agent_install.md` URL exposure**: the file is the "one URL the agent fetches" — confirm it's OK to point to `raw.githubusercontent.com/Azimshawon/SKY/main/docs/agent_install.md`.

**No code has been changed.** Reply with D1=…D2=…D3=…D4=…D5=… (or
"all ★" for the recommended default) and coding starts.

---

## 5. What we explicitly are *not* copying (out-of-scope list)

Agent-Reach is, fundamentally, a **web-reading** tool. CryptoBrain is,
fundamentally, a **trading-signal** tool. The things in Agent-Reach that
CryptoBrain should not adopt:

- Web scraping of Twitter / Reddit / Bilibili / Xiaohongshu / Facebook
  / Instagram / LinkedIn / V2EX / Xueqiu / Xiaoyuzhou. Out of scope;
  CryptoBrain's universe is exchange market data + private CryptoDada
  membership + private Discord + RSS news.
- Audio transcription of podcasts/video. Out of scope; no audio source.
- Browser cookie extraction, cookie editing, third-party CLI
  orchestration (`gh`, `mcporter`, `bili-cli`, `twitter-cli`, `rdt-cli`,
  `OpenCLI`). CryptoBrain has zero of these dependencies.
- `agent-reach install --env local|server` distinction. CryptoBrain
  already runs identically in DEMO_MODE on a server and in dev.
- Sponsor / 6-language README matrix. Single-language repo is fine.

The upgrade is therefore small, surgical, and improves the
agent-discoverability surface — not the trading surface.

---

## 6. Definition of done (per phase)

**P7 done =**
- `SKILL.md` exists at repo root, ≤ 250 lines, contains the 14 tool
  names, the safety guarantee, and the citation pattern.
- `python main.py doctor` returns the channels + immune-system health,
  exit 0 on healthy.
- `python main.py skill --print` prints the SKILL.md to stdout.
- `python main.py skill --install` copies it into `~/.claude/skills/cryptobrain/SKILL.md`
  (no other path), only with `--system`, with a `--dry-run` preview.
- `python -m pytest` still ≥ 258 pass / 0 fail.
- `python main.py --help` shows the new subcommands.

**P8 done =**
- `brain/channels.py` exists, lists 4 channels × 3–4 backends each.
- `python main.py channels` prints a table (text + `--json`).
- `doctor` is implemented as a presentation layer over
  `channels.probe_all() + immune.run_health_check()`.
- `python -m pytest` still ≥ 260 pass / 0 fail.
- A new "Channels" panel appears in `web/app.py` and the dashboard
  renders without HTTP 500 on `/api/scan` or `/api/channels` (the
  `_sanitize_for_json` regression caught in MERGE_NOTES.md must
  remain fixed).

**P9 done =**
- MCP `tools/list` exposes 13 read-only tools; the deny list is
  visible in `mcp_server.py` and is tested.
- A new CI job `wheel-gate` builds the wheel, installs it in a clean
  venv, and runs `python -c "import cryptobrain"` + a CLI smoke test.
- `docs/agent_install.md` exists and is referenced from `SKILL.md`.
- `python -m pytest` still ≥ 268 pass / 0 fail.

---

## 7. Why not just fork Agent-Reach?

Because the problems are different. Agent-Reach's value is *channel
coverage* (15 platforms). CryptoBrain's value is *signal quality on
one asset class* (BTC/ETH/GOLD). Forking would graft a web scraper
onto a quant engine and bloat the dependency surface with
`browser-cookie3`, `playwright`, `yt-dlp`, `ffmpeg`, `mcporter`,
Twitter/RDT/Bili CLIs, and 8 social-platform cookie formats — all of
which are **never used** by a trading signal engine. The cost/benefit
of forking is bad; the cost/benefit of adopting its
*operational patterns* (SKILL, doctor, install/configure, ordered
backends) is excellent.

---

## 8. TL;DR

| | Today | After P7 | After P9 |
|---|---|---|---|
| Discoverable by an AI agent from cold | No (only the 42 KB README) | Yes (SKILL.md) | Yes (SKILL + install URL) |
| Self-diagnosing | `python main.py health` | `python main.py doctor` (alias + channels) | `doctor` + MCP `health` tool |
| Source routing with fallbacks | Manual mode-switch | Ordered `channels.py` | Same, with dashboard panel |
| CI wheel-gate | No | No | Yes |
| Test count | 258 | ≥ 260 | ≥ 268 |
| Net new dependencies | — | 0 | 0 |
| Out-of-scope cookie/CLI plumbing | 0 | 0 | 0 |
| "No exchange order placed" guarantee | Enforced | Enforced | Enforced |

The upgrade is the right size: small enough to ship in three PRs, big
enough to turn a private quant engine into a tool every AI agent can
find, install, and route commands through — the same way Agent-Reach
turned a pile of web-reader scripts into a 70k★ capability layer.
