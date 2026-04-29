# config.py — Kalshi Bot Configuration

# ─── Environment ────────────────────────────────────────────────
DEMO_MODE = True  # Set to False when going live

DEMO_BASE_URL = "https://demo-api.kalshi.co/trade-api/v2"
LIVE_BASE_URL  = "https://api.elections.kalshi.com/trade-api/v2"

# Credentials — loaded from macOS Keychain (never stored in plaintext)
import subprocess

def _keychain_get(service: str, account: str) -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True, text=True
    )
    return result.stdout.strip()

KEYCHAIN_ACCOUNT = "kaifine14@gmail.com"
DEMO_API_KEY     = _keychain_get("kalshi-demo-apikey", KEYCHAIN_ACCOUNT)
LIVE_API_KEY     = _keychain_get("kalshi-live-apikey", KEYCHAIN_ACCOUNT)

# ─── Strategy ───────────────────────────────────────────────────
MIN_EDGE         = 0.05   # Minimum edge required to place a bet (5%)
MAX_KELLY_FRAC   = 0.25   # Cap Kelly fraction at 25% of bankroll per bet
MIN_BET_DOLLARS  = 1.00   # Minimum bet size
MAX_BET_DOLLARS  = 2.00   # Maximum bet size — trial run cap
SCAN_INTERVAL_S  = 60     # Seconds between market scans

# ─── Market Focus ───────────────────────────────────────────────
# Categories to scan (comment out to disable)
TARGET_SERIES = [
    "KXFED",   # Fed rate decisions — high volume, CME FedWatch edge
    "KXGDP",   # GDP — GDPNow model edge
    "KXCPI",   # CPI — Cleveland Fed nowcast edge
    "KXNBA",   # NBA — statistical model edge
    "KXNHL",   # NHL — statistical model edge
    "KXMLB",   # MLB — statistical model edge
]

# ─── Logging ────────────────────────────────────────────────────
LOG_FILE = "logs/bot.log"
PNL_FILE = "logs/pnl.csv"
