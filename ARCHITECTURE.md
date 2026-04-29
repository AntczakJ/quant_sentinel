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
│   │   ├── ensemble_models.py    #   6-voter ensemble fusion (was 7;
│   │   │                            decompose dropped 2026-04-30 P2.5)
│   │   ├── ml_models.py          #   LSTM + XGBoost training/inference
│   │   │                            (per-fold scalers + WF purge/embargo
│   │   │                             + precomputed_target arg for TB)
│   │   ├── rl_agent.py           #   Double DQN reinforcement learning
│   │   ├── attention_model.py    #   TFT-lite (MultiHeadAttention)
│   │   ├── transformer_model.py  #   DeepTrans (env-gated, default off)
│   │   ├── model_calibration.py  #   Platt Scaling — kill-switch
│   │   │                            DISABLE_CALIBRATION=1 (Batch A)
│   │   └── model_monitor.py      #   Drift detection (PSI)
│   │
│   ├── trading/sim_time.py       #   sim/wall clock helper for backtest
│   │                                (consolidates 7 backtest leak fixes)
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
│   │   ├── compute.py            #   Feature computation (36 features:
│   │   │                            31 base + 3 USDJPY macro + 2 VWAP)
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
├── tests/                        # 445 pytest tests (was 114; +331 since
│                                    2026-04 — leak regression armor)
├── scripts/                      # Utility scripts (start.bat, migrate)
├── docs/                         # Extended documentation
├── Dockerfile                    # Multi-stage Docker build
├── docker-compose.yml            # Container orchestration
└── pyproject.toml                # pytest + mypy + black config
```

## 2026-04-29 / 04-30 — Pre-training audit + cleanup wave

A 4-agent independent audit (`docs/strategy/2026-04-29_audit_*.md`)
returned NO-GO on retraining. 19 of 22 ranked findings closed across
the day (`docs/strategy/2026-04-29_pretraining_master.md` for the
full list). Headlines:

- **Calibration was inverting signals** — Platt fit on TRADE WIN/LOSS
  vs P(LONG-wins) raw output gave negative `a` for all 3 calibrated
  voters. LSTM/XGB/DQN were voting SHORT on every signal regardless
  of model output. Kill-switch `DISABLE_CALIBRATION=1` shipped (Batch A).
- **Training data ≠ inference data** — yfinance GC=F (futures) at train,
  TwelveData XAU/USD (spot) at infer. $65-75 price gap → out-of-distribution
  predictions. Switched to warehouse parquet (Batch B).
- **Multiple data leaks** — centered convolution in Decompose
  (np.convolve mode='same' pulls 10 future bars), scaler fit-on-full
  before walk-forward (4 neural voters), features_v2 ffill +30 min on
  start-stamped HTF bars. All fixed with regression tests.
- **Triple-barrier labels shipped + wired** — `tools/build_triple_barrier_labels.py`
  + `train_all.py --target triple_barrier`. Honest baseline XGB 0.629
  vs binary 0.526 (+10pp).
- **Operational scripts** — `inspect_phase8_retrain.py` (parses
  overnight log, green/red verdict), `preflight_api_restart.py` (12
  sanity checks before live restart), `voter_correlation.py` (D.2
  research; identifies effective voter count).

Voter inventory after the cleanup: XGB + LSTM + Attention + DQN +
SMC heuristic + v2_xgb (currently muted to 0.0 weight pending
re-validation on shifted features). Decompose dropped. DeepTrans
gated off via `QUANT_ENABLE_TRANSFORMER`. So the "7-voter ensemble"
is in practice 3-4 active voters; weights frozen at hand-mutated
values until 2026-04-30 D.1 wired `update_ensemble_weights` to
the trade resolver.
