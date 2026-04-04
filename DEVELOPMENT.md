# QUANT SENTINEL - Professional Development Guide

## Project Structure

```
quant_sentinel/
├── frontend/                 # React + TypeScript (Vite)
│   ├── src/
│   │   ├── components/      # Reusable React components
│   │   ├── hooks/           # Custom React hooks
│   │   ├── store/           # Zustand state management
│   │   ├── api/             # API client (axios)
│   │   ├── types/           # TypeScript interfaces
│   │   └── App.tsx          # Root component
│   ├── package.json         # Frontend dependencies
│   ├── tsconfig.json        # TypeScript configuration
│   ├── .eslintrc.json       # ESLint rules
│   └── vite.config.ts       # Vite build config
│
├── api/                      # FastAPI backend
│   ├── routers/             # API endpoints (market, signals, portfolio, etc)
│   ├── schemas/             # Pydantic models
│   ├── websocket/           # WebSocket manager
│   └── main.py              # FastAPI application
│
├── src/                      # Core bot logic
│   ├── main.py              # Telegram bot entry point
│   ├── config.py            # Configuration
│   ├── logger.py            # Logging setup
│   ├── database.py          # Database layer (SQLite/Turso)
│   ├── smc_engine.py        # Smart Money Concepts analysis
│   ├── ai_engine.py         # OpenAI GPT-4o integration
│   ├── ml_models.py         # ML models (LSTM, XGBoost)
│   ├── rl_agent.py          # DQN Reinforcement Learning
│   ├── scanner.py           # Market scanner
│   ├── finance.py           # Position calculations
│   ├── indicators.py        # Technical indicators
│   ├── data_sources.py      # Market data providers
│   └── ...
│
├── tests/                    # Test suite
│   ├── run_all_tests.py
│   ├── test_*.py            # Individual test files
│   └── conftest.py
│
├── models/                   # Pre-trained models
│   ├── lstm.keras
│   ├── xgb.pkl
│   └── rl_agent.keras
│
├── requirements.txt          # Python dependencies (PINNED VERSIONS)
├── .flake8                   # Python style guide
├── .pylintrc                 # Python linter config
├── .editorconfig             # IDE configuration
├── .gitattributes            # Git line endings
└── .env.example              # Environment variables template
```

## Code Quality Standards

### TypeScript/React Frontend
- ✅ **Type Safety**: `strict: true` in tsconfig.json
- ✅ **No `any` types**: Enforced via ESLint
- ✅ **No unused variables**: Caught by TypeScript compiler
- ✅ **ESLint rules**: `@typescript-eslint/recommended`
- ✅ **Prettier formatting**: Auto-format with `npm run format`

### Python Backend
- ✅ **Type hints**: All functions have return type annotations
- ✅ **Docstrings**: Google/NumPy style docstrings
- ✅ **Error handling**: Proper exception catching (no bare `except:`)
- ✅ **Logging**: Use `logger` module, not `print()`
- ✅ **Constants**: Uppercase for constants

### General
- ✅ **No hardcoded paths**: Use `os.path` for portability
- ✅ **UTF-8 encoding**: All files must be UTF-8
- ✅ **Line endings**: Unix-style (LF) via `.gitattributes`

## Development Commands

### Frontend
```bash
cd frontend

# Install dependencies
npm install

# Development server (hot reload)
npm run dev

# Type checking
npm run type-check

# Linting (with auto-fix)
npm run lint:fix

# Code formatting
npm run format

# Build for production
npm build
```

### Backend
```bash
# Install dependencies (with pinned versions)
pip install -r requirements.txt

# Run API server
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Run Telegram bot
python src/main.py

# Run tests
python -m pytest tests/

# Check Python code quality
flake8 src/
pylint src/
```

## Dependency Management

### Frontend (package.json)
- ✅ All dependencies have exact versions (no `^` or `~`)
- ✅ Use `npm install` to lock exact versions in package-lock.json

### Backend (requirements.txt)
- ✅ All dependencies are PINNED to exact versions
- ✅ No `>=` or `~=` operators (except legacy dev dependencies)
- ✅ Update with: `pip install -U package==version`

Example update:
```bash
# Check for updates
pip list --outdated

# Update specific package
pip install --upgrade package-name==new.version.number
pip freeze | grep package-name >> requirements.txt
```

## Git Workflow

### Commit Standards
- Use descriptive commit messages
- Follow conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Example: `feat: add WebSocket support for live price updates`

### Pre-commit Checks
```bash
# Frontend
npm run type-check && npm run lint

# Backend
flake8 src/ && pylint src/
```

## Testing

### Run All Tests
```bash
python tests/run_all_tests.py
```

### Run Specific Test File
```bash
python -m pytest tests/test_ml.py -v
```

### Test Coverage
```bash
pip install pytest-cov
pytest --cov=src tests/
```

## Deployment

### Production Build - Frontend
```bash
cd frontend
npm run build
# Output: dist/ folder ready for deployment
```

### Production Deployment - Backend
```bash
# With Gunicorn + Uvicorn
pip install gunicorn
gunicorn api.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker
```

## Environment Variables

Required `.env` file:
```env
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id
OPENAI_API_KEY=your_openai_key
TWELVE_DATA_API_KEY=your_twelve_data_key
DATA_PROVIDER=twelve_data
ENABLE_ML=true
ENABLE_RL=false
ENABLE_ADVANCED_INDICATORS=true
ENABLE_PATTERNS=true
```

## Performance Monitoring

### Key Metrics
- API Response Time: < 1s
- WebSocket Latency: < 100ms
- Database Query Time: < 10ms
- Memory Usage: ~500MB (idle)
- CPU Usage: < 15% (idle)

### Health Checks
```bash
# Check API health
curl http://localhost:8000/api/market/status

# Check WebSocket
wscat -c ws://localhost:8000/ws/prices
```

## Troubleshooting

### Common Issues

1. **TypeScript Compilation Errors**
   ```bash
   npm run type-check
   npm run lint:fix  # Auto-fix errors
   ```

2. **Python Import Errors**
   ```bash
   python -m py_compile src/*.py
   ```

3. **Database Connection Issues**
   - Check `.env` file for `DATABASE_URL`
   - For Turso: ensure `DATABASE_TOKEN` is set

4. **API Rate Limiting**
   - Check `src/api_optimizer.py` for rate limit config
   - Implement exponential backoff retry logic

## Security

- ✅ No API keys in code (use .env)
- ✅ No passwords in Git (use .gitignore)
- ✅ Input validation on all API endpoints (Pydantic)
- ✅ CORS configured for development only
- ✅ SQLite queries use parameterized statements (no SQL injection)

## Performance Optimization

### Frontend
- Code splitting via Vite (automatic)
- Lazy loading components
- Memoization with `useMemo`, `useCallback`
- Zustand for efficient state management

### Backend
- Connection pooling for database
- API response caching (120-300 seconds)
- Async/await for I/O operations
- Model inference caching

## Resources

- **Frontend Framework**: React 18 + TypeScript 5
- **Backend Framework**: FastAPI 0.110
- **State Management**: Zustand 4.4
- **Database**: SQLite3 (with Turso cloud option)
- **ML Models**: TensorFlow 2.15, XGBoost 2.0
- **API Documentation**: http://localhost:8000/docs (Swagger UI)

---

**Last Updated**: 2024-04-03  
**Status**: Production Ready ✅

