# Factor importance audit (2026-04-27)

Generated: 2026-04-27T22:06:18

Twin views: (1) trade-side factor presence vs WIN/LOSS, (2) rejection-side filter vs would-have-won ground truth. Both with Bonferroni multiple-comparisons correction.

**Phase-B flip cutoff:** `2026-04-26 19:20:00` (CEST). Pre/post split flags how recent the data is.

## 1. Trade-side factor presence

- Resolved trades with factors JSON: **n=32**, baseline WR: **21.9%**

**Time split (sanity check on relevance):**

| Window | n | wins | WR |
|---|---:|---:|---:|
| pre_phase_B | 29 | 6 | 20.7% |
| post_phase_B | 3 | 1 | 33.3% |

### 1a. All directions combined

Sample is **n≈32** — Bonferroni-corrected p-values are mostly non-significant. This table is **early signal**, not a verdict. n<20 cells flagged with `↘`.

| Factor | n with | n w/o | WR with | WR w/o | Δ pp | p raw | p Bonf |
|---|---:|---:|---:|---:|---:|---:|---:|
| `grab_mss` ↘ | 1 | 31 | 100.0% | 19.4% | +80.6pp | 0.219 | 1.000 |
| `ob_count` | 31 | 1 | 19.4% | 100.0% | -80.6pp | 0.219 | 1.000 |
| `bos` ↘ | 13 | 19 | 46.2% | 5.3% | +40.9pp | 0.010 | 0.122 |
| `rsi_opt` ↘ | 2 | 30 | 50.0% | 20.0% | +30.0pp | 0.395 | 1.000 |
| `killzone` ↘ | 12 | 20 | 8.3% | 30.0% | -21.7pp | 0.212 | 1.000 |
| `fvg` ↘ | 11 | 21 | 9.1% | 28.6% | -19.5pp | 0.374 | 1.000 |
| `ichimoku_bear` ↘ | 16 | 16 | 31.2% | 12.5% | +18.8pp | 0.394 | 1.000 |
| `macro` ↘ | 15 | 17 | 13.3% | 29.4% | -16.1pp | 0.402 | 1.000 |
| `ob_main` | 29 | 3 | 20.7% | 33.3% | -12.6pp | 0.536 | 1.000 |
| `ichimoku_bull` ↘ | 13 | 19 | 15.4% | 26.3% | -10.9pp | 0.671 | 1.000 |
| `choch` | 25 | 7 | 20.0% | 28.6% | -8.6pp | 0.632 | 1.000 |
| `engulfing` ↘ | 4 | 28 | 25.0% | 21.4% | +3.6pp | 1.000 | 1.000 |

### 1b. LONG only

| Factor | n with | WR with | WR w/o | Δ pp | p raw | p Bonf |
|---|---:|---:|---:|---:|---:|---:|
| `bos` ↘ | 4 | 50.0% | 0.0% | +50.0pp | 0.050 | 0.500 |
| `killzone` ↘ | 8 | 0.0% | 25.0% | -25.0pp | 0.467 | 1.000 |
| `fvg` ↘ | 5 | 0.0% | 18.2% | -18.2pp | 1.000 | 1.000 |
| `choch` | 12 | 16.7% | 0.0% | +16.7pp | 1.000 | 1.000 |
| `ichimoku_bull` | 13 | 15.4% | 0.0% | +15.4pp | 1.000 | 1.000 |
| `engulfing` ↘ | 1 | 0.0% | 13.3% | -13.3pp | 1.000 | 1.000 |
| `macro` | 15 | 13.3% | 0.0% | +13.3pp | 1.000 | 1.000 |
| `ob_main` | 15 | 13.3% | 0.0% | +13.3pp | 1.000 | 1.000 |
| `rsi_opt` ↘ | 1 | 0.0% | 13.3% | -13.3pp | 1.000 | 1.000 |
| `ob_count` | 16 | 12.5% | — | — | 1.000 | 1.000 |

### 1b. SHORT only

| Factor | n with | WR with | WR w/o | Δ pp | p raw | p Bonf |
|---|---:|---:|---:|---:|---:|---:|
| `grab_mss` ↘ | 1 | 100.0% | 26.7% | +73.3pp | 0.312 | 1.000 |
| `ob_count` | 15 | 26.7% | 100.0% | -73.3pp | 0.312 | 1.000 |
| `rsi_opt` ↘ | 1 | 100.0% | 26.7% | +73.3pp | 0.312 | 1.000 |
| `choch` | 13 | 23.1% | 66.7% | -43.6pp | 0.214 | 1.000 |
| `bos` ↘ | 9 | 44.4% | 14.3% | +30.2pp | 0.308 | 1.000 |
| `fvg` ↘ | 6 | 16.7% | 40.0% | -23.3pp | 0.588 | 1.000 |
| `ob_main` | 14 | 28.6% | 50.0% | -21.4pp | 1.000 | 1.000 |
| `killzone` ↘ | 4 | 25.0% | 33.3% | -8.3pp | 1.000 | 1.000 |
| `engulfing` ↘ | 3 | 33.3% | 30.8% | +2.6pp | 1.000 | 1.000 |
| `ichimoku_bear` | 16 | 31.2% | — | — | 1.000 | 1.000 |

