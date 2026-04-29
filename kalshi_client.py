# kalshi_client.py — API client for Kalshi (RSA-signed requests)

import requests
import time
import base64
import logging
import subprocess
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from config import (
    DEMO_MODE, DEMO_BASE_URL, LIVE_BASE_URL,
    DEMO_API_KEY, LIVE_API_KEY,
    KEYCHAIN_ACCOUNT
)

logger = logging.getLogger("kalshi.client")

def _keychain_get(service: str, account: str) -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True, text=True
    )
    raw = result.stdout.strip()
    # Keychain may return hex-encoded values for multiline secrets
    try:
        return bytes.fromhex(raw).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return raw

class KalshiClient:
    def __init__(self):
        self.base_url = DEMO_BASE_URL if DEMO_MODE else LIVE_BASE_URL
        self.api_key  = DEMO_API_KEY if DEMO_MODE else LIVE_API_KEY
        self.mode     = "DEMO" if DEMO_MODE else "LIVE"

        # Load private key from Keychain
        key_service  = "kalshi-demo-privatekey" if DEMO_MODE else "kalshi-live-privatekey"
        pem          = _keychain_get(key_service, KEYCHAIN_ACCOUNT).encode()
        self.privkey = serialization.load_pem_private_key(pem, password=None, backend=default_backend())

        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _sign(self, timestamp_ms: int, method: str, path: str) -> str:
        """RSA-PSS-SHA256 signature: timestamp(ms) + METHOD + path"""
        message = f"{timestamp_ms}{method}{path}".encode("utf-8")
        sig = self.privkey.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256()
        )
        return base64.b64encode(sig).decode("utf-8")

    def _headers(self, method: str, path: str) -> dict:
        ts = str(int(time.time() * 1000))
        return {
            "Content-Type":          "application/json",
            "KALSHI-ACCESS-KEY":     self.api_key,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": self._sign(int(ts), method.upper(), path),
        }

    def _path(self, endpoint: str) -> str:
        """Extract path from full URL for signing."""
        base_path = self.base_url.replace("https://demo-api.kalshi.co", "")
        base_path = base_path.replace("https://api.elections.kalshi.com", "")
        return f"{base_path}/{endpoint.lstrip('/')}"

    def _get(self, endpoint: str, params: dict = None):
        path = self._path(endpoint)
        url  = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self.session.get(url, params=params, headers=self._headers("GET", path))
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint: str, payload: dict):
        path = self._path(endpoint)
        url  = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self.session.post(url, json=payload, headers=self._headers("POST", path))
        resp.raise_for_status()
        return resp.json()

    def _delete(self, endpoint: str):
        path = self._path(endpoint)
        url  = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self.session.delete(url, headers=self._headers("DELETE", path))
        resp.raise_for_status()
        return resp.json()

    # ── Auth ──────────────────────────────────────────────────────
    def login(self):
        balance = self.get_balance()
        logger.info(f"[{self.mode}] Connected. Balance: ${balance:.2f}")
        return True

    # ── Account ───────────────────────────────────────────────────
    def get_balance(self):
        data = self._get("portfolio/balance")
        return data.get("balance", 0) / 100.0

    def get_positions(self):
        data = self._get("portfolio/positions")
        return data.get("market_positions", [])

    # ── Markets ───────────────────────────────────────────────────
    def get_markets(self, series_ticker=None, status="open", limit=100):
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        return self._get("markets", params=params).get("markets", [])

    def get_market(self, ticker):
        return self._get(f"markets/{ticker}").get("market", {})

    def get_orderbook(self, ticker):
        return self._get(f"markets/{ticker}/orderbook")

    # ── Orders ────────────────────────────────────────────────────
    def place_order(self, ticker, side, count, yes_price_cents, order_type="limit"):
        payload = {
            "ticker":    ticker,
            "action":    "buy",
            "side":      side,
            "type":      order_type,
            "count":     count,
            "yes_price": yes_price_cents,
        }
        logger.info(f"[{self.mode}] Placing order: {payload}")
        return self._post("portfolio/orders", payload)

    def get_orders(self, status=None):
        params = {"status": status} if status else {}
        return self._get("portfolio/orders", params=params).get("orders", [])

    def cancel_order(self, order_id):
        return self._delete(f"portfolio/orders/{order_id}")

    # ── Events ────────────────────────────────────────────────────
    def get_events(self, series_ticker=None, status="open", limit=50):
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        return self._get("events", params=params).get("events", [])
