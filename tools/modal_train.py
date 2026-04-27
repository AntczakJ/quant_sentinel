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
_REPO_ROOT = Path(__file__).resolve().parents[1]


_IGNORE_DIRS = {
    ".venv", "node_modules", "__pycache__", "dist", "build", ".git",
    ".idea", ".vscode",   # IDE state — PyCharm rewrites workspace.xml mid-build
    "backups", "logs", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    "frontend", "frontend_v3_baseline", "frontend_v1", ".logfire",
    "historical",     # warehouse goes via Volume, not the bundled image
    "models",         # models go via the qs-models Volume — bundled stale
                      # weights would otherwise overwrite freshly-trained ones
    "models_modal",   # local pull dir, irrelevant on remote
    "optuna_studies", "param_backups",
    "tasks",   # claude task transcripts
}
_IGNORE_FILES = {"sentinel.db", "sentinel.db-wal", "sentinel.db-shm",
                 "backtest.db", "backtest.db-wal", "backtest.db-shm",
                 "uv.lock"}


def _ignore_path(path) -> bool:
    """`add_local_dir` ignore-callback. Path-component matching so Windows
    backslashes / forward-slashes / mixed work identically. Returns True
    when the path should NOT be uploaded into the image."""
    p = Path(path)
    parts = set(p.parts)
    if parts & _IGNORE_DIRS:
        return True
    if p.name in _IGNORE_FILES:
        return True
    # data/_<anything>cache<anything>/  — sweep caches
    for part in p.parts:
        if part.startswith("_") and "cache" in part.lower():
            return True
    return False


