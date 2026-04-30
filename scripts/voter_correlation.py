"""voter_correlation.py — Empirical voter diversity audit for the 7-voter ensemble.

Hypothesis (architectural): the 4 ML voters that share the same 34-feature
vector from `compute_features` (xgb, lstm, attention, decompose) should produce
highly correlated outputs (pairwise Pearson r > 0.85), proving they are
"one model with vibrato" rather than a real ensemble. v2_xgb uses 62-feature
features_v2 vector and dqn consumes raw close prices, so those two should be
the genuinely independent contributors.

This script measures the truth.

USAGE
    .venv/Scripts/python.exe scripts/voter_correlation.py

OUTPUTS
    reports/2026-04-29_voter_correlation.csv  (full pairwise matrices)
    reports/2026-04-29_voter_correlation.md   (human-readable verdict)

DESIGN NOTES
- Reads from data/historical/XAU_USD/5min.parquet and USD_JPY/15min.parquet
  (15min reindexed forward-fill onto 5min grid since USD_JPY/5min.parquet
  does not exist).
- Held-out window = last 30 days of warehouse data, with 60-bar warmup.
- Sliding stride 6 bars (= every 30 min) → ~1440 anchor bars per 30-day window.
  Cuts compute from ~10 min to ~1-2 min while preserving ample sample size.
- DISABLE_CALIBRATION=1 (kill-switch in model_calibration.py) so the negative
  Platt bug from 2026-04-29 audit does not skew comparison.
- QUANT_BACKTEST_MODE=1 to short-circuit news/macro_quotes live API hooks.
- _fetch_live_usdjpy in ensemble_models is monkey-patched to return the
  pre-sliced USDJPY view (up to anchor ts) — keeps inference path realistic
  while staying offline.
- Voters that fail to load or return None are reported and skipped (not fatal).
"""
from __future__ import annotations

import os
import sys
import time
import json
import warnings
from pathlib import Path
from typing import Optional

# ── Env gates BEFORE any project import ────────────────────────────────
os.environ["DISABLE_CALIBRATION"] = "1"
os.environ["QUANT_BACKTEST_MODE"] = "1"
os.environ.setdefault("ONNX_FORCE_CPU", "1")  # avoid GPU contention with running scanner
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
warnings.filterwarnings("ignore")

# Force UTF-8 on stdout to avoid cp1252 crashes on Windows console.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

import numpy as np
import pandas as pd

# Project root on sys.path so `from src.*` works when invoked directly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Project imports ────────────────────────────────────────────────────
from src.ml import ensemble_models as em  # noqa: E402
from src.ml.ensemble_models import (  # noqa: E402
    predict_lstm_direction,
    predict_xgb_direction,
    predict_v2_xgb_direction,
    predict_dqn_action,
)
from src.ml.attention_model import predict_attention  # noqa: E402
# decompose voter dropped 2026-04-30 (P2.5 — file deleted; centered
# convolution leak per audit P1.1). Stubbed below for back-compat.
predict_decompose = lambda *a, **kw: None  # noqa: E731
from src.ml.transformer_model import predict_deeptrans  # noqa: E402
from src.analysis import compute as _compute_mod  # for monkey-patch
from src.analysis.compute import compute_features as _orig_compute_features, FEATURE_COLS  # noqa: E402


# ── Compute-features sanitization patch ────────────────────────────────
# `xau_usdjpy_corr_20` produces ±inf when forward-filled USDJPY has flat
# 20-bar windows (zero variance → corr divide-by-zero). This Inf propagates
# into MinMaxScaler.transform → all-Inf scaled features → predict returns None.
# Sanitize the dataframe by clipping/replacing non-finite values with 0.
# Also patch the module-level reference so `predict_attention` sees it
# via its `from src.analysis.compute import compute_features` rebinding
# trick (re-import at function scope reads the module attr live).
def _clean_compute_features(df, use_cache=True, usdjpy_df=None):
    out = _orig_compute_features(df, use_cache=use_cache, usdjpy_df=usdjpy_df)
    # Replace Inf with NaN, then NaN with 0 only on FEATURE_COLS to keep
    # OHLCV pristine. Cheaper than .replace([inf,-inf], 0) on the whole frame.
    for c in FEATURE_COLS:
        if c in out.columns:
            col = out[c]
            if not np.isfinite(col.values).all():
                out[c] = col.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


