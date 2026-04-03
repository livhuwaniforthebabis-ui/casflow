# 🏦 SMC VIP Trading Signal Bot

A **production-grade Telegram VIP trading signal bot** built on **Smart Money Concepts (SMC)**. Delivers institutional-grade signals for Gold, Bitcoin, Forex, and Indices with full multi-timeframe analysis, confidence scoring, and trade monitoring.

---

## 📊 Strategy Overview

| Step | Timeframe | Purpose |
|------|-----------|---------|
| 1 | Daily | Macro bias (Bullish/Bearish/Neutral) |
| 2 | 4H + 1H | BOS/MSS confirmation, internal structure |
| 3 | 30M | Liquidity inducement, POI detection, entry |

**Points of Interest (POI):**
- Order Blocks (OB)
- Breaker Blocks (BB)  
- Fair Value Gaps (FVG)

**Signal sent ONLY when:**
- Daily bias confirmed
- BOS or MSS on lower TF
- Liquidity sweep detected on 30M
- Price returns to valid POI
- Confidence ≥ 70%
- RR ≥ 1:3

---

## 🛠 Tech Stack

- **Python 3.12** + python-telegram-bot v21
- **SQLAlchemy** — SQLite (dev) / PostgreSQL (prod)
- **Pandas + NumPy** — OHLCV analysis
- **Twelve Data API** — Forex + Indices
- **Binance API** — BTCUSD
- **Railway** — Cloud deployment
- **GitHub Actions** — CI/CD

---

## 📁 Project Structure

```
smc-bot/
├── bot/
│   ├── main.py           # Entry point, Telegram app
│   └── handlers.py       # Command handlers
├── strategy/
│   ├── smc_engine.py     # Core SMC analysis (structure, OB, FVG, liquidity)
│   ├── signal_generator.py  # Trade signal generation + confidence scoring
│   └── scanner.py        # Orchestration, trade monitoring
├── data/
│   ├── database.py       # SQLAlchemy models + ORM
│   └── fetcher.py        # Multi-source OHLCV data
├── config/
│   └── settings.py       # Environment config
├── requirements.txt
├── Dockerfile
├── .env.example
└── .github/workflows/deploy.yml
```

---

## 🚀 Quick Start (Local)

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/smc-vip-bot.git
cd smc-vip-bot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your tokens

# 4. Run
python -m bot.main
```

---

## ☁️ Deploy to Railway

### Step 1 — Create Railway project

1. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Connect your repo
3. Add a **PostgreSQL** database service

### Step 2 — Set environment variables

In Railway dashboard → Variables, set all values from `.env.example`:

| Variable | Required | Notes |
|----------|----------|-------|
| `TELEGRAM_BOT_TOKEN` | ✅ | From @BotFather |
| `VIP_CHANNEL_ID` | ✅ | Your channel ID (e.g. `-1001234567890`) |
| `ADMIN_IDS` | ✅ | Your Telegram user ID(s) |
| `DATABASE_URL` | ✅ | Auto-set if using Railway Postgres |
| `TWELVE_DATA_KEY` | ✅ | [twelvedata.com](https://twelvedata.com) free tier |
| `MIN_CONFIDENCE` | ⚙️ | Default 70 |
| `MAX_SIGNALS_PER_DAY` | ⚙️ | Default 5 |

### Step 3 — Deploy

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Deploy
railway up
```

Or push to `main` branch — GitHub Actions auto-deploys.

---

## 🤖 Bot Commands

| Command | Access | Description |
|---------|--------|-------------|
| `/start` | All | Welcome message |
| `/dashboard` | All | Live dashboard with stats & active trades |
| `/signals` | All | Recent 5 signals |
| `/performance` | All | Win rate & statistics |
| `/bias` | All | Current market bias per instrument |
| `/help` | All | Help & strategy explanation |
| `/force_scan` | Admin | Manually trigger market scan |
| `/manual_signal` | Admin | Send a custom signal |
| `/pause` | Admin | Pause the scanner |
| `/resume` | Admin | Resume the scanner |

---

## 📡 API Keys

### Telegram Bot
1. Message [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy the token to `TELEGRAM_BOT_TOKEN`
3. Create a channel → add the bot as admin
4. Get channel ID: forward a message to [@userinfobot](https://t.me/userinfobot)

### Twelve Data (Forex + Indices)
1. Sign up at [twelvedata.com](https://twelvedata.com) (free: 800 req/day)
2. Copy API key to `TWELVE_DATA_KEY`

### Binance (BTCUSD)
- Public endpoints work **without** an API key for price data
- Optional: add key for higher rate limits

---

## 📈 Instruments

| Instrument | Source | Notes |
|-----------|--------|-------|
| XAUUSD | Twelve Data | Gold — highest volume |
| BTCUSD | Binance | BTC/USDT spot |
| GBPUSD | Twelve Data | Cable |
| USDJPY | Twelve Data | Yen pairs |
| NAS100 | Twelve Data | Nasdaq 100 |
| US30 | Twelve Data | Dow Jones |

---

## ⚠️ Disclaimer

This bot is for **educational and informational purposes only**. Trading financial instruments carries significant risk. Past performance is not indicative of future results. Never risk money you cannot afford to lose. Always use proper risk management (1-2% per trade maximum).
