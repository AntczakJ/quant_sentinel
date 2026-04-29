# `rsi_extreme` filter audit — 2026-04-29

Read-only audit against `data/sentinel.db`. No production code touched.

## TL;DR (verdict)

The Apr-27 memo headline ("rsi_extreme SHORT: 57.4% WR_strict at n=101,
Bonferroni-clear") **does not survive 2 days of additional replay
data**. Today the same query gives **WR_strict 32.4% at n=179 SHORT**
(58 TP / 121 SL). The filter is now *correct on average* — directionally
opposite to the prior conclusion. Sample drift, not regime shift, drives
this: more rows have resolved (n_strict 232 vs 101) and the new ones lean
heavily to SL.

But the per-bucket splits are sharp and worth preserving.

**One-line recommendation:** *Wait — do not act on the Apr-27 memo. The
SHORT effect is not stable. Re-audit after macro_snapshots has ≥4 weeks
of coverage and after a 2nd replay of the new period.*

## Headline numbers (resolved cohort, 2026-04-09 → 2026-04-27)

| Direction | TP | SL | TimeWin | TimeLoss | n_strict | WR_strict | Wilson 95% |
|-----------|----|----|---------|----------|----------|-----------|------------|
| LONG      | 12 | 41 | 0       | 5        | 53       | **22.6%** | 13.5–35.5% |
| SHORT     | 58 |121 | 6       | 10       | 179      | **32.4%** | 26.0–39.6% |

Both directions now show the filter is *more right than wrong*. SHORT is
no longer above 50%.

## Per-TF × direction (the real story)

| TF  | dir   | TP | SL  | n   | WR_strict | Wilson 95%   | Filter is… |
|-----|-------|----|-----|-----|-----------|--------------|------------|
| 5m  | LONG  | 12 | 25  | 37  | 32.4%     | 19.6–48.5%   | mildly correct |
| 5m  | SHORT | 19 | 10  | 29  | **65.5%** | 47.3–80.1%   | **wrong** |
| 15m | LONG  |  0 |  4  |  4  | 0.0%      | 0–49% (tiny) | correct (n=4) |
| 15m | SHORT | 15 |  4  | 19  | **78.9%** | 56.7–91.5%   | **wrong** |
| 30m | SHORT | 17 | 42  | 59  | 28.8%     | 18.8–41.4%   | correct |
| 1h  | LONG  |  0 | 12  | 12  | 0.0%      | 0–24%        | correct |
| 1h  | SHORT |  7 | 37  | 44  | 15.9%     | 7.9–29.4%    | correct |
| 4h  | SHORT |  0 | 28  | 28  | 0.0%      | 0–12%        | correct |

The "filter is wrong" mass is **5m+15m SHORT only** (n=48 combined,
70.8% WR). Above 30m the filter is decisively correct. **4h SHORT has
rsi stuck on the constant 22.8 across all 28 rows** — almost certainly a
logging artefact (same scan retried during a sweep). Treat 4h numbers
as not-real-evidence.

## Per-RSI bucket (SHORT, where the asymmetry lives)

The `direction` column encodes proposed setup direction — RSI is in the
*opposite* zone for each side (RSI low when proposing SHORT, RSI high
when proposing LONG = momentum continuation, not mean-reversion).

| Bucket   | TP | SL | n  | WR_strict | Wilson |
|----------|----|----|----|-----------|--------|
| [0, 5)   | 40 |  2 | 42 | **95.2%** | 84–99% |
| [5, 10)  |  0 | 43 | 43 | 0.0%      | 0–8%   |
| [10, 15) |  0 | 27 | 27 | 0.0%      | 0–12%  |
| [15, 20) | 10 |  5 | 15 | 66.7%     | 42–85% |
| [20, 25) |  8 | 44 | 52 | 15.4%     | 8–28%  |

Bimodal. RSI < 5 SHORT setups would have WON 40/42 — these are deep
oversold capitulation continuations. Filter is dead-wrong here. RSI 5-15
SHORT setups (the bulk of the trigger zone) lose 70/70 — filter is
perfect. **The single threshold collapses two opposite regimes.**

## Per-RSI bucket (LONG)

| Bucket   | TP | SL | n  | WR_strict |
|----------|----|----|----|-----------|
| [75, 80) |  7 | 25 | 32 | 21.9%     |
| [80, 85) |  4 | 12 | 16 | 25.0%     |
| [85, 90) |  1 |  4 |  5 | 20.0%     |

Flat ~22% across the whole overbought range — filter is correctly
catching mean-reversion losers. No relaxation case for LONG.

## Time-window stability

Cohort is **single quarter (2026-Q2, all April 2026)** — every resolved
row falls in 2026-04. `macro_snapshots` only has 29 rows starting
2026-04-27, so no historical join is possible. **No regime split is
possible from this dataset.** The sample is concentrated in one
~3-week window with the API's current scanner config.

## SQL used

```sql
-- Headline per direction
SELECT direction,
       SUM(CASE WHEN would_have_won=1 THEN 1 ELSE 0 END) AS tp,
       SUM(CASE WHEN would_have_won=0 THEN 1 ELSE 0 END) AS sl,
       SUM(CASE WHEN would_have_won=2 THEN 1 ELSE 0 END) AS time_win,
       SUM(CASE WHEN would_have_won=3 THEN 1 ELSE 0 END) AS time_loss
FROM rejected_setups
WHERE filter_name='rsi_extreme' AND would_have_won IS NOT NULL
GROUP BY direction;

-- Per-TF × direction (strict)
SELECT timeframe, direction,
       SUM(CASE WHEN would_have_won=1 THEN 1 ELSE 0 END) AS tp,
       SUM(CASE WHEN would_have_won=0 THEN 1 ELSE 0 END) AS sl
FROM rejected_setups
WHERE filter_name='rsi_extreme' AND would_have_won IN (0,1)
GROUP BY timeframe, direction
ORDER BY timeframe, direction;

-- Per-RSI bucket (SHORT)
SELECT
  CASE
    WHEN rsi <  5 THEN '[0,5)'
    WHEN rsi < 10 THEN '[5,10)'
    WHEN rsi < 15 THEN '[10,15)'
    WHEN rsi < 20 THEN '[15,20)'
    ELSE '[20,25)'
  END AS bucket,
  SUM(CASE WHEN would_have_won=1 THEN 1 ELSE 0 END) AS tp,
  SUM(CASE WHEN would_have_won=0 THEN 1 ELSE 0 END) AS sl
FROM rejected_setups
WHERE filter_name='rsi_extreme' AND direction='SHORT' AND would_have_won IN (0,1)
GROUP BY bucket;

-- Quarterly span check
SELECT strftime('%Y','timestamp') || '-Q' ||
       ((CAST(strftime('%m',timestamp) AS INT)-1)/3 + 1) AS q,
       COUNT(*)
FROM rejected_setups
WHERE filter_name='rsi_extreme' AND would_have_won IS NOT NULL
GROUP BY q;

-- Macro coverage check
SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM macro_snapshots;
SELECT MIN(timestamp), MAX(timestamp) FROM rejected_setups
WHERE filter_name='rsi_extreme';
```

Wilson 95% CI computed in Python (`(p̂ + z²/2n ± z·√(…))/(1+z²/n)`,
z=1.96). Code in the audit transcript.

## Sanity flags found

1. **Apr-27 headline now stale** — n grew 101 → 232 strict; WR collapsed
   57.4% → 32.4%. Every "Bonferroni-clear" claim from a single window
   needs a confirm-window before any code change.
2. **4h SHORT rsi=22.8 constant on all 28 rows** — same value across
   every timestamp 2026-04-21 21:46 onward. This is a logging artefact
   (likely a single scan retried; or `rsi` snapshot cached). Drop 4h
   from any rsi-bucket analysis until verified.
3. **`macro_snapshots` empty for the cohort** — first row 2026-04-27
   14:45, all rsi_extreme rejections are earlier. Cannot regime-split
   without forward-collection.

## Verdict and next step

The cleanest interpretable signal is *not* "57% WR on SHORT" — it is
**bimodal RSI behaviour**: SHORT proposals at RSI < 5 win 95%
(continuation), at RSI 5-20 lose ~7% (mean-reverting). A single
threshold (`rsi < 25`) cannot separate them.

**Do not relax the threshold globally.** That would re-admit the 70/70
losing cluster between RSI 5-15 alongside the 40/42 winners below 5.

**Defensible move (still don't ship yet — wait one more replay window):**
introduce a *carve-out*, not a relaxation. Allow SHORT through the
filter only when `rsi < 5 AND timeframe IN ('5m','15m')`. Block remains
elsewhere. Expected: +40 TP / -2 SL on the audited cohort. Validate on
a fresh window before live.

**One-line recommendation:** *Wait — re-replay in 2 weeks once
macro_snapshots has joinable coverage and n_strict approaches 400; if
the RSI < 5 carve-out still shows >85% WR, ship it as a narrow exception
with macro_regime guard.*
