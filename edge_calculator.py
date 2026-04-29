# edge_calculator.py — Calculates edge and Kelly-optimal bet size

import math
import logging
from config import MIN_EDGE, MAX_KELLY_FRAC, MIN_BET_DOLLARS, MAX_BET_DOLLARS

logger = logging.getLogger("kalshi.edge")

class EdgeCalculator:

    def analyze(self, market: dict, true_prob: float, bankroll: float) -> dict | None:
        """
        Given a market and our estimated true probability,
        returns a trade recommendation or None if no edge.

        Returns:
            {
                "ticker": str,
                "side": "yes" | "no",
                "edge": float,
                "true_prob": float,
                "market_prob": float,
                "bet_dollars": float,
                "contracts": int,
                "yes_price_cents": int,
            }
        """
        ticker   = market.get("ticker", "")
        yes_ask  = float(market.get("yes_ask_dollars", 1.0))  # cost to buy yes
        no_ask   = float(market.get("no_ask_dollars", 1.0))   # cost to buy no

        # Market-implied probability of yes
        market_prob_yes = yes_ask  # on Kalshi, price ≈ probability

        # Calculate edge for each side
        edge_yes = true_prob - yes_ask        # edge buying YES
        edge_no  = (1 - true_prob) - no_ask  # edge buying NO

        best_edge = max(edge_yes, edge_no)
        side      = "yes" if edge_yes >= edge_no else "no"
        price     = yes_ask if side == "yes" else no_ask
        prob_win  = true_prob if side == "yes" else (1 - true_prob)

        if best_edge < MIN_EDGE:
            logger.debug(f"{ticker}: edge {best_edge:.3f} below threshold {MIN_EDGE}")
            return None

        # Kelly criterion: f* = (bp - q) / b
        # b = net odds (1/price - 1), p = prob win, q = 1-p
        b = (1.0 / price) - 1.0
        p = prob_win
        q = 1.0 - p

        kelly_frac = (b * p - q) / b if b > 0 else 0
        kelly_frac = max(0, min(kelly_frac, MAX_KELLY_FRAC))  # cap for safety

        bet_dollars = kelly_frac * bankroll
        bet_dollars = max(MIN_BET_DOLLARS, min(bet_dollars, MAX_BET_DOLLARS))

        # Contracts = bet / price per contract
        contracts = max(1, round(bet_dollars / price))

        yes_price_cents = round(price * 100) if side == "yes" else round((1 - price) * 100)

        logger.info(
            f"{ticker} | side={side} | edge={best_edge:.3f} | "
            f"true_prob={true_prob:.3f} | market_prob={market_prob_yes:.3f} | "
            f"kelly={kelly_frac:.3f} | bet=${bet_dollars:.2f} | contracts={contracts}"
        )

        return {
            "ticker":          ticker,
            "side":            side,
            "edge":            round(best_edge, 4),
            "true_prob":       round(true_prob, 4),
            "market_prob":     round(market_prob_yes, 4),
            "kelly_frac":      round(kelly_frac, 4),
            "bet_dollars":     round(bet_dollars, 2),
            "contracts":       contracts,
            "yes_price_cents": yes_price_cents,
        }

    def summarize_opportunity(self, rec: dict) -> str:
        return (
            f"📈 {rec['ticker']} | BUY {rec['side'].upper()} | "
            f"Edge: {rec['edge']*100:.1f}% | "
            f"True: {rec['true_prob']*100:.1f}% vs Market: {rec['market_prob']*100:.1f}% | "
            f"Bet: ${rec['bet_dollars']:.2f} ({rec['contracts']} contracts)"
        )
