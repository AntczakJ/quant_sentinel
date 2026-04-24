# Quant Sentinel — Audit Report (2026-04-24)

System audit against XAU/USD trading research. Brutal but actionable.

## TL;DR — The core diagnosis

Twój system to **klasyczny SMC scanner z ML ensemble** — **dokładnie ten "retail obsession" który research nazywa anti-patternem**. Największe problemy:

1. **ML widzi tylko OHLC gold** — bez DXY, real yields, XAG. "Memorizes patterns without causation" (cytat).
2. **Brak regime classifier** — ten sam stack na trendzie i na range. Research: regime gating fixuje więcej WR niż nowy voter.
3. **Pattern/stats filtry contamined** streakiem + overfit Bayesian params.
4. **News pipeline = regex keyword count** (2010-era NLP) + 3 wpisy w tabeli `news_sentiment`.
5. **Pure SMC (OB, FVG, MSS)** ma słabe backtest evidence jako standalone trigger — działa tylko gdy overlap z pivotami/PDH/VWAP.
6. **Brak VWAP, Asia ORB, LBMA fix, spread-aware filter** — wszystko backtested edge.

System broni się filtrami od złych trejdów, ale fundamentalnie **patrzy na złe sygnały** dla XAU.

---

## 🔴 Co JEST ZŁE (fundamentalne)

### 1. Ensemble nie widzi macro drivers
- Feature set (30 cech) ma WYŁĄCZNIE price-derived: RSI, MACD, ATR, returns, williams, OFI, ADX, candles.
- **Brak DXY, TIPS 10Y real yield, XAG, GLD ETF flows, fed funds futures.**
- LSTM bull acc 28% live to logiczna konsekwencja — model nie wie WHY gold rośnie, tylko patrzy na ruchy price. Dla EUR/USD ok, dla XAU katastrofa (gold to meta-asset: yields + USD + geopolityka + ETF flow).
- **Research**: "ML stack that only sees OHLC can at best learn patterns; it cannot learn why gold moves." Biggest single gap.

### 2. Gold/real-yield correlation PĘKŁA w 2022
- Historycznie -0.82, obecnie +0.02. CB gold buying + de-dollarization overwhelming yield channel.
- **Nasze modele trenowane na danych post-2026-01 powinny być ok**, ALE jeśli korzystały z historical pre-2022 training set, są scripted na wymarłym regime.
- W praktyce to wpływa szczególnie na macro_regime factor w SMC scoring (scanner.py:89-93 używa "zielony"/"czerwony" makro) — może wypacza signals.

### 3. Brak regime classifier (HMM lub BBW+ADX)
- Scanner.py fires TEN SAM cascade na trendzie i na range.
- Research: mean-reversion wygrywa ~65% sessions, trend-follow 35%. Bez regime gating trading strategię anti-strategia.
- **Impact: #1 priorytet WR.** Większy niż nowy voter.

### 4. Pure SMC (OB, FVG, MSS, CHoCH) ma słabe evidence
- Research TradingRush + r/Forex: SMC = rebranded price action. Bez volume/VWAP/intermarket confluence pure SMC jest noise.
- **Nasze SMC scoring:** grab+MSS=+25 (top), DBR/RBD=+20, CHoCH=+15, BOS=+12, FVG=+10, OB=+8.
- Waga za duża na samych SMC bez confirmation. Szczególnie OB (+8) i FVG (+10) często firejują bez prawdziwej confluence.
- **Fix**: OB/FVG score tylko gdy overlap z PDH/PDL/VWAP/pivot. Alternatywa: downgrade weights.

### 5. News pipeline dysfunkcjonalny
```python
BULLISH_WORDS = ["surge", "rally", "rise", "gain", "jump", ...]
BEARISH_WORDS = ["drop", "fall", "decline", ...]
def _detect_sentiment(title): return "bullish" if bull > bear else ...
```
- Regex keyword counting. "Gold fall(s) to support" = bearish (błędnie).
- Tabela `news_sentiment`: 3 wiersze, wszystkie 2026-04-16. Dead feature.
- Scanner.py:564 czyta **najstarszy wpis jako current**.
- Research: headline sentiment has "limited edge"; 2010-era NLP doesn't capture context.

### 6. 7 nakładających się stats filtrów
`fail_rate`, `pattern_weight` (INERT dead code), `toxic_pattern`, `loss_pattern`, `session_performance`, `hourly_stats`, `HTF_confirmation` — compound over-blocking. 96 confluence + 37 toxic_pattern + 17 B-block rejections/24h, 0 entries.

