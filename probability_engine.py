# probability_engine.py — Estimates true probability for real Kalshi markets
# 
# Core rule: only price markets where we have FORWARD-LOOKING data.
# Never extrapolate current readings to future unknown months.

import requests
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger("kalshi.probability")

# Timeout for all external requests
TIMEOUT = 10

class ProbabilityEngine:

    def estimate(self, market: dict) -> float | None:
        ticker = market.get("ticker", "")
        series = ticker.split("-")[0]

        logger.debug(f"Estimating: {ticker}")

        if series == "KXFED":
            return self._estimate_fed(market)
        elif series == "KXGDP":
            return self._estimate_gdp(market)
        elif series == "KXCPI":
            return self._estimate_cpi(market)
        elif series in ("KXNBA", "KXNHL", "KXMLB"):
            return self._estimate_sports(market)
        return None

    # ── Fed Rate ──────────────────────────────────────────────────
    def _estimate_fed(self, market: dict) -> float | None:
        """
        Uses CME FedWatch implied probabilities — the gold standard for 
        Fed rate path. We compare Kalshi price vs CME implied prob.
        Only prices markets closing within 400 days (reliable horizon).
        """
        try:
            title     = market.get("title", "")
            close_time = market.get("close_time", "")
            days_out  = self._days_until(close_time)

            # Beyond ~400 days the market is too uncertain to model well
            if days_out > 400:
                return None

            match = re.search(r'above\s+([\d\.]+)%', title)
            if not match:
                return None
            target_rate = float(match.group(1))

            # Fetch current Fed funds rate from FRED
            current_rate = self._fetch_fred_rate("DFEDTARU")
            if current_rate is None:
                return None

            # Fetch CME FedWatch data for implied cut probabilities
            # CME provides meeting-by-meeting cut probabilities
            cme_prob = self._fetch_cme_fedwatch(target_rate, days_out)
            if cme_prob is not None:
                logger.info(f"Fed [{ticker_from_title(title)}]: CME prob={cme_prob:.3f} "
                            f"(target={target_rate}%, current={current_rate}%, days={days_out})")
                return round(cme_prob, 3)

            # Fallback: simple rate distance model with uncertainty bands
            rate_gap = current_rate - target_rate  # positive = above target already

            # Base probability from rate distance
            if rate_gap > 1.0:
                base = 0.88
            elif rate_gap > 0.50:
                base = 0.75
            elif rate_gap > 0.25:
                base = 0.60
            elif rate_gap > 0:
                base = 0.52
            elif rate_gap > -0.25:
                base = 0.40
            elif rate_gap > -0.75:
                base = 0.22
            else:
                base = 0.08

            # Shrink toward 0.5 based on time horizon uncertainty
            # More time = more uncertainty = closer to 50/50
            uncertainty = min(0.35, days_out / 1200)
            prob = base + (0.5 - base) * uncertainty

            logger.info(f"Fed fallback: target={target_rate}% current={current_rate}% "
                        f"gap={rate_gap:+.2f} base={base:.2f} prob={prob:.3f} days={days_out}")
            return round(max(0.03, min(0.97, prob)), 3)

        except Exception as e:
            logger.warning(f"Fed estimate error: {e}")
            return None

    def _fetch_fred_rate(self, series_id: str) -> float | None:
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            resp = requests.get(url, timeout=TIMEOUT)
            lines = [l for l in resp.text.strip().split("\n") if "." in l and not l.startswith("D")]
            if not lines:
                return None
            return float(lines[-1].split(",")[1])
        except Exception as e:
            logger.warning(f"FRED fetch failed ({series_id}): {e}")
            return None

    def _fetch_cme_fedwatch(self, target_rate: float, days_out: int) -> float | None:
        """
        Fetches CME FedWatch implied probabilities for Fed rate path.
        Returns probability that rate will be ABOVE target_rate.
        """
        try:
            url = ("https://www.cmegroup.com/CmeWS/mvc/MeetingCalendar/list.json")
            resp = requests.get(url, timeout=TIMEOUT,
                                headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return None

            meetings = resp.json()
            if not meetings:
                return None

            # Find meeting closest to our close_time
            target_meeting = None
            for m in meetings:
                meeting_days = self._days_until(m.get("meetingDate", "") + "T00:00:00Z")
                if meeting_days <= days_out:
                    target_meeting = m
                else:
                    break

            if not target_meeting:
                target_meeting = meetings[0]

            # Sum probability of rate being above target
            probs = target_meeting.get("probabilityData", [])
            if not probs:
                return None

            prob_above = sum(
                float(p.get("probability", 0)) / 100
                for p in probs
                if self._rate_from_label(p.get("rateBps", "")) > target_rate
            )
            return round(prob_above, 3)

        except Exception as e:
            logger.debug(f"CME FedWatch fetch failed: {e}")
            return None

    def _rate_from_label(self, bps_str: str) -> float:
        try:
            return int(bps_str) / 100
        except Exception:
            return 0.0

    # ── GDP ───────────────────────────────────────────────────────
    def _estimate_gdp(self, market: dict) -> float | None:
        """
        Uses Atlanta Fed GDPNow — the best real-time GDP tracker.
        ONLY prices the CURRENT quarter (close_time within 120 days).
        Future quarters are too uncertain to model.
        """
        try:
            close_time = market.get("close_time", "")
            days_out   = self._days_until(close_time)

            # Only price near-term GDP markets
            if days_out > 120:
                logger.debug(f"GDP market too far out ({days_out} days) — skipping")
                return None

            title = market.get("title", "")
            match = re.search(r'more than ([\d\.]+)%', title)
            if not match:
                return None
            threshold = float(match.group(1))

            # Atlanta Fed GDPNow current estimate
            gdpnow = self._fetch_gdpnow()
            if gdpnow is None:
                return None

            logger.info(f"GDPNow: {gdpnow:.2f}% | threshold: {threshold}%")

            # Uncertainty band: GDPNow has ~1.5% RMSE historically
            rmse = 1.5
            diff = gdpnow - threshold

            # Convert to probability using normal distribution approximation
            # P(actual > threshold) = P(Z > (threshold - gdpnow) / rmse)
            z = (threshold - gdpnow) / rmse
            prob = self._normal_cdf(-z)  # P(above threshold)

            # Compress extremes slightly — model isn't perfect
            prob = 0.05 + prob * 0.90

            logger.info(f"GDP: gdpnow={gdpnow:.2f}% threshold={threshold}% z={z:.2f} prob={prob:.3f}")
            return round(prob, 3)

        except Exception as e:
            logger.warning(f"GDP estimate error: {e}")
            return None

    def _fetch_gdpnow(self) -> float | None:
        """Fetches Atlanta Fed GDPNow latest estimate from FRED."""
        try:
            # GDPNow is published on FRED as GDPNOW
            url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDPNOW"
            resp = requests.get(url, timeout=TIMEOUT)
            lines = [l for l in resp.text.strip().split("\n")
                     if "," in l and not l.startswith("D")]
            if not lines:
                return None
            return float(lines[-1].split(",")[1])
        except Exception as e:
            logger.warning(f"GDPNow fetch failed: {e}")
            return None

    # ── CPI ───────────────────────────────────────────────────────
    def _estimate_cpi(self, market: dict) -> float | None:
        """
        Uses Cleveland Fed CPI Nowcast — a FORWARD-LOOKING model.
        Only prices the NEXT month's release (close_time within 60 days).
        Never extrapolates current data to distant future months.
        """
        try:
            close_time = market.get("close_time", "")
            days_out   = self._days_until(close_time)

            # Only price if release is within 60 days
            if days_out > 60:
                logger.debug(f"CPI market too far out ({days_out} days) — skipping")
                return None

            title = market.get("title", "")
            match = re.search(r'more than ([\-\d\.]+)%', title)
            if not match:
                return None
            threshold = float(match.group(1))

            # Cleveland Fed Inflation Nowcast (forward-looking)
            nowcast = self._fetch_cleveland_nowcast()
            if nowcast is None:
                # Fallback: FRED last reading — high uncertainty, different month
                nowcast = self._fetch_bls_cpi_mom()
                if nowcast is None:
                    return None
                # Last month's reading is a noisy predictor of next month
                # CPI MoM std dev is ~0.35%, and we're one month stale
                uncertainty_rmse = 0.40
                logger.info(f"CPI using lagged FRED data — high uncertainty (rmse={uncertainty_rmse})")
            else:
                # Cleveland nowcast is forward-looking but still ~0.20% RMSE
                uncertainty_rmse = 0.20

            logger.info(f"CPI nowcast: {nowcast:.3f}% | threshold: {threshold}% | days_out: {days_out}")

            diff = nowcast - threshold
            z    = (threshold - nowcast) / uncertainty_rmse
            prob = self._normal_cdf(-z)
            prob = 0.03 + prob * 0.94  # compress extremes

            logger.info(f"CPI: nowcast={nowcast:.3f}% threshold={threshold}% z={z:.2f} prob={prob:.3f}")
            return round(prob, 3)

        except Exception as e:
            logger.warning(f"CPI estimate error: {e}")
            return None

    def _fetch_cleveland_nowcast(self) -> float | None:
        """Fetches Cleveland Fed CPI Nowcast."""
        try:
            url = ("https://www.clevelandfed.org/indicators-and-data/"
                   "inflation-nowcasting/nowcast-data-download")
            resp = requests.get(url, timeout=TIMEOUT,
                                headers={"User-Agent": "Mozilla/5.0"})
            # Parse JSON from page if available
            # This endpoint varies — fall back to BLS if it fails
            if resp.status_code != 200:
                return None
            # Try to extract nowcast value from response
            text = resp.text
            match = re.search(r'"cpiMoM":\s*([\-\d\.]+)', text)
            if match:
                return float(match.group(1))
            return None
        except Exception:
            return None

    def _fetch_bls_cpi_mom(self) -> float | None:
        """Fetches CPI MoM from FRED (CPIAUCNS = not seasonally adjusted)."""
        try:
            # FRED CSV — no API key needed, generous rate limits
            url  = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCNS"
            resp = requests.get(url, timeout=TIMEOUT)
            lines = [l for l in resp.text.strip().split("\n")
                     if "," in l and not l.startswith("D")]
            if len(lines) < 2:
                return None
            curr = float(lines[-1].split(",")[1])
            prev = float(lines[-2].split(",")[1])
            mom  = (curr - prev) / prev * 100
            logger.info(f"CPI MoM from FRED: {mom:.4f}% (curr={curr}, prev={prev})")
            return mom
        except Exception as e:
            logger.warning(f"FRED CPI fetch failed: {e}")
            return None

    # ── Sports ────────────────────────────────────────────────────
    def _estimate_sports(self, market: dict) -> float | None:
        """
        Championship futures only. Applies long-shot bias correction.
        Underdogs (<15%) are systematically overpriced in prediction markets.
        Favorites (>40%) are roughly fairly priced.
        Only bets NO on heavy underdogs or YES on clear favorites.
        """
        try:
            yes_ask = float(market.get("yes_ask_dollars", 0))
            title   = market.get("title", "")

            if yes_ask <= 0.01 or yes_ask >= 0.99:
                return None

            # Long-shot bias: bettors love underdogs, overprice them
            if yes_ask < 0.04:
                prob = yes_ask * 0.60   # 40% reduction — heavy longshot
            elif yes_ask < 0.08:
                prob = yes_ask * 0.75
            elif yes_ask < 0.15:
                prob = yes_ask * 0.87
            elif yes_ask < 0.30:
                prob = yes_ask * 0.94
            else:
                prob = yes_ask          # favorites fairly priced

            logger.info(f"Sports: market={yes_ask:.3f} → adjusted={prob:.3f} | {title[:50]}")
            return round(prob, 3)

        except Exception as e:
            logger.warning(f"Sports estimate error: {e}")
            return None

    # ── Utilities ─────────────────────────────────────────────────
    def _days_until(self, iso_time: str) -> int:
        try:
            t = iso_time.replace("Z", "+00:00")
            if len(t) == 10:
                t += "T00:00:00+00:00"
            target = datetime.fromisoformat(t)
            now    = datetime.now(timezone.utc)
            return max(1, (target - now).days)
        except Exception:
            return 999

    def _normal_cdf(self, z: float) -> float:
        """Approximation of standard normal CDF."""
        import math
        return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def ticker_from_title(title: str) -> str:
    return title[:30]
