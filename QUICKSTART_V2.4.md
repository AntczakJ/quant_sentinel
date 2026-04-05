# Quick Start Guide — Quant Sentinel V2.4

## Prerequisites
- Python 3.10+
- Node.js 18+
- SQLite or Turso database access

---

## 🚀 Backend Setup

### 1. Install Dependencies
```bash
cd C:\quant_sentinel
pip install -r requirements.txt
```

### 2. Configure Environment
Create/edit `.env` file:
```env
# Database (local SQLite or remote Turso)
DATABASE_URL=data/sentinel.db
# DATABASE_URL=libsql://your-database.turso.io
# DATABASE_TOKEN=your_turso_token

# Market Data API
TWELVE_DATA_API_KEY=your_key_here

# OpenAI Agent
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini  # or gpt-4o for higher quality

# Telegram Bot (optional)
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHANNEL_ID=your_channel_id
```

### 3. Run API Server
```bash
python api/main.py
```
Server starts on `http://localhost:8000`

**What happens on startup:**
- ✅ ML models loaded (RL, LSTM, XGBoost)
- ✅ Background scanner starts (SMC every 15 min)
- ✅ Price broadcaster starts (5 sec intervals, on-demand)
- ✅ Trade resolver starts (auto-marks WIN/LOSS every 5 min)

**Check status:**
```bash
curl http://localhost:8000/health
# Returns: {"status": "healthy", "models_loaded": true}
```

---

## 🎨 Frontend Setup

### 1. Install Dependencies
```bash
cd C:\quant_sentinel\frontend
npm install
```

### 2. Configure Environment
Create `frontend/.env` file (optional):
```env
VITE_API_URL=http://localhost:8000/api
VITE_WS_URL=ws://localhost:8000
```

### 3. Run Development Server
```bash
npm run dev
```
Opens `http://localhost:5173`

**Frontend features:**
- ✅ Real-time price feed via WebSocket
- ✅ Live portfolio stats with win rate
- ✅ Rich signal history with entry/SL/TP
- ✅ Connection status indicator
- ✅ Auto-reconnect if API/WS unavailable

---

## 🤖 Telegram Bot (Optional)

### 1. Run Bot
```bash
python run.py
```

**What the bot does:**
- Sends startup dashboard to Telegram
- `/status` — Portfolio + current signal
- `/cap [amount]` — Set portfolio balance
- `/scan` — Run manual SMC analysis
- `/agent [message]` — Chat with AI agent
- Receives daily reports

**Note:** Bot and API can run simultaneously. They share the same database.

---

## 📊 Dashboard Overview

### Header (Top)
```
[QUANT SENTINEL] [XAU/USD] 
        $2650.50 
     +$10.00 (+0.38%)
[API 🟢 CONNECTED] [📡 WS live]
```
- Shows real-time price from WebSocket
- API status: Health check every 10s
- WS status: Connected/Disconnected

### Signal Panel (Top Right)
```
⚡ CONSENSUS: STRONG_BUY (0.85/1.0)
Current: $2650.50

🤖 Models:
  RL Agent: BUY (75% confidence)
  LSTM: +0.50% forecast
  XGBoost: UP (82% probability)
```

### Portfolio (Right Side)
```
Balance: 10000.00 PLN
Initial: 10000.00 PLN
Equity: 10500.00 PLN

P&L: +500.00 (+5.0%)
ROE: +5.00%
Win Rate: 72.3% (18W/5L)
```

### Signal History (Bottom Right)
```
[LONG] [Stable] [WIN] 2 hours ago
  Entry: $2630.50
  SL:    $2620.00
  TP:    $2650.00
  RSI: 65.2 (Overbought)

[LONG] [MSS] [LOSS] 4 hours ago
  Entry: $2620.00
  SL:    $2610.00
  TP:    $2635.00
  RSI: 45.1
```

### Trade History (Bottom Left)
```
Total: 25 trades
Wins:  18 (72%)
Losses: 5 (20%)
Pending: 2 (8%)

[📈 LONG] Entry: $2630.50
  WIN +$20.00 @ $2650.50 ✅
```

### Charts (Center)
```
Candlestick chart with:
- OHLCV bars (updates every interval)
- Subtle "updating..." indicator during refresh
- No flickering/disappearing
- Full price history preserved
```

---

## 🔄 Background Tasks

### Scanner (Every 15 min)
```
15:00 → Run SMC analysis
15:01 → Calculate entry/SL/TP
15:02 → Save to scanner_signals
      ↓
Logger: "📡 [BG Scanner] Saved LONG signal @ $2650.50 | RSI=68.3"
```

### Price Broadcaster (Every 5 sec)
```
Only broadcasts if clients connected to /ws/prices

Connected? → Fetch price → Broadcast to WS
Not connected? → Skip (saves API calls)

Log: "📊 [PriceBroadcast] XAU/USD $2650.50"
```

### Trade Resolver (Every 5 min)
```
Check all OPEN trades:
  IF direction=LONG AND price >= tp → Mark WIN
  IF direction=LONG AND price <= sl → Mark LOSS
  IF direction=SHORT AND price <= tp → Mark WIN
  IF direction=SHORT AND price >= sl → Mark LOSS

Log: "✅ [Resolver] Trade #42 WIN @ $2650.50 (TP:$2650.00)"
```

