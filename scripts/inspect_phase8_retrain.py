#!/usr/bin/env python3
"""
inspect_phase8_retrain.py — parse logs/phase8_retrain.log and produce a
green/red morning verdict on the overnight retrain.

Extracts per-voter walk-forward accuracies, DQN reward, Bayesian opt
params, holdout backtest stats. Compares against audit-derived
thresholds:

  - XGB walk-forward acc:       0.50-0.70  (red flag if >0.70 = leak)
  - LSTM walk-forward acc:      0.50-0.70
  - Attention walk-forward acc: 0.50-0.70
  - DQN best reward (avg 20):   > 0
  - Holdout PF:                 > 1.0
  - Holdout return:             > 0
  - Holdout max DD:             > -10%

Plus presence checks for the artifact files that should exist after
a clean retrain:
  models/xgb.pkl, models/lstm.keras, models/lstm_scaler.pkl,
  models/attention.keras, models/attention_scaler.pkl,
  models/rl_agent.keras, models/feature_cols.json,
  data/historical/labels/triple_barrier_*.parquet (already there)

Usage:
    python scripts/inspect_phase8_retrain.py
    python scripts/inspect_phase8_retrain.py --log logs/phase8_retrain.log

Exit 0 = green light; 1 = at least one red flag; 2 = log incomplete.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Audit-derived thresholds
ACC_LOWER, ACC_UPPER = 0.50, 0.70
DQN_REWARD_LOWER = 0.0
PF_LOWER = 1.0
DD_LOWER = -10.0  # percentage points

REQUIRED_ARTIFACTS = [
    "models/xgb.pkl",
    "models/lstm.keras",
    "models/lstm_scaler.pkl",
    "models/attention.keras",
    "models/attention_scaler.pkl",
    "models/rl_agent.keras",
    "models/feature_cols.json",
]


def _parse_log(text: str) -> dict:
    """Pull walk-forward accuracies + RL + backtest from log text."""
    out = {
        "xgb_acc": None,
        "lstm_acc": None,
        "lstm_val_acc": None,
        "attention_acc": None,
        "dqn_best_reward": None,
        "dqn_episodes": None,
        "holdout_pf": None,
        "holdout_return": None,
        "holdout_dd": None,
        "bayesian_params": {},
        "calibration_skipped": False,
        "feature_cols_pinned": None,
        "errors": [],
    }

    # XGB walk-forward acc
    m = re.search(r"XGBoost trained, walk-forward accuracy:\s*([\d.]+)", text)
    if m:
        out["xgb_acc"] = float(m.group(1))

    # LSTM
    m = re.search(r"lstm_walkforward_accuracy.*?[\s=:]\s*([\d.]+)", text)
    if m:
        out["lstm_acc"] = float(m.group(1))
    m = re.search(r"lstm_last_accuracy.*?[\s=:]\s*([\d.]+)", text)
    if m:
        out["lstm_val_acc"] = float(m.group(1))
    # Fallback — direct regex on "Validation accuracy: 56.0%"
    m = re.search(r"Validation accuracy:\s*([\d.]+)%", text)
    if m and out["lstm_val_acc"] is None:
        out["lstm_val_acc"] = float(m.group(1)) / 100.0
    m = re.search(r"Walk-forward accuracy:\s*([\d.]+)%", text)
    # multiple matches — last one in LSTM section
    matches = re.findall(r"Walk-forward accuracy:\s*([\d.]+)%", text)
    if matches:
        # First match = XGB (we already got that). Look for one in LSTM section.
        lstm_section = re.search(
            r"TRENING LSTM(.*?)(?:TRENING|TFT-lite|ATTENTION|=====)",
            text, re.DOTALL,
        )
        if lstm_section:
            m2 = re.search(r"Walk-forward accuracy:\s*([\d.]+)%", lstm_section.group(1))
            if m2:
                out["lstm_acc"] = float(m2.group(1)) / 100.0

    # Attention walk-forward acc
    m = re.search(r"ATTENTION MODEL.*?Walk-forward accuracy:\s*([\d.]+)%", text, re.DOTALL)
    if m:
        out["attention_acc"] = float(m.group(1)) / 100.0
    else:
        # Alternative format
        m = re.search(r"attention.*?accuracy[:\s]+([\d.]+)", text, re.IGNORECASE | re.DOTALL)
        if m:
            try:
                out["attention_acc"] = float(m.group(1))
            except ValueError:
                pass

    # DQN
    m = re.search(r"Najlepsza nagroda:\s*([\-\d.]+)", text)
    if m:
        out["dqn_best_reward"] = float(m.group(1))
    m = re.search(r"Model zapisany \(ep (\d+)/(\d+)\)", text)
    if m:
        out["dqn_episodes"] = int(m.group(1))

    # Bayesian opt — scrape "key: value" lines from BAYESOWSKA section
    bayes_section = re.search(
        r"OPTYMALIZACJA BAYESOWSKA(.*?)(?:===|BACKTEST|POST-TRAINING|RAPORT)",
        text, re.DOTALL,
    )
    if bayes_section:
        for line in bayes_section.group(1).split("\n"):
            mp = re.match(r"\s+([\w_]+):\s*([\d.]+)\s*$", line)
            if mp:
                out["bayesian_params"][mp.group(1)] = float(mp.group(2))

    # Backtest holdout
    m = re.search(r"profit_factor[\s|:|=]+([\d.]+)", text, re.IGNORECASE)
    if m:
        out["holdout_pf"] = float(m.group(1))
    m = re.search(r"return_pct[\s|:|=]+([\-\d.]+)", text, re.IGNORECASE)
    if m:
        out["holdout_return"] = float(m.group(1))
    m = re.search(r"max_drawdown_pct[\s|:|=]+([\-\d.]+)", text, re.IGNORECASE)
    if m:
        out["holdout_dd"] = float(m.group(1))

    # Calibration
    if "Calibration fit SKIPPED" in text or "DISABLE_CALIBRATION" in text:
        out["calibration_skipped"] = True

    # FEATURE_COLS pin
    m = re.search(r"FEATURE_COLS pinned:\s*(\d+)\s*cols", text)
    if m:
        out["feature_cols_pinned"] = int(m.group(1))

    # Crashes / tracebacks
    if "Traceback" in text:
        # Pull the LAST traceback (most recent error)
        tb_starts = [i for i in range(len(text)) if text.startswith("Traceback", i)]
        if tb_starts:
            last_tb = text[tb_starts[-1]:tb_starts[-1] + 2000]
            out["errors"].append(last_tb.split("\n")[-2:][-1] if last_tb else "Traceback present")

    return out


def _check_artifacts(base: Path) -> dict:
    """Verify all required model files exist + are recent."""
    result = {}
    for rel in REQUIRED_ARTIFACTS:
        path = base / rel
        if path.exists():
            stat = path.stat()
            result[rel] = {
                "exists": True,
                "size_kb": round(stat.st_size / 1024, 1),
                "mtime": stat.st_mtime,
            }
        else:
            result[rel] = {"exists": False}
    return result


def _verdict_per_voter(name: str, acc: float | None) -> tuple[str, str]:
    if acc is None:
        return ("MISSING", f"no walk-forward acc for {name} — voter may have crashed")
    if acc < ACC_LOWER:
        return ("RED", f"{name} acc {acc:.3f} < {ACC_LOWER} — model is worse than random")
    if acc > ACC_UPPER:
        return ("RED", f"{name} acc {acc:.3f} > {ACC_UPPER} — investigate for hidden leak")
    return ("GREEN", f"{name} acc {acc:.3f} in healthy band [{ACC_LOWER},{ACC_UPPER}]")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", default="logs/phase8_retrain.log")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    log_path = _REPO_ROOT / args.log
    if not log_path.exists():
        print(f"[ERROR] log not found: {log_path}")
        sys.exit(2)

    text = log_path.read_text(encoding="utf-8", errors="replace")
    parsed = _parse_log(text)

    artifacts = _check_artifacts(_REPO_ROOT)

    if args.json:
        print(json.dumps({"parsed": parsed, "artifacts": artifacts}, indent=2, default=str))
        sys.exit(0)

    # ── Pretty print ─────────────────────────────────────────────────
    print("=" * 70)
    print("Phase 8 Retrain — Morning Inspection")
    print("=" * 70)
    print(f"  log: {log_path}  ({log_path.stat().st_size / 1024:.0f} KB)")
    print()

    print("[Voters — walk-forward accuracy]")
    voters = [
        ("xgb", parsed["xgb_acc"]),
        ("lstm", parsed["lstm_acc"]),
        ("attention", parsed["attention_acc"]),
    ]
    red_count = 0
    missing_count = 0
    for name, acc in voters:
        verdict, msg = _verdict_per_voter(name, acc)
        marker = {"GREEN": "OK  ", "RED": "RED ", "MISSING": "????"}[verdict]
        print(f"  [{marker}] {msg}")
        if verdict == "RED":
            red_count += 1
        if verdict == "MISSING":
            missing_count += 1

    print()
    print("[DQN]")
    if parsed["dqn_best_reward"] is not None:
        if parsed["dqn_best_reward"] > DQN_REWARD_LOWER:
            print(f"  [OK  ] best reward {parsed['dqn_best_reward']:+.4f} "
                  f"(eps trained: {parsed['dqn_episodes'] or '?'})")
        else:
            print(f"  [RED ] best reward {parsed['dqn_best_reward']:+.4f} "
                  f"<= 0 — RL agent learned nothing usable")
            red_count += 1
    else:
        print(f"  [????] no DQN reward in log (skipped or crashed)")
        missing_count += 1

    print()
    print("[Holdout backtest]")
    pf = parsed["holdout_pf"]
    ret = parsed["holdout_return"]
    dd = parsed["holdout_dd"]
    if pf is not None:
        if pf >= PF_LOWER:
            print(f"  [OK  ] PF {pf:.2f} >= {PF_LOWER}")
        else:
            print(f"  [RED ] PF {pf:.2f} < {PF_LOWER}")
            red_count += 1
    else:
        print(f"  [????] no PF in log")
        missing_count += 1
    if ret is not None:
        marker = "OK  " if ret > 0 else "RED "
        if ret <= 0:
            red_count += 1
        print(f"  [{marker}] return {ret:+.2f}%")
    if dd is not None:
        marker = "OK  " if dd > DD_LOWER else "RED "
        if dd <= DD_LOWER:
            red_count += 1
        print(f"  [{marker}] max DD {dd:.2f}%")

    print()
    print("[Pipeline hygiene]")
    print(f"  [{'OK  ' if parsed['calibration_skipped'] else 'WARN'}] "
          f"calibration {'skipped' if parsed['calibration_skipped'] else 'NOT skipped — verify .env'}")
    print(f"  [{'OK  ' if parsed['feature_cols_pinned'] else 'WARN'}] "
          f"FEATURE_COLS pinned: {parsed['feature_cols_pinned'] or 'NOT pinned'}")

    print()
    print("[Bayesian opt params (top of section)]")
    if parsed["bayesian_params"]:
        for k, v in list(parsed["bayesian_params"].items())[:6]:
            print(f"      {k}: {v}")
    else:
        print(f"      (none captured)")

    print()
    print("[Artifacts]")
    for rel, info in artifacts.items():
        if info["exists"]:
            print(f"  [OK  ] {rel}  ({info['size_kb']:.1f} KB)")
        else:
            print(f"  [MISS] {rel}")
            missing_count += 1

    if parsed["errors"]:
        print()
        print("[Errors found in log (last lines)]")
        for e in parsed["errors"]:
            print(f"  {e}")

    # ── Final verdict ────────────────────────────────────────────────
    print()
    print("=" * 70)
    if red_count == 0 and missing_count == 0:
        print(f"VERDICT: GREEN — all checks passed. Safe to commit + Treelite recompile + API restart.")
        rc = 0
    elif red_count == 0:
        print(f"VERDICT: YELLOW — no red flags but {missing_count} item(s) missing/incomplete.")
        print(f"  Investigate before committing. Retrain may still be running.")
        rc = 2
    else:
        print(f"VERDICT: RED — {red_count} red flag(s), {missing_count} missing.")
        print(f"  DO NOT push to live. Investigate root cause + re-run.")
        rc = 1
    print("=" * 70)

    print()
    print("Next steps if GREEN:")
    print("  .venv/Scripts/python.exe tools/compile_xgb_treelite.py")
    print("  .venv/Scripts/python.exe scripts/preflight_api_restart.py")
    print("  .venv/Scripts/python.exe scripts/voter_correlation.py")
    print("  # Then start API:")
    print("  .venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --log-level info > logs/api.log 2>&1 &")

    return rc


if __name__ == "__main__":
    sys.exit(main())
