# src/self_learning.py
"""
self_learning.py – mechanizmy samouczenia: optymalizacja parametrów, analiza wzorców.
"""

import asyncio
import re
import random
import sys

from src.core.database import NewsDB, _db_locked
from src.core.logger import logger
from src.trading.smc_engine import get_smc_analysis
from src.trading.finance import calculate_position
from src.integrations.ai_engine import ask_ai_gold  # zachowane jako fallback w testach
from src.integrations.openai_agent import ask_agent_with_memory
from src.core.config import USER_PREFS, TD_API_KEY, ENABLE_BAYES

# Minimalna liczba transakcji do uruchomienia optymalizacji
MIN_TRADES_FOR_OPT = 20

def update_pattern_weight(analysis_data: dict, outcome: str):
    """
    Aktualizuje statystyki wzorca na podstawie wyniku transakcji.
    Wywoływane przez resolver.
    """
    db = NewsDB()
    pattern = analysis_data.get('pattern')
    if pattern:
        db.update_pattern_stats(pattern, outcome)


def get_time_weighted_win_rate(pattern: str, decay_days: float = 30.0) -> dict:
    """
    Compute time-weighted win rate for a pattern.

    Recent trades weighted exponentially more than old ones:
      weight = exp(-age_days / decay_days)

    30-day decay = recent trades get ~10x weight vs 2-month-old trades.
    Returns: {'win_rate': float, 'count': int, 'effective_n': float}
    """
    db = NewsDB()
    try:
        rows = db._query(
            "SELECT status, timestamp FROM trades WHERE pattern = ? AND status IN ('WIN', 'LOSS') "
            "ORDER BY timestamp DESC LIMIT 100",
            (pattern,)
        )
        if not rows or len(rows) < 5:
            return {'win_rate': 0.5, 'count': len(rows or []), 'effective_n': 0}

        import datetime
        now = datetime.datetime.now()
        weighted_wins = 0.0
        weighted_total = 0.0

        for status, ts in rows:
            try:
                trade_time = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                age_days = (now - trade_time).total_seconds() / 86400
                weight = 2.718 ** (-age_days / decay_days)  # exp decay
            except (ValueError, TypeError):
                weight = 0.1

            weighted_total += weight
            if status == 'WIN':
                weighted_wins += weight

        wr = weighted_wins / weighted_total if weighted_total > 0 else 0.5
        return {'win_rate': round(wr, 3), 'count': len(rows), 'effective_n': round(weighted_total, 1)}

    except (AttributeError, TypeError) as e:
        logger.debug(f"Time-weighted stats failed: {e}")
        return {'win_rate': 0.5, 'count': 0, 'effective_n': 0}


def get_pattern_adjustment(analysis_data: dict) -> float:
    """
    Zwraca współczynnik korekty (0.5-1.5) na podstawie time-weighted win rate wzorca.
    Kontekstowy: uwzględnia sesję, godzinę i reżim makro.
    """
    db = NewsDB()
    pattern = analysis_data.get('pattern')
    if not pattern:
        return 1.0

    # Use time-weighted win rate (recent trades matter more)
    tw_stats = get_time_weighted_win_rate(pattern)
    if tw_stats['count'] < 5:
        return 1.0

    # Bazowy współczynnik z time-weighted WR
    adj = tw_stats['win_rate'] * 1.5

    # --- KOREKTA KONTEKSTOWA: sesja ---
    try:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        hour = now.hour  # used later by hourly block
        current_session = db.get_session(now.strftime("%Y-%m-%d %H:%M:%S"))

        session_stats = db.get_session_stats(pattern)
        for ss in session_stats:
            # ss = (pattern, session, count, wins, losses, win_rate)
            if ss[1] == current_session and ss[2] >= 5:
                session_wr = ss[5]
                # Jeśli pattern w tej sesji ma lepszy/gorszy WR niż globalny, skoryguj
                if session_wr > tw_stats['win_rate'] + 0.1:
                    adj *= 1.15  # bonus za dobrą sesję
                elif session_wr < tw_stats['win_rate'] - 0.1:
                    adj *= 0.85  # kara za złą sesję
                break
    except Exception:
        pass

    # --- KOREKTA KONTEKSTOWA: godzina ---
    try:
        hourly = db.get_hourly_stats(hour)
        direction = pattern.split('_')[0] if '_' in pattern else None
        if direction and hourly:
            for h in hourly:
                # h = (hour, direction, count, wins, losses, win_rate)
                if h[1] == direction and h[2] >= 5:
                    hourly_wr = h[5]
                    if hourly_wr < 0.35:
                        adj *= 0.7  # godzina z niskim WR
                    elif hourly_wr > 0.65:
                        adj *= 1.2  # godzina z wysokim WR
                    break
    except Exception:
        pass

    # --- KOREKTA KONTEKSTOWA: setup grade historyczny ---
    try:
        grade_stats = db.get_setup_quality_stats()
        for gs in grade_stats:
            # gs = (grade, direction, count, wins, losses, win_rate, avg_profit)
            if gs[2] >= 10:  # minimum 10 trade'ów
                if gs[5] > 0.65:
                    # Grade z dobrym WR → bonus jeśli nasz pattern pasuje
                    pass  # grade jest oceniany osobno w score_setup_quality
                elif gs[5] < 0.35 and gs[0] == "B":
                    adj *= 0.9  # Grade B ma niski WR historycznie
    except Exception:
        pass

    return max(0.5, min(1.5, adj))


