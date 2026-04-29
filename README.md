# Kalshi Quant Bot 🗡️

Autonomous prediction market trading bot for [Kalshi](https://kalshi.com).

Built by Gen Tao, in service of the Young Master.

## Architecture

| Module | Purpose |
|---|---|
| `bot.py` | Main scan loop — runs continuously |
| `kalshi_client.py` | Kalshi API client (RSA-signed requests) |
| `probability_engine.py` | Estimates true probability from external data |
| `edge_calculator.py` | Kelly criterion bet sizing |
| `pnl_tracker.py` | Trade logging and P&L reporting |
| `learner.py` | Calibration tracking — learns from outcomes |
| `dashboard.py` | Writes live dashboard to Obsidian vault |
| `config.py` | Settings (credentials loaded from macOS Keychain) |

## Data Sources

- **Fed markets** — FRED API + CME FedWatch
- **GDP markets** — Atlanta Fed GDPNow
- **CPI markets** — Cleveland Fed Inflation Nowcast + FRED
- **Sports markets** — Long-shot bias correction

## Security

- All credentials stored in macOS Keychain — never in plaintext
- RSA-PSS signed API requests
- Demo mode by default (`DEMO_MODE = True` in config.py)

## Setup

```bash
pip3 install requests cryptography
# Add credentials to Keychain (see config.py)
python3 bot.py
python3 dashboard.py  # optional — Obsidian dashboard
```
