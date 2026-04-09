# Architecture — Quant Sentinel v3

## Project Structure

```
quant_sentinel/
│
├── run.py                        # Entry: Telegram bot
├── train_all.py                  # Entry: ML training pipeline
├── train_rl.py                   # Entry: standalone RL training
│
├── src/                          # Backend Python package
│   ├── core/                     # Foundation
│   │   ├── config.py             #   Environment vars, feature flags
│   │   ├── logger.py             #   Logging (console + file + JSON)
│   │   ├── database.py           #   SQLite/Turso dual-write layer
│   │   ├── auth.py               #   JWT + bcrypt user authentication
│   │   └── cache.py              #   In-memory TTL cache decorator
│   │
│   ├── trading/                  # Trading logic
│   │   ├── scanner.py            #   Multi-TF cascade scanner + resolver
│   │   ├── finance.py            #   Position sizing, SL/TP calculation
│   │   ├── risk_manager.py       #   Kelly criterion, circuit breakers
│   │   └── smc_engine.py         #   Smart Money Concepts analysis
│   │
│   ├── ml/                       # Machine Learning
│   │   ├── ensemble_models.py    #   6-model ensemble fusion
│   │   ├── ml_models.py          #   LSTM + XGBoost training/inference
│   │   ├── rl_agent.py           #   Double DQN reinforcement learning
│   │   ├── attention_model.py    #   TFT-lite (MultiHeadAttention)
│   │   ├── decompose_model.py    #   DPformer (Decompose + LSTM + Attention)
│   │   ├── model_calibration.py  #   Platt Scaling calibration
│   │   └── model_monitor.py      #   Drift detection (PSI)
│   │
│   ├── data/                     # External data sources
│   │   ├── data_sources.py       #   Twelve Data API client
│   │   ├── cot_data.py           #   CFTC Commitment of Traders
│   │   ├── macro_data.py         #   FRED real yields + seasonality
│   │   ├── news_feed.py          #   Finnhub news + sentiment
│   │   ├── news_similarity.py    #   FAISS headline similarity
│   │   ├── gpr_index.py          #   Geopolitical Risk Index
│   │   ├── event_reactions.py    #   CPI/FOMC/NFP historical reactions
│   │   ├── news.py               #   ForexFactory calendar
│   │   └── sentiment.py          #   FinBERT sentiment analysis
│   │
│   ├── analysis/                 # Technical analysis
│   │   ├── compute.py            #   Feature computation (31 features)
│   │   ├── indicators.py         #   Ichimoku, Volume Profile
│   │   ├── candlestick_patterns.py  # Engulfing, Pin Bar, Inside Bar
│   │   ├── signal_confirmation.py   # Post-ensemble signal validation
│   │   ├── backtest.py           #   Backtesting engine + Monte Carlo
│   │   └── feature_engineering.py   # LEGACY experimental features
│   │
│   ├── learning/                 # Self-optimization
│   │   ├── self_learning.py      #   Thompson Sampling + pattern stats
│   │   ├── ab_testing.py         #   A/B parameter testing
│   │   └── bayesian_opt.py       #   Bayesian hyperparameter search
│   │
│   ├── ops/                      # Operations & monitoring
│   │   ├── metrics.py            #   In-process counters/histograms
│   │   ├── monitoring.py         #   Telegram alerts (daily P&L, drift)
│   │   ├── compliance.py         #   Hash-chain audit, data retention
│   │   └── db_backup.py          #   SQLite backup + WAL mode
│   │
│   ├── integrations/             # External services
│   │   ├── openai_agent.py       #   GPT-4o agent with memory + tools
│   │   ├── ai_engine.py          #   OpenAI base client
│   │   └── interface.py          #   Telegram bot keyboards
│   │
│   ├── main.py                   # Telegram bot handlers
│   ├── persistent_cache.py       # Disk-backed cache
│   └── api_optimizer.py          # API rate limiter
│
├── api/                          # FastAPI REST + WebSocket
│   ├── main.py                   #   App, middleware, background tasks
│   ├── middleware/
│   │   ├── jwt_auth.py           #   JWT + API key authentication
│   │   └── rate_limit.py         #   Token bucket rate limiting
│   ├── routers/                  #   10 endpoint groups
│   ├── schemas/                  #   Pydantic models
│   └── websocket/                #   WebSocket manager + heartbeat
│
├── frontend/                     # React 18 + TypeScript + Vite
│   └── src/
│       ├── components/charts/    #   TradingView lightweight-charts
│       ├── components/dashboard/ #   Header, panels, agent chat
│       ├── components/ui/        #   Toast, Card, ErrorBoundary
│       ├── hooks/                #   useTheme, useWebSocket, caching
│       └── store/                #   Zustand global state
│
├── models/                       # Trained ML models (Git tracked)
├── data/                         # SQLite database (Git tracked)
├── tests/                        # 114 pytest tests
├── scripts/                      # Utility scripts (start.bat, migrate)
├── docs/                         # Extended documentation
├── Dockerfile                    # Multi-stage Docker build
├── docker-compose.yml            # Container orchestration
└── pyproject.toml                # pytest + mypy + black config
```