_compute_mod.compute_features = _clean_compute_features
# attention_model + decompose_model + transformer_model rebind at function
# scope (`from src.analysis.compute import compute_features`), so we also
# rewrite their module references after import:
import src.ml.attention_model as _am_mod  # noqa: E402
import src.ml.transformer_model as _tm_mod  # noqa: E402
for _m in (_am_mod, _tm_mod):
    if hasattr(_m, "compute_features"):
        _m.compute_features = _clean_compute_features
# ensemble_models calls compute_features inside _compute_ensemble_features
# via `from src.analysis.compute import compute_features` at module top:
em.compute_features = _clean_compute_features


# ── Force XGB to use sklearn pkl path (Treelite returns (1,1,1) which
# the production reader can't decode). Pre-populate the cache so _load_xgb
# returns sklearn even when xgb_treelite.dll is present.
def _force_sklearn_xgb():
    try:
        import pickle
        pkl = ROOT / "models" / "xgb.pkl"
        if not pkl.exists():
            return False
        with open(pkl, "rb") as f:
            model = pickle.load(f)
        em._models_cache["xgb"] = ("sklearn", model)
        em._models_loaded["xgb"] = True
        em._models_mtime["xgb"] = max(
            em._file_mtime(str(ROOT / "models" / "xgb.pkl")),
            em._file_mtime(str(ROOT / "models" / "xgb.onnx")),
            em._file_mtime(str(ROOT / "models" / "xgb_treelite.dll")),
        ) + 1.0  # prevent _invalidate_if_stale from undoing our pin
        return True
    except Exception as e:
        print(f"[force_sklearn_xgb] FAILED: {e}")
        return False

# ── Config ─────────────────────────────────────────────────────────────
XAU_PATH = ROOT / "data" / "historical" / "XAU_USD" / "5min.parquet"
USDJPY_PATH = ROOT / "data" / "historical" / "USD_JPY" / "15min.parquet"
REPORT_DIR = ROOT / "reports"
TODAY = "2026-04-29"
CSV_PATH = REPORT_DIR / f"{TODAY}_voter_correlation.csv"
MD_PATH = REPORT_DIR / f"{TODAY}_voter_correlation.md"

HOLDOUT_DAYS = 30
WARMUP_BARS = 200       # enough for ATR/EMA/RSI/ADX warmup + LSTM seq_len 60
LOOKBACK_BARS = 400     # bars of history fed to each predictor at every anchor
STRIDE_BARS = 6         # every 30 min on 5m grid
VOTERS = ["xgb", "lstm", "attention", "deeptrans", "v2_xgb", "dqn"]  # decompose dropped 2026-04-30


