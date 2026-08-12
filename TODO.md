# TODO — CryptoBrain / SKY

**Last reconciled:** 2026-08-11 (Asia/Dhaka)

Completed history belongs in `CHANGELOG.md`; this file contains only actionable
next work. Safety invariant: no real exchange-order capability.

## P0 — Merge and observe

- [ ] Review/merge the `arena/019ff0d9-ai` PR after CI passes.
- [ ] A repository owner with workflow-scoped credentials should copy
  `docs/workflows/acceptance.yml` to `.github/workflows/acceptance.yml`; the
  Arena GitHub App cannot create/update workflows.
- [ ] Run the dashboard in `DEMO_MODE=1` and verify the new payload's
  `decision_service` section is visible in raw JSON without breaking legacy UI.
- [ ] After activation, observe one week of scheduled acceptance runs before
  changing blessed signatures. A signature update requires an explanation in
  `CHANGELOG.md`.

## P1 — Dashboard decision semantics

- [ ] Add a first-class three-column view: Watch items / Active candidate / Desk
  verdict.
- [ ] Show analytical confidence and execution probability as different labels.
- [ ] Show fill sample count next to probability; render `unknown` rather than
  inventing probability when evidence is sparse.
- [ ] Show the HTF source timeframe on OB/FVG pullback cards.

## P2 — Meta-learner statistical hardening

- [ ] Add anchored walk-forward train/validation folds.
- [ ] Rank on out-of-sample expectancy and drawdown, not in-sample objective.
- [ ] Add a multiple-comparison penalty before expanding beyond the four small
  named profiles.
- [ ] Require per-regime/per-asset minimum samples and stability across folds.
- [ ] Keep activation manual through `SCORING_WEIGHTS_JSON`; do not add an
  auto-approve flag.

## P3 — Context-provider operations

- [ ] Record provider latency, fetched-at timestamp, and staleness.
- [ ] Surface completeness in `/api/health` and the dashboard readiness strip.
- [ ] Add contract tests for a third-party plugin provider.
- [ ] Keep private CryptoDada/Discord output at context-only source tiers.

## P4 — API migration

- [ ] Document `decision_service` as the v2.1 canonical contract in
  `output/signal_schema.py`.
- [ ] Migrate dashboard, signal cards, notifiers, MCP, and coach to canonical
  fields.
- [ ] Add a deprecation warning for top-level `signal`.
- [ ] Remove the adapter only in a major version after downstream migration.

## P5 — Acceptance evidence quality

- [ ] Replace deterministic ETH/XAU market-shaped fixtures with legally
  redistributable recorded public exchange/proxy bars when available.
- [ ] Add fixture checksums and capture timestamps/provider metadata.
- [ ] Keep acceptance signatures structural only; never feed them into
  calibration, graduation, or profitability claims.

## P6 — Existing SKY roadmap carryover

- [ ] Add packaging metadata / wheel smoke gate after deciding whether this is a
  distributable package or repository application.
- [ ] Add `brain.agent.desk_status()` as read-only advisory if it can reuse the
  canonical `decision_service` contract without introducing a second truth.
- [ ] Maintain the MCP mutation deny list (`approve`, `reject`, `execute`,
  `close`, `place_order`, `sign`, `withdraw`, `transfer`).
