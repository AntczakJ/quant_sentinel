"""
scanner.py — autonomiczny skaner rynku i resolver transakcji.

Multi-Timeframe Cascade:
  - scan_market_task przeszukuje timeframe'y od najwyższego do najniższego:
    4h → 1h → 15m → 5m
  - Jeśli na danym TF znajdzie ważny setup, stawia trade i przerywa kaskadę.
  - Jeśli żaden TF nie daje sygnału, loguje heartbeat.

Naprawiono:
  - scan_market_task teraz zapisuje sygnały do scanner_signals
  - resolve_trades_task zapisuje powód i okoliczności przegranej do trades
  - processed_news jest teraz wypełniana przy alertach FVG/trend
"""

import hashlib
import requests
import time as _time

from src.core.logger import logger
from src.core.config import TOKEN, CHAT_ID, USER_PREFS, LAST_STATUS, LAST_STATUS_LOCK, TD_API_KEY
from src.trading.smc_engine import get_smc_analysis

# Kolejność kaskady: od najniższego do najwyższego timeframe'u
# (scalp-first: 5m/15m/30m jako primary, 1h/4h jako fallback premium setups)
SCAN_TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h"]

# Simulated-time cell. Production leaves this None and time-of-day filters fall
# back to wall-clock. The backtest harness rebinds it to a `[ts]` cell and
# updates the slot per cycle so filters reflect the simulated bar's hour.
_SIM_CURRENT_TS = None

TF_LABELS = {
    "4h": "H4",
    "1h": "H1",
    "30m": "M30",
    "15m": "M15",
    "5m": "M5",
}

def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def extract_factors(analysis: dict, direction: str) -> dict:
    """
    Wyciaga czynniki tradingowe z analizy SMC do zapisu w trades.factors.
    Uzywane przez background scanner, quick-trade, i log_trade.
    """
    factors = {}
    if not analysis:
        return factors

    # BOS
    if (direction == "LONG" and analysis.get('bos_bullish')) or \
       (direction == "SHORT" and analysis.get('bos_bearish')):
        factors['bos'] = 1

    # CHoCH
    if (direction == "LONG" and analysis.get('choch_bullish')) or \
       (direction == "SHORT" and analysis.get('choch_bearish')):
        factors['choch'] = 1

    # Order blocks — direction-filtered (2026-05-04 fix, mirrors
    # self_learning.py:428). Only count OBs whose type matches the
    # setup direction. Was the most likely root cause of ob_count -17.7pp
    # WR delta in factor_predictive analysis.
    ob_list = analysis.get('order_blocks', [])
    if ob_list:
        expected_type = 'bullish' if direction == 'LONG' else 'bearish'
        ob_dir_aligned = [b for b in ob_list if b.get('type') == expected_type]
        if ob_dir_aligned:
            factors['ob_count'] = min(len(ob_dir_aligned), 3)

    ob_main = analysis.get('ob_price')
    if ob_main and analysis.get('price'):
        if (direction == "LONG" and ob_main < analysis['price']) or \
           (direction == "SHORT" and ob_main > analysis['price']):
            factors['ob_main'] = 1

    # FVG
    fvg_type = analysis.get('fvg_type')
    if (direction == "LONG" and fvg_type == "bullish") or \
       (direction == "SHORT" and fvg_type == "bearish"):
        factors['fvg'] = 1

    # Liquidity Grab + MSS
    if analysis.get('liquidity_grab') and analysis.get('mss'):
        grab_dir = analysis.get('liquidity_grab_dir')
        if (direction == "LONG" and grab_dir == "bullish") or \
           (direction == "SHORT" and grab_dir == "bearish"):
            factors['grab_mss'] = 1

    # DBR/RBD
    dbr_type = analysis.get('dbr_rbd_type')
    if (direction == "LONG" and dbr_type == "DBR") or \
       (direction == "SHORT" and dbr_type == "RBD"):
        factors['dbr_rbd'] = 1

    # Macro
    macro = analysis.get('macro_regime')
    if (direction == "LONG" and macro == "zielony") or \
       (direction == "SHORT" and macro == "czerwony"):
        factors['macro'] = 1

    # RSI optimal zone
    rsi = analysis.get('rsi')
    if rsi:
        if direction == "LONG" and 40 <= rsi <= 50:
            factors['rsi_opt'] = 1
        elif direction == "SHORT" and 50 <= rsi <= 60:
            factors['rsi_opt'] = 1

    # RSI Divergence
    if (direction == "LONG" and analysis.get('rsi_div_bull')) or \
       (direction == "SHORT" and analysis.get('rsi_div_bear')):
        factors['rsi_divergence'] = 1

    # Engulfing
    eng = analysis.get('engulfing', False)
    if (direction == "LONG" and eng == 'bullish') or \
       (direction == "SHORT" and eng == 'bearish'):
        factors['engulfing'] = 1

    # Pin bar
    pb = analysis.get('pin_bar', False)
    if (direction == "LONG" and pb == 'bullish') or \
       (direction == "SHORT" and pb == 'bearish'):
        factors['pin_bar'] = 1

    # Ichimoku
    if direction == "LONG" and analysis.get('ichimoku_above_cloud'):
        factors['ichimoku_bull'] = 1
    elif direction == "SHORT" and analysis.get('ichimoku_below_cloud'):
        factors['ichimoku_bear'] = 1

    # Killzone / session
    if analysis.get('is_killzone'):
        factors['killzone'] = 1

    # 2026-05-04: OTE (Optimal Trade Entry) zone factor — Stage 1 logging.
    # ICT-style 50-79% retracement of dealing range. Highest expected WR
    # impact per 10-agent research (+5-8pp combined with FVG).
    # Stage 2 will enable scoring bonus after N=50+ trades validate edge.
    if direction == 'LONG' and analysis.get('in_ote_long'):
        factors['ote_zone'] = 1
    elif direction == 'SHORT' and analysis.get('in_ote_short'):
        factors['ote_zone'] = 1
    if analysis.get('in_ote_sweet'):
        factors['ote_sweet'] = 1  # 70.5% retracement (premium ICT level)

    # 2026-05-04: VWAP Stage 1 — log alignment factor (no scoring change).
    # Stage 2 will enable scoring bonus after N=50 trades validate edge.
    vwap_above = analysis.get('vwap_above')
    if vwap_above is not None:
        if (direction == 'LONG' and vwap_above) or \
           (direction == 'SHORT' and not vwap_above):
            factors['vwap_align'] = 1

    # 2026-05-04: Day-of-week as factor (logging + future weight).
    # Mon/Fri have known different WR. Log so factor_predictive can
    # quantify per-day WR delta on N=200+ cohort.
    try:
        from src.trading.sim_time import now_utc
        ts = now_utc()
        dow = ts.weekday()  # 0=Mon, 4=Fri
        if dow == 0:
            factors['dow_mon'] = 1
        elif dow == 4:
            factors['dow_fri'] = 1
        # Tue/Wed/Thu = no factor logged (baseline)
    except Exception:
        pass

    return factors

def send_telegram_alert(text: str):
    """
    Pomocnicza funkcja do wysyłania powiadomień push na Telegram.
    """
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        logger.error(f"❌ Błąd wysyłki Telegram: {e}")


# =============================================================================
# MULTI-TIMEFRAME TRADE EVALUATOR
# =============================================================================

def _log_rejection(db, tf, direction, price, reason, filter_name,
                   confluence_count=0, rsi=0, trend="", pattern="", atr=0):
    """Helper do zapisu odrzuconego setupu do bazy (fire-and-forget)."""
    try:
        db.log_rejected_setup(
            timeframe=tf, direction=direction, price=price,
            rejection_reason=reason, filter_name=filter_name,
            confluence_count=confluence_count, rsi=rsi,
            trend=trend, pattern=pattern, atr=atr
        )
    except (AttributeError, TypeError, Exception) as e:
        logger.debug(f"Rejection log failed: {e}")


