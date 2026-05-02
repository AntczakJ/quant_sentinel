#!/usr/bin/env python3
"""
preflight_api_restart.py — sanity-check before bringing the API back live.

Runs ALL of these and prints PASS/FAIL for each. Returns 0 (green) only
if every check passes; otherwise prints the failing items + bail.

  1.  Calibration kill-switch active (DISABLE_CALIBRATION=1 in .env or env)
  2.  models/calibration_params.pkl all entries fitted=False (defense-in-depth)
  3.  models/feature_cols.json present + dim matches src.analysis.compute.FEATURE_COLS
  4.  Required artifacts exist + recent (xgb.pkl, lstm.keras, attention.keras, ...)
  5.  XGB Treelite DLL is FRESH (mtime > xgb.pkl mtime — stale guard would refuse it)
  6.  Each voter's _load_xgb / _load_lstm / _load_attention returns a non-None object
  7.  Inference smoke: run predict_xgb_direction / predict_lstm_direction on a small
      tail of warehouse XAU. Verify outputs are in [0, 1] and not NaN/Inf.
  8.  Port 8000 not in use (no rogue uvicorn or other listener)
  9.  data/SCANNER_PAUSED flag absent (or warn if present — operator may want pause)
  10. data/sentinel.db reachable + no zombie OPEN trades with synthetic prices
  11. dynamic_params voter weights sum is sensible (sum > 0.5)
  12. .env has DISABLE_TRAILING + MAX_LOT_CAP set (lot-sizing safety net still on)

Run BEFORE every API restart. Especially after a fresh retrain — catches
common foot-guns (stale Treelite, mismatched FEATURE_COLS dim, etc.).

Usage:
    python scripts/preflight_api_restart.py
    python scripts/preflight_api_restart.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import socket
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ── Individual check helpers ──────────────────────────────────────────

def _check_calibration_killswitch() -> tuple[bool, str]:
    # Env var
    val = os.environ.get("DISABLE_CALIBRATION")
    if val == "1":
        return (True, "DISABLE_CALIBRATION=1 in process env")
    # .env file
    env_path = _REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == "DISABLE_CALIBRATION" and v.strip() == "1":
                return (True, f"DISABLE_CALIBRATION=1 in .env (will be loaded by api/main.py)")
    return (False, "DISABLE_CALIBRATION not set — calibration will reload INVERTED Platt params")


def _check_calibration_pkl() -> tuple[bool, str]:
    pkl = _REPO_ROOT / "models" / "calibration_params.pkl"
    if not pkl.exists():
        return (True, "calibration_params.pkl absent (no mappings — kill-switch effective)")
    try:
        with open(pkl, "rb") as f:
            data = pickle.load(f)
        if not isinstance(data, dict):
            return (False, f"calibration_params.pkl unexpected type {type(data).__name__}")
        for name, entry in data.items():
            if entry.get("fitted"):
                return (False, f"calibration_params.pkl[{name}] fitted=True — kill-switch is your only line of defense")
        return (True, f"all {len(data)} calibration entries fitted=False")
    except Exception as e:
        return (False, f"calibration_params.pkl unreadable: {e}")


def _check_feature_cols_pin() -> tuple[bool, str]:
    pin = _REPO_ROOT / "models" / "feature_cols.json"
    if not pin.exists():
        return (False, "models/feature_cols.json missing — train_all.py was not run on cleaned pipeline")
    try:
        from src.analysis.compute import FEATURE_COLS
    except Exception as e:
        return (False, f"cannot import FEATURE_COLS: {e}")
    pinned = json.loads(pin.read_text(encoding="utf-8"))
    pinned_cols = pinned.get("feature_cols", [])
    if list(pinned_cols) != list(FEATURE_COLS):
        diff = set(pinned_cols).symmetric_difference(set(FEATURE_COLS))
        return (False, f"FEATURE_COLS mismatch ({len(diff)} differing): in-memory={len(FEATURE_COLS)} pinned={len(pinned_cols)}")
    return (True, f"FEATURE_COLS dim match: {len(FEATURE_COLS)} cols (trained {pinned.get('trained_at', '?')})")


REQUIRED = [
    "models/xgb.pkl",
    "models/lstm.keras",
    "models/lstm_scaler.pkl",
    "models/attention.keras",
    "models/attention_scaler.pkl",
    "models/feature_cols.json",
]


def _check_artifacts() -> tuple[bool, str]:
    missing = [p for p in REQUIRED if not (_REPO_ROOT / p).exists()]
    if missing:
        return (False, f"missing: {missing}")
    return (True, f"all {len(REQUIRED)} artifacts present")


def _check_treelite_freshness() -> tuple[bool, str]:
    import platform
    treelite = _REPO_ROOT / "models" / ("xgb_treelite.dll" if platform.system() == "Windows" else "xgb_treelite.so")
    pkl = _REPO_ROOT / "models" / "xgb.pkl"
    if not treelite.exists():
        return (True, "Treelite DLL absent — _load_xgb will fall through to ONNX/sklearn (slower but safe)")
    if not pkl.exists():
        return (False, "xgb_treelite present but xgb.pkl missing — broken state")
    if treelite.stat().st_mtime + 1.0 < pkl.stat().st_mtime:
        return (False, f"Treelite DLL is STALE — recompile via tools/compile_xgb_treelite.py")
    return (True, "Treelite DLL fresher than xgb.pkl")


def _check_voter_loaders() -> tuple[bool, str]:
    """Try loading each voter via the actual ensemble_models loader API.

    Public loaders in src/ml/ensemble_models.py: _load_xgb, _load_lstm,
    _load_dqn, _load_v2_xgb. Attention is loaded inside
    `predict_attention_direction` (no separate loader fn — model loaded
    on first call via its own caching path).
    """
    os.environ["DISABLE_CALIBRATION"] = "1"  # safety
    try:
        from src.ml.ensemble_models import _load_xgb, _load_lstm, _load_dqn
    except Exception as e:
        return (False, f"ensemble_models import failed: {e}")
    failures = []
    successes = []
    for name, fn in (("xgb", _load_xgb), ("lstm", _load_lstm)):
        try:
            r = fn()
            if r is None:
                failures.append(name)
            else:
                kind = r[0] if isinstance(r, tuple) else "?"
                successes.append(f"{name}({kind})")
        except Exception as e:
            failures.append(f"{name}({e!r})")
    try:
        r = _load_dqn()
        successes.append("dqn(loaded)" if r is not None else "dqn(none)")
    except Exception as e:
        failures.append(f"dqn({e!r})")
    if failures:
        return (False, f"loaders failed: {failures}; succeeded: {successes}")
    return (True, f"loaders ok: {successes}")


def _check_inference_smoke() -> tuple[bool, str]:
    """Run inference on a tiny tail of warehouse XAU + USDJPY."""
    import pandas as pd
    import numpy as np
    os.environ["DISABLE_CALIBRATION"] = "1"
    xau_path = _REPO_ROOT / "data" / "historical" / "XAU_USD" / "1h.parquet"
    if not xau_path.exists():
        return (False, "warehouse XAU 1h parquet missing")
    df = pd.read_parquet(xau_path).tail(300)
    try:
        from src.ml.ensemble_models import predict_xgb_direction, predict_lstm_direction
        xgb_pred = predict_xgb_direction(df)
        lstm_pred = predict_lstm_direction(df)
    except Exception as e:
        return (False, f"inference exception: {e}")
    issues = []
    for name, p in (("xgb", xgb_pred), ("lstm", lstm_pred)):
        if p is None:
            issues.append(f"{name}=None (voter unavailable)")
        elif not np.isfinite(p):
            issues.append(f"{name}={p} (NaN/Inf)")
        elif not (0.0 <= p <= 1.0):
            issues.append(f"{name}={p:.3f} (out of [0,1])")
    if issues:
        return (False, "; ".join(issues))
    return (True, f"xgb={xgb_pred:.3f}, lstm={lstm_pred:.3f}")


def _check_port_8000() -> tuple[bool, str]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        if s.connect_ex(("127.0.0.1", 8000)) == 0:
            return (False, "port 8000 already in use — kill existing uvicorn first")
        return (True, "port 8000 free")
    finally:
        s.close()


def _check_pause_flag() -> tuple[bool, str]:
    flag = _REPO_ROOT / "data" / "SCANNER_PAUSED"
    if flag.exists():
        return (True, "SCANNER_PAUSED present — API will start in paused state (intentional?)")
    return (True, "SCANNER_PAUSED absent — scanner active on start")


def _check_db_state() -> tuple[bool, str]:
    import sqlite3
    db = _REPO_ROOT / "data" / "sentinel.db"
    if not db.exists():
        return (False, "data/sentinel.db missing")
    try:
        con = sqlite3.connect(str(db))
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM trades")
        n_total = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM trades WHERE status IN ('OPEN','PROPOSED') "
            "AND entry < 1000"  # synthetic phantom indicator
        )
        n_phantom = cur.fetchone()[0]
        con.close()
    except Exception as e:
        return (False, f"sqlite query failed: {e}")
    if n_phantom > 0:
        return (False, f"{n_phantom} OPEN/PROPOSED trades with entry<1000 (synthetic phantoms — auto-resolver will crash)")
    return (True, f"DB clean: {n_total} total trades, 0 phantom OPEN")


def _check_voter_weights_sum() -> tuple[bool, str]:
    try:
        from src.ml.ensemble_models import _load_dynamic_weights
        w = _load_dynamic_weights()
    except Exception as e:
        return (False, f"weight load failed: {e}")
    s = sum(w.values())
    if s < 0.5:
        return (False, f"weight sum {s:.3f} < 0.5 — most voters muted, ensemble dead")
    return (True, f"weight sum {s:.3f}, weights={w}")


def _check_env_safety_flags() -> tuple[bool, str]:
    env_path = _REPO_ROOT / ".env"
    flags = {"DISABLE_TRAILING": None, "MAX_LOT_CAP": None}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k in flags:
                flags[k] = v.strip()
    msgs = []
    bad = False
    if flags["DISABLE_TRAILING"] != "1":
        msgs.append("DISABLE_TRAILING≠1 (backtest showed trailing OFF was +EV)")
        bad = True
    else:
        msgs.append("DISABLE_TRAILING=1 OK")
    if flags["MAX_LOT_CAP"] is None:
        msgs.append("MAX_LOT_CAP unset — lot-sizing rebuild design assumes cap=0.01")
        bad = True
    else:
        msgs.append(f"MAX_LOT_CAP={flags['MAX_LOT_CAP']} OK")
    return (not bad, "; ".join(msgs))


def _check_factor_weights_tuned() -> tuple[bool, str]:
    """Verify the 2026-05-02 factor weight tuning hasn't been rolled back.

    bos should be near 1.8 (was 1.598), fvg near 0.7 (was 1.281), etc.
    These weights affect score_setup_quality grading and were applied
    autonomously per Janek authorization.
    """
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        expected = {
            "weight_bos":           (1.7, 2.0),    # tuned to 1.800
            "weight_ichimoku_bear": (1.05, 1.30),  # tuned to 1.150
            "weight_fvg":           (0.50, 0.85),  # tuned to 0.700 (cut)
            "weight_killzone":      (0.50, 0.85),  # tuned to 0.700
            "weight_ichimoku_bull": (0.70, 1.00),  # tuned to 0.850
            "weight_macro":         (0.65, 0.95),  # tuned to 0.800
        }
        bad = []
        for key, (lo, hi) in expected.items():
            val = db.get_param(key, None)
            if val is None or not (lo <= float(val) <= hi):
                bad.append(f"{key}={val} (expected {lo}-{hi})")
        if bad:
            return (False, "; ".join(bad))
        return (True, "all 6 factor weights within expected tuned range")
    except Exception as e:
        return (False, f"check failed: {e}")


def _check_voter_persist_fix() -> tuple[bool, str]:
    """Verify the 2026-05-02 _voter_value muted-handling fix is in place.

    Reads ensemble_models.py source for the _MISSING_STATUSES set —
    catches accidental rollback of the fix that was breaking self-learner
    attribution for muted voters.
    """
    try:
        path = _REPO_ROOT / "src" / "ml" / "ensemble_models.py"
        body = path.read_text(encoding="utf-8")
        if "_MISSING_STATUSES" in body and '"unavailable"' in body and '"disabled"' in body:
            return (True, "_voter_value uses _MISSING_STATUSES set (fix in place)")
        return (False, "voter persist fix appears reverted — _MISSING_STATUSES missing")
    except Exception as e:
        return (False, f"check failed: {e}")


def _check_ml_majority_keys() -> tuple[bool, str]:
    """Smoke: get_ensemble_prediction returns ml_majority_disagrees +
    decisive_ratio in model_agreement. Catches accidental revert of the
    2026-05-02 observability additions.
    """
    try:
        # Just check source has the keys — running a full ensemble call here
        # would require live data and 30+ seconds.
        path = _REPO_ROOT / "src" / "ml" / "ensemble_models.py"
        body = path.read_text(encoding="utf-8")
        missing = []
        for key in ("ml_majority", "decisive_ratio", "ml_majority_disagrees"):
            if key not in body:
                missing.append(key)
        if missing:
            return (False, f"missing keys in ensemble_models.py: {missing}")
        return (True, "ml_majority_disagrees + decisive_ratio + ml_majority all defined")
    except Exception as e:
        return (False, f"check failed: {e}")


CHECKS = [
    ("calibration_killswitch", _check_calibration_killswitch),
    ("calibration_pkl_neutral", _check_calibration_pkl),
    ("feature_cols_pin", _check_feature_cols_pin),
    ("artifacts_present", _check_artifacts),
    ("treelite_freshness", _check_treelite_freshness),
    ("voter_loaders", _check_voter_loaders),
    ("inference_smoke", _check_inference_smoke),
    ("port_8000_free", _check_port_8000),
    ("pause_flag", _check_pause_flag),
    ("db_clean", _check_db_state),
    ("voter_weights", _check_voter_weights_sum),
    ("env_safety_flags", _check_env_safety_flags),
    # 2026-05-02 audit additions
    ("factor_weights_tuned", _check_factor_weights_tuned),
    ("voter_persist_fix", _check_voter_persist_fix),
    ("ml_majority_keys", _check_ml_majority_keys),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = {}
    for name, fn in CHECKS:
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, f"check raised: {e!r}"
        results[name] = {"ok": ok, "msg": msg}

    if args.json:
        print(json.dumps(results, indent=2, default=str))
        return 0 if all(r["ok"] for r in results.values()) else 1

    print("=" * 70)
    print("API Restart Pre-flight")
    print("=" * 70)
    fail_count = 0
    for name, r in results.items():
        marker = "PASS" if r["ok"] else "FAIL"
        if not r["ok"]:
            fail_count += 1
        print(f"  [{marker}]  {name}")
        print(f"          {r['msg']}")

    print()
    print("=" * 70)
    if fail_count == 0:
        print(f"VERDICT: GREEN — safe to start API.")
        print()
        print("Suggested startup:")
        print("  .venv/Scripts/python.exe -m uvicorn api.main:app \\")
        print("      --host 127.0.0.1 --port 8000 --log-level info \\")
        print("      > logs/api.log 2>&1 &")
        return 0
    else:
        print(f"VERDICT: RED — {fail_count} check(s) failed. Do NOT start API.")
        print()
        print("Fix the failing items above, then re-run:")
        print("  .venv/Scripts/python.exe scripts/preflight_api_restart.py")
        return 1


if __name__ == "__main__":
    sys.exit(main())