# ── Data prep ──────────────────────────────────────────────────────────
def load_warehouse() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (xau_5m, usdjpy_5m_aligned). Both indexed by tz-aware datetime."""
    xau = pd.read_parquet(XAU_PATH)
    if "datetime" in xau.columns:
        xau = xau.set_index("datetime")
    xau = xau.sort_index()

    uj = pd.read_parquet(USDJPY_PATH)
    if "datetime" in uj.columns:
        uj = uj.set_index("datetime")
    uj = uj.sort_index()
    # Reindex onto the XAU 5-min grid via forward-fill. USDJPY moves slowly
    # enough at 15-min granularity that this is benign for z-score / ret_5
    # / corr_20 features.
    uj_5m = uj.reindex(xau.index, method="ffill")
    return xau, uj_5m


def slice_holdout(xau: pd.DataFrame, days: int) -> pd.DataFrame:
    end = xau.index[-1]
    start = end - pd.Timedelta(days=days)
    return xau.loc[start:end]


# ── Voter wrappers ─────────────────────────────────────────────────────
class UsdJpyContext:
    """Monkey-patches ensemble_models._fetch_live_usdjpy to feed a sliced
    historical USDJPY view aligned to the anchor bar. Avoids any live API
    call while preserving the inference path the production scanner uses.

    Use as a context manager so the patch unwinds even if the loop crashes."""

    def __init__(self, usdjpy_full: pd.DataFrame):
        self._uj = usdjpy_full
        self._anchor_ts: Optional[pd.Timestamp] = None
        self._original = None

    def set_anchor(self, ts: pd.Timestamp) -> None:
        self._anchor_ts = ts

    def __enter__(self):
        self._original = em._fetch_live_usdjpy

        def _patched(limit: int = 200) -> Optional[pd.DataFrame]:
            if self._anchor_ts is None:
                return None
            window = self._uj.loc[: self._anchor_ts].tail(limit)
            if len(window) < 20:
                return None
            return window.copy()

        em._fetch_live_usdjpy = _patched
        return self

    def __exit__(self, *exc):
        em._fetch_live_usdjpy = self._original


def safe_call(fn, *args, **kwargs) -> Optional[float]:
    try:
        out = fn(*args, **kwargs)
        if out is None:
            return None
        return float(out)
    except Exception:
        return None


def predict_dqn_long_bias(df: pd.DataFrame) -> Optional[float]:
    """Convert DQN action to 0-1 LONG-bias signal (matches run_ensemble logic
    in ensemble_models.py:1057)."""
    closes = df["close"].tail(20).values
    if len(closes) < 20:
        return None
    res = predict_dqn_action(closes, balance=1.0, position=0)
    if res is None:
        return None
    action = res.get("action")
    return {0: 0.5, 1: 0.8, 2: 0.2}.get(action, 0.5)


def collect_voter_predictions(df_window: pd.DataFrame, uj_ctx: UsdJpyContext,
                              anchor_ts: pd.Timestamp,
                              available: dict[str, bool]) -> dict[str, Optional[float]]:
    """Run all voters on a single anchor bar's lookback window."""
    uj_ctx.set_anchor(anchor_ts)
    uj_window = uj_ctx._uj.loc[: anchor_ts].tail(LOOKBACK_BARS)

    out: dict[str, Optional[float]] = {}
    out["xgb"] = safe_call(predict_xgb_direction, df_window) if available["xgb"] else None
    out["lstm"] = safe_call(predict_lstm_direction, df_window) if available["lstm"] else None
    out["attention"] = safe_call(predict_attention, df_window, usdjpy_df=uj_window) if available["attention"] else None
    out["decompose"] = safe_call(predict_decompose, df_window) if available["decompose"] else None
    out["deeptrans"] = safe_call(predict_deeptrans, df_window) if available["deeptrans"] else None
    out["v2_xgb"] = safe_call(predict_v2_xgb_direction, df_window) if available["v2_xgb"] else None
    out["dqn"] = predict_dqn_long_bias(df_window) if available["dqn"] else None
    return out


# ── Voter availability probe ───────────────────────────────────────────
def probe_voters(df_warmup: pd.DataFrame, uj_full: pd.DataFrame) -> dict[str, bool]:
    """Run each voter once on a warmup window. If it returns a finite float,
    mark it available; else log + skip."""
    print("[probe] testing voter availability ...")
    avail = {v: False for v in VOTERS}
    with UsdJpyContext(uj_full) as ctx:
        ctx.set_anchor(df_warmup.index[-1])
        uj_w = uj_full.loc[: df_warmup.index[-1]].tail(LOOKBACK_BARS)
        # Test each in isolation
        try:
            r = predict_xgb_direction(df_warmup); avail["xgb"] = r is not None
            print(f"  xgb         -> {r}")
        except Exception as e:
            print(f"  xgb         -> ERROR: {e}")
        try:
            r = predict_lstm_direction(df_warmup); avail["lstm"] = r is not None
            print(f"  lstm        -> {r}")
        except Exception as e:
            print(f"  lstm        -> ERROR: {e}")
        try:
            r = predict_attention(df_warmup, usdjpy_df=uj_w); avail["attention"] = r is not None
            print(f"  attention   -> {r}")
        except Exception as e:
            print(f"  attention   -> ERROR: {e}")
        try:
            r = predict_decompose(df_warmup); avail["decompose"] = r is not None
            print(f"  decompose   -> {r}")
        except Exception as e:
            print(f"  decompose   -> ERROR: {e}")
        try:
            r = predict_deeptrans(df_warmup); avail["deeptrans"] = r is not None
            print(f"  deeptrans   -> {r}")
        except Exception as e:
            print(f"  deeptrans   -> ERROR: {e}")
        try:
            r = predict_v2_xgb_direction(df_warmup); avail["v2_xgb"] = r is not None
            print(f"  v2_xgb      -> {r}")
        except Exception as e:
            print(f"  v2_xgb      -> ERROR: {e}")
        try:
            r = predict_dqn_long_bias(df_warmup); avail["dqn"] = r is not None
            print(f"  dqn         -> {r}")
        except Exception as e:
            print(f"  dqn         -> ERROR: {e}")
    return avail


