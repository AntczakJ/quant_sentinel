# XAU/USD Profitable Strategies Research (2026-04-24)

**Research agent findings** — 12 web searches, tier-ranked by backtest evidence.

## Tier A — Strong evidence, underused by generic SMC stacks

1. **Asian-session range breakout / Initial Balance** — backtested +411%/yr on gold futures (TradeThatSwing), profit factor 7.29. Mechanism: Asia low-liquidity → London forces institutional reallocation. 15m entry at London/NY open, filter with 200 EMA trend. Fails on NFP/FOMC days.

2. **NY 08:30 ET news second-rotation setup** — Don't trade first 5 min of CPI/NFP/FOMC. Wait 15 min for spread to normalize, trade second retrace. 80-150 pip gold moves in 2h window post-FOMC. We currently BLOCK instead of TRADING this.

3. **Real-yield / DXY divergence filter** — When gold rallies WITH DXY/US10Y rising, move is fragile (fear premium, not structural). Fade or stand aside. Correlation typically -0.7 to -0.9 with DXY. Our ML doesn't see DXY or US10Y — **biggest gap**.

4. **London killzone momentum (02:00-05:00 ET / 07:00-10:00 GMT)** — LBMA gold fix (10:30 GMT / 15:00 GMT) creates real order flow. 50-100 pip candles. Trade direction of first displacement. Session weight, not just HTF filter.

5. **PDH/PDL liquidity sweep + reversal** — Genuine stop-cluster magnets on gold. Edgeful-confirmed. Pattern = wick + reversal within 1-3 candles. We have this (liquidity_grab) but confirmation-within-N-candles often missing.

6. **VWAP + anchored VWAP (from news / session open)** — Mean-reversion to session VWAP in ranges, trend-follow rejection from aVWAP at NFP/FOMC print. Institutional TWAP/VWAP algos cluster here. Problem: XAU spot has no consolidated volume; use /GC proxy or tick-volume.

7. **Volatility compression → expansion (BB/Keltner squeeze)** — BB(30, 2.2) contracts inside KC(30, ATR*1.8). Breakout follows 70%+ of time within N bars. Direction 50/50 without filter — pair with Asia range or HTF trend.

## Tier B — Works but overhyped / needs filtering

8. **ICT killzones** — time-of-day matters (London, NY AM, NY PM reversal). Use as WEIGHT, not standalone signal.
9. **Fib 61.8/78.6 at confluence** — self-fulfilling. Only works with pivot/PDH overlap.
10. **Mean-reversion in ranging regime (ATR-gated)** — beats trend-follow ~65% of sessions. Needs regime classifier.
11. **Pivot points** — Camarilla S3/R3 fade in range; R4/S4 breakout.
12. **Intermarket pairs (DXY, USDJPY, US10Y, XAG)** — Silver leads gold in risk-on. Multi-asset feature set = quant fund standard.

## Tier C — Marginal / narrative-only

13. **Pure SMC order blocks / FVG as triggers** — TradingRush + r/Forex critique: SMC = repackaged price action. Backtest evidence thin. OBs work when overlap with pivots/PDH/VWAP; pure "last bullish candle before displacement" has no edge.
14. **FVG fill as MR target** — fills 60-70% but that's base rate of any price gap; no alpha.
15. **MSS/BOS as trigger** — just renamed lower-high/lower-low. Useful as trend definition, not entry.

## Anti-patterns (retail obsessions with no gold-edge)

- Pure SMC stack without volume/VWAP/intermarket — indistinguishable from classical S/R + session
- Drawing dozens of OB/FVG zones — confirmation bias machine
- RSI oversold = buy — no edge; gold trends keep RSI extreme for days
- **Fixed-pip stops/TPs** — catastrophic on gold, must be ATR-scaled
- 1m chart scalping without tick execution — spread dominates
- LSTM/sequence models on raw OHLC without macro features — memorizes without causation
- Killzones as hard rule without vol context

## Regime sensitivity (critical)

| Regime | Works | Fails |
|---|---|---|
| Trending (ADX>25, BBW↑) | ORB, pullback-to-EMA, killzone continuation, FVG fill with trend | Mean reversion, Camarilla fades, RSI shorts |
| Ranging (ADX<20, BBW↓) | PDH/PDL sweep reversal, VWAP MR, Camarilla S3/R3 fade, Asia range | Breakouts, MSS entries (mostly fakes), trend-follow |
| High vol (ATR>1.5× 20d, post-news) | Second-rotation reversal, wait-spread-normalize fade | All momentum, tight stops, SMC OB (violated) |
| Low vol / Asia (ATR<0.5× avg) | Range mark-up for London break | Intra-Asia scalps (spread > move) |

**Our 7-voter ensemble has NO regime classifier.** This is likely the biggest WR lever — more impact than any new voter.

## News handling (pro approach)

- Tier 1 (NFP/CPI/FOMC/PCE): flat ±15 min, trade **second rotation only**
- Tier 2 (PPI, ADP, retail): size -50%, stops ATR×1.5
- Tier 3 (Fed speakers, minutes): trade normally but reweight DXY-correlated voter
- FOMC: direction from **dot plot (14:00 ET) + Chair presser (14:30 ET)**, not raw rate decision
- Geopolitical tail (war, sanctions): gold + DXY BOTH rise = different regime

## What's different for XAU vs general FX

1. **Real yields** (TIPS 10Y = FRED DFII10) = single most important feature
2. DXY inverse is baseline but breakable (fear trades)
3. LBMA AM/PM fix (10:30 / 15:00 GMT) = real liquidity events
4. COMEX /GC futures drive spot during NY (13:20 CME open)
5. Physical demand / CB buying = multi-week drifts ML on 1h can't capture
6. Geopolitical premium has persistent autocorrelation (gold follow-through real)
7. Weekend gap risk higher than FX (Friday 19:30 UTC close correct)
8. Spread: normal 2-4, Asia 5-8, news 20-40 — spread-aware essential
9. No consolidated tape — tick-volume broker-local; skeptical of volume features
10. Weekly seasonality: Tue/Wed trending, Fri reversals

## Top 10 codebase recommendations (ranked by WR impact)

1. **Add DXY + US10Y real-yield features** — lstm bearish 0-14% acc almost certainly because no macro anchor
2. **News-blackout via calendar API** — ±15 min Tier 1, avoid news blindness
3. **Regime classifier (HMM or BBW+ADX rule)** — gating layer before voter weighting
4. **Asia-session ORB as discrete voter**
5. **VWAP + session VWAP** as feature + voter
6. **Correlation regime detector** — when DXY/gold correlation drifts from normal, mute ML
7. **Killzone time-of-day as voter weight modifier**, not hard filter
8. **Downgrade pure SMC voters (OB, FVG)** unless overlap with pivot/PDH/PDL/VWAP
9. **LBMA fix times** as MR/breakout reference
10. **Spread-aware rejection** — skip if spread > 1.5× 20-session median

**Biggest single gap:** ensemble has no macro/intermarket awareness. An ML stack seeing only OHLC of XAU can learn patterns but not why gold moves.

---

Sources: TradeThatSwing, QuantifiedStrategies, edgeful, World Gold Council, ECB IRE, SSGA, ICT docs, FXNX, ACY, InnerCircleTrader, ChartSchool, TradingRush, DailyPriceAction, MacroMicro, TrendSpider. Content-quality: shilled (FXM/XS/XNX branded), decent (TradeThatSwing/edgeful backtests), authoritative (WGC/ECB/SSGA).
