#!/usr/bin/env bash
# scripts/run_aggressive_backtest.sh — combined-stack 3yr backtest.
#
# 2026-05-06: aggressive path test. Runs all Phase A + B + C wired
# strategies + sizing layers on the 3yr warehouse. Goal: validate that
# the full stack produces ≥+20% / ≤10% DD before committing to live
# without forward observation.
#
# If results pass: enable env flags, run live with full stack.
# If results fail: fall back to compressed (sequential rollout).
#
# IMPORTANT: must run AFTER walk-forward v2 finishes (uses backtest.db).
#
# Usage:
#   bash scripts/run_aggressive_backtest.sh

set -euo pipefail
cd "$(dirname "$0")/.."

# Pre-flight: confirm WF v2 finished (no other backtest process)
if pgrep -f "run_production_backtest" > /dev/null 2>&1; then
    if ! grep -q "WALK-FORWARD AGGREGATE" logs/wf_2026-05-06.log 2>/dev/null; then
        echo "ERROR: walk-forward still running. Wait for it to finish first." >&2
        echo "Tail: $(tail -1 logs/wf_2026-05-06.log)" >&2
        exit 1
    fi
fi

ts=$(date +%Y%m%d_%H%M%S)
echo "[aggr] $ts — starting aggressive 3yr backtest with FULL STACK"

# Backup before wipe
cp data/backtest.db "data/backups/backtest_pre_aggr_${ts}.db" 2>/dev/null || true

# Activate ALL phase env flags for this backtest
# Phase A alphas auto-fire (no flag).
# Phase B sizing (3 toggles)
# Phase 1 meta-labeler sizing
# Phase 2 partial-1R
# Phase C strategies live
# OOD gate OFF for full-history fairness (was fit on recent ~5k prices)
# Meta-label gate kept ON (already validated veto-only)

QUANT_VOL_TARGETING=1 \
QUANT_DD_SIZING=1 \
QUANT_EQUITY_CURVE_FILTER=1 \
QUANT_META_LABEL_SIZING=1 \
QUANT_PARTIAL_1R=1 \
QUANT_MEAN_REV_LIVE=1 \
QUANT_VOL_BREAKOUT_LIVE=1 \
QUANT_OOD_GATE=0 \
QUANT_META_LABEL_GATE=1 \
.venv/Scripts/python.exe -X utf8 run_production_backtest.py \
    --warehouse \
    --start 2023-05-01 \
    --end 2026-04-27 \
    --step-minutes 15 \
    --reset \
    --output reports/2026-05-06_aggressive_3yr.json \
    --analytics \
    2>&1 | tee logs/aggressive_backtest_2026-05-06.log

echo ""
echo "[aggr] Done. Results:"
echo "  reports/2026-05-06_aggressive_3yr.json"
echo "  logs/aggressive_backtest_2026-05-06.log"

# Auto-compare vs baseline
echo ""
echo "[aggr] Comparison vs 3yr post-audit (Phase A only):"
.venv/Scripts/python.exe -X utf8 scripts/compare_backtests.py \
    reports/2026-05-05_post_audit_3yr.json \
    reports/2026-05-06_aggressive_3yr.json \
    2>&1 | head -40
