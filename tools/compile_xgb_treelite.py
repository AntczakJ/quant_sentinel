"""
tools/compile_xgb_treelite.py — compile models/xgb.pkl into a native shared
library via Treelite + tl2cgen (MSVC toolchain on Windows).

Output: models/xgb_treelite.dll  (or .so on Linux/macOS).
Verification: parity test against the native XGBoost predictions on a
random feature batch (max abs diff must be < 1e-6).

Run: .venv/Scripts/python.exe tools/compile_xgb_treelite.py
"""
from __future__ import annotations

import pickle
import platform
import sys
import time
from pathlib import Path

import numpy as np

# tl2cgen on Windows looks for `<venv>/Library/bin` for shipped DLLs.
# Pre-create the directory so the import doesn't blow up before we even start.
import os as _os
_lib_dir = Path(_os.path.normpath(sys.prefix)) / "Library" / "bin"
_lib_dir.mkdir(parents=True, exist_ok=True)

import treelite  # noqa: E402
import tl2cgen   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
XGB_PKL = ROOT / "models" / "xgb.pkl"


def main() -> int:
    if not XGB_PKL.exists():
        print(f"[ERR] {XGB_PKL} not found — train XGB first.")
        return 1

    print(f"== Loading XGBoost pickle: {XGB_PKL}")
    with open(XGB_PKL, "rb") as f:
        clf = pickle.load(f)
    print(f"   type={type(clf).__name__}  n_features={getattr(clf, 'n_features_in_', '?')}")

    booster = clf.get_booster() if hasattr(clf, "get_booster") else clf
    print(f"   booster: {type(booster).__name__}")

    # ── Treelite import ────────────────────────────────────────────
    print("== Importing booster into Treelite IR ...")
    model = treelite.frontend.from_xgboost(booster)
    print(f"   num_tree={model.num_tree}  num_feature={model.num_feature}")

    # ── tl2cgen compile ────────────────────────────────────────────
    out_dir = ROOT / "models"
    sysname = platform.system()
    libname = "xgb_treelite.dll" if sysname == "Windows" else "xgb_treelite.so"
    libpath = out_dir / libname
    toolchain = "msvc" if sysname == "Windows" else "gcc"
    print(f"== Compiling via tl2cgen -> {libpath} (toolchain={toolchain})")
    t0 = time.perf_counter()
    tl2cgen.export_lib(
        model,
        toolchain=toolchain,
        libpath=str(libpath),
        params={"parallel_comp": 4},
        verbose=False,
    )
    print(f"   compiled in {time.perf_counter() - t0:.1f} s | {libpath.stat().st_size / 1024:.0f} kB")

    # ── Parity check ───────────────────────────────────────────────
    print("== Parity test: native XGBoost vs Treelite (100 random samples)")
    rng = np.random.default_rng(42)
    n_features = model.num_feature
    X = rng.standard_normal(size=(100, n_features), dtype=np.float32)
    # XGB native
    if hasattr(clf, "predict_proba"):
        y_native = clf.predict_proba(X)
        if y_native.ndim == 2 and y_native.shape[1] == 2:
            y_native = y_native[:, 1]
    else:
        import xgboost as xgb
        y_native = booster.predict(xgb.DMatrix(X))

    # Treelite
    predictor = tl2cgen.Predictor(str(libpath))
    dmat = tl2cgen.DMatrix(X.astype(np.float32))
    y_tl = predictor.predict(dmat).flatten()

    diff = np.abs(y_native.flatten() - y_tl)
    print(f"   max abs diff = {diff.max():.6e}")
    print(f"   mean abs diff = {diff.mean():.6e}")
    if diff.max() > 1e-4:
        print("[ERR] Predictions diverge — refusing to call this a successful compile.")
        return 2
    print("[OK] Parity holds (< 1e-4) — Treelite shared lib ready.")

    # ── Speed bench (small N — what scanner uses per cycle is N=1) ──
    print("== Speed comparison (5000 samples, 5 runs each)")
    Xb = rng.standard_normal(size=(5000, n_features), dtype=np.float32)
    runs = 5
    # native
    t = []
    for _ in range(runs):
        s = time.perf_counter()
        _ = clf.predict_proba(Xb)
        t.append(time.perf_counter() - s)
    print(f"   native xgb predict_proba: median={sorted(t)[runs//2]*1000:.1f} ms  min={min(t)*1000:.1f} ms")
    # treelite
    dm = tl2cgen.DMatrix(Xb.astype(np.float32))
    t = []
    for _ in range(runs):
        s = time.perf_counter()
        _ = predictor.predict(dm)
        t.append(time.perf_counter() - s)
    print(f"   treelite predictor:       median={sorted(t)[runs//2]*1000:.1f} ms  min={min(t)*1000:.1f} ms")

    return 0


if __name__ == "__main__":
    sys.exit(main())
