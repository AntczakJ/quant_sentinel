# XAU News/Sentiment Research (2026-04-24)

**Research agent findings** — input into system audit synthesis.

## Key conclusions

1. **Headline sentiment = LIMITED edge** (academic consensus: mixed-to-negative). Markets are anticipatory, not reactive.
2. **Gold/real-yield correlation BROKE in 2022** (central bank buying overwhelming yield channel). Historical -0.82 correlation now +0.02. **Models trained on pre-2022 data are suspect.**
3. Sentiment works on LONGER horizons (1-3 months, geopolitical) — not intraday.
4. Extreme sentiment + contra-price = contrarian signal, not trend-follow.

## News tradability ranking for XAU

1. FOMC + dot plot (300-1000+ pips, medium tradability)
2. US CPI core YoY surprise (200-600 pips, medium-high)
3. NFP (200-500 pips, **low tradability for retail** — whipsaw)
4. Fed speakers (50-200 pips, medium)
5. Geopolitical shocks (100-500 pips, low — too fast)
6. Real yields (structural driver, high quality signal)
7. ECB/BoJ/SNB (50-150 pips, medium)
8. GDP/PPI/retail (30-150 pips, medium — surprise only)
9. ETF flows (structural, low tradability)
10. Central bank purchases (slow burn, low-medium)

## Timing playbook

- **T-15 to T-0:** sit out / flatten (our current behavior = consensus best practice ✅)
- **T+0 to T+5:** hard blackout (spread widens 1→15-20 pips, stop-hunts)
- **T+5 to T+15:** WAIT for 15m candle close
- **T+15 to T+60:** enter on confirmation (close beyond pre-news range + next candle same direction)
- **T+60 to T+120:** continuation setups much stronger if range held
- **T+1h onward:** sentiment edge decayed for intraday

## Sentiment → signal conversion (practical)

- **Decay**: 60-90 min post-release for intraday; ~3-day half-life for news-bar sentiment
- **Magnitude scaling**: tier-based (strong/moderate/weak → TP 1.3×/1.1×/1.0×, cap 1.5×)
- **NOT linear scaling** — LLM confidence poorly calibrated (Sharpe swings 2.0→-0.48 across regimes)
- **Use sentiment for position-size / TP modification**, NOT entry origination
- **Confirmation required**:
  - 15m candle close beyond pre-news range
  - Volume > 1.5× rolling median
  - Sentiment direction aligned with HTF trend

## Failure modes

1. Whipsaw/stop-hunt at release
2. Spread explosion triggers stops by widening alone
3. Latency arbitrage (HFT <1ms vs retail 50-500ms)
4. Trading raw number vs policy implication
5. LLM confidence miscalibration (timid in uptrends, reckless in downturns)
6. Overfitting to pre-2022 gold-yield regime
7. Headline topic confusion ("gold hits new high" = reporting, not forward info)
8. Counter-trend sentiment trades have NEGATIVE expected value

## Concrete recommendations

1. **Extend LONG TP by 1.2×** when bullish news fires within 60 min AND HTF trend aligned
2. **Mandatory 15m candle close confirmation** before sentiment unlocks trade modification
3. **Shadow-log sentiment→outcome** for 2 weeks before hard rule (same pattern as directional_alignment memo)
4. **Add GPR-based regime flag** (daily Z-score from geopolitical risk index) for multi-day bias tilt
5. **Keep current pre-event block** (T-15/T-0 blackout) — consensus best practice

## What NOT to build

- Pre-release directional positioning (no retail edge)
- Fast news entry (first 5 min) — can't beat HFT latency
- LLM sentiment as primary entry signal
- Trading geopolitical shock in first 5-30 min

## Realistic expectation

**5-15% WR or RR improvement** on already-filtered setups, not a standalone strategy. Sentiment = **conditioner**, not generator.

---

Sources: 22+ papers/blogs including MDPI, ScienceDirect, arXiv, Permutable.ai, LSEG, World Gold Council, practitioner guides (FXNX, Vantage, Opofinance, ACY).
