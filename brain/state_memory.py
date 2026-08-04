"""brain/state_memory.py — the trader's memory.

A human trader does NOT generate a new signal every 30 seconds. They hold a
view, update it when the market *state* changes, and only act when a setup is
fresh. This module gives the AI that same behaviour:

* It fingerprints the current market state (HTF bias, alignment, structure
  event, style directions, price location).
* If the fingerprint is unchanged → the signal is REAFFIRMED, not re-emitted.
  The dashboard shows "signal stable since 14:02" instead of a fresh signal.
* If it changes → NEW / UPDATED / FLIP, with per-style cooldowns, so a style
  can only fire again after its cooldown (Scalp 15m, Day 1h, Swing 4h,
  Momentum 1h, Position 24h).
* Whipsaw guard: if the HTF bias flips too often within an hour, signals are
  suppressed (the classic "don't trade chop" rule).

State lives in SQLite (`market_state` + `state_events`), so memory survives
restarts — the AI genuinely remembers what it said last time.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Optional

from config import SIGNAL_COOLDOWN_MINUTES, FLIP_PRICE_THRESHOLD_PCT, MAX_FLIPS_PER_HOUR
from .styles import STYLE_COOLDOWN_MIN, ORDER


def _fp_components(mtf: dict, styles: dict, f: dict) -> dict:
    """The state features that matter for a *new* signal decision."""
    htf = mtf.get("htf_bias", "neutral")
    align = mtf.get("alignment", {}).get("label", "mixed")
    event = f.get("event_kind")
    styles_on = tuple(sorted(s for s, v in styles.items() if v.get("available")))
    dirs = tuple(sorted(f"{s}:{styles[s].get('direction')}" for s in styles_on))
    price = f.get("price") or 0.0
    swing_hi = f.get("swing_high")
    swing_lo = f.get("swing_low")
    zone = f.get("premium_discount")
    bucket = "above" if (swing_hi and price > swing_hi) else "below" if (swing_lo and price < swing_lo) else "inside"
    return {
        "htf": htf, "align": align, "event": event,
        "styles_on": styles_on, "dirs": dirs, "zone": zone, "bucket": bucket,
    }


def _fingerprint(parts: dict) -> str:
    blob = json.dumps(parts, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _now_ms() -> int:
    return int(time.time() * 1000)


class SignalMemory:
    def __init__(self, db=None):
        if db is None:
            from data.database import SignalDB
            db = SignalDB()
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        self.db.conn.executescript("""
        CREATE TABLE IF NOT EXISTS market_state(
          symbol TEXT, timeframe TEXT,
          state_hash TEXT, htf_bias TEXT, alignment TEXT, last_event TEXT,
          price REAL, updated_at INTEGER, reaffirms INTEGER DEFAULT 0,
          flips_1h INTEGER DEFAULT 0, last_flip_at INTEGER,
          styles_json TEXT, last_signal_json TEXT,
          PRIMARY KEY(symbol, timeframe)
        );
        CREATE TABLE IF NOT EXISTS state_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          symbol TEXT, timeframe TEXT, kind TEXT, detail TEXT, ts INTEGER
        );
        """)
        self.db.conn.commit()

    # ── state persistence ────────────────────────────────────────────────
    def get_state(self, symbol: str, tf: str) -> Optional[dict]:
        row = self.db.conn.execute(
            "SELECT * FROM market_state WHERE symbol=? AND timeframe=?",
            (symbol, tf)).fetchone()
        return dict(row) if row else None

    def _put_state(self, symbol, tf, state: dict) -> None:
        self.db.conn.execute(
            """INSERT INTO market_state
               (symbol, timeframe, state_hash, htf_bias, alignment, last_event,
                price, updated_at, reaffirms, flips_1h, last_flip_at,
                styles_json, last_signal_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(symbol, timeframe) DO UPDATE SET
                 state_hash=excluded.state_hash, htf_bias=excluded.htf_bias,
                 alignment=excluded.alignment, last_event=excluded.last_event,
                 price=excluded.price, updated_at=excluded.updated_at,
                 reaffirms=excluded.reaffirms, flips_1h=excluded.flips_1h,
                 last_flip_at=excluded.last_flip_at,
                 styles_json=excluded.styles_json,
                 last_signal_json=excluded.last_signal_json""",
            (symbol, tf, state["state_hash"], state["htf_bias"], state["alignment"],
             state["last_event"], state["price"], state["updated_at"],
             state["reaffirms"], state["flips_1h"], state["last_flip_at"],
             state["styles_json"], state["last_signal_json"]))
        self.db.conn.commit()

    def _log_event(self, symbol, tf, kind, detail) -> None:
        self.db.conn.execute(
            "INSERT INTO state_events(symbol, timeframe, kind, detail, ts) VALUES (?,?,?,?,?)",
            (symbol, tf, kind, detail, _now_ms()))
        self.db.conn.commit()

    def history(self, symbol: str | None = None, tf: str | None = None, limit: int = 30) -> list[dict]:
        q = "SELECT * FROM state_events"
        conds, args = [], []
        if symbol:
            conds.append("symbol=?")
            args.append(symbol)
        if tf:
            conds.append("timeframe=?")
            args.append(tf)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.db.conn.execute(q, args).fetchall()]

    # ── the decision ─────────────────────────────────────────────────────
    def update(self, symbol: str, tf: str, mtf: dict, styles: dict,
               frame: dict) -> dict:
        """Reconcile the current analysis with what the AI remembered.

        Returns a dict describing what happened:
          status: 'NEW' | 'FLIP' | 'UPDATED' | 'SAME'
          fresh_styles: styles that may fire now (past cooldown, state changed)
          changes: human-readable list of what changed
          stable_since: epoch ms of when the current state began
          reaffirms: how many refreshes the same state has been reaffirmed
        """
        f = frame.get("snapshot", {}).get("features", {})
        now = _now_ms()
        style_map = styles.get("styles", {}) if isinstance(styles, dict) else {}
        parts = _fp_components(mtf, style_map, f)
        fp = _fingerprint(parts)
        prev = self.get_state(symbol, tf)

        htf_flip = prev and prev["htf_bias"] != parts["htf"] and parts["htf"] != "neutral"
        # pricestill inside previous state's range?
        price = f.get("price") or 0.0

        # Build per-style memory (since_ts + last fired)
        prev_styles = {}
        if prev and prev.get("styles_json"):
            try:
                prev_styles = json.loads(prev["styles_json"])
            except Exception:
                prev_styles = {}

        changes = []
        status = "SAME"
        if prev is None:
            status = "NEW"
            changes.append("first observation of this market state")
        elif htf_flip:
            status = "FLIP"
            changes.append(f"HTF bias flipped to {parts['htf']}")
        elif prev["state_hash"] != fp:
            status = "UPDATED"
            if prev.get("last_event") != parts["event"]:
                changes.append(f"structure event: {parts['event']}")
            prev_on = set(json.loads(prev.get("styles_json") or "{}").get("__on", [])) \
                if prev.get("styles_json") else set()
            new_on = set(parts["styles_on"])
            if new_on != prev_on:
                added = new_on - prev_on
                removed = prev_on - new_on
                if added:
                    changes.append(f"new setup(s): {', '.join(sorted(added))}")
                if removed:
                    changes.append(f"setup(s) gone: {', '.join(sorted(removed))}")
            if not changes:
                changes.append("market state changed (levels/zone moved)")
        else:
            # same fingerprint → reaffirm; roll a fresh flip window
            if prev.get("last_flip_at") and now - prev.get("last_flip_at", 0) > 3600_000:
                flips = 0
            else:
                flips = prev.get("flips_1h", 0)
            self._put_state(symbol, tf, {
                **prev,
                "price": price,
                "updated_at": now,
                "reaffirms": prev.get("reaffirms", 0) + 1,
                "flips_1h": flips,
                "last_flip_at": prev.get("last_flip_at"),
                "state_hash": fp,
                "htf_bias": parts["htf"],
                "alignment": parts["align"],
                "last_event": parts["event"],
                "styles_json": prev.get("styles_json", "{}"),
                "last_signal_json": prev.get("last_signal_json", "{}"),
            })
            return {
                "status": "SAME",
                "fresh_styles": [],
                "changes": [],
                "stable_since": prev.get("updated_at"),
                "reaffirms": prev.get("reaffirms", 0) + 1,
                "stand_aside": styles.get("stand_aside", []),
            }

        # ── fresh state: decide which styles may fire ────────────────────
        flips_1h = prev.get("flips_1h", 0) if prev else 0
        last_flip_at = prev.get("last_flip_at") if prev else None
        if status == "FLIP":
            if last_flip_at and now - last_flip_at <= 3600_000:
                flips_1h += 1
            else:
                flips_1h = 1
            last_flip_at = now
        elif prev and last_flip_at and now - last_flip_at > 3600_000:
            flips_1h = 0

        whipsaw = flips_1h >= MAX_FLIPS_PER_HOUR
        if whipsaw:
            changes.append(f"⚠️ whipsaw guard: {flips_1h} HTF flips in the last hour — signals suppressed")

        # per-style cooldowns
        fresh: list[str] = []
        style_mem = {}
        for s in ORDER:
            info = prev_styles.get(s, {})
            last_fired = info.get("last_ts", 0)
            cd = STYLE_COOLDOWN_MIN.get(s, 60) * 60_000
            if not whipsaw:
                fired_before = bool(last_fired)
                due = (now - last_fired) >= cd if fired_before else True
                if due:
                    fresh.append(s)
            style_mem[s] = {
                "since_ts": info.get("since_ts"),
                "last_ts": last_fired,
                "cooldown_min": STYLE_COOLDOWN_MIN.get(s, 60),
            }

        # stamp the fresh styles with since_ts and record last_ts
        for s in fresh:
            style_mem[s]["since_ts"] = now
            style_mem[s]["last_ts"] = now
        for s in style_map:
            if s in style_mem:
                style_map[s]["since_ts"] = style_mem[s]["since_ts"]

        styles_json = {s: style_mem[s] for s in ORDER}
        styles_json["__on"] = list(parts["styles_on"])

        state = {
            "state_hash": fp, "htf_bias": parts["htf"], "alignment": parts["align"],
            "last_event": parts["event"], "price": price, "updated_at": now,
            "reaffirms": 0, "flips_1h": flips_1h, "last_flip_at": last_flip_at,
            "styles_json": json.dumps(styles_json),
            "last_signal_json": json.dumps({
                "status": status, "htf": parts["htf"], "align": parts["align"],
                "event": parts["event"], "styles_on": list(parts["styles_on"]),
            }),
        }
        self._put_state(symbol, tf, state)
        self._log_event(symbol, tf, status,
                        "; ".join(changes) if changes else "state changed")

        # stable_since = when this fingerprint first appeared
        stable_since = now
        return {
            "status": status,
            "fresh_styles": fresh,
            "changes": changes,
            "stable_since": stable_since,
            "reaffirms": 0,
            "flips_1h": flips_1h,
            "whipsaw": whipsaw,
            "stand_aside": styles.get("stand_aside", []),
        }
