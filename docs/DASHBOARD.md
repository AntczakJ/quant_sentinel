# Dashboard Guide

Quick tour of the Quant Sentinel web dashboard. Open with
`npm run dev` in `frontend/` and navigate to the **Models** page
for the observability stack built up during the 2026-04-16 audit.

## Pages

### Models page — the main control tower
Top-to-bottom widgets (LAYOUT_VERSION=6):

1. **System Health Summary** — 8-card at-a-glance
   - LSTM verdict, drift alerts, open/heat, scanner freshness
   - PnL 24h / 7d, scanner last-signal age, issue count
   - Open positions detail table underneath
   - Data: `/api/system-health`. Auto-refresh 20s.

2. **Voter Live Accuracy** — per-voter forward-move accuracy
   - Bull/bear/combined accuracy per voter (SMC, LSTM, XGB, Attention, DQN, Ensemble)
   - Horizon selector: 15m / 30m / 1h / 2h / 4h
   - Color-coded status: good (≥55%), weak (≥45%), anti-signal (<45%)
   - Data: `/api/voter-live-accuracy` (cached 10min server-side)

3. **Daily Digest** — markdown summary (matches Telegram digest)
   - PnL, win rate, balance, scanner activity, red flags
   - Horizon: 6h / 24h / 72h / 7d
   - Data: `/api/daily-digest`

4. **LSTM Prediction Distribution** — bimodality check
   - Side-by-side histograms: post-swap vs pre-swap reference
   - Verdict: healthy / concerning / degenerate
   - Metrics: conviction, extreme fraction, middle fraction
   - Data: `/api/models/lstm-distribution`

5. **Walk-Forward Grid (live)** — running grid sweep leaderboard
   - Top-5 by composite score, with Pareto flags
   - Progress bar when grid is running
   - Data: `/api/backtest/wf-grid-live?name=prod_v1`

Plus existing widgets: Model Drift Alert, Training History,
Backtest Results, Voter Attribution, Trading Performance.

## Key endpoints

| Endpoint | Purpose | Cache |
|---|---|---|
| `GET /api/system-health` | Aggregated health — all 6 widget queries in one call | none |
| `GET /api/voter-live-accuracy?hours=72&horizon_candles=12` | Per-voter forward accuracy | 10min server |
| `GET /api/daily-digest?hours=24` | Markdown digest for Telegram/dashboard | none |
| `GET /api/models/lstm-distribution` | Bimodality histogram + verdict | none |
| `GET /api/backtest/wf-grid-live?name=NAME&stage=A` | Live grid leaderboard | none |

## Automations

### Daily morning digest (08:00 local)
```powershell
# Run ONCE as Administrator
.\scripts\install_daily_digest_task.ps1
```
Schedules `scripts/daily_digest.py` to send Telegram summary every
morning. Uses existing TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID from
`.env`.

### Voter accuracy watchdog (every 6h)
```powershell
# Run ONCE as Administrator
.\scripts\install_voter_watchdog_task.ps1
```
Schedules `scripts/voter_watchdog.py` to check every voter's
directional accuracy. Auto-mutes any voter that hits anti_signal
status. Sends Telegram alert on auto-mute.

## Offline tools

### Replay analyzer — what-if on rejected setups
```bash
python scripts/replay_analyzer.py --hours 24
```
Classifies rejected setups by filter, computes hypothetical WR
if we'd taken them. Says "SHOULD ACCEPT" if the filter is blocking
profitable trades, "CORRECT REJECT" otherwise. No live risk.

### Apply grid winner — promote backtest config
```bash
python scripts/apply_grid_winner.py --grid prod_v1 --dry-run  # preview
python scripts/apply_grid_winner.py --grid prod_v1 --yes      # apply
python scripts/apply_grid_winner.py --rollback PATH           # undo
```
Safe param-promotion with automatic JSON backup to
`data/param_backups/`.

## Layout management

Layouts live in `localStorage` under `qs:grid-layout:*`. Bump
`LAYOUT_VERSION` in `frontend/src/components/layout/DraggableGrid.tsx`
when default layouts change to force-reset cached user layouts.

Current version: **6**. History of bumps:
- v4 (2026-04-16): first scalp-first cascade widgets
- v5 (2026-04-16): added VoterAccuracy
- v6 (2026-04-16): added DailyDigest

## Monitoring thresholds

| Metric | Healthy | Warning | Critical |
|---|---|---|---|
| Portfolio heat | < 3% | 3-6% | > 6% (blocks new trades) |
| LSTM bimodality | middle > 30% | middle 15-30% | middle < 15% + extreme > 70% |
| Voter accuracy | ≥ 55% | 45-55% | < 45% |
| Drift alert PSI | < 0.25 | 0.25-1.0 | > 1.0 (auto-persist) |
| Scanner last-rejection age | < 10m | 10m-1h | > 1h (silent) |
