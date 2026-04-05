/**
 * indicators.worker.ts — Web Worker for heavy indicator math
 *
 * Runs EMA, RSI, SMA, Bollinger Bands off the main thread so the UI
 * stays responsive during 60s data refresh cycles.
 *
 * Protocol:  postMessage({ type, payload }) → postMessage({ type, result })
 */

/* ── Indicator math (identical to CandlestickChart.tsx originals) ── */

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
  closes: number[],
  period = 20,
  mult = 2,
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

/* ── Message handler ── */

export interface IndicatorRequest {
  type: 'computeAll';
  payload: {
    closes: number[];
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
  };
}

self.onmessage = (e: MessageEvent<IndicatorRequest>) => {
  const { type, payload } = e.data;

  if (type === 'computeAll') {
    const { closes, emaPeriod = 21, rsiPeriod = 14, bbPeriod = 20, bbMult = 2 } = payload;

    const ema = calcEMA(closes, emaPeriod);
    const rsi = calcRSI(closes, rsiPeriod);
    const bb = calcBollingerBands(closes, bbPeriod, bbMult);

    const response: IndicatorResult = { type: 'computeAll', result: { ema, rsi, bb } };
    (self as unknown as Worker).postMessage(response);
  }
};