def optimize_parameters():
    """
    Pełny backtest parametrów (risk_percent, min_tp_distance_mult, target_rr)
    na historycznych transakcjach.

    Accelerated: equity simulation uses Numba JIT (10-50x faster).
    Dane ładowane raz do numpy, JIT-compiled inner loop per combo.
    """
    import numpy as np
    from src.analysis.compute import _equity_simulation_numba

    db = NewsDB()
    trades = db._query("""
        SELECT timestamp, direction, entry, sl, tp, status
        FROM trades
        WHERE status IN ('WIN', 'PROFIT', 'LOSS')
        ORDER BY timestamp ASC
    """)
    if len(trades) < 50:
        return

    # ── Pre-compute trade vectors (done once) ──
    entries    = np.array([t[2] for t in trades], dtype=np.float64)
    sls        = np.array([t[3] for t in trades], dtype=np.float64)
    tps        = np.array([t[4] for t in trades], dtype=np.float64)
    is_profit  = np.array([t[5] in ("WIN", "PROFIT") for t in trades], dtype=bool)

    dists       = np.abs(entries - sls)
    tp_dists    = np.abs(entries - tps)

    # Parametry do testowania
    risk_values = [0.5, 1.0, 1.5, 2.0]
    min_tp_dist_mult_values = [0.5, 1.0, 1.5, 2.0]
    target_rr_values = [1.5, 2.0, 2.5, 3.0]

    best_score = -float('inf')
    best_params = {}

    for risk in risk_values:
        for mult in min_tp_dist_mult_values:
            for rr in target_rr_values:
                # Numba JIT: vectorized filter + sequential equity sim in compiled code
                equity, total_trades = _equity_simulation_numba(
                    dists, tp_dists, is_profit, risk, mult, rr, 10000.0
                )

                if total_trades == 0:
                    continue

                avg_profit = (equity - 10000.0) / total_trades
                if avg_profit > best_score:
                    best_score = avg_profit
                    best_params = {
                        "risk_percent": risk,
                        "min_tp_distance_mult": mult,
                        "target_rr": rr
                    }

    # Zapisz najlepsze parametry
    for name, value in best_params.items():
        db.set_param(name, value)
    # Mirror target_rr → tp_to_sl_ratio (production reads tp_to_sl_ratio in finance.py)
    if 'target_rr' in best_params:
        db.set_param('tp_to_sl_ratio', best_params['target_rr'])
    logger.info(f"[BACKTEST] Zoptymalizowano parametry: {best_params} (score: {best_score:.2f})")

def auto_tune_pattern_weights():
    """
    Analizuje statystyki wzorców i zapisuje dynamiczne wagi.
    Wagi mogą być używane przez AI lub przy generowaniu sygnałów.
    """
    db = NewsDB()
    patterns = db.get_all_patterns_stats()
    for pattern, count, wins, losses, win_rate in patterns:
        if count >= 5:
            # Waga = win_rate * 2 (max 1.5, min 0.5)
            weight = win_rate * 2
            weight = max(0.5, min(1.5, weight))
            db.set_param(f"pattern_weight_{pattern}", weight)
        else:
            # Za mało danych – domyślnie 1.0
            db.set_param(f"pattern_weight_{pattern}", 1.0)

