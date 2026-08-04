"""brain/coach.py

The teaching layer — turns the engine's decisions into explanations a human
can learn from, and turns *your* approval history into personal feedback.

Three functions:
  explain_signal(payload)  — why did the engine say what it said? plain words,
                             with glossary terms expanded.
  mentor(payload, db)      — a step-by-step walkthrough of the top plan, like a
                             patient trading mentor explaining a setup.
  personal_feedback(db)    — what have *you* approved/rejected recently, and
                             does your record agree with the engine's measured
                             edge map? (e.g. "you keep approving Breakout Buy,
                             but the engine measured it at 8.5% win-rate.")
"""
from __future__ import annotations

import re
from typing import Optional

# Term -> (one-line meaning, why it matters)
GLOSSARY = {
    "BOS": ("Break of Structure — price broke a recent swing high/low, confirming the current trend.",
            "The strongest confirmation that a move is real, not noise."),
    "CHOCH": ("Change of Character — price broke structure against the previous trend, signalling a possible reversal.",
               "The earliest warning that a trend may be ending."),
    "Order Block": ("A zone where smart money left a footprint (last opposite candle before a strong move).",
                    "High-probability place where price often reverses or continues from."),
    "FVG": ("Fair Value Gap — a 3-candle imbalance where price moved too fast, leaving a one-sided gap.",
            "Price tends to return ('rebalance') into these gaps before continuing."),
    "Liquidity Sweep": ("A wick through a level of resting stop-losses (swing high/low), grabbing them before reversing.",
                        "Stop hunts often mark the real turning point."),
    "Buyside Liquidity": ("Resting buy stops above swing highs.",
                          "A target for price to 'sweep' — and often the fuel for reversals."),
    "Sellside Liquidity": ("Resting sell stops below swing lows.",
                           "Same idea on the downside."),
    "Premium": ("Price above the midpoint of the dealing range (expensive).",
                "Smart money tends to sell into premium."),
    "Discount": ("Price below the midpoint of the dealing range (cheap).",
                 "Smart money tends to buy from discount."),
    "VWAP": ("Volume-Weighted Average Price — the true average price of the session.",
             "Above VWAP = buyers in control; below = sellers."),
    "RSI": ("Relative Strength Index (0-100). Overbought ≥70, oversold ≤30.",
            "Momentum gauge — but divergences matter more than levels."),
    "Divergence": ("Price makes a new high/low but the oscillator doesn't agree.",
                   "A classic early warning of exhaustion."),
    "Volume Spike": ("Volume several times above its average.",
                     "Confirms that institutional interest is behind a move."),
    "Supertrend": ("A trend-following line that flips above/below price.",
                   "A simple on/off trend switch."),
    "ADX": ("Average Directional Index — trend strength (≥25 = strong).",
            "Weak trend + your setup = lower odds; strong trend = higher odds."),
    "EMA Stack": ("EMA 20 > 50 > 200 = bullish alignment (and vice versa).",
                  "The simplest filter: only trade with the stack."),
    "Take Profit": ("Your exit target where you bank profit.",
                    "TP1 at 1R lets you de-risk; TP2 rides the trend."),
    "Stop Loss": ("The price where you admit you're wrong.",
                  "Never move it away from the trade — that's how accounts die."),
    "Risk:Reward": ("How much you risk vs how much you target (e.g. 1:2).",
                    "You don't need a high win-rate if your R:R is positive."),
    "Expectancy": ("Average R per trade across many trades.",
                   "The only number that matters long-term. Positive = you have an edge."),
}

_TERM_KEYS = sorted(GLOSSARY, key=len, reverse=True)  # longest first for matching


def _expand(text: str) -> str:
    """Bold+explain glossary terms found in a string."""
    out = text
    for term in _TERM_KEYS:
        if term.lower() in out.lower():
            meaning, why = GLOSSARY[term]
            out = out.replace(term, f"{term} ({meaning})")
    return out


