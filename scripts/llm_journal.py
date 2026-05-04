"""
scripts/llm_journal.py — LLM-powered trade journal auto-analysis.

For each recent closed trade, builds a context bundle (trade params, ML
predictions, factor breakdown, regime) and asks gpt-4o-mini for a
structured post-mortem: verdict, root_cause, lesson_learned.

Then aggregates across trades to surface recurring themes.

Usage:
    python scripts/llm_journal.py [--n 10] [--status LOSS] [--write-md]

Output: prints to stdout + optionally writes reports/journal_<date>.md.

Cost: ~$0.003 per trade × N trades. Cached in trade_journal table by
trade_id so reruns are free.
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


SYSTEM_PROMPT = """You are a senior quant trading analyst reviewing a closed trade.
Output STRICT JSON only, no prose, no markdown. Fields:
  verdict: "good_setup_bad_outcome" | "bad_setup_correct_loss" | "good_setup_good_win" | "lucky_win"
  root_cause: 1 short sentence (<25 words) — what drove the outcome
  lesson: 1 short sentence (<25 words) — what to do differently/repeat
  confidence: 0.0-1.0 — how confident you are in the verdict given limited info

Rules:
- Be honest. If signal looks weak, say so even on a win (lucky_win).
- Reference specific factors/voters when relevant.
- Don't speculate beyond what's provided.
"""


def init_journal_table(conn):
    # Distinct from legacy `trade_journal` (manual rationale/emotion/lesson/notes).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_trade_journal (
            trade_id INTEGER PRIMARY KEY,
            verdict TEXT,
            root_cause TEXT,
            lesson TEXT,
            confidence REAL,
            llm_model TEXT,
            analysis_json TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def fetch_trades_with_context(conn, n: int, status_filter: str | None):
    """Pull recent closed trades + joined ML predictions."""
    where = "t.status IN ('WIN', 'LOSS', 'TIMEOUT')"
    if status_filter:
        where = f"t.status = '{status_filter}'"
    sql = f"""
        SELECT t.id, t.timestamp, t.direction, t.entry, t.sl, t.tp,
               t.status, t.profit, t.pattern, t.session, t.setup_grade,
               t.setup_score, t.factors, t.rsi, t.trend, t.structure,
               t.failure_reason, t.vol_regime, t.spread_at_entry,
               m.lstm_pred, m.xgb_pred, m.smc_pred, m.attention_pred,
               m.dqn_action, m.ensemble_score, m.ensemble_signal,
               m.confidence, m.predictions_json
        FROM trades t
        LEFT JOIN ml_predictions m ON m.trade_id = t.id
        WHERE {where}
        ORDER BY t.id DESC
        LIMIT {n}
    """
    rows = conn.execute(sql).fetchall()
    cols = [d[0] for d in conn.execute(sql).description]
    return [dict(zip(cols, r)) for r in rows]


def build_user_prompt(trade: dict) -> str:
    """Compact, structured prompt — keep token cost low."""
    factors = trade.get("factors") or "{}"
    try:
        factors_d = json.loads(factors) if isinstance(factors, str) else factors
    except Exception:
        factors_d = {}

    pred_json = trade.get("predictions_json") or "{}"
    try:
        pred_d = json.loads(pred_json) if isinstance(pred_json, str) else pred_json
    except Exception:
        pred_d = {}

    rr = abs(trade["tp"] - trade["entry"]) / max(0.01, abs(trade["entry"] - trade["sl"]))

    lines = [
        f"TRADE #{trade['id']} — {trade['timestamp']} — {trade['direction']} @ {trade['entry']}",
        f"SL={trade['sl']} TP={trade['tp']} R:R={rr:.2f}",
        f"OUTCOME: {trade['status']} (P/L ${trade.get('profit') or 0:.2f})",
        f"Pattern: {trade.get('pattern')}",
        f"Setup: grade={trade.get('setup_grade')} score={trade.get('setup_score')}",
        f"Session: {trade.get('session')} | Trend: {trade.get('trend')} | Structure: {trade.get('structure')}",
        f"Vol regime: {trade.get('vol_regime')} | RSI: {trade.get('rsi')} | Spread: {trade.get('spread_at_entry')}",
        f"Factors fired: {list(factors_d.keys()) if factors_d else 'none'}",
        f"ML voters: lstm={trade.get('lstm_pred')}, xgb={trade.get('xgb_pred')}, smc={trade.get('smc_pred')}, attn={trade.get('attention_pred')}, dqn={trade.get('dqn_action')}",
        f"Ensemble: signal={trade.get('ensemble_signal')} score={trade.get('ensemble_score')} conf={trade.get('confidence')}",
    ]
    if trade.get("failure_reason"):
        lines.append(f"Failure mode: {trade['failure_reason'][:120]}")

    return "\n".join(lines)


def analyze_trade(client, trade: dict, model: str = "gpt-4o-mini") -> dict | None:
    """Single LLM call. Returns parsed JSON or None on error."""
    user_prompt = build_user_prompt(trade)
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


def store_analysis(conn, trade_id: int, analysis: dict, model: str):
    conn.execute(
        """INSERT OR REPLACE INTO llm_trade_journal
           (trade_id, verdict, root_cause, lesson, confidence, llm_model, analysis_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            trade_id,
            analysis.get("verdict"),
            analysis.get("root_cause"),
            analysis.get("lesson"),
            float(analysis.get("confidence", 0.0)),
            model,
            json.dumps(analysis),
        ),
    )
    conn.commit()


