"""
api/routers/scanner.py — Background scanner control endpoints.

The scanner uses a file-based pause flag (`data/SCANNER_PAUSED`) read by
`_background_scanner()` in `api/main.py`. These endpoints expose the
flag to the frontend so the operator can pause/resume from the UI
(Cmd+K palette → "Pause scanner") without dropping into a shell.

Distinct from `risk.halt/resume` which kills *trading*; pausing the
scanner only stops *new entries* — open positions still resolve and
the dashboard keeps refreshing.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException

from src.core.logger import logger

router = APIRouter()

# Pause flag file — must match the path in api/main.py:_background_scanner
_PAUSE_FLAG = os.path.join("data", "SCANNER_PAUSED")


def _read_flag_state() -> dict:
    """Single source of truth for current pause state."""
    if not os.path.exists(_PAUSE_FLAG):
        return {"paused": False, "reason": None, "since": None}
    reason = None
    since = None
    try:
        with open(_PAUSE_FLAG, "r", encoding="utf-8") as f:
            raw = f.read().strip()
            reason = raw or None
        st = os.stat(_PAUSE_FLAG)
        since = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
    except Exception as e:
        logger.warning(f"[scanner] could not read pause flag content: {e}")
    return {"paused": True, "reason": reason, "since": since}


@router.get(
    "/status",
    summary="Scanner pause status",
    description="Returns whether the background scanner is paused and the reason.",
)
async def scanner_status():
    return _read_flag_state()


@router.post(
    "/pause",
    summary="Pause the background scanner",
    description=(
        "Creates `data/SCANNER_PAUSED`. The background loop will skip cycles "
        "until the flag is removed. Open trade resolution and dashboard "
        "fetches continue — only new entries are blocked."
    ),
)
async def scanner_pause(reason: str | None = Body(default=None, embed=True)):
    text = reason or "manual pause via API"
    try:
        os.makedirs(os.path.dirname(_PAUSE_FLAG), exist_ok=True)
        with open(_PAUSE_FLAG, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception as e:
        logger.error(f"[scanner] pause failed: {e}")
        raise HTTPException(status_code=500, detail=f"could not create pause flag: {e}")
    logger.warning(f"📡 [scanner] PAUSED via API — reason: {text}")
    return {"ok": True, **_read_flag_state()}


@router.get(
    "/peek",
    summary="Scanner diagnostic snapshot — what would the scanner see right now",
    description=(
        "Read-only ad-hoc indicators on the latest N bars. No SMC scoring, "
        "no ML inference, no DB writes — just the technical indicators a "
        "human looks at when answering 'why no trade today?'. "
        "Returns ATR(14), RSI(14), EMA-20 distance, 14-bar high/low, "
        "20-bar volatility."
    ),
)
async def scanner_peek(symbol: str = "XAU/USD", interval: str = "15m", count: int = 100):
    try:
        import numpy as _np
        import pandas as _pd
        from src.data.data_sources import get_provider
        provider = get_provider()
        df = await asyncio.to_thread(provider.get_candles, symbol, interval, count)
        if df is None or len(df) < 20:
            n = 0 if df is None else len(df)
            raise HTTPException(status_code=503, detail=f"insufficient bars ({n})")
        # Normalize timestamp column — providers vary between 'time'/'timestamp'/'datetime'.
        ts_col = next((c for c in ("timestamp", "datetime", "time", "date") if c in df.columns), None)
        if ts_col is None and df.index.name in ("timestamp", "datetime", "time", "date"):
            df = df.reset_index()
            ts_col = next((c for c in ("timestamp", "datetime", "time", "date") if c in df.columns), None)
        if ts_col is None:
            raise HTTPException(status_code=500, detail=f"candles missing timestamp column. cols={list(df.columns)}")
        df = df.rename(columns={ts_col: "ts"}).sort_values("ts").reset_index(drop=True)
        close = df["close"].astype(float).to_numpy()
        high  = df["high"].astype(float).to_numpy()
        low   = df["low"].astype(float).to_numpy()
        # ATR(14) — Wilder, ewm alpha=1/14
        prev_close = _np.concatenate([[close[0]], close[:-1]])
        tr = _np.maximum.reduce([high - low, _np.abs(high - prev_close), _np.abs(low - prev_close)])
        atr = float(_pd.Series(tr).ewm(alpha=1/14, adjust=False).mean().iloc[-1])
        # RSI(14) — pandas_ta-equivalent (ewm of gains / losses)
        delta = _pd.Series(close).diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        rs = (gain / (loss + 1e-10))
        rsi = float(100 - 100 / (1 + rs.iloc[-1]))
        # EMA-20 distance
        ema20 = _pd.Series(close).ewm(span=20, adjust=False).mean()
        ema_distance_pct = float((close[-1] - ema20.iloc[-1]) / ema20.iloc[-1] * 100)
        # Rolling high/low (14)
        hi14 = float(_pd.Series(high).rolling(14).max().iloc[-1])
        lo14 = float(_pd.Series(low).rolling(14).min().iloc[-1])
        # 20-bar volatility (std of pct change)
        vol20 = float(_pd.Series(close).pct_change().rolling(20).std().iloc[-1])
        # Trend bias from EMA distance + RSI
        if ema_distance_pct > 0.2 and rsi > 55:
            bias = "bullish"
        elif ema_distance_pct < -0.2 and rsi < 45:
            bias = "bearish"
        else:
            bias = "neutral"

        last_ts = df["ts"].iloc[-1]
        return {
            "symbol": symbol,
            "interval": interval,
            "bars_used": len(df),
            "last_bar": {
                "ts": str(last_ts),
                "close": float(close[-1]),
                "high":  float(high[-1]),
                "low":   float(low[-1]),
            },
            "indicators": {
                "atr_14":           round(atr, 4),
                "rsi_14":           round(rsi, 2),
                "ema_20":           round(float(ema20.iloc[-1]), 4),
                "ema_distance_pct": round(ema_distance_pct, 4),
                "high_14":          round(hi14, 4),
                "low_14":           round(lo14, 4),
                "volatility_20":    round(vol20, 6),
            },
            "bias": bias,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"scanner/peek error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/peek-all",
    summary="Multi-TF diagnostic snapshot — all 5 timeframes in one call",
    description=(
        "Returns the same indicator set as /peek but for every TF in the "
        "scanner cascade (5m, 15m, 30m, 1h, 4h). Useful for the 'is XAU "
        "in agreement across timeframes?' check. ~5 provider calls — "
        "skip the rate-limit budget if you're poll-spamming. Cache TTL "
        "30 s."
    ),
)
async def scanner_peek_all(symbol: str = "XAU/USD", count: int = 100):
    intervals = ("5m", "15m", "30m", "1h", "4h")
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}
    # Run sequentially — provider already caches recent candles, so 5
    # back-to-back calls usually share the same fetch round.
    for tf in intervals:
        try:
            results[tf] = await scanner_peek(symbol=symbol, interval=tf, count=count)
        except HTTPException as he:
            errors[tf] = f"{he.status_code}: {he.detail}"
        except Exception as e:
            errors[tf] = str(e)
    # Aggregate bias — multi-TF agreement signal
    biases = [r.get("bias") for r in results.values()]
    bull_count = sum(1 for b in biases if b == "bullish")
    bear_count = sum(1 for b in biases if b == "bearish")
    if bull_count >= 4:
        agreement = "strong_bull"
    elif bear_count >= 4:
        agreement = "strong_bear"
    elif bull_count >= 3:
        agreement = "lean_bull"
    elif bear_count >= 3:
        agreement = "lean_bear"
    else:
        agreement = "mixed"
    return {
        "symbol": symbol,
        "by_tf": results,
        "errors": errors,
        "agreement": {
            "label": agreement,
            "bull_count": bull_count,
            "bear_count": bear_count,
            "neutral_count": len(biases) - bull_count - bear_count,
            "tfs_ok": list(results.keys()),
            "tfs_failed": list(errors.keys()),
        },
    }


@router.post(
    "/resume",
    summary="Resume the background scanner",
    description="Deletes `data/SCANNER_PAUSED`. No-op if the flag is absent.",
)
async def scanner_resume():
    if not os.path.exists(_PAUSE_FLAG):
        return {"ok": True, "was_paused": False, **_read_flag_state()}
    try:
        os.remove(_PAUSE_FLAG)
    except Exception as e:
        logger.error(f"[scanner] resume failed: {e}")
        raise HTTPException(status_code=500, detail=f"could not remove pause flag: {e}")
    logger.info("📡 [scanner] RESUMED via API — pause flag removed")
    return {"ok": True, "was_paused": True, **_read_flag_state()}
