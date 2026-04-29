"""
gdpnow.py — Atlanta Fed GDPNow fetcher

Tries multiple sources in order of reliability:
1. Atlanta Fed tracking page (HTML parse — best, daily)
2. FRED API (requires free API key — register at fred.stlouisfed.org)
3. FRED CSV fallback (no key, but quarterly only)

Result: (estimate_pct, source, date)
"""

import requests
import re
import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("kalshi.gdpnow")

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")  # set in env or keychain
CACHE_FILE   = "data/gdpnow_cache.json"
TIMEOUT      = 10

def fetch() -> tuple[float | None, str, str]:
    """
    Returns (gdpnow_pct, source_name, as_of_date).
    Tries sources in order, falls back gracefully.
    """
    # 1. Check cache (valid for 3 hours)
    cached = _load_cache()
    if cached:
        logger.info(f"GDPNow from cache: {cached['value']}% ({cached['source']}) as of {cached['date']}")
        return cached['value'], cached['source'], cached['date']

    # 2. Atlanta Fed page (HTML — best free source)
    result = _fetch_atlanta_fed()
    if result[0] is not None:
        _save_cache(*result)
        return result

    # 3. FRED API with key
    if FRED_API_KEY:
        result = _fetch_fred_api()
        if result[0] is not None:
            _save_cache(*result)
            return result

    # 4. FRED CSV (no key, quarterly only)
    result = _fetch_fred_csv()
    if result[0] is not None:
        _save_cache(*result)
        return result

    logger.warning("GDPNow: all sources failed")
    return None, "none", ""


def _fetch_atlanta_fed() -> tuple[float | None, str, str]:
    """
    Scrapes Atlanta Fed GDPNow page for current estimate.
    The page embeds the estimate in its text content.
    """
    try:
        url  = "https://www.atlantafed.org/cqer/research/gdpnow"
        resp = requests.get(url, timeout=TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"})
        text = resp.text

        # Pattern 1: "The GDPNow model estimate ... in the Xth quarter of 20XX is X.X percent"
        # Pattern 2: Look for the current estimate in structured data
        patterns = [
            r'model\s+estimate[^.]{0,300}?(\-?\d+\.\d+)\s*percent\s+as\s+of\s+([\w\s,]+\d{4})',
            r'(\-?\d+\.\d+)\s*percent\s+\(as\s+of\s+([\w\s,]+\d{4})\)',
            r'estimate\s+is\s+(\-?\d+\.\d+)\s*percent\s+\(?\s*([\w\s,]*\d{4})',
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE | re.DOTALL)
            if m:
                val  = float(m.group(1))
                date = m.group(2).strip() if len(m.groups()) > 1 else "unknown"
                logger.info(f"GDPNow (Atlanta Fed): {val}% as of {date}")
                return val, "atlanta_fed", date

        # Fallback: extract numbers embedded in page data near GDPNow context
        # Remove script/style tags first
        clean = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'<[^>]+>', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean)

        m2 = re.search(r'GDPNow[^.]{0,200}?(\-?\d+\.\d+)\s*percent', clean, re.IGNORECASE)
        if m2:
            val = float(m2.group(1))
            logger.info(f"GDPNow (Atlanta Fed fallback): {val}%")
            return val, "atlanta_fed_approx", datetime.now().strftime("%Y-%m-%d")

        return None, "", ""
    except Exception as e:
        logger.debug(f"Atlanta Fed fetch failed: {e}")
        return None, "", ""


def _fetch_fred_api() -> tuple[float | None, str, str]:
    """Fetches latest GDPNow from FRED API (requires free key)."""
    try:
        url = (f"https://api.stlouisfed.org/fred/series/observations"
               f"?series_id=GDPNOW&api_key={FRED_API_KEY}"
               f"&file_type=json&limit=1&sort_order=desc")
        resp = requests.get(url, timeout=TIMEOUT)
        data = resp.json()
        obs  = data.get("observations", [])
        if not obs:
            return None, "", ""
        val  = float(obs[0]["value"])
        date = obs[0]["date"]
        logger.info(f"GDPNow (FRED API): {val}% as of {date}")
        return val, "fred_api", date
    except Exception as e:
        logger.debug(f"FRED API fetch failed: {e}")
        return None, "", ""


def _fetch_fred_csv() -> tuple[float | None, str, str]:
    """
    Fallback: FRED CSV without key.
    Returns quarterly estimate (less current but always available).
    """
    try:
        url  = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDPNOW"
        resp = requests.get(url, timeout=TIMEOUT)
        lines = [l for l in resp.text.strip().split("\n")
                 if "," in l and not l.startswith("D")]
        if not lines:
            return None, "", ""
        date, val = lines[-1].split(",")
        logger.info(f"GDPNow (FRED CSV/quarterly): {val}% as of {date}")
        return float(val), "fred_csv_quarterly", date.strip()
    except Exception as e:
        logger.debug(f"FRED CSV fetch failed: {e}")
        return None, "", ""


def _load_cache() -> dict | None:
    """Load cached value if fresh (< 3 hours)."""
    try:
        if not os.path.exists(CACHE_FILE):
            return None
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        cached_at = datetime.fromisoformat(cache["cached_at"])
        age_hours = (datetime.now(timezone.utc) - cached_at).seconds / 3600
        if age_hours < 3:
            return cache
        return None
    except Exception:
        return None


def _save_cache(value: float, source: str, date: str):
    """Save to cache."""
    try:
        os.makedirs("data", exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump({
                "value":     value,
                "source":    source,
                "date":      date,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }, f)
    except Exception:
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    val, source, date = fetch()
    print(f"\nGDPNow: {val}% | Source: {source} | As of: {date}")
    if source == "fred_csv_quarterly":
        print("⚠️  Using quarterly snapshot — register free FRED API key at")
        print("   https://fred.stlouisfed.org/docs/api/api_key.html")
        print("   Then: export FRED_API_KEY=your_key")
