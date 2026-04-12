# Production Backtest — Documentation

End-to-end walk-forward backtest of the **real production scanner** on
historical OHLCV data. Same code path as live trading (SMC engine → ML
ensemble → risk manager → calculate_position → log_trade) with complete
isolation from production DB.

## Quick start

```bash
# Default: 30 days, 15m step, relaxed filters, full P0-P4 features
python run_production_backtest.py --reset --days 30

# Production cadence (matches live API scanner)
python run_production_backtest.py --reset --days 14 --step-minutes 5

# Specific date window
python run_production_backtest.py --reset --start 2026-03-01 --end 2026-04-01

# Full battery: analytics + Monte Carlo + CSV + PNG
python run_production_backtest.py --reset --days 30 \
    --output reports/bt.json --export-csv reports/bt.csv \
    --plot-equity reports/bt.png --analytics --monte-carlo 1000
```

## Safety isolation (CRITICAL)

The runner NEVER writes to production DB. Three layers enforce this:

1. **`enforce_isolation()` at top of runner** — sets `DATABASE_URL=data/backtest.db`
   and disables `TURSO_URL`. Raises `BacktestIsolationError` if env points
   at `data/sentinel.db`.
2. **Scanner relaxation requires both `QUANT_BACKTEST_MODE=1` AND
   `QUANT_BACKTEST_RELAX=1`** — production entry points (api/main.py,
   src/main.py) explicitly clear these at startup.
3. **`assert_not_production_db()` guard on all write paths** — paranoid
   runtime check.

Verified with 25+ tests in `tests/test_backtest_isolation.py`.

## CLI flags

| Flag | Purpose |
|---|---|
| `--symbol XAU/USD` / `--yf GC=F` | symbol + yfinance ticker |
| `--days N` | backtest window from today |
| `--start/--end YYYY-MM-DD` | explicit date range (overrides --days) |
| `--step-minutes N` | scan cadence (production = 5, default = 15) |
| `--reset` | wipe data/backtest.db first |
| `--resume` | continue from last checkpoint (skip --reset) |
| `--checkpoint-every N` | save progress every N cycles (default 100) |
| `--strict` | disable relaxed filters, run production thresholds |
| `--partial-close` | close 50% at 1R, trail remainder |
| `--no-cache` | bypass yfinance disk cache |
| `--seed N` | random seed for reproducibility (default 42) |
| `--output path.json` | save stats JSON |
| `--export-csv path.csv` | dump all trades to CSV |
| `--plot-equity path.png` | save equity curve PNG |
| `--analytics` | Sharpe/Sortino/expectancy/rolling/heatmap/distribution |
| `--monte-carlo N` | bootstrap trade order N times, return distribution |
| `--walk-forward N` | split window into N chunks, aggregate |
| `--compare A.json B.json` | diff two --output files side-by-side |

## Interpreting results

### Core metrics
- **win_rate_pct**: % closed trades that were WIN
- **profit_factor**: gross_win / gross_loss. >1.5 = tradeable edge
- **max_drawdown_pct**: peak-to-trough on compounding equity
- **max_consec_losses**: risk metric, "worst losing streak"
- **return_pct / final_equity**: actual capital change (lot-aware)
- **alpha_vs_bh_pct**: strategy return − buy-and-hold return

### Diagnostics
- **cycles_total / weekend_skipped / no_setup**: where cycles went
- **ensemble_confidence_avg**: model agreement strength
- **ensemble_signals_long/short/wait**: ML output distribution
- **top_rejections**: which filters blocked most setups

### Advanced (`--analytics`)
- **Sharpe**: >1 = good, >2 = excellent
- **Sortino**: Sharpe without penalizing upside
- **Calmar**: return / |max_dd|. >3 = very strong
- **Expectancy**: $ per-trade expected value. Must be positive.
- **Payoff ratio**: avg_win / avg_loss. >1.5 + WR 40% = profitable
- **Rolling WR stdev**: <0.1 = stable, >0.2 = unstable edge
- **Skewness**: >0 favorable (rare big wins), <0 dangerous
- **Excess kurtosis**: >3 = fat tails (more extreme outcomes)

