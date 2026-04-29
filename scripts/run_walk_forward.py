#!/usr/bin/env python3
"""
run_walk_forward.py — Convenience wrapper to run walk-forward backtest.

Two modes:
  --static (default): each window uses the CURRENT live models. Tests
    edge stability across regimes WITHOUT retraining — fast, but the
    audit (P1.12, 2026-04-29) flagged this as "regime-stability test
    of a static model, not real walk-forward."
  --retrain: each window first re-trains XGB on the train slice, then
    runs the test backtest against those fresh weights. Honest
    walk-forward. ~5x slower per window.

Usage:
    python scripts/run_walk_forward.py
    python scripts/run_walk_forward.py --quick                # static, 30/7/14
    python scripts/run_walk_forward.py --quick --retrain      # honest WF
    python scripts/run_walk_forward.py --start 2024-01-01 --end 2026-04-01 \\
        --train 90 --test 7 --step 7 --retrain
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure repo root on path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.backtest.walk_forward import walk_forward, print_summary


def _xgb_only_train_runner(train_s, train_e):
    """Per-window retrainer — XGB only (LSTM/Attention would multiply
    runtime by 30x+). Reads warehouse 1h for the train slice, computes
    features, fits a fresh XGB on triple-barrier target, saves to
    `models/xgb.pkl` so the test backtest's _load_xgb picks it up.

    Triple-barrier target (TP-hit binary on label_long) is used by
    default since binary `compute_target` was flagged tautological.
    Override via env QUANT_WF_TARGET=binary if needed.

    LSTM and Attention NOT retrained — their saved weights from the
    most recent full train_all run are used. Documented limitation.
    """
    import os
    import pandas as pd
    from src.core.logger import logger
    from src.analysis.compute import compute_features

    logger.info(f"[WF-retrain] training XGB on [{train_s} .. {train_e}]")

    xau_path = _REPO_ROOT / "data" / "historical" / "XAU_USD" / "1h.parquet"
    df = pd.read_parquet(xau_path)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    train_s_ts = pd.Timestamp(train_s, tz="UTC") if not isinstance(train_s, pd.Timestamp) else train_s
    train_e_ts = pd.Timestamp(train_e, tz="UTC") if not isinstance(train_e, pd.Timestamp) else train_e
    mask = (df["datetime"] >= train_s_ts) & (df["datetime"] < train_e_ts)
    slice_df = df[mask].reset_index(drop=True)
    if len(slice_df) < 200:
        logger.warning(f"[WF-retrain] too few train bars ({len(slice_df)}) — skipping retrain")
        return

    # USDJPY for macro features
    usdjpy_path = _REPO_ROOT / "data" / "historical" / "USD_JPY" / "1h.parquet"
    usdjpy_df = None
    if usdjpy_path.exists():
        usdjpy_df = pd.read_parquet(usdjpy_path)
        usdjpy_df["datetime"] = pd.to_datetime(usdjpy_df["datetime"], utc=True)

    features = compute_features(slice_df, usdjpy_df=usdjpy_df)
    if len(features) < 100:
        logger.warning(f"[WF-retrain] too few feature rows ({len(features)}) — skipping")
        return

    # Default to triple-barrier target if labels parquet exists
    target_kind = os.environ.get("QUANT_WF_TARGET", "triple_barrier")
    precomputed_target = None
    if target_kind == "triple_barrier":
        labels_dir = _REPO_ROOT / "data" / "historical" / "labels"
        candidates = sorted(labels_dir.glob("triple_barrier_XAU_USD_1h_*.parquet"))
        if candidates:
            labels = pd.read_parquet(max(candidates, key=lambda p: p.stat().st_mtime))
            merged = slice_df.merge(labels[["datetime", "label_long"]], on="datetime", how="left")
            precomputed_target = (merged["label_long"] == 1).astype(int)
            # Auto-set purge from filename
            import re as _re
            m = _re.search(r"_max(\d+)", max(candidates).name)
            if m and "WF_PURGE_BARS" not in os.environ:
                os.environ["WF_PURGE_BARS"] = m.group(1)

    from src.ml.ml_models import ml as _ml
    acc = _ml.train_xgb(slice_df, precomputed_features=features,
                        precomputed_target=precomputed_target)
    logger.info(f"[WF-retrain] XGB walk-forward acc on this train window: {acc}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-04-01")
    ap.add_argument("--train", type=int, default=90, help="train window days")
    ap.add_argument("--test", type=int, default=7, help="test window days")
    ap.add_argument("--step", type=int, default=7, help="step between windows")
    ap.add_argument("--quick", action="store_true",
                    help="quick mode: 30/7/14 (smaller windows + bigger steps)")
    ap.add_argument("--retrain", action="store_true",
                    help="honest WF — retrain XGB per window (P1.12). "
                         "~5x slower but actually walk-forward. Default: static.")
    ap.add_argument("--out", default="docs/walk_forward_results.json")
    args = ap.parse_args()

    if args.quick:
        args.train = 30
        args.test = 7
        args.step = 14

    print(f"Starting walk-forward: train={args.train}d, test={args.test}d, step={args.step}d")
    print(f"Period: {args.start} -> {args.end}")
    print(f"Mode: {'RETRAIN per window (honest WF)' if args.retrain else 'STATIC live models (regime stability test)'}")
    print(f"Output: {args.out}")
    print()

    train_runner = _xgb_only_train_runner if args.retrain else None

    results = walk_forward(
        start_date=args.start, end_date=args.end,
        train_days=args.train, test_days=args.test, step_days=args.step,
        train_runner=train_runner,
    )
    print_summary(results)
    results.save(args.out)
    print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