# ── GPU image (2026-04-27 rebuild) ───────────────────────────────
#
# Why this changed: the previous attempt used
# `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04` as a base + `add_python=
# "3.13"` + `tensorflow[and-cuda]>=2.20`. The base ships an older cuDNN
# (~9.0/9.1 with CUDA 12.4) than what TF 2.21 expects (CUDA 12.5+, cuDNN
# 9.3+). `tensorflow[and-cuda]` does pull the right `nvidia-*` packages
# into site-packages, but the older system cuDNN was getting picked up
# first by the dynamic loader, leaving TF's GPU init silently broken
# (visible in logs only as "GPU will not be used"). Net: T4 paid for,
# zero GPU work.
#
# New strategy: drop the heavy CUDA base and let TF's pip extras own the
# CUDA + cuDNN install end-to-end. This is the canonical Modal pattern.
# `debian_slim` provides a clean userland with no conflicting CUDA libs.
# TF 2.18+ auto-discovers `site-packages/nvidia/*/lib` at import time, so
# no extra `LD_LIBRARY_PATH` is needed (we set one anyway as belt+braces
# for any sub-process / native lib that doesn't go through Python).
#
# Verification path: `modal run tools/modal_train.py::gpu_check` runs the
# diagnostic function below — confirms TF sees a CUDA device, runs a
# tiny GPU matmul, prints versions + paths. Run that BEFORE every full
# training run when stack changes.
image = (
    modal.Image.debian_slim(python_version="3.13")
    # tzdata: yfinance needs `zoneinfo.ZoneInfo("America/New_York")`.
    # build-essential: numba / pandas_ta / pywavelets occasionally need
    # a C toolchain at install or runtime. git: harmless, useful for
    # any pip-from-vcs deps that may slip in.
    .apt_install("git", "build-essential", "tzdata")
    .pip_install(
        # Core ML stack
        "numpy>=2.2,<2.5",
        "pandas>=3.0",
        "scikit-learn>=1.8",
        "xgboost>=3.0",
        # `[and-cuda]` brings cuda-runtime, cublas, cudnn, cufft, curand,
        # cusolver, cusparse, nccl, nvjitlink — all version-locked to
        # what TF was built against. Pinning the major-minor avoids the
        # auto-bump-to-2.22-tomorrow surprise. Stays in sync with the
        # local pyproject.toml `tensorflow>=2.20` constraint.
        "tensorflow[and-cuda]==2.21.0",
        "scipy>=1.17",
        "tqdm>=4.67",
        "pydantic>=2.12",
        # Data providers — train_all.py pulls XAU history via yfinance
        "yfinance>=1.2.2",
        "curl-cffi>=0.15.0",        # transitive yfinance dep, CVE patch
        "fredapi>=0.5.0",            # macro
        "finnhub-python>=2.4.0",     # macro
        "feedparser>=6.0.10",        # news parsing (optional)
        # Utilities transitively imported by src/* on training path
        "python-dotenv>=1.2.0",
        "PyJWT>=2.12.0",
        "bcrypt>=4.0.0",
        "psutil>=6.0.0",
        "pandas_ta>=0.4.0b0",        # technical indicators in feature engineering
        "pywavelets>=1.8.0",         # signal processing
        "numba>=0.61.0",             # compute hot path JIT
        "tf2onnx>=1.17.0",           # train_all.py converts .keras → .onnx after train
        "onnx>=1.21.0",              # tf2onnx dep — without it conversion silently warns
    )
    # Belt-and-braces LD_LIBRARY_PATH. TF 2.18+ does auto-discovery of
    # `nvidia-*` packages in site-packages at import time; this env is
    # for anything that calls a native lib outside that path
    # (subprocesses, ldd inspections, debugging). debian_slim default
    # site-packages is `/usr/local/lib/python3.13/site-packages`.
    .env({
        "LD_LIBRARY_PATH": ":".join([
            "/usr/local/lib/python3.13/site-packages/nvidia/cublas/lib",
            "/usr/local/lib/python3.13/site-packages/nvidia/cuda_cupti/lib",
            "/usr/local/lib/python3.13/site-packages/nvidia/cuda_nvrtc/lib",
            "/usr/local/lib/python3.13/site-packages/nvidia/cuda_runtime/lib",
            "/usr/local/lib/python3.13/site-packages/nvidia/cudnn/lib",
            "/usr/local/lib/python3.13/site-packages/nvidia/cufft/lib",
            "/usr/local/lib/python3.13/site-packages/nvidia/curand/lib",
            "/usr/local/lib/python3.13/site-packages/nvidia/cusolver/lib",
            "/usr/local/lib/python3.13/site-packages/nvidia/cusparse/lib",
            "/usr/local/lib/python3.13/site-packages/nvidia/nccl/lib",
            "/usr/local/lib/python3.13/site-packages/nvidia/nvjitlink/lib",
        ]),
    })
    # Bundle the repo source into the image once. Volumes still carry
    # warehouse + models per-run.
    .add_local_dir(str(_REPO_ROOT), remote_path="/repo", ignore=_ignore_path)
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
    # Weekly retrain trigger — Sunday 03:00 UTC (~05:00 PL). Conservative
    # default; bump to daily ("0 3 * * *") in the UI when you trust the
    # pipeline. Each fire costs ~$0.30-0.60 on T4.
    schedule=modal.Cron("0 3 * * 0"),
)
def run(
    skip_rl: bool = True,
    skip_backtest: bool = True,
    skip_bayes: bool = True,
    epochs: int = 50,
    symbol: str = "GC=F",
):
    """Mirror of `train_all.py` invocation, executed on Modal infrastructure.

    train_all.py supports: --skip-rl, --skip-backtest, --skip-bayes,
    --epochs N, --rl-episodes N, --symbol <ticker>. There is NO per-voter
    skip flag (LSTM and XGB are always trained together unless backtest
    pieces are skipped).
    """
    import subprocess
    import sys

    cmd = [sys.executable, "/repo/train_all.py",
           "--symbol", symbol, "--epochs", str(epochs)]
    if skip_rl:
        cmd.append("--skip-rl")
    if skip_backtest:
        cmd.append("--skip-backtest")
    if skip_bayes:
        cmd.append("--skip-bayes")

    print(f"[modal_train] running: {' '.join(cmd)}")
    # Stream stdout/stderr live so failures surface in the local terminal
    # instead of getting hidden behind `subprocess.CalledProcessError`.
    result = subprocess.run(
        cmd,
        env={**os.environ, "PYTHONPATH": "/repo", "PYTHONUNBUFFERED": "1"},
    )
    if result.returncode != 0:
        print(f"\n[modal_train] FAILED — exit code {result.returncode}\n"
              f"  command: {' '.join(cmd)}\n"
              f"  cwd: /repo\n"
              "  Inspect the lines above this for the real traceback.")
        raise SystemExit(result.returncode)

    # train_all.py writes via relative `models/...` paths — subprocess
    # cwd is `/`, so those land directly inside the /models Volume mount.
    # The earlier "copy /repo/models/* → /models/" loop here was a bug:
    # because models/ was bundled into the image, the loop kept clobbering
    # freshly-trained weights with the stale bundle copies. We now exclude
    # `models` from the bundle entirely (see _IGNORE_DIRS) and let the
    # trainer write to the volume natively.
    try:
        models_volume.commit()
        print("[modal_train] /models volume committed")
    except Exception as e:
        print(f"[modal_train] volume.commit() warning: {e}")


