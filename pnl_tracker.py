# pnl_tracker.py — Tracks P&L, logs trades, writes to CSV

import csv
import os
import logging
from datetime import datetime, timezone
from config import PNL_FILE

logger = logging.getLogger("kalshi.pnl")

HEADERS = [
    "timestamp", "ticker", "side", "contracts", "price",
    "bet_dollars", "edge", "true_prob", "market_prob",
    "status", "pnl_dollars"
]

class PnLTracker:
    def __init__(self):
        self._ensure_file()
        self.open_positions = {}  # ticker -> trade record

    def _ensure_file(self):
        if not os.path.exists(PNL_FILE):
            with open(PNL_FILE, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=HEADERS)
                writer.writeheader()

    def log_trade(self, rec: dict, status: str = "open", pnl: float = 0.0):
        row = {
            "timestamp":    datetime.now(timezone.utc).isoformat(),
            "ticker":       rec.get("ticker"),
            "side":         rec.get("side"),
            "contracts":    rec.get("contracts"),
            "price":        rec.get("yes_price_cents", 0) / 100,
            "bet_dollars":  rec.get("bet_dollars"),
            "edge":         rec.get("edge"),
            "true_prob":    rec.get("true_prob"),
            "market_prob":  rec.get("market_prob"),
            "status":       status,
            "pnl_dollars":  pnl,
        }
        with open(PNL_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            writer.writerow(row)
        logger.info(f"Trade logged: {rec['ticker']} {status} pnl=${pnl:.2f}")

    def summary(self) -> dict:
        """Returns total P&L summary from CSV."""
        total_bet   = 0.0
        total_pnl   = 0.0
        wins        = 0
        losses      = 0
        open_count  = 0

        if not os.path.exists(PNL_FILE):
            return {}

        with open(PNL_FILE, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = row["status"]
                pnl    = float(row["pnl_dollars"] or 0)
                bet    = float(row["bet_dollars"] or 0)
                if status == "open":
                    open_count += 1
                elif status == "won":
                    wins      += 1
                    total_pnl += pnl
                    total_bet += bet
                elif status == "lost":
                    losses    += 1
                    total_pnl += pnl
                    total_bet += bet

        return {
            "total_bet":    round(total_bet, 2),
            "total_pnl":    round(total_pnl, 2),
            "wins":         wins,
            "losses":       losses,
            "open":         open_count,
            "roi_pct":      round((total_pnl / total_bet * 100) if total_bet else 0, 2),
        }

    def print_summary(self):
        s = self.summary()
        if not s:
            print("No trades yet.")
            return
        print(f"\n{'='*40}")
        print(f"  P&L SUMMARY")
        print(f"{'='*40}")
        print(f"  Total wagered : ${s['total_bet']:.2f}")
        print(f"  Total P&L     : ${s['total_pnl']:+.2f}")
        print(f"  ROI           : {s['roi_pct']:+.1f}%")
        print(f"  W/L/Open      : {s['wins']}/{s['losses']}/{s['open']}")
        print(f"{'='*40}\n")
