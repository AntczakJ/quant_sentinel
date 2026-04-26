"""
tools/modal_train.py — Modal Labs offload skeleton for `train_all.py`.

This is a SKELETON — it doesn't run until you add Modal credentials and
deploy. Goal: rent a cloud GPU for the heavy retrain (LSTM/XGB/transformer
voters) once a day, keep the local 1070 free for live scoring.

Why bother
----------
Current TF Windows build has no GPU support after 2.11, so LSTM training
runs on CPU even though Janek has a 1070. As features creep upward, the
24h retrain cycle gets tighter every month. Modal H100 30-min slot is
~$5–15/month and frees the local box.

Setup (one-time, ~5 min)
------------------------
1. `pip install modal` (already in your dev tooling)
2. `modal token new` — opens browser, links a free account.
3. `modal deploy tools/modal_train.py` — pushes this app to Modal.
4. `modal run tools/modal_train.py::run` — kicks a remote training run.

After deploy, schedule it from Modal's UI (Periodic Trigger, e.g. daily
at 02:00 UTC) or call `modal_app.run.remote()` from your local cron.

What this skeleton does (and doesn't)
-------------------------------------
- DOES define a Modal app, an Image with the heavy ML deps, a Volume for
  the warehouse + models, and a `run` function that mirrors your local
  `train_all.py` invocation.
- DOES NOT push your warehouse data automatically. Use `modal volume put
  qs-warehouse data/historical /historical` to seed it once; subsequent
  trades are pulled fresh inside the function.
- DOES NOT touch live trading or sentinel.db — only writes new models.
- Models flow back via the same Volume; download with
  `modal volume get qs-models models/ ./models/` after each run.

Trim the dependency list to fit your real `train_all.py` imports.
"""
from __future__ import annotations

import os
from pathlib import Path

# This import will fail locally until you `pip install modal`. That's
# fine — the skeleton is still useful for `modal deploy`.
try:
    import modal  # type: ignore
except ImportError:  # pragma: no cover
    print("[modal_train] `modal` package not installed locally — `pip install modal` first.")
    raise SystemExit(0)


APP_NAME = "quant-sentinel-train"

# ── Container image ────────────────────────────────────────────────
# Pin versions you actually use. Modal caches layers, so this only
# rebuilds when this list changes.
image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("git", "build-essential")
    .pip_install(
        "numpy>=2.2,<2.5",
        "pandas>=3.0",
        "scikit-learn>=1.8",
        "xgboost>=3.0",
        "torch>=2.11",      # CUDA wheels on Modal are auto-resolved
        "tensorflow>=2.20",
        "transformers>=5.4",
        "sentence-transformers>=5.0",
        "scipy>=1.17",
        "pywavelets>=1.8",
        "tqdm>=4.67",
        "pydantic>=2.12",
        "treelite>=4.7",
        "tl2cgen>=1.0",
    )
)

# Volumes — persistent across runs, mounted at /historical and /models.
warehouse_volume = modal.Volume.from_name("qs-warehouse", create_if_missing=True)
models_volume = modal.Volume.from_name("qs-models", create_if_missing=True)

app = modal.App(APP_NAME, image=image)


@app.function(
    # Pick the smallest GPU that fits — Janek's models are XGB-heavy,
    # T4 is enough; bump to L4/A100 only if LSTM training balloons.
    gpu="T4",
    timeout=60 * 60,  # 1h hard cap
    volumes={
        "/historical": warehouse_volume,
        "/models": models_volume,
    },
    # Add secrets on first deploy: `modal secret create qs-keys
    #   TWELVEDATA_KEY=... ALPHA_VANTAGE_KEY=... FRED_API_KEY=...`
    # then re-run `modal deploy` to pick it up.
    secrets=[modal.Secret.from_name("qs-keys")] if os.environ.get("MODAL_USE_SECRETS") else [],
)
def run(
    skip_lstm: bool = False,
    skip_rl: bool = True,
    skip_xgb: bool = False,
    days: int = 365,
):
    """Mirror of `train_all.py` invocation, executed on Modal infrastructure.

    The actual training script ships with the function via the
    `add_local_dir` mount below in `local_entrypoint`. This function then
    invokes it as a subprocess so logging behaves identically to local.
    """
    import subprocess
    import sys

    cmd = [sys.executable, "/repo/train_all.py", "--days", str(days)]
    if skip_lstm:
        cmd.append("--skip-lstm")
    if skip_rl:
        cmd.append("--skip-rl")
    if skip_xgb:
        cmd.append("--skip-xgb")

    print(f"[modal_train] running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, env={**os.environ, "PYTHONPATH": "/repo"})

    # Persist trained artifacts back to the volume.
    out = Path("/repo/models")
    if out.exists():
        for f in out.glob("*"):
            dest = Path("/models") / f.name
            dest.write_bytes(f.read_bytes())
        print(f"[modal_train] copied {len(list(out.glob('*')))} model files to /models")


_MOUNT_IGNORE = (
    # Anything that would inflate the bundle past the 5 GB Modal limit.
    "**/.venv/**", "**/node_modules/**", "**/__pycache__/**",
    "**/dist/**", "**/build/**", "**/.git/**",
    "**/data/sentinel.db*", "**/data/backups/**", "**/data/_*cache*/**",
    "**/data/historical/**",   # warehouse goes via the qs-warehouse Volume
    "**/logs/**", "**/.pytest_cache/**", "**/.ruff_cache/**",
    "**/frontend/**",          # the trainer never touches the SPA
    "**/frontend_v3_baseline/**", "**/frontend_v1/**",
    "**/uv.lock", "**/.mypy_cache/**",
)


@app.local_entrypoint()
def main(skip_lstm: bool = False, skip_rl: bool = True, skip_xgb: bool = False):
    """Local CLI hook: `modal run tools/modal_train.py::main --skip-lstm`.

    The repo gets attached as a local dir so train_all.py runs unchanged
    on the remote container. Heavy / irrelevant trees are excluded via
    `_MOUNT_IGNORE` — without them Modal would refuse the upload.
    """
    repo_root = Path(__file__).resolve().parents[1]
    run.with_options(  # type: ignore[attr-defined]
        mounts=[modal.Mount.from_local_dir(
            str(repo_root),
            remote_path="/repo",
            condition=lambda p: not any(
                __import__("fnmatch").fnmatch(p, pat) for pat in _MOUNT_IGNORE
            ),
        )]
    ).remote(skip_lstm=skip_lstm, skip_rl=skip_rl, skip_xgb=skip_xgb)


if __name__ == "__main__":
    print(__doc__)
    print("\nUsage: modal run tools/modal_train.py::main [--skip-lstm] [--skip-rl] [--skip-xgb]")