## 2. Rejection-side: filters blocking would-be winners

- Resolved rejections (`would_have_won IS NOT NULL`): **n=8490**
- Outcome breakdown: TP=599  SL=1874  time-win=3001  time-loss=3016
- Population WR_strict (TP / TP+SL): **24.2%**  |  WR_loose (any positive): **42.4%**
- **Breakeven WR_strict** (R=1.96): **33.7%** — filters above this are blocking +EV setups.

**Direction split (TP / SL / WR_strict / WR_loose):**

| Direction | n | TP | SL | WR_strict | WR_loose |
|---|---:|---:|---:|---:|---:|
| LONG | 4356 | 346 | 1076 | 24.3% | 41.2% |
| SHORT | 4134 | 253 | 798 | 24.1% | 43.7% |

### 2a. Filters ranked by |WR_strict − breakeven|

**Reading the table:** WR_strict only counts setups that resolved at TP or SL (no time-exits). Compares to the **breakeven WR** (~33.7% at R=1.96). Above breakeven → filter is blocking +EV setups. Below → catching losers correctly. Underpowered = `n_at_level < 30` (too few resolved-at-level samples).

| Filter | n_rej | n@lvl | TP | SL | WR_strict | Δ vs breakeven | p Bonf | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `session_performance` | 49 | 43 | 0 | 43 | 0.0% | -33.7pp | <0.001 | ✅ catches losers |
| `directional_alignment` | 1313 | 419 | 48 | 371 | 11.5% | -22.3pp | <0.001 | ✅ catches losers |
| `pattern_weight` | 39 | 31 | 4 | 27 | 12.9% | -20.8pp | 0.103 | neutral |
| `toxic_pattern` | 251 | 228 | 44 | 184 | 19.3% | -14.5pp | <0.001 | ✅ catches losers |
| `rsi_extreme` | 175 | 154 | 70 | 84 | 45.5% | +11.7pp | 0.022 | 🚨 BLOCKS WINNERS |
| `confluence` | 5091 | 1305 | 315 | 990 | 24.1% | -9.6pp | <0.001 | ✅ catches losers |
| `atr_filter` | 1451 | 220 | 88 | 132 | 40.0% | +6.3pp | 0.433 | neutral |
| `htf_confirmation` | 60 | 47 | 18 | 29 | 38.3% | +4.5pp | 1.000 | neutral |
| `hourly_stats` | 9 | 7 | 5 | 2 | 71.4% | +37.7pp | 0.382 | ↘ underpowered |
| `ml_conflict` | 10 | 7 | 4 | 3 | 57.1% | +23.4pp | 1.000 | ↘ underpowered |
| `setup_quality_scalp` | 42 | 12 | 3 | 9 | 25.0% | -8.7pp | 1.000 | ↘ underpowered |

## 3. Caveats

- Trade-side n=32 is too small for definitive ranking. Treat as hypothesis generators only. Re-run after Phase B accumulates 100+ resolved trades.
- Rejection-side `would_have_won` is set by the resolver against forward N-min outcome — it's not the same as **would have hit TP first** (true backtest semantics). It biases toward direction-correctness, not full setup. Useful but not perfect.
- Some factors are always-present descriptors (e.g., `ob_count`, `fvg`) — their WR delta is noise unless we add value-bucketing.
- Bonferroni is conservative; with k≈10-15 factors any raw p<0.005 corrects to <0.05. Lower bar p<0.10 is 'worth investigating', not 'act on'.
- Time-split confirms whether the conclusions still hold post-Phase-B. If pre/post diverges sharply, treat the all-time table with extra suspicion.

## 4. Suggested follow-ups

1. Any filter with `🚨 BLOCKS WINNERS` deserves a manual sample inspection (10-20 rejections per filter, are they obvious losers a human would skip?).
2. Any factor with Bonferroni p<0.10 in trade-view + n>=20 is a candidate for upweighting in scanner score.
3. Re-run this audit weekly. Drop n threshold once post-Phase-B sample reaches 100 trades.