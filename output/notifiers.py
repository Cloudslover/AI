"""output/notifiers.py

Push CryptoBrain signals to Telegram and/or Discord (webhook) channels.
All pushes are best-effort — failures are logged, never raised.
"""
from __future__ import annotations

import json
from typing import Optional

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DISCORD_ANNOUNCE_WEBHOOK


def format_signal_message(signal: dict, plans: Optional[list] = None) -> str:
    lines = [
        f"**{signal.get('action')} {signal.get('asset')}** — {signal.get('timeframe')}",
        f"`{signal.get('signal_id')}`  conf: {signal.get('confidence')}",
        f"Entry: {signal.get('entry')}  SL: {signal.get('stop_loss')}  TP: {signal.get('take_profit')}",
        f"RR: {signal.get('risk_reward')}",
        f"Reason: {signal.get('reason')}",
    ]
    if plans:
        lines.append("")
        lines.append("Conditional plans:")
        for p in plans[:4]:
            lines.append(f"  • {p['type']} ({p['confidence']}%) — {p['condition'][:120]}")
    lines.append("")
    lines.append("⚠️ Not financial advice. Use stop-losses.")
    return "\n".join(lines)


def notify_telegram(signal: dict, plans: Optional[list] = None,
                    token: str = TELEGRAM_BOT_TOKEN, chat_id: str = TELEGRAM_CHAT_ID) -> bool:
    if not token or not chat_id:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": format_signal_message(signal, plans), "parse_mode": "Markdown"},
            timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


def notify_discord(signal: dict, plans: Optional[list] = None,
                   webhook: str = DISCORD_ANNOUNCE_WEBHOOK) -> bool:
    if not webhook:
        return False
    try:
        r = requests.post(webhook, json={"content": format_signal_message(signal, plans)}, timeout=10)
        return r.status_code in (200, 204)
    except requests.RequestException:
        return False


def notify_all(signal: dict, plans: Optional[list] = None) -> dict:
    return {
        "telegram": notify_telegram(signal, plans),
        "discord": notify_discord(signal, plans),
    }
