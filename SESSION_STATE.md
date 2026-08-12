# SESSION_STATE.md — CryptoBrain / SKY handoff

**Last reconciled:** 2026-08-11 (Asia/Dhaka)
**Working branch:** `arena/019ff0d9-ai` (Arena-fixed; do not rename/switch)
**Canonical source imported:** `Azimshawon/SKY@4216448`
**Implementation:** canonical sync + v2.1 boundary redesign are combined in this PR
**Current release:** `2.1.0`
**Current PR:** [Cloudslover/AI#5](https://github.com/Cloudslover/AI/pull/5) from `arena/019ff0d9-ai` to `main`

## Start here

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
DEMO_MODE=1 .venv/bin/python -m pytest -q
```

The project is paper/research-first. It has no real exchange-order path. The
machine proposes, the risk gate evaluates, the human approves, and the
paper-runner simulates.

## What changed in this session

### 1. Canonical SKY sync

The complete `Azimshawon/SKY` main tree at `4216448` was imported into the
Arena-fixed Cloudslover branch. This brought the AI anatomy/RAG agents,
hidden-alpha modules, modern dashboard, channels, root MCP server, operations
assets, and the 306-pass baseline into this repository.

### 2. Functional core / imperative shell

- `engine/pipeline.py` is the side-effect-free analytical core.
- Stages (`FeatureStage`, `ScoreStage`, `PlanStage`, `BrainOutput`) are frozen;
  nested JSON-shaped structures are recursively immutable.
- `now_ms` is injectable for deterministic acceptance tests.
- `engine/signal_engine.py` preserves the historical import surface.
- `brain/full_pipeline.py` is the shell that owns market/context/DB/state I/O.

### 3. Honest decision semantics

`brain/decision_service.py` produces:

1. `watch_items` — conditional and unauthorized research scenarios;
2. `active_candidate` — authorized and executable now;
3. `desk_verdict` — final playbook/portfolio/risk-gated action.

Analytical confidence and historical fill probability are separate. The legacy
`signal` adapter remains for compatibility but is built only from an active
candidate. CLI/web queue persistence checks the canonical desk verdict.

### 4. Policy-based setup authorization

`engine/policy.py` applies the configured setup family after generation and
calibration. Other setup families remain visible and learnable but cannot reach
the active candidate.

### 5. HTF structure propagation

`engine/mtf.py` now carries unbroken order blocks and unfilled FVGs from
1W/1D/4H/1H. `engine/rules.py` may select those precise levels while requiring
execution-timeframe CHOCH/rejection confirmation.

### 6. Context provider boundary

`brain/context_providers.py` standardizes all enrichers as
`fetch_context(symbol) -> dict`. Failures are isolated and surfaced through
`context_completeness`. CryptoDada and Discord are optional providers; neither
can block core analysis.

### 7. Learning improvements

- Calibration records conditional-entry fill probability independently from
  expectancy and persists the existing `filtered` flag correctly.
- Scorer accepts validated 100-point profiles.
- `brain/meta_learner.py` / `python main.py meta-learn` performs an offline
  grid advisory. It never activates a profile. A human must set
  `SCORING_WEIGHTS_JSON` after review.

### 8. Acceptance protection

`docs/workflows/acceptance.yml` is an activation-ready scheduled workflow. It
exercises MTF → core → intelligence → playbook/portfolio/risk → decision layers
for BTC, ETH, and XAU/GOLD and compares blessed structural signatures. The
Arena GitHub App cannot create/update workflow files; a repository owner must
copy it to `.github/workflows/acceptance.yml` using workflow-scoped credentials.

Fixture honesty is documented in `data_samples/acceptance/MANIFEST.md`: BTC is
the repository's recorded sample; ETH/XAU are frozen deterministic
market-shaped fixtures and never count as evidence.

## Architectural invariants

1. No real exchange orders, signing, withdrawal, or transfer capability.
2. MCP tools remain read-only; approval mutations stay CLI/dashboard + human.
3. Risk gate is evaluated on every approval and paper enrollment.
4. Conditional plans never become immediate candidates before their trigger.
5. Confidence is per-plan confluence; fill probability is a separate metric.
6. Setup authorization occurs after generation so research is not suppressed.
7. External context is optional and exception-isolated.
8. Meta-learning is offline advisory only.
9. BTC + ETH remain one correlated crypto-risk bucket; GOLD is separate.
10. Tests must remain green; activate and preserve the scheduled full-desk
    acceptance template when workflow-scoped GitHub credentials are available.

## Verification

Run before handing off:

```bash
DEMO_MODE=1 .venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q engine data ai brain output web tests main.py config.py
node --check /tmp/dash.js  # extract from web/app.py as CI does
```

Latest verification: **317 passed, 1 skipped** in offline mode; compileall and
dashboard JavaScript syntax checks passed.

## Important files

- `docs/adr/0001-functional-core-and-decision-layers.md` — rationale/trade-offs
- `ARCHITECTURE.md` — module map and invariants
- `CHANGELOG.md` — shipped behavior
- `TODO.md` — next work only
- `BLUEPRINT.md` — progression to evidence-backed paper/micro operation
- `PROFESSIONAL_PLAN_DECISIONS.md` — professional trading plan

## Next safe work

1. Add rolling out-of-sample folds and multiple-comparison penalties to the
   meta-learner before adding more candidate profiles.
2. Version/deprecate the legacy top-level `signal` adapter only after dashboard,
   MCP, and third-party clients consume `decision_service`.
3. Display watch-item fill probability/sample count directly in the dashboard.
4. Add provider latency/staleness to `context_completeness` and health.
5. Continue paper sample collection; do not infer profitability from acceptance
   fixtures or smoke tests.