# ── Correlation analysis ───────────────────────────────────────────────
def pairwise_correlations(arr: np.ndarray, names: list[str]) -> dict:
    """Return pearson, spearman, agreement matrices. NaN-safe pairwise."""
    n_voters = arr.shape[1]
    pearson = np.full((n_voters, n_voters), np.nan)
    spearman = np.full((n_voters, n_voters), np.nan)
    agreement = np.full((n_voters, n_voters), np.nan)

    from scipy.stats import pearsonr, spearmanr  # local import to avoid hard dep noise

    for i in range(n_voters):
        for j in range(n_voters):
            ai, aj = arr[:, i], arr[:, j]
            mask = ~(np.isnan(ai) | np.isnan(aj))
            if mask.sum() < 30:
                continue
            xi, xj = ai[mask], aj[mask]
            # Pearson — handle constant columns
            if np.std(xi) < 1e-10 or np.std(xj) < 1e-10:
                pearson[i, j] = 1.0 if i == j else np.nan
            else:
                pearson[i, j] = float(pearsonr(xi, xj)[0])
            # Spearman
            try:
                rho = spearmanr(xi, xj).statistic
                spearman[i, j] = float(rho) if not np.isnan(rho) else np.nan
            except Exception:
                spearman[i, j] = np.nan
            # Direction agreement: both >0.5 or both <0.5
            di = (xi > 0.5).astype(int)
            dj = (xj > 0.5).astype(int)
            agreement[i, j] = float((di == dj).mean())

    return {
        "pearson": pd.DataFrame(pearson, index=names, columns=names),
        "spearman": pd.DataFrame(spearman, index=names, columns=names),
        "agreement": pd.DataFrame(agreement, index=names, columns=names),
    }


def effective_voters(pearson_df: pd.DataFrame, threshold: float = 0.85) -> int:
    """Eigenvalue-based effective dimensionality on the LOADED-voter
    submatrix only. NaN rows (skipped voters) inflate apparent rank — drop
    them before computing the participation ratio."""
    keep = [c for c in pearson_df.columns
            if not pearson_df.loc[c].isna().all()]
    if len(keep) <= 1:
        return len(keep)
    M = pearson_df.loc[keep, keep].values.astype(float).copy()
    M = np.nan_to_num(M, nan=0.0)
    np.fill_diagonal(M, 1.0)
    M = 0.5 * (M + M.T)
    try:
        eigvals = np.linalg.eigvalsh(M)
        eigvals = np.clip(eigvals, 0.0, None)
        if eigvals.sum() <= 0:
            return len(keep)
        # Participation ratio: (sum λ)^2 / sum(λ^2).
        eff = float((eigvals.sum() ** 2) / (eigvals ** 2).sum())
        return int(round(eff))
    except Exception:
        return len(keep)


def cluster_at_threshold(pearson_df: pd.DataFrame, thr: float) -> list[list[str]]:
    """Group voters via union-find on |r| >= thr edges."""
    names = list(pearson_df.index)
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, a in enumerate(names):
        for j, b in enumerate(names):
            if i >= j:
                continue
            v = pearson_df.iloc[i, j]
            if not np.isnan(v) and abs(v) >= thr:
                union(a, b)
    groups: dict[str, list[str]] = {}
    for n in names:
        r = find(n)
        groups.setdefault(r, []).append(n)
    return list(groups.values())


def top_pairs(df: pd.DataFrame, ascending: bool, k: int = 5) -> list[tuple[str, str, float]]:
    out: list[tuple[str, str, float]] = []
    names = list(df.index)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            v = df.iloc[i, j]
            if not np.isnan(v):
                out.append((names[i], names[j], float(v)))
    out.sort(key=lambda x: abs(x[2]), reverse=not ascending)
    return out[:k]


# ── Report writing ─────────────────────────────────────────────────────
def write_csv(corrs: dict, predictions: pd.DataFrame, n_anchors: int) -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    with open(CSV_PATH, "w", encoding="utf-8") as f:
        f.write(f"# voter_correlation report {TODAY}\n")
        f.write(f"# n_anchors={n_anchors} stride={STRIDE_BARS}bars holdout_days={HOLDOUT_DAYS}\n")
        f.write("\n## Pearson\n")
        corrs["pearson"].to_csv(f)
        f.write("\n## Spearman\n")
        corrs["spearman"].to_csv(f)
        f.write("\n## DirectionAgreement\n")
        corrs["agreement"].to_csv(f)


