"""CryptoBrain configuration — copy .env.example to .env to override."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent

# ── Market data ──────────────────────────────────────────────────────────
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
TIMEFRAME = os.getenv("TIMEFRAME", "15m")
BARS = int(os.getenv("BARS", "500"))

# Binance endpoints: the geo-friendly public market-data mirror is tried
# first, then the standard host. Futures endpoints geo-block some regions;
# the client degrades gracefully when they are unreachable.
BINANCE_HOSTS = ["https://data-api.binance.vision", "https://api.binance.com"]
BINANCE_FUTURES_HOSTS = ["https://fapi.binance.com", "https://fapi.binance.com"]

# ── Signal engine ────────────────────────────────────────────────────────
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "55"))
DEFAULT_RISK_REWARD = float(os.getenv("DEFAULT_RISK_REWARD", "2.0"))
MAX_RISK_PCT = float(os.getenv("MAX_RISK_PCT", "1.0"))

# ── CryptoDada connector ─────────────────────────────────────────────────
CRYPTODADA_MODE = os.getenv("CRYPTODADA_MODE", "auto")          # auto|api|browser
CRYPTODADA_BASE_URL = os.getenv("CRYPTODADA_BASE_URL", "").rstrip("/")
CRYPTODADA_EMAIL = os.getenv("CRYPTODADA_EMAIL", "")
CRYPTODADA_PASSWORD = os.getenv("CRYPTODADA_PASSWORD", "")
CRYPTODADA_2FA = os.getenv("CRYPTODADA_2FA", "")

# ── Discord ──────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_CHANNEL_IDS = [c.strip() for c in os.getenv("DISCORD_CHANNEL_IDS", "").split(",") if c.strip()]
DISCORD_ANNOUNCE_WEBHOOK = os.getenv("DISCORD_ANNOUNCE_WEBHOOK", "")

# ── LLM AI Brain ─────────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "off")                 # auto|groq|openai|gemini|off
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ── Notifiers ────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Web dashboard ────────────────────────────────────────────────────────
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8050"))