def _feature_plain(f: dict) -> list[str]:
    """Translate the feature snapshot into plain-English observations."""
    lines = []
    t = f.get("trend")
    if t:
        lines.append(f"The trend is {t} — EMA stack "
                     f"{'aligned bullish' if f.get('ema_alignment_bull') else 'aligned bearish' if f.get('ema_alignment_bear') else 'mixed'}, "
                     f"Supertrend {'bullish' if f.get('supertrend_bull') else 'bearish'}, "
                     f"ADX {f.get('adx')} ({'strong' if f.get('adx_strong') else 'weak'}).")
    rsi = f.get("rsi")
    if rsi is not None:
        zone = "overbought (≥70)" if rsi >= 70 else "oversold (≤30)" if rsi <= 30 else "neutral"
        lines.append(f"RSI {rsi:.1f} — {zone}.")
    div = f.get("rsi_divergence") or {}
    if div.get("bull"):
        lines.append(f"Bullish RSI divergence {'confirmed' if div['bull']==2 else 'forming'} — momentum is "
                     f"improving while price made a low.")
    if div.get("bear"):
        lines.append(f"Bearish RSI divergence {'confirmed' if div['bear']==2 else 'forming'} — momentum is "
                     f"weakening while price made a high.")
    if f.get("volume_spike"):
        lines.append(f"Volume is {f.get('volume_ratio')}x average — a spike confirms institutional activity.")
    if f.get("above_vwap") is not None:
        lines.append(f"Price is {'above' if f.get('above_vwap') else 'below'} session VWAP "
                     f"({f.get('close_vs_vwap_pct')}%).")
    if f.get("event_kind"):
        lines.append(f"Latest structure event: {f['event_kind'].replace('_',' ').upper()} "
                     f"({_expand(f['event_kind'].replace('_',' ').upper())}).")
    if f.get("premium_discount"):
        lines.append(f"Price sits in the {f['premium_discount']} zone of the dealing range "
                     f"({f.get('premium_discount_position')} of the way up).")
    sw = f.get("sweep")
    if sw:
        lines.append(f"{sw['side'].title()} liquidity was swept at {sw['level']:,.2f} — a stop hunt.")
    return lines


def explain_signal(payload: dict) -> list[str]:
    """Plain-English explanation of one engine output."""
    sig = payload.get("signal", {})
    snap = payload.get("snapshot", {})
    feats = snap.get("features", {})
    lines = [f"Signal {sig.get('signal_id')}: {sig.get('action')} {sig.get('asset')} "
             f"{sig.get('timeframe')} — confidence {sig.get('confidence')}."]
    lines += _feature_plain(feats)
    if sig.get("reason"):
        lines.append(f"Engine's one-line reason: {sig.get('reason')}.")
    plans = payload.get("plans", [])
    if plans:
        lines.append(f"Top plan: {plans[0]['type']} ({plans[0]['confidence']}%) — "
                     f"{_expand(plans[0]['condition'])}")
        if len(plans) > 1:
            lines.append(f"Also watching: {', '.join(p['type'] for p in plans[1:4])}.")
    lines.append("Remember: entry = where you get in, SL = where you're wrong, "
                 "TP = where you bank. Never risk more than you plan to lose.")
    return lines


