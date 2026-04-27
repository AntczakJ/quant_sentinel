# Lot-sizing rebuild — design doc (2026-04-27)

Status: **design only — no code changes yet**.
Author: Janek (with Claude Code assistance).
Decision deadline: after 24-72h live observation of current Phase B + B7
config validates (or invalidates) the 90-day backtest baseline
(PF 1.21, +3.30%, -3.63% DD, 137 trades).

## 1. Why this exists

Yesterday's evening session uncovered that lot size on the **backtest**
cohort was inversely correlated with outcome — winners avg lot ≈ 0.026,
losers avg lot ≈ 0.084 (3.2× bigger). The dominant cause was the per-grade
risk multiplier `risk_percent × 1.5` for A+ setups: when the model felt
*most* confident, it sized up — but those confident setups actually lost
more often than baseline. This is classic confidence-mis-calibration risk.

The stop-gap shipped yesterday:
- `MAX_LOT_CAP=0.01` in `.env` — hard-cap until proper fix lands
- Per-grade `× 1.5 / × 0.7` multipliers removed in `finance.py`

That stop-gap **flattens the distribution** but throws away any
real signal that grade does carry. We need a principled rebuild.

## 2. What we know vs what we suspect

**Confirmed (backtest, n≈137):**
- Lot variance is large in pre-fix runs (0.01 → 0.08)
- A+ lots correlated with worse outcomes
- Flat 0.01 across all trades (post-fix backtest) reaches PF 1.21

**Uncertain — need more data before committing:**
- Live cohort id 100–199 actually shows the **opposite** trend
  (winners avg lot 0.032, losers 0.026) — sample too small (28 trades)
  to draw conclusions. Backtest result may not generalize to live.
- Grade-A confidence may genuinely encode edge in some regimes (trending)
  and noise in others (chop). We have not tested regime-conditioned grades.
- Kelly sizing path (`kelly_reset_ts` in `dynamic_params`) was reset
  recently after the loss-streak audit. Whether Kelly converges to a
  reasonable f* needs more post-reset trade history.

**Constraints we will not relax in this rebuild:**
- Must work alongside `DISABLE_TRAILING=1` (locked in by Phase B win)
- Must not double-count with `MAX_LOT_CAP` — design must replace the cap,
  not stack with it
- Must preserve risk-per-trade ceiling around 0.5–1% of balance
- Must respect `kelly_min_trades` floor — no Kelly extrapolation from
  contaminated streak

## 3. Three candidate designs

### Option A — Constant 0.5% risk, no grade modulation

**What:** Drop A/B/C grade multipliers entirely. Compute lot purely
from `(balance × 0.005) / sl_pips_in_dollars`. Kelly path stays
disabled until KELLY_MIN_TRADES post-reset.

**Pros:**
- Simplest possible. Zero degrees of freedom to overfit.
- Backtest PF 1.21 was achieved with effectively this (flat 0.01).
- Easy to validate — A/B test against current state cleanly.

