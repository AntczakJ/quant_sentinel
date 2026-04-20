# Shadow-Log Study: directional_alignment filter on H1/4h

**Baseline:** 2026-04-20
**Checkpoint:** 2026-05-04 (T+2 weeks)
**Status:** Observational — no code change. Data already collecting in `rejected_setups`.

## Motivation

Replay analyzer (2026-04-20, `GET /api/replay-analyzer?hours=168`) flagged `directional_alignment` with 1010 rejections over 7 days and hypothetical WR of **59.8%**. If real, that would be the biggest edge left on the table.

### Why we don't act on replay number alone

The `hypothetical_wr_pct` in `api/main.py:1463-1467` treats a rejection as a WIN if price moved **+0.1% in the forward 24-bar window** (~$4.80 on gold at $4790). That's a loose bar — it says nothing about whether a realistic trade with ATR-sized SL and R:R ≈ 1.96 TP would have hit TP before SL.

Secondary concerns:
- Single 7-day window = one regime (Friday 2026-04-17 LONG squeeze + weekend selloff).
- `_scalp_risk_halve` is a **no-op on minimum lot 0.01** (`src/trading/finance.py:487-491` clamps lot_size back to 0.01 after halving). "Relax to soft-halve" on current lot sizes means full-risk pass-through.

Expected realistic WR at R:R 1.96: **35-45%**, likely break-even or worse. Needs verification, not a code commit.

## What we're collecting (automatically)

Table `rejected_setups` (sentinel.db) already captures every rejection with enough info to reconstruct the counterfactual trade:

```sql
-- Schema (abridged)
timestamp DATETIME,
timeframe TEXT,         -- '1h', '4h' are the target
direction TEXT,         -- 'LONG' or 'SHORT'
price REAL,             -- entry price at rejection
atr REAL,               -- ATR for SL sizing
rsi REAL,
trend TEXT,
pattern TEXT,
confluence_count INTEGER,
filter_name TEXT,       -- 'directional_alignment' isolates this study
would_have_won INTEGER  -- currently always NULL, populated by replay script
```

### Baseline volumes (7d through 2026-04-20)

| TF | Rejections | Notes |
|----|-----------|-------|
| 4h | 325 | Primary target |
| 1h | 286 | Primary target |
| 15m | 251 | Pre-commit 110585a only (no longer rejects on this filter) |
| 30m | 89 | Pre-commit 110585a only |
| 5m | 75 | Pre-commit 110585a only |

**Post-commit 110585a (2026-04-17), only 1h and 4h contribute new rows.** Expected throughput: ~611 new H1+4h rejections per 2 weeks.

## Replay recipe (to run on checkpoint)

Build as `scripts/replay_directional_alignment.py`. Steps:

1. **Query rejections** in the study window:
   ```sql
   SELECT id, timestamp, timeframe, direction, price, atr, confluence_count
   FROM rejected_setups
   WHERE filter_name = 'directional_alignment'
     AND timeframe IN ('1h', '4h')
     AND timestamp >= '2026-04-20'
     AND would_have_won IS NULL;
   ```

2. **Reconstruct counterfactual SL/TP** using params in effect at rejection time:
   - `sl_atr_multiplier` (dynamic_params, baseline 2.063)
   - `sl_min_distance` (dynamic_params, baseline 6.587)
   - `target_rr` = `tp_to_sl_ratio` (dynamic_params, baseline 1.963)
   - Also honor `sl_floor = 4.0` for scalp TFs (set in `finance.py:163`)

   ```
   sl_distance = max(atr * sl_atr_multiplier, sl_min_distance, sl_floor)
   tp_distance = sl_distance * target_rr
   For LONG:  sl = entry - sl_distance, tp = entry + tp_distance
   For SHORT: sl = entry + sl_distance, tp = entry - tp_distance
   ```

   **Snapshot these param values in the script** — don't read current values in 2 weeks, because self-learning may have mutated them. Use the 2026-04-20 snapshot above.

3. **Fetch forward bars** from TwelveData — 5m resolution, `[timestamp, timestamp + hold_cap]`:
   - hold_cap = 4h for 1h setups (matches time-exit)
   - hold_cap = 4h for 4h setups (same cap — scalp-mode time-exit applies)
   - Rate limit: 55 credits/min, 611 calls = ~12 min

4. **Simulate hit-first** per bar:
   - SL hit when `bar.high >= sl` (SHORT) or `bar.low <= sl` (LONG)
   - TP hit when `bar.low <= tp` (SHORT) or `bar.high >= tp` (LONG)
   - If both in same 5m bar: assume SL first (pessimistic)
   - If neither by hold_cap: close at last bar's close, record PnL vs entry

5. **Update `would_have_won`** per row:
   - `1` = TP hit
   - `0` = SL hit
   - `2` = time-exit winner
   - `3` = time-exit loser

6. **Aggregate** and output per-TF:
   - `WR = wins / total`
   - `expectancy_R = (wins * R_ratio - losses) / total` where R_ratio = target_rr
   - Also bucket by:
     - Direction (LONG vs SHORT conflict)
     - Confluence (≥3 vs <3)
     - Week (to detect regime bias)

## Decision gate on 2026-05-04

| Realistic WR | Expectancy | Action |
|---|---|---|
| ≥60% | > +0.25R | Relax H1 **and** 4h to soft-halve path (scanner.py:349). |
| ≥55% | > +0.15R | Relax **H1 only** to soft-halve. Keep 4h hard-block. |
| 45-55% | ≥ break-even | Hold. Re-check at T+4 weeks (2026-05-18) with more data. |
| <45% | negative | Validate hard-block stays. Close the question. |

Before acting on any "relax" outcome, verify:
- WR is not driven by one week — re-compute per-week, expect no single week dominating.
- No direction asymmetry — if SHORT-conflict (blocked LONGs) is 70% and LONG-conflict is 40%, fix asymmetrically.
- Remember `_scalp_risk_halve` is no-op at 0.01 lot — soft-halve = full pass-through in practice.

## Rollback / invalidation triggers

Re-baseline (ignore data collected so far, start over) if between 2026-04-20 and 2026-05-04:
- A new voter is added or ensemble weights change materially (±20%).
- `sl_atr_multiplier` or `target_rr` drift >20% from baseline (2.063 / 1.963) — even if we snapshot, scoring might have changed upstream.
- SMC scoring thresholds change (affects which setups even reach the filter).
- Scalp soft-halve gets extended to H1/4h prematurely (makes the study moot).
