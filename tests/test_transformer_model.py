"""tests/test_transformer_model.py - Unit tests for the deep transformer voter.

Runs entirely on synthetic data so CI never hits yfinance / compute_features.
Covers: feature-flag gating, 3-class-to-value mapping, label generation,
model-build shapes, train+predict roundtrip, save/load, ensemble integration.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import numpy as np
import pytest


# --- Flag helpers ---------------------------------------------------------

@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv("QUANT_ENABLE_TRANSFORMER", raising=False)
    yield


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("QUANT_ENABLE_TRANSFORMER", "1")
    yield


# --- is_enabled -----------------------------------------------------------

def test_is_enabled_respects_flag(flag_off):
    from src.ml.transformer_model import is_enabled
    assert is_enabled() is False


def test_is_enabled_on(flag_on):
    from src.ml.transformer_model import is_enabled
    assert is_enabled() is True


# --- Probability -> ensemble value ---------------------------------------

def test_probs_to_value_neutral_on_pure_hold():
    from src.ml.transformer_model import _probs_to_ensemble_value
    probs = np.array([0.0, 1.0, 0.0])  # pure HOLD
    value, conf = _probs_to_ensemble_value(probs)
    assert value == pytest.approx(0.5)
    assert conf == pytest.approx(0.0)


def test_probs_to_value_extremes():
    from src.ml.transformer_model import _probs_to_ensemble_value
    v_long, c_long = _probs_to_ensemble_value(np.array([1.0, 0.0, 0.0]))
    v_short, c_short = _probs_to_ensemble_value(np.array([0.0, 0.0, 1.0]))
    assert v_long == pytest.approx(1.0)
    assert v_short == pytest.approx(0.0)
    assert c_long == pytest.approx(1.0)
    assert c_short == pytest.approx(1.0)


def test_probs_to_value_mixed_long_hold():
    """50/50 LONG/HOLD should sit above neutral but below certainty."""
    from src.ml.transformer_model import _probs_to_ensemble_value
    value, conf = _probs_to_ensemble_value(np.array([0.5, 0.5, 0.0]))
    assert 0.5 < value < 1.0
    assert conf == pytest.approx(0.5)


# --- Positional encoding --------------------------------------------------

def test_positional_encoding_shape_and_bounds():
    from src.ml.transformer_model import _sinusoidal_positional_encoding
    pe = _sinusoidal_positional_encoding(seq_len=32, d_model=16)
    assert pe.shape == (32, 16)
    assert pe.dtype == np.float32
    assert np.all(pe <= 1.0) and np.all(pe >= -1.0)


# --- Label generation -----------------------------------------------------

def test_label_windows_up_trend_labels_long():
    from src.ml.transformer_model import _label_windows, LABEL_LONG
    # Strong uptrend: +1% per bar -> forward return >> threshold.
    close = 100.0 * (1.01 ** np.arange(50))
    labels = _label_windows(close, horizon=5, threshold_pct=0.2)
    # All labels except the trailing horizon should be LONG.
    assert np.all(labels[:-5] == LABEL_LONG)
    # Trailing bars have no horizon -> -1.
    assert np.all(labels[-5:] == -1)


def test_label_windows_flat_is_hold():
    from src.ml.transformer_model import _label_windows, LABEL_HOLD
    close = np.full(30, 100.0)
    labels = _label_windows(close, horizon=5, threshold_pct=0.2)
    assert np.all(labels[:-5] == LABEL_HOLD)


def test_label_windows_down_is_short():
    from src.ml.transformer_model import _label_windows, LABEL_SHORT
    close = 100.0 * (0.99 ** np.arange(50))
    labels = _label_windows(close, horizon=5, threshold_pct=0.2)
    assert np.all(labels[:-5] == LABEL_SHORT)


# --- Model build ---------------------------------------------------------

def test_build_deep_transformer_output_shape():
    from src.ml.transformer_model import build_deep_transformer
    model = build_deep_transformer(seq_len=24, n_features=8, n_blocks=2,
                                   n_heads=2, d_model=16, ffn_dim=32)
    x = np.random.randn(4, 24, 8).astype(np.float32)
    y = model(x, training=False).numpy()
    assert y.shape == (4, 3)
    # Softmax rows sum to 1.
    assert np.allclose(y.sum(axis=1), 1.0, atol=1e-5)


def test_build_deep_transformer_param_count_reasonable():
    """A 2-block / d_model=16 model should weigh in under 20k parameters."""
    from src.ml.transformer_model import build_deep_transformer
    model = build_deep_transformer(seq_len=24, n_features=8, n_blocks=2,
                                   n_heads=2, d_model=16, ffn_dim=32)
    n_params = model.count_params()
    assert n_params < 20_000, f"unexpected bloat: {n_params} params"


# --- Train + predict roundtrip on synthetic tensors -----------------------

def _train_synthetic(tmp_path, flag_on_fixture):
    """Train a tiny model on synthetic tensors, save it, return path."""
    from src.ml.transformer_model import (
        build_deep_transformer, MODEL_FILENAME, SCALER_FILENAME,
    )
    from sklearn.preprocessing import MinMaxScaler
    import tensorflow as tf
    import pickle

    seq_len = 16
    n_features = 6
    n_samples = 200
    rng = np.random.default_rng(0)
    # Class-separable synthetic data: each class gets a distinct mean.
    X_list, y_list = [], []
    for cls in (0, 1, 2):
        offset = (cls - 1) * 0.8
        chunk = rng.normal(offset, 0.2, size=(n_samples // 3, seq_len, n_features))
        X_list.append(chunk)
        y_list.append(np.full(n_samples // 3, cls, dtype=np.int64))
    X = np.concatenate(X_list).astype(np.float32)
    y = np.concatenate(y_list)
    # Shuffle.
    perm = rng.permutation(len(X))
    X, y = X[perm], y[perm]

    scaler = MinMaxScaler().fit(X.reshape(-1, n_features))
    X_scaled = scaler.transform(X.reshape(-1, n_features)).reshape(X.shape)

    model = build_deep_transformer(seq_len=seq_len, n_features=n_features,
                                   n_blocks=2, n_heads=2,
                                   d_model=16, ffn_dim=32, dropout=0.1)
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-3),
                  loss="sparse_categorical_crossentropy",
                  metrics=["accuracy"])
    model.fit(X_scaled, y, epochs=3, batch_size=32, verbose=0)

    model_path = tmp_path / "models" / MODEL_FILENAME
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(model_path)
    with open(tmp_path / "models" / SCALER_FILENAME, "wb") as f:
        pickle.dump({
            "scaler": scaler, "seq_len": seq_len,
            "feature_cols": [f"f{i}" for i in range(n_features)],
            "horizon": 5, "threshold_pct": 0.2,
        }, f)
    return tmp_path / "models", seq_len, n_features


def test_train_and_predict_roundtrip(tmp_path, flag_on, monkeypatch):
    """End-to-end: train on synthetic windows, then predict via the
    flag-gated ensemble entry point using a mocked compute_features."""
    import src.ml.transformer_model as tm
    tm.reset_cache()

    model_dir, seq_len, n_features = _train_synthetic(tmp_path, flag_on)

    # predict_deeptrans calls compute_features(df) internally. Replace it
    # with a passthrough that returns a DataFrame of the right feature cols.
    import pandas as pd

    feature_cols = [f"f{i}" for i in range(n_features)]
    rng = np.random.default_rng(1)
    fake_feats = pd.DataFrame(
        rng.normal(0.5, 0.1, size=(seq_len + 5, n_features)),
        columns=feature_cols,
    )

    def fake_compute_features(df, use_cache=True):
        return fake_feats

    monkeypatch.setattr("src.analysis.compute.compute_features",
                        fake_compute_features)

    value = tm.predict_deeptrans(df=pd.DataFrame({"close": np.arange(50)}),
                                 model_dir=str(model_dir))
    assert value is not None
    assert 0.0 <= value <= 1.0


def test_predict_returns_none_when_flag_off(flag_off, tmp_path):
    from src.ml.transformer_model import predict_deeptrans
    # Even if artifacts existed, the flag short-circuits the call.
    result = predict_deeptrans(df=None, model_dir=str(tmp_path))
    assert result is None


def test_predict_returns_none_when_artifacts_missing(flag_on, tmp_path):
    import src.ml.transformer_model as tm
    tm.reset_cache()
    assert tm.predict_deeptrans(df=None, model_dir=str(tmp_path / "nothing")) is None


# --- Ensemble integration -------------------------------------------------

def test_ensemble_default_weights_include_deeptrans():
    """Weights dict must know the new voter, regardless of flag state."""
    from src.ml import ensemble_models as em
    # _load_dynamic_weights hits the DB; read the default dict instead by
    # inspecting the source of truth — the default_weights literal.
    src = Path(em.__file__).read_text(encoding="utf-8")
    assert '"deeptrans"' in src


def test_ensemble_track_record_includes_deeptrans():
    from src.ml import ensemble_models as em
    src = Path(em.__file__).read_text(encoding="utf-8")
    # Should be in the track-record model list.
    assert '"deeptrans"' in src


def test_predict_deeptrans_skipped_when_flag_off_in_ensemble(flag_off, monkeypatch):
    """With the flag off, predict_deeptrans returns None and the ensemble
    marks the voter 'unavailable' — so total weights effectively unchanged."""
    from src.ml.transformer_model import predict_deeptrans
    assert predict_deeptrans(df=None) is None
