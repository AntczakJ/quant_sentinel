# 📊 Frontend Components - QUANT SENTINEL

Nowo zbudowane komponenty dla panelu kontroli handlowego.

## Struktura Komponentów

```
src/components/
├── charts/
│   ├── CandlestickChart.tsx        ✨ NEW - Wykres świec + objętość + RSI + BB
│   └── __init__.ts
├── dashboard/
│   ├── Dashboard.tsx               ✅ Root layout
│   ├── Header.tsx                  ✅ Live price ticker
│   ├── SignalPanel.tsx             ✨ NEW - Consensus signal + modele
│   ├── PortfolioStats.tsx          ✨ NEW - Bilans + P&L + pozycja
│   ├── ModelStats.tsx              ✨ NEW - Statystyki ML (RL, LSTM, XGB)
│   └── SignalHistory.tsx           ✨ NEW - Historia ostatnich sygnałów
└── ui/
    └── [future UI components]
```

## 📈 Komponenty - Szczegóły

### 1. **CandlestickChart** 
- **Plik**: `src/components/charts/CandlestickChart.tsx`
- **Funkcjonalność**:
  - Wykres ceny z candlestick (Open, High, Low, Close)
  - Wizualizacja volume'u
  - RSI indicator z kolorami (Overbought/Oversold)
  - Bollinger Bands (Upper, Middle, Lower)
  - Auto-refresh co 30 sekund
- **Dane**: Z API `/market/candles`, `/market/indicators`

### 2. **SignalPanel**
- **Plik**: `src/components/dashboard/SignalPanel.tsx`
- **Funkcjonalność**:
  - Consensus signal (STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL)
  - Consensus score
  - Indywidualne sygnały od modeli:
    - RL Agent (BUY/SELL/HOLD + confidence)
    - LSTM (predykcja ceny + % zmiana)
    - XGBoost (kierunek + probabilność)
  - Wizualna kodowanie kolorami
- **Dane**: Z API `/signals/current`

### 3. **PortfolioStats**
- **Plik**: `src/components/dashboard/PortfolioStats.tsx`
- **Funkcjonalność**:
  - Balance i Equity
  - P&L (profit/loss) z procentami
  - Status pozycji (LONG/SHORT/NONE)
  - Entry price i unrealized P&L
  - ROE (Return on Equity)
  - Auto-refresh co 3 sekundy
- **Dane**: Z API `/portfolio/status`

### 4. **ModelStats**
- **Plik**: `src/components/dashboard/ModelStats.tsx`
- **Funkcjonalność**:
  - Ensemble Accuracy (główna metryką)
  - RL Agent: Win Rate, Epsilon, Episodes
  - LSTM: Accuracy, Precision, Recall
  - XGBoost: Accuracy, Precision, Recall
  - Kolorowe progress bary
  - Auto-refresh co 10 sekund
- **Dane**: Z API `/models/stats`

### 5. **SignalHistory**
- **Plik**: `src/components/dashboard/SignalHistory.tsx`
- **Funkcjonalność**:
  - Ostatnie 20 sygnałów w chronologicznym porządku
  - Dla każdego sygnału:
    - Konsensus + ikonka
    - Cena w momencie sygnału
    - Consensus score
    - Mini stats: RL action, LSTM %, XGB direction
    - RSI wartość
  - Time ago display (e.g., "2 minutes ago")
  - Statystyki: ilość BUY/SELL sygnałów
  - Auto-refresh co 10 sekund
- **Dane**: Z API `/signals/history`

## 🎨 Styling

Wszystkie komponenty używają:
- **TailwindCSS** - utility classes
- **Dark theme** - kolory z `index.css`:
  - `bg-dark-bg` - tło główne
  - `bg-dark-surface` - karty
  - `accent-green` - bullish (#10b981)
  - `accent-red` - bearish (#ef4444)
  - `accent-blue` - neutral (#3b82f6)

## 📡 API Integration

Komponenty integują się poprzez:
- **API Client** (`src/api/client.ts`):
  - `marketAPI.getCandles()`
  - `marketAPI.getIndicators()`
  - `signalsAPI.getCurrent()`
  - `signalsAPI.getHistory()`
  - `portfolioAPI.getStatus()`
  - `modelsAPI.getStats()`

## 🔄 State Management

Używa **Zustand** (`useTradingStore`):
- Globalna kasa (`ticker`, `currentSignal`, `portfolio`, `modelsStats`)
- Auto-sync z komponentami

## 📱 Responsive Design

- **Desktop**: 3-kolumnowy layout (2/3 chart, 1/3 stats)
- **Mobile**: Responsywny grid (1-kolumnowy)
- **Grid**: `lg:grid-cols-3`, `lg:col-span-2`, etc.

## ✨ Features

✅ Live price updates (3s interval)
✅ Real-time signal consensus
✅ Portfolio tracking z P&L
✅ ML models performance metrics
✅ Signal history z timestamps
✅ Responsive na mobile
✅ Dark theme trading UI
✅ Loading states + error handling
✅ Auto-refresh intervals
✅ Kolorowe visual feedback

## 🚀 Wykorzystanie

Komponenty są już zintegrowane w `Dashboard.tsx`:

```typescript
<Dashboard>
  ├─ Header (live price)
  ├─ CandlestickChart (2/3)
  ├─ SignalPanel (1/3)
  ├─ PortfolioStats (1/3)
  ├─ ModelStats (1/2)
  └─ SignalHistory (1/2)
</Dashboard>
```

## 🔧 TODO - Następne kroki

- [ ] WebSocket live updates (zamiast polling)
- [ ] Advanced chart indicators (MACD, EMA, etc)
- [ ] Position management panel (TP/SL sliders)
- [ ] Trade execution interface
- [ ] Performance analytics page
- [ ] Risk calculator
- [ ] Backtesting simulator