def _df_to_md(df: pd.DataFrame) -> str:
    """Manual markdown table — avoids tabulate dependency."""
    cols = list(df.columns)
    lines = []
    lines.append("| | " + " | ".join(str(c) for c in cols) + " |")
    lines.append("|" + "---|" * (len(cols) + 1))
    for idx, row in df.iterrows():
        cells = []
        for v in row.values:
            if isinstance(v, float):
                if np.isnan(v):
                    cells.append("nan")
                else:
                    cells.append(f"{v:.3f}")
            else:
                cells.append(str(v))
        lines.append(f"| {idx} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_md(corrs: dict, predictions: pd.DataFrame, available: dict[str, bool],
             n_anchors: int, missing_rates: dict[str, float]) -> None:
    pearson = corrs["pearson"]
    agreement = corrs["agreement"]

    worst = top_pairs(pearson.abs(), ascending=False, k=10)  # highest |r|
    best = top_pairs(pearson.abs(), ascending=True, k=10)    # lowest |r|

    eff_n = effective_voters(pearson, threshold=0.85)
    clusters_85 = cluster_at_threshold(pearson, 0.85)
    clusters_70 = cluster_at_threshold(pearson, 0.70)

    avail_voters = [v for v in VOTERS if available.get(v)]
    skipped = [v for v in VOTERS if not available.get(v)]

    avg_agree = agreement.where(~np.eye(len(agreement), dtype=bool)).stack().mean()

    lines = []
    lines.append(f"# Voter Correlation Audit — {TODAY}")
    lines.append("")
    lines.append("## Setup")
    lines.append(f"- Held-out window: last **{HOLDOUT_DAYS} days** of XAU/USD 5min warehouse")
    lines.append(f"- Anchor stride: every **{STRIDE_BARS} bars** (~30 min) → **{n_anchors} anchors**")
    lines.append(f"- Lookback per anchor: {LOOKBACK_BARS} bars")
    lines.append(f"- USDJPY: 15min reindexed forward-fill onto 5min grid")
    lines.append("- `DISABLE_CALIBRATION=1`, `QUANT_BACKTEST_MODE=1`, `ONNX_FORCE_CPU=1`")
    lines.append("")
    lines.append("## Voter availability")
    for v in VOTERS:
        status = "OK" if available.get(v) else "SKIPPED"
        miss = missing_rates.get(v, 1.0)
        lines.append(f"- `{v}`: {status} (None rate over anchors: {miss:.1%})")
    lines.append("")

    lines.append("## Pearson correlation matrix")
    lines.append("")
    lines.append(_df_to_md(pearson.round(3)))
    lines.append("")

    lines.append("## Spearman correlation matrix")
    lines.append("")
    lines.append(_df_to_md(corrs["spearman"].round(3)))
    lines.append("")

    lines.append("## Direction-agreement matrix (% bars with same >0.5/<0.5 verdict)")
    lines.append("")
    lines.append(_df_to_md((agreement * 100).round(1)))
    lines.append(f"- Mean off-diagonal agreement: **{avg_agree:.1%}**")
    lines.append("")

    lines.append("## Top **diversity** pairs (lowest |Pearson r| — these are real ensemble contributors)")
    for a, b, v in best:
        lines.append(f"- `{a}` ↔ `{b}` : r = {v:+.3f}")
    lines.append("")

    lines.append("## Top **redundancy** pairs (highest |Pearson r| — drop candidates)")
    for a, b, v in worst:
        lines.append(f"- `{a}` ↔ `{b}` : r = {v:+.3f}")
    lines.append("")

    lines.append("## Effective voter count")
    lines.append(f"- Loaded voters: **{len(avail_voters)}** of {len(VOTERS)}")
    lines.append(f"- Eigenvalue participation-ratio effective dimensionality: **~{eff_n}**")
    lines.append(f"- Clusters at |r| >= 0.85: {clusters_85}")
    lines.append(f"- Clusters at |r| >= 0.70: {clusters_70}")
    lines.append("")

    lines.append("## Verdict")
    if eff_n <= 3:
        lines.append(f"- **Severe redundancy.** Eigenvalue analysis says we have ~{eff_n} effective voters out of {len(avail_voters)} loaded.")
    elif eff_n <= len(avail_voters) - 2:
        lines.append(f"- **Moderate redundancy.** ~{eff_n} effective voters out of {len(avail_voters)} loaded.")
    else:
        lines.append(f"- **Diversity reasonable.** ~{eff_n} effective voters out of {len(avail_voters)} loaded — no strong drop case.")
    lines.append("")
    lines.append("Drop candidates are the redundancy-pair members that share the same input feature vector. "
                 "When two voters have |r| > 0.85 and consume identical features (compute_features 34-vector), "
                 "the more compute-expensive one (LSTM/Attention/Decompose vs XGB) is the drop target.")
    lines.append("")

    if skipped:
        lines.append(f"### Skipped voters (load failure or no signal): {skipped}")

    MD_PATH.write_text("\n".join(lines), encoding="utf-8")


