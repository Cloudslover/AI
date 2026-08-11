#!/usr/bin/env python3
"""mcp_server.py — Minimal, dependency-free Model Context Protocol (MCP) server.

Implements JSON-RPC 2.0 over stdio for LLM integration (Claude Desktop, Cursor,
Arena, and MCP clients). Exposes grounded trading tools while strictly enforcing
a read-only permission map (no automatic order placement or gate bypass).

TOOL PERMISSION MAP (single source of truth — see ALLOWED_TOOLS below).
Read-only / research tools only. Mutation paths (approve | reject | execute |
close | place_order | sign | withdraw | transfer) are NEVER in this map and
MUST NOT be added — the engine physically cannot be asked to trade. The
human-approval gate is the only path to action and lives in `brain/risk_gate.py`.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brain.ask import ask
from brain.brief import generate_morning_brief, post_trade_review
from brain.risk_gate import evaluate_risk_gate
from data.database import SignalDB
from data.symbols import normalize_symbol

SERVER_NAME = "cryptobrain-mcp"
SERVER_VERSION = "1.1.0"  # bumped: TODO-2 added 5 new tools (P9 capability endpoints)
PROTOCOL_VERSION = "2024-11-05"

# Read-only / research tools allowed. No order or approval bypass tools.
#
# Test contract: tests/test_mcp_stdio.py:ROOT_TOOLS is the canonical assertion
# of this set. If you add/remove a tool here, update ROOT_TOOLS too.
ALLOWED_TOOLS = {
    "ask": {
        "description": "Query grounded trading knowledge, setup expectancies, and playbooks with source citations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Question to answer (e.g. 'which setups have positive expectancy in ranging markets?')"}
            },
            "required": ["query"],
        },
    },
    "tradestate": {
        "description": "View or update behavioral trader flags (angry, tired, revenge, chasing).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "set", "clear"], "default": "get"},
                "angry": {"type": "boolean"},
                "tired": {"type": "boolean"},
                "revenge": {"type": "boolean"},
                "chasing": {"type": "boolean"},
                "note": {"type": "string"},
            },
        },
    },
    "risk": {
        "description": "Get current risk gate status, daily/weekly loss limits, and progression ladder.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    "health": {
        "description": "Run immune system health diagnostics and data freshness checks.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    "brief": {
        "description": "Generate cross-asset morning briefing across BTC, ETH, and GOLD.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbols": {"type": "array", "items": {"type": "string"}, "description": "List of symbols to brief"}
            },
        },
    },
    "postreview": {
        "description": "Generate post-trade review and MAE/MFE analytics for a scan ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scan_id": {"type": "integer", "description": "Database scan ID to review"}
            },
            "required": ["scan_id"],
        },
    },
    # ── P9: Capability endpoints (TODO-2). Same data as `python main.py` ──
    # All five are read-only wrappers around existing brain/engine library
    # functions. The dashboard, CLI, and MCP surface all read from the same
    # source-of-truth functions — no drift between surfaces.
    "channels": {
        "description": "Ordered-backend channel registry: per-source (cryptodada / discord / news / llm) active backend and probe status. Panniantong/Agent-Reach pattern. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    "correlation": {
        "description": "Measured BTC/ETH/GOLD rolling correlation matrix + ETH/BTC beta. Read-only analytics — the same as `python main.py correlation --json`.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbols": {"type": "array", "items": {"type": "string"}, "description": "Watchlist (default BTCUSDT,ETHUSDT,XAUUSD)"},
                "timeframe": {"type": "string", "default": "1h", "description": "Candle timeframe"},
                "bars": {"type": "integer", "default": 300, "description": "History length (max 1000)"},
                "window": {"type": "integer", "default": 60, "description": "Rolling window of aligned returns"},
            },
        },
    },
    "hidden_chart_read": {
        "description": "HMM latent regime + CVD order flow + Bayesian Kelly advisory for a single symbol. Read-only; the same as `python main.py hidden chart_read <SYMBOL>`. Not auto-executed — advisory only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT", "description": "Asset (aliases: BTC, ETH, XAU/GOLD)"},
                "timeframe": {"type": "string", "default": "15m"},
                "bars": {"type": "integer", "default": 500, "description": "History length"},
            },
        },
    },
    "hidden_analytics_mae": {
        "description": "MAE/MFE summary per setup from the paper-trade DB. Read-only; the same as `python main.py hidden analytics mae`. Surfaces where stops are too tight or targets unreachable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan_type": {"type": "string", "description": "Optional plan-type filter (e.g. 'Buy Pullback')"},
            },
        },
    },
    "hidden_analytics_mc": {
        "description": "Monte Carlo resampling of realized paper outcomes (terminal equity + drawdown distribution). Read-only; the same as `python main.py hidden analytics mc`. Advisory only — does not place orders.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "samples": {"type": "integer", "default": 2000, "description": "Number of Monte Carlo samples"},
                "seed": {"type": "integer", "description": "Optional RNG seed for reproducible runs"},
            },
        },
    },
}


def handle_tool_call(name: str, args: dict[str, Any]) -> dict:
    if name not in ALLOWED_TOOLS:
        raise ValueError(f"Tool '{name}' is not permitted or does not exist. (Permission map enforced: read-only tools only)")

    if name == "ask":
        query = args.get("query", "")
        res = ask(query)
        return res

    elif name == "tradestate":
        action = args.get("action", "get")
        with SignalDB() as db:
            if action == "clear":
                db.set_trader_state(angry=False, tired=False, revenge=False, chasing=False, note="cleared via MCP")
            elif action == "set":
                db.set_trader_state(
                    angry=args.get("angry"),
                    tired=args.get("tired"),
                    revenge=args.get("revenge"),
                    chasing=args.get("chasing"),
                    note=args.get("note", "updated via MCP"),
                )
            return db.get_trader_state()

    elif name == "risk":
        with SignalDB() as db:
            return evaluate_risk_gate(db)

    elif name == "health":
        from brain.immune import run_health_check
        return run_health_check()

    elif name == "brief":
        syms = args.get("symbols")
        return generate_morning_brief(symbols=syms)

    elif name == "postreview":
        scan_id = int(args.get("scan_id", 0))
        return post_trade_review(scan_id)

    # ── P9 capability endpoints (TODO-2) — read-only wrappers ─────────
    elif name == "channels":
        # Ordered-backend channel registry. Same data as /api/channels
        # and `python main.py channels --json`. Probe-isolated by
        # brain.channels.probe_all().
        from brain.channels import list_channels
        return list_channels(as_json=True)

    elif name == "correlation":
        # Measured cross-asset correlation + ETH/BTC beta. Read-only.
        from data.sample_client import maybe_client
        from engine.correlation import fetch_report
        client = maybe_client()
        syms = args.get("symbols")
        symbols = tuple(syms) if isinstance(syms, list) and syms else None
        return fetch_report(
            client,
            symbols=symbols,
            timeframe=args.get("timeframe", "1h"),
            bars=min(int(args.get("bars", 300)), 1000),
            window=int(args.get("window", 60)),
        )

    elif name == "hidden_chart_read":
        # HMM regime + CVD + Kelly advisory for one symbol. Read-only.
        from data.sample_client import maybe_client
        from engine.hidden_alpha import hidden_alpha_report
        sym = normalize_symbol(args.get("symbol", "BTCUSDT"))
        tf = args.get("timeframe", "15m")
        bars = min(int(args.get("bars", 500)), 1000)
        client = maybe_client()
        df = client.klines(sym, tf, bars)
        return hidden_alpha_report(df, sym, tf)

    elif name == "hidden_analytics_mae":
        # MAE/MFE summary from the paper-trade DB. Read-only.
        from brain.analytics import mae_mfe_summary
        plan_type = args.get("plan_type")
        with SignalDB() as db:
            return mae_mfe_summary(db, plan_type=plan_type)

    elif name == "hidden_analytics_mc":
        # Monte Carlo equity / drawdown distribution. Read-only.
        from brain.analytics import monte_carlo_equity
        samples = min(int(args.get("samples", 2000)), 20000)
        seed = args.get("seed")
        with SignalDB() as db:
            return monte_carlo_equity(db, samples=samples,
                                      seed=int(seed) if seed is not None else None)

    raise ValueError(f"Unhandled tool: {name}")


def process_message(msg: dict) -> Optional[dict]:
    msg_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            },
        }

    elif method == "notifications/initialized":
        return None

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    elif method == "tools/list":
        tools_out = []
        for name, spec in ALLOWED_TOOLS.items():
            tools_out.append({
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["inputSchema"],
            })
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools_out}}

    elif method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}
        try:
            res_data = handle_tool_call(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(res_data, indent=2, default=str)}
                    ]
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32000,
                    "message": str(exc),
                },
            }

    else:
        if msg_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }
        return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            resp = process_message(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
