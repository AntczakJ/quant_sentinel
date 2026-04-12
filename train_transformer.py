#!/usr/bin/env python3
"""train_transformer.py - Offline training for the deep transformer voter.

Fetches OHLCV via yfinance (rate-limit friendly combos), runs
`src.ml.transformer_model.train_deep_transformer`, and logs the run to
the training registry. Independent of production scanner state.

DO NOT launch this while the Optuna RL sweep is running - both compete
for TF / CPU and will slow each other significantly.

Usage
-----
  python train_transformer.py                          # 2y/1h XAU/USD
  python train_transformer.py --symbol EURUSD=X
  python train_transformer.py --epochs 80 --n-blocks 6 # larger/longer
  python train_transformer.py --force                  # ignore cache age
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import time
from pathlib import Path
from typing import Optional

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import pandas as pd
import yfinance as yf

from src.core.logger import logger
from src.ml.transformer_model import (
    train_deep_transformer, DEFAULT_SEQ_LEN, DEFAULT_N_BLOCKS,
    MODEL_NAME, MODEL_FILENAME,
)
from src.ml.training_registry import log_training_run


def _fetch(symbol: str) -> Optional[pd.DataFrame]:
    """Fetch OHLCV with yfinance fallbacks. Muted stdout to avoid cp1252 breakage."""
    for period, interval in (("2y", "1h"), ("1y", "1h"), ("5y", "1d"), ("2y", "1d")):
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                df = yf.Ticker(symbol).history(period=period, interval=interval)
            if df is None or len(df) < 200:
                continue
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
            df = df[keep].dropna().reset_index(drop=True)
            print(f"[data] {symbol}: {len(df)} bars @ {period}/{interval}")
            return df
        except Exception as e:
            logger.debug(f"[data] fetch {period}/{interval} failed: {e}")
            continue
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="GC=F")
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--seq-len", type=int, default=DEFAULT_SEQ_LEN)
    p.add_argument("--n-blocks", type=int, default=DEFAULT_N_BLOCKS)
    p.add_argument("--horizon", type=int, default=5,
                   help="forward bars used to label LONG/HOLD/SHORT")
    p.add_argument("--threshold-pct", type=float, default=0.2,
                   help="|forward return| below this is labeled HOLD")
    p.add_argument("--output-dir", default="models")
    args = p.parse_args()

    t0 = time.time()
    df = _fetch(args.symbol)
    if df is None:
        print(f"[fatal] could not fetch data for {args.symbol}", file=sys.stderr)
        return 2

    print(f"[train] {MODEL_NAME}: symbol={args.symbol} seq_len={args.seq_len} "
          f"n_blocks={args.n_blocks} horizon={args.horizon} "
          f"threshold_pct={args.threshold_pct} epochs={args.epochs}")

    model, val_acc = train_deep_transformer(
        df,
        model_dir=args.output_dir,
        seq_len=args.seq_len,
        n_blocks=args.n_blocks,
        horizon=args.horizon,
        threshold_pct=args.threshold_pct,
        epochs=args.epochs,
        batch_size=args.batch_size,
    )
    if model is None:
        print("[fatal] training returned no model (insufficient data?)",
              file=sys.stderr)
        return 3

    elapsed = time.time() - t0
    print(f"[train] done in {elapsed/60:.1f} min, val_acc={val_acc:.3f}")

    artifact = Path(args.output_dir) / MODEL_FILENAME
    try:
        log_training_run(
            model_type=MODEL_NAME,
            hyperparams={
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "seq_len": args.seq_len,
                "n_blocks": args.n_blocks,
                "horizon": args.horizon,
                "threshold_pct": args.threshold_pct,
            },
            data_signature={"symbol": args.symbol, "bars": len(df)},
            metrics={"val_accuracy": round(val_acc, 4),
                     "elapsed_min": round(elapsed / 60, 2)},
            artifact_path=str(artifact),
            notes="DeepTrans voter training",
        )
    except Exception as e:
        print(f"[registry] log failed: {e}", file=sys.stderr)

    # ONNX regen for DirectML inference (matches other voters' convention).
    try:
        from src.analysis.compute import convert_keras_to_onnx
        onnx_path = convert_keras_to_onnx(
            str(artifact),
            str(Path(args.output_dir) / "deeptrans.onnx"),
        )
        if onnx_path:
            print(f"[onnx] -> {onnx_path}")
    except Exception as e:
        print(f"[onnx] regen failed (non-fatal): {e}")

    print(f"\nTo enable in the ensemble:")
    print(f"    set QUANT_ENABLE_TRANSFORMER=1    (Windows)")
    print(f"    export QUANT_ENABLE_TRANSFORMER=1 (bash)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
