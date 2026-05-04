"""
scripts/trade_explainer.py — per-trade root-cause analysis using all
2026-05-04 session findings.

For each closed trade, scores the setup against multiple known
risk dimensions:
  - Factor predictive power (bos +21.8pp, macro -13.9pp, choch -13.1pp, etc.)
  - Toxic pairs (choch+ob_count, fvg+ob_count)
  - Session WR (overlap good, london bad)
  - A+ grade trap (target_rr=3.0 too wide)
  - Direction-regime mismatch (SHORT in zielony, LONG in czerwony)

Output: per-trade verdict + risk score + which findings applied.

Differs from llm_journal.py (LLM narrative) by being deterministic
rules-based — fast, free, reproducible.

Usage:
    python scripts/trade_explainer.py [--n 20] [--status LOSS] [--db both]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# Findings from today's audit + factor_predictive + wr_cube + sl_tp_analyzer
FACTOR_DELTA_PP = {
    "bos": +21.8,           # only significant edge
    "pin_bar": +19.8,       # promising but small N
    "macro": -13.9,
    "choch": -13.1,
    "killzone": -9.5,
    "fvg": -7.9,
    "ob_count": -17.7,
}

TOXIC_PAIRS = [
    ("choch", "ob_count", -16.0),  # N=30 WR 16.7%
    ("choch", "killzone", -10.0),
    ("fvg", "ob_count", -11.0),
]

SESSION_WR = {
    "overlap": 51.5,
    "new_york": 34.6,
    "off_hours": 20.0,
    "asian": 16.7,
    "london": 14.3,
}
COHORT_WR = 32.7  # baseline N=121

# Per-grade targets
GRADE_RR = {"A+": 3.0, "A": 2.5, "B": 2.0, "C": 0}


def fetch(db_path: str, n: int, status: str | None) -> list[dict]:
    conn = sqlite3.connect(db_path)
    where = "status IN ('WIN','LOSS','TIMEOUT','BREAKEVEN')"
    if status:
        where = f"status = '{status}'"
    rows = conn.execute(
        f"""SELECT id, timestamp, direction, status, profit, factors,
                   setup_grade, setup_score, session, pattern
            FROM trades WHERE {where}
            ORDER BY id DESC LIMIT ?""",
        (n,)
    ).fetchall()
    out = []
    for r in rows:
        try:
            f = json.loads(r[5]) if r[5] else {}
        except Exception:
            f = {}
        out.append({
            "id": r[0], "ts": r[1], "direction": r[2], "status": r[3],
            "profit": r[4] or 0,
            "factors": set(k for k, v in f.items() if v and not k.endswith("_penalty")),
            "grade": r[6], "score": r[7],
            "session": r[8], "pattern": r[9],
        })
    conn.close()
    return out


def explain_trade(t: dict) -> dict:
    """Return dict with risk_score (0-100, higher = more risky pre-entry)
    and a list of factor explanations."""
    risk_score = 0
    flags = []

    # 1. Factor delta (sum of WR-pp impact for each factor present)
    factor_pp = 0
    for f in t["factors"]:
        delta = FACTOR_DELTA_PP.get(f, 0)
        if delta != 0:
            factor_pp += delta
            if delta < -10:
                flags.append(f"factor:{f} ({delta:+.0f}pp WR)")
    if factor_pp < -20:
        risk_score += 30
        flags.append(f"factor stack -{abs(factor_pp):.0f}pp aggregate")

    # 2. Toxic pairs
    for f1, f2, _ in TOXIC_PAIRS:
        if f1 in t["factors"] and f2 in t["factors"]:
            risk_score += 25
            flags.append(f"toxic_pair:{f1}+{f2}")

    # 3. Session
    sess = (t.get("session") or "").lower()
    sess_wr = SESSION_WR.get(sess, COHORT_WR)
    if sess_wr < 25:
        risk_score += 20
        flags.append(f"session:{sess} WR {sess_wr:.0f}%")
    elif sess_wr > 45:
        risk_score -= 10
        flags.append(f"session:{sess} GOOD WR {sess_wr:.0f}%")

    # 4. Grade trap
    g = t.get("grade")
    rr = GRADE_RR.get(g, 2.0)
    if g == "A+" and rr >= 3.0:
        risk_score += 15
        flags.append(f"grade:A+ target_rr={rr} (wide TP trap)")

    # 5. Direction signal
    if t["direction"] == "LONG" and "ichimoku_bear" in t["factors"]:
        risk_score += 20
        flags.append("direction_conflict:LONG with bearish ichimoku")
    elif t["direction"] == "SHORT" and "ichimoku_bull" in t["factors"]:
        risk_score += 20
        flags.append("direction_conflict:SHORT with bullish ichimoku")

    # bos always positive — credit
    if "bos" in t["factors"]:
        risk_score -= 15
        flags.append("factor:bos GOOD (+21.8pp)")

    # Verdict
    if risk_score >= 50:
        verdict = "HIGH RISK — should not have fired"
    elif risk_score >= 30:
        verdict = "MEDIUM RISK — borderline"
    elif risk_score >= 10:
        verdict = "LOW RISK — quality setup"
    else:
        verdict = "NEGATIVE RISK — premium setup"

    # Outcome match
    is_win = t["status"] == "WIN"
    if is_win and risk_score >= 30:
        outcome_match = "LUCKY (won despite high risk)"
    elif not is_win and risk_score >= 30:
        outcome_match = "EXPECTED LOSS (high risk score predicted)"
    elif is_win and risk_score < 30:
        outcome_match = "EXPECTED WIN (low risk score)"
    else:
        outcome_match = "VARIANCE LOSS (low risk but lost)"

    return {
        "risk_score": risk_score,
        "verdict": verdict,
        "outcome_match": outcome_match,
        "flags": flags,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--status", choices=["WIN", "LOSS"], default=None)
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="live")
    args = ap.parse_args()

    trades = []
    if args.db in ("live", "both"):
        trades.extend(fetch("data/sentinel.db", args.n, args.status))
    if args.db in ("backtest", "both"):
        trades.extend(fetch("data/backtest.db", args.n, args.status))

    if not trades:
        print("No trades.")
        return

    print(f"=== TRADE EXPLAINER on {len(trades)} trade(s) ===\n")
    print(f"Risk model based on 2026-05-04 session findings:\n"
          f"  Factor deltas (top): bos +21.8, ob_count -17.7, macro -13.9, choch -13.1\n"
          f"  Toxic pairs: choch+ob_count -16, fvg+ob_count -11\n"
          f"  Session WR: overlap 51.5% / london 14.3%\n"
          f"  A+ grade target_rr=3.0 trap\n")

    by_outcome = {"EXPECTED WIN": 0, "EXPECTED LOSS": 0, "LUCKY": 0, "VARIANCE LOSS": 0}
    for t in trades:
        e = explain_trade(t)
        oc = e["outcome_match"].split(" ")[0:2]
        oc_key = " ".join(oc)
        if "LUCKY" in e["outcome_match"]:
            by_outcome["LUCKY"] += 1
        elif "VARIANCE" in e["outcome_match"]:
            by_outcome["VARIANCE LOSS"] += 1
        elif "EXPECTED WIN" in e["outcome_match"]:
            by_outcome["EXPECTED WIN"] += 1
        else:
            by_outcome["EXPECTED LOSS"] += 1
        print(f"#{t['id']:>5} {t['direction']:<5} {t['status']:<5} ${t['profit']:>+7.2f}  "
              f"risk={e['risk_score']:>3}  {e['verdict']}")
        print(f"      {e['outcome_match']}")
        if e["flags"]:
            print(f"      flags: {', '.join(e['flags'][:5])}")
            if len(e["flags"]) > 5:
                print(f"      ... +{len(e['flags']) - 5} more")
        print()

    print("=" * 60)
    print("OUTCOME ATTRIBUTION")
    print("=" * 60)
    for k, v in by_outcome.items():
        print(f"  {k:<20} {v}")

    n = len(trades)
    if by_outcome["EXPECTED LOSS"] + by_outcome["EXPECTED WIN"] > 0:
        explained = (by_outcome["EXPECTED LOSS"] + by_outcome["EXPECTED WIN"]) / n * 100
        print(f"\nRisk model explains {explained:.0f}% of outcomes "
              f"({n - by_outcome['LUCKY'] - by_outcome['VARIANCE LOSS']}/{n})")


if __name__ == "__main__":
    main()
