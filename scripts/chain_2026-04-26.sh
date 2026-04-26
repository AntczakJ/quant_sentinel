#!/bin/bash
# Chain runner for 2026-04-26 — waits for baseline.json then runs everything.
# Total wall-clock: ~4-5 hours after baseline finishes.
set +e  # don't bail mid-chain on a single backtest failure
PY=".venv/Scripts/python.exe"
RPT="reports/2026-04-26"

echo "[$(date +%H:%M)] Chain runner armed — waiting for baseline.json"
until [ -f "$RPT/baseline.json" ]; do sleep 30; done
echo "[$(date +%H:%M)] Baseline detected — starting Phase 1 sweep"

bash scripts/sweep_2026-04-26.sh > "$RPT/_chain_phase1.log" 2>&1
echo "[$(date +%H:%M)] Phase 1 sweep complete"

# Phase 2: walk-forward 3 windows on baseline (no env changes)
echo "[$(date +%H:%M)] Starting walk-forward baseline"
$PY run_production_backtest.py --days 30 --walk-forward 3 \
    --output "$RPT/wf_baseline.json" > "$RPT/wf_baseline.log" 2>&1
echo "[$(date +%H:%M)] Walk-forward baseline complete"

# Comparison report
echo "[$(date +%H:%M)] Generating comparison"
$PY scripts/compare_sweep_2026-04-26.py > "$RPT/_summary.txt" 2>&1
cat "$RPT/_summary.txt"

echo ""
echo "[$(date +%H:%M)] CHAIN COMPLETE"
