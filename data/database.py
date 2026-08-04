"""data/database.py

SQLite learning store for the CryptoBrain engine.

Tables
------
scans            : one row per engine run (signal + reason + feature snapshot)
plans            : the conditional plans each scan produced
backtest_results : per-plan outcomes from the walk-forward backtester

The point of this store: accumulate every scan and every graded backtest
outcome, then answer questions like
  * "Which plan types actually win most often?"
  * "Does confidence >= 80 beat confidence 55-60?"
  * "Do BUY setups on the 15m beat SELL setups?"

No extra dependencies — stdlib sqlite3.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER, symbol TEXT, timeframe TEXT, price REAL,
  action TEXT, entry REAL, stop_loss REAL, take_profit REAL,
  risk_reward REAL, confidence_label TEXT, confidence_pct INTEGER,
  reason TEXT, signal_type TEXT,
  features_json TEXT, plans_json TEXT, context_json TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS plans(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id INTEGER NOT NULL,
  plan_id TEXT, type TEXT, action TEXT, condition TEXT,
  trigger_level REAL, entry REAL, stop_loss REAL,
  tp1 REAL, tp2 REAL, risk_reward REAL,
  confidence_pct INTEGER, confidence_label TEXT, status TEXT,
  FOREIGN KEY(scan_id) REFERENCES scans(id)
);
CREATE TABLE IF NOT EXISTS backtest_results(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT, ts INTEGER, symbol TEXT, timeframe TEXT,
  plan_type TEXT, action TEXT, confidence_pct INTEGER,
  horizon_hours REAL, outcome TEXT,
  rr_achieved REAL, max_favorable REAL, max_adverse REAL,
  entry REAL, trigger_level REAL
);
CREATE TABLE IF NOT EXISTS decisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id INTEGER NOT NULL,
  from_state TEXT, to_state TEXT,
  reviewer TEXT DEFAULT 'human',
  note TEXT,
  ts INTEGER,
  FOREIGN KEY(scan_id) REFERENCES scans(id)
);
CREATE TABLE IF NOT EXISTS calibration(
  plan_type TEXT PRIMARY KEY,
  multiplier REAL, expectancy REAL, samples INTEGER,
  updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_plans_scan ON plans(scan_id);
CREATE INDEX IF NOT EXISTS idx_bt_type ON backtest_results(plan_type);
CREATE INDEX IF NOT EXISTS idx_bt_outcome ON backtest_results(outcome);
CREATE INDEX IF NOT EXISTS idx_decisions_scan ON decisions(scan_id);
"""


