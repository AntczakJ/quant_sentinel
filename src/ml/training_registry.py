"""
src/ml/training_registry.py — Lightweight training run registry.

Logs each model training session to models/training_history.jsonl
(append-only JSONL) for:
  - model_type (rl_agent, lstm, xgb, attention, decompose)
  - timestamp, git commit hash, git branch
  - hyperparameters (episodes, batch_size, lr, etc.)
  - data signature (symbols, interval, period, hash)
  - validation metrics (per-symbol + aggregate)
  - artifact path + size

No external deps. JSONL chosen over SQLite for:
  - Easy diffing in git (if committed)
  - No schema migrations
  - cat/grep-friendly
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.logger import logger


REGISTRY_PATH = Path("models/training_history.jsonl")


def _git_info() -> Dict[str, str]:
    """Best-effort git metadata. Returns empty strings if git unavailable."""
    def _run(cmd):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
            return out.stdout.strip() if out.returncode == 0 else ""
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
    return {
        "git_commit": _run(["git", "rev-parse", "--short", "HEAD"]),
        "git_branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "git_dirty": bool(_run(["git", "status", "--porcelain"])),
    }


def log_training_run(
    model_type: str,
    hyperparams: Dict[str, Any],
    data_signature: Dict[str, Any],
    metrics: Dict[str, Any],
    artifact_path: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a training run record to the registry.

    Args:
      model_type: 'rl_agent', 'lstm', 'xgb', 'attention', 'decompose', etc.
      hyperparams: e.g. {'episodes': 300, 'batch_size': 64, 'lr': 0.001}
      data_signature: e.g. {'symbols': [...], 'interval': '1h', 'period': '2y', 'data_hash': 'abc123'}
      metrics: e.g. {'val_return': -4.6, 'val_win_rate': 54, 'per_symbol': {...}}
      artifact_path: path to saved model file (for size lookup)
      notes: free-form string

    Returns the record that was written.
    """
    artifact_info = {}
    if artifact_path and os.path.exists(artifact_path):
        artifact_info = {
            "path": artifact_path,
            "size_bytes": os.path.getsize(artifact_path),
        }

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "unix_ts": time.time(),
        "model_type": model_type,
        "hyperparams": hyperparams,
        "data": data_signature,
        "metrics": metrics,
        "artifact": artifact_info,
        "notes": notes,
        **_git_info(),
    }

    try:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REGISTRY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(f"[registry] logged {model_type} training run (val={metrics.get('val_return', 'n/a')})")
    except Exception as e:
        logger.warning(f"[registry] failed to log training run: {e}")

    return record


def list_runs(model_type: Optional[str] = None, limit: int = 20) -> list[Dict]:
    """Return most recent training runs (optionally filtered by model_type)."""
    if not REGISTRY_PATH.exists():
        return []
    runs = []
    try:
        with REGISTRY_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if model_type and rec.get("model_type") != model_type:
                    continue
                runs.append(rec)
    except Exception as e:
        logger.warning(f"[registry] read failed: {e}")
        return []
    runs.sort(key=lambda r: r.get("unix_ts", 0), reverse=True)
    return runs[:limit]


def get_best_run(model_type: str, metric: str = "val_return",
                 higher_is_better: bool = True) -> Optional[Dict]:
    """Find the best historical run for a model_type by a given metric."""
    runs = list_runs(model_type=model_type, limit=1000)
    def _metric(r):
        v = r.get("metrics", {}).get(metric)
        try:
            return float(v)
        except (TypeError, ValueError):
            return float("-inf") if higher_is_better else float("inf")
    if not runs:
        return None
    return max(runs, key=_metric) if higher_is_better else min(runs, key=_metric)