@app.function(
    gpu="T4",
    timeout=300,    # 5 min hard cap — diagnostic should be < 60 s
)
def gpu_diagnostic() -> dict:
    """Fast GPU sanity check — prints what TF sees and runs a tiny matmul.

    Run via `modal run tools/modal_train.py::gpu_check`. Use this BEFORE
    every full training run when the image stack changes, and any time
    a new TF / CUDA / cuDNN combination is introduced. Cheap (~30 s
    cold start, ~10 s warm) so iterating on image config is painless.

    Returns a dict with the structured findings so the caller can assert
    on them in CI / wrapper scripts later.
    """
    import os
    import platform
    import subprocess
    import sys
    import time

    findings: dict = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "ld_library_path": os.environ.get("LD_LIBRARY_PATH", "<unset>"),
    }

    print("=" * 72)
    print(f"GPU diagnostic — Python {findings['python']} on {findings['platform']}")
    print("=" * 72)

    # 1. nvidia-smi — confirms the host actually exposes a CUDA device
    print("\n[1/5] nvidia-smi")
    try:
        smi = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        )
        if smi.returncode == 0:
            findings["nvidia_smi"] = smi.stdout.strip()
            print(f"  OK: {smi.stdout.strip()}")
        else:
            findings["nvidia_smi"] = f"FAILED rc={smi.returncode}: {smi.stderr.strip()}"
            print(f"  FAIL: {findings['nvidia_smi']}")
    except FileNotFoundError:
        findings["nvidia_smi"] = "nvidia-smi not on PATH"
        print(f"  FAIL: {findings['nvidia_smi']}")
    except Exception as e:
        findings["nvidia_smi"] = f"error: {e!r}"
        print(f"  FAIL: {findings['nvidia_smi']}")

    # 2. site-packages/nvidia/* — confirms the [and-cuda] extras shipped
    print("\n[2/5] tensorflow[and-cuda] — site-packages/nvidia/*")
    try:
        site_dir = next(
            (p for p in sys.path if p.endswith("site-packages")),
            None,
        )
        if site_dir:
            nv_dir = os.path.join(site_dir, "nvidia")
            if os.path.isdir(nv_dir):
                libs = sorted(os.listdir(nv_dir))
                findings["nvidia_pkgs"] = libs
                print(f"  OK ({len(libs)} pkgs): {', '.join(libs)}")
            else:
                findings["nvidia_pkgs"] = f"missing dir: {nv_dir}"
                print(f"  FAIL: {findings['nvidia_pkgs']}")
        else:
            findings["nvidia_pkgs"] = "no site-packages on sys.path"
            print(f"  FAIL: {findings['nvidia_pkgs']}")
    except Exception as e:
        findings["nvidia_pkgs"] = f"error: {e!r}"
        print(f"  FAIL: {findings['nvidia_pkgs']}")

    # 3. Import TF, capture init warnings — first import is the moment of
    #    truth for cuDNN / CUDA library version compatibility.
    print("\n[3/5] tensorflow import")
    t_import_start = time.time()
    try:
        import tensorflow as tf  # noqa: PLC0415
        findings["tf_version"] = tf.__version__
        findings["tf_import_sec"] = round(time.time() - t_import_start, 2)
        print(f"  OK: tf={tf.__version__} (imported in {findings['tf_import_sec']} s)")
    except Exception as e:
        findings["tf_version"] = None
        findings["tf_import_error"] = repr(e)
        print(f"  FAIL: {e!r}")
        return findings

    # 4. tf.config.list_physical_devices('GPU') — the canonical TF check
    print("\n[4/5] tf.config.list_physical_devices('GPU')")
    try:
        gpus = tf.config.list_physical_devices("GPU")
        findings["tf_gpus"] = [str(g) for g in gpus]
        if gpus:
            print(f"  OK: {len(gpus)} GPU(s): {findings['tf_gpus']}")
        else:
            print("  FAIL: TF sees zero GPUs (would fall back to CPU)")
    except Exception as e:
        findings["tf_gpus"] = None
        findings["tf_gpus_error"] = repr(e)
        print(f"  FAIL: {e!r}")

    # 5. Tiny GPU compute — proves end-to-end CUDA path actually works.
    #    A pass on 4) but fail here means cuDNN missing / version skew.
    print("\n[5/5] GPU matmul")
    try:
        if not findings.get("tf_gpus"):
            findings["gpu_matmul"] = "skipped (no GPU)"
            print("  SKIP (no GPU)")
        else:
            with tf.device("/GPU:0"):
                a = tf.random.normal((512, 512))
                b = tf.random.normal((512, 512))
                t0 = time.time()
                c = tf.matmul(a, b)
                _ = c.numpy()  # force sync
                elapsed_ms = round((time.time() - t0) * 1000, 2)
            findings["gpu_matmul"] = f"OK ({elapsed_ms} ms)"
            print(f"  OK: 512×512 matmul in {elapsed_ms} ms on /GPU:0")
    except Exception as e:
        findings["gpu_matmul"] = f"error: {e!r}"
        print(f"  FAIL: {e!r}")

    print("\n" + "=" * 72)
    print(f"VERDICT: TF GPU is {'OPERATIONAL ✓' if findings.get('tf_gpus') and 'OK' in str(findings.get('gpu_matmul', '')) else 'BROKEN ✗'}")
    print("=" * 72)
    return findings


