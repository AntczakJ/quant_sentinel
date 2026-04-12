#!/usr/bin/env python3
"""
train_rl.py — trenowanie agenta RL (Double DQN) na historycznych danych.

Ulepszenia:
- Pobiera 6 miesięcy danych (zamiast 1 miesiąca)
- Jeśli brak 15m, fallback na 1h lub 1d
- Lepszy logging z metrykami per-epizod (win_rate, balance)
- Zapisuje metryki do bazy danych
"""

import sys
import os
import hashlib
import time

# Suppress TF noise + enable optimizations BEFORE importing TF
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '1'

import yfinance as yf
import pandas as pd
import numpy as np
from src.ml.rl_agent import TradingEnv, DQNAgent
from src.core.logger import logger

# Ustawienia trenowania (override: python train_rl.py 500)
EPISODES = 300
SEQ_LEN = 20            # długość okna stanu (liczba świec)
INITIAL_BALANCE = 10000
TRANSACTION_COST = 0.001
NOISE_STD = 0.001       # augmentacja: 0.1% szumu na cenach per epizod
MIN_RETRAIN_HOURS = 12  # minimalny odstęp między treningami na tych samych danych

# Multi-asset training — koszyk symboli dla lepszej generalizacji
# BTC-USD wykluczone: zbyt wysoka volatility (miało sens przed vol_normalize,
#   ale po naprawie TradingEnv możnaby dodać z powrotem — zostawiam jako
#   eksperyment na później).
# ES=F wykluczone: chroniczny loser we WSZYSTKICH modelach (-23 do -44% OOS).
#   S&P futures mają strukturalną dynamikę wymagającą market-wide features
#   (VIX, sektor rotation), których nie mamy w stanie 22-wymiarowym.
SYMBOLS = ["GC=F", "EURUSD=X", "CL=F"]
# GC=F gold, EURUSD=X forex, CL=F crude oil

# Validation early stopping
VAL_EVERY = 20          # waliduj co N epizodów
VAL_PATIENCE = 30       # zatrzymaj jeśli brak poprawy przez N epizodów
# (obniżone z 50 po obserwacji że best val zwykle osiągany ~ep 40,
#  więc czekanie 50 ep po tym to zbędna strata czasu)


def compute_data_hash(df):
    """Hash danych — zmieni się gdy okno czasowe się przesunie."""
    raw = df[['close']].values.tobytes()
    return hashlib.sha256(raw).hexdigest()[:16]


def should_retrain(agent, data_hash, force=False):
    """Sprawdź czy trening ma sens — czy dane się zmieniły lub minął czas."""
    if force:
        return True, "wymuszony trening (--force)"

    last_ts = getattr(agent, '_last_train_ts', 0)
    last_hash = getattr(agent, '_data_hash', None)

    if last_hash is None:
        return True, "brak poprzedniego treningu"

    hours_since = (time.time() - last_ts) / 3600

    if last_hash != data_hash:
        return True, f"dane się zmieniły (nowy hash: {data_hash[:8]})"

    if hours_since >= MIN_RETRAIN_HOURS:
        return True, f"minęło {hours_since:.0f}h od ostatniego treningu"

    return False, (f"dane identyczne, ostatni trening {hours_since:.1f}h temu "
                   f"(min {MIN_RETRAIN_HOURS}h). Użyj --force aby wymusić")

def fetch_historical_data(symbol="GC=F", periods=None, intervals=None):
    """
    Pobiera dane historyczne z yfinance.
    Próbuje kolejne kombinacje period/interval aż znajdzie wystarczająco danych.

    Preferowane: 2y/1h dla szerszej dystrybucji i mniejszego overfitu.
    Fallback: 6mo/15m lub dzień dla symboli z brakiem 1h.
    """
    if periods is None:
        periods = ["2y", "1y", "6mo", "3mo"]
    if intervals is None:
        intervals = ["1h", "1d", "15m"]

    ticker = yf.Ticker(symbol)

    for period in periods:
        for interval in intervals:
            try:
                df = ticker.history(period=period, interval=interval)
                if df is not None and len(df) >= 100:
                    df = df.reset_index()
                    # Normalizuj nazwy kolumn
                    col_map = {c: c.lower() for c in df.columns}
                    df.rename(columns=col_map, inplace=True)

                    required = ['open', 'high', 'low', 'close', 'volume']
                    available = [c for c in required if c in df.columns]
                    df = df[available]

                    print(f"✅ Pobrano {len(df)} świec ({symbol}, {period}, {interval})")
                    return df
            except Exception as e:
                print(f"⚠️ Nie udało się pobrać {period}/{interval}: {e}")
                continue

    raise ValueError(f"Nie udało się pobrać danych dla {symbol}")


