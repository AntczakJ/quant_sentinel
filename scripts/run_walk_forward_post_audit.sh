#!/usr/bin/env bash
# 2026-05-05: walk-forward validation, fires after the 3yr backtest finishes.
#
# Strategy: 4 chronological folds across the same 3yr warehouse window.
# Compare per-fold WR/PF/Return. Recent-fold drop > 5pp = regime alarm.
# Pairs with reports/2026-05-05_post_audit_3yr.json (single-window run).
#
# Pre-flight:
#   - Confirm 3yr backtest finished: reports/2026-05-05_post_audit_3yr.json exists
#   - Confirm no other backtest process running: ps -ef | grep run_production_backtest
#   - Backup data/backtest.db (3yr DB) so we don't lose it:
#       cp data/backtest.db data/backups/backtest_3yr_2026-05-05.db
#
# Run:
#   bash scripts/run_walk_forward_post_audit.sh
#
# Cost: ~25h wall-clock (4 windows × ~6.25h each). Same trade-quality
# defenses active (London block, A demote, SHORT-bull floor, finance.py
# fix). Aggregated metrics in reports/2026-05-05_post_audit_wf4.json.

set -euo pipefail

cd "$(dirname "$0")/.."

# Confirm prerequisites
if [ ! -f "reports/2026-05-05_post_audit_3yr.json" ]; then
    echo "ERROR: 3yr backtest results missing — run that first" >&2
    exit 1
fi

# Backup current backtest.db before --reset wipes it
ts=$(date +%Y%m%d_%H%M%S)
cp data/backtest.db "data/backups/backtest_3yr_pre_wf_${ts}.db"
echo "[wf] Backed up backtest.db → data/backups/backtest_3yr_pre_wf_${ts}.db"

# Run 4-fold walk-forward across same period
# 2026-05-06: use --days 1090 (3yr) — `--walk-forward N` overrides
# --start/--end with today()-offset windows. -X utf8 forces UTF-8
# stdout so Unicode arrows in aggregate print don't crash on cp1252.
.venv/Scripts/python.exe -X utf8 run_production_backtest.py \
    --warehouse \
    --days 1080 \
    --end 2026-04-27 \
    --step-minutes 15 \
    --reset \
    --walk-forward 4 \
    --output reports/2026-05-05_post_audit_wf4.json \
    2>&1 | tee logs/wf_2026-05-05_post_audit.log

# Post-hoc validator on the resulting DB
.venv/Scripts/python.exe scripts/walk_forward_validator.py \
    --db backtest --folds 4 \
    2>&1 | tee logs/wf_validator_2026-05-05.log

# A/B compare the two runs
.venv/Scripts/python.exe run_production_backtest.py --compare \
    reports/2026-05-05_post_audit_3yr.json \
    reports/2026-05-05_post_audit_wf4.json \
    2>&1 | tee logs/wf_compare_2026-05-05.log

echo "[wf] Done. Reports:"
echo "  reports/2026-05-05_post_audit_wf4.json"
echo "  logs/wf_2026-05-05_post_audit.log"
echo "  logs/wf_validator_2026-05-05.log"
echo "  logs/wf_compare_2026-05-05.log"
