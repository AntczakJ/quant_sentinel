"""
Uwagi dla Frontend-u: ML Ensemble Integration

Frontend może teraz wyświetlać ML predictions obok SMC analysis.
"""

# ============================================================================
# 1. NOWY ENDPOINT: /analysis/ml-ensemble
# ============================================================================

# Pobiera detailowe ML predictions
# GET http://localhost:8000/analysis/ml-ensemble?tf=15m

# Response:
{
    "timestamp": "2026-04-04T12:00:00Z",
    "timeframe": "15m",
    "current_price": 2050.5,
    "ensemble_signal": "LONG",           # ← SYGNAŁ
    "final_score": 0.742,                 # ← SIŁA SYGNAŁU (0-1)
    "confidence": 0.65,                   # ← PEWNOŚĆ (0-1)
    "models_available": 3,                # ← ILE MODELI DOSTĘPNYCH
    "individual_predictions": {
        "smc": {
            "direction": "LONG",
            "confidence": 0.80,
            "value": 1.0,
            "status": "ok"
        },
        "lstm": {
            "direction": "LONG",
            "confidence": 0.72,
            "value": 0.72,
            "status": "ok"
        },
        "xgb": {
            "direction": "SHORT",
            "confidence": 0.55,
            "value": 0.45,
            "status": "ok"
        },
        "dqn": {
            "direction": "BUY",
            "confidence": 0.70,
            "value": 0.8,
            "status": "ok"
        }
    },
    "weights": {
        "smc": 0.35,
        "lstm": 0.25,
        "xgb": 0.20,
        "dqn": 0.20
    }
}

# ============================================================================
# 2. ZMODYFIKOWANY ENDPOINT: /analysis/quant-pro
# ============================================================================

# Teraz zawiera ML ensemble data w response
# GET http://localhost:8000/analysis/quant-pro?tf=15m

# NOWE POLA:
{
    ...istniejące pola...,
    "ml_ensemble": {
        "signal": "LONG",
        "final_score": 0.742,
        "confidence": 0.65,
        "models_available": 3,
        "predictions": {
            "smc": {"direction": "LONG", "confidence": 0.80, "status": "ok"},
            "lstm": {"direction": "LONG", "confidence": 0.72, "status": "ok"},
            "xgb": {"direction": "SHORT", "confidence": 0.55, "status": "ok"},
            "dqn": {"direction": "BUY", "confidence": 0.70, "status": "ok"}
        }
    }
}

# ============================================================================
# 3. INTERPRETACJA SYGNAŁÓW
# ============================================================================

ENSEMBLE_SIGNAL:
  - "LONG"    → Kupuj (score > 0.65)
  - "SHORT"   → Sprzedawaj (score < 0.35)
  - "CZEKAJ"  → Czekaj (0.35 ≤ score ≤ 0.65 OR confidence < 0.4)
  - "NEUTRAL" → Niski confidence - czekaj

CONFIDENCE:
  - > 0.7   → Silny sygnał (wszystkie modele się zgadzają)
  - 0.4-0.7 → Umiarkowany sygnał
  - < 0.4   → Słaby sygnał (sygnały się przeczyją)

FINAL_SCORE:
  - 1.0     → 100% pewności że LONG
  - 0.5     → Neutralna strefa
  - 0.0     → 100% pewności że SHORT

# ============================================================================
# 4. WYŚWIETLANIE W UI
# ============================================================================

// Przykład React komponentu:

