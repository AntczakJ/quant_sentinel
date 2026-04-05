/**
 * smcDetector.ts — Client-side Smart Money Concepts detection
 *
 * Runs on already-loaded CandlestickData[], no extra API call needed.
 * Detects: FVG, Order Blocks, Supply/Demand zones, Equilibrium.
 */

export interface SmcZone {
  type: 'fvg_bull' | 'fvg_bear' | 'ob_bull' | 'ob_bear' | 'supply' | 'demand';
  upper: number;
  lower: number;
  startTime: number;
  endTime: number;       // 0 = extend to right edge; otherwise unix ts where zone ends (mitigated or last candle)
  label: string;
  color: string;
}

interface OhlcBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  Mitigation helpers — find when price fills / enters a zone               */
/* ══════════════════════════════════════════════════════════════════════════ */

/**
 * Scan candles forward from `fromIdx` to find when price enters the
 * (lower, upper) range, i.e. the zone is "mitigated".
 * For bullish zones: mitigated when a candle's low dips into the zone.
 * For bearish zones: mitigated when a candle's high rises into the zone.
 * Returns the mitigating candle's time, or `fallback` (last candle time)
 * if the zone is still open.
 */
function findMitigationTime(
  candles: OhlcBar[], fromIdx: number,
  lower: number, upper: number,
  direction: 'bull' | 'bear',
  fallback: number,
): number {
  for (let j = fromIdx + 1; j < candles.length; j++) {
    const c = candles[j];
    if (direction === 'bull' && c.low <= upper) return c.time;
    if (direction === 'bear' && c.high >= lower) return c.time;
  }
  return fallback;
}