def run_learning_cycle():
    # 2026-05-04 fix: legacy `optimize_parameters()` is a discrete grid
    # search (4×4×4 = 64 combos) that writes target_rr/risk_percent without
    # holdout validation. When Bayesian (below) rejects its winner due to
    # unprofitable holdout, the grid result was still applied — silent
    # overfit. Skipped now; Bayesian is the canonical optimizer with
    # train/holdout split. Use ENABLE_BAYES=0 + ENABLE_GRID=1 to revert.
    import os as _os
    if _os.environ.get("ENABLE_GRID") == "1":
        optimize_parameters()
    auto_tune_pattern_weights()
    if ENABLE_BAYES:
        from src.learning.bayesian_opt import BayesianOptimizer
        from src.core.database import NewsDB
        import numpy as np
        from src.analysis.compute import _equity_sim_with_drawdown_numba

        # Load trades ONCE (not per-iteration — was causing N*20 DB queries)
        _bayes_db = NewsDB()
        _bayes_trades = _bayes_db._query("""
            SELECT direction, entry, sl, tp, status
            FROM trades
            WHERE status IN ('WIN', 'PROFIT', 'LOSS')
            ORDER BY timestamp ASC
        """)

        if len(_bayes_trades) >= 20:
            # Pre-compute vectors
            _b_entries   = np.array([t[1] for t in _bayes_trades], dtype=np.float64)
            _b_sls       = np.array([t[2] for t in _bayes_trades], dtype=np.float64)
            _b_tps       = np.array([t[3] for t in _bayes_trades], dtype=np.float64)
            _b_is_profit = np.array([t[4] in ("WIN", "PROFIT") for t in _bayes_trades], dtype=bool)
            _b_dists     = np.abs(_b_entries - _b_sls)
            _b_tp_dists  = np.abs(_b_entries - _b_tps)

            # Split: 70% train, 30% holdout for out-of-sample validation
            n_total = len(_bayes_trades)
            n_train = int(n_total * 0.7)
            train_dists, holdout_dists = _b_dists[:n_train], _b_dists[n_train:]
            train_tp, holdout_tp = _b_tp_dists[:n_train], _b_tp_dists[n_train:]
            train_profit, holdout_profit = _b_is_profit[:n_train], _b_is_profit[n_train:]

            def objective(params):
                risk = params.get('risk_percent', 1.0)
                min_tp_mult = params.get('min_tp_distance_mult', 1.0)
                target_rr = params.get('target_rr', 2.5)

                # Optimize on TRAIN set only
                equity, max_drawdown = _equity_sim_with_drawdown_numba(
                    train_dists, train_tp, train_profit,
                    risk, min_tp_mult, target_rr, 10000.0
                )

                dd_penalty = max(0, 1 - max_drawdown * 2)
                return equity * dd_penalty

            bounds = {
                'risk_percent': (0.5, 2.0),
                'min_tp_distance_mult': (0.5, 2.0),
                'target_rr': (1.5, 3.5),
                'min_score': (3.0, 7.0),
                'sl_atr_multiplier': (1.0, 2.5),
                'sl_min_distance': (3.0, 8.0),
            }
            opt = BayesianOptimizer(bounds, objective, n_init=10, n_iter=40)
            best_params, best_score = opt.optimize()

            # Validate on HOLDOUT set before applying
            holdout_equity, holdout_dd = _equity_sim_with_drawdown_numba(
                holdout_dists, holdout_tp, holdout_profit,
                best_params.get('risk_percent', 1.0),
                best_params.get('min_tp_distance_mult', 1.0),
                best_params.get('target_rr', 2.5),
                10000.0
            )
            holdout_profitable = holdout_equity > 10000.0

            # 2026-05-04: also require WALK-FORWARD validation pass.
            # Holdout-profitable alone is necessary but not sufficient;
            # if recent fold WR collapsed (regime shift), don't tune to it.
            wf_pass = True
            try:
                import subprocess as _sub
                from pathlib import Path as _P
                _root = _P(__file__).resolve().parents[2]
                _wfv = _root / "scripts" / "walk_forward_validator.py"
                if _wfv.exists():
                    res = _sub.run(
                        [sys.executable, str(_wfv), "--db", "live"],
                        capture_output=True, text=True, timeout=60,
                        cwd=str(_root),
                    )
                    # Exit code 1 = walk-forward alarm
                    wf_pass = (res.returncode == 0)
                    if not wf_pass:
                        logger.warning(
                            "Bayesian REJECTED: walk-forward validator alarm. "
                            "Recent fold deviates from older folds — likely regime shift. "
                            "Keeping current params."
                        )
            except Exception as _wfe:
                logger.debug(f"walk-forward validation skipped: {_wfe}")

            if holdout_profitable and wf_pass:
                db = NewsDB()
                for name, val in best_params.items():
                    db.set_param(name, val)
                # Mirror target_rr → tp_to_sl_ratio: production reads tp_to_sl_ratio
                # in finance.py:119 but the optimizer only objects on target_rr,
                # so they must be coupled or live trading sees a stale value.
                if 'target_rr' in best_params:
                    db.set_param('tp_to_sl_ratio', best_params['target_rr'])
                logger.info(
                    f"Bayesian optimization APPLIED: {best_params} "
                    f"(train={best_score:.0f}, holdout={holdout_equity:.0f}, holdout_dd={holdout_dd:.1%})"
                )
            else:
                logger.warning(
                    f"Bayesian optimization REJECTED — holdout unprofitable "
                    f"(equity={holdout_equity:.0f}, dd={holdout_dd:.1%}). Keeping current params."
                )
        else:
            logger.info(f"Bayesian optimization skipped: {len(_bayes_trades)} trades < 20 minimum")



