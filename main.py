#!/usr/bin/env python3
"""CryptoBrain — AI trading-brain signal engine.

Usage:
  python main.py scan --symbol BTCUSDT --tf 15m --json
  python main.py scan --symbols BTCUSDT,ETHUSDT,SOLUSDT
  python main.py watch --symbol BTCUSDT --interval 120      # continuous loop
  python main.py web                                         # dashboard
  python main.py sources                                     # CryptoDada + Discord + news
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (SYMBOL, TIMEFRAME, BARS, MIN_CONFIDENCE, DEFAULT_RISK_REWARD,
                    DASHBOARD_HOST, DASHBOARD_PORT)

from data.binance_client import BinanceClient
from engine.signal_engine import analyze_frame
from output.signal_schema import validate_output
from output.notifiers import notify_all


def _client() -> BinanceClient:
    return BinanceClient()


def _load_calibration() -> dict:
    """Load the self-improvement profile from the DB (empty dict when unused)."""
    try:
        from data.database import SignalDB
        with SignalDB() as db:
            return db.load_calibration()
    except Exception:
        return {}


def run_scan(symbol: str, timeframe: str, bars: int, with_context: bool = True,
             with_llm: bool = False, save_db: bool = True,
             auto_approve: bool = False) -> dict:
    client = _client()
    df = client.klines(symbol, timeframe, bars)
    calib = _load_calibration()
    out = analyze_frame(df, symbol=symbol, timeframe=timeframe,
                        min_confidence=MIN_CONFIDENCE, default_rr=DEFAULT_RISK_REWARD,
                        calibration=calib)
    payload = out.as_json()

    if with_context:
        ctx = client.market_context(symbol)
        payload["market_context"] = ctx

    if with_llm:
        from ai.llm_brain import LLMBrain
        payload["llm"] = LLMBrain().generate(payload)

    payload["validation"] = validate_output(payload)

    if save_db:
        from data.database import SignalDB
        from engine.lifecycle import reviewable
        with SignalDB() as db:
            scan_id = db.save_scan(payload)
            payload["scan_id"] = scan_id
            if auto_approve and reviewable(payload.get("signal", {})):
                db.update_status(scan_id, "APPROVED", note="auto-approve",
                                 reviewer="auto")
                payload["lifecycle"] = {"status": "APPROVED",
                                        "note": "auto-approved (--auto-approve)"}
            else:
                payload["lifecycle"] = {
                    "status": "PENDING_REVIEW" if reviewable(payload.get("signal", {})) else "CREATED",
                    "note": ("awaiting human approval — `python main.py review`"
                             if reviewable(payload.get("signal", {})) else
                             "monitor-only signal (no action required)"),
                }
    return payload


def cmd_scan(args) -> int:
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    all_payloads = []
    for sym in symbols:
        try:
            payload = run_scan(sym, args.tf, args.bars, with_llm=args.llm,
                               save_db=not args.no_save, auto_approve=args.auto_approve)
            all_payloads.append(payload)
            if not args.json:
                _print_human(payload)
        except ConnectionError as exc:
            print(f"[!] {sym}: {exc}", file=sys.stderr)
    if args.json:
        body = all_payloads[0] if len(all_payloads) == 1 else all_payloads
        print(json.dumps(body, indent=2, default=str))
    return 0 if all_payloads else 1


def _print_human(payload: dict) -> None:
    sig = payload["signal"]
    print("=" * 72)
    print(f"{sig['action']:>10}  {sig['asset']}  [{sig['timeframe']}]  "
          f"conf={sig['confidence']:<7} {sig['signal_id']}")
    if sig.get("entry"):
        print(f"   entry {sig['entry']:>12,.2f}   SL {sig['stop_loss']:>10,.2f}   "
              f"TP {sig['take_profit']:>12,.2f}   RR {sig['risk_reward']:.2f}")
    print(f"   reason: {sig['reason']}")
    print("-" * 72)
    for p in payload.get("plans", []):
        print(f"   [{p['confidence']:>3}% {p['confidence_label']:<6}] {p['type']:<22} "
              f"{p['condition'][:80]}")
    scores = payload.get("snapshot", {}).get("scores", {})
    if scores:
        print(f"   scores → bull {scores.get('bull', {}).get('score', 0)}  |  "
              f"bear {scores.get('bear', {}).get('score', 0)}")
    if payload.get("market_context", {}).get("futures"):
        ctx = payload["market_context"]
        print(f"   funding {ctx['funding_rate_pct']}%  OI {ctx['open_interest']:,.0f}  "
              f"L/S {ctx['long_short_ratio']:.2f}")
    else:
        print("   futures context unavailable from this network (geo-block) — works from most regions")
    lc = payload.get("lifecycle")
    if lc:
        print(f"   lifecycle: {lc.get('status')} — {lc.get('note')}")
    print()


def cmd_watch(args) -> int:
    print(f"Watching {args.symbol} {args.tf} every {args.interval}s — Ctrl+C to stop")
    last_sig = None
    while True:
        try:
            payload = run_scan(args.symbol, args.tf, args.bars,
                               save_db=not args.no_save, auto_approve=args.auto_approve)
            sig = payload["signal"]
            if sig["action"] != "NO TRADE" and sig.get("signal_id") != last_sig:
                last_sig = sig.get("signal_id")
                _print_human(payload)
                if args.notify:
                    res = notify_all(sig, payload.get("plans"))
                    print(f"   notified: {res}")
            else:
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] {sig['asset']} {sig['action']} conf={sig['confidence']} "
                      f"(score {sig.get('confidence')})")
        except Exception as exc:  # keep the loop alive
            print(f"[!] {exc}", file=sys.stderr)
        time.sleep(max(10, args.interval))


def cmd_sources(args) -> int:
    from data.sources.cryptodada_website import CryptoDadaConnector, summarize_cryptodada
    from data.sources.discord_reader import DiscordReader, summarize_discord
    from data.sources.news import fetch_news

    result = {}
    cd = CryptoDadaConnector()
    result["cryptodada"] = summarize_cryptodada(cd.fetch()) if cd.configured else {
        "configured": False, "message": "Set CRYPTODADA_* in .env"}
    dr = DiscordReader()
    result["discord"] = summarize_discord(dr.read_all()) if dr.can_read else {
        "configured": False, "message": "Set DISCORD_TOKEN + DISCORD_CHANNEL_IDS in .env"}
    result["news"] = fetch_news(limit=12)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_backtest(args) -> int:
    from data.backtester import run_backtest, save_report, print_report
    from data.database import SignalDB

    client = _client()
    df = client.klines(args.symbol, args.tf, args.bars)
    horizons = [float(h) for h in args.horizons.split(",") if h.strip()]
    result = run_backtest(df, symbol=args.symbol, timeframe=args.tf,
                          horizons=horizons, min_confidence=args.min_conf)
    report = result["report"]
    save_report(report)
    print_report(report)

    if args.save:
        run_id = time.strftime("%Y%m%d_%H%M%S")
        rows = []
        for g in result["graded"]:
            r = g.as_row()
            r.update({"run_id": run_id, "symbol": args.symbol,
                      "timeframe": args.tf})
            rows.append(r)
        with SignalDB() as db:
            n = db.save_backtest_rows(rows, run_id)
        print(f"\nSaved {n} graded plans to the signal database (run {run_id}).")
        print("Run `python main.py stats` to see what the engine has learned.")
    return 0


def _print_review_row(r: dict) -> None:
    print(f"  #{r['id']:<5} {r['symbol']:<10} {r['timeframe']:<4} {r['action']:<5} "
          f"conf={r['confidence_label']:<7} entry={r['entry']}  "
          f"plans={r['n_plans']}  {r['reason'][:60]}")


def cmd_review(args) -> int:
    from data.database import SignalDB
    with SignalDB() as db:
        rows = db.pending_reviews(args.symbol or None)
    print(f"Pending human approval: {len(rows)}")
    for r in rows:
        _print_review_row(r)
    print("\nApprove:  python main.py approve <id> [--note ...]")
    print("Reject:   python main.py reject <id> [--note ...]")
    print("Details:  python main.py signal <id>")
    return 0


def _decide(args, to_state: str) -> int:
    from data.database import SignalDB
    from engine.lifecycle import LifecycleError
    with SignalDB() as db:
        try:
            new = db.update_status(args.scan_id, to_state, note=args.note or "")
        except LifecycleError as exc:
            print(f"[!] {exc}", file=sys.stderr)
            return 1
        if new is None:
            print(f"[!] scan #{args.scan_id} not found", file=sys.stderr)
            return 1
        sig = db.get_scan(args.scan_id)
    print(f"scan #{args.scan_id} → {new}  ({sig['symbol']} {sig['action']} "
          f"{sig['entry']})  note: {args.note or '—'}")
    return 0


def cmd_approve(args) -> int:
    return _decide(args, "APPROVED")


def cmd_reject(args) -> int:
    return _decide(args, "REJECTED")


def cmd_execute(args) -> int:
    return _decide(args, "EXECUTED")


def cmd_close(args) -> int:
    return _decide(args, "CLOSED")


def cmd_signal(args) -> int:
    from data.database import SignalDB
    import json as _json
    with SignalDB() as db:
        scan = db.get_scan(args.scan_id)
        if scan is None:
            print(f"[!] scan #{args.scan_id} not found", file=sys.stderr)
            return 1
        history = db.decision_history(args.scan_id)
    print(f"scan #{scan['id']} — {scan['symbol']} {scan['timeframe']} {scan['action']} "
          f"({scan['created_at']})")
    print(f"  status: {scan['status']}  conf: {scan['confidence_label']}  "
          f"entry: {scan['entry']}  SL: {scan['stop_loss']}  TP: {scan['take_profit']}")
    print(f"  reason: {scan['reason']}")
    print("  lifecycle:")
    for h in history:
        print(f"    {h['from_state']} → {h['to_state']}  by {h['reviewer']}  "
              f"note: {h['note'] or '—'}")
    if scan.get("plans_json"):
        plans = _json.loads(scan["plans_json"])
        print(f"  plans ({len(plans)}):")
        for p in plans[:5]:
            print(f"    [{p['confidence']}%] {p['type']} — {p['condition'][:80]}")
    return 0


def cmd_learn(args) -> int:
    from brain.calibrator import learn, describe
    result = learn()
    print(describe(result["profile"]))
    if args.json:
        import json as _json
        print(_json.dumps(result["profile"], indent=2))
    return 0


def cmd_coach(args) -> int:
    from data.database import SignalDB
    from brain.coach import explain_signal, mentor, personal_feedback, GLOSSARY

    # 1) teach from the current market (fresh scan, no DB save)
    payload = run_scan(args.symbol, args.tf, args.bars, save_db=False)
    print("=" * 70)
    print("🧑‍🏫 COACH — what's happening right now")
    print("=" * 70)
    for line in explain_signal(payload):
        print(" ", line)
    print()
    print(mentor(payload))

    # 2) personal feedback from decision history
    with SignalDB() as db:
        fb = personal_feedback(db)
    print()
    print("📈 YOUR TRADING FEEDBACK")
    for f in fb:
        print(" ", f)

    # 3) optional glossary deep-dive
    if args.term:
        term = next((k for k in GLOSSARY if k.lower() == args.term.lower()), None)
        if term:
            meaning, why = GLOSSARY[term]
            print(f"\n📖 {term}: {meaning}\n   Why it matters: {why}")
        else:
            print(f"\n[!] unknown term '{args.term}' — try: {', '.join(GLOSSARY)}")
    return 0


def cmd_glossary(args) -> int:
    from brain.coach import GLOSSARY
    if args.term:
        term = next((k for k in GLOSSARY if k.lower() == args.term.lower()), None)
        if term:
            meaning, why = GLOSSARY[term]
            print(f"{term}: {meaning}\n  Why it matters: {why}")
        else:
            print(f"unknown term '{args.term}'")
        return 0
    for term, (meaning, why) in GLOSSARY.items():
        print(f"{term:<18} {meaning}")
    return 0


def cmd_stats(args) -> int:
    from data.database import SignalDB

    with SignalDB() as db:
        scans = db.latest_scans(args.symbol or None, limit=15)
        plan_stats = db.plan_stats()
        bt = db.backtest_stats()

    print("=" * 66)
    print("SIGNAL DATABASE — learning store")
    if not scans:
        print("No scans recorded yet. Run `python main.py scan` (saves by default).")
        return 0
    print(f"latest {len(scans)} scans:")
    for s in scans:
        print(f"  {s['symbol']:<10} {s['timeframe']:<4} {s['action']:<8} "
              f"conf={s['confidence_label']:<7} entry={s['entry']}  {s['created_at']}")
    print("-" * 66)
    print("plan-type distribution (live scans):")
    for p in plan_stats:
        print(f"  {p['type']:<24} n={p['n']:>4} avgConf={p['avg_conf']}  avgRR={p['avg_rr']}")

    overall = bt["overall"]
    print("-" * 66)
    print("BACKTEST learning:")
    if overall["n"]:
        wr = overall["win_rate"]
        print(f"  overall: {overall['n']} graded | win-rate "
              f"{f'{wr*100:.1f}%' if wr is not None else 'n/a'} | "
              f"avgR {overall['avg_rr']} | wins {overall['wins']} losses {overall['losses']}")
        print("  by plan type:")
        for r in bt["by_type"]:
            wr = r["win_rate"]
            print(f"    {r['plan_type']:<24} n={r['n']:>4} win "
                  f"{f'{wr*100:.1f}%' if wr is not None else 'n/a'}  avgR {r['avg_rr']}")
        print("  by confidence bucket:")
        for r in bt["by_confidence"]:
            wr = r["win_rate"]
            print(f"    {r['bucket']:<8} n={r['n']:>4} win "
                  f"{f'{wr*100:.1f}%' if wr is not None else 'n/a'}  avgR {r['avg_rr']}")
    else:
        print("  none yet — run `python main.py backtest --save` to start learning.")
    return 0


def cmd_web(args) -> int:
    from web.app import make_app, serve
    host = args.host or DASHBOARD_HOST
    port = args.port or DASHBOARD_PORT
    serve(make_app(), host, port)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="CryptoBrain — AI trading-brain signal engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="one-shot signal scan")
    p_scan.add_argument("--symbol", default=SYMBOL)
    p_scan.add_argument("--symbols", default=None, help="comma-separated (overrides --symbol)")
    p_scan.add_argument("--tf", default=TIMEFRAME)
    p_scan.add_argument("--bars", type=int, default=BARS)
    p_scan.add_argument("--json", action="store_true", help="raw JSON output")
    p_scan.add_argument("--llm", action="store_true", help="attach LLM narrative if configured")
    p_scan.add_argument("--no-save", action="store_true", help="do not write the scan to the signal database")
    p_scan.add_argument("--auto-approve", action="store_true",
                        help="skip the human approval gate (unattended mode)")
    p_scan.set_defaults(func=cmd_scan)

    p_watch = sub.add_parser("watch", help="continuous monitor loop")
    p_watch.add_argument("--symbol", default=SYMBOL)
    p_watch.add_argument("--tf", default=TIMEFRAME)
    p_watch.add_argument("--bars", type=int, default=BARS)
    p_watch.add_argument("--interval", type=int, default=120)
    p_watch.add_argument("--notify", action="store_true", help="push signals to Telegram/Discord")
    p_watch.add_argument("--no-save", action="store_true", help="do not write scans to the signal database")
    p_watch.add_argument("--auto-approve", action="store_true",
                        help="approve signals automatically (unattended mode)")
    p_watch.set_defaults(func=cmd_watch)

    p_src = sub.add_parser("sources", help="pull CryptoDada + Discord + news")
    p_src.set_defaults(func=cmd_sources)

    p_bt = sub.add_parser("backtest", help="walk-forward grade of engine plans")
    p_bt.add_argument("--symbol", default=SYMBOL)
    p_bt.add_argument("--tf", default=TIMEFRAME)
    p_bt.add_argument("--bars", type=int, default=BARS)
    p_bt.add_argument("--horizons", default="1,4,24", help="comma-separated hours, e.g. 1,4,24")
    p_bt.add_argument("--min-conf", type=int, default=MIN_CONFIDENCE)
    p_bt.add_argument("--save", action="store_true", help="store graded outcomes in the signal database")
    p_bt.set_defaults(func=cmd_backtest)

    p_stats = sub.add_parser("stats", help="what the engine has learned (DB + backtests)")
    p_stats.add_argument("--symbol", default=None)
    p_stats.set_defaults(func=cmd_stats)

    p_rev = sub.add_parser("review", help="list signals awaiting human approval")
    p_rev.add_argument("--symbol", default=None)
    p_rev.set_defaults(func=cmd_review)

    p_app = sub.add_parser("approve", help="approve a pending signal")
    p_app.add_argument("scan_id", type=int)
    p_app.add_argument("--note", default="")
    p_app.set_defaults(func=cmd_approve)

    p_rej = sub.add_parser("reject", help="reject a pending signal")
    p_rej.add_argument("scan_id", type=int)
    p_rej.add_argument("--note", default="")
    p_rej.set_defaults(func=cmd_reject)

    p_exec = sub.add_parser("execute", help="mark an approved signal as executed")
    p_exec.add_argument("scan_id", type=int)
    p_exec.add_argument("--note", default="")
    p_exec.set_defaults(func=cmd_execute)

    p_close = sub.add_parser("close", help="close an executed signal (outcome recorded)")
    p_close.add_argument("scan_id", type=int)
    p_close.add_argument("--note", default="")
    p_close.set_defaults(func=cmd_close)

    p_sig = sub.add_parser("signal", help="show a signal's full detail + lifecycle")
    p_sig.add_argument("scan_id", type=int)
    p_sig.set_defaults(func=cmd_signal)

    p_learn = sub.add_parser("learn", help="recompute the self-improvement calibration profile")
    p_learn.add_argument("--json", action="store_true")
    p_learn.set_defaults(func=cmd_learn)

    p_coach = sub.add_parser("coach", help="teaching mode: explain + mentor + personal feedback")
    p_coach.add_argument("--symbol", default=SYMBOL)
    p_coach.add_argument("--tf", default=TIMEFRAME)
    p_coach.add_argument("--bars", type=int, default=BARS)
    p_coach.add_argument("--term", default=None, help="explain a glossary term (e.g. FVG)")
    p_coach.set_defaults(func=cmd_coach)

    p_gl = sub.add_parser("glossary", help="list trading terms used by the engine")
    p_gl.add_argument("term", nargs="?", default=None)
    p_gl.set_defaults(func=cmd_glossary)

    p_web = sub.add_parser("web", help="run the web dashboard")
    p_web.add_argument("--host", default=None)
    p_web.add_argument("--port", type=int, default=None)
    p_web.set_defaults(func=cmd_web)

    args = ap.parse_args()
    if args.cmd == "scan" and args.symbols is None:
        args.symbols = args.symbol
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