**Cons:**
- Throws away any real grade signal (and there might be one in
  trending regimes — we just haven't measured per-regime).
- If account grows, doesn't auto-scale risk down once vol regime
  changes — strict 0.5% means same dollar risk in calm and chop.

**When to pick:** if 24–72h live obs shows current flat-0.01 cohort
matches backtest PF range. Safe default. Validate by raising
`MAX_LOT_CAP` to 0.05 and seeing if dollar-risk stays in the
0.4–0.6% band per trade.

### Option B — Model-driven R-multiple modulator

**What:** v2 XGB model (planned per `2026-04-25_max_winrate_master_plan.md`)
predicts expected R-multiple per setup. Use that as the risk modulator:
- predicted_R ≥ 1.5 → 1.0× base risk (0.5%)
- predicted_R 1.0–1.5 → 0.6× base risk (0.3%)
- predicted_R < 1.0 → trade rejected (don't size, reject)

**Pros:**
- Principled — sizing is tied to expected return, not heuristic grade.
- Walk-forward validation built in (we'd train R-mult model on rolling
  windows and only deploy if it generalizes).
- Self-correcting: bad regime → predictions degrade → smaller lots.

**Cons:**
- Requires the v2 XGB model to exist and be production-grade — that's
  weeks of work per master plan.
- Adds another point of failure (if model goes stale silently,
  sizing degrades silently).
- Calibration drift is real — need ongoing monitoring.

**When to pick:** after Phase 5 of master plan ships
(walk-forward + per-direction models). Not now.

### Option C — Strict ¼-Kelly, no other multipliers

**What:** Pure ¼-Kelly: `f* = (W·R - L) / R` where W is win rate, R is
avg R-multiple, L = 1−W. Use rolling 50-trade window post-Kelly-reset.
Lot = `balance × clip(¼·f*, 0.001, 0.01)`.

**Pros:**
- Theoretically optimal for a stationary edge.
- Conservative ¼-fraction protects against W/R mis-estimation.
- Auto-scales with edge confidence.

**Cons:**
- Variance can be high — some trades 0.001, some 0.01 even on similar
  setups. Psychologically harder to monitor.
- Sensitive to recent W/R skew — a streak biases f* aggressively.
  Cooldown logic gets complex.
- Untested on this account — we'd need ≥50 post-reset trades to
  even estimate f*, and we have 3 since reset.

**When to pick:** when account has 100+ post-Kelly-reset trades and
W/R is stable across multiple regime windows. **Probably 6+ weeks out.**

## 4. Recommendation

**Pick Option A (constant 0.5%) once live obs validates current state.**

Reasoning:
1. Backtest already validated it implicitly (flat 0.01 ≈ flat 0.5% on
   our balance band).
2. Smallest blast radius — minimum new code paths.
3. Easy to revert if it underperforms.
4. Doesn't preclude moving to B or C later — A is the *baseline*.

**Validation procedure for Option A:**
1. Live obs validates current Phase B + flat-0.01 (target: ≥30 trades
   in 14d, PF ≥ 1.0, lot stays at 0.01 always).
2. Branch `lot-sizing-A`: replace MAX_LOT_CAP-based logic with explicit
   0.5% computation. Keep MAX_LOT_CAP as a hard ceiling, not the source.
3. Backtest 90d on warehouse data, expect PF within ±10% of current
   flat-0.01 baseline (PF 1.21).
4. Shadow log for 24h (compute proposed lot side-by-side with current,
   no execution change).
5. Flip the cutover, raise MAX_LOT_CAP to 0.02 (safety net, not active
   constraint). Monitor 7d for regression.

## 5. What this design doc DOES NOT cover

- Vol-targeting (lot scales inverse to ATR) — research-backed but not
  required for a base rebuild. Add as Phase 2.
- Per-direction sizing (LONG vs SHORT given asymmetry flip) — current
  scope is direction-agnostic flat risk.
- Account growth response — for now, fixed 0.5% of current balance,
  not target-equity scaling.
- Drawdown-sensitive sizing (reduce lot when in drawdown) — separate
  question from base sizing model.
- Multi-asset sizing — XAU only for now.

## 6. Why not just leave MAX_LOT_CAP=0.01 indefinitely?

- It silently caps **good** opportunities along with bad ones.
- It's not principled — it's a band-aid the code doesn't reason about.
- It doesn't scale: if account grows 2×, 0.01 is now half the intended
  risk — and we'd never notice.
- It hides whether the underlying sizing logic is fixed.

A proper rebuild lets us **explain** the lot on every trade, which is
auditability we lack now.

## 7. Open questions before code

1. **Where does balance come from for the 0.5% computation?**
   Currently `dynamic_params.portfolio_balance`. Needs read on every
   `calculate_position` call — already happens, no change needed.

2. **What's the SL→dollar conversion for XAU?**
   Need to verify `lot × 100 × pip_distance` formula matches broker's
   actual margin/risk calc. Document constants (1 lot XAU = 100 oz,
   $1 pip move = $1 P&L per oz at standard leverage).

3. **What about the spread?**
   SL distance currently includes spread. Confirm the 0.5% allocation
   is *gross* (pre-spread) or *net* (post-spread). Net is more honest.

4. **Currency conversion for non-USD accounts?**
   `get_fx_rate` was deleted today as dead code. If account currency
   is PLN, do we need a live USD/PLN rate to translate the 0.5% target?
   Currently the system seems to compute in account currency directly —
   confirm this still holds after rebuild.

## 8. Decision gate

This doc is **not actionable** until:

- Live cohort N ≥ 30 post-2026-04-26-config (currently N=3)
- 7-day live PF computed and within ±20% of backtest PF 1.21
- No SHORT bleed in zielony regime confirmed (B7 working — see
  SHORT #200 forensics 2026-04-27, B7 verified working)

Earliest revisit: **2026-05-04** (7 days from now).
Before that: pure observation, no parameter tuning.