@app.local_entrypoint()
def gpu_check():
    """Run gpu_diagnostic and pretty-print the result. Cheap (~30-60 s
    cold start). Use it as the first step whenever the image stack
    changes, before kicking off a full retrain.

      modal run tools/modal_train.py::gpu_check
    """
    findings = gpu_diagnostic.remote()
    print("\n--- structured findings ---")
    import json as _json
    print(_json.dumps(findings, indent=2, default=str))


@app.local_entrypoint()
def main(
    skip_rl: bool = True,
    skip_backtest: bool = True,
    skip_bayes: bool = True,
    epochs: int = 10,        # cheap default — bump for real runs
    symbol: str = "GC=F",
):
    """Local CLI hook. Examples:

      # Cheap smoke test (10 epochs, no RL, no backtest, no bayes)
      modal run tools/modal_train.py::main --epochs 10

      # Realistic LSTM retrain (50 epochs, ~30-45 min on T4)
      modal run tools/modal_train.py::main --epochs 50

      # Full deal (with RL + backtest + bayes; long, expensive)
      modal run tools/modal_train.py::main --no-skip-rl --no-skip-backtest --no-skip-bayes
    """
    run.remote(
        skip_rl=skip_rl, skip_backtest=skip_backtest, skip_bayes=skip_bayes,
        epochs=epochs, symbol=symbol,
    )


if __name__ == "__main__":
    print(__doc__)
    print("\nUsage: modal run tools/modal_train.py::main [--skip-lstm] [--skip-rl] [--skip-xgb]")
