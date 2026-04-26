#!/usr/bin/env python3
"""
status_v2.py — Quick status check of master plan v2 components.

Reports:
  - Data warehouse: which symbols/TFs present, last fetch dates
  - Models v2: which trained, last train date, cv metrics
  - Shadow log: how many predictions logged, time range
  - Active background processes
  - Suggested next actions

Run anytime to see "where are we" at a glance.

Usage:
    python scripts/status_v2.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Repo root path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

WAREHOUSE = Path("data/historical")
MANIFEST = WAREHOUSE / "manifest.json"
MODELS_V2 = Path("models/v2")
SHADOW_LOG = Path("data/shadow_predictions.jsonl")


def warehouse_status():
    print("=" * 60)
    print("DATA WAREHOUSE")
    print("=" * 60)
    if not MANIFEST.exists():
        print("  No manifest. Run scripts/data_collection/build_data_warehouse.py")
        return
    with open(MANIFEST) as f:
        manifest = json.load(f)
    by_symbol = {}
    for key, value in manifest.items():
        # 2026-04-26: support both legacy flat format ("XAU/USD/5m": "2026-04-26...")
        # and nested format ({"XAU_USD": {"5m": {"last_fetched": "..."}}}).
        if isinstance(value, dict):
            # Nested per-symbol format
            for tf, meta in value.items():
                last_ts = meta.get("last_fetched") if isinstance(meta, dict) else str(meta)
                if last_ts:
                    by_symbol.setdefault(key, []).append((tf, last_ts))
        else:
            # Flat key format
            try:
                symbol, tf = key.rsplit("/", 1)
            except ValueError:
                continue
            by_symbol.setdefault(symbol, []).append((tf, value))
    for symbol, entries in sorted(by_symbol.items()):
        tfs_str = ", ".join(f"{tf}({last[:10]})" for tf, last in sorted(entries))
        print(f"  {symbol:12s}: {tfs_str}")
    print()


def models_status():
    print("=" * 60)
    print("MODELS V2")
    print("=" * 60)
    if not MODELS_V2.exists():
        print("  No models/v2 dir. Run python scripts/train_v2.py")
        return
    metas = list(MODELS_V2.glob("*.meta.json"))
    if not metas:
        print("  No metadata files found.")
        return
    for meta_path in sorted(metas):
        with open(meta_path) as f:
            meta = json.load(f)
        name = meta_path.stem.replace(".meta", "")
        direction = meta.get("direction", "?")
        n_samples = meta.get("n_samples", "?")
        score = meta.get("best_cv_mse") or meta.get("val_mse")
        trained_at = meta.get("trained_at", "?")[:19]
        print(f"  {name:30s}: dir={direction}, n={n_samples}, "
              f"score={score}, at={trained_at}")
    print()


def shadow_status():
    print("=" * 60)
    print("SHADOW LOG")
    print("=" * 60)
    if not SHADOW_LOG.exists():
        print("  No shadow log yet. Will appear when API + v2 models running.")
        return
    n_records = 0
    earliest = None
    latest = None
    actionable = 0
    with open(SHADOW_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except:
                continue
            n_records += 1
            ts = rec.get("ts")
            if ts:
                if earliest is None or ts < earliest:
                    earliest = ts
                if latest is None or ts > latest:
                    latest = ts
            if rec.get("v2_signal") in ("LONG", "SHORT"):
                actionable += 1
    print(f"  Records:      {n_records}")
    print(f"  Actionable:   {actionable} ({actionable/max(n_records,1)*100:.1f}%)")
    print(f"  Earliest:     {earliest}")
    print(f"  Latest:       {latest}")
    print()


def suggest_next():
    print("=" * 60)
    print("SUGGESTED NEXT ACTIONS")
    print("=" * 60)
    actions = []
    if not MANIFEST.exists():
        actions.append("python scripts/data_collection/build_data_warehouse.py")
    elif not MODELS_V2.exists() or not list(MODELS_V2.glob("xau_*.json")):
        actions.append("python scripts/train_v2.py --years 3")
    elif not SHADOW_LOG.exists():
        actions.append("Restart API to enable _shadow_scanner background task")
    else:
        with open(SHADOW_LOG) as f:
            n = sum(1 for _ in f)
        if n < 100:
            actions.append(f"Wait for shadow log to accumulate (currently {n})")
        else:
            actions.append("python scripts/compare_v1_v2_shadow.py")

    # Walk-forward suggestion
    if MODELS_V2.exists() and list(MODELS_V2.glob("xau_*.json")):
        actions.append("python scripts/run_walk_forward.py --quick  # 30/7/14 fast test")

    if not actions:
        actions.append("All systems ready. Monitor shadow log + walk-forward results.")

    for a in actions:
        print(f"  - {a}")
    print()


def main():
    warehouse_status()
    models_status()
    shadow_status()
    suggest_next()


if __name__ == "__main__":
    main()