### 7. LSTM trained without macro = always will disappoint
- Live acc bull 28%, bear 84% — model zgaduje "bear default" bo nie ma feature który powie "bullish gold setup".
- Retrain 04-22 nie pomógł bo feature set identyczny.

---

## 🟡 Co jest BEZUŻYTECZNE (dead code + weak edge)

1. **`pattern_weight` filter** (scanner.py:285) — INERT. Używa `LONG_Stable_bullish` naming, trades stored jako `[M5] Trend Bull + FVG`. Mismatch → zawsze `count<5` → defaulty 1.0 → filter nothing. **Remove lub pożenić naming.**

2. **`detect_supply_demand`** — kolejny classical S/R w przebraniu. Waga 1.5 w dynamic_params ale nigdzie nie widzę live usage.

3. **`dpformer` voter** — defused 04-13 (weight=0). Kod jeszcze fires. Remove.

4. **Old `loss_pattern` table** — 3 wpisy z 04-09 ("low_confluence" 0 czynników). Outdated. `check_loss_pattern_match` scanner.py:617 używa stale data.

5. **`decompose` model** — 78.8% "accuracy" = likely data leak. Nie w ensemble weights → live impact 0, ale metric fałszywa.

6. **Bayesian-tuned 15-decimal params** (min_score=4.067353..., risk=0.50129..., target_rr=1.962...) — grid winner z 04-16. CLAUDE.md: "Sharpe stdev > mean → unstable". Ale applied. **Rollback do round numbers** lub rerun z stability constraint.

7. **`deeptrans` weight 0.05** — muted od kwietnia. Nie trenowany w ostatnim retrain. Remove or retrain.

8. **Redundant sentiment paths**: regex (`news.py`) + LLM (`news_sentiment` tabela empty) + event guard (calendar). Trzy drogi, żadna nie daje real signal.

---

## 🔵 Co NAM PSUJE (active harm)

### A. Pattern_stats contamination (streak effect)

`[M5] Trend Bull + FVG`:
- Pre-streak: 3W/4L = 43% WR (normalny pattern)
- Streak #166-171: **6 consecutive LOSS w 1h** 2026-04-17 w okresie LSTM anti_signal
- Streak total #166-186: 0W/8L = 0% WR
- Post-restart: 0 trades (filter self-locked)
- Historia: 15 trades, 20% WR → blocked until n=20

**Problem**: 8 losów w 1h to 1 event (LSTM bug day), nie 8 niezależnych observation. Filtrujemy na skażonych statystykach.

**Fix (just shipped)**: raised n≥8 → n≥20. Allow re-sampling.

### B. Streak auto-pause counted streak losses as "current"
- Pierwszy deploy re-paused immediately bo 5L było na #182-186 (pre-unpause).
- Fix: 6h recency window. Now working.

### C. SMT Divergence firing on noise (pre-fix 167×/session)
- Naive logic: any USDJPY move >0 bars over 10-bar window in same direction.
- Fix: 0.15% magnitude threshold.

### D. B-block blanket scalp → blocked 6-factor setups
- Shipped soften: B allowed when 5+ factors AND score≥35.