def aggregate_themes(analyses: list[dict]) -> dict:
    """Surface verdict distribution + recurring themes from cause/lesson text."""
    verdict_counts = {}
    causes = []
    lessons = []
    for a in analyses:
        v = a.get("verdict", "unknown")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
        if a.get("root_cause"):
            causes.append(a["root_cause"])
        if a.get("lesson"):
            lessons.append(a["lesson"])
    return {"verdict_counts": verdict_counts, "causes": causes, "lessons": lessons}


def themes_summary(client, themes: dict, model: str = "gpt-4o-mini") -> str:
    """Single rollup call: feed all causes/lessons, ask for top 3 themes."""
    if not themes["causes"]:
        return "(no analyses to summarize)"
    user = (
        f"Here are post-mortems from {len(themes['causes'])} closed trades.\n\n"
        f"Verdict distribution: {themes['verdict_counts']}\n\n"
        f"Root causes:\n" + "\n".join(f"- {c}" for c in themes["causes"]) + "\n\n"
        f"Lessons:\n" + "\n".join(f"- {l}" for l in themes["lessons"]) + "\n\n"
        "Identify the TOP 3 recurring themes. For each, give: theme name (3-5 words), "
        "frequency (n trades it appears in), and concrete actionable change. Plain text, "
        "numbered list, max 50 words per theme."
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a senior trading coach distilling patterns. Be concrete and actionable."},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"(themes summary failed: {e})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="Number of recent trades to analyze")
    ap.add_argument("--status", choices=["WIN", "LOSS", "TIMEOUT"], default=None)
    ap.add_argument("--write-md", action="store_true", help="Write reports/journal_<date>.md")
    ap.add_argument("--no-cache", action="store_true", help="Re-analyze even if cached")
    args = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    from openai import OpenAI
    client = OpenAI()

    conn = sqlite3.connect(ROOT / "data" / "sentinel.db")
    init_journal_table(conn)

    trades = fetch_trades_with_context(conn, args.n, args.status)
    if not trades:
        print("No closed trades found.")
        return

    print(f"== LLM Trade Journal — {len(trades)} trade(s), status={args.status or 'any'} ==\n")

    analyses = []
    for t in trades:
        if not args.no_cache:
            cached = conn.execute(
                "SELECT analysis_json FROM llm_trade_journal WHERE trade_id=?", (t["id"],)
            ).fetchone()
            if cached:
                analyses.append(json.loads(cached[0]))
                print(f"#{t['id']:>4} {t['status']:<7} {t['direction']:<5} (cached) -> {analyses[-1].get('verdict')}")
                continue

        a = analyze_trade(client, t)
        if a:
            store_analysis(conn, t["id"], a, "gpt-4o-mini")
            analyses.append(a)
            print(f"#{t['id']:>4} {t['status']:<7} {t['direction']:<5} -> {a.get('verdict')}")
            print(f"      cause: {a.get('root_cause')}")
            print(f"      lesson: {a.get('lesson')}")
        else:
            print(f"#{t['id']:>4} {t['status']:<7} {t['direction']:<5} -> ANALYSIS FAILED")

    print()
    themes = aggregate_themes(analyses)
    print("== Verdict distribution ==")
    for v, c in sorted(themes["verdict_counts"].items(), key=lambda x: -x[1]):
        print(f"  {v:<30} {c}")
    print()

    print("== TOP 3 recurring themes (LLM rollup) ==")
    summary = themes_summary(client, themes)
    print(summary)

    if args.write_md:
        out = ROOT / "reports" / f"journal_{datetime.now().strftime('%Y-%m-%d')}.md"
        out.parent.mkdir(exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# LLM Trade Journal — {datetime.now().isoformat(timespec='minutes')}\n\n")
            f.write(f"Trades analyzed: {len(trades)} (status={args.status or 'any'})\n\n")
            f.write("## Per-trade analyses\n\n")
            for t, a in zip(trades, analyses):
                f.write(f"### #{t['id']} — {t['direction']} {t['status']} ${t.get('profit') or 0:.2f}\n")
                f.write(f"- **Verdict:** {a.get('verdict')} (conf {a.get('confidence')})\n")
                f.write(f"- **Cause:** {a.get('root_cause')}\n")
                f.write(f"- **Lesson:** {a.get('lesson')}\n\n")
            f.write("## Verdict distribution\n\n")
            for v, c in themes["verdict_counts"].items():
                f.write(f"- {v}: {c}\n")
            f.write("\n## Recurring themes\n\n")
            f.write(summary + "\n")
        print(f"\nWritten -> {out}")

    conn.close()


if __name__ == "__main__":
    main()