def fetch_multi_asset_data(symbols=None):
    """Pobiera dane dla wielu symboli. Zwraca dict {symbol: df}.
    Pomija symbole, dla których nie udało się pobrać danych."""
    if symbols is None:
        symbols = SYMBOLS

    results = {}
    for sym in symbols:
        try:
            df = fetch_historical_data(symbol=sym)
            if df is not None and not df.empty:
                results[sym] = df
        except Exception as e:
            print(f"⚠️ Pominięto {sym}: {e}")

    if not results:
        raise ValueError("Nie udało się pobrać żadnego symbolu")

    print(f"✅ Multi-asset: {len(results)}/{len(symbols)} symboli pobranych")
    return results


def evaluate_agent(agent, val_env):
    """Eval agenta na val_env z epsilon=0 (czysta exploitacja).
    Zwraca (val_return_pct, val_win_rate, val_trades, val_balance)."""
    old_epsilon = agent.epsilon
    agent.epsilon = 0.0
    state = val_env.reset()
    done = False
    info = {}
    while not done:
        action = agent.act(state)
        state, _, done, info = val_env.step(action)
    agent.epsilon = old_epsilon

    val_balance = info.get('balance', INITIAL_BALANCE)
    val_return = (val_balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100
    val_trades = info.get('total_trades', 0)
    val_win_rate = info.get('win_rate', 0) * 100
    return val_return, val_win_rate, val_trades, val_balance


def main():
    global EPISODES
    force_train = "--force" in sys.argv
    for arg in sys.argv[1:]:
        if arg != "--force":
            try:
                EPISODES = int(arg)
            except ValueError:
                pass

    print("=" * 60)
    print(f"🧠 TRENOWANIE AGENTA RL (Double DQN) — {EPISODES} epizodów")
    print("=" * 60)

    # 1. Pobierz dane (multi-asset)
    print("\n📊 Pobieranie danych multi-asset...")
    asset_data = fetch_multi_asset_data()

    # Hash z cen close wszystkich symboli (stabilny pomimo różnej kolejności)
    import hashlib
    combined = b''.join(
        df[['close']].values.tobytes() for sym, df in sorted(asset_data.items())
    )
    data_hash = hashlib.sha256(combined).hexdigest()[:16]

    # 2. Podział train/val (80/20) per symbol — stwórz envs
    train_envs = {}
    val_envs = {}
    state_size = None
    for sym, df in asset_data.items():
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx].reset_index(drop=True)
        val_df = df.iloc[split_idx:].reset_index(drop=True)
        if len(train_df) < 50 or len(val_df) < 20:
            print(f"⚠️ {sym}: za mało danych ({len(train_df)}/{len(val_df)}), pomijam")
            continue
        train_envs[sym] = TradingEnv(train_df, initial_balance=INITIAL_BALANCE,
                                     transaction_cost=TRANSACTION_COST, noise_std=NOISE_STD,
                                     vol_normalize=True)
        val_envs[sym] = TradingEnv(val_df, initial_balance=INITIAL_BALANCE,
                                   transaction_cost=TRANSACTION_COST, noise_std=0.0,
                                   vol_normalize=True)
        if state_size is None:
            state_size = len(train_envs[sym].reset())
        print(f"  📈 {sym}: train={len(train_df)} | val={len(val_df)}")

    if not train_envs:
        logger.error("Brak envs do treningu.")
        return

    action_size = 3  # hold, buy, sell
    symbols_list = list(train_envs.keys())

    # 3. Zainicjuj agenta (z resume jeśli istnieje checkpoint)
    agent = DQNAgent(state_size, action_size)
    checkpoint_path = "models/rl_agent.keras"
    resumed = False
    if os.path.exists(checkpoint_path) and os.path.exists(checkpoint_path + '.params'):
        try:
            agent.load(checkpoint_path)
            resumed = True
            print(f"🔄 Wznowiono z checkpointu: ε={agent.epsilon:.3f}, "
                  f"train_step={agent.train_step}, memory={len(agent.memory)}")
        except Exception as e:
            print(f"⚠️ Nie udało się wczytać checkpointu ({e}) — trening od zera")
            agent = DQNAgent(state_size, action_size)

    # 4. Sprawdź czy trening ma sens
    if resumed:
        ok, reason = should_retrain(agent, data_hash, force=force_train)
        if not ok:
            print(f"\n⏭️  Pominięto trening: {reason}")
            return
        print(f"📋 Powód treningu: {reason}")

    if not resumed:
        print(f"🤖 Agent: state_size={state_size}, action_size={action_size}")
    print(f"🔧 PER + N-step + Multi-asset ({len(symbols_list)} symboli) + noise={NOISE_STD}")

    # 5. Trenowanie z rotacją symboli + early stopping
    scores = []
    best_reward = -float('inf')
    best_balance = 0
    best_win_rate = 0
    best_val_return = -float('inf')
    best_weights = None
    no_improve = 0
    info = {}

    import gc
    import random as _random
    import time as _time
    import json as _json

    # Heartbeat path — the API reads this to surface live progress in the UI.
    # File is rewritten on each episode; absence (or stale mtime) means no
    # training is active.
    _heartbeat_path = "data/training_heartbeat.json"
    _train_start = _time.time()

    def _write_heartbeat(ep: int, reward: float, avg_reward: float,
                         balance_: float, wr_: float, eps_: float) -> None:
        try:
            elapsed = _time.time() - _train_start
            per_ep = elapsed / max(1, ep)
            eta_sec = per_ep * (EPISODES - ep)
            payload = {
                "status": "running",
                "current_episode": ep,
                "total_episodes": EPISODES,
                "last_reward": float(reward),
                "avg_reward_20": float(avg_reward),
                "balance": float(balance_),
                "win_rate_pct": float(wr_),
                "epsilon": float(eps_),
                "elapsed_sec": elapsed,
                "eta_sec": eta_sec,
                "updated_at": _time.time(),
            }
            import os as _os2
            _os2.makedirs("data", exist_ok=True)
            with open(_heartbeat_path, "w", encoding="utf-8") as _f:
                _json.dump(payload, _f)
        except Exception:
            pass  # Heartbeat failure must never stop training.

    early_stopped = False
    for episode in range(EPISODES):
        # Multi-asset: losowy symbol per epizod
        sym = _random.choice(symbols_list)
        env = train_envs[sym]
        state = env.reset()

        total_reward = 0
        done = False
        step = 0
        replay_count = 0
        while not done:
            action = agent.act(state)
            next_state, reward, done, info = env.step(action)
            agent.remember(state, action, reward, next_state, done)
            state = next_state
            total_reward += reward
            step += 1
            if step % 8 == 0 and replay_count < 40 and len(agent.memory) >= 256:
                agent.replay(batch_size=32)
                replay_count += 1

        scores.append(total_reward)
        avg = np.mean(scores[-min(20, len(scores)):])
        win_rate = info.get('win_rate', 0) * 100
        balance = info.get('balance', INITIAL_BALANCE)

        if total_reward > best_reward:
            best_reward = total_reward
            best_balance = balance
            best_win_rate = win_rate

        agent.update_lr(episode, EPISODES)

        print(f"  [{episode+1}/{EPISODES}] sym={sym} reward={total_reward:.2f} "
              f"bal=${balance:.0f} ε={agent.epsilon:.3f} replays={replay_count}", flush=True)

        # Non-blocking live progress signal for the UI widget.
        _write_heartbeat(
            episode + 1, total_reward, float(avg),
            float(balance), win_rate, agent.epsilon,
        )

        # Walidacja co VAL_EVERY epizodów (na wszystkich symbolach)
        if (episode + 1) % VAL_EVERY == 0 and (episode + 1) >= VAL_EVERY:
            val_returns = []
            for vsym, venv in val_envs.items():
                vr, _, _, _ = evaluate_agent(agent, venv)
                val_returns.append(vr)
            mean_val_return = np.mean(val_returns)

            if mean_val_return > best_val_return:
                best_val_return = mean_val_return
                best_weights = agent.model.get_weights()
                no_improve = 0
                marker = "⭐ NEW BEST"
            else:
                no_improve += VAL_EVERY
                marker = f"(no improve {no_improve}/{VAL_PATIENCE})"
            print(f"  📊 Val mean={mean_val_return:+.2f}% (best {best_val_return:+.2f}%) {marker}",
                  flush=True)

            if no_improve >= VAL_PATIENCE and (episode + 1) >= 100:
                print(f"  ⚡ Early stop @ ep {episode+1} — przywracam best weights")
                if best_weights is not None:
                    agent.model.set_weights(best_weights)
                    agent._sync_target_hard()
                early_stopped = True
                break

        # Status i checkpoint co 50 epizodów
        if (episode + 1) % 50 == 0:
            logger.info(
                f"═══ Ep {episode+1}/{EPISODES} ═══ "
                f"avg_reward={avg:.4f} | best_val={best_val_return:+.2f}% | "
                f"trades={info.get('total_trades', 0)} | wr={win_rate:.0f}% | "
                f"ε={agent.epsilon:.3f}"
            )
            try:
                agent.save("models/rl_agent.keras", data_hash=data_hash)
                print(f"  💾 Checkpoint saved (ep {episode+1})", flush=True)
            except Exception as e:
                print(f"  ⚠️ Checkpoint save failed: {e}", flush=True)

        if (episode + 1) % 100 == 0:
            gc.collect()

    # 6. Końcowa walidacja per-symbol na danych out-of-sample
    print("\n📊 Walidacja końcowa (out-of-sample, per symbol):")
    all_returns = []
    all_win_rates = []
    total_trades_all = 0
    for vsym, venv in val_envs.items():
        vr, vwr, vt, vb = evaluate_agent(agent, venv)
        all_returns.append(vr)
        all_win_rates.append(vwr)
        total_trades_all += vt
        print(f"   {vsym}: ${vb:.0f} ({vr:+.1f}%) | trades={vt} | WR={vwr:.0f}%")

    val_return = float(np.mean(all_returns)) if all_returns else 0.0
    val_win_rate = float(np.mean(all_win_rates)) if all_win_rates else 0.0
    val_balance = INITIAL_BALANCE * (1 + val_return / 100)
    val_trades = total_trades_all

    print(f"📈 Średnia walidacji: {val_return:+.2f}% | "
          f"WR={val_win_rate:.0f}% | total trades={val_trades}")
    if early_stopped:
        print(f"   (early-stopped, best val był {best_val_return:+.2f}%)")

    # 8. Zapisz model
    os.makedirs("models", exist_ok=True)
    model_path = "models/rl_agent.keras"
    agent.save(model_path, data_hash=data_hash)
    logger.info(f"Model zapisany do {model_path}")

    # 8b. Regeneruj ONNX dla GPU inference (DirectML)
    try:
        from src.analysis.compute import convert_keras_to_onnx
        onnx_path = convert_keras_to_onnx(model_path, "models/rl_agent.onnx")
        if onnx_path:
            print(f"   ONNX zregenerowany: {onnx_path}")
    except Exception as e:
        print(f"   Ostrzezenie: ONNX regen nieudany ({e}) — stary .onnx pozostaje")

    # 9. Zapisz metryki do bazy
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        db.set_param("rl_best_reward", best_reward)
        db.set_param("rl_best_win_rate", best_win_rate)
        db.set_param("rl_val_return", val_return)
        db.set_param("rl_val_win_rate", val_win_rate)
        prev_episodes = db.get_param("rl_episodes_trained") or 0
        try:
            prev_episodes = int(float(prev_episodes))
        except (ValueError, TypeError):
            prev_episodes = 0
        db.set_param("rl_episodes_trained", prev_episodes + EPISODES)
        print("📝 Metryki zapisane do bazy.")
    except Exception as e:
        print(f"⚠️ Nie udało się zapisać metryk: {e}")

    # 10. Log run do training registry (historia eksperymentów)
    try:
        from src.ml.training_registry import log_training_run
        per_symbol = {}
        for sym, venv in val_envs.items():
            vr, vwr, vt, vb = evaluate_agent(agent, venv)
            per_symbol[sym] = {"return_pct": round(vr, 2), "win_rate": round(vwr, 1),
                              "trades": vt, "balance": round(vb, 2)}
        log_training_run(
            model_type="rl_agent",
            hyperparams={
                "episodes": EPISODES,
                "episodes_completed": len(scores),
                "early_stopped": early_stopped,
                "vol_normalize": True,
                "noise_std": NOISE_STD,
                "val_every": VAL_EVERY,
                "val_patience": VAL_PATIENCE,
                "memory_maxlen": agent.memory.maxlen,
                "tau": agent.tau,
                "target_update_freq": agent.target_update_freq,
                "epsilon_final": round(agent.epsilon, 4),
            },
            data_signature={
                "symbols": list(val_envs.keys()),
                "data_hash": data_hash,
                "train_samples_per_symbol": {s: len(e._base_prices) for s, e in train_envs.items()},
            },
            metrics={
                "val_return": round(val_return, 2),
                "val_win_rate": round(val_win_rate, 1),
                "val_trades": val_trades,
                "best_val_return": round(best_val_return, 2),
                "best_reward": round(best_reward, 4),
                "best_win_rate": round(best_win_rate, 1),
                "per_symbol": per_symbol,
            },
            artifact_path=model_path,
        )
    except Exception as e:
        print(f"⚠️ Training registry log failed: {e}")

    print("\n✅ Trenowanie zakończone.")
    print(f"   Najlepsza nagroda: {best_reward:.4f}")
    print(f"   Walidacja: ${val_balance:.0f} ({val_return:+.1f}%)")
    print(f"   Win rate (val): {val_win_rate:.0f}%")

if __name__ == "__main__":
    main()
