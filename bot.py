#!/usr/bin/env python3
# bot.py — Main Kalshi quant bot

import logging
import time
import sys
import os
from datetime import datetime, timezone

# ── Setup ─────────────────────────────────────────────────────────
os.chdir(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("kalshi.bot")

from config import DEMO_MODE, SCAN_INTERVAL_S, TARGET_SERIES, MAX_BET_DOLLARS
from kalshi_client import KalshiClient
from probability_engine import ProbabilityEngine
from edge_calculator import EdgeCalculator
from pnl_tracker import PnLTracker
from learner import Learner

def banner():
    mode = "🧪 DEMO" if DEMO_MODE else "⚠️  LIVE"
    print(f"""
╔══════════════════════════════════════════╗
║        KALSHI QUANT BOT v1.0            ║
║        Mode: {mode:<28}║
║        Young Master's Treasury          ║
╚══════════════════════════════════════════╝
""")

def run():
    banner()

    client  = KalshiClient()
    engine  = ProbabilityEngine()
    calc    = EdgeCalculator()
    tracker = PnLTracker()
    learner = Learner()

    learner.session_start()

    logger.info("Connecting to Kalshi...")
    client.login()

    placed_this_run = set()  # avoid double-betting same ticker
    cycle = 0

    while True:
        cycle += 1
        logger.info(f"━━━ Scan cycle {cycle} ━━━")

        # Balance check
        try:
            balance = client.get_balance()
            logger.info(f"💰 Balance: ${balance:.2f} | Max bet: ${MAX_BET_DOLLARS:.2f}")
        except Exception as e:
            logger.warning(f"Balance check failed: {e}")
            balance = 100.0

        # Check for resolved positions → feed learner
        try:
            positions = client.get_positions()
            orders    = client.get_orders(status="resting")
            logger.info(f"Open positions: {len(positions)} | Resting orders: {len(orders)}")
        except Exception as e:
            logger.warning(f"Portfolio check failed: {e}")

        opportunities = []

        # ── Scan all open markets ──────────────────────────────────
        for series in TARGET_SERIES:
            try:
                markets = client.get_markets(series_ticker=series, limit=50, status="open")
                active  = [m for m in markets
                           if m.get("status") == "active"
                           and float(m.get("yes_ask_dollars", 0)) > 0
                           and float(m.get("yes_ask_dollars", 0)) < 1.0
                           and m["ticker"] not in placed_this_run]

                logger.info(f"  [{series}] {len(markets)} markets, {len(active)} active+liquid")

                for market in active:
                    true_prob = engine.estimate(market)
                    if true_prob is None:
                        continue

                    # Apply learned calibration
                    mtype     = series.replace("KX", "").lower()
                    true_prob = learner.adjust(true_prob, mtype)

                    rec = calc.analyze(market, true_prob, balance)
                    if rec is None:
                        continue

                    rec["market_type"] = mtype
                    opportunities.append(rec)
                    logger.info(f"  🎯 {calc.summarize_opportunity(rec)}")

            except Exception as e:
                logger.warning(f"  [{series}] Scan error: {e}")

        # ── Execute best opportunities ─────────────────────────────
        if opportunities:
            # Sort by edge descending, take top 3
            opportunities.sort(key=lambda x: x["edge"], reverse=True)
            for rec in opportunities[:3]:
                ticker = rec["ticker"]
                if ticker in placed_this_run:
                    continue
                try:
                    result = client.place_order(
                        ticker          = ticker,
                        side            = rec["side"],
                        count           = rec["contracts"],
                        yes_price_cents = rec["yes_price_cents"],
                    )
                    tracker.log_trade(rec, status="open")
                    learner.record_prediction(
                        ticker       = ticker,
                        predicted_prob = rec["true_prob"],
                        market_type  = rec.get("market_type", "generic"),
                        market_prob  = rec["market_prob"],
                    )
                    placed_this_run.add(ticker)
                    logger.info(f"✅ Order placed on {ticker}")
                except Exception as e:
                    logger.error(f"❌ Order failed [{ticker}]: {e}")
        else:
            logger.info("No edge found this cycle — standing by")

        # ── Periodic summary ──────────────────────────────────────
        if cycle % 5 == 0:
            tracker.print_summary()
            logger.info(f"Learner:\n{learner.summary()}")

        logger.info(f"Sleeping {SCAN_INTERVAL_S}s...\n")
        time.sleep(SCAN_INTERVAL_S)

if __name__ == "__main__":
    run()