# ── Main ───────────────────────────────────────────────────────────────
def main() -> int:
    REPORT_DIR.mkdir(exist_ok=True)

    # Force sklearn XGB (Treelite output shape (1,1,1) breaks the production
    # decoder; bug surface but not for this script to fix).
    print(f"[setup] forcing XGB sklearn path: {_force_sklearn_xgb()}")

    print(f"[load] reading {XAU_PATH.name} + {USDJPY_PATH.name}")
    xau_full, uj_full = load_warehouse()
    print(f"[load] xau range {xau_full.index[0]} -> {xau_full.index[-1]} ({len(xau_full)} bars)")

    holdout = slice_holdout(xau_full, HOLDOUT_DAYS)
    print(f"[holdout] {holdout.index[0]} -> {holdout.index[-1]} ({len(holdout)} bars)")

    # First anchor must have at least LOOKBACK_BARS of XAU history available
    # Use full xau as the source so warmup can extend into pre-holdout data.
    # Indices into xau_full of holdout bars:
    holdout_idx_loc = xau_full.index.searchsorted(holdout.index[0])
    last_loc = len(xau_full) - 1
    if holdout_idx_loc < LOOKBACK_BARS:
        print(f"[abort] insufficient warmup: need {LOOKBACK_BARS} pre-holdout bars, have {holdout_idx_loc}")
        return 1

    anchor_locs = list(range(holdout_idx_loc + WARMUP_BARS, last_loc + 1, STRIDE_BARS))
    print(f"[plan] {len(anchor_locs)} anchor bars (stride={STRIDE_BARS})")

    # Probe availability on the latest fully-warmed window
    probe_window = xau_full.iloc[last_loc - LOOKBACK_BARS + 1 : last_loc + 1].copy()
    available = probe_voters(probe_window, uj_full)
    avail_voters = [v for v in VOTERS if available.get(v)]
    print(f"[probe] available voters: {avail_voters}")
    if len(avail_voters) < 2:
        print("[abort] need >= 2 voters to compute pairwise correlations")
        return 1

    # ── Main loop ──
    rows: list[dict] = []
    t0 = time.time()
    with UsdJpyContext(uj_full) as ctx:
        for k, loc in enumerate(anchor_locs):
            window = xau_full.iloc[loc - LOOKBACK_BARS + 1 : loc + 1].copy()
            ts = window.index[-1]
            preds = collect_voter_predictions(window, ctx, ts, available)
            preds["_ts"] = ts
            rows.append(preds)
            if k % 50 == 0 and k > 0:
                elapsed = time.time() - t0
                eta = elapsed / k * (len(anchor_locs) - k)
                print(f"  [progress] {k}/{len(anchor_locs)} elapsed={elapsed:.0f}s eta={eta:.0f}s")

    print(f"[done] inference loop finished in {time.time() - t0:.1f}s")

    pred_df = pd.DataFrame(rows).set_index("_ts")
    arr = pred_df[VOTERS].values.astype(float)
    print(f"[matrix] {arr.shape}  None-rate per voter:")
    missing_rates = {}
    for v in VOTERS:
        nr = pred_df[v].isna().mean()
        missing_rates[v] = float(nr)
        print(f"  {v:10s}: {nr:.1%}")

    corrs = pairwise_correlations(arr, VOTERS)
    print("\n[Pearson]\n", corrs["pearson"].round(3))
    print("\n[Spearman]\n", corrs["spearman"].round(3))
    print("\n[Agreement]\n", corrs["agreement"].round(3))

    write_csv(corrs, pred_df, len(anchor_locs))
    write_md(corrs, pred_df, available, len(anchor_locs), missing_rates)
    print(f"\n[write] {CSV_PATH}")
    print(f"[write] {MD_PATH}")

    eff_n = effective_voters(corrs["pearson"], threshold=0.85)
    print(f"\n[verdict] effective voters (eigenvalue PR): ~{eff_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
