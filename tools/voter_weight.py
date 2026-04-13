#!/usr/bin/env python3
"""tools/voter_weight.py - manage per-voter ensemble weights.

Subcommands

  status                    show all voter weights + _prev backups
  defuse <voter>            weight -> 0.0, save prior as ensemble_weight_<voter>_prev
  restore <voter>           read ensemble_weight_<voter>_prev -> ensemble_weight_<voter>
  set <voter> <value>       manual override (saves current as _prev first)

Safe to call while the API is running — NewsDB re-reads dynamic_params
on every ensemble call (no cache). Scanner picks up the new weight on
the next cycle.

Audit trail: every mutation stamps `voter_weight_last_change` with ISO
timestamp + reason + voter.

Voter names: smc, attention, dpformer, lstm, xgb, dqn, deeptrans.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

# Script runs from tools/ but imports live in ../src/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VALID_VOTERS = ("smc", "attention", "dpformer", "lstm", "xgb", "dqn", "deeptrans")


def _ts() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _stamp(db, voter: str, action: str, old, new) -> None:
    db.set_param("voter_weight_last_change",
                 f"{_ts()} | {action} | {voter} | {old} -> {new}")


def cmd_status(db) -> int:
    print(f"{'voter':<12} {'weight':>10} {'_prev':>10} {'status'}")
    print("-" * 52)
    for v in VALID_VOTERS:
        w = db.get_param(f"ensemble_weight_{v}", None)
        prev = db.get_param(f"ensemble_weight_{v}_prev", None)
        if w is None:
            status = "unset (uses default)"
        elif float(w) == 0.0:
            status = f"DEFUSED (can restore {prev})" if prev else "DEFUSED"
        else:
            status = "active"
        w_str = f"{w:.4f}" if w is not None else "—"
        p_str = f"{prev:.4f}" if isinstance(prev, (int, float)) else "—"
        print(f"{v:<12} {w_str:>10} {p_str:>10} {status}")
    print()
    last = db.get_param("voter_weight_last_change", None)
    if last:
        print(f"last change: {last}")
    return 0


def cmd_defuse(db, voter: str, reason: str | None) -> int:
    cur = db.get_param(f"ensemble_weight_{voter}", None)
    if cur is None:
        print(f"[error] no ensemble_weight_{voter} in DB", file=sys.stderr)
        return 2
    if float(cur) == 0.0:
        print(f"[noop] {voter} already defused (weight=0.0)")
        return 0
    db.set_param(f"ensemble_weight_{voter}_prev", cur)
    db.set_param(f"ensemble_weight_{voter}", 0.0)
    db.set_param(f"{voter}_defused_at", _ts())
    if reason:
        db.set_param(f"{voter}_defused_reason", reason)
    _stamp(db, voter, "defuse", cur, 0.0)
    print(f"[ok] {voter}: {cur:.4f} -> 0.0 (prev saved)")
    return 0


def cmd_restore(db, voter: str, to: float | None) -> int:
    cur = db.get_param(f"ensemble_weight_{voter}", None)
    prev = db.get_param(f"ensemble_weight_{voter}_prev", None)
    target = to if to is not None else prev
    if target is None:
        print(f"[error] no ensemble_weight_{voter}_prev to restore from; "
              f"pass --to <value> to override", file=sys.stderr)
        return 2
    target = float(target)
    db.set_param(f"ensemble_weight_{voter}", target)
    db.set_param(f"{voter}_restored_at", _ts())
    _stamp(db, voter, "restore", cur, target)
    print(f"[ok] {voter}: {cur} -> {target:.4f}")
    return 0


def cmd_set(db, voter: str, value: float) -> int:
    cur = db.get_param(f"ensemble_weight_{voter}", None)
    if cur is not None:
        db.set_param(f"ensemble_weight_{voter}_prev", cur)
    db.set_param(f"ensemble_weight_{voter}", float(value))
    _stamp(db, voter, "set", cur, value)
    print(f"[ok] {voter}: {cur} -> {value:.4f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show all voter weights")

    p_defuse = sub.add_parser("defuse", help="set voter weight to 0.0")
    p_defuse.add_argument("voter", choices=VALID_VOTERS)
    p_defuse.add_argument("--reason", default=None)

    p_restore = sub.add_parser("restore", help="restore voter from _prev")
    p_restore.add_argument("voter", choices=VALID_VOTERS)
    p_restore.add_argument("--to", type=float, default=None,
                           help="target weight (overrides _prev)")

    p_set = sub.add_parser("set", help="manually set voter weight")
    p_set.add_argument("voter", choices=VALID_VOTERS)
    p_set.add_argument("value", type=float)

    args = ap.parse_args()

    from src.core.database import NewsDB
    db = NewsDB()

    if args.cmd == "status":
        return cmd_status(db)
    if args.cmd == "defuse":
        return cmd_defuse(db, args.voter, args.reason)
    if args.cmd == "restore":
        return cmd_restore(db, args.voter, args.to)
    if args.cmd == "set":
        return cmd_set(db, args.voter, args.value)
    return 1


if __name__ == "__main__":
    sys.exit(main())
