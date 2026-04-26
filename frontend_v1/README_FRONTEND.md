# 🎯 QUANT SENTINEL - Frontend

Profesjonalny dashboard do handlu złotem (XAU/USD) z Telegram integracją.

## 🚀 Quick Start

```bash
# Instalacja zależności
npm install

# Dev mode (localhost:5173)
npm run dev

# Build produkcji
npm run build

# Preview built app
npm run preview
```

## 📊 Dashboard Overview

Zbudowany z React + TypeScript + Recharts + TailwindCSS

```
┌─────────────────────────────────────────────────────┐
│  QUANT SENTINEL | XAU/USD  │  $2450.35  │  CONNECTED  │
├──────────────────────┬──────────────────────────────┤
│                      │  🚀 STRONG BUY               │
│  Price Chart         │  Consensus: 0.85             │
│  • Candlestick       │  ───────────────             │
│  • Volume            │  RL: BUY (92%)               │
│  • RSI               │  LSTM: +2.34%                │
│  • Bollinger Bands   │  XGB: UP (89%)               │
│                      │                              │
│                      │  💰 Portfolio                │
│                      │  Balance: $10,500            │
│                      │  P&L: +$245 (+2.4%)          │
│                      │  Position: LONG (Entry $2425)│
├──────────────┬───────┴──────────────────────────────┤
│ ML Models    │ Signal History                       │
│ • Accuracy   │ • Last 20 signals                   │
│ • Episodes   │ • Mini stats per signal             │
│ • Metrics    │ • RSI + confidence                  │
└──────────────┴────────────────────────────────────────┘
```

## 🎨 Komponenty

| Komponent | Plik | Funkcja |
|-----------|------|---------|
| **Dashboard** | `dashboard/Dashboard.tsx` | Root layout + grid |
| **Header** | `dashboard/Header.tsx` | Live price ticker |
| **CandlestickChart** | `charts/CandlestickChart.tsx` | OHLC + indicators |
| **SignalPanel** | `dashboard/SignalPanel.tsx` | Consensus + models |
| **PortfolioStats** | `dashboard/PortfolioStats.tsx` | P&L + balance |
| **ModelStats** | `dashboard/ModelStats.tsx` | ML metrics |
| **SignalHistory** | `dashboard/SignalHistory.tsx` | Trade history |

Szczegóły: patrz [COMPONENTS.md](./COMPONENTS.md)

## 📦 Dependencje

```json
{
  "react": "18.2.0",
  "typescript": "5.3.3",
  "recharts": "2.10.3",           // Wykresy
  "zustand": "4.4.1",              // State management
  "@tanstack/react-query": "5.28", // API queries
  "tailwindcss": "3.4.1",          // Styling
  "lucide-react": "0.383",         // Ikony
  "axios": "1.6.5",                // HTTP client
  "date-fns": "3.0.0"              // Obsługa dat
}
```

## 🔌 API Endpoints

Frontend komunikuje z backendową API:

```typescript
// Market data
GET /api/market/candles      // OHLCV data
GET /api/market/ticker       // Current price
GET /api/market/indicators   // RSI, MACD, BB

// Signals
GET /api/signals/current     // Latest consensus
GET /api/signals/history     // Signal history

// Portfolio
GET /api/portfolio/status    // Balance, P&L, position

// Models
GET /api/models/stats        // ML metrics
```

Konfig: `.env.local` lub `vite.config.ts`
```
VITE_API_URL=http://localhost:8000/api
```

## 🎯 State Management

Zustand store (`src/store/tradingStore.ts`):

```typescript
// Market
ticker: Ticker | null
currentSignal: Signal | null
portfolio: Portfolio | null
modelsStats: AllModelsStats | null

// UI
selectedInterval: string ('15m' default)
wsConnected: boolean

// History
priceHistory: { time, price }[]
```

## 🔄 Real-time Updates

Aktualnie: **Polling** (3-30s intervals)
```typescript
// Np. CandlestickChart auto-refreshuje co 30s
const interval = setInterval(fetchChartData, 30000);
```

Przyszłość: **WebSocket** dla live updates

## 📱 Responsive

- **Desktop**: 3-kolumnowy (chart 2/3, stats 1/3)
- **Tablet**: 2-kolumnowy
- **Mobile**: 1-kolumnowy (stack vertical)

Breakpoints: Tailwind defaults (`sm:`, `lg:`, `xl:`)

## 🎨 Theming

Dark theme (premium trading look):

```css
--bg-dark-bg:        #0f1419
--bg-dark-surface:   #1a2332
--bg-dark-secondary: #2a3a42

--accent-green:      #10b981
--accent-red:        #ef4444
--accent-blue:       #3b82f6
```

## 🐛 Error Handling

Każdy component ma:
- Loading states
- Error boundaries
- Fallback UI
- Console logging

## 🧪 Testing (TODO)

```bash
# Unit tests
npm run test

# E2E tests
npm run test:e2e

# Coverage
npm run test:coverage
```

## 📝 Env Variables

```bash
# .env.local
VITE_API_URL=http://localhost:8000/api
VITE_DEBUG=true
```

## 🚀 Deploy

```bash
# Build
npm run build

# Output: dist/
# Deploy to Vercel/Netlify/S3 + CloudFront

# Health check
curl http://localhost:5173
```

## 📚 Struktura Plików

```
frontend/
├── src/
│   ├── App.tsx                    # Main app
│   ├── main.tsx                   # Entry point
│   ├── index.css                  # Global styles
│   ├── api/
│   │   └── client.ts              # Axios + endpoints
│   ├── components/
│   │   ├── dashboard/             # Dashboard comps
│   │   └── charts/                # Chart comps
│   ├── hooks/                     # Custom hooks
│   ├── store/
│   │   └── tradingStore.ts        # Zustand store
│   └── types/
│       └── trading.ts             # TypeScript types
├── public/                        # Static assets
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
└── README.md
```

## 🔗 Links

- Backend: `http://localhost:8000` (FastAPI)
- Frontend: `http://localhost:5173` (Vite dev)
- Telegram Bot: Quant Sentinel Bot
- DB: SQLite (`data/sentinel.db`)

## 👨‍💻 Dev Tips

1. **Hot reload**: Vite auto-refreshuje na zmiany
2. **React DevTools**: Zainstaluj rozszerzenie
3. **Network**: Dev tools → Network tab dla API calls
4. **Console**: Debuguj z `console.log()`, `console.error()`

## ⚠️ Known Issues

- [ ] Recharts responsive width (needs manual container width)
- [ ] WebSocket disconnect handling
- [ ] Large signal history pagination

## 🎯 Next Steps

1. ✅ Komponenty Charts, Signals, Stats
2. ⏳ WebSocket live updates
3. ⏳ Advanced charting (TradingView embed?)
4. ⏳ Trade execution UI
5. ⏳ Risk calculator
6. ⏳ Performance analytics

---

**Status**: 🚀 Alfa (wszystkie komponenty gotowe)
**Ostatnia aktualizacja**: April 2, 2026

