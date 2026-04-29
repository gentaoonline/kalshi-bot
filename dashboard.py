#!/usr/bin/env python3
# dashboard.py — Writes a live dashboard to the Obsidian Scrolls vault

import os
import csv
import json
import time
import re
import subprocess
from datetime import datetime, timezone

os.chdir(os.path.dirname(os.path.abspath(__file__)))

VAULT_PATH    = "/Users/gentao/Documents/Scrolls"
DASHBOARD_NOTE = f"{VAULT_PATH}/Treasury/Bot Dashboard.md"
PNL_FILE      = "logs/pnl.csv"
LOG_FILE      = "logs/bot.log"
LEARN_FILE    = "data/learner.json"
REFRESH_S     = 60

os.makedirs(f"{VAULT_PATH}/Treasury", exist_ok=True)

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S PDT")

def read_pnl():
    rows = []
    if not os.path.exists(PNL_FILE):
        return rows
    with open(PNL_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def pnl_summary(rows):
    total_bet  = sum(float(r["bet_dollars"] or 0) for r in rows)
    total_pnl  = sum(float(r["pnl_dollars"] or 0) for r in rows)
    wins       = sum(1 for r in rows if r["status"] == "won")
    losses     = sum(1 for r in rows if r["status"] == "lost")
    open_count = sum(1 for r in rows if r["status"] == "open")
    roi        = (total_pnl / total_bet * 100) if total_bet else 0
    return total_bet, total_pnl, roi, wins, losses, open_count

def get_balance():
    """Read latest balance from bot log."""
    if not os.path.exists(LOG_FILE):
        return "unknown"
    lines = open(LOG_FILE).readlines()
    for line in reversed(lines):
        m = re.search(r"Balance: \$([\d\.]+)", line)
        if m:
            return f"${m.group(1)}"
    return "unknown"

def get_recent_log(n=20):
    """Last N meaningful log lines."""
    if not os.path.exists(LOG_FILE):
        return []
    lines = open(LOG_FILE).readlines()
    # Filter to interesting lines
    keywords = ["Balance", "Edge", "Order placed", "Order failed",
                 "Scan cycle", "No edge", "estimate", "Sleeping"]
    filtered = [l.strip() for l in lines if any(k in l for k in keywords)]
    return filtered[-n:]

def get_open_positions():
    """Get current open positions from learner data."""
    rows = read_pnl()
    return [r for r in rows if r["status"] == "open"]

def get_learner_summary():
    if not os.path.exists(LEARN_FILE):
        return None
    with open(LEARN_FILE) as f:
        return json.load(f)

def bot_is_running():
    try:
        result = subprocess.run(["pgrep", "-f", "bot.py"], capture_output=True, text=True)
        return bool(result.stdout.strip())
    except Exception:
        return False

def build_dashboard():
    rows       = read_pnl()
    total_bet, total_pnl, roi, wins, losses, open_count = pnl_summary(rows)
    balance    = get_balance()
    positions  = get_open_positions()
    learner    = get_learner_summary()
    running    = bot_is_running()
    log_lines  = get_recent_log(15)

    status_icon = "🟢 Running" if running else "🔴 Stopped"
    pnl_icon    = "📈" if total_pnl >= 0 else "📉"

    md = f"""# ⚔️ Treasury Dashboard
*Gen Tao's Quant Bot — Young Master's eyes on the operation*

> **Last updated:** {now_str()}

---

## Status

| | |
|---|---|
| Bot | {status_icon} |
| Balance | {balance} |
| Mode | 🧪 DEMO |
| Scan interval | 60s |

---

## P&L Summary

| Metric | Value |
|---|---|
| Total wagered | ${total_bet:.2f} |
| Total P&L | {pnl_icon} ${total_pnl:+.2f} |
| ROI | {roi:+.1f}% |
| Wins | {wins} |
| Losses | {losses} |
| Open positions | {open_count} |

---

## Open Positions

"""
    if positions:
        md += "| Ticker | Side | Bet | Edge | True% | Market% | Opened |\n"
        md += "|---|---|---|---|---|---|---|\n"
        for p in positions:
            ts = p.get("timestamp","")[:16].replace("T"," ")
            md += (f"| `{p['ticker'][:30]}` | **{p['side'].upper()}** | "
                   f"${float(p['bet_dollars']):.2f} | "
                   f"{float(p['edge'])*100:.1f}% | "
                   f"{float(p['true_prob'])*100:.1f}% | "
                   f"{float(p['market_prob'])*100:.1f}% | "
                   f"{ts} |\n")
    else:
        md += "*No open positions.*\n"

    md += "\n---\n\n## Calibration (Learning)\n\n"
    if learner and learner.get("calibration"):
        md += "| Market Type | Bias | Avg Predicted | Avg Actual | Sample Size |\n"
        md += "|---|---|---|---|---|\n"
        for mtype, cal in learner["calibration"].items():
            bias_icon = "🔴" if abs(cal["bias"]) > 0.10 else "🟡" if abs(cal["bias"]) > 0.05 else "🟢"
            md += (f"| {mtype} | {bias_icon} {cal['bias']:+.3f} | "
                   f"{cal['avg_predicted']:.3f} | {cal['avg_actual']:.3f} | "
                   f"{cal['sample_size']} |\n")
        md += f"\n*Sessions run: {learner.get('sessions', 0)}*\n"
    else:
        md += "*Not enough resolved predictions yet — calibration pending.*\n"

    md += "\n---\n\n## Recent Activity\n\n```\n"
    if log_lines:
        # Clean ANSI and trim timestamps
        for line in log_lines:
            clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
            # Shorten timestamp
            clean = re.sub(r'^\d{4}-\d{2}-\d{2} ', '', clean)
            md += clean + "\n"
    else:
        md += "No log data yet.\n"
    md += "```\n\n"

    md += "---\n\n## Strategy Map\n\n"
    md += "| Series | Data Source | Horizon | Edge Type |\n"
    md += "|---|---|---|---|\n"
    md += "| KXFED | FRED + CME FedWatch | ≤400 days | Rate path vs market |\n"
    md += "| KXGDP | Atlanta Fed GDPNow | ≤120 days | Nowcast vs market |\n"
    md += "| KXCPI | FRED CPI (lagged) | ≤60 days | MoM reading vs market |\n"
    md += "| KXNBA/NHL/MLB | Long-shot bias model | Any | Underdog overpricing |\n"

    md += "\n---\n\n*[[Mission Log]] · [[Chronicle/2026-04-27]] · [[Observations/Model Map]]*\n"
    md += f"\n*Auto-refreshes every {REFRESH_S}s — open in Obsidian and keep it pinned.*\n"

    return md

def run():
    print(f"Dashboard updater started — writing to:\n  {DASHBOARD_NOTE}")
    print(f"Refreshing every {REFRESH_S}s. Ctrl+C to stop.\n")
    while True:
        try:
            content = build_dashboard()
            with open(DASHBOARD_NOTE, "w") as f:
                f.write(content)
            print(f"[{now_str()}] Dashboard updated ✅")
        except Exception as e:
            print(f"[{now_str()}] Error: {e}")
        time.sleep(REFRESH_S)

if __name__ == "__main__":
    run()
