# Architecture — Quant Sentinel

## Module Map

```
quant_sentinel/
│
├── run.py                    # Entry: Telegram bot
├── train_all.py              # Entry: ML training pipeline
├── train_rl.py               # Entry: standalone RL training
│
├── src/                      # Core business logic
│   ├── config.py             # Environment vars, user prefs, feature flags
│   ├── logger.py             # Logging (console + file + JSON structured)
│   ├── database.py           # SQLite/Turso data layer (dual-write)
│   │
│   ├── smc_engine.py         # Smart Money Concepts analysis (1386 lines)
│   ├── scanner.py            # Multi-TF trade scanner + resolver (1547 lines)
│   ├── finance.py            # Position sizing, SL/TP, risk calc
│   ├── signal_confirmation.py# Post-ensemble signal validation
│   │
│   ├── ensemble_models.py    # ML ensemble: LSTM + XGB + DQN fusion
│   ├── ml_models.py          # LSTM/XGBoost training + inference
│   ├── rl_agent.py           # Double DQN reinforcement learning
│   ├── compute.py            # Feature computation, GPU detection, Numba JIT
│   ├── model_calibration.py  # Platt Scaling for prediction calibration
│   ├── model_monitor.py      # Drift detection (PSI), accuracy tracking
│   │
│   ├── risk_manager.py       # Kelly criterion, circuit breakers, portfolio heat
│   ├── self_learning.py      # Parameter optimization, Thompson Sampling
│   ├── ab_testing.py         # A/B testing framework for parameters
│   │
│   ├── data_sources.py       # Twelve Data API client (rate limited, cached)
│   ├── cot_data.py           # CFTC Commitment of Traders weekly data
│   ├── news.py               # ForexFactory economic calendar
│   ├── sentiment.py          # FinBERT sentiment analysis
│   │
│   ├── auth.py               # User auth (bcrypt + JWT)
│   ├── metrics.py            # In-process counters/histograms
│   ├── monitoring.py         # Telegram alerts (daily P&L, drift, trades)
│   ├── compliance.py         # Hash-chain audit, execution quality, retention
│   ├── db_backup.py          # SQLite backup + WAL mode
│   │
│   ├── ai_engine.py          # OpenAI GPT-4o base client
│   ├── openai_agent.py       # AI agent with memory + tools
│   ├── main.py               # Telegram bot handlers
│   │
│   ├── cache.py              # In-memory TTL cache decorator
│   ├── persistent_cache.py   # Disk-backed cache (IndexedDB-style)
│   ├── api_optimizer.py      # API rate limiter + credit tracking
│   ├── bayesian_opt.py       # Bayesian hyperparameter optimization
│   │
│   ├── indicators.py         # Ichimoku, Volume Profile
│   ├── candlestick_patterns.py # Engulfing, Pin Bar, Inside Bar
│   ├── interface.py          # Telegram bot keyboard layouts
│   │
│   ├── ensemble_voting.py    # LEGACY — use ensemble_models.py
│   └── feature_engineering.py # LEGACY — use compute.py
│
├── api/                       # FastAPI REST + WebSocket API
│   ├── main.py               # App setup, middleware, background tasks
│   ├── middleware/
│   │   ├── jwt_auth.py       # JWT + API key authentication
│   │   └── rate_limit.py     # Token bucket rate limiting
│   ├── routers/
│   │   ├── market.py         # /api/market/* (candles, ticker, indicators)
│   │   ├── signals.py        # /api/signals/* (current, history)
│   │   ├── portfolio.py      # /api/portfolio/* (balance, trades)
│   │   ├── analysis.py       # /api/analysis/* (quant pro, MTF)
│   │   ├── models.py         # /api/models/* (stats, monitoring)
│   │   ├── training.py       # /api/training/* (train, backtest)
│   │   ├── risk.py           # /api/risk/* (halt, resume, status)
│   │   ├── export.py         # /api/export/* (CSV/JSON, audit, reports)
│   │   ├── agent.py          # /api/agent/* (AI chat)
│   │   └── auth.py           # /api/auth/* (register, login)
│   ├── schemas/
│   │   └── models.py         # Pydantic response models
│   └── websocket/
│       └── manager.py        # WebSocket connection manager + heartbeat
│
├── frontend/                  # React 18 + TypeScript + Vite
│   └── src/
│       ├── App.tsx            # Router + providers (Toast, Query, Store)
│       ├── pages/             # Lazy-loaded route pages
│       ├── components/
│       │   ├── charts/        # TradingView lightweight-charts + drawings
│       │   ├── dashboard/     # Header, panels, stats, agent chat
│       │   └── ui/            # Button, Card, Toast, ErrorBoundary
│       ├── hooks/             # WebSocket, caching, performance
│       ├── store/             # Zustand global state
│       ├── api/               # Axios client + circuit breaker
│       └── workers/           # Web Worker for indicator calc
│
├── models/                    # Trained ML models (Git tracked)
├── data/                      # SQLite database (Git tracked)
├── tests/                     # pytest test suite (41 tests)
└── logs/                      # Runtime logs (Git ignored)
```

## Data Flow

```
Market Data (Twelve Data)
        │
        ▼
┌─── SMC Engine ───┐     ┌─── ML Ensemble ───┐
│ Trend, OB, FVG,  │     │ LSTM + XGBoost +  │
│ Grab, BOS, CHoCH │     │ DQN + Calibration │
└────────┬─────────┘     └────────┬──────────┘
         │                         │
         ▼                         ▼
┌──────── Scanner (Multi-TF Cascade) ────────┐
│ 12 filter gates → calculate_position →     │
│ risk_manager check → log_trade             │
└────────────────┬───────────────────────────┘
                 │
    ┌────────────┼────────────┐
    ▼            ▼            ▼
 Database    Telegram     Monitoring
 (dual-write) (alerts)   (metrics)
```

## Key Design Decisions

1. **Dual-write DB**: Local SQLite (fast) + Turso cloud (sync)
2. **Lazy imports**: Avoid circular deps, fast startup
3. **Thread-safe DB**: Lock with 5s timeout, never hangs
4. **Hash-chain audit**: Tamper-proof trade history
5. **Session-aware**: All logic adapts to London/NY/Asian sessions
6. **Self-learning**: Thompson Sampling weights, Bayesian param optimization
7. **Circuit breakers**: Daily loss limits, consecutive loss cooldown