def mentor(payload: dict, db=None) -> str:
    """Step-by-step walkthrough of the top plan — the mentor voice."""
    sig = payload.get("signal", {})
    plans = payload.get("plans", [])
    snap = payload.get("snapshot", {})
    feats = snap.get("features", {})
    out = []
    price = feats.get("price")
    price_txt = f"{price:,.2f}" if price is not None else "—"
    out.append("Let's walk through this setup the way I'd teach it:\n")
    out.append(f"1. The market is currently {feats.get('trend','mixed')} on {sig.get('timeframe')} "
               f"(price {price_txt}). Structure bias: {feats.get('trend_bias')}.")
    if not plans:
        out.append("2. There is no plan above the confidence threshold right now. "
                   "The best trade is no trade. Wait for the market to offer a clean setup — "
                   "patience is a position.")
        return "\n".join(out)
    p = plans[0]
    out.append(f"2. The setup I like most: {p['type']} ({p['confidence']}%).")
    out.append(f"   Condition: {p['condition']}")
    out.append(f"3. Entry {p['entry']:,.2f} — "
               f"{'we can enter immediately' if p['status']=='active' else 'we WAIT for the trigger — do not chase'}.")
    out.append(f"4. Stop at {p['stop_loss']:,.2f}. That's the line where the idea is wrong. "
               f"Risk per trade ≈ {abs(p['entry']-p['stop_loss']):,.2f}.")
    out.append(f"5. Take profits at {', '.join(f'{tp:,.2f}' for tp in p['take_profits'])}. "
               f"TP1 banks the first target, TP2 lets the winner run.")
    out.append(f"6. Risk:reward ≈ {p['risk_reward']}. "
               f"With a positive R:R you can be right less than half the time and still profit.")
    for i, r in enumerate(p.get("reasons", [])[:3], start=7):
        out.append(f"{i}. Why it fired: {_expand(r)}")
    out.append("\nHomework: write down your plan BEFORE price moves. If the trigger "
               "doesn't happen, the plan is cancelled — no revenge trades.")
    return "\n".join(out)


def personal_feedback(db, limit: int = 25) -> list[str]:
    """Teaching feedback derived from the user's own approval history + engine stats."""
    notes: list[str] = []
    try:
        decisions = [dict(r) for r in db.conn.execute(
            """SELECT s.symbol, s.timeframe, s.action, s.reason, d.to_state, d.note, d.ts
               FROM decisions d JOIN scans s ON s.id=d.scan_id
               ORDER BY d.ts DESC LIMIT ?""", (limit,)).fetchall()]
    except Exception:
        return ["No decision history yet — approve/reject a few signals and I'll teach from them."]
    if not decisions:
        return ["No decision history yet — approve/reject a few signals and I'll teach from them."]

    approved = [d for d in decisions if d["to_state"] == "APPROVED"]
    rejected = [d for d in decisions if d["to_state"] == "REJECTED"]
    notes.append(f"Recent activity: {len(approved)} approved, {len(rejected)} rejected "
                 f"of the last {len(decisions)} decisions.")

    # Which plan types did the user approve? Cross-check with measured edge.
    try:
        plan_approvals = [dict(r) for r in db.conn.execute(
            """SELECT p.type, COUNT(*) n
               FROM decisions d JOIN scans s ON s.id=d.scan_id
               JOIN plans p ON p.scan_id=s.id
               WHERE d.to_state='APPROVED'
               GROUP BY p.type ORDER BY n DESC LIMIT 5""").fetchall()]
        if plan_approvals:
            stats = db.backtest_stats().get("by_type", [])
            edge = {r["plan_type"]: r for r in stats}
            for pa in plan_approvals:
                e = edge.get(pa["type"])
                if e and e["n"] and e["n"] >= 10 and e["win_rate"] is not None:
                    verdict = ("this matches a positive-expectancy setup — good instinct"
                               if (e["win_rate"] or 0) >= 0.5 else
                               "the engine's measured win-rate for this setup is low — "
                               "consider filtering it")
                    notes.append(f"You tend to approve {pa['type']} ({pa['n']}x) — "
                                 f"{verdict} ({e['win_rate']*100:.0f}% win over {e['n']} samples).")
    except Exception:
        pass

    rej_notes = [d["note"] for d in rejected if d.get("note")]
    if rej_notes:
        from collections import Counter
        top = Counter(rej_notes).most_common(3)
        notes.append("Most common rejection reasons: " +
                     ", ".join(f"{r} ({n}x)" for r, n in top) + ".")
    return notes