/** Generic: mitigated when any subsequent candle's range overlaps the zone. */
function findZoneMitigationTime(
  candles: OhlcBar[], fromIdx: number,
  lower: number, upper: number,
  fallback: number,
): number {
  for (let j = fromIdx + 1; j < candles.length; j++) {
    const c = candles[j];
    // candle overlaps zone if candle.low < upper AND candle.high > lower
    if (c.low < upper && c.high > lower) return c.time;
  }
  return fallback;
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  FVG — Fair Value Gap (3-candle imbalance)                               */
/* ══════════════════════════════════════════════════════════════════════════ */

export function detectFVGs(candles: OhlcBar[], maxZones = 5): SmcZone[] {
  const zones: SmcZone[] = [];
  if (candles.length < 3) return zones;
  const lastTime = candles[candles.length - 1].time;

  for (let i = 2; i < candles.length; i++) {
    const c1 = candles[i - 2];
    const c3 = candles[i];

    // Bullish FVG: gap between c1.high and c3.low
    if (c3.low > c1.high) {
      const endTime = findMitigationTime(candles, i, c1.high, c3.low, 'bull', lastTime);
      zones.push({
        type: 'fvg_bull',
        lower: c1.high,
        upper: c3.low,
        startTime: c1.time,
        endTime,
        label: 'FVG ▲',
        color: 'rgba(34, 197, 94, 0.25)',
      });
    }
    // Bearish FVG: gap between c1.low and c3.high
    if (c3.high < c1.low) {
      const endTime = findMitigationTime(candles, i, c3.high, c1.low, 'bear', lastTime);
      zones.push({
        type: 'fvg_bear',
        lower: c3.high,
        upper: c1.low,
        startTime: c1.time,
        endTime,
        label: 'FVG ▼',
        color: 'rgba(239, 68, 68, 0.25)',
      });
    }
  }

  // Return most recent N (they're already in chronological order)
  return zones.slice(-maxZones);
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  Order Blocks — last opposing candle before a strong impulse move         */
/* ══════════════════════════════════════════════════════════════════════════ */

export function detectOrderBlocks(candles: OhlcBar[], maxBlocks = 3): SmcZone[] {
  const zones: SmcZone[] = [];
  if (candles.length < 20) return zones;
  const lastTime = candles[candles.length - 1].time;

  // Average body size for "strong move" threshold
  let bodySum = 0;
  for (const c of candles) bodySum += Math.abs(c.close - c.open);
  const avgBody = bodySum / candles.length;
  const threshold = avgBody * 1.5;

  for (let i = candles.length - 2; i >= 1 && zones.length < maxBlocks * 2; i--) {
    const curr = candles[i];
    const next = candles[i + 1];
    const nextBody = Math.abs(next.close - next.open);

    if (nextBody < threshold) continue;

    const currBearish = curr.close < curr.open;
    const currBullish = curr.close > curr.open;
    const nextBullish = next.close > next.open;
    const nextBearish = next.close < next.open;

    // Bullish OB: bearish candle → strong bullish impulse
    if (currBearish && nextBullish) {
      const endTime = findZoneMitigationTime(candles, i + 1, curr.low, curr.open, lastTime);
      zones.push({
        type: 'ob_bull',
        upper: curr.open,
        lower: curr.low,
        startTime: curr.time,
        endTime,
        label: 'OB ▲',
        color: 'rgba(59, 130, 246, 0.28)',
      });
    }
    // Bearish OB: bullish candle → strong bearish impulse
    if (currBullish && nextBearish) {
      const endTime = findZoneMitigationTime(candles, i + 1, curr.open, curr.high, lastTime);
      zones.push({
        type: 'ob_bear',
        upper: curr.high,
        lower: curr.open,
        startTime: curr.time,
        endTime,
        label: 'OB ▼',
        color: 'rgba(168, 85, 247, 0.28)',
      });
    }
  }

  // Limit per type
  const bulls = zones.filter(z => z.type === 'ob_bull').slice(0, maxBlocks);
  const bears = zones.filter(z => z.type === 'ob_bear').slice(0, maxBlocks);
  return [...bulls, ...bears];
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  Supply & Demand — zones around swing highs / lows                       */
/* ══════════════════════════════════════════════════════════════════════════ */

function findSwingPoints(candles: OhlcBar[], window = 5) {
  const swingHighs: { idx: number; price: number }[] = [];
  const swingLows: { idx: number; price: number }[] = [];

  for (let i = window; i < candles.length - window; i++) {
    let isHigh = true;
    let isLow = true;
    for (let j = i - window; j <= i + window; j++) {
      if (j === i) continue;
      if (candles[j].high >= candles[i].high) isHigh = false;
      if (candles[j].low <= candles[i].low) isLow = false;
    }
    if (isHigh) swingHighs.push({ idx: i, price: candles[i].high });
    if (isLow) swingLows.push({ idx: i, price: candles[i].low });
  }
  return { swingHighs, swingLows };
}

export function detectSupplyDemand(candles: OhlcBar[]): SmcZone[] {
  if (candles.length < 20) return [];
  const { swingHighs, swingLows } = findSwingPoints(candles, 5);
  const lastTime = candles[candles.length - 1].time;

  const zones: SmcZone[] = [];

  // Last 2 supply zones (swing highs)
  for (const sh of swingHighs.slice(-2)) {
    const c = candles[sh.idx];
    const bodyTop = Math.max(c.open, c.close);
    const endTime = findZoneMitigationTime(candles, sh.idx, bodyTop, c.high, lastTime);
    zones.push({
      type: 'supply',
      upper: c.high,
      lower: bodyTop,
      startTime: c.time,
      endTime,
      label: 'SUPPLY',
      color: 'rgba(239, 68, 68, 0.22)',
    });
  }

  // Last 2 demand zones (swing lows)
  for (const sl of swingLows.slice(-2)) {
    const c = candles[sl.idx];
    const bodyBottom = Math.min(c.open, c.close);
    const endTime = findZoneMitigationTime(candles, sl.idx, c.low, bodyBottom, lastTime);
    zones.push({
      type: 'demand',
      upper: bodyBottom,
      lower: c.low,
      startTime: c.time,
      endTime,
      label: 'DEMAND',
      color: 'rgba(34, 197, 94, 0.22)',
    });
  }

  return zones;
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  Equilibrium — 50 % of the last swing range                              */
/* ══════════════════════════════════════════════════════════════════════════ */

export function calcEquilibrium(candles: OhlcBar[]): number | null {
  if (candles.length < 20) return null;
  const { swingHighs, swingLows } = findSwingPoints(candles, 5);
  if (!swingHighs.length || !swingLows.length) return null;

  const lastHigh = swingHighs[swingHighs.length - 1].price;
  const lastLow = swingLows[swingLows.length - 1].price;
  return (lastHigh + lastLow) / 2;
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  Position tool zones — entry/SL/TP rectangles                            */
/* ══════════════════════════════════════════════════════════════════════════ */

export function buildPositionZones(
  entry: number, sl: number, tp: number, startTime: number,
): SmcZone[] {
  const zones: SmcZone[] = [];
  // TP zone (green)
  if (tp && entry) {
    zones.push({
      type: tp > entry ? 'fvg_bull' : 'fvg_bear',
      upper: Math.max(entry, tp),
      lower: Math.min(entry, tp),
      startTime,
      endTime: 0,
      label: `TP ${Math.abs(tp - entry).toFixed(1)}`,
      color: 'rgba(34, 197, 94, 0.18)',
    });
  }
  // SL zone (red)
  if (sl && entry) {
    zones.push({
      type: sl < entry ? 'fvg_bear' : 'fvg_bull',
      upper: Math.max(entry, sl),
      lower: Math.min(entry, sl),
      startTime,
      endTime: 0,
      label: `SL ${Math.abs(sl - entry).toFixed(1)}`,
      color: 'rgba(239, 68, 68, 0.18)',
    });
  }
  return zones;
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  Master function — run all detectors                                     */
/* ══════════════════════════════════════════════════════════════════════════ */

export interface SmcResult {
  zones: SmcZone[];
  eqLevel: number | null;
}

export function detectAllSmcZones(candles: OhlcBar[]): SmcResult {
  const fvgs = detectFVGs(candles, 5);
  const obs = detectOrderBlocks(candles, 3);
  const sd = detectSupplyDemand(candles);
  const eqLevel = calcEquilibrium(candles);

  return {
    zones: [...fvgs, ...obs, ...sd],
    eqLevel,
  };
}