### Monte Carlo (`--monte-carlo 1000`)
Bootstraps trade order with replacement to stress-test:
- **p5 of return**: 5% worst case. If <0, luck-heavy.
- **p50**: median outcome
- **prob_profitable**: % of simulations ending positive

If p5 > 0, edge survives adversarial resampling = **genuine edge**.
If p5 ≈ 0 and stdev high, real outcome was probably lucky draw.

## Data fidelity caveats

**yfinance vs production Twelve Data:**
- yfinance 5m limited to 60 days
- USD/JPY real-time correlation not reconstructible
- News sentiment = neutral in backtest (would be look-ahead)
- Macro signals (FRED, Myfxbook) = neutral (look-ahead)

**Relaxed filters (default):**
- confluence threshold: 3 (prod) → 2 (backtest)
- "Stable" structure: blocked (prod) → allowed (backtest)

Compensates for missing data. Use `--strict` to disable and match
production behavior exactly (expect 0-5 trades on 60-day yfinance window).

## Execution realism (P6)

- **commission**: $1.00 per round-trip per 0.01 lot
- **slippage**: $0.40 + 0.03 × bar_ATR (vol-scaled)
- **swap**: $0.50/day overnight financing (XAU CFD standard)
- **gap penalty**: 1.4× slippage on gap-filled exits

## Workflow recipes

### Find optimal `min_confidence` threshold
```bash
# Coming soon: --grid-search flag
# For now: manual sweep
for conf in 0.30 0.40 0.50 0.60; do
  # Edit ensemble_strategy min_confidence
  python run_production_backtest.py --reset --days 30 \
    --output reports/bt_conf${conf}.json
done
python run_production_backtest.py --compare reports/bt_conf0.40.json reports/bt_conf0.55.json
```

### Reproduce production day
```bash
# Pick a day where production fired trades, compare backtest
python run_production_backtest.py --reset \
  --start 2026-03-15 --end 2026-03-20 --step-minutes 5 \
  --output reports/mar15-20.json
```

### Regression test after code change
```bash
# Before your change
git stash
python run_production_backtest.py --reset --days 14 --seed 42 \
  --output before.json

# Apply your change
git stash pop

# After
python run_production_backtest.py --reset --days 14 --seed 42 \
  --output after.json

# Diff
python run_production_backtest.py --compare before.json after.json
```

## Troubleshooting

**"0 trades on 30-day run"**
- Window may be sideways → 4h structure=Stable blocks. Try `--start`
  on known-trending window.
- Try `--step-minutes 5` instead of 60 (4× more opportunities).
- Check `top_rejections` in output — if 50%+ are `confluence<2`,
  the data window is genuinely low-setup.

**"All trades stuck OPEN"**
- Resolver uses 5m bars to detect SL/TP hits. If 5m cache failed
  to load, trades never resolve.
- Check for error: `HistoricalProvider: failed fetching 5m`.

**"BacktestIsolationError: production DB"**
- You have `DATABASE_URL=data/sentinel.db` in your shell env.
- `export DATABASE_URL=` (unset) and re-run.

## Files

- `run_production_backtest.py` — main entry, CLI runner
- `src/backtest/isolation.py` — env/DB safety guards
- `src/backtest/historical_provider.py` — yfinance replay
- `src/backtest/analytics.py` — Sharpe/Sortino/expectancy etc.
- `tests/test_backtest_isolation.py` — safety tests
- `tests/test_historical_provider.py` — replay tests
- `data/backtest.db` — scratch DB (gitignored)
- `data/_backtest_cache/` — yfinance disk cache (gitignored)

## Related scripts

- `backtest_harness.py` — simpler standalone harness with pluggable
  strategies (SMA/RSI/ensemble). Use for quick strategy R&D.
- `eval_rl.py` — evaluate specific RL model checkpoints, compare two models.
- `verify_install.py` — post-deploy smoke check (includes backtest artifact sanity).
