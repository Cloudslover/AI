# Agent Install — CryptoBrain

> If you are an AI agent that has been handed this URL, you are being
> asked to **install and use CryptoBrain** for the operator. The full
> behaviour contract is in [`../SKILL.md`](../SKILL.md). This file is
> the install guide only.

## 1. Clone and install

```bash
git clone https://github.com/Azimshawon/SKY.git
cd SKY
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

## 2. Verify readiness (read-only, never mutates the system)

```bash
python main.py doctor         # text report
python main.py doctor --json  # machine-readable for your tooling
python main.py health         # equivalent, legacy name
```

A healthy install reports `OK` on: data feeds, database, risk gate, MCP
ready, no behavioural flags, no calibration drift.

## 3. Optional — opt-in to live data and credentials

Everything in `.env.example` is opt-in. The engine works offline with
`DEMO_MODE=1`. If the operator wants live Binance data, LLM
narratives, Discord alerts, or CryptoDada website scraping, edit
`.env` accordingly. **No system-level change happens without an
explicit value in `.env`.**

## 4. First scan (read-only)

```bash
python main.py scan --symbol BTCUSDT --tf 15m --json
python main.py brief
python main.py ask "which setups have positive expectancy in ranging markets?"
```

## 5. Read the SKILL

Before you call any tool, read [`../SKILL.md`](../SKILL.md). It defines
the full read-only tool surface, the deny list, the citation pattern,
and the progression ladder (student → researcher → simulator → micro
→ consistent → scale).

## 6. What you must never do

- Never place, route, or relay an order to any exchange. There is no
  such tool in CryptoBrain and there never will be.
- Never bypass the human-approval gate. The gate is enforced in
  `brain/risk_gate.py` and consulted on every approval.
- Never change `PROGRESSION` to a live tier on the operator's behalf.
  It is a human-promotion decision gated on the graduation
  statistics.

## 7. Optional — register the SKILL with your agent runtime

If your runtime supports skill discovery (Claude Code, Cursor, Arena),
point it at `SKILL.md` in the cloned repo, or:

```bash
python main.py skill --print           # show the SKILL on stdout
python main.py skill --install --system  # copy to ~/.claude/skills/cryptobrain/SKILL.md
python main.py skill --uninstall --system
```

Default is inspect-only. `--system` is required before any file is
written under the user's home directory.
