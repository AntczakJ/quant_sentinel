"""
scripts/trade_premortem.py — LLM predicts trade outcome BEFORE entry.

Given a setup's factors + grade + market context, ask gpt-4o-mini
"if we entered this trade now, what's the probability it wins?"
The historical analog: factor combos that have lost N times before
should be flagged.

Two modes:
  1. Live current setup: pulls latest analysis from /api or computes
     factors from ml_predictions row, asks LLM, returns probability.
  2. Historical: takes a closed-trade ID, redacts the outcome, asks
     LLM, compares verdict to actual. Validates the predictor itself.

Mode 2 is the validation step — only after >70% accuracy on closed
trades should mode 1 (live veto) be considered.

Cost: ~$0.001 per call. Cached in `llm_premortem` table by trade_id.

Usage:
    python scripts/trade_premortem.py --validate --n 30   # mode 2
    python scripts/trade_premortem.py --trade-id 222       # one trade
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


SYSTEM_PROMPT = """You are a senior quant trading analyst evaluating a setup
BEFORE the trade is placed. You're given the setup's factors, grade, market
context. Predict whether the trade will WIN or LOSS at the typical 2R target.

Output STRICT JSON. Fields:
  prediction: "WIN" | "LOSS" | "UNCERTAIN"
  confidence: 0.0-1.0
  reasoning: one short sentence (<25 words) why
  red_flags: list of 0-3 strings, factor combos that worry you

