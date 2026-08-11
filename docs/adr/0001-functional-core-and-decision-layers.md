# ADR-0001: Functional Core, Policy Gate, and Three-Layer Decisions

- **Status:** Accepted
- **Date:** 2026-08-11
- **Scope:** signal construction, MTF structure, context, learning, CI

## Context

CryptoBrain grew organically into a broad discretionary-trading model. That
breadth is valuable, but it created three risks:

1. orchestration mixed pure analysis with I/O and state;
2. a high-confidence conditional pullback could be presented like an immediate
   signal even though price might never fill it;
3. the primary-setup rule lived too close to plan generation, where it could
   suppress research rather than authorize execution.

The guiding design rule is:

> Separate what the system thinks from when and how that thought is acted upon.

## Decision

### 1. Functional core, imperative shell

`engine/pipeline.py` is the pure core. It accepts a closed OHLCV frame and
explicit inputs (calibration, weights, HTF context, timestamp) and returns
immutable stage records:

- `FeatureStage`
- `ScoreStage`
- `PlanStage`
- `BrainOutput`

Nested JSON-shaped values are recursively frozen. `BrainOutput.as_json()`
returns fresh mutable/serializable copies at the boundary.

`brain/full_pipeline.py` is the imperative shell. It owns market-data fetches,
context providers, calibration reads, state memory, DB-backed risk gates, and
final desk orchestration. CLI/web own persistence and notifications.

`engine/signal_engine.py` remains a compatibility facade.

### 2. Three decision layers

`brain/decision_service.py` returns:

- `watch_items`: conditional scenarios and unauthorized research plans;
- `active_candidate`: one authorized plan executable now, if one exists;
- `desk_verdict`: the playbook/portfolio/risk-gated `TRADE` or `NO_TRADE`.

Analytical `confidence` remains per-plan. `execution_probability` is separate:
`1.0` for an immediate candidate, or a historical trigger/fill rate for a
conditional plan. A 95% pullback plan with a 37% fill rate is therefore not
misrepresented as a 95% immediate trade.

The legacy top-level `signal` remains as an adapter for existing clients. It is
built only from `active_candidate`; it can no longer promote a waiting plan.
New integrations must consume `decision_service`.

### 3. Authorization after generation

`engine/policy.py` applies `SetupFamilyPolicy` after every plan family has been
generated and calibrated. Unauthorized plans remain in output and continue to
feed backtests. They cannot become `active_candidate`.

### 4. HTF SMC objects, not only HTF bias

`engine/mtf.py` propagates unbroken 1W/1D/4H/1H order blocks and unfilled FVGs
as `htf_structure`. The execution planner selects a relevant nearby object and
can produce conditions such as:

> IF price pulls back to the 1h bullish Order Block near X AND 15m prints CHOCH
> up / bullish rejection.

### 5. Context provider interface

Every external enrichment implements:

```python
fetch_context(symbol) -> dict
```

`brain/context_providers.py` isolates exceptions and reports
`context_completeness`. CryptoDada and Discord are optional providers. Provider
failure cannot stop core analysis.

### 6. Two learning loops with human approval

The existing calibrator continues to adjust per-setup confidence and TP distance.
It now also measures conditional-entry fill probability separately from
expectancy.

`brain/meta_learner.py` performs an offline grid search over complete 100-point
scoring profiles. It emits an advisory and an explicit `SCORING_WEIGHTS_JSON`
value. It never edits configuration or activates a profile; operator review is
mandatory.

### 7. Acceptance snapshots

A ready-to-activate workflow template runs the complete BTC/ETH/GOLD path over
frozen offline frames and compares a blessed structural signature. It lives at
`docs/workflows/acceptance.yml`; copy it to `.github/workflows/` with a GitHub
credential that has `workflows` permission. (The Arena GitHub App used for this
PR cannot create workflow files.) The fixture
manifest clearly distinguishes recorded BTC input from deterministic ETH/GOLD
market-shaped fixtures; none are calibration evidence.

## Consequences

### Positive

- Core analysis is deterministic under an injected timestamp and can be tested
  without network, DB, or notification mocks.
- Confidence semantics are statistically honest.
- New context sources and setup policies do not require edits to core reasoning.
- HTF structure can directly improve conditional entry precision.
- Legacy API clients remain functional during migration.

### Costs and limitations

- The top-level `signal` and `decision` fields temporarily duplicate the new
  contract and must eventually be versioned/deprecated.
- Frozen boundary conversion adds small allocation overhead; negligible beside
  indicator and MTF computation.
- Fill probability uses observed backtest trigger frequency. It is not a
  calibrated probability model and must expose sample size.
- The meta-learner grid is intentionally small. Bayesian optimization may be
  added only after robust out-of-sample and multiple-comparison controls exist.
- A blessed signature catches structural drift, not economic validity. Profit
  claims still require walk-forward and live paper evidence.

## Safety invariants

- No real exchange order path is introduced.
- Human approval and the risk gate remain mandatory.
- Private/social context is never a direct trade trigger.
- Meta-learning is advisory only.