### E. Over-aggressive filters combined
- 705 rejections/24h, 0 trades → market może dawać setupy, ale filtry je odrzucają.
- Jeden trade (#189) od restartu 2 dni temu. Time-exit na $3 loss.

### F. Kelly ultra-conservative feedback loop
- WR 21% (przez streak) → f*=0.014 → risk 0.35% → po consec losses 0.18%
- Każdy rzadki A-grade setup ma MICRO size → nawet wygrana nie podnosi balance meaningfully
- Dopóki streak dominates stats, Kelly będzie tnie wszystko do kości

---

## 🟢 Co jest DOBRE (keep)

1. **Pre-event hard block T-5min** — consensus best practice per research.
2. **Soft risk halve T-15min na scalp** — również correct.
3. **Friday 19:30 UTC pre-weekend close** — correct dla XAU specifically.
4. **Time-exit 4h na scalp** — limits exposure.
5. **DQN voter (0.25 weight)** — single healthy voter, 66-80% live acc. Don't touch.
6. **Streak auto-pause (z 6h recency)** — safety net dobrze zaprojektowany teraz.
7. **Toxic pattern filter architecture** (z fixem n≥20) — reasonable self-healing.
8. **Scalp SL floor 4.0 + ATR-scaled** (commit e5772ac) — XAU-appropriate.
9. **HTF trend confirmation** — blocks counter-trend scalps.
10. **Session awareness** (killzone, session performance) — correct concept, just lazy weights.
11. **Config architecture** — dynamic_params, pattern_stats, rejected_setups = good observability.
12. **RSI extreme hard block (>75/<25)** — correct, gold can stay extreme for days, but wanting to catch absolute extremes is sensible.

---

## 🟣 Co MOŻNA/POWINNO WDROŻYĆ (ranked by WR impact)

### P0 — Biggest WR levers

**1. Add DXY + US10Y real yield features to ML ensemble** (3-5 days work)
- Pull from FRED (API already in stack for macro).
- Add to `compute.py:FEATURE_COLS`: `dxy_change`, `dxy_ema_slope`, `us10y_real_change`, `us10y_vs_gold_corr_20d`.
- Retrain all ML voters on expanded feature set.
- **Expected WR lift**: +5-10pp bull accuracy (models finally have macro anchor).
- **Dependency**: check if FRED fetch exists, add if missing.

**2. Regime classifier gating layer** (2-3 days work)
- Compute: `bbw_20 / bbw_20_ma50` (compression ratio), `adx_14`, `atr_ratio_vs_20d`.
- Derive regime: `trending_high_vol` / `trending_low_vol` / `ranging` / `squeeze`.
- Route strategy per regime: TF-following vouchers active in trending, MR vouchers in ranging.
- **Expected WR lift**: +5-10pp (choose right strategy for regime).

**3. Asia Session ORB as discrete voter** (2-3 days)
- Mark Asia session H/L at 07:00 GMT (London open).
- Generate BUY/SELL signal on break beyond Asia H/L with 200 EMA filter.
- Backtested +411%/yr on gold futures per research.
- Add to ensemble weights.

**4. News blackout via real economic calendar** (1-2 days)
- Replace keyword-based impact detection with Finnhub/ForexFactory API.
- Tier 1: NFP/CPI/FOMC/PCE → flat ±15min, trade second rotation only.
- Tier 2: PPI/ADP → size halve.
- Tier 3: Fed speakers → normal + DXY re-weight.
- **Remove regex sentiment entirely** (it's actively hurting).

### P1 — Solid adds

**5. VWAP + session VWAP + anchored VWAP** (3-4 days)
- Current session VWAP, NY session VWAP, aVWAP from NFP print.
- Add to SMC score: OB/FVG valid ONLY if within ATR of VWAP. Cuts noise SMC.
- **Volume proxy**: use tick-volume or /GC if available.

**6. Downgrade pure SMC voters without confluence**
- FVG/OB score 0 unless overlaps PDH/PDL/VWAP/pivot.
- CHoCH/MSS score 0 unless confirmed by subsequent break.
- Score function already has `factors_detail` — just add confluence checks.

**7. Spread-aware rejection**
- Track 20-session median spread; if current > 1.5×, skip entry.
- Gold-specific: spread goes 2 → 40 around news, stops hunt by spread alone.

**8. DXY correlation regime detector**
- Rolling 20-period correlation gold vs DXY.
- Normal: -0.5 to -0.9 (healthy inverse).
- Alert: >-0.3 (fear trade — gold + USD both rise, or risk-on, decoupling).
- In alert regime: mute ML voters (trained for normal correlation), rely on SMC + news.

### P2 — Nice to have

**9. Killzone weights** — already have killzone factor, make it a voter-weight multiplier per session.

**10. Sentiment as CONDITIONER, not GENERATOR** (research point)
- Keep current news_sentiment blocking opposite side.
- Add: if bullish news fires within 60 min AND HTF trend aligned AND 15m candle closed above pre-news range → extend LONG TP by 1.2×, tighten trail.
- Shadow-log for 2 weeks before commit.

**11. LBMA fix times as MR reference** (10:30 GMT / 15:00 GMT)

**12. GPR-based multi-day bias tilt** (geopolitical risk index Z-score)

### P3 — Don't bother

- SMC OBs/FVGs training scripts (already have them, weak edge)
- Decompose model (leak suspect)
- dpformer (defused)
- Pure retraining LSTM on same features (won't fix without macro)

---

## 📊 Data RESET recommendations

**Reset patterns:**
1. **`pattern_stats` table** — wipe entries dominated by streak. Specifically `[M5] Trend Bull + FVG`. Let it rebuild from post-04-23 trades.
2. **`loss_patterns` table** — 3 stale entries z 04-09. Useless.
3. **`news_sentiment` table** — 3 wiersze z 04-16. Clean, rebuild with real feed.

**Keep (but flag as contaminated):**
- `trades` table — keep history, but note #122-186 as "pre-scalp-first + anti-signal LSTM" cohort. Use only post-#189 for live WR computation.
- `ml_predictions` — keep, useful for retraining labels.

**Retrain:**
- **All ML models** with DXY + US10Y features added. Old models effectively corrupted by missing macro anchor.
- Consider regime-conditional training (separate model per regime).

**Reset Bayesian params:**
- `min_score`, `risk_percent`, `target_rr`, `sl_atr_multiplier`, `vol_target_atr` → rollback do round numbers (5.0, 1.0, 2.0, 2.0, 5.0).
- Rerun grid only AFTER regime classifier + macro features deployed (otherwise overfitting to broken foundation).

---

## 📰 News pipeline verdict (user-asked specifically)

**Current state: BROKEN.** 
- Regex keyword sentiment = 2010-era NLP, research says no edge
- 3 rows in news_sentiment table since 04-16, not being populated
- Impact detection = keyword matching (`"fed"` = high impact)
- Pre-event block via calendar WORKS but calendar parsing is stub

**Proposed pipeline** (research-backed):

```
┌─────────────────────────────────────────────────────────────┐
│ EVENT LAYER (real-time calendar via Finnhub/ForexFactory)   │
│ - Tier 1 (NFP/CPI/FOMC/PCE): flat ±15min                    │
│ - Tier 2 (PPI/ADP): risk halve                              │
│ - Post-event: wait 15m candle close, check volume>1.5× med  │
│ - TRADE second rotation (not current "always block")        │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ SENTIMENT LAYER (LLM-based, decay 60-90 min)                │
│ - Replace regex with actual LLM classification              │
│ - Role: CONDITIONER, not GENERATOR                          │
│ - When bullish news + HTF up + 15m close → TP ×1.2          │
│ - Shadow-log 2 weeks before hard rules                      │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ GEOPOLITICAL REGIME LAYER (GPR index Z-score)               │
│ - Daily update                                              │
│ - Z>1 → bias long XAU for 1-5 days (research-backed)        │
└─────────────────────────────────────────────────────────────┘
```

**Konkretnie do zrobienia**:
1. Remove `_detect_sentiment`, `_detect_impact` from `news.py` — delete 20 lines regex
2. Wire Finnhub calendar API dla events (already have key)
3. Add second-rotation trading logic w scanner (post-event 15-60 min window)
4. Shadow-log sentiment→outcome 2 weeks
5. Add GPR index fetch (daily)

**Expected impact**: 5-15% WR or RR improvement on already-filtered setups (research number).

---

## 🎯 Rekomendacja — fazy wdrożenia

**Faza 1 (1 tydzień) — stop the bleeding**: 
- Deploy wszystkie quick-wins z ostatniej sesji (SMT ✅, B-soften ✅, toxic n≥20 ✅)
- Remove dead code: `pattern_weight` inert filter, regex sentiment detection, dpformer
- Reset stale stats: news_sentiment, loss_patterns tables
- Kelly cap: override if WR z ostatnich 20 trejdów < 30%, limit risk to 1% (nie 0.18%) — break feedback loop

**Faza 2 (2-3 tygodnie) — foundations**:
- Add DXY + US10Y real yield features do feature set
- Retrain wszystkie ML voters na rozszerzonym feature set
- Deploy regime classifier (BBW+ADX rule based for V1)
- Replace news keyword detection z calendar API (Finnhub/FF)

**Faza 3 (miesiąc+) — edges**:
- Asia ORB voter
- VWAP family
- Spread-aware rejection
- Second-rotation post-news trading
- GPR multi-day tilt
- Correlation regime detector

**Faza 4 (ciągłe)**:
- Shadow-log sentiment, Asian ORB, second-rotation — 2-week windows każdy
- Rerun Bayesian ONLY po deployment regime + macro features
- Regime-conditional voter weights (bull-trusted voters active only when regime = trending)

---

## Follow-up actionables do decyzji z userem

1. **Approve phase 1 start** (dead code removal + Kelly cap + stats reset)? Najniższe ryzyko, quick wins.
2. **Start macro feature integration** (DXY, real yields)? Wymaga FRED API config + retrain ~30 min.
3. **Regime classifier** — rule-based V1 (BBW+ADX) czy HMM od razu?
4. **News overhaul** — Finnhub integration vs ForexFactory scraping?
5. **Data reset** — tak, robimy na tabelach `loss_patterns`, `news_sentiment`?