---

## 📈 Performance Expectations

### API Response Times
- `/api/market/ticker` — 200-500ms (via Twelve Data)
- `/api/signals/current` — 50-100ms (database)
- `/api/signals/scanner` — 50-100ms (database)
- `/api/portfolio/status` — 50-100ms (database)
- `/api/portfolio/quick-trade` — 1-3s (SMC engine)
- `/api/analysis/quant-pro` — 30-60s (OpenAI + SMC)

### WebSocket Latency
- **Price update latency**: 5 seconds (broadcast interval)
- **Connection time**: ~500ms (WebSocket handshake)
- **Reconnect time**: 3-5 seconds (auto-reconnect)

### CPU / Memory
- **API server**: ~50-100 MB baseline, +20 MB per ML model
- **Scanner task**: ~5-10% CPU during scans (async to_thread)
- **Price broadcaster**: <1% CPU when no clients
- **Frontend**: ~50-100 MB (React + state)

---

## 🛠️ Troubleshooting

### Price not updating in real-time?
```bash
# Check WebSocket connection:
# Open browser DevTools → Application → WS tab
# Should see /ws/prices connection

# If disconnected:
- Check API is running: curl http://localhost:8000/health
- Check CORS: API logs should show connection attempts
- Check firewall: Port 8000 should be accessible
```

### Win rate shows "-"?
```bash
# Stats endpoint returns empty:
# - No trades in database yet
# - Run some manual trades first
# - Wait 5+ minutes for auto-resolver to run

# Check trades:
sqlite3 data/sentinel.db "SELECT COUNT(*) FROM trades WHERE status='WIN'"
```

### Scanner signals not showing?
```bash
# Background scanner hasn't run yet:
# - Scanner runs every 15 minutes
# - Check logs: "📡 [BG Scanner] Saved LONG signal"
# - Manual trigger: Hit "Refresh Analysis" button in UI

# Or check database:
sqlite3 data/sentinel.db "SELECT COUNT(*) FROM scanner_signals"
```

### Add Trade button too slow?
```bash
# Might be using old /api/analysis/quant-pro (30-60s)
# New /api/portfolio/quick-trade should be 1-3s
# Check browser DevTools → Network tab
# Should show /portfolio/quick-trade not /analysis/quant-pro
```

---

## 📋 Database Schema

### Key Tables
- `trades` — All trades (entry, SL, TP, profit, status)
- `scanner_signals` — Background scanner outputs
- `user_settings` — User balance (Telegram bot)
- `dynamic_params` — Portfolio state (frontend)
- `pattern_stats` — SMC pattern statistics

### Useful Queries
```sql
-- Win rate
SELECT 
  COUNT(*) as total,
  SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins,
  ROUND(100.0 * SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) / COUNT(*), 2) as win_rate
FROM trades WHERE status IN ('WIN', 'LOSS');

-- Recent signals
SELECT timestamp, direction, entry, sl, tp, status FROM scanner_signals 
ORDER BY timestamp DESC LIMIT 10;

-- Portfolio balance
SELECT param_value FROM dynamic_params WHERE param_name = 'portfolio_balance';
```

---

## 🔗 API Reference

### Market Data
- `GET /api/market/ticker?symbol=XAU/USD` — Live ticker
- `GET /api/market/candles?symbol=XAU/USD&interval=15m` — OHLCV bars
- `GET /api/market/indicators?symbol=XAU/USD&interval=15m` — Technical indicators

### Signals
- `GET /api/signals/current` — Current consensus signal
- `GET /api/signals/history?limit=50` — Trade history fallback
- `GET /api/signals/scanner?limit=30` — **NEW**: Rich SMC history
- `GET /api/signals/stats` — Win rate, trade counts

### Portfolio
- `GET /api/portfolio/status` — Balance, equity, P&L
- `POST /api/portfolio/update-balance` — Set balance
- `POST /api/portfolio/quick-trade` — **NEW**: Add trade (SMC only, 1-3s)

### Analysis
- `GET /api/analysis/quant-pro?tf=15m` — Full analysis (30-60s)
- `GET /api/analysis/trades?limit=20` — Trade history

### AI Agent
- `POST /api/agent/chat` — Chat with AI
- `POST /api/agent/thread` — Create conversation thread

### WebSocket
- `WS /ws/prices` — **NEW**: Live XAU/USD price feed (every 5s)
- `WS /ws/signals` — Signal updates (when available)

---

## 📞 Support

### Logs
```bash
# API logs
tail -f logs/sentinel.log

# Telegram logs (if running)
# Check console output for /run.py

# Frontend errors
# Check browser Console (F12)
```

### Common Issues
1. **ModuleNotFoundError**: Run `pip install -r requirements.txt`
2. **FastAPI not found**: Verify Python version 3.10+, run pip install again
3. **Port 8000 already in use**: Kill existing process or change port
4. **Database locked**: Close other processes using `data/sentinel.db`

---

**Last Updated**: April 4, 2026  
**Version**: 2.4  
**Status**: ✅ Production-Ready