def classify_loss(trade_id: int) -> str:
    """
    Klasyfikuje typ straty na podstawie condition_at_loss i parametrów trade'a.
    Zwraca pattern_type: 'sl_too_tight', 'wrong_direction', 'timing', 'news_spike', 'unknown'.
    Zapisuje do loss_patterns w bazie.
    """
    db = NewsDB()
    row = db._query_one(
        "SELECT direction, entry, sl, tp, condition_at_loss, factors, rsi, trend FROM trades WHERE id = ?",
        (trade_id,)
    )
    if not row:
        return "unknown"

    direction, entry, sl, tp, condition, factors_json, rsi, trend = row
    import json
    factors = json.loads(factors_json) if factors_json else {}

    entry_f = float(entry or 0)
    sl_f = float(sl or 0)
    tp_f = float(tp or 0)
    sl_dist = abs(entry_f - sl_f) if entry_f and sl_f else 0
    tp_dist = abs(entry_f - tp_f) if entry_f and tp_f else 0

    pattern_type = "unknown"
    description = ""

    # --- KLASYFIKACJA ---

    # 1. SL za ciasny — cena prawie dotarła do TP ale cofnęła się do SL
    # Indykator: TP daleko, ale SL bliski (niski R:R efektywny)
    if sl_dist > 0 and tp_dist > 0:
        rr = tp_dist / sl_dist
        if rr > 3.0 and sl_dist < 8.0:
            pattern_type = "sl_too_tight"
            description = f"SL={sl_dist:.1f}$ za ciasny przy TP={tp_dist:.1f}$ (R:R={rr:.1f})"

    # 2. Wrong direction — trend i direction się nie zgadzają
    if direction and trend:
        dir_clean = str(direction).strip().upper()
        if ("LONG" in dir_clean and trend == "bear") or ("SHORT" in dir_clean and trend == "bull"):
            pattern_type = "wrong_direction"
            description = f"Trade {dir_clean} przeciw trendowi {trend}"

    # 3. Timing — wejście w złej sesji / godzinie
    # Sprawdzamy condition_at_loss po RSI extreme
    if condition and rsi:
        rsi_val = float(rsi) if rsi else 50
        if rsi_val > 75 and "LONG" in str(direction).upper():
            pattern_type = "timing"
            description = f"LONG przy RSI={rsi_val:.0f} (wykupiony)"
        elif rsi_val < 25 and "SHORT" in str(direction).upper():
            pattern_type = "timing"
            description = f"SHORT przy RSI={rsi_val:.0f} (wyprzedany)"

    # 4. Brak konfluencji — za mało czynników
    if len(factors) <= 2:
        pattern_type = "low_confluence"
        description = f"Tylko {len(factors)} czynników: {list(factors.keys())}"

    # Zapisz do bazy
    dir_clean = str(direction).strip().upper() if direction else "UNKNOWN"
    db.update_loss_pattern(pattern_type, dir_clean, description)
    logger.info(f"📝 Loss classified: {pattern_type} — {description}")

    return pattern_type


