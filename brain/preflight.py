"""Production preflight for unattended, live-data paper trading.

``health`` answers "can the application run?".  This module answers the
stricter operations question: "is this host safely configured to collect real
paper-trading evidence unattended?"

The preflight never places an order and never reads exchange credentials.  It
fails closed when live feeds are missing/stale, core safety controls are off,
or the host is not in simulator progression.  Non-critical integrations (LLM,
MCP, notifications, one unavailable cross-check exchange) are warnings.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import config

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

# A 15-minute Binance candle may still be open.  Two full candle intervals is
# enough clock/network tolerance while still detecting an abandoned feed.
DEFAULT_MAX_CANDLE_AGE_SECONDS = 30 * 60


def _check(name: str, status: str, message: str, **details: Any) -> dict:
    row = {"name": name, "status": status, "message": message}
    if details:
        row["details"] = details
    return row


def _credential_names() -> list[str]:
    """Return names (never values) of unnecessary exchange secrets in env."""
    names = (
        "BINANCE_API_KEY", "BINANCE_SECRET_KEY", "BINANCE_API_SECRET",
        "EXCHANGE_API_KEY", "EXCHANGE_API_SECRET",
    )
    return [name for name in names if os.getenv(name)]


def _cross_exchange_check(cross: dict) -> dict:
    flagged: list[str] = []
    compared = 0
    available = 0
    for exchange, payload in (cross.get("exchanges") or {}).items():
        if payload.get("ok"):
            available += 1
        for symbol, info in (payload.get("symbols") or {}).items():
            if "deviation_pct" in info:
                compared += 1
            if info.get("flag"):
                flagged.append(
                    f"{exchange}:{symbol} {float(info.get('deviation_pct', 0)):+.2f}%"
                )
    if flagged:
        return _check(
            "cross_exchange", FAIL,
            "price deviation exceeds the 1% safety threshold",
            flagged=flagged,
        )
    if not cross.get("exchanges") or available == 0 or compared == 0:
        return _check(
            "cross_exchange", WARN,
            "no independent exchange price comparison is currently available",
        )
    if not cross.get("ok"):
        return _check(
            "cross_exchange", WARN,
            f"price comparison passed, but only {available} cross-check exchange(s) responded",
            compared=compared,
        )
    return _check(
        "cross_exchange", PASS,
        f"independent prices agree within 1% ({compared} comparisons)",
    )


def preflight_report(
    *,
    health: dict | None = None,
    allow_demo: bool = False,
    max_candle_age_seconds: int = DEFAULT_MAX_CANDLE_AGE_SECONDS,
) -> dict:
    """Return a JSON-safe paper-operations readiness report.

    Args:
        health: Optional injected health report, mainly for deterministic tests.
        allow_demo: Permit sample/synthetic feeds for a local rehearsal.  Demo
            mode is never presented as live evidence.
        max_candle_age_seconds: Maximum live 15m candle age before failing.
    """
    if health is None:
        from brain.agent import health_report
        health = health_report()

    checks: list[dict] = []
    data = health.get("data") or {}
    mode = str(data.get("mode") or "unknown").lower()
    is_live = mode == "live"
    is_rehearsal = allow_demo and mode == "demo"

    if is_live:
        checks.append(_check("data_mode", PASS, "live public market data enabled"))
    elif allow_demo and mode == "demo":
        checks.append(_check(
            "data_mode", WARN,
            "demo data allowed for rehearsal; results are not live paper evidence",
        ))
    else:
        checks.append(_check(
            "data_mode", FAIL,
            "live data required; set DEMO_MODE=0 (or use --allow-demo only for rehearsal)",
            detected=mode,
        ))

    probes = data.get("probe") or {}
    expected = list(config.SYMBOLS)
    missing = [symbol for symbol in expected if symbol not in probes]
    failed = [symbol for symbol in expected if not (probes.get(symbol) or {}).get("ok")]
    if missing or failed:
        checks.append(_check(
            "market_feeds", FAIL,
            "every configured watchlist feed must respond",
            missing=missing,
            failed=failed,
        ))
    else:
        checks.append(_check(
            "market_feeds", PASS,
            f"all {len(expected)} watchlist feeds responded",
            symbols=expected,
        ))

    if is_live and not missing and not failed:
        stale: list[str] = []
        future: list[str] = []
        unknown: list[str] = []
        for symbol in expected:
            age = (probes.get(symbol) or {}).get("age_seconds")
            if age is None:
                unknown.append(symbol)
            elif float(age) < -60:
                future.append(f"{symbol} {-float(age):.1f}s ahead")
            elif float(age) > max(1, max_candle_age_seconds):
                stale.append(f"{symbol} {float(age) / 60:.1f}m")
        if stale or future or unknown:
            checks.append(_check(
                "candle_freshness", FAIL,
                "live candle timestamps are stale, future-dated, or unavailable",
                stale=stale,
                future=future,
                unknown=unknown,
                max_age_seconds=max_candle_age_seconds,
                max_future_skew_seconds=60,
            ))
        else:
            checks.append(_check(
                "candle_freshness", PASS,
                f"all live candles are newer than {max_candle_age_seconds // 60} minutes",
            ))
    else:
        checks.append(_check(
            "candle_freshness", WARN,
            "freshness certification applies only to healthy live feeds",
        ))

    database = health.get("database") or {}
    if database.get("ok"):
        checks.append(_check(
            "database", PASS,
            "SQLite learning store opened and schema queries succeeded",
            path=database.get("path"),
        ))
    else:
        checks.append(_check(
            "database", FAIL,
            "SQLite learning store is unavailable",
            error=database.get("error", "unknown error"),
            path=database.get("path"),
        ))

    db_path_raw = database.get("path") or config.DB_PATH
    try:
        db_path = Path(db_path_raw).expanduser().resolve()
        checkout = Path(config.ROOT).resolve()
        in_checkout = db_path == checkout or checkout in db_path.parents
        ephemeral_roots = tuple(
            Path(root).resolve() for root in ("/tmp", "/var/tmp", "/dev/shm")
        )
        ephemeral = any(db_path == root or root in db_path.parents for root in ephemeral_roots)
    except (OSError, TypeError, ValueError):
        db_path = None
        in_checkout = True
        ephemeral = False
    unsafe_location = in_checkout or ephemeral
    if not unsafe_location:
        checks.append(_check(
            "database_location", PASS,
            "learning store is in a durable location outside the application checkout",
            path=str(db_path),
        ))
    elif is_rehearsal:
        checks.append(_check(
            "database_location", WARN,
            "non-durable storage is acceptable only for a disposable demo rehearsal",
            path=str(db_path_raw),
        ))
    else:
        checks.append(_check(
            "database_location", FAIL,
            "production paper evidence requires durable storage outside the Git checkout",
            path=str(db_path_raw),
            issue="inside checkout" if in_checkout else "temporary filesystem",
            recommended="/var/lib/cryptobrain/cryptobrain.db",
        ))

    if config.PROGRESSION == "simulator":
        checks.append(_check(
            "progression", PASS,
            "PROGRESSION=simulator; unproven setups remain paper-only",
        ))
    else:
        checks.append(_check(
            "progression", FAIL,
            "unattended evidence collection requires PROGRESSION=simulator",
            detected=config.PROGRESSION,
        ))

    disabled_controls = []
    if not config.ENFORCE_RISK_LIMITS:
        disabled_controls.append("ENFORCE_RISK_LIMITS")
    if not config.TRADER_STATE_BLOCK:
        disabled_controls.append("TRADER_STATE_BLOCK")
    if disabled_controls:
        checks.append(_check(
            "risk_controls", FAIL,
            "mandatory risk/behavior controls are disabled",
            disabled=disabled_controls,
        ))
    else:
        checks.append(_check(
            "risk_controls", PASS,
            "risk limits and behavioral no-trade gate are enforced",
        ))

    if config.DESK_DEFAULT and config.PRIMARY_SETUP_FAMILY != "all":
        checks.append(_check(
            "desk_policy", PASS,
            f"desk-first output narrowed to {config.PRIMARY_SETUP_FAMILY}",
        ))
    else:
        checks.append(_check(
            "desk_policy", FAIL,
            "production paper evidence requires DESK_DEFAULT=true and one primary setup family",
            desk_default=config.DESK_DEFAULT,
            primary_setup_family=config.PRIMARY_SETUP_FAMILY,
        ))

    gold_enabled = "XAUUSD" in expected
    if not gold_enabled:
        checks.append(_check("gold_session", PASS, "gold is not in the watchlist"))
    elif config.GOLD_SESSION_MODE == "block":
        checks.append(_check(
            "gold_session", PASS,
            "gold entries are blocked outside London/New York windows",
        ))
    elif is_live:
        checks.append(_check(
            "gold_session", FAIL,
            "live XAUUSD monitoring requires GOLD_SESSION_MODE=block",
            detected=config.GOLD_SESSION_MODE,
        ))
    else:
        checks.append(_check(
            "gold_session", WARN,
            "set GOLD_SESSION_MODE=block before switching this rehearsal to live data",
            detected=config.GOLD_SESSION_MODE,
        ))

    checks.append(_cross_exchange_check(data.get("cross_exchange") or {}))

    gate = health.get("risk_gate") or {}
    if not gate.get("progression"):
        checks.append(_check(
            "risk_gate", FAIL,
            "risk gate status could not be evaluated",
            blocked_by=gate.get("blocked_by", []),
        ))
    elif gate.get("allowed"):
        checks.append(_check("risk_gate", PASS, "risk gate is currently open"))
    else:
        # A closed gate is a normal capital-protection state.  The monitor can
        # keep managing existing paper trades, but will not enroll new ones.
        checks.append(_check(
            "risk_gate", WARN,
            "risk gate is closed; existing paper trades remain monitored but no new trades enroll",
            blocked_by=gate.get("blocked_by", []),
        ))

    host = str(config.DASHBOARD_HOST).strip().lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        checks.append(_check(
            "dashboard_binding", PASS,
            "dashboard is bound to loopback only",
        ))
    else:
        checks.append(_check(
            "dashboard_binding", WARN,
            "dashboard is not loopback-only; use 127.0.0.1 plus an authenticated reverse proxy",
            detected=config.DASHBOARD_HOST,
        ))

    credentials = _credential_names()
    if credentials:
        checks.append(_check(
            "exchange_credentials", WARN,
            "paper trading does not need exchange secrets; remove them from this service environment",
            names=credentials,
        ))
    else:
        checks.append(_check(
            "exchange_credentials", PASS,
            "no exchange-order credentials detected or required",
        ))

    notifiers = bool(
        (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)
        or config.DISCORD_ANNOUNCE_WEBHOOK
    )
    if notifiers:
        checks.append(_check("notifications", PASS, "an outbound alert channel is configured"))
    else:
        checks.append(_check(
            "notifications", WARN,
            "no Telegram/Discord alert channel configured; rely on system logs and dashboard",
        ))

    failures = sum(row["status"] == FAIL for row in checks)
    warnings = sum(row["status"] == WARN for row in checks)
    return {
        "ready": failures == 0,
        "profile": "paper-rehearsal" if is_rehearsal else "live-paper",
        "data_mode": mode,
        "checks": checks,
        "summary": {
            "passed": sum(row["status"] == PASS for row in checks),
            "warnings": warnings,
            "failures": failures,
            "total": len(checks),
        },
    }


def format_preflight(report: dict) -> str:
    """Format a concise terminal report without hiding blockers."""
    lines = [
        "=" * 72,
        f"PAPER OPERATIONS PREFLIGHT — {str(report.get('profile', '')).upper()}",
        "-" * 72,
    ]
    icons = {PASS: "✓", WARN: "!", FAIL: "✗"}
    for row in report.get("checks", []):
        status = row.get("status", "?")
        lines.append(
            f"  {icons.get(status, '?')} {row.get('name', '?'):<22} "
            f"{status:<4}  {row.get('message', '')}"
        )
        details = row.get("details") or {}
        if details:
            bits = [f"{key}={value}" for key, value in details.items() if value not in (None, [], {})]
            if bits:
                lines.append("      " + " · ".join(bits))
    summary = report.get("summary") or {}
    lines.extend([
        "-" * 72,
        f"  {summary.get('passed', 0)} passed · {summary.get('warnings', 0)} warnings · "
        f"{summary.get('failures', 0)} failures",
        f"  VERDICT: {'READY FOR PAPER OPERATIONS' if report.get('ready') else 'BLOCKED — FIX FAILURES BEFORE STARTING'}",
    ])
    return "\n".join(lines)
