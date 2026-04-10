/**
 * indicators.worker.ts — Web Worker for heavy indicator math
 *
 * Runs EMA, RSI, SMA, Bollinger Bands, MACD, ATR, Stochastic
 * off the main thread so the UI stays responsive.
 *
 * Protocol:  postMessage({ type, payload }) → postMessage({ type, result })
 */

/* ── Basic math ─────────────────────────────────────────────────────── */

function calcEMA(closes: number[], period: number): (number | null)[] {
  const k = 2 / (period + 1);
  const out: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += closes[i];
  out[period - 1] = sum / period;
  for (let i = period; i < closes.length; i++) {
    out[i] = closes[i] * k + (out[i - 1] as number) * (1 - k);
  }
  return out;
}

function calcRSI(closes: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length < period + 1) return out;
  let gainSum = 0;
  let lossSum = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) gainSum += d;
    else lossSum -= d;
  }
  let avgGain = gainSum / period;
  let avgLoss = lossSum / period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    avgGain = (avgGain * (period - 1) + (d > 0 ? d : 0)) / period;
    avgLoss = (avgLoss * (period - 1) + (d < 0 ? -d : 0)) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

function calcSMA(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  out[period - 1] = sum / period;
  for (let i = period; i < values.length; i++) {
    sum += values[i] - values[i - period];
    out[i] = sum / period;
  }
  return out;
}

function calcBollingerBands(
  closes: number[], period = 20, mult = 2,
): { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] } {
  const middle = calcSMA(closes, period);
  const upper: (number | null)[] = new Array(closes.length).fill(null);
  const lower: (number | null)[] = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    const m = middle[i];
    if (m === null) continue;
    let sqSum = 0;
    for (let j = i - period + 1; j <= i; j++) sqSum += (closes[j] - m) ** 2;
    const std = Math.sqrt(sqSum / period);
    upper[i] = m + mult * std;
    lower[i] = m - mult * std;
  }
  return { upper, middle, lower };
}

/* ── MACD (12, 26, 9) ──────────────────────────────────────────────── */

function calcMACD(closes: number[], fastP = 12, slowP = 26, signalP = 9) {
  const fast = calcEMA(closes, fastP);
  const slow = calcEMA(closes, slowP);
  const macdLine: (number | null)[] = new Array(closes.length).fill(null);
  const macdValues: number[] = []; // for signal EMA
  const macdIndices: number[] = [];

  for (let i = 0; i < closes.length; i++) {
    if (fast[i] !== null && slow[i] !== null) {
      macdLine[i] = fast[i]! - slow[i]!;
      macdValues.push(macdLine[i]!);
      macdIndices.push(i);
    }
  }

  // Signal line = EMA(9) of MACD values
  const signalRaw = calcEMA(macdValues, signalP);
  const signal: (number | null)[] = new Array(closes.length).fill(null);
  const histogram: (number | null)[] = new Array(closes.length).fill(null);

  for (let j = 0; j < macdValues.length; j++) {
    const idx = macdIndices[j];
    if (signalRaw[j] !== null) {
      signal[idx] = signalRaw[j];
      histogram[idx] = macdValues[j] - signalRaw[j]!;
    }
  }

  return { macd: macdLine, signal, histogram };
}

/* ── ATR (Average True Range) ──────────────────────────────────────── */

function calcATR(
  highs: number[], lows: number[], closes: number[], period = 14,
): (number | null)[] {
  const n = closes.length;
  const out: (number | null)[] = new Array(n).fill(null);
  if (n < 2) return out;

  // True Range
  const tr: number[] = [highs[0] - lows[0]];
  for (let i = 1; i < n; i++) {
    tr.push(Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1]),
    ));
  }

  if (n < period) return out;

  // Initial ATR = SMA of first `period` TRs
  let atr = 0;
  for (let i = 0; i < period; i++) atr += tr[i];
  atr /= period;
  out[period - 1] = atr;

  // Wilder smoothing
  for (let i = period; i < n; i++) {
    atr = (atr * (period - 1) + tr[i]) / period;
    out[i] = atr;
  }

  return out;
}

/* ── Stochastic Oscillator (%K, %D) ───────────────────────────────── */

function calcStochastic(
  highs: number[], lows: number[], closes: number[],
  kPeriod = 14, kSmooth = 3, dPeriod = 3,
) {
  const n = closes.length;
  const rawK: (number | null)[] = new Array(n).fill(null);

  // Raw %K
  for (let i = kPeriod - 1; i < n; i++) {
    let hh = -Infinity, ll = Infinity;
    for (let j = i - kPeriod + 1; j <= i; j++) {
      if (highs[j] > hh) hh = highs[j];
      if (lows[j] < ll) ll = lows[j];
    }
    const range = hh - ll;
    rawK[i] = range > 0 ? ((closes[i] - ll) / range) * 100 : 50;
  }

  // Smooth %K = SMA(kSmooth) of raw %K
  const kValues: number[] = [];
  const kIdx: number[] = [];
  for (let i = 0; i < n; i++) {
    if (rawK[i] !== null) { kValues.push(rawK[i]!); kIdx.push(i); }
  }
  const smoothedKraw = calcSMA(kValues, kSmooth);
  const k: (number | null)[] = new Array(n).fill(null);
  for (let j = 0; j < kValues.length; j++) {
    if (smoothedKraw[j] !== null) k[kIdx[j]] = smoothedKraw[j];
  }

  // %D = SMA(dPeriod) of %K
  const dValues: number[] = [];
  const dIdx: number[] = [];
  for (let i = 0; i < n; i++) {
    if (k[i] !== null) { dValues.push(k[i]!); dIdx.push(i); }
  }
  const dRaw = calcSMA(dValues, dPeriod);
  const d: (number | null)[] = new Array(n).fill(null);
  for (let j = 0; j < dValues.length; j++) {
    if (dRaw[j] !== null) d[dIdx[j]] = dRaw[j];
  }

  return { k, d };
}

/* ── Message handler ── */

export interface IndicatorRequest {
  type: 'computeAll';
  payload: {
    closes: number[];
    highs?: number[];
    lows?: number[];
    emaPeriod?: number;
    rsiPeriod?: number;
    bbPeriod?: number;
    bbMult?: number;
  };
}

export interface IndicatorResult {
  type: 'computeAll';
  result: {
    ema: (number | null)[];
    rsi: (number | null)[];
    bb: { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] };
    macd: { macd: (number | null)[]; signal: (number | null)[]; histogram: (number | null)[] };
    atr: (number | null)[];
    stoch: { k: (number | null)[]; d: (number | null)[] };
  };
}

self.onmessage = (e: MessageEvent<IndicatorRequest>) => {
  const { type, payload } = e.data;

  if (type === 'computeAll') {
    const { closes, highs, lows, emaPeriod = 21, rsiPeriod = 14, bbPeriod = 20, bbMult = 2 } = payload;

    const h = highs ?? closes;
    const l = lows ?? closes;

    const ema = calcEMA(closes, emaPeriod);
    const rsi = calcRSI(closes, rsiPeriod);
    const bb = calcBollingerBands(closes, bbPeriod, bbMult);
    const macd = calcMACD(closes);
    const atr = calcATR(h, l, closes);
    const stoch = calcStochastic(h, l, closes);

    const response: IndicatorResult = {
      type: 'computeAll',
      result: { ema, rsi, bb, macd, atr, stoch },
    };
    (self as unknown as Worker).postMessage(response);
  }
};
