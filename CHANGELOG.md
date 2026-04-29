# Changelog

All notable changes to Quant Sentinel. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### 2026-04-29 (evening) — Pre-training audit (NO-GO) + Batch A hotfixes

Four parallel read-only audit agents launched before authorizing any
retraining. All four reached NO-GO independently. 15 distinct findings
ranked P0/P1/P2/P3. Batch A (P0 hotfixes) shipped same evening; Batches
B-E queued for following sessions.

#### Added — `docs/strategy/2026-04-29_audit_{1..4}_*.md` + `_pretraining_master.md`

Five-doc audit set saved to `docs/strategy/`:

- `audit_1_data_leaks.md` — 6 CRITICAL data-leak paths in features
  (centered convolution in Decompose; scaler fit-on-full-set in all 4
  neural voters; multi-TF and USDJPY ffill leaking +30 min into v2_xgb
  which is LIVE @0.10).
- `audit_2_architecture.md` — capacity vs data ratio, voter diversity
  (4 ML voters share the same 34-feature vector — different inductive
  biases on identical info don't decorrelate).
- `audit_3_reprodeploy.md` — `train_all.py:117-127` fetches yfinance
  `GC=F` (Gold Futures) for training; live inference uses TwelveData
  XAU/USD (Spot Gold). $65-75 price gap. Plus zero determinism seeds
  in `train_all.py` and no stale-dll detection for Treelite XGB.
- `audit_4_label_ensemble.md` — Platt calibration parameters
  mathematically inverting signals (`a≈-0.17` for all 3 calibrated
  voters); `update_ensemble_weights` defined but never called →
  voter weights frozen at hand-mutated values; the "7-voter ensemble"
  is in fact 3 voters because the other four sit at floor weight 0.05
  below the 0.10 active threshold; just-shipped triple-barrier labels
  not wired anywhere.
- `pretraining_master.md` — synthesis of all four with severity-
  ranked deduplication, fix order Batches A–E, pre-training go/no-go
  checklist.

#### Fixed — `src/ml/model_calibration.py` — `DISABLE_CALIBRATION` env flag (P0.1)

`ModelCalibrator.calibrate` early-returns the raw prediction unchanged
when `DISABLE_CALIBRATION=1`, bypassing both the fitted-Platt path
AND the 20% uncalibrated-shrinkage path. Set in `.env`. Reversible.

Pre-existing `models/calibration_params.pkl` backed up to
`models/calibration_params_2026-04-29_inverted.pkl.bak` and overwritten
with all `fitted: False` (defense-in-depth — env flag is primary).

The audit verified by loading the .pkl directly and simulating the
mapping across raw 0.10..0.90: output stuck in 0.36..0.40 monotonic
DECREASING in raw, i.e. high raw → low calibrated → ensemble votes
SHORT regardless of model output. Live since the calibration was last
fit; explains why live cohort PF 0.83, return -1.08% pattern resembles
near-random with slight negative drift.

#### Fixed — `tests/test_local_db.py`, `tests/test_new_features.py` — pytest no longer pollutes `data/sentinel.db`

While preparing Batch A: discovered 14 phantom trades (ids 203-216) in
production `sentinel.db` with identical entry=$2350 (live XAU is ~$4574).
Source:

```
tests/test_local_db.py:8       os.environ['DATABASE_URL']='data/sentinel.db'  ← prod!
tests/test_local_db.py:63      db.log_trade('LONG', 2350.0, ..., 'TEST', ...)
tests/test_new_features.py:214 db.log_trade(direction='LONG', price=2350.0, ...)
```

Both are script-style (no `def test_*`); pytest imports them during
collection, runs the module body, inserts trades. Each `pytest tests/`
ran 2 inserts. Fix:

1. Both files now create a per-process tempfile SQLite, set
   `DATABASE_URL` to it BEFORE any database import.
2. After setenv they call `_reinit_connection_for_test()` to invalidate
   any cached module-level `_conn` from earlier test imports — without
   this, an earlier test's `from src.core.database import NewsDB` would
   pin `_conn` to prod and our setenv would have no effect.
3. Best-effort tempfile cleanup on `atexit` (Windows file-lock
   tolerated).
4. Phantom trades 203-216 marked `status='CANCELED'` with audit
   reference in `failure_reason` — prevents API auto-resolver from
   trying to close them against $4574 live price (which would mint
   fake $200 instant-TP profits each).
5. `data/sentinel_backup_2026-04-29_pre_calibration_neutralize.db`
   snapshotted before any DB mutation (gitignored).

#### Tests

`tests/test_new_modules.py::TestModelCalibrator` gains
`test_calibrate_disabled_returns_raw` (verifies kill-switch identity
for both fitted-voter path and unknown-voter path) +
`test_calibrate_unknown_model_applies_shrinkage` gains a
`monkeypatch.delenv` to make the existing test env-independent.

Full pytest: **429 passed / 1 skipped** (was 412/1 yesterday). Verified
`pytest tests/ -q` does NOT increase `sentinel.db` trade count (59 → 59
after a clean run).

#### Not changed — pending user approval

- API NOT restarted yet. Calibration kill-switch takes effect on next
  uvicorn reload because the calibrator caches at module import.
- No retraining. P0.2 (yfinance vs TwelveData training/inference
  distribution mismatch) and P0.3 (v2_xgb features_v2 ffill leak) are
  still active and need Batches B + C before any model is touched.

### 2026-04-29 (late) — sim_time helper + triple-barrier labels + lot-sizing scaffold

Big-batch session: closed the sim-time leak family on the deepest level,
shipped Phase 2 master-plan core (triple-barrier label builder), and
scaffolded Lot Sizing Option A behind an env flag for the 2026-05-04
decision gate. rsi_extreme audit landed (verdict: WAIT — sample drift
flipped the headline 57.4% claim to 32.4%; do not act).

#### Added — `src/trading/sim_time.py` (single source of truth for "now")

Centralizes the sim-vs-wall-clock decision in a single helper that the
backtest harness, scanner filters, smc_engine session classifier, and
Asia ORB voter all share. Production paths default-call wall-clock UTC;
when `QUANT_BACKTEST_MODE=1` and `scanner._SIM_CURRENT_TS[0]` is bound
by `run_production_backtest.py`, we return the simulated bar timestamp.

#### Fixed — three deeper sim-time leaks (not in the original A+B1+B2+B3 family)

The 2026-04-29 audit pattern (`grep -nE "datetime\.now|_persistent_cache"
src/trading/`) surfaced four more wall-clock reads that contaminated
backtest factor scoring. All routed through the new `sim_time.now_utc()`:

- `src/trading/smc_engine.py::is_market_open` — was anchoring CET
  weekend/hour gating to wall-clock when called without a `dt_cet` arg
  (every call site in scanner does this).
- `src/trading/smc_engine.py::get_active_session` — same pattern;
  session classification (overlap/london/ny/asian/off_hours/weekend),
  which feeds both the +15 Asia ORB factor and the session-based risk
  multiplier in `finance.py:104` (overlap=1.0x, asian=0.6x, etc.),
  was using TODAY's UTC hour for any 2024 setup.
- `src/trading/asia_orb.py::get_asia_range` — Asia window anchoring
  defaulted to wall-clock, so backtests built ranges from today's
  Asian session and never produced ORB hits on historical bars.
- `src/trading/asia_orb.py::detect_orb_signal` — same default.

Net effect: with these fixes, a 2024 backtest now classifies session,
killzone, and Asia ORB on the actual simulated hour. Production
behavior is unchanged (env flag unset → wall-clock fallback).

#### Added — `tools/build_triple_barrier_labels.py` (Phase 2 master plan core)

Replaces the binary `compute_target` (0.5 ATR up-move within 5 bars,
flagged tautological in `memory/label_baseline_2026-04-26.md`) with
proper triple-barrier labels per López de Prado:

- For each anchor bar, simulates LONG and SHORT entries, walks forward
  up to `max_holding` bars, and records first-barrier-touched as one
  of {WIN, LOSS, TIMEOUT} with R-multiple.
- Numba-JIT inner loop processes XAU 5min full warehouse (232,129 rows)
  in 2.9s; falls back to pure-numpy when Numba unavailable.
- Output: `data/historical/labels/triple_barrier_{symbol}_{tf}_tp{N}_sl{N}_max{N}.parquet`.

**First-pass distribution** (TP=2*ATR, SL=1*ATR, RR=2, on full warehouse):

| TF    | Bars   | LONG TP | LONG avg_R | SHORT TP | SHORT avg_R |
|-------|--------|---------|-----------|----------|-------------|
| 5min  | 232k   | 33.4%   | +0.054    | 31.0%    | -0.022      |
| 15min | 78k    | 30.9%   | +0.058    | 27.4%    | -0.063      |
| 1h    | 19k    | 28.6%   | +0.093    | 24.0%    | -0.082      |

Validates: random LONG entry on 2023-2026 XAU has positive expected R
across all TFs (gold drift); random SHORT has negative R. Filter
job is to push WR above the 30%-band baseline. **No model training
yet** — labels exist, v2 XGB consumption is the next phase.

#### Added — `USE_FLAT_RISK` env-flag scaffold in `src/trading/finance.py`

Per `docs/strategy/2026-04-27_lot_sizing_rebuild_design.md` Option A:
when `USE_FLAT_RISK=1`, replaces the entire Kelly + daily-DD + session
+ vol + loss-streak risk-percent compounding stack with a single explicit
percentage (default 0.5%, configurable via `FLAT_RISK_PCT`). Logs both
"would have used X%" and "now using Y%" for audit.

**OFF by default — no behavior change today.** Decision gate remains
2026-05-04 per design doc; this is reversible plumbing only.

#### Added — `docs/strategy/2026-04-29_rsi_extreme_audit.md`

Re-runs the 2026-04-27 finding "rsi_extreme SHORT 57.4% WR n=101
(Bonferroni-clear)" against current data. **Verdict: stale.** Sample
grew n=101 → n=232 (+128%); SHORT WR dropped to 32.4% (Wilson 26-40%).
The single-window result reversed under more data — exactly the
overfitting-check failure mode `feedback_overfitting_check.md` warns
about. Bimodal sub-finding: RSI<5 SHORT 95.2% WR (n=42) vs RSI 5-15
SHORT 0% WR (n=70) — but action deferred until macro_snapshots can
backfill regime context (currently 29 rows from 2026-04-27 only).

Side-finding: 4h SHORT rejections show constant `rsi=22.8` across
28 rows — a logging artefact worth investigating separately.

#### Tests

- `tests/test_sim_time.py` (6 cases) — sim/wall fallback, env-flag
  behavior, end-to-end through smc_engine.get_active_session and
  asia_orb.get_asia_range with simulated 2024-08-15 anchor.
- `tests/test_triple_barrier_labels.py` (6 cases) — barrier ordering,
  TP-hit, SL-hit, timeout, sentinel for no-lookahead, real XAU 5min
  distribution sanity.
- `tests/test_finance_flat_risk.py` (4 cases) — env-flag presence,
  default pct, custom pct.

Total new: 16 cases. Full pytest: **428 passed / 1 skipped** (was
412/1 before this batch; +16 = exactly the new tests).

### 2026-04-27 (late evening) — Factor audit + macro snapshots + walk-forward unblock

WR-improvement push that intentionally avoids touching live trading
config (live cohort still N=3 — too small for any tuning). Three
research-side deliverables:

#### Added — `scripts/factor_importance_audit.py`
Twin-view factor importance analysis with overfitting guards:
- **Trade-side** (n=32): per-factor presence vs WIN/LOSS, Fisher exact,
  Bonferroni multi-comparison correction, direction split, time slice
  pre/post Phase-B.
- **Rejection-side** (n=9227 logged, only n=40 resolved): per-filter
  would-have-WR vs baseline. Reveals the rejection resolver was never
  built — `docs/SHADOW_LOG_DIRECTIONAL_ALIGNMENT.md` designs
  `scripts/replay_directional_alignment.py` but it doesn't exist.
- Output: `docs/strategy/2026-04-27_factor_importance_audit.md`.

**Realne odkrycie** (early signal, sample limited):
`bos` (Break of Structure) jest najsilniejszym predyktorem WR mamy:
+40.9pp delta (46% z vs 5% bez), n=13/32, raw p=0.010. LONG-only
view nawet ostrzejszy: +50pp przy n=4. Hypothesis worth re-testing
when sample reaches 100+. **Nie podejmujemy akcji** dopóki próbka
nie urośnie i nie przejdzie Bonferroni.

#### Added — `macro_snapshots` table + persister BG task
- New SQLite table `macro_snapshots` (id, timestamp, macro_regime,
  usdjpy_zscore, usdjpy_price, atr_ratio, uup, tlt, vixy,
  market_regime, signals_json) with indexes on timestamp + regime.
- `NewsDB.write_macro_snapshot(...)` and `get_recent_macro_snapshots()`.
- `_persist_macro_snapshots` BG task in `api/main.py` lifespan —
  5 min cadence, decoupled from trade evaluation, survives
  scanner pause. Activates on next API restart.
- New endpoint `GET /api/macro/snapshots?limit=N` — paginated history.
- **Why:** the 2026-04-27 SHORT #200 forensics had to infer
  `macro_regime` from `factors`-dict presence (no `short_in_bull_regime`
  key meant regime wasn't zielony). With persistence we get direct
  ground truth — enables future B7-efficacy audits, regime-conditioned
  WR analyses, and the factor-audit's "did edge depend on regime?"
  question.
- **First snapshot recorded** (smoke test):
  `regime=zielony, USDJPY z=−1.14, ATR ratio=1.00, market=ranging`,
  i.e. B7 currently ARMED for any SHORT setup.

#### Fixed — `src/backtest/walk_forward.py` (three bugs in one harness)

The walk-forward harness existed in `src/backtest/walk_forward.py` +
`scripts/run_walk_forward.py` but had three layered bugs that meant it
had never produced honest results:

1. **WinError 2 — relative interpreter path.** `.venv/Scripts/python.exe`
   was passed as the subprocess argv[0] without resolving against the
   repo root, so it only worked when CWD was the repo root. Fixed with
   absolute path from `__file__`, `sys.executable` fallback, and
   explicit `cwd=repo_root` on the subprocess.

2. **AttributeError — Windows cp1252 stdout.** `subprocess.run(text=True)`
   uses the platform locale codec for decode, which is cp1252 on
   Windows. The backtest's UTF-8 dashes / Polish chars trip that decode
   and `result.stdout` becomes `None`, then `splitlines()` explodes.
   Fixed by `encoding="utf-8", errors="replace"` plus child env
   `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`. Also rerouted the
   results parsing — instead of fragile stdout grep on the FINAL
   RESULTS block, use `--output <tmp.json>` and load the dict directly.

3. **Silently identical windows — env var nobody reads.** The runner
   set `BACKTEST_START_DATE=<window>` env var per cycle, but
   `run_production_backtest.py` doesn't read that variable. It uses
   `--start` / `--end` CLI flags or falls back to "last N days from
   data tail". So **every window backtested the same default range**
   and produced identical metrics. Caught only when window 0-3 all
   came back as `4 trades, 0 wins, -27.30 PnL` exactly. Fixed by
   passing `--start` and `--end` explicitly to the subprocess.

After all three fixes, `scripts/run_walk_forward.py --quick` runs
end-to-end and produces window-distinct results. Smoke run on
2026-Q1 warehouse data is a 30/7/14 walk-forward (4 windows).

#### Added — `scripts/replay_directional_alignment.py` (built + run)

Implements the spec from `docs/SHADOW_LOG_DIRECTIONAL_ALIGNMENT.md`.
Reads forward bars from the local 5-min warehouse parquet (no API hits)
and walks bar-by-bar to determine whether each rejected setup would have
hit TP or SL first. Updates `would_have_won` per row.

**First full run resolved 8,450 of 9,294 unresolved rejections in 15 s**
(844 skipped because they happened after the warehouse cutoff). The DB
went from "40 resolved / 9,227 NULL" to "8,490 resolved / 844 NULL"
in one execution.

Two metrics surfaced separately to avoid the loose-criterion bias:
- **WR_strict** = TP-hits / (TP-hits + SL-hits) — only setups that
  resolved at a level. Compares directly to the `1 / (1 + R_target)`
  break-even (33.8% at R=1.96).
- **WR_loose** = any-positive / total — includes time-exits with
  PnL>0 from a barely-green close. Easy to confuse with edge.

**Findings on the resolved sample (mostly W15-W17 of 2026):**

| Filter | n@level | WR_strict | Verdict |
|---|---:|---:|---|
| `session_performance` | 43 | 0.0% | ✅ catches losers (perfect) |
| `directional_alignment` | 419 | 11.5% | ✅ catches losers (closes shadow-log study; <45% bucket → "validate hard-block stays") |
| `confluence` | 1,305 | 24.1% | ✅ catches losers |
| `toxic_pattern` | 228 | 19.3% | ✅ catches losers |
| **`rsi_extreme`** | **154** | **45.5%** | **🚨 BLOCKS WINNERS** (Bonferroni p=0.022) |
| `atr_filter` | 220 | 40.0% | neutral after correction |

After Bonferroni multi-comparison correction over 6 filters with
n_at_level ≥ 30, **only `rsi_extreme` clears the 0.05 threshold as a
"blocks winners" candidate**. (An earlier draft of this changelog
flagged `atr_filter` too; that was an artefact of an audit-script bug
treating `would_have_won ∈ {2, 3}` time-exit codes as wins. Fixed.)

**Direction split for `rsi_extreme`** (the one survivor):
- LONG: 22.6% WR_strict (n=53) — catches losers correctly
- SHORT: 57.4% WR_strict (n=101) — Bonferroni p<0.0001 corrected

**Per timeframe** (`rsi_extreme`):
- 30m: 94.4% WR (n=18) ↘ underpowered
- 15m: 65.2% WR (n=23)
- 5m:  47.0% WR (n=66)
- 1h:  36.8% WR (n=19) ↘ underpowered
- 4h:   0.0% WR (n=28) — sample skewed; SL bias

**Actionable (with overfitting caveats):** `rsi_extreme` appears to
be over-rejecting SHORT-side setups in the W15-W17 window. But: (1)
sample is one 17-day window in one regime, (2) `macro_snapshots`
wasn't persisted then so we can't slice by regime, (3) walk-forward
is still pending. **Not a live config change.** Hypothesis tracked
for re-test once `macro_snapshots` accumulates 2+ weeks of regime
data and the daily replay cron resolves a wider sample.

#### Added — `_replay_rejections_daily` BG task

Runs the replay script once per 24h via subprocess (same pattern
walk_forward uses for run_production_backtest). 30-min boot delay
to avoid competing with scanner. Logs `[replay] daily run done — N
rows resolved` per cycle. Pairs with `_persist_macro_snapshots` so
each future rejection gets BOTH ground-truth outcome AND regime
context — the missing piece for proper regime-conditioned filter
audits. Activates on next API restart.

Caveat: rejections within ~hold_cap (4 h) of "now" can't be replayed
until the warehouse is refreshed past their forward window, so they
stay NULL and get picked up on a later night's run. Warehouse refresh
cadence is a separate question (currently manual).

### 2026-04-27 (evening) — Modal TF GPU fixed end-to-end

The "TF falls back to CPU on Modal T4" issue tracked since the Modal
pipeline went live is now resolved. Diagnostic verdict:

```
[1/5] nvidia-smi:        Tesla T4, 15360 MiB, driver 580.95.05    OK
[2/5] nvidia/* pkgs:     14 (cublas/cudnn/cuda_runtime/...)        OK
[3/5] TF import:         tf=2.21.0 in 5.86 s                       OK
[4/5] list GPU devices:  1 GPU [/physical_device:GPU:0]            OK
[5/5] 512×512 matmul:    55.87 ms on /GPU:0                        OK
VERDICT: TF GPU is OPERATIONAL ✓
```

#### Fixed
- **Image base swap**: `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04`
  + `add_python="3.13"` → `debian_slim(python_version="3.13")`. The
  CUDA base shipped cuDNN ~9.0/9.1 (paired with CUDA 12.4) but TF 2.21
  expects CUDA 12.5+ + cuDNN 9.3+. The system cuDNN was getting
  resolved before the pip-installed `nvidia-cudnn-cu12==9.21.1.3`,
  silently breaking GPU init. New image lets `tensorflow[and-cuda]`
  own all CUDA + cuDNN end-to-end via pip — no system libs to
  conflict with. Same TF version, same train_all.py — only the
  underlying base image changed.
- **TF version pin**: bumped from `>=2.20` to `==2.21.0` in the Modal
  image so cuDNN co-install version (9.21.1.3) stays locked-in. uv
  lock already had 2.21.0 resolved; this just stops a future TF 2.22
  surprise from drifting the cuDNN version.

#### Added
- **`gpu_diagnostic` Modal function** + **`gpu_check` local entrypoint**
  in `tools/modal_train.py`. 5-step probe: nvidia-smi → site-packages
  inventory → TF import → `list_physical_devices('GPU')` → real GPU
  matmul. Returns structured findings dict for assertion in
  CI / wrapper scripts. Cost: ~30 s warm / ~3 min first cold start
  (image build). Run `modal run tools/modal_train.py::gpu_check`
  before any full training run when the stack changes.
- **Belt-and-braces `LD_LIBRARY_PATH`** in the image env, listing all
  11 `nvidia/*/lib` paths. TF 2.18+ auto-discovers these at import
  time, but the explicit env helps any sub-process or native lib
  lookup that doesn't go through Python's site-packages logic.

#### Verified next
- New image deployed under `quant-sentinel-train`. Sunday 03:00 UTC
  cron will use the GPU build automatically — no further action.
- 5-epoch smoke training run kicked off as final end-to-end gate.

### 2026-04-27 (afternoon) — TwelveData hardening + lot-sizing design

#### Fixed
- **Env-name drift in observability layer** — `api/routers/system.py`
  recommendations + system/info checked `TWELVEDATA_KEY` and
  `FINNHUB_KEY`, but `.env` (and `src/core/config.py`) actually use
  `TWELVE_DATA_API_KEY` and `FINNHUB_API_KEY`. Settings → Recommendations
  was showing a permanent "TwelveData API key missing" warning even
  though the provider was initialized correctly. Same drift hit the
  startup `[ENV]` report in `api/main.py` for the Turso keys
  (`TURSO_AUTH_TOKEN`/`TURSO_DATABASE_URL` → `TURSO_TOKEN`/`TURSO_URL`).
  Verified: post-restart, recommendations endpoint returns 0 items.

#### Removed
- Dead `get_fx_rate` in `src/trading/finance.py` — sole yfinance call
  on the live-trading-adjacent path. Grep confirmed zero callers
  in repo. Live trading path is now 100 % TwelveData (yfinance lives
  only in offline training + legacy backtest fallback).

#### Added
- **Credit-budget alarm** in `RateLimiter` (`src/api_optimizer.py`).
  Once-per-cooldown WARN when last-min usage crosses
  `alarm_threshold` (default 45 / safe-limit 52 / hard-limit 55).
  Alarm fans out to `logger.warning` + Logfire `rate_limiter.high_usage`
  event + Sentry breadcrumb. Tunable via env vars
  `TWELVEDATA_ALARM_THRESHOLD` and `TWELVEDATA_ALARM_COOLDOWN_SEC`.
  `get_stats()` now exposes `alarm_threshold`, `alarm_cooldown_sec`,
  and `last_alarm_ts` so the Settings widget can show the threshold
  marker and the most recent alarm age.
- **Settings `RateLimitBlock` refactor** — bar now visualizes
  rolling-minute *usage* (0 → 55) with green / gold / red zones,
  plus marker lines at the alarm threshold (gold) and skip-cycle
  guard (red). Three-color legend + new "Last alarm" stat.
- **`twelvedata_plan_policy.md` memory** — declares the project rule
  that all live data goes through TwelveData (paid plan, 55 / min
  hard cap), documents env-var name (`TWELVE_DATA_API_KEY`), and
  notes the rate budget envelope for new live fetches.

#### Investigated
- **SHORT trade #200** (2026-04-27 01:08 UTC, +14.86 PLN, lot 0.01) —
  factors dict had no `short_in_bull_regime` key, confirming
  `macro_regime` was not "zielony" at trade time. B7 logic verified
  working on the first live SHORT post-flip. Side-finding:
  `macro_regime` is computed live but not persisted — no
  `macro_snapshots` table — so historical audits of this kind
  rely on inferring from `factors` presence.

#### Documented
- **`docs/strategy/2026-04-27_lot_sizing_rebuild_design.md`** —
  3-option design doc (constant 0.5 % / model-driven R-mult /
  ¼-Kelly) with explicit decision gate (≥ 30 post-config trades + 7d
  PF within ±20 % of backtest 1.21 + B7 verified). Recommendation:
  **Option A** once gate clears, no implementation before
  2026-05-04.

### 2026-04-27 — Logfire / Sentry / Modal wired up

End-to-end activation of the three external services that the v4 push
left as soft-stub. All three now actively shipping data:

- **Logfire**: project `antczak-j/quant-sentinel` created at
  `https://logfire-eu.pydantic.dev/antczak-j/quant-sentinel`, EU region,
  credentials in `.logfire/logfire_credentials.json` (gitignored). API
  startup picks them up automatically. `POST /api/system/test-trace`
  returned `{ok: true}` and the span landed in the dashboard.
- **Sentry**: DSN in `.env` (gitignored), env report confirms
  `SENTRY_DSN: OK` at startup. `POST /api/system/test-error` raised
  the intentional ZeroDivisionError and Sentry captured it (500 in
  the API log; event in Issues).
- **Modal Labs**: token at `~/.modal.toml`, workspace `antczakj`. App
  deployed at `https://modal.com/apps/antczakj/main/deployed/quant-sentinel-train`.
  First deploy with the full ML stack (TF + Torch + transformers +
  sentence-transformers + treelite ≈ 6 GB) hit the free-tier image-build
  shutdown; trimmed `tools/modal_train.py` to what `train_all.py`
  actually imports (numpy / pandas / sklearn / xgboost / TF / scipy /
  tqdm / pydantic ≈ 2-3 GB) and the second deploy succeeded in 76 s.

#### Fixed
- `_safe_version` in `api/routers/system.py` falls back to `.VERSION`
  attr — `sentry_sdk` exposes `VERSION` (uppercase), not
  `__version__`, so /api/system/info was returning null for it.

#### Added later in the same day (after the auth flow)

After the three integrations were live, an extension batch added:

- **Cmd+K "External" group** — three palette actions (Open Logfire
  dashboard / Open Sentry Issues / Open Modal app), each just a
  `window.open()` with the right URL. Entries also bump the Recent
  ring so they show up at the top of the palette after first use.
- **Settings ExternalServicesBlock** — three sub-cards with status
  pills (`✓ ACTIVE` green when configured, else muted) and "Open
  dashboard ↗" button per service. Status comes from a new
  `/api/system/info.integrations` field that probes file presence
  beyond just env vars (Logfire credentials file, ~/.modal.toml).
- **`scripts/start.ps1`** — PowerShell wrapper for everyday DX:
  `api`, `dev`, `both`, `stop`, `status`, `restart` subcommands.
  Idempotent (checks ports first, won't double-spawn). Auto-runs
  `npm install` if frontend/node_modules is missing.
- **Logfire structured event in resolver loop** — every
  `_auto_resolve_trades` cycle ends with
  `_logfire.info("resolver.cycle.done", open_count=N,
  trades_resolved=K, spot_price=X)` so the resolver path is as
  searchable in the Logfire dashboard as the scanner side. An
  `resolver.cycle.failed` exception event covers the error path.
- **`GET /api/scanner/peek`** — read-only ad-hoc indicator
  snapshot. Computes ATR(14), RSI(14), EMA-20 distance, 14-bar
  high/low, 20-bar volatility on the latest 100 bars of any TF.
  No SMC scoring, no ML inference, no DB writes — answers "why no
  trade today?" without dropping into a shell. Settings page
  ScannerPeekBlock card with TF picker (5m/15m/30m/1h/4h),
  bias pill (bullish/bearish/neutral from EMA distance + RSI),
  and 8-tile metric grid. 30 s polling.

#### Modal pipeline — ongoing issues
- TF inside the T4 container still falls back to CPU despite
  `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04` base + `tensorflow
  [and-cuda]`. XGBoost CUDA does work (`device='cuda'` confirmed).
  Cost overhead at weekly cadence: ~$0.50/mc wasted on T4 that's
  underused by LSTM. Tracked for next session.
- First end-to-end Modal run produced model files identical SHA1
  to local pre-train versions because the bundled `/repo/models`
  was overwriting freshly-trained weights post-run. Fixed in
  `ce63402` by excluding `models` from the image bundle.
- Local network glitch (100% packet loss to `api.modal.com` after
  laptop sleep) blocked subsequent retries — neither bug nor
  Modal-side, just ISP/router. Weekly cron will retry on its own.

### 2026-04-26 → 2026-04-27 — v4 frontend redesign + observability + ML perf push

A two-day session producing 18 commits. Frontend redesigned end-to-end,
backend gained 10 new endpoints + observability stack (Logfire + Sentry),
defensive `dynamic_params` schema closes the bug class behind `95569f7`,
Treelite ships a 12× speedup on the live-scanner XGB inference path.
Production scanner / trade resolution paths untouched throughout — every
new feature defaults OFF or is opt-in.

#### Added — Frontend (v4 redesign)
- Cursor-reactive WebGL **mesh-gradient background** via Paper Shaders
  (`MeshBackground`), lazy-loaded, disabled on `/chart` to free GPU for
  lightweight-charts. Grain noise overlay. (`2236dc5`)
- **Cmd+K command palette** (`cmdk`) — pages, symbols, recent trades,
  scanner pause/resume, grid preview/apply, grid rollback, refresh,
  reduced-motion toggle. (`2236dc5`, `9b6d9cd`, `6c292ac`)
- **Bento Dashboard** — 12-col grid with Motion `layoutId` expand-to-modal
  cards. Balance / WinRate / Recent P&L / Open / Macro / Recent signals
  / Scanner all expand to detail views. (`2236dc5`, `71a35a5`)
- **NumberFlow rolling digits** + `FlashOnChange` bull/bear pulse on
  every live numeric. (`2236dc5`, `71a35a5`)
- **AnimatedBeam** voter→ensemble→signal flow on Models page; intensity
  scales with `voter_weight × accuracy`. (`2236dc5`, `71a35a5`)
- **VoterCard expandable** with 72-h forward-move accuracy and per-voter
  retrain commands. (`9b6d9cd`)
- **Equity curve** in `BalanceDetail` (with trades-derived fallback when
  cache empty), USD/JPY 1h × 200-bar chart in MacroDetail, open-positions
  detail with 5 s polling. (`71a35a5`, `63e5bab`)
- Mini-sparklines under WR + Recent P&L bento. Magnetic buttons.
  ScrambleText brand reveal. Aurora bg. WebAudio sound feedback. (`2236dc5`)
- `?` keyboard shortcuts overlay. (`faee71f`)
- Settings widgets: SystemInfo (versions / models / GPU / disk / env /
  git short SHA), RateLimit (credit bucket bar), DbStats (table counts +
  sentinel.db file size). (`faee71f`, `8ffb7fc`, `d5c732f`)
- Cmd+K recent-actions history (last 5 in localStorage). (`30c9fbb`)
- HealthDeepPopover replaces the static live/down pill — click for
  per-subsystem status (DB / models / GPU / scanner / trades).
  (`379fc99`)
- React `ErrorBoundary` around routes — render exceptions show a
  recoverable fallback instead of a blank screen. (this release)

#### Added — Backend endpoints
- `POST /api/scanner/{pause,resume}` + `GET /api/scanner/status` — surface
  the file-flag mechanism. (`71a35a5`)
- `GET /api/models/ensemble-weights` reads voter weights from
  `dynamic_params`. (`71a35a5`)
- `GET /api/portfolio/history` reconstructs from `trades` when cache empty.
  (`71a35a5`)
- `GET /api/params/{usage,drifts}` — live writer/reader counters + drift
  detector for `dynamic_params`. (`e0ccc66`)
- `GET /api/grid/{list,preview,apply,backups,rollback}` — surfaces
  `apply_grid_winner.py` over HTTP, `confirm:true` required for writes,
  path-traversal-safe rollback. (`9b6d9cd`)
- `GET /api/system/{info,db-stats,rate-limit,health/deep}` + `POST
  /api/system/{test-trace,test-error}` for observability smoke tests
  and Settings widgets. (`faee71f`, `8ffb7fc`, `d5c732f`, `30c9fbb`)

#### Added — Observability + defense
- **Logfire** OTEL platform (auto FastAPI + httpx instrumentation, custom
  scanner spans). Soft-disabled without `LOGFIRE_TOKEN`. (`67ecd77`)
- **Sentry** — error capture + slow-tx + cron heartbeat
  (`monitor_slug=bg-scanner`). Soft-disabled without `SENTRY_DSN`.
  (`9b6d9cd`, `6c292ac`)
- **Slow-request middleware** — logs WARN above `SLOW_REQUEST_MS`
  (default 500 ms). (`8ffb7fc`)
- **`dynamic_params` Pydantic-style schema** with auto-mirror
  `target_rr → tp_to_sl_ratio` (closes bug class `95569f7`), 30-min drift
  watchdog, schema-aware `set_param` / `get_param`. (`e0ccc66`, `faee71f`)
- Startup env-vars OK/missing report in `logs/api.log`. (`6c292ac`)

#### Added — ML / performance
- **Treelite-compiled XGB voter** (`tools/compile_xgb_treelite.py`) — ~12×
  speedup on N=1 single-sample inference (the actual scanner case).
  Parity max abs diff 5.96e-08 vs native. Load priority: Treelite →
  ONNX/DirectML → sklearn. (`d972d3f`)
- **DuckDB warehouse reader** (opt-in `QUANT_USE_DUCKDB=1`). Empirical
  bench: pandas wins 2.5× on single files, DuckDB wins 4× on multi-file
  SQL aggregations. 8/8 parity tests. (`e9488c8`)
- **Polars groundwork** — 16/16 features pass parity (≤3.6e-12 EWM, ≤3.3e-16
  elsewhere). `compute_features` itself stays pandas. (`6c292ac`, `faee71f`)
- **Optuna optimizer** (`scripts/run_optuna_optimization.py`) — TPE +
  median pruner, SQLite study storage, `--mock` evaluator. (`6c292ac`)
- **Modal Labs skeleton** for off-loading `train_all.py`. (`6c292ac`)

#### Added — Build
- Migrated to **`pyproject.toml` + `uv.lock`** (199 packages); back-compat
  `pip install -r requirements.txt` still works. `requires-python ≥ 3.12`.
  (`58566f8`)

#### Fixed
- Hero price + KPI digits invisible under `text-display-gradient` /
  `text-gold-gradient` (cascading `-webkit-text-fill-color: transparent`
  bled into NumberFlow). Switched numeric values to solid colors.
  (`5029fdf`)
- `TracedConnectionProxy` breaks `Connection.backup()` — disabled
  Logfire's sqlite3 instrumentation. (`67ecd77`)
- uv `prerelease=allow` (global) picked dev wheels for unrelated packages;
  switched to `if-necessary`. (`e9488c8`)

#### Tests
40 unit tests across three suites:
- `tests/test_dynamic_params_schema.py` — 19 (mirror, drift, edge cases).
- `tests/test_grid_endpoints.py` — 13 (TestClient, path traversal,
  confirm-required, 404 handling).
- `tests/test_warehouse_duckdb_parity.py` — 8 (pandas vs DuckDB parity).

#### Tooling
- `tools/bench_warehouse_reader.py`, `tools/compile_xgb_treelite.py`,
  `tools/polars_features_parity.py`, `tools/modal_train.py`,
  `scripts/run_optuna_optimization.py`.

---

### 2026-04-13 — Autonomous overnight retrain session

**Net production change**: LSTM voter resurrected. Other voters unchanged.

#### Added
- `tune_lstm.py` — Optuna sweep for LSTM with 14-dim search space including
  target redesign axis (`target_type`, `target_horizon`, `target_atr_mult`).
  Two-gate winner selection: `balanced_acc >= 0.52 AND live_stdev >= 0.03`.
- `retrain_deeptrans_loop.py` — strict-gated retrain loop for the deep
  transformer voter (3-class softmax, balanced_accuracy + live_stdev gates).
- Backup safety net: `models/_backup_<TS>/` dir + git tag
  `pre-autonomous-overnight-<TS>` snapshotting all artefacts + DB params
  before any production-touching change.

#### Changed
- `models/lstm.{keras,onnx,scaler.pkl}` **promoted from sweep winner**
  (trial #38: balanced_acc 0.547, live_stdev 0.0336 → 0.4593 post-retrain
  on train+val merge). `ensemble_weight_lstm` restored 0.0 → 0.15
  (conservative; previous self-learned 0.25 was on the flat-output era model).
- `run_production_backtest.py::_reset_backtest_db` — now truncates
  `trades / scanner_signals / ml_predictions` tables instead of unlinking
  the SQLite file. The unlink path raised `WinError 32 'used by another
  process'` while the module-level `src.core.database._conn` held the file
  open, AND closing that conn broke any `NewsDB` instances that had
  cached `self.conn`. Truncate is locally race-free.

#### Tried but not promoted (see `logs/autonomous_morning_report.md`)
- DQN sweep (8 of 60 trials, early-stopped). Trial 8 won val at +14.99%
  but `--apply-winner`'s held-out test reproduced only +0.06%; eval_compare
  vs production confirmed mode collapse (1 trade vs prod's 547).
  Production DQN retained (live attribution showed it as 82%-accuracy
  voter — still the best of the basket).
- DeepTrans retrain (4 iterations). All flat on live (stdev 0.005-0.011),
  best val_bal 0.391 < 0.42 floor. Voter stays disabled
  (`QUANT_ENABLE_TRANSFORMER` unset).

#### Known limitations (acknowledged, not fixed this session)
- `ml_predictions.trade_id` remains historically NULL on most rows. The
  scanner.py:921 UPDATE that links predictions to trades runs inside a
  silent `try/except: pass` and has been failing silently long before
  this session. Worked around by `/api/models/voter-attribution`'s
  timestamp-join. Fix would touch hot live code path — deferred.

### Added — Backtest infrastructure (P0-P8)
- **Production backtest harness** (`run_production_backtest.py`): walk-forward
  through historical data using the REAL scanner pipeline (SMC + ML ensemble +
  risk manager). 3-layer isolation from production DB (`data/backtest.db`,
  env var enforcement, paranoid runtime guards).
- **Historical data provider** (`src/backtest/historical_provider.py`): yfinance
  replay with proper time-slicing, disk cache (6h TTL), SMC cache invalidation
  on each tick.
- **Execution realism** (P6): commission, vol-scaled slippage, overnight swap
  cost, gap detection with worse-fill penalty.
- **Position management**: next-bar-open entry (no look-ahead), trailing stops
  (1R→BE, 1.5R→lock, 2R→trail), optional partial close at 1R (`--partial-close`),
  BREAKEVEN status for trail-to-entry exits.
- **Advanced analytics** (`src/backtest/analytics.py`): Sharpe/Sortino/Calmar,
  expectancy, rolling WR/PF, drawdown recovery time, time-of-day/DOW heatmap,
  P&L skewness/kurtosis.
- **Statistical methodology**: walk-forward windows (`--walk-forward N`),
  Monte Carlo bootstrap (`--monte-carlo N`), buy-and-hold benchmark with
  `alpha_vs_bh_pct`.
- **Tooling**: `--strict` for production-parity thresholds, `--compare`
  side-by-side diff, `--seed` for determinism, `--export-csv`, `--plot-equity`,
  `--resume` checkpoint recovery, `--analytics` full report.
- **Parameter sweep** (`run_backtest_grid.py`): systematic grid over
  min_confidence × sl_atr_mult × target_rr, ranked by Sharpe.
- **Frontend dashboard**: `BacktestResults` component on ModelsPage reads
  `/api/backtest/runs` + `/api/backtest/latest` + `/api/backtest/chart` +
  `/api/backtest/run?name=X` endpoints. Shows metrics card, equity curve PNG,
  Monte Carlo p5/p50/p95 distribution, rejection histogram, compare dialog.
- **Documentation**: `docs/BACKTEST.md` full CLI + metrics interpretation reference.
- **Tests**: 38 new tests (isolation, historical provider, e2e analytics).

### Added — RL training overhaul
- **Prioritized Experience Replay** (SumTree) with bootstrap stratification.
- **Multi-asset training** with `vol_normalize=True` fixing critical
  `balance += pnl × entry_price` bug (forex was invisible, BTC dominated).
- **Validation early stopping** (`VAL_PATIENCE=30`) + best-weight restoration.
- **Noise augmentation** (NOISE_STD=0.001) + checkpoint resume with data hash.
- **Training registry** (`src/ml/training_registry.py`): append-only JSONL
  log with git commit, hyperparams, per-symbol metrics.
- **Eval tooling**: `eval_rl.py` with model comparison, `regenerate_rl_onnx.py`
  standalone helper.
- **New model**: retrained 4-asset basket (GC/EURUSD/ES/CL) with vol_normalize
  → **+14pp OOS improvement** over pre-session gold baseline.

### Added — Observability (Phase 1)
- Scanner health metrics: `scan_duration` histogram, `scan_errors_total`,
  `scan_last_ts`, `data_fetch_failures`, `signals_long/short/wait`.
- Ensemble instrumentation: `ensemble_confidence` histogram + signal counters.
- `/api/health/scanner` endpoint with `healthy/stale/degraded/no_data` status.
- `/api/health/models` endpoint with staleness detection (14-day threshold).
- `/api/training/history` endpoint + `TrainingHistory` frontend widget.
- Database indexes: `idx_ml_pred_timestamp` (COVERING, 4.7k-row table),
  `idx_ml_pred_trade_id`, `idx_rejected_filter`.
- `verify_install.py` post-deploy smoke check (8 automated checks).

### Added — Defense (Phase 2)
- **Event guard**: `@requires_clear_calendar` decorator blocks trades 15 min
  before high-impact USD events (NFP/CPI/Fed).
- **Volatility targeting**: position size scales inversely with ATR
  (baseline/current ratio, clamped [0.4, 1.8]).
- **Volatility-aware slippage**: spread scales with current ATR × session.

### Added — Iteration tools (Phase 3)
- Training registry JSONL (`models/training_history.jsonl`).
- Backtest harness with pluggable strategies (SMA/RSI/ensemble).
- Per-model track record (`model_*_correct/incorrect` counters).
- Ensemble confidence tracking in metrics.

### Added — Code quality (Phase 4)
- Type hints pass on config.py, compute.py, new files.
- ESLint 8 → 9 migration with flat config (`eslint.config.js`).
- Tests: `test_rl_agent.py` (17), `test_event_guard.py` (8),
  `test_backtest_isolation.py` (16), `test_historical_provider.py` (10),
  `test_backtest_e2e.py` (13), `test_backtest_harness.py` (9).

### Changed
- **Scanner cadence 15min → 5min** (4× more trade opportunities, credit
  budget 1.6/min avg of 55/min limit).
- **`@vitejs/plugin-react` 4 → 6**, **`lucide-react` 0.383 → 1.8**,
  **`eslint` 8 → 9**, **`TypeScript` 5.3 → 5.9**, **`tailwindcss` 3 → 4**
  (flat config, `@theme` in CSS, Lightning CSS autoprefix).
- **DQN ensemble weight** 0.20 → 0.12 (conservative default, let
  self-learning adjust based on live track record).
- **Event guard integration** centralized via decorator.

### Fixed
- **Critical**: backtest trades were never resolved — `db.log_trade()` used
  wall-clock `datetime.now()` instead of simulated time.
- **Critical**: SMC cache (60s TTL) not invalidated between backtest ticks,
  making all cycles return identical analysis.
- **Critical**: `TradingEnv.balance += pnl * entry_price` broke multi-asset
  training (BTC at $60k dominated forex at $1.05). Fixed via `vol_normalize`.
- **Critical**: in production, `QUANT_BACKTEST_RELAX` shell-env leak could
  activate relaxed filters. Fixed via double-gate (`MODE + RELAX` both
  required) + production entry points explicitly clearing flags.
- `self_learning.py:113` undefined `stats` (should be `tw_stats`).
- `self_learning.py` session comparison: used capitalized strings against
  DB's lowercase `db.get_session()` output. Now uses same helper.
- `add_wavelet_features`: "buffer source array is read-only" via
  `df['close'].to_numpy(copy=True)`.
- `UnicodeEncodeError` in `DQNAgent.load()` on Windows cp1252 console.
- `calculate_position(td_api_key)` unused parameter marked deprecated,
  defaulted to empty string.
- Implicit Optional in `compute.py` ONNX conversion helpers.
- `macro_data.Myfxbook` login spam downgraded to debug in backtest mode.
- `vite-plugin-pwa` peer-dep workaround via `package.json overrides`
  (removed `.npmrc legacy-peer-deps` hack).

### Removed
- `frontend/.npmrc` (replaced by `package.json overrides`).
- `frontend/postcss.config.js`, `frontend/tailwind.config.js`
  (Tailwind 4 uses CSS `@theme`).
- `frontend/.eslintrc.json`, `frontend/.eslintignore` (ESLint 9 flat config).
- `autoprefixer` dependency (Lightning CSS built-in).

### Security
- Production hardening: `api/main.py` and `src/main.py` explicitly clear
  `QUANT_BACKTEST_MODE` + `QUANT_BACKTEST_RELAX` env vars at startup with
  warning if present.
- Backtest isolation: `BacktestIsolationError` raised if `DATABASE_URL`
  resolves to `data/sentinel.db` at enforce time.

---

## Pre-changelog history

See commits before 2026-04-11 in git log. Major milestones:
- React 18 → 19 upgrade (commit 6f48a30)
- WebSocket → Server-Sent Events migration (commit e409940)
- Flask → FastAPI migration (commit 0d5b910)
- Dark/light theme toggle
- PWA + offline support
- 3-phase frontend roadmap complete (Layout, Mobile, Model Health)