def _evaluate_tf_for_trade(tf: str, db, balance: float = 10000, currency: str = "USD") -> dict | None:
    """
    Ocenia dany timeframe pod kątem ważnego setupu tradingowego.

    Zwraca dict z parametrami trade'a jeśli setup jest ważny, None jeśli nie.

    Walidacja obejmuje:
      0. Price sanity check (porównanie z persistent cache)
      1. Analiza SMC (trend, FVG, liquidity grab, MSS, order blocks)
      2. Filtr fail-rate wzorca (>75% → skip)
      3. Filtr wagi wzorca z self-learning (<0.5 → skip)
      4. Obliczenie pozycji (SL/TP) przez calculate_position
      5. Sprawdzenie kierunku (CZEKAJ → skip)
      6. ML ensemble validation (niska pewność → ostrzeżenie, ale nie blokuje)
    """
    from src.trading.finance import calculate_position
    from src.learning.self_learning import get_pattern_adjustment

    # ─── EVENT GUARD: tier-aware (2026-04-24, upgraded from binary high-impact) ───
    # Research-backed tier mapping (docs/research/2026-04-24_xau_news_research.md):
    #   Tier 1 (NFP/CPI/FOMC/PCE): flat ±15 min; trade only second rotation
    #     after 15-min candle confirm. These move gold 200-1000 pips.
    #   Tier 2 (PPI/ADP/Retail/Jobless/GDP): halve risk ±10 min.
    #   Tier 3 (Fed speakers, ECB/BoJ/SNB): normal + warning log.
    # Legacy behavior (±5min hard / ±15min halve) preserved as fallback path
    # when tier classifier doesn't recognize the event.
    event_halve_risk = False
    try:
        from src.data.news import get_imminent_events_by_tier, get_imminent_high_impact_events
        tiered = get_imminent_events_by_tier(minutes_window=15)
        tier1_soon = tiered.get("tier1", [])
        tier2_soon = tiered.get("tier2", [])
        tier3_soon = tiered.get("tier3", [])

        # Tier 1: hard block ±15 min (everything)
        if tier1_soon:
            titles = ", ".join(e.get("event", "?") for e in tier1_soon[:2])
            logger.info(f"⏸️ [EVENT GUARD] {tf}: TIER 1 block ±15min — {titles}")
            return None

        # Tier 2: halve risk on scalp TFs, block on H1+
        if tier2_soon:
            is_low_tf = str(tf) in ("5m", "15m", "30m")
            titles = ", ".join(e.get("event", "?") for e in tier2_soon[:2])
            if is_low_tf:
                logger.warning(f"🟡 [EVENT GUARD] {tf}: TIER 2 — halve risk, {titles}")
                event_halve_risk = True
            else:
                logger.info(f"⏸️ [EVENT GUARD] {tf}: TIER 2 block (H1+) — {titles}")
                return None

        # Tier 3: log only, trade normally
        if tier3_soon:
            titles = ", ".join(e.get("event", "?") for e in tier3_soon[:2])
            logger.info(f"📢 [EVENT GUARD] {tf}: TIER 3 speaker — trading normal, watch: {titles}")

        # Legacy fallback: catch high-impact events our tier keywords miss
        imminent_hard = get_imminent_high_impact_events(minutes_window=5)
        if imminent_hard and not tier1_soon and not tier2_soon:
            titles = ", ".join(e.get("event", "?") for e in imminent_hard[:2])
            logger.info(f"⏸️ [EVENT GUARD] {tf}: high-impact ±5min (untiered): {titles}")
            return None
    except Exception as _e:
        logger.debug(f"Event guard check failed: {_e}")  # soft-fail, don't block trading

    analysis = get_smc_analysis(tf)
    if not analysis:
        logger.debug(f"🔍 [MTF] {tf}: brak danych SMC — pomijam")
        return None

    # Propagate event-guard halve flag to position sizing
    if event_halve_risk:
        analysis['_scalp_risk_halve'] = True

    current_price = analysis['price']
    current_rsi = analysis['rsi']
    current_trend = analysis['trend']

    # --- 0a. PHASE V2 REGIME ROUTING (env-gated, default OFF) ---
    # 2026-05-04: when QUANT_REGIME_V2=1, the regime classifier (V1) is
    # consumed for: (a) block_entry on squeeze, (b) min_score override per
    # regime+TF, (c) direction filter from macro_regime. See module
    # src/analysis/regime_routing.py + memory/regime_v2_integration_runbook.md
    # Default OFF — no behavior change without explicit opt-in.
    _regime_routing = None
    if os.environ.get("QUANT_REGIME_V2") == "1":
        try:
            from src.analysis.regime import classify_regime
            from src.analysis.regime_routing import get_routing
            # Use the analysis frame from smc_engine (already computed for this TF)
            df_for_regime = analysis.get('_df') or analysis.get('df')
            market_regime = "ranging"
            if df_for_regime is not None and len(df_for_regime) >= 50:
                market_regime = classify_regime(df_for_regime)
            macro_regime = analysis.get('macro_regime') or 'neutralny'
            _regime_routing = get_routing(market_regime, tf, macro_regime)
            if _regime_routing.block_entry:
                logger.info(f"[MTF] {tf}: V2 regime={market_regime}/{macro_regime} -> block")
                _log_rejection(db, tf, "?", current_price,
                               f"regime_v2_block({market_regime}/{macro_regime})",
                               "regime_routing")
                return None
        except Exception as _re:
            logger.debug(f"regime_routing skipped: {_re}")
            _regime_routing = None

    # --- 0. PRICE SANITY CHECK ---
    if current_price <= 0:
        logger.debug(f"🔍 [MTF] {tf}: cena <= 0 — pomijam")
        return None
    # Skip live-ticker sanity in backtest: persistent_cache holds real-time
    # XAU price (today $4720), but simulated bars walk historical prices
    # ($2400 in 2024-08). Without this guard the check rejected 100% of
    # setups whenever |sim_price - live_price| / live_price > 20% — i.e.
    # the entire pre-2025-09 horizon, producing the spurious "scanner has
    # zero edge in 2024" walk-forward result.
    import os as _os_sanity
    if not _os_sanity.environ.get("QUANT_BACKTEST_MODE"):
        try:
            from api.routers.market import _persistent_cache as _mkt_pc
            ref = float(_mkt_pc.get("ticker", {}).get("price", 0))
            if ref > 1000:
                deviation = abs(current_price - ref) / ref
                if deviation > 0.20:
                    logger.warning(
                        f"🔍 [MTF] {tf}: Price sanity FAIL: SMC=${current_price:.2f} vs "
                        f"ticker=${ref:.2f} (Δ{deviation:.0%}) — pomijam"
                    )
                    return None
        except (ImportError, AttributeError, TypeError, ValueError):
            pass  # persistent_cache not available outside FastAPI context
    current_structure = analysis.get('structure', 'Stable')
    current_fvg = analysis.get('fvg')
    current_fvg_type = analysis.get('fvg_type')

    # --- 0b. FILTR MINIMALNEJ ZMIENNOŚCI (ATR) ---
    current_atr = analysis.get('atr', 0)
    if current_atr < 2.0:
        logger.info(f"🔍 [MTF] {tf}: ATR={current_atr:.2f} za niski (min 2.0) — zbyt mała zmienność")
        _log_rejection(db, tf, "LONG" if current_trend == "bull" else "SHORT",
                       current_price, f"ATR={current_atr:.2f}<2.0", "atr_filter",
                       rsi=current_rsi, trend=current_trend, atr=current_atr)
        return None

    # --- 0b2. SPREAD-AWARE FILTER (2026-04-24) ---
    # Block entries when ATR has expanded dramatically vs its 20-bar baseline.
    # Research: on XAU, spreads widen from 2-4 USD (normal) to 20-40 USD during
    # vol spikes (unscheduled news, flash moves). Stops get hunted by spread
    # widening alone, not real price action. Event guard catches scheduled
    # tier-1 events; this catches the rest (breaking news, central-bank
    # surprises, geopolitical). Threshold 2.0 = 2× baseline vol; 1.5 would
    # over-block since gold runs hot in normal trending sessions.
    atr_expansion = analysis.get('atr_expansion')
    if atr_expansion is None:
        # Derive if not already in analysis — use atr_mean if present
        atr_mean = analysis.get('atr_mean') or current_atr
        atr_expansion = current_atr / atr_mean if atr_mean > 0 else 1.0
    SPREAD_EXPANSION_CAP = 2.0
    if atr_expansion > SPREAD_EXPANSION_CAP:
        logger.info(
            f"🔍 [MTF] {tf}: ATR expansion {atr_expansion:.2f}× > {SPREAD_EXPANSION_CAP}× baseline "
            f"— vol spike (spread likely wide), pomijam"
        )
        _log_rejection(db, tf, "LONG" if current_trend == "bull" else "SHORT",
                       current_price, f"atr_exp={atr_expansion:.2f}>{SPREAD_EXPANSION_CAP}",
                       "spread_vol_spike",
                       rsi=current_rsi, trend=current_trend, atr=current_atr)
        return None

    # --- 0c. FILTR RSI EXTREME — nie wchodź w pozycję przeciw momentum ---
    if current_trend == "bull" and current_rsi > 75:
        logger.info(f"[MTF] {tf}: RSI={current_rsi:.0f} > 75 (wykupiony) — nie LONG na szczycie")
        _log_rejection(db, tf, "LONG", current_price, f"RSI={current_rsi:.0f}>75", "rsi_extreme",
                       rsi=current_rsi, trend=current_trend, atr=current_atr)
        return None
    if current_trend == "bear" and current_rsi < 25:
        logger.info(f"[MTF] {tf}: RSI={current_rsi:.0f} < 25 (wyprzedany) — nie SHORT na dnie")
        _log_rejection(db, tf, "SHORT", current_price, f"RSI={current_rsi:.0f}<25", "rsi_extreme",
                       rsi=current_rsi, trend=current_trend, atr=current_atr)
        return None

    # --- 1. FILTR FAIL RATE (tightened: 75% → 65%) ---
    fail_rate = db.get_fail_rate_for_pattern(current_rsi, current_structure)
    if fail_rate > 65:
        logger.info(f"[MTF] {tf}: fail rate {fail_rate}% za wysoki (max 65%) — pomijam")
        _log_rejection(db, tf, "LONG" if current_trend == "bull" else "SHORT",
                       current_price, f"fail_rate={fail_rate}%>65%", "fail_rate",
                       rsi=current_rsi, trend=current_trend, atr=current_atr)
        return None

    # --- 1b. TOXIC PATTERN BLOCK (2026-04-22, threshold bumped 2026-04-24) ---
    # pattern_stats holds the REAL pattern key ([M5] Trend Bull + FVG) matching
    # trades.pattern; scanner-side `LONG_Stable_bullish` naming was inert because
    # trades are logged as `[tf_label] {logic}` in api/main.py. Query the real key
    # directly and block toxic patterns.
    #
    # 2026-04-24: Raised n threshold 8 → 20. The 04-17 streak injected 8
    # clustered losses on [M5] Trend Bull + FVG in ~1h (#166-171), dominating
    # the n=15 sample. Pre-streak WR was 43%; during streak 0%; post-streak
    # 0 trades (filter self-locked). Requiring n>=20 lets the pattern re-enter
    # the sample after ~5 more trades, revalidating against current regime.
    # If it truly remains toxic, filter re-engages automatically.
    try:
        tox_pattern_key = f"[{TF_LABELS.get(tf, tf.upper())}] Trend {'Bull' if current_trend == 'bull' else 'Bear'} + FVG"
        tox_row = db._query_one(
            "SELECT count, wins, losses FROM pattern_stats WHERE pattern = ?",
            (tox_pattern_key,)
        )
        if tox_row:
            tox_n = tox_row[0]
            tox_wr = tox_row[1] / tox_n if tox_n else 0.5
            # Hard block: full toxic threshold met (n>=20, WR<30%)
            if tox_n >= 20 and tox_wr < 0.30:
                logger.info(
                    f"[MTF] {tf}: toxic pattern '{tox_pattern_key}' "
                    f"{tox_row[1]}W/{tox_row[2]}L WR={tox_wr:.0%}<30% (n={tox_n}) — pomijam"
                )
                _log_rejection(
                    db, tf, "LONG" if current_trend == "bull" else "SHORT",
                    current_price,
                    f"toxic_pattern:{tox_pattern_key}_WR{tox_wr:.0%}({tox_n})",
                    "toxic_pattern",
                    rsi=current_rsi, trend=current_trend,
                    pattern=tox_pattern_key, atr=current_atr
                )
                return None
            # 2026-05-02 audit: toxic-IMMINENT filter — pattern is approaching
            # the 20/30% threshold (n>=15 with WR<35%). Don't auto-block, but
            # tag analysis so downstream finance.py applies stricter gates.
            # Used by ML conflict block to insist on ML support before trading
            # near-toxic patterns. Self-correcting once pattern recovers WR.
            if tox_n >= 15 and tox_wr < 0.35:
                logger.warning(
                    f"[MTF] {tf}: toxic-IMMINENT '{tox_pattern_key}' "
                    f"{tox_row[1]}W/{tox_row[2]}L WR={tox_wr:.0%} (n={tox_n}) "
                    f"— stricter ML gate applied"
                )
                analysis['_toxic_imminent'] = True
                analysis['_toxic_pattern_key'] = tox_pattern_key
                analysis['_toxic_wr'] = tox_wr
                analysis['_toxic_n'] = tox_n
    except (AttributeError, TypeError, Exception) as _e:
        logger.debug(f"Toxic pattern check failed: {_e}")

    # --- 2. FILTR WAGI WZORCA — REMOVED 2026-04-24 ---
    # The pattern name constructed here was `LONG_Stable_bullish` style but
    # trades are logged to trades.pattern in `[M5] Trend Bull + FVG` format
    # (via api/main.py:363). `get_pattern_adjustment()` queries trades table
    # where pattern=<scanner key> → always count<5 → default weight 1.0 →
    # filter inert. This was a dead filter producing noise in logs but zero
    # actual blocking. Removed to simplify cascade. The toxic_pattern filter
    # at step 1b uses the CORRECT `[M5] Trend Bull + FVG` key and handles
    # the real pattern-based blocking.
    direction_str = "LONG" if current_trend == "bull" else "SHORT"
    pattern = f"{direction_str}_{current_structure}_{current_fvg_type}"

    # --- 0b. PHASE V2 — direction filter from regime_routing ---
    # If V2 active and regime restricts allowed_directions, reject early.
    if _regime_routing is not None and _regime_routing.allowed_directions:
        if direction_str not in _regime_routing.allowed_directions:
            logger.info(f"[MTF] {tf}: V2 direction={direction_str} not in "
                        f"{_regime_routing.allowed_directions} -> block")
            _log_rejection(db, tf, direction_str, current_price,
                           f"regime_v2_dir({direction_str}!in{_regime_routing.allowed_directions})",
                           "regime_routing")
            return None

    # --- 3. SPRAWDZENIE SETUPU SMC: wymagamy silnej konfluencji ---
    has_grab_mss = analysis.get('liquidity_grab') and analysis.get('mss')
    has_fvg = current_fvg_type in ("bullish", "bearish")
    has_bos = analysis.get('bos_bullish') or analysis.get('bos_bearish')
    has_choch = analysis.get('choch_bullish') or analysis.get('choch_bearish')
    has_dbr_rbd = analysis.get('dbr_rbd_type') in ("DBR", "RBD")
    has_ob = analysis.get('ob_price') is not None and analysis.get('ob_price') != current_price

    # RSI Divergence — silny kontrtrendowy sygnał
    has_rsi_div = (
        (current_trend == "bull" and analysis.get('rsi_div_bull')) or
        (current_trend == "bear" and analysis.get('rsi_div_bear'))
    )
    # Engulfing pattern confirmation
    has_engulfing = (
        (current_trend == "bull" and analysis.get('engulfing') == "bullish") or
        (current_trend == "bear" and analysis.get('engulfing') == "bearish")
    )

    # Count confluence signals
    confluence_count = sum([
        bool(has_grab_mss),
        bool(has_fvg),
        bool(has_bos or has_choch),
        bool(has_dbr_rbd),
        bool(has_ob),
        bool(has_rsi_div),
        bool(has_engulfing),
    ])

    # Backtest isolation flag — used in both step 3a (direction_conflict
    # scalp soften) and step 3 below (confluence/stable). Kept here (before
    # first usage) so scalp_soften doesn't UnboundLocalError.
    import os as _os_bt
    _relax = (
        _os_bt.environ.get("QUANT_BACKTEST_RELAX") == "1"
        and _os_bt.environ.get("QUANT_BACKTEST_MODE") == "1"
    )
    # Defense-in-depth: api/main.py:98 clears these env vars at startup, but
    # if a worker re-acquired them somehow, this is the last line of defense.
    # Log loudly (once-per-process) so the leak is visible.
    if _relax and not getattr(_evaluate_tf_for_trade, "_relax_warned", False):
        logger.error(
            "[SAFETY] _relax=True in scanner but should be production. "
            "QUANT_BACKTEST_RELAX/MODE leaked to worker — investigate env! "
            "Production filters will use backtest thresholds until restart."
        )
        _evaluate_tf_for_trade._relax_warned = True  # type: ignore[attr-defined]

    # --- 3a. DIRECTIONAL ALIGNMENT CHECK (new) ---
    # BOS/CHoCH must agree with trade direction — don't trade against structure
    if has_bos or has_choch:
        bos_bullish = analysis.get('bos_bullish', False)
        bos_bearish = analysis.get('bos_bearish', False)
        choch_bullish = analysis.get('choch_bullish', False)
        choch_bearish = analysis.get('choch_bearish', False)

        structure_bullish = bos_bullish or choch_bullish
        structure_bearish = bos_bearish or choch_bearish

        # Scalp mode (5m/15m/30m): structure conflict is a RISK SIGNAL, not
        # a hard block. Replay analyzer (7-day, 2026-04-17) showed 1009
        # directional_alignment rejects at 60% hypothetical WR — biggest
        # edge left on the table. On scalp TFs with small SL ($2-15),
        # halving lot caps downside while capturing the 60% upside.
        # H1/4h still hard-block (larger SL = genuinely expensive error).
        _scalp_soften = str(tf) in ("5m", "15m", "30m") and not _relax
        if direction_str == "LONG" and structure_bearish and not structure_bullish:
            if _scalp_soften:
                logger.warning(f"[MTF] {tf}: LONG vs BOS bearish — SCALP halve risk (soft)")
                analysis['_scalp_risk_halve'] = True
            else:
                logger.info(f"[MTF] {tf}: LONG but BOS/CHoCH is bearish — structural conflict")
                _log_rejection(db, tf, direction_str, current_price,
                               "structure_direction_conflict", "directional_alignment",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                return None
        if direction_str == "SHORT" and structure_bullish and not structure_bearish:
            if _scalp_soften:
                logger.warning(f"[MTF] {tf}: SHORT vs BOS bullish — SCALP halve risk (soft)")
                analysis['_scalp_risk_halve'] = True
            else:
                logger.info(f"[MTF] {tf}: SHORT but BOS/CHoCH is bullish — structural conflict")
                _log_rejection(db, tf, direction_str, current_price,
                               "structure_direction_conflict", "directional_alignment",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                return None

    # --- 3b. CONFLUENCE THRESHOLD (tightened: 3→4 base, grab+2→grab+3, dbr+2→dbr+3) ---
    # "Stable" structure = konsolidacja = 0% win rate historycznie — blokuj.
    #
    # BACKTEST RELAXATION: with yfinance-only data (no Twelve Data USD/JPY
    # correlation, no Myfxbook macro, no news sentiment feedback) we can't
    # reach confluence=3 in production setups. Lower to 2 and allow Stable.
    # Directional alignment + RSI extreme stay strict — those are reality
    # checks, not data-source-dependent.
    #
    # SAFETY: _relax already initialized at top of function (step 3a).
    # Double-gate — requires BOTH env vars. QUANT_BACKTEST_MODE is only set
    # by src.backtest.isolation.enforce_isolation(), which runs in a separate
    # process with a separate DB file. Production API never calls
    # enforce_isolation(), so it never sees either flag.
    # Backtest: threshold=1 — yfinance data produces max confluence=2-3,
    # and we lose news/macro signals (worth ~1-2 confluence in live).
    # At threshold=2 we got 0.5 trades/day; target is 2-3/day for
    # meaningful statistical sample. Directional alignment + RSI extreme
    # still strict — those protect against bad trades regardless.
    #
    # 2026-05-03: env-flagged HTF threshold override. filter_precision_report
    # found confluence at 57.2% precision — blocks 2351 winning trades on
    # cohort N=9430. HTF (1h, 4h) split: 1h LONG 57.5%, 4h SHORT 50.0%
    # (literal coin flip — ZERO signal at threshold 3). Lowering to 2 should
    # capture ~$25-50k EV per filter_precision_report.py.
    # Set QUANT_CONF_HTF_MIN=2 in .env to enable. Default unchanged.
    _min_conf = 1 if _relax else 3
    if not _relax:
        _htf_override = _os_bt.environ.get("QUANT_CONF_HTF_MIN", "")
        if _htf_override:
            try:
                _min_conf = int(_htf_override)
            except ValueError:
                pass

    structure = analysis.get('structure', 'Stable')
    is_stable = 'Stable' in str(structure)

    # --- Low-TF scalp exceptions (5m/15m, 2026-04-16) ---
    # Scalp-primary workflow: 5m and 15m catch $10-30 daily moves that don't
    # involve fresh grab/mss. Higher TFs (1h/4h) keep strict gates for
    # premium swing setups. On these lower TFs:
    #   - min_conf = 1 (single price-action factor is legit scalp trigger)
    #   - allow structure=Stable (Stable IS the default context — most
    #     ticks don't have a fresh SMC event; blocking Stable here kills
    #     every intraday setup)
    # Other filters (RSI extreme, directional alignment, ML ensemble
    # validation, pattern_weight, event guard, etc.) still apply — so we
    # accept thinner SMC confirmation, not a flood of junk.
    if str(tf) in ("5m", "15m", "30m") and not _relax:
        _min_conf = 1
        _allow_stable_5m = True
    else:
        _allow_stable_5m = False

    # Asian session (typically 00:00-08:00 CEST) is structurally a ranging market
    # for XAU/USD — "Stable" is the DEFAULT state, not a warning sign. Blocking
    # Stable in Asian killed ~230 setups across H4/H1/M15 overnight. Allow it
    # across all TFs when session = asian, on top of the 5m-always exception.
    _session = (analysis.get('session') or '').lower()
    _allow_stable_asian = _session == 'asian'

    strong_setup = (
        (has_grab_mss and confluence_count >= _min_conf)   # premium: grab+mss + N confirmations
        or (has_dbr_rbd and confluence_count >= _min_conf)  # DBR/RBD + N confirmations
        or confluence_count >= _min_conf                     # standalone: N+ signals required
    )
    # Stable is NOT an automatic block when: relaxed mode, 5m scalp, or asian session
    block_stable = (
        is_stable and not _relax
        and not _allow_stable_5m and not _allow_stable_asian
    )

    if not strong_setup or block_stable:
        reason = "structure=Stable (no grab/mss)" if block_stable else f"confluence={confluence_count}<{_min_conf}"
        logger.debug(f"[MTF] {tf}: brak silnego setupu ({reason}) -- pomijam")
        _log_rejection(db, tf, direction_str, current_price, reason, "confluence",
                       confluence_count=confluence_count, rsi=current_rsi,
                       trend=current_trend, pattern=pattern, atr=current_atr)
        return None

    # --- 3b. FVG-direction check moved below to AFTER direction_str is set
    # (line 553+). Previous version used current_trend as proxy for trade
    # direction, which would block legitimate ML-override setups where the
    # proposed direction differs from EMA trend. 2026-05-02 audit fix.

    # --- 4. OBLICZENIE POZYCJI (SL/TP/kierunek) ---
    # Pass empty DataFrame to skip redundant ML candle fetch inside calculate_position —
    # ML validation is done separately in step 5 with the correct TF candles.
    try:
        import pandas as _pd
        analysis['tf'] = tf  # pass TF so finance.py can apply scalp-mode on 5m
        pos = calculate_position(analysis, balance, currency, "", df=_pd.DataFrame())
    except Exception as e:
        logger.warning(f"🔍 [MTF] {tf}: błąd calculate_position: {e}")
        return None

    if pos.get("direction") == "CZEKAJ":
        logger.info(f"🔍 [MTF] {tf}: pozycja CZEKAJ — {pos.get('reason', '?')}")
        return None

    direction = pos['direction']
    entry = pos['entry']
    sl = pos['sl']
    tp = pos['tp']
    lot = pos.get('lot', 0.01)
    logic = pos.get('logic', '')

    # --- 3b. FVG-DIRECTION CHECK (moved from line 530, 2026-05-02) ---
    # Block when FVG opposes the actual trade direction (not just trend).
    # FVG bearish + LONG trade = setup contradicts itself; same for inverse.
    # This now correctly handles ML-override cases where direction != trend.
    if has_fvg:
        if direction == "LONG" and current_fvg_type == "bearish":
            logger.info(f"🔍 [MTF] {tf}: FVG bearish vs LONG direction — konfluencja słaba, pomijam")
            _log_rejection(db, tf, "LONG", current_price, "fvg_bearish_vs_long",
                           "fvg_direction", rsi=current_rsi, trend=current_trend, atr=current_atr)
            return None
        if direction == "SHORT" and current_fvg_type == "bullish":
            logger.info(f"🔍 [MTF] {tf}: FVG bullish vs SHORT direction — konfluencja słaba, pomijam")
            _log_rejection(db, tf, "SHORT", current_price, "fvg_bullish_vs_short",
                           "fvg_direction", rsi=current_rsi, trend=current_trend, atr=current_atr)
            return None

    # --- 3c. ML-MAJORITY + DECISIVE_RATIO GATES (env-flagged, 2026-05-02) ---
    # When QUANT_ML_MAJORITY_GATE=1, block trade if 2+ ML voters
    # (xgb/lstm/attention/v2_xgb) agreed on the OPPOSITE direction of
    # what the ensemble produced. The 5/5 LONG-LOSS streak (#217-221)
    # had this exact signature: xgb 0.28 SHORT, lstm 0.46 SHORT, attn
    # 0.48 SHORT — but ensemble fired LONG due to SMC + weight gates.
    # Default OFF: collect ml_majority_disagrees observability data
    # first, flip ON after empirical validation that the gate doesn't
    # over-block winning trades.
    #
    # QUANT_DECISIVE_GATE_MIN (e.g. "0.60") additionally blocks when
    # decisive_ratio (consensus among voters that took a side) is below
    # the threshold. Companion gate — catches "split decision" trades
    # where directional voters disagree among themselves. Default unset
    # = disabled.
    import os as _os_mlmaj
    ed = pos.get('ensemble_data', {}) or {}
    mag = ed.get('model_agreement', {}) or {}

    # Decisive_ratio gate (precedes ml_majority since it's a more general
    # split-decision check)
    _decisive_min_str = _os_mlmaj.environ.get("QUANT_DECISIVE_GATE_MIN", "")
    if _decisive_min_str:
        try:
            _decisive_min = float(_decisive_min_str)
        except ValueError:
            _decisive_min = 0.0
        if _decisive_min > 0:
            dr = mag.get('decisive_ratio', 1.0)
            decisive_voters = (mag.get('long', 0) + mag.get('short', 0))
            # Only enforce when at least 3 decisive voters; otherwise sample
            # too small for the ratio to be meaningful.
            if decisive_voters >= 3 and dr < _decisive_min:
                logger.info(
                    f"🔍 [MTF] {tf}: decisive_ratio={dr:.2f} < {_decisive_min:.2f} "
                    f"(L={mag.get('long')} S={mag.get('short')} N={mag.get('neutral')}) "
                    f"— pomijam (QUANT_DECISIVE_GATE_MIN)"
                )
                _log_rejection(
                    db, tf, direction, current_price,
                    f"decisive_ratio={dr:.2f}<{_decisive_min:.2f}",
                    "decisive_ratio_gate",
                    rsi=current_rsi, trend=current_trend,
                    pattern=pos.get('pattern', ''), atr=current_atr,
                )
                return None

    # SHORT-XGB shadow veto (2026-05-02 backfill analysis showed T=0.55
    # would have blocked 5/5 of the LOSS streak #217-#221, saving ~$80
    # at cost of 2 false LONG-WIN blocks). Env-flagged opt-in.
    #
    # 2026-05-03 REGIME-AWARE update: 3-month backtest (Jan-Mar 2026,
    # bull regime) showed veto fired 215× and blocked many LONG winners
    # (estimated -$1000+ vs no-veto in bull regime). Veto is appropriate
    # for current bear/squeeze regime but harmful in bull regimes.
    # Add QUANT_SHORT_XGB_VETO_SKIP_REGIMES env (default 'zielony') to
    # skip veto in macro_regime values matching the comma-separated list.
    # macro_regime semantics: zielony=bullish_gold, czerwony=bearish_gold,
    # neutralny=mixed.
    _short_veto_str = _os_mlmaj.environ.get("QUANT_SHORT_XGB_VETO_T", "")
    if _short_veto_str and direction == "LONG":
        try:
            _short_veto_T = float(_short_veto_str)
        except ValueError:
            _short_veto_T = 0.0
        if _short_veto_T > 0:
            # Regime-aware skip: don't veto LONG when macro regime is
            # in the skip-list (default 'zielony' = bullish gold, where
            # LONG should win and veto would block winners)
            _skip_regimes = _os_mlmaj.environ.get(
                "QUANT_SHORT_XGB_VETO_SKIP_REGIMES", "zielony"
            ).split(",")
            _skip_regimes = [r.strip() for r in _skip_regimes if r.strip()]
            _current_macro = analysis.get("macro_regime", "neutralny")
            if _current_macro in _skip_regimes:
                # Veto skipped — log at debug to avoid spam
                logger.debug(
                    f"[MTF] {tf}: SHORT-XGB veto skipped "
                    f"(macro_regime={_current_macro} in skip-list)"
                )
            else:
                try:
                    from src.ml.short_shadow import predict_short_xgb
                    from src.data.data_sources import get_provider as _get_p
                    _provider = _get_p()
                    _df_for_veto = _provider.get_candles('XAU/USD', tf, 200)
                    if _df_for_veto is None or _df_for_veto.empty:
                        raise RuntimeError("no candles for veto")
                    _short_p = predict_short_xgb(_df_for_veto)
                    if _short_p is not None and _short_p > _short_veto_T:
                        logger.info(
                            f"🔍 [MTF] {tf}: SHORT-XGB shadow veto LONG "
                            f"(short_p={_short_p:.3f} > {_short_veto_T:.2f}, "
                            f"macro={_current_macro}) — pomijam"
                        )
                        _log_rejection(
                            db, tf, direction, current_price,
                            f"short_xgb_veto:p={_short_p:.3f}>T={_short_veto_T:.2f}",
                            "short_xgb_veto",
                            rsi=current_rsi, trend=current_trend,
                            pattern=pos.get('pattern', ''), atr=current_atr,
                        )
                        return None
                except Exception as _ve:
                    logger.debug(f"SHORT-XGB veto skipped: {_ve}")

    if _os_mlmaj.environ.get("QUANT_ML_MAJORITY_GATE") == "1":
        if ed.get('ml_majority_disagrees'):
            ml_maj_dir = mag.get('ml_majority', '?')
            ml_long = mag.get('ml_long', 0)
            ml_short = mag.get('ml_short', 0)
            logger.info(
                f"🔍 [MTF] {tf}: ML majority disagrees with {direction} "
                f"(ML votes: long={ml_long} short={ml_short}, ml_majority={ml_maj_dir}) "
                f"— pomijam (QUANT_ML_MAJORITY_GATE=1)"
            )
            _log_rejection(
                db, tf, direction, current_price,
                f"ml_maj_disagrees_long{ml_long}_short{ml_short}",
                "ml_majority_gate",
                rsi=current_rsi, trend=current_trend,
                pattern=pos.get('pattern', ''), atr=current_atr,
            )
            return None

    # --- 5. ML ENSEMBLE VALIDATION (BLOKUJĄCE jeśli ML silnie się nie zgadza) ---
    ml_info = ""
    ensemble_result = None  # zachowaj ensemble result do zapisu w bazie
    try:
        from src.data.data_sources import get_provider
        from src.ml.ensemble_models import get_ensemble_prediction

        provider = get_provider()
        candles = provider.get_candles('XAU/USD', tf, 200)

        if candles is not None and not candles.empty:
            ensemble = get_ensemble_prediction(
                df=candles,
                smc_trend=current_trend,
                current_price=current_price,
                balance=10000,
                initial_balance=10000,
                position=0
            )
            ensemble_result = ensemble  # ZACHOWAJ do użycia później
            ml_signal = ensemble.get('ensemble_signal', 'CZEKAJ')
            ml_conf = ensemble.get('confidence', 0)

            # ML conflict threshold per TF — 5m scalp uses 65% (matches
            # finance.py scalp threshold so the morning raise takes effect),
            # H1+ uses 45% (slow TFs more sensitive to ML disagreement,
            # larger SL means wrong-direction trade is genuinely costly).
            _ml_conflict_threshold = 0.65 if str(tf) == "5m" else 0.45
            if ml_conf > 0.6 and ml_signal == direction_str:
                ml_info = f"ML: {ml_signal} ({ml_conf:.0%})"
                logger.info(f"[MTF] {tf}: ML potwierdza kierunek — {ml_info}")
            elif (ml_conf > _ml_conflict_threshold
                    and ml_signal != "CZEKAJ"
                    and ml_signal != direction_str):
                logger.warning(
                    f"[MTF] {tf}: ML ({ml_signal}, {ml_conf:.0%}) "
                    f"KONFLIKT z SMC ({direction_str}) — BLOKUJĘ trade"
                )
                _log_rejection(db, tf, direction_str, current_price,
                               f"ML={ml_signal}({ml_conf:.0%}) vs SMC={direction_str}", "ml_conflict",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                return None
            elif ml_conf < 0.3:
                logger.info(f"⚠️ [MTF] {tf}: ML niska pewność {ml_conf:.0%} — trade dozwolony ale ryzykowny")
                ml_info = f"ML: niepewny ({ml_conf:.0%})"
    except Exception as e:
        logger.debug(f"[MTF] {tf}: ML ensemble validation skipped: {e}")

    # --- 6b. SENTIMENT FILTER (opcjonalny — nie blokuje jeśli brak danych) ---
    try:
        from src.core.database import NewsDB as _SentDB
        _sent_db = _SentDB()
        # Sprawdź ostatni sentyment z news_sentiment (jeśli istnieje)
        _sent_row = _sent_db._query_one(
            "SELECT sentiment, score FROM news_sentiment ORDER BY id DESC LIMIT 1"
        )
        if _sent_row and _sent_row[0] and _sent_row[1]:
            news_sentiment = str(_sent_row[0]).lower()
            sent_conf = float(_sent_row[1]) if _sent_row[1] else 0
            # Jeśli sentyment jest silnie przeciwny do kierunku — blokuj
            if sent_conf > 0.7:
                if direction_str == "LONG" and "bearish" in news_sentiment:
                    logger.info(
                        f"📰 [MTF] {tf}: Sentyment BEARISH ({sent_conf:.0%}) "
                        f"vs LONG — BLOKUJĘ trade"
                    )
                    return None
                elif direction_str == "SHORT" and "bullish" in news_sentiment:
                    logger.info(
                        f"📰 [MTF] {tf}: Sentyment BULLISH ({sent_conf:.0%}) "
                        f"vs SHORT — BLOKUJĘ trade"
                    )
                    return None
    except Exception as e:
        logger.debug(f"[MTF] Sentiment filter skipped: {e}")

    # --- 6c. SMT DIVERGENCE FILTER — dolar i złoto nie powinny iść razem ---
    smt_warning = analysis.get('smt', 'Brak')
    if smt_warning and smt_warning != "Brak":
        logger.warning(f"⚠️ [MTF] {tf}: {smt_warning} — pomijam trade (SMT)")
        return None

    # --- 6d. PREMIUM/DISCOUNT FILTER — nie kupuj na premium, nie shortuj na discount ---
    # 5m scalp override (2026-04-14, v2): allow LONG-in-premium /
    # SHORT-in-discount on 5m when confluence_count >= 2 (matches the 5m
    # min_conf gate already enforced earlier in the function). Initial
    # override at >=3 never triggered — live setups on 5m cluster at
    # confluence=2. Lowering the bar to 2 effectively disables premium
    # filter on 5m but keeps it strict on 15m/1h/4h where premium
    # positioning genuinely kills R:R for longer holds.
    is_premium = analysis.get('is_premium', False)
    is_discount = analysis.get('is_discount', False)
    _premium_override_5m = (str(tf) == "5m" and confluence_count >= 2)
    if direction_str == "LONG" and is_premium and not _premium_override_5m:
        logger.info(f"🔍 [MTF] {tf}: LONG w strefie PREMIUM — złe R:R, pomijam")
        return None
    if direction_str == "SHORT" and is_discount and not _premium_override_5m:
        logger.info(f"🔍 [MTF] {tf}: SHORT w strefie DISCOUNT — złe R:R, pomijam")
        return None
    if _premium_override_5m and (is_premium or is_discount):
        logger.info(f"[MTF] {tf}: {direction_str} w strefie "
                    f"{'premium' if is_premium else 'discount'} dozwolone "
                    f"(confluence={confluence_count}>=2) — scalp override")

    # --- 6e. LOSS PATTERN CHECK (nowe!) ---
    try:
        from src.learning.self_learning import check_loss_pattern_match
        loss_match = check_loss_pattern_match(analysis, direction_str)
        if loss_match and loss_match['count'] >= 5:
            logger.warning(
                f"⚠️ [MTF] {tf}: Wykryto wzorzec strat: {loss_match['pattern_type']} "
                f"({loss_match['count']}x) — {loss_match['desc']}"
            )
            _log_rejection(db, tf, direction_str, current_price,
                           f"loss_pattern:{loss_match['pattern_type']}({loss_match['count']}x)",
                           "loss_pattern", confluence_count=confluence_count,
                           rsi=current_rsi, trend=current_trend, pattern=pattern, atr=current_atr)
            return None
        elif loss_match:
            logger.info(
                f"📝 [MTF] {tf}: Ostrzeżenie — wzorzec strat: {loss_match['pattern_type']} "
                f"({loss_match['count']}x) — kontynuuję ale z ostrzeżeniem"
            )
    except Exception as e:
        logger.debug(f"Loss pattern check skipped: {e}")

    # --- 6f. SESSION PERFORMANCE FILTER ---
    # Block trading in sessions where historical WR is poor for this direction
    try:
        current_session = analysis.get('session', 'unknown')
        session_perf = db.get_session_win_rate(current_session, direction_str, min_trades=5)
        if session_perf.get('sufficient_data') and session_perf['win_rate'] is not None:
            if session_perf['win_rate'] < 0.30:
                logger.info(
                    f"[MTF] {tf}: Session '{current_session}' WR={session_perf['win_rate']:.0%} "
                    f"for {direction_str} ({session_perf['count']} trades) — below 30%, pomijam"
                )
                _log_rejection(db, tf, direction_str, current_price,
                               f"session_wr={session_perf['win_rate']:.0%}<30%({current_session})",
                               "session_performance",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                return None
            elif session_perf['win_rate'] < 0.40:
                logger.info(
                    f"[MTF] {tf}: Session '{current_session}' WR={session_perf['win_rate']:.0%} "
                    f"for {direction_str} — marginal, proceeding with caution"
                )
    except (AttributeError, TypeError) as e:
        logger.debug(f"Session performance check skipped: {e}")

    # --- 6g. HOURLY STATS CHECK ---
    try:
        from datetime import datetime
        # Honour simulated time in backtest. Production leaves _SIM_CURRENT_TS
        # at None, so this falls through to wall-clock UTC. In a backtest the
        # harness rebinds the cell and updates [0] per cycle.
        _sim_cell = _SIM_CURRENT_TS
        if _sim_cell is not None and _sim_cell[0] is not None:
            current_hour = _sim_cell[0].hour
        else:
            current_hour = datetime.now().hour
        bad_hours = db.get_bad_hours(min_trades=5, max_winrate=0.35)
        for bh in bad_hours:
            hour, bh_dir, bh_wr, bh_count = bh
            if hour == current_hour and bh_dir == direction_str:
                logger.warning(
                    f"⏰ [MTF] {tf}: Godzina {current_hour}:00 ma winrate {bh_wr:.0%} "
                    f"dla {direction_str} ({bh_count} tradów) — pomijam"
                )
                _log_rejection(db, tf, direction_str, current_price,
                               f"bad_hour={current_hour}:00 WR={bh_wr:.0%}({bh_count}trades)",
                               "hourly_stats", confluence_count=confluence_count,
                               rsi=current_rsi, trend=current_trend, pattern=pattern, atr=current_atr)
                return None
    except Exception as e:
        logger.debug(f"Hourly stats check skipped: {e}")

    # --- 6g. HTF TREND CONFIRMATION (nie handluj przeciw wyższemu TF) ---
    # M5/M15 must align with H1; M15 should also check H4 for stronger confirmation
    htf_checks = []
    if tf == "5m":
        htf_checks = [("1h", "H1")]
    elif tf == "15m":
        htf_checks = [("1h", "H1"), ("4h", "H4")]
    elif tf == "30m":
        htf_checks = [("1h", "H1"), ("4h", "H4")]
    elif tf == "1h":
        htf_checks = [("4h", "H4")]

    # HTF conflict semantics (2026-04-16 relax):
    # Previously ANY single HTF disagreement hard-rejected. Replay analyzer
    # showed 100% hypothetical win-rate on 4 htf_confirmation rejects over
    # 24h (small sample, but directional signal). For low-TF scalps, use
    # quorum logic: reject only if MAJORITY of HTFs disagree. For 1h, keep
    # hard reject (a single H4 disagreement on an hourly trade is real risk).
    htf_is_scalp_quorum = str(tf) in ("5m", "15m", "30m")
    htf_conflicts = 0
    htf_conflict_label = None
    for htf_tf, htf_label in htf_checks:
        try:
            htf_analysis = get_smc_analysis(htf_tf)
            if not htf_analysis:
                continue
            htf_trend = htf_analysis.get('trend', '')
            conflict = (direction == "LONG" and htf_trend == "bear") or \
                       (direction == "SHORT" and htf_trend == "bull")
            if conflict:
                if not htf_is_scalp_quorum:
                    # H1 trades: single disagreement = hard reject (bigger SL, costlier to be wrong)
                    logger.info(f"[MTF] {tf}: {direction} vs {htf_label} trend={htf_trend} — NIE handluj przeciw HTF")
                    _log_rejection(db, tf, direction, current_price,
                                   f"htf_conflict:{htf_label}={htf_trend}", "htf_confirmation",
                                   confluence_count=confluence_count, rsi=current_rsi,
                                   trend=current_trend, pattern=pattern, atr=current_atr)
                    return None
                htf_conflicts += 1
                htf_conflict_label = htf_label
        except (ImportError, AttributeError, TypeError) as e:
            logger.debug(f"[MTF] {htf_label} confirmation skipped: {e}")

    # Low-TF quorum: majority of HTFs must disagree before hard-reject.
    # For 15m/30m we check 2 HTFs (H1+H4), so require BOTH to disagree.
    # If only 1 disagrees: soft-halve risk via existing _scalp_risk_halve.
    if htf_is_scalp_quorum and htf_conflicts > 0:
        n_checks = len(htf_checks)
        if n_checks > 0 and htf_conflicts >= (n_checks + 1) // 2 + (0 if n_checks == 1 else 0):
            # Majority conflict (or only HTF disagrees for 5m)
            if htf_conflicts == n_checks:
                logger.info(f"[MTF] {tf}: {direction} all HTFs disagree — block")
                _log_rejection(db, tf, direction, current_price,
                               f"htf_conflict_quorum:{htf_conflicts}/{n_checks}", "htf_confirmation",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                return None
        # Partial conflict on multi-HTF: halve risk, let it through
        logger.warning(f"[MTF] {tf}: {direction} partial HTF conflict ({htf_conflicts}/{n_checks}, {htf_conflict_label}) — halve risk")
        analysis['_scalp_risk_halve'] = True

    if htf_checks and htf_conflicts == 0:
        logger.info(f"[MTF] {tf}: HTF trend alignment confirmed for {direction}")

    # --- 6h. TOXIC PAIR FILTER (env-gated, default OFF) ---
    # 2026-05-04: choch + ob_count globally has WR 16.7% on N=30 — strongest
    # anti-pattern found. Block when both fire together.
    # Memory: toxic_pair_choch_obcount_2026-05-04.md
    if os.environ.get("QUANT_BLOCK_CHOCH_OBCOUNT") == "1":
        # Use the analysis output to detect — factors are derived in
        # score_setup_quality but available here from analysis dict.
        try:
            choch_present = bool(analysis.get("choch") or analysis.get("change_of_character"))
            ob_count = analysis.get("ob_count", 0) or 0
            if choch_present and ob_count >= 1:
                _log_rejection(db, tf, direction_str, current_price,
                               "toxic_pair_choch_ob_count_WR16.7%",
                               "toxic_pair_filter",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                logger.info(f"[MTF] {tf}: TOXIC pair choch+ob_count → block (N=30 WR 16.7%)")
                return None
        except Exception as _e:
            logger.debug(f"toxic_pair check skipped: {_e}")

    # --- 7. SETUP QUALITY SCORING (nowe!) ---
    setup_quality = None
    try:
        from src.trading.smc_engine import score_setup_quality
        setup_quality = score_setup_quality(analysis, direction)
        grade = setup_quality['grade']

        # --- 7a. PHASE V2 — min_score floor override ---
        # When V2 active, override the C-only block with regime-specific floor.
        if _regime_routing is not None and _regime_routing.min_score_floor is not None:
            score_val = setup_quality.get('score', 0)
            if score_val < _regime_routing.min_score_floor:
                logger.info(f"[MTF] {tf}: V2 score={score_val:.1f} < floor "
                            f"{_regime_routing.min_score_floor} -> block")
                _log_rejection(db, tf, direction_str, current_price,
                               f"regime_v2_score<{_regime_routing.min_score_floor}({score_val:.1f})",
                               "regime_routing",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                return None

        if grade == "C":
            # Surface factors_detail so we can see WHAT is missing. Previously
            # we only logged "C (14/100)" which made diagnosis impossible.
            factors = setup_quality.get('factors_detail', {})
            factors_str = ', '.join(f"{k}={v}" for k, v in factors.items()) if factors else '(no factors matched)'
            logger.info(
                f"🔍 [MTF] {tf}: Setup grade=C ({setup_quality['score']}/100) — "
                f"zbyt niska jakość, pomijam | factors: {factors_str}"
            )
            _log_rejection(db, tf, direction, current_price,
                           f"setup_grade=C({setup_quality['score']}/100)", "setup_quality",
                           confluence_count=confluence_count, rsi=current_rsi,
                           trend=current_trend, pattern=pattern, atr=current_atr)
            return None

        # 2026-04-21: B grade (25-44) on scalp TFs after 17-losses-in-19 streak
        # 04-17→21 (WR 25%). Losing trades #179-#183 had scores 26-39 — B grade
        # with LOW confluence (3-4 noise factors). H1/4h keeps B unconditionally
        # (HTF setups are rarer, B on HTF = genuine confluence gap).
        #
        # 2026-04-24: Softened — blanket scalp B-block was over-blocking real
        # confluence. Found B(42.8) with 6 SMC factors (bos+fvg+ob+ichimoku+
        # macro+macro_aligned) being rejected — score reduced by penalties
        # (ob_distance_penalty), not by missing structure. Now: block scalp B
        # only when fewer than 5 non-penalty factors fired. 5+ factors = real
        # confluence even if penalties drag the score, so allow at 0.5x risk.
        if grade == "B" and str(tf) in ("5m", "15m", "30m"):
            factors = setup_quality.get('factors_detail', {})
            non_penalty_factor_count = sum(
                1 for k in factors.keys() if not k.endswith('_penalty')
            )
            # Allow B only when BOTH conditions met: real confluence (5+ factors)
            # AND score not in the streak's noise zone (>=35). Streak losses
            # #179-186 had scores 26-39 — keep the lower band blocked even if
            # they have factor counts, because those were precisely the
            # patterns that bled. The 35 threshold lets through B(37.9) /
            # B(42.8) penalty-reduced setups that DO have real structure.
            b_allow = non_penalty_factor_count >= 5 and setup_quality['score'] >= 35
            if not b_allow:
                factors_str = ', '.join(f"{k}={v}" for k, v in factors.items()) if factors else '(no factors matched)'
                logger.info(
                    f"🔍 [MTF] {tf}: Setup grade=B ({setup_quality['score']}/100) "
                    f"factors={non_penalty_factor_count} — block (need 5+ factors AND score>=35) | factors: {factors_str}"
                )
                _log_rejection(db, tf, direction, current_price,
                               f"setup_grade=B_low({setup_quality['score']}/100,n={non_penalty_factor_count})",
                               "setup_quality_scalp",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                return None
            # Else: B with 5+ factors AND score>=35 — real confluence at 0.5x risk
            logger.info(
                f"📊 [MTF] {tf}: Setup grade=B ({setup_quality['score']}/100) "
                f"with {non_penalty_factor_count} SMC factors — allowing (real confluence, 0.5x size)"
            )

        logger.info(
            f"📊 [MTF] {tf}: Setup {grade} ({setup_quality['score']}/100) | "
            f"Risk mult: {setup_quality['risk_mult']} | R:R: {setup_quality['target_rr']}"
        )
    except Exception as e:
        logger.debug(f"Setup quality scoring skipped: {e}")
        setup_quality = {'grade': 'A', 'score': 50, 'risk_mult': 1.0, 'target_rr': 2.5, 'factors_detail': {}}

    # --- 8. SETUP WAŻNY — zwróć parametry trade'a ---
    grade_icon = {"A+": "⭐", "A": "✅", "B": "⚠️"}.get(setup_quality['grade'], "❓")
    logger.info(
        f"🎯 [MTF] ZNALEZIONO TRADE na {tf}! {grade_icon} Grade: {setup_quality['grade']} | "
        f"{direction} @ {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | {logic}"
    )

    # Extract SMC factors for self-learning attribution
    factors = extract_factors(analysis, direction)

    return {
        "tf": tf,
        "tf_label": TF_LABELS.get(tf, tf.upper()),
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "lot": lot,
        "logic": logic,
        "trend": current_trend,
        "rsi": current_rsi,
        "structure": current_structure,
        "fvg": current_fvg,
        "fvg_type": current_fvg_type,
        "pattern": pattern,
        "fail_rate": fail_rate,
        "price": current_price,
        "ml_info": ml_info,
        "analysis": analysis,
        "factors": factors,
        "setup_quality": setup_quality,
        "ensemble_result": ensemble_result,
    }


def _get_adaptive_cooldown_hours(db) -> float:
    """
    Compute adaptive cooldown based on session + RECENT consecutive losses.

    2026-04-14: Halved base values across all sessions (scalp-friendly).
    The old 2.0h off_hours cooldown blocked legitimate post-NY-close
    setups on 5m. New base keeps meaningful rate-limiting but lets the
    scanner react to intraday setups without burning 2-3 hours between
    each one.

    Base cooldown per session:
      Asian:    0.75h  (was 1.5)
      London:   0.25h  (was 0.5 — high vol, fast moves)
      Overlap:  0.25h  (was 0.5 — max liquidity)
      NY:       0.5h   (was 0.75)
      Off-hours: 1.0h  (was 2.0 — thin liquidity but still tradeable)
      Weekend:  24.0h  (unchanged — no tradeable setups)

    Consecutive loss scaling: +0.3h per loss (up to +1h, was 2h).
    IMPORTANT: only losses within the last 24h count. Stale losses from
    earlier sessions (e.g. a 6-day-old loss streak) no longer keep the
    cooldown inflated forever.
    """
    # Session-dependent base cooldown
    try:
        from src.trading.smc_engine import get_active_session
        session_info = get_active_session()
        session = session_info.get('session', 'off_hours')
    except (ImportError, AttributeError):
        session = 'off_hours'

    base_hours = {
        'asian': 0.75,
        'london': 0.25,
        'overlap': 0.25,
        'new_york': 0.5,
        'off_hours': 1.0,
        'weekend': 24.0,
    }.get(session, 0.5)

    # Add penalty for consecutive RECENT losses (last 24h only).
    try:
        recent = db._query(
            "SELECT status FROM trades "
            "WHERE status IN ('WIN', 'LOSS') "
            "  AND timestamp >= datetime('now', '-24 hours') "
            "ORDER BY id DESC LIMIT 5"
        )
        consec_losses = 0
        for r in (recent or []):
            if r[0] == 'LOSS':
                consec_losses += 1
            else:
                break
        base_hours += min(consec_losses * 0.3, 1.0)
    except (AttributeError, TypeError, IndexError):
        pass

    return base_hours


def _check_trade_cooldown(db, min_hours: float = None) -> bool:
    """
    Sprawdza czy minął minimalny czas od ostatniego trade'a.
    Uses adaptive cooldown based on session + loss streak if min_hours not specified.
    Zwraca True jeśli można handlować, False jeśli jeszcze za wcześnie.
    """
    # 2026-04-25: Set BACKTEST_DISABLE_COOLDOWN=1 to skip cooldown in
    # comparison backtests where cooldown skews trade count vs other
    # variants (e.g. trailing-disabled runs hold positions longer).
    import os
    if os.environ.get("BACKTEST_DISABLE_COOLDOWN") == "1":
        return True

    if min_hours is None:
        min_hours = _get_adaptive_cooldown_hours(db)

    try:
        from datetime import datetime, timedelta, timezone
        last_trade = db._query_one(
            "SELECT timestamp FROM trades ORDER BY id DESC LIMIT 1"
        )
        if last_trade and last_trade[0]:
            # Trade timestamps are stored in UTC since 2026-04-15. `datetime.now()`
            # without tz returns LOCAL time (CEST = UTC+2), which added a fake 2h
            # to elapsed — effectively disabling cooldown. The 5 consecutive
            # SHORT trades opened 3-5 min apart on 2026-04-16 16:37-16:53 traced
            # to this. Compare both as UTC.
            last_time = datetime.strptime(last_trade[0], "%Y-%m-%d %H:%M:%S")
            last_time = last_time.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - last_time).total_seconds() / 3600
            if elapsed < min_hours:
                logger.info(
                    f"[COOLDOWN] Ostatni trade {elapsed:.2f}h temu, "
                    f"adaptive minimum {min_hours:.2f}h — pomijam"
                )
                return False
    except (ValueError, TypeError, AttributeError) as e:
        logger.debug(f"Cooldown check error: {e}")
    return True


def cascade_mtf_scan(db, balance: float = 10000, currency: str = "USD") -> dict | None:
    """
    Kaskadowe skanowanie multi-timeframe: 4h → 1h → 15m → 5m.
    Zwraca dict z parametrami trade'a na pierwszym TF z ważnym setupem, lub None.

    NIE zapisuje do bazy, NIE wysyła alertów — to odpowiedzialność wywołującego.
    Sprawdza dostępność kredytów API przed każdym TF.

    Args:
        db: instancja NewsDB
        balance: balance portfela (do calculate_position)
        currency: waluta portfela

    Returns:
        dict z parametrami trade'a lub None jeśli żaden TF nie dał sygnału
    """
    # --- RISK MANAGER: circuit breaker check before scanning ---
    try:
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        can_trade, reason = rm.check_circuit_breakers(balance)
        if not can_trade:
            logger.warning(f"[MTF] Risk manager blocked scan: {reason}")
            return None
    except (ImportError, AttributeError) as e:
        logger.debug(f"Risk manager unavailable: {e}")

    # --- COOLDOWN: minimum 30min między tradami (M5/M15 dają setupy częściej) ---
    if not _check_trade_cooldown(db):  # adaptive cooldown (session + loss streak)
        return None

    logger.info(f"🔎 [MTF] Start kaskady: {' → '.join(SCAN_TIMEFRAMES)}")

    for tf in SCAN_TIMEFRAMES:
        logger.info(f"🔎 [MTF] Sprawdzam {TF_LABELS.get(tf, tf)}...")

        # Credit pre-check per TF (candles + USD/JPY ≈ 2 credits)
        try:
            from src.api_optimizer import get_rate_limiter
            can, _ = get_rate_limiter().can_use_credits(2)
            if not can:
                logger.info(f"🔎 [MTF] Credits low — przerywam kaskadę na {tf}")
                break
        except (ImportError, AttributeError):
            pass  # API optimizer not initialized (tests / early startup)

        result = _evaluate_tf_for_trade(tf, db, balance=balance, currency=currency)
        if result is not None:
            logger.info(f"✅ [MTF] Trade znaleziony na {TF_LABELS.get(tf, tf)} — przerywam kaskadę.")
            return result
        else:
            logger.debug(f"⏭️ [MTF] Brak setupu na {TF_LABELS.get(tf, tf)} — szukam niżej...")

    logger.info("🔎 [MTF] Brak ważnego setupu na żadnym TF.")
    return None



def apply_trailing_stop(db, trade_row: tuple, current_price: float, atr: float = 0.0) -> bool:
    """Apply 5-level trailing stop to one open trade. Returns True if SL updated.

    Standalone version of the trailing block from resolve_trades_task — usable
    from api/main.py:_auto_resolve_trades which (until 2026-04-15) had no
    trailing logic at all and lost the full SL distance on every trade that
    went 1.5R+ into profit then reversed.

    trade_row: (id, direction, entry, sl, tp, trailing_sl) tuple.
    current_price: latest market price.
    atr: optional ATR for ATR_TRAIL level (>=2.5R). Falls back to sl_distance
         if 0/missing.
    """
    try:
        t_id, direction, entry, sl, tp, trailing_sl = trade_row[:6]
        dir_clean = str(direction or "").upper()
        entry_f = float(entry or 0)
        original_sl = float(sl or 0)
        sl_f = float(trailing_sl or sl or 0)
        if entry_f <= 0 or original_sl <= 0:
            return False
        sl_distance = abs(entry_f - original_sl)
        if sl_distance <= 0:
            return False

        if "LONG" in dir_clean:
            r_multiple = (current_price - entry_f) / sl_distance
        else:
            r_multiple = (entry_f - current_price) / sl_distance

        # Only consider locking levels — under 0.5R no action
        if r_multiple < 0.5:
            return False

        try:
            from src.trading.risk_manager import get_risk_manager
            spread_buf = get_risk_manager().get_spread_buffer()
        except (ImportError, AttributeError):
            spread_buf = 0.60

        def _trail_sl(lock_r: float) -> float:
            if "LONG" in dir_clean:
                return round(entry_f + sl_distance * lock_r, 2)
            return round(entry_f - sl_distance * lock_r, 2)

        def _is_better(cand: float) -> bool:
            if "LONG" in dir_clean:
                return cand > sl_f
            return cand < sl_f

        candidate_sl = None
        trail_event = None

        if r_multiple >= 2.5:
            _atr = atr if atr > 0 else sl_distance
            atr_trail = max(_atr * 1.5, sl_distance * 0.5)
            if "LONG" in dir_clean:
                candidate_sl = round(current_price - atr_trail, 2)
            else:
                candidate_sl = round(current_price + atr_trail, 2)
            fixed_floor = _trail_sl(1.25)
            if "LONG" in dir_clean:
                candidate_sl = max(candidate_sl, fixed_floor)
            else:
                candidate_sl = min(candidate_sl, fixed_floor)
            trail_event = "ATR_TRAIL"
        elif r_multiple >= 2.0:
            candidate_sl = _trail_sl(1.25)
            trail_event = "TRAIL_2R"
        elif r_multiple >= 1.5:
            candidate_sl = _trail_sl(0.75)
            trail_event = "LOCK_1.5R"
        elif r_multiple >= 1.0:
            if "LONG" in dir_clean:
                candidate_sl = round(entry_f + spread_buf, 2)
            else:
                candidate_sl = round(entry_f - spread_buf, 2)
            trail_event = "BREAKEVEN_1R"
        elif r_multiple >= 0.5:
            candidate_sl = _trail_sl(-0.7)
            trail_event = "REDUCE_0.5R"

        if candidate_sl is None or trail_event is None or not _is_better(candidate_sl):
            return False

        try:
            db.update_trade_trailing_sl(t_id, candidate_sl)
            db.log_trailing_stop_event(t_id, trail_event, sl_f, candidate_sl,
                                        current_price, round(r_multiple, 2))
            logger.info(
                f"[TRAILING] #{t_id} {dir_clean} | {trail_event} R={r_multiple:.2f} | "
                f"SL: {sl_f:.2f} → {candidate_sl:.2f}"
            )
            return True
        except Exception as e:
            logger.warning(f"[TRAILING] #{t_id} update failed: {e}")
            return False
    except Exception as e:
        logger.debug(f"apply_trailing_stop error: {e}")
        return False


