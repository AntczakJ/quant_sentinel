#!/usr/bin/env python
"""scripts/export_tax_ledger.py — quarterly tax-ready ledger export.

2026-05-05: shipped per comparative research adoption (#8). Quarterly
export of closed trades with hash-chain tamper-evidence. Format covers
both Form 8949 (US) + PIT-38 (PL):
  open_ts, close_ts, symbol, side, lot, entry, exit, fees, pnl_usd,
  pnl_pln_at_close, prev_hash, row_hash

Hash chain: row_hash = SHA256(prev_hash || row_data). Modify any past
row → all subsequent hashes break. Stored in `reports/tax/YYYY/Qx.csv`
plus `reports/tax/YYYY/Qx.hash` containing the final hash for cold
storage / audit.

Usage:
  python scripts/export_tax_ledger.py --year 2026 --quarter 1
  python scripts/export_tax_ledger.py --year 2026   # full year
  python scripts/export_tax_ledger.py --since 2026-01-01 --until 2026-12-31

By default uses USD/PLN closing rate from FRED (cached) for pnl_pln.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import sqlite3
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]


COLUMNS = [
    "open_ts", "close_ts", "symbol", "side", "lot",
    "entry", "exit", "fees", "pnl_usd", "pnl_pln_at_close",
    "prev_hash", "row_hash",
]


def _row_hash(prev_hash: str, row: dict) -> str:
    """SHA256 over prev_hash + row data (deterministic key order)."""
    payload = prev_hash + "|".join(
        f"{k}={row.get(k, '')}" for k in COLUMNS[:-2]  # exclude hash columns
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_usdpln_rate(date_str: str, _cache: dict = {}) -> Optional[float]:
    """USD/PLN closing rate. Cached. Returns None on lookup failure.

    Uses NBP table A (PL National Bank reference rate) — accepted by PL tax
    authorities. Endpoint: https://api.nbp.pl/api/exchangerates/rates/A/USD/{date}
    """
    if date_str in _cache:
        return _cache[date_str]
    try:
        import urllib.request, json
        url = f"https://api.nbp.pl/api/exchangerates/rates/A/USD/{date_str}/?format=json"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read().decode())
            rate = float(data["rates"][0]["mid"])
            _cache[date_str] = rate
            return rate
    except Exception:
        # NBP returns 404 on weekends/holidays — try previous business day
        for delta in (1, 2, 3, 4):
            try:
                d = (dt.datetime.strptime(date_str, "%Y-%m-%d") - dt.timedelta(days=delta)).strftime("%Y-%m-%d")
                url = f"https://api.nbp.pl/api/exchangerates/rates/A/USD/{d}/?format=json"
                import urllib.request, json
                with urllib.request.urlopen(url, timeout=5) as r:
                    data = json.loads(r.read().decode())
                    rate = float(data["rates"][0]["mid"])
                    _cache[date_str] = rate
                    return rate
            except Exception:
                continue
        return None


def _fetch_closed_trades(db_path: str, since: str, until: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT timestamp, direction, lot, entry, tp, profit, status "
        "FROM trades WHERE status IN ('WIN','LOSS','PROFIT','BREAKEVEN') "
        "AND timestamp >= ? AND timestamp <= ? "
        "ORDER BY timestamp",
        (since, until),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        ts, direction, lot, entry, tp, profit, status = r
        # Naive close estimate: backtest stores close in tp column on resolve
        out.append({
            "open_ts": ts,
            "close_ts": ts,  # we don't store distinct close ts in this schema
            "symbol": "XAU/USD",
            "side": (direction or "").upper(),
            "lot": float(lot or 0),
            "entry": float(entry or 0),
            "exit": float(tp or 0),
            "fees": 0.0,  # broker doesn't surface, document elsewhere
            "pnl_usd": round(float(profit or 0), 2),
        })
    return out


def export(year: int, quarter: Optional[int],
           since: Optional[str], until: Optional[str],
           db_path: str, out_dir: Path) -> Path:
    if since and until:
        period_label = f"custom_{since}_to_{until}"
    elif quarter:
        q_starts = {1: f"{year}-01-01", 2: f"{year}-04-01",
                    3: f"{year}-07-01", 4: f"{year}-10-01"}
        q_ends = {1: f"{year}-03-31", 2: f"{year}-06-30",
                  3: f"{year}-09-30", 4: f"{year}-12-31"}
        since = q_starts[quarter]
        until = q_ends[quarter] + " 23:59:59"
        period_label = f"Q{quarter}"
    else:
        since = f"{year}-01-01"
        until = f"{year}-12-31 23:59:59"
        period_label = "full_year"

    rows = _fetch_closed_trades(db_path, since, until)
    print(f"[tax] {len(rows)} closed trades from {since} to {until}")

    # Hash-chain
    prev_hash = "GENESIS"
    chained_rows = []
    for r in rows:
        date_str = r["close_ts"][:10]
        rate = _get_usdpln_rate(date_str)
        r["pnl_pln_at_close"] = round(r["pnl_usd"] * rate, 2) if rate else None
        r["prev_hash"] = prev_hash
        h = _row_hash(prev_hash, r)
        r["row_hash"] = h
        chained_rows.append(r)
        prev_hash = h

    out_dir = out_dir / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{period_label}.csv"
    hash_path = out_dir / f"{period_label}.hash"

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in chained_rows:
            w.writerow({k: r.get(k, "") for k in COLUMNS})

    hash_path.write_text(prev_hash + "\n", encoding="utf-8")

    print(f"[tax] CSV  → {csv_path}")
    print(f"[tax] hash → {hash_path}  ({prev_hash[:16]}...)")
    return csv_path


def verify(csv_path: Path, hash_path: Path) -> bool:
    """Re-walk hash chain, verify final hash matches stored."""
    if not csv_path.exists() or not hash_path.exists():
        print(f"[verify] missing file(s)")
        return False
    expected = hash_path.read_text().strip()
    prev_hash = "GENESIS"
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            stored = row["row_hash"]
            row_for_hash = {k: row[k] for k in COLUMNS[:-2]}
            computed = _row_hash(prev_hash, row_for_hash)
            if stored != computed:
                print(f"[verify] FAIL at row {row.get('open_ts')}: "
                      f"stored={stored[:12]}... computed={computed[:12]}...")
                return False
            prev_hash = stored
    if prev_hash == expected:
        print(f"[verify] OK — final hash matches")
        return True
    print(f"[verify] FAIL — chain end hash mismatch: stored={expected[:12]}... "
          f"computed={prev_hash[:12]}...")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--quarter", type=int, choices=[1, 2, 3, 4], default=None)
    ap.add_argument("--since", type=str, default=None)
    ap.add_argument("--until", type=str, default=None)
    ap.add_argument("--db", type=str, default=str(ROOT / "data" / "sentinel.db"))
    ap.add_argument("--out-dir", type=Path, default=ROOT / "reports" / "tax")
    ap.add_argument("--verify", type=Path, default=None,
                    help="Verify a previously exported CSV (pass the .csv path)")
    args = ap.parse_args()

    if args.verify:
        hash_path = args.verify.with_suffix(".hash")
        return 0 if verify(args.verify, hash_path) else 1

    if not args.year:
        args.year = dt.datetime.now().year

    export(args.year, args.quarter, args.since, args.until,
           args.db, args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
