# learner.py — Tracks prediction accuracy and adjusts estimates over time

import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger("kalshi.learner")
LEARN_FILE = "data/learner.json"

class Learner:
    """
    Tracks our probability estimates vs actual outcomes.
    Over time, detects if we are systematically over/under-estimating
    and applies a calibration correction.
    """
    def __init__(self):
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(LEARN_FILE):
            with open(LEARN_FILE) as f:
                return json.load(f)
        return {
            "predictions": [],       # list of {ticker, predicted, outcome, market_type}
            "calibration": {},       # per market_type bias correction
            "total_edge_captured": 0.0,
            "sessions": 0,
        }

    def _save(self):
        os.makedirs("data", exist_ok=True)
        with open(LEARN_FILE, "w") as f:
            json.dump(self.data, f, indent=2)

    def record_prediction(self, ticker: str, predicted_prob: float,
                          market_type: str, market_prob: float):
        """Call when we make a bet — records our prediction."""
        self.data["predictions"].append({
            "ticker":       ticker,
            "predicted":    predicted_prob,
            "market_prob":  market_prob,
            "market_type":  market_type,
            "outcome":      None,  # filled in when resolved
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        })
        self._save()
        logger.info(f"Prediction recorded: {ticker} @ {predicted_prob:.3f}")

    def record_outcome(self, ticker: str, won: bool):
        """Call when a market resolves — records actual outcome."""
        for p in self.data["predictions"]:
            if p["ticker"] == ticker and p["outcome"] is None:
                p["outcome"] = 1.0 if won else 0.0
                logger.info(f"Outcome recorded: {ticker} {'WIN' if won else 'LOSS'}")
                self._recalibrate()
                self._save()
                return

    def _recalibrate(self):
        """
        Computes calibration bias per market type.
        If we consistently predict 60% but only win 45%, we're overconfident.
        Applies a shrinkage correction toward market price.
        """
        resolved = [p for p in self.data["predictions"] if p["outcome"] is not None]
        if len(resolved) < 5:
            return  # not enough data yet

        # Group by market type
        by_type = {}
        for p in resolved:
            mt = p.get("market_type", "generic")
            by_type.setdefault(mt, []).append(p)

        for mt, preds in by_type.items():
            if len(preds) < 3:
                continue
            avg_predicted = sum(p["predicted"] for p in preds) / len(preds)
            avg_actual    = sum(p["outcome"]   for p in preds) / len(preds)
            bias          = avg_predicted - avg_actual  # positive = overconfident
            self.data["calibration"][mt] = {
                "bias":          round(bias, 4),
                "sample_size":   len(preds),
                "avg_predicted": round(avg_predicted, 4),
                "avg_actual":    round(avg_actual, 4),
            }
            logger.info(f"Calibration [{mt}]: bias={bias:+.3f} n={len(preds)}")

    def adjust(self, prob: float, market_type: str) -> float:
        """Apply learned calibration correction to a raw probability estimate."""
        cal = self.data["calibration"].get(market_type)
        if not cal or cal["sample_size"] < 5:
            return prob  # not enough data, trust raw estimate
        corrected = prob - (cal["bias"] * 0.5)  # partial correction (conservative)
        corrected = max(0.01, min(0.99, corrected))
        logger.debug(f"Calibration adjusted {prob:.3f} → {corrected:.3f} [{market_type}]")
        return corrected

    def session_start(self):
        self.data["sessions"] += 1
        self._save()
        logger.info(f"Learner session #{self.data['sessions']} started")

    def summary(self):
        resolved = [p for p in self.data["predictions"] if p["outcome"] is not None]
        pending  = [p for p in self.data["predictions"] if p["outcome"] is None]
        if not resolved:
            return "No resolved predictions yet."
        wins  = sum(1 for p in resolved if p["outcome"] == 1.0)
        total = len(resolved)
        avg_pred    = sum(p["predicted"] for p in resolved) / total
        avg_actual  = sum(p["outcome"]   for p in resolved) / total
        lines = [
            f"Predictions resolved : {total} ({wins}W / {total-wins}L)",
            f"Pending              : {len(pending)}",
            f"Avg predicted prob   : {avg_pred:.3f}",
            f"Actual win rate      : {avg_actual:.3f}",
            f"Calibration          : {self.data['calibration']}",
        ]
        return "\n".join(lines)
