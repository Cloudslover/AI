"""CryptoBrain configuration — copy .env.example to .env to override."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

VERSION = "1.7.2"

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

# ── Signal database (learning store) ─────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", str(ROOT / "data" / "cryptobrain.db"))

# ── Backtester ───────────────────────────────────────────────────────────
BACKTEST_HORIZONS = [float(h) for h in os.getenv("BACKTEST_HORIZONS", "1,4,24").split(",")]
BACKTEST_MIN_BARS = int(os.getenv("BACKTEST_MIN_BARS", "120"))
BACKTEST_STEP = int(os.getenv("BACKTEST_STEP", "1"))

# ── Calibration (self-improvement) ───────────────────────────────────────
CALIBRATE_MIN_N = int(os.getenv("CALIBRATE_MIN_N", "20"))     # min samples to trust a plan type
CALIBRATE_GAIN = float(os.getenv("CALIBRATE_GAIN", "0.25"))   # expectancy -> multiplier sensitivity
CALIBRATE_MAX_MULT = float(os.getenv("CALIBRATE_MAX_MULT", "1.25"))
CALIBRATE_MIN_MULT = float(os.getenv("CALIBRATE_MIN_MULT", "0.6"))
CALIBRATE_FILTER = os.getenv("CALIBRATE_FILTER", "false").lower() in ("1", "true", "yes")
CALIBRATE_FILTER_THRESHOLD = float(os.getenv("CALIBRATE_FILTER_THRESHOLD", "-0.35"))  # R, negative

# ── State memory / signal stability (anti-spam, anti-whipsaw) ────────────
SIGNAL_COOLDOWN_MINUTES = int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "30"))  # global floor
FLIP_PRICE_THRESHOLD_PCT = float(os.getenv("FLIP_PRICE_THRESHOLD_PCT", "0.8"))
MAX_FLIPS_PER_HOUR = int(os.getenv("MAX_FLIPS_PER_HOUR", "2"))
