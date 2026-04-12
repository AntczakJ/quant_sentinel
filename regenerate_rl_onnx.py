#!/usr/bin/env python3
"""Regenerate models/rl_agent.onnx from models/rl_agent.keras.

Used after train_rl.py runs that predate the built-in ONNX export step.
Safe to run anytime — skips if ONNX is already newer than Keras model.
"""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

from src.analysis.compute import convert_keras_to_onnx

if __name__ == "__main__":
    keras_path = "models/rl_agent.keras"
    onnx_path = "models/rl_agent.onnx"
    if not os.path.exists(keras_path):
        raise SystemExit(f"Missing {keras_path}")
    result = convert_keras_to_onnx(keras_path, onnx_path)
    if result:
        print(f"OK: {onnx_path} ({os.path.getsize(onnx_path) / 1024:.1f} KB)")
    else:
        raise SystemExit("ONNX conversion failed — see logs")
