#!/usr/bin/env python3
"""
smoke_train_xgb_triple_barrier.py — fast end-to-end validation of the
triple-barrier consumer path wired in Phase 5.

Loads warehouse 1h XAU + USDJPY, attaches the canonical triple-barrier
labels (label_long mapped to TP-hit binary), runs ml.train_xgb with
precomputed_target. ~15-30s on Janek's box.

Pairs with scripts/smoke_train_xgb.py (binary target). When both
produce sane numbers, Phase 6 gate is green and we can ship Path B
overnight retrain.

Usage:
    python scripts/smoke_train_xgb_triple_barrier.py
    python scripts/smoke_train_xgb_triple_barrier.py --tf 1h --bars 4500
"""
from __future__ import annotations

import argparse
import os
import sys
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Determinism + calibration kill-switch
os.environ.setdefault("PYTHONHASHSEED", "42")
os.environ.setdefault("TF_DETERMINISTIC_OPS", "1")
os.environ.setdefault("DISABLE_CALIBRATION", "1")
import random as _r
_r.seed(42)
np.random.seed(42)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bars", type=int, default=4500)
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--symbol", default="XAU_USD")
    ap.add_argument("--target-direction", choices=["long", "short"], default="long")
    args = ap.parse_args()

    print("=" * 60)
    print(f"SMOKE — XGB / triple_barrier ({args.target_direction})")
    print("=" * 60)
    print(f"  TF: {args.tf}    bars: {args.bars}    symbol: {args.symbol}")

    from train_all import fetch_training_data, fetch_usdjpy_aligned
    from src.analysis.compute import compute_features, FEATURE_COLS

    # ── 1. Load warehouse data ────────────────────────────────────────
    t0 = time.perf_counter()
    df = fetch_training_data(source="warehouse", tf=args.tf, symbol=args.symbol)
    df = df.tail(args.bars).reset_index(drop=True)
    usdjpy_df = fetch_usdjpy_aligned(df, source="warehouse", tf=args.tf)
    print(f"\n[1] warehouse XAU: {len(df)} rows, USDJPY: {len(usdjpy_df)} rows")

    # ── 2. Find latest triple-barrier parquet ─────────────────────────
    labels_dir = _REPO_ROOT / "data" / "historical" / "labels"
    glob_pat = f"triple_barrier_{args.symbol}_{args.tf}_*.parquet"
    candidates = sorted(labels_dir.glob(glob_pat))
    if not candidates:
        print(f"\n[ERROR] No triple-barrier parquet under {labels_dir}/{glob_pat}.")
        print(f"        Run: python tools/build_triple_barrier_labels.py --tf {args.tf}")
        return 1
    labels_path = max(candidates, key=lambda p: p.stat().st_mtime)
    labels_df = pd.read_parquet(labels_path)
    print(f"[2] labels: {labels_path.name} ({len(labels_df)} rows)")

    # ── 3. Compute features + join target ─────────────────────────────
    features = compute_features(df, usdjpy_df=usdjpy_df if len(usdjpy_df) else None)
    print(f"[3] compute_features: {len(features)} rows × {len(features.columns)} cols")

    label_col = f"label_{args.target_direction}"
    merged = df.merge(labels_df[["datetime", label_col]], on="datetime", how="left")
    target = (merged[label_col] == 1).astype(int)
    n_pos = int(target.sum()); n_total = len(target)
    print(f"[4] target distribution: {n_pos}/{n_total} positives "
          f"({n_pos/n_total*100:.1f}% TP rate)")

    # ── 4. Train XGB with precomputed_target ──────────────────────────
    pkl_backup = None
    if (Path("models/xgb.pkl")).exists():
        pkl_backup = Path("models/_smoke") / "xgb_backup_pre_triple_barrier.pkl"
        pkl_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy("models/xgb.pkl", pkl_backup)

    from src.ml.ml_models import ml as _ml
    t1 = time.perf_counter()
    acc = _ml.train_xgb(df.iloc[:len(features)],
                        precomputed_features=features,
                        precomputed_target=target)
    print(f"\n[5] train_xgb walk-forward acc: {acc} "
          f"(elapsed {time.perf_counter()-t1:.1f}s)")

    if pkl_backup is not None:
        shutil.copy(pkl_backup, "models/xgb.pkl")
        print(f"    Restored models/xgb.pkl from pre-test backup")

    # ── 5. Sanity ─────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("SMOKE RESULTS")
    print(f"{'=' * 60}")
    print(f"  warehouse load:           OK")
    print(f"  triple_barrier load:      OK ({labels_path.name})")
    print(f"  target join (long):       OK ({n_pos/n_total*100:.1f}% positive)")
    print(f"  XGB walk-forward acc:     {acc:.3f}")
    print(f"  total elapsed:            {time.perf_counter()-t0:.1f}s")

    if acc is None:
        print("\n  FAIL XGB training returned None — debug.")
        return 1

    # Compare against binary baseline (smoke_train_xgb produces 0.578 on
    # 4500-row 1h slice). triple_barrier target distribution is different
    # so accuracy isn't apples-to-apples, but it should be within
    # ~0.45-0.65 band — anything >0.7 is a red flag for a leak.
    if acc > 0.70:
        print(f"\n  WARN  acc={acc:.3f} > 0.70 — investigate before pushing forward.")
        return 1
    if acc < 0.45:
        print(f"\n  WARN  acc={acc:.3f} < 0.45 — model worse than random on this target.")
        return 1
    print(f"\n  OK Plumbing OK. Triple-barrier path safe to use in full retrain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
