"""brain/metrics.py — measure yourself like a business (decision B4).

Phase 9 of your roadmap: every 50-100 trades calculate win rate, average
winner, average loser, expectancy, profit factor, max drawdown, streaks —
plus execution discipline (violations, revenge trades, overtrading).

The business metrics run on **decided paper trades** (your actual decisions
that reached TP or SL).  Backtests are research; paper trades are your track
record.
"""
from __future__ import annotations

from data.database import SignalDB
from brain.risk_gate import effective_risk


def _equity_curve(db: SignalDB, start: float = 10_000.0) -> list[dict]:
    # exclude_sim: simulator walk-forward rows are calibration evidence with
    # backdated timestamps — the scorecard tracks YOUR paper book only.
    rows = db.decided_paper_rows(exclude_sim=True)
    risk = effective_risk()
    equity = start
    out = []
    for r in rows:
        equity += start * (float(r["rr_achieved"] or 0.0) * risk["risk_pct"] / 100.0)
        out.append({
            "ts": r.get("closed_ts") or r.get("opened_ts"),
            "symbol": r.get("symbol"),
            "plan_type": r.get("plan_type"),
            "rr": float(r.get("rr_achieved") or 0.0),
            "equity": round(equity, 2),
        })
    return out


def _metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    wins = [r for r in rows if float(r["rr_achieved"] or 0) > 0]
    losses = [r for r in rows if float(r["rr_achieved"] or 0) <= 0]
    n = len(rows)
    gross_win = sum(float(r["rr_achieved"]) for r in wins)
    gross_loss = abs(sum(float(r["rr_achieved"]) for r in losses))
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 1.0
    max_streak = cur = 0
    max_win_streak = max_loss_streak = 0
    for r in rows:
        if float(r["rr_achieved"] or 0) > 0:
            cur = cur + 1 if cur > 0 else 1
            max_win_streak = max(max_win_streak, cur)
            max_loss_streak = max(max_loss_streak, 0)
        else:
            cur = cur - 1 if cur < 0 else -1
            max_loss_streak = max(max_loss_streak, -cur)
            max_win_streak = max(max_win_streak, 0)
    equity = 10_000.0
    peak = equity
    max_dd = 0.0
    risk = effective_risk()
    for r in rows:
        equity += 10_000.0 * (float(r["rr_achieved"] or 0.0) * risk["risk_pct"] / 100.0)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100.0 if peak else 0.0)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n, 3),
        "avg_win_r": round(avg_win, 3),
        "avg_loss_r": round(avg_loss, 3),
        "expectancy_r": round(sum(float(r["rr_achieved"] or 0) for r in rows) / n, 3),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else None,
        "max_drawdown_pct": round(max_dd, 2),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "final_equity": round(equity, 2),
    }


def business_metrics(db: SignalDB, windows: tuple[int, ...] = (50, 100)) -> dict:
    """Full business scorecard: overall + rolling windows + execution.

    Runs on the real paper book only (exclude_sim=True): simulator
    walk-forward samples feed calibration/setup-proof, not your scorecard.
    """
    rows = db.decided_paper_rows(exclude_sim=True)
    overall = _metrics(rows)
    rolling = {}
    for w in windows:
        rolling[str(w)] = _metrics(rows[-w:])
    from brain.journal import violation_rate
    exec_stats = violation_rate(db)
    return {
        "overall": overall,
        "rolling": rolling,
        "execution": exec_stats,
        "equity_curve": _equity_curve(db),
    }


def format_metrics(metrics: dict) -> str:
    o = metrics["overall"]
    if not o.get("n"):
        return ("No decided paper trades yet — approve signals and run "
                "`python main.py paper --watch` to build your track record.")
    lines = [
        "=" * 66,
        f"BUSINESS SCORECARD  ({o['n']} decided paper trades)",
        "-" * 66,
        f"  win rate        {o['win_rate']*100:.1f}%  ({o['wins']}W / {o['losses']}L)",
        f"  avg winner      {o['avg_win_r']:+.2f}R    avg loser {o['avg_loss_r']:.2f}R",
        f"  expectancy      {o['expectancy_r']:+.3f}R per trade",
        f"  profit factor   {o['profit_factor'] if o['profit_factor'] is not None else 'n/a'}",
        f"  max drawdown    {o['max_drawdown_pct']:.2f}%   final equity {o['final_equity']:,.2f}",
        f"  streaks         {o['max_win_streak']}W / {o['max_loss_streak']}L",
    ]
    for w, r in metrics["rolling"].items():
        if r.get("n"):
            lines.append(f"  last {w:<4} trades: win {r['win_rate']*100:.0f}%  "
                         f"exp {r['expectancy_r']:+.3f}R  pf {r['profit_factor']}")
    e = metrics["execution"]
    if e.get("n"):
        lines.append(f"  execution       {e['violation_rate']*100:.0f}% rule violations "
                     f"({e['violations']}/{e['n']} journaled trades)")
    return "\n".join(lines)