def check_loss_pattern_match(analysis_data: dict, direction: str) -> dict | None:
    """
    Sprawdza czy obecne warunki rynkowe pasują do historycznych wzorców strat.
    Jeśli pasują do wzorca z >= 3 wystąpieniami → zwraca warning.
    Nie blokuje trade'a (to robi caller), tylko informuje.

    Returns:
        dict z pattern_type i count, lub None jeśli nie znaleziono dopasowania
    """
    db = NewsDB()
    loss_patterns = db.get_loss_patterns(direction, min_count=3)
    if not loss_patterns:
        return None

    rsi = analysis_data.get('rsi', 50)
    trend = analysis_data.get('trend', '')

    for pattern_type, pat_dir, count, description in loss_patterns:
        # Sprawdź czy obecne warunki pasują
        if pattern_type == "wrong_direction":
            if (direction == "LONG" and trend == "bear") or \
               (direction == "SHORT" and trend == "bull"):
                return {"pattern_type": pattern_type, "count": count, "desc": description}

        elif pattern_type == "timing":
            if (direction == "LONG" and rsi > 72) or \
               (direction == "SHORT" and rsi < 28):
                return {"pattern_type": pattern_type, "count": count, "desc": description}

        elif pattern_type == "low_confluence":
            # Ten pattern jest sprawdzany przez setup quality scoring
            pass

    return None


def update_factor_weights(trade_id, outcome):
    """
    Update factor weights using Thompson Sampling (Beta-Bernoulli bandit).

    Each factor tracks (alpha, beta) = (wins, losses) when present in a trade.
    Weight = sample from Beta(alpha, beta) — naturally balances explore/exploit.

    2026-05-04 night: 3 hardenings vs the original Thompson loop.
      1. TIMEOUT/BREAKEVEN trades skipped — they're inconclusive
         (max_horizon hit before SL/TP). Learning from them muddies signal.
      2. Confidence-weighted update — α/β increment by ensemble_confidence
         (clamped to [0.4, 1.5]) instead of always 1.0. High-conf wins
         amplify factor reward; low-conf wins barely move it.
      3. Atomic read+write — full per-factor get+set inside _db_locked()
         so two concurrent resolves can't corrupt α/β counts.
    """
    if outcome not in ("WIN", "LOSS", "PROFIT"):
        return

    db = NewsDB()
    factors = db.get_trade_factors(trade_id)
    if not factors:
        return

    is_win = outcome in ("WIN", "PROFIT")

    conf_row = db._query_one(
        "SELECT confidence FROM ml_predictions WHERE trade_id = ? "
        "ORDER BY timestamp DESC LIMIT 1",
        (trade_id,),
    )
    raw_conf = float(conf_row[0]) if conf_row and conf_row[0] is not None else 1.0
    update_strength = max(0.4, min(1.5, raw_conf))

    NEUTRAL_SAMPLE = 0.2

    for factor, present in factors.items():
        if not present:
            continue

        alpha_key = f"factor_alpha_{factor}"
        beta_key = f"factor_beta_{factor}"
        weight_name = f"weight_{factor}"

        with _db_locked():
            alpha = float(db.get_param(alpha_key, 1.0))
            beta_val = float(db.get_param(beta_key, 1.0))

            if is_win:
                alpha += update_strength
            else:
                beta_val += update_strength

            db.set_param(alpha_key, alpha)
            db.set_param(beta_key, beta_val)

            n_observed = (alpha - 1) + (beta_val - 1)
            sampled_weight = random.betavariate(max(alpha, 0.1), max(beta_val, 0.1))
            if n_observed < 20:
                blend = n_observed / 20.0
                sampled_weight = blend * sampled_weight + (1 - blend) * NEUTRAL_SAMPLE

            weight = 0.5 + sampled_weight * 2.5
            db.set_param(weight_name, round(weight, 3))
