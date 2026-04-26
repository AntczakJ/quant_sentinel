#!/bin/bash
# Sweep runner for 2026-04-26 session (scoped to ~13-40 trades/run sample).
# Sequential — single data/backtest.db with --reset between runs (truncates
# trades but keeps dynamic_params, so Bayesian winner values stay constant).
#
# Methodology (overfit defense):
#   - Same 30-day window, same seed (deterministic)
#   - Single-variable changes only at this sample size
#   - Walk-forward validates winner only AFTER A/B identifies it
#   - Direction-of-effect is the signal; absolute numbers are noisy at n<50
set -e
PY=".venv/Scripts/python.exe"
RPT="reports/2026-04-26"
mkdir -p "$RPT"

run() {
    local name="$1"; shift
    local extra_env=""
    local extra_args=""
    local saw_dashdash=0
    for arg in "$@"; do
        if [ "$arg" = "--" ]; then saw_dashdash=1; continue; fi
        if [ $saw_dashdash -eq 1 ]; then
            extra_args="$extra_args $arg"
        else
            extra_env="$extra_env $arg"
        fi
    done
    echo ""
    echo "============================================================"
    echo "[$(date +%H:%M)] RUN: $name"
    echo "  env: $extra_env"
    echo "============================================================"
    env $extra_env $PY run_production_backtest.py \
        --days 30 --reset \
        --output "$RPT/${name}.json" \
        --export-csv "$RPT/${name}_trades.csv" \
        $extra_args > "$RPT/${name}.log" 2>&1
    echo "[$(date +%H:%M)] DONE: $name"
    grep -A 20 "FINAL RESULTS" "$RPT/${name}.log" | head -22 || tail -3 "$RPT/${name}.log"
}

# ── Phase 1 — single-variable A/Bs ────────────────────────────────────
run "trailing_off" "BACKTEST_DISABLE_TRAILING=1"
run "timeexit_prodparity" "BACKTEST_TIME_EXIT_SCALP_HOURS=4.0" "BACKTEST_TIME_EXIT_SWING_HOURS=48.0"
run "long_risk_half" "QUANT_RISK_LONG_MULT=0.5"

# Combo: best-case "what does prod-parity + trailing OFF look like"
run "combo_trailoff_timeexit" "BACKTEST_DISABLE_TRAILING=1" "BACKTEST_TIME_EXIT_SCALP_HOURS=4.0" "BACKTEST_TIME_EXIT_SWING_HOURS=48.0"

echo ""
echo "============================================================"
echo "PHASE 1 COMPLETE — see $RPT/"
echo "Compare: .venv/Scripts/python.exe run_production_backtest.py --compare $RPT/baseline.json $RPT/trailing_off.json"
echo "============================================================"