Rules:
- Be honest. If signal looks weak or contradictory, say UNCERTAIN.
- Reference factors / regime / session / RSI specifically.
- Don't say "depends" — give a directional verdict or UNCERTAIN.
"""


def init_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_premortem (
            trade_id INTEGER PRIMARY KEY,
            prediction TEXT,
            confidence REAL,
            reasoning TEXT,
            red_flags_json TEXT,
            actual_outcome TEXT,
            correct INTEGER,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def fetch_trade_for_premortem(conn, trade_id: int) -> dict | None:
    """Pull setup context for one trade (no outcome leak in prompt)."""
    row = conn.execute("""
        SELECT t.id, t.timestamp, t.direction, t.entry, t.sl, t.tp,
               t.pattern, t.session, t.setup_grade, t.setup_score,
               t.factors, t.rsi, t.trend, t.structure, t.vol_regime,
               t.spread_at_entry,
               t.status, t.profit
        FROM trades t WHERE t.id = ?
    """, (trade_id,)).fetchone()
    if not row:
        return None
    cols = ["id", "timestamp", "direction", "entry", "sl", "tp",
            "pattern", "session", "setup_grade", "setup_score",
            "factors", "rsi", "trend", "structure", "vol_regime",
            "spread_at_entry", "status", "profit"]
    return dict(zip(cols, row))


def build_premortem_prompt(trade: dict) -> str:
    """No outcome info — just setup context."""
    factors = trade.get("factors") or "{}"
    try:
        factors_d = json.loads(factors) if isinstance(factors, str) else factors
    except Exception:
        factors_d = {}
    rr = abs(trade["tp"] - trade["entry"]) / max(0.01, abs(trade["entry"] - trade["sl"]))
    lines = [
        f"SETUP @ {trade['timestamp']} — {trade['direction']} from {trade['entry']}",
        f"SL={trade['sl']} TP={trade['tp']} R:R={rr:.2f}",
        f"Pattern: {trade.get('pattern')}",
        f"Setup: grade={trade.get('setup_grade')} score={trade.get('setup_score')}",
        f"Session: {trade.get('session')} | Trend: {trade.get('trend')} | Structure: {trade.get('structure')}",
        f"RSI: {trade.get('rsi')} | Vol regime: {trade.get('vol_regime')} | Spread: {trade.get('spread_at_entry')}",
        f"Factors: {list(factors_d.keys()) if factors_d else 'none'}",
    ]
    return "\n".join(lines)


def predict(client, trade: dict, model: str = "gpt-4o-mini") -> dict | None:
    user_prompt = build_premortem_prompt(trade)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=200,
        )
        content = resp.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        print(f"  [WARN] trade #{trade['id']}: {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true",
                    help="Run on N closed trades, compare prediction vs actual")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--trade-id", type=int, default=None,
                    help="One specific trade")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    from openai import OpenAI
    client = OpenAI()
    conn = sqlite3.connect(ROOT / "data" / "sentinel.db")
    init_table(conn)

    if args.trade_id:
        trade_ids = [args.trade_id]
    elif args.validate:
        rows = conn.execute(
            "SELECT id FROM trades WHERE status IN ('WIN','LOSS') "
            "ORDER BY id DESC LIMIT ?", (args.n,)
        ).fetchall()
        trade_ids = [r[0] for r in rows]
    else:
        print("Pass --validate or --trade-id")
        return

    print(f"== PRE-MORTEM on {len(trade_ids)} trade(s) ==\n")

    results = []
    correct = 0
    for tid in trade_ids:
        trade = fetch_trade_for_premortem(conn, tid)
        if not trade:
            continue

        # Cache hit?
        if not args.no_cache:
            cached = conn.execute(
                "SELECT prediction, confidence, reasoning, red_flags_json FROM llm_premortem WHERE trade_id=?",
                (tid,)
            ).fetchone()
            if cached:
                pred = {"prediction": cached[0], "confidence": cached[1],
                        "reasoning": cached[2],
                        "red_flags": json.loads(cached[3]) if cached[3] else []}
                actual = trade.get("status")
                hit = (pred["prediction"] == "WIN" and actual == "WIN") or \
                      (pred["prediction"] == "LOSS" and actual == "LOSS")
                if hit:
                    correct += 1
                results.append((trade, pred, actual, hit))
                marker = "OK" if hit else ("UN" if pred["prediction"] == "UNCERTAIN" else "WRONG")
                print(f"#{tid:>4} {trade['direction']:<5} actual={actual:<5} pred={pred['prediction']:<10} conf={pred['confidence']:.2f}  [{marker}]  (cached)")
                continue

        pred = predict(client, trade)
        if not pred:
            continue
        actual = trade.get("status")
        hit = (pred["prediction"] == "WIN" and actual == "WIN") or \
              (pred["prediction"] == "LOSS" and actual == "LOSS")
        if hit:
            correct += 1
        conn.execute(
            "INSERT OR REPLACE INTO llm_premortem (trade_id, prediction, confidence, reasoning, red_flags_json, actual_outcome, correct) VALUES (?,?,?,?,?,?,?)",
            (tid, pred.get("prediction"), float(pred.get("confidence", 0.0)),
             pred.get("reasoning"), json.dumps(pred.get("red_flags", [])),
             actual, 1 if hit else 0)
        )
        conn.commit()
        results.append((trade, pred, actual, hit))
        marker = "OK" if hit else ("UN" if pred["prediction"] == "UNCERTAIN" else "WRONG")
        print(f"#{tid:>4} {trade['direction']:<5} actual={actual:<5} pred={pred['prediction']:<10} conf={pred['confidence']:.2f}  [{marker}]")
        print(f"      {pred.get('reasoning','')}")

    print("\n" + "=" * 60)
    n_decisive = sum(1 for _, p, _, _ in results if p["prediction"] != "UNCERTAIN")
    n_uncertain = sum(1 for _, p, _, _ in results if p["prediction"] == "UNCERTAIN")
    if n_decisive > 0:
        print(f"Predictor accuracy on decisive verdicts: {correct}/{n_decisive} = {correct/n_decisive*100:.1f}%")
    print(f"Uncertain: {n_uncertain}/{len(results)}")
    print(f"  (Random baseline = 50% — predictor is useful only if >70% on >=20 decisive)")

    conn.close()


if __name__ == "__main__":
    main()