function MLEnsemblePanel({ tf = "15m" }) {
  const [ensemble, setEnsemble] = useState(null);

  useEffect(() => {
    fetch(`/analysis/ml-ensemble?tf=${tf}`)
      .then(r => r.json())
      .then(data => setEnsemble(data));
  }, [tf]);

  if (!ensemble) return <div>Loading...</div>;

  const signalColor = {
    "LONG": "🟢",
    "SHORT": "🔴",
    "CZEKAJ": "🟡",
    "NEUTRAL": "⚪"
  };

  return (
    <div className="ensemble-panel">
      <h3>🤖 ML Ensemble</h3>
      
      {/* Signal */}
      <div className="signal">
        <span>{signalColor[ensemble.ensemble_signal]} {ensemble.ensemble_signal}</span>
        <span>Score: {(ensemble.final_score * 100).toFixed(1)}%</span>
        <span>Confidence: {(ensemble.confidence * 100).toFixed(0)}%</span>
      </div>

      {/* Individual Models */}
      <div className="models">
        {Object.entries(ensemble.individual_predictions).map(([model, pred]) => (
          <div key={model} className="model">
            <span>{model.toUpperCase()}</span>
            <span>{pred.direction}</span>
            <span>{(pred.confidence * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>

      {/* Weights */}
      <div className="weights">
        <small>Weights:</small>
        {Object.entries(ensemble.weights).map(([model, weight]) => (
          <small key={model}>{model}: {(weight * 100).toFixed(0)}%</small>
        ))}
      </div>
    </div>
  );
}

# ============================================================================
# 5. PORÓWNANIE SMC vs ML
# ============================================================================

Wskaż kolizje (konflikty) między SMC a ML:

function ComparisonPanel({ smc, ml }) {
  const conflict = smc.trend === "bull" && ml.ensemble_signal === "SHORT";
  
  return (
    <div className={conflict ? "conflict" : "agree"}>
      <h3>SMC vs ML Comparison</h3>
      <div>SMC: {smc.trend === "bull" ? "🟢 LONG" : "🔴 SHORT"}</div>
      <div>ML:  {ml.ensemble_signal === "LONG" ? "🟢 LONG" : ml.ensemble_signal === "SHORT" ? "🔴 SHORT" : "🟡 CZEKAJ"}</div>
      
      {conflict && (
        <div className="warning">
          ⚠️ KONFLIKT: SMC i ML się nie zgadzają!
          ML confidence: {(ml.confidence * 100).toFixed(0)}%
        </div>
      )}
    </div>
  );
}

# ============================================================================
# 6. STYLING REKOMENDACJE
# ============================================================================

/* ML Signal Colors */
.signal.LONG  { background: #10b981; color: white; }
.signal.SHORT { background: #ef4444; color: white; }
.signal.CZEKAJ { background: #f59e0b; color: white; }

/* Confidence Bars */
.confidence { 
  background: linear-gradient(90deg, #ef4444, #f59e0b, #10b981);
  width: calc(var(--confidence) * 100%);
}

/* Model Icons */
.model.smc  { color: #3b82f6; }
.model.lstm { color: #8b5cf6; }
.model.xgb  { color: #06b6d4; }
.model.dqn  { color: #ec4899; }

# ============================================================================
# 7. ERROR HANDLING
# ============================================================================

Model może być niedostępny jeśli:
- status: "unavailable"
- Wówczas system używa pozostałych modeli

// Obsłuż w UI:
function ModelStatus({ pred }) {
  if (pred.status === "unavailable") {
    return <span className="unavailable">⚠️ Unavailable</span>;
  }
  return <span className="available">✅ {pred.direction}</span>;
}

# ============================================================================
# 8. REAL-TIME UPDATES (WebSocket)
# ============================================================================

Jeśli masz WebSocket w frontend, możesz subskrybować ML updates:

io.on("ml_ensemble_update", (data) => {
  console.log("New ensemble signal:", data);
  // Zaktualizuj UI
});

Backend może wysyłać updates co N sekund:

async def broadcast_ml_update():
    while True:
        ensemble = get_ensemble_prediction(...)
        await manager.broadcast({
            "type": "ml_ensemble_update",
            "data": ensemble
        })
        await asyncio.sleep(60)  # Co minutę

# ============================================================================
# 9. PRZYKŁAD PEŁNEGO DASHBOARDU
# ============================================================================

<DashboardLayout>
  <Grid columns={2}>
    {/* Lewo */}
    <Panel title="SMC Analysis">
      <TrendIndicator trend={smc.trend} />
      <StructureView structure={smc.structure} />
      <FVGIndicator fvg={smc.fvg} />
      <RSIChart rsi={smc.rsi} />
    </Panel>

    {/* Prawo */}
    <Panel title="ML Ensemble">
      <MLSignalBig signal={ml.ensemble_signal} score={ml.final_score} />
      <ConfidenceMeter confidence={ml.confidence} />
      <ModelComparison predictions={ml.individual_predictions} />
      <ComparisonSMCvML smc={smc} ml={ml} />
    </Panel>
  </Grid>

  {/* Full Width */}
  <Panel title="Position Calculator">
    <PositionDetails 
      position={position}
      ensemble={ml}
    />
  </Panel>
</DashboardLayout>

# ============================================================================
# 10. UNIT TESTS FRONTEND'U
# ============================================================================

test("ML Ensemble displays LONG signal", () => {
  const ensemble = {
    ensemble_signal: "LONG",
    final_score: 0.75,
    confidence: 0.65
  };
  
  render(<MLEnsemblePanel data={ensemble} />);
  
  expect(screen.getByText("LONG")).toBeInTheDocument();
  expect(screen.getByText(/75/)).toBeInTheDocument();
});

test("Shows warning on SMC vs ML conflict", () => {
  const smc = { trend: "bull" };
  const ml = { ensemble_signal: "SHORT", confidence: 0.8 };
  
  render(<ComparisonPanel smc={smc} ml={ml} />);
  
  expect(screen.getByText(/KONFLIKT/)).toBeInTheDocument();
});

# ============================================================================
# PODSUMOWANIE
# ============================================================================

Frontend otrzymuje:
1. /analysis/ml-ensemble → Szczegółowe ML predictions
2. /analysis/quant-pro → ML data wbudowana w SMC response
3. Wszystkie modele (SMC, LSTM, XGBoost, DQN) z confidence scores
4. Możliwość porównania SMC vs ML

Można wyświetlić:
- Główny signal (LONG/SHORT/CZEKAJ)
- Individual model predictions
- Confidence scores
- Model weights
- Konflikty SMC vs ML