class SignalDB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Path(DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ── migration ────────────────────────────────────────────────────────
    def _migrate(self) -> None:
        """Add lifecycle columns to pre-existing DBs (idempotent)."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(scans)")}
        if "status" not in cols:
            self.conn.execute("ALTER TABLE scans ADD COLUMN status TEXT DEFAULT 'PENDING_REVIEW'")
        if "lifecycle_ts" not in cols:
            self.conn.execute("ALTER TABLE scans ADD COLUMN lifecycle_ts INTEGER")
        if "approve_note" not in cols:
            self.conn.execute("ALTER TABLE scans ADD COLUMN approve_note TEXT")

    # ── lifecycle ────────────────────────────────────────────────────────
    def update_status(self, scan_id: int, to_state: str, note: str = "",
                      reviewer: str = "human") -> Optional[str]:
        """Transition a scan's lifecycle state and log a decision row.
        Returns the new state, or None if the scan doesn't exist."""
        row = self.conn.execute("SELECT status FROM scans WHERE id=?", (scan_id,)).fetchone()
        if row is None:
            return None
        from engine.lifecycle import transition, LifecycleError
        try:
            new_state = transition(row["status"], to_state)
        except LifecycleError as exc:
            raise LifecycleError(exc.message) from None
        self.conn.execute(
            "UPDATE scans SET status=?, lifecycle_ts=? WHERE id=?",
            (new_state, int(time.time() * 1000), scan_id))
        self.conn.execute(
            "INSERT INTO decisions(scan_id, from_state, to_state, reviewer, note, ts) "
            "VALUES (?,?,?,?,?,?)",
            (scan_id, row["status"], new_state, reviewer, note, int(time.time() * 1000)))
        self.conn.commit()
        return new_state

    def pending_reviews(self, symbol: str | None = None) -> list[dict]:
        """Signals awaiting human approval, newest first."""
        q = ("SELECT s.*, (SELECT COUNT(*) FROM plans p WHERE p.scan_id=s.id) n_plans "
             "FROM scans s WHERE s.status='PENDING_REVIEW' AND s.action IN ('BUY','SELL')")
        args: tuple = ()
        if symbol:
            q += " AND s.symbol=?"
            args = (symbol,)
        q += " ORDER BY s.ts DESC LIMIT 30"
        return [dict(r) for r in self.conn.execute(q, args).fetchall()]

    def decision_history(self, scan_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT from_state, to_state, reviewer, note, ts FROM decisions "
            "WHERE scan_id=? ORDER BY ts", (scan_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_scan(self, scan_id: int) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        return dict(row) if row else None

    # ── calibration (self-improvement profile) ───────────────────────────
    def save_calibration(self, profile: dict) -> None:
        now = int(time.time() * 1000)
        for plan_type, entry in profile.items():
            self.conn.execute(
                """INSERT INTO calibration(plan_type, multiplier, expectancy, samples, updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(plan_type) DO UPDATE SET
                     multiplier=excluded.multiplier, expectancy=excluded.expectancy,
                     samples=excluded.samples, updated_at=excluded.updated_at""",
                (plan_type, entry.get("multiplier", 1.0),
                 entry.get("expectancy"), entry.get("samples", 0), now))
        self.conn.commit()

    def load_calibration(self) -> dict:
        rows = self.conn.execute("SELECT * FROM calibration").fetchall()
        return {r["plan_type"]: {"multiplier": r["multiplier"],
                                 "expectancy": r["expectancy"],
                                 "samples": r["samples"]} for r in rows}

    # ── scans ────────────────────────────────────────────────────────────
    def save_scan(self, payload: dict) -> int:
        """Persist one engine output (signal + plans + snapshot). Returns scan id."""
        sig = payload.get("signal", {})
        snap = payload.get("snapshot", {})
        features = snap.get("features", {})
        plans = payload.get("plans", [])
        from engine.lifecycle import reviewable
        status = "PENDING_REVIEW" if reviewable(sig) else "CREATED"
        cur = self.conn.execute(
            """INSERT INTO scans
               (ts, symbol, timeframe, price, action, entry, stop_loss, take_profit,
                risk_reward, confidence_label, confidence_pct, reason, signal_type,
                features_json, plans_json, context_json, status, lifecycle_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sig.get("timestamp") or int(time.time() * 1000),
                sig.get("asset", ""),
                sig.get("timeframe", ""),
                features.get("price"),
                sig.get("action"),
                sig.get("entry"),
                sig.get("stop_loss"),
                sig.get("take_profit"),
                sig.get("risk_reward"),
                sig.get("confidence"),
                features.get("score_used"),
                sig.get("reason", ""),
                sig.get("signal_type", ""),
                json.dumps(features, default=str),
                json.dumps(plans, default=str),
                json.dumps(payload.get("market_context", {}), default=str),
                status,
                int(time.time() * 1000),
            ),
        )
        scan_id = cur.lastrowid
        for p in plans:
            tps = p.get("take_profits") or []
            self.conn.execute(
                """INSERT INTO plans
                   (scan_id, plan_id, type, action, condition, trigger_level,
                    entry, stop_loss, tp1, tp2, risk_reward, confidence_pct,
                    confidence_label, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    scan_id, p.get("id"), p.get("type"), p.get("action"),
                    p.get("condition"), p.get("trigger_level"), p.get("entry"),
                    p.get("stop_loss"), tps[0] if len(tps) > 0 else None,
                    tps[1] if len(tps) > 1 else None, p.get("risk_reward"),
                    p.get("confidence"), p.get("confidence_label"), p.get("status"),
                ),
            )
        self.conn.commit()
        return scan_id

    def latest_scans(self, symbol: str | None = None, limit: int = 20) -> list[dict]:
        q = "SELECT * FROM scans"
        args: tuple = ()
        if symbol:
            q += " WHERE symbol = ?"
            args = (symbol,)
        q += " ORDER BY ts DESC LIMIT ?"
        rows = self.conn.execute(q, args + (limit,)).fetchall()
        return [dict(r) for r in rows]

    def plan_stats(self) -> list[dict]:
        """Plan-type distribution from real (live) scans."""
        rows = self.conn.execute(
            """SELECT type, action, COUNT(*) n,
                      ROUND(AVG(confidence_pct),1) avg_conf,
                      ROUND(AVG(risk_reward),2) avg_rr
               FROM plans GROUP BY type, action ORDER BY n DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    # ── backtest results ─────────────────────────────────────────────────
    def save_backtest_rows(self, rows: list[dict], run_id: str) -> int:
        n = 0
        for r in rows:
            self.conn.execute(
                """INSERT INTO backtest_results
                   (run_id, ts, symbol, timeframe, plan_type, action,
                    confidence_pct, horizon_hours, outcome, rr_achieved,
                    max_favorable, max_adverse, entry, trigger_level)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, r.get("ts"), r.get("symbol"), r.get("timeframe"),
                 r.get("plan_type"), r.get("action"), r.get("confidence_pct"),
                 r.get("horizon_hours"), r.get("outcome"), r.get("rr_achieved"),
                 r.get("max_favorable"), r.get("max_adverse"), r.get("entry"),
                 r.get("trigger_level")),
            )
            n += 1
        self.conn.commit()
        return n

    def backtest_stats(self) -> dict:
        """Win-rate learning: by plan type and by confidence bucket."""
        def agg(where: str = "") -> dict:
            q = f"""SELECT COUNT(*) n,
                           SUM(CASE WHEN outcome IN ('WIN','FULL_WIN','PARTIAL_WIN') THEN 1 ELSE 0 END) wins,
                           SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) losses,
                           SUM(CASE WHEN outcome='OPEN' THEN 1 ELSE 0 END) opens,
                           SUM(CASE WHEN outcome='NOT_TRIGGERED' THEN 1 ELSE 0 END) not_triggered,
                           ROUND(AVG(rr_achieved),2) avg_rr
                    FROM backtest_results {where}"""
            row = dict(self.conn.execute(q).fetchone())
            decided = row["wins"] + row["losses"]
            row["win_rate"] = round(row["wins"] / decided, 3) if decided else None
            row["n"] = row["n"] or 0
            return row

        by_type = [dict(r) for r in self.conn.execute(
            """SELECT plan_type, COUNT(*) n,
                      SUM(CASE WHEN outcome IN ('WIN','FULL_WIN','PARTIAL_WIN') THEN 1 ELSE 0 END) wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) losses,
                      ROUND(AVG(rr_achieved),2) avg_rr
               FROM backtest_results GROUP BY plan_type ORDER BY n DESC""").fetchall()]
        for r in by_type:
            decided = (r["wins"] or 0) + (r["losses"] or 0)
            r["win_rate"] = round(r["wins"] / decided, 3) if decided else None

        by_conf = [dict(r) for r in self.conn.execute(
            """SELECT CASE WHEN confidence_pct >= 80 THEN 'HIGH'
                           WHEN confidence_pct >= 60 THEN 'MEDIUM'
                           ELSE 'LOW' END bucket,
                      COUNT(*) n,
                      SUM(CASE WHEN outcome IN ('WIN','FULL_WIN','PARTIAL_WIN') THEN 1 ELSE 0 END) wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) losses,
                      ROUND(AVG(rr_achieved),2) avg_rr
               FROM backtest_results GROUP BY bucket""").fetchall()]
        for r in by_conf:
            decided = (r["wins"] or 0) + (r["losses"] or 0)
            r["win_rate"] = round(r["wins"] / decided, 3) if decided else None

        return {"overall": agg(), "by_type": by_type, "by_confidence": by_conf}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
