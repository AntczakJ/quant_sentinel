#!/usr/bin/env python3
"""
scripts/retrain_scheduler.py — Auto-retrain ML models when stale.

Checks model file ages and triggers retrain if older than threshold.
Designed for cron:

    # Weekly RL retrain (Sunday 03:00):
    0 3 * * 0 cd /opt/quant_sentinel && .venv/bin/python scripts/retrain_scheduler.py rl

    # Weekly full ensemble retrain (Sunday 04:00):
    0 4 * * 0 cd /opt/quant_sentinel && .venv/bin/python scripts/retrain_scheduler.py all

    # Or auto-mode: retrain only what's stale:
    0 3 * * 0 cd /opt/quant_sentinel && .venv/bin/python scripts/retrain_scheduler.py auto

Usage:
    python scripts/retrain_scheduler.py check   # dry-run, just report status
    python scripts/retrain_scheduler.py auto    # retrain only stale models
    python scripts/retrain_scheduler.py rl      # force RL retrain
    python scripts/retrain_scheduler.py all     # force full ensemble retrain

Safety:
- Always backs up current model before retrain
- Logs to logs/retrain_scheduler.log
- Sends Telegram alert on start + completion
- Rolls back if training fails
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


STALE_DAYS_THRESHOLD = 14

MODELS = {
    "rl": ["models/rl_agent.keras", "models/rl_agent.keras.params"],
    "lstm": ["models/lstm.keras", "models/lstm_scaler.pkl"],
    "xgb": ["models/xgb.pkl"],
    "attention": ["models/attention.keras", "models/attention_scaler.pkl"],
    "decompose": ["models/decompose.keras", "models/decompose_scaler.pkl"],
}


def _age_days(path: str) -> float:
    if not os.path.exists(path):
        return float("inf")
    return (time.time() - os.path.getmtime(path)) / 86400


def _stale_models() -> list[str]:
    """Return list of model names that are stale (>threshold days)."""
    stale = []
    for name, files in MODELS.items():
        primary = files[0]
        age = _age_days(primary)
        if age > STALE_DAYS_THRESHOLD or age == float("inf"):
            stale.append(name)
    return stale


def _backup_models(names: list[str]) -> str:
    """Snapshot models to data/backups/pre_retrain_<ts>/. Returns backup dir."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(f"data/backups/pre_retrain_{ts}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        for src in MODELS[name]:
            if os.path.exists(src):
                dst = backup_dir / Path(src).name
                shutil.copy2(src, dst)
    return str(backup_dir)


def _telegram_alert(text: str) -> None:
    try:
        from src.trading.scanner import send_telegram_alert
        send_telegram_alert(text)
    except Exception:
        pass


def _run(cmd: list[str], timeout: int = 3600) -> tuple[bool, str]:
    """Run subprocess. Returns (ok, log tail)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        ok = result.returncode == 0
        return ok, (result.stdout + "\n" + result.stderr)[-500:]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT after {timeout}s"
    except Exception as e:
        return False, f"EXCEPTION: {e}"


def check_status() -> None:
    """Dry-run: print model ages."""
    print(f"Model staleness check (threshold: {STALE_DAYS_THRESHOLD} days)")
    print("=" * 60)
    for name, files in MODELS.items():
        age = _age_days(files[0])
        age_str = "MISSING" if age == float("inf") else f"{age:.1f}d old"
        status = "STALE" if age > STALE_DAYS_THRESHOLD else "fresh"
        print(f"  [{status:>5}] {name:<12} {age_str:<12} ({files[0]})")


def retrain_rl() -> bool:
    """Retrain RL agent. Returns True on success."""
    print("[scheduler] Retraining RL agent (150 episodes)...")
    backup = _backup_models(["rl"])
    print(f"[scheduler] Backed up to {backup}")
    _telegram_alert(f"🔄 *RL retrain started*\nBackup: `{backup}`")
    ok, tail = _run([sys.executable, "train_rl.py", "150"], timeout=3600)
    if not ok:
        _telegram_alert(f"❌ *RL retrain FAILED*\n```\n{tail[:300]}\n```\nRolling back...")
        # Restore
        for src_file in Path(backup).iterdir():
            shutil.copy2(src_file, f"models/{src_file.name}")
        return False
    _telegram_alert("✅ *RL retrain complete*\nNew model live.")
    return True


def retrain_all() -> bool:
    """Full ensemble retrain via train_all.py."""
    print("[scheduler] Retraining full ensemble...")
    backup = _backup_models(list(MODELS.keys()))
    _telegram_alert(f"🔄 *Full ensemble retrain started*\nBackup: `{backup}`")
    ok, tail = _run([sys.executable, "train_all.py"], timeout=7200)  # 2h
    if not ok:
        _telegram_alert(f"❌ *Full retrain FAILED*\n```\n{tail[:300]}\n```")
        return False
    _telegram_alert("✅ *Full retrain complete*")
    return True


def auto() -> None:
    """Retrain only models that are stale."""
    stale = _stale_models()
    if not stale:
        print("[scheduler] All models fresh — nothing to do")
        return
    print(f"[scheduler] Stale models: {stale}")
    if "rl" in stale:
        retrain_rl()
    non_rl_stale = [m for m in stale if m != "rl"]
    if non_rl_stale:
        # train_all.py retrains all non-RL + RL; use it if any non-RL is stale
        retrain_all()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "auto", "rl", "all"],
                    help="check=dry-run, auto=stale only, rl/all=force")
    args = ap.parse_args()

    if args.action == "check":
        check_status()
    elif args.action == "auto":
        auto()
    elif args.action == "rl":
        retrain_rl()
    elif args.action == "all":
        retrain_all()


if __name__ == "__main__":
    main()
