/**
 * useIndicatorWorker.ts — React hook to compute indicators off main thread
 *
 * Spawns a single Web Worker and reuses it across the component lifecycle.
 * Falls back to inline computation if workers are unavailable.
 */

import { useRef, useCallback, useEffect } from 'react';
import type { IndicatorResult } from '../workers/indicators.worker';

export interface IndicatorOutput {
  ema: (number | null)[];
  rsi: (number | null)[];
  bb: { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] };
  macd: { macd: (number | null)[]; signal: (number | null)[]; histogram: (number | null)[] };
  atr: (number | null)[];
  stoch: { k: (number | null)[]; d: (number | null)[] };
}

/* ── Synchronous fallback (identical logic to worker) ── */

function calcEMA(closes: number[], period: number): (number | null)[] {
  const k = 2 / (period + 1);
  const out: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length < period) {return out;}
  let sum = 0;
  for (let i = 0; i < period; i++) {sum += closes[i];}
  out[period - 1] = sum / period;
  for (let i = period; i < closes.length; i++) {
    out[i] = closes[i] * k + (out[i - 1] as number) * (1 - k);
  }
  return out;
}

function calcRSI(closes: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length < period + 1) {return out;}
  let gainSum = 0, lossSum = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) {gainSum += d;} else {lossSum -= d;}
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
  if (values.length < period) {return out;}
  let sum = 0;
  for (let i = 0; i < period; i++) {sum += values[i];}
  out[period - 1] = sum / period;
  for (let i = period; i < values.length; i++) {
    sum += values[i] - values[i - period];
    out[i] = sum / period;
  }
  return out;
}

function calcBollingerBands(closes: number[], period = 20, mult = 2) {
  const middle = calcSMA(closes, period);
  const upper: (number | null)[] = new Array(closes.length).fill(null);
  const lower: (number | null)[] = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    const m = middle[i];
    if (m === null) {continue;}
    let sqSum = 0;
    for (let j = i - period + 1; j <= i; j++) {sqSum += (closes[j] - m) ** 2;}
    const std = Math.sqrt(sqSum / period);
    upper[i] = m + mult * std;
    lower[i] = m - mult * std;
  }
  return { upper, middle, lower };
}

function calcMACD(closes: number[], fastP = 12, slowP = 26, signalP = 9) {
  const fast = calcEMA(closes, fastP);
  const slow = calcEMA(closes, slowP);
  const macdLine: (number | null)[] = new Array(closes.length).fill(null);
  const macdValues: number[] = [];
  const macdIndices: number[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (fast[i] !== null && slow[i] !== null) {
      macdLine[i] = fast[i]! - slow[i]!;
      macdValues.push(macdLine[i]!);
      macdIndices.push(i);
    }
  }
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

function calcATR(highs: number[], lows: number[], closes: number[], period = 14): (number | null)[] {
  const n = closes.length;
  const out: (number | null)[] = new Array(n).fill(null);
  if (n < 2) {return out;}
  const tr: number[] = [highs[0] - lows[0]];
  for (let i = 1; i < n; i++) {
    tr.push(Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i - 1]), Math.abs(lows[i] - closes[i - 1])));
  }
  if (n < period) {return out;}
  let atr = 0;
  for (let i = 0; i < period; i++) {atr += tr[i];}
  atr /= period;
  out[period - 1] = atr;
  for (let i = period; i < n; i++) {
    atr = (atr * (period - 1) + tr[i]) / period;
    out[i] = atr;
  }
  return out;
}

function calcStochastic(highs: number[], lows: number[], closes: number[], kP = 14, kS = 3, dP = 3) {
  const n = closes.length;
  const rawK: (number | null)[] = new Array(n).fill(null);
  for (let i = kP - 1; i < n; i++) {
    let hh = -Infinity, ll = Infinity;
    for (let j = i - kP + 1; j <= i; j++) {
      if (highs[j] > hh) {hh = highs[j];}
      if (lows[j] < ll) {ll = lows[j];}
    }
    const range = hh - ll;
    rawK[i] = range > 0 ? ((closes[i] - ll) / range) * 100 : 50;
  }
  const kVals: number[] = []; const kIdx: number[] = [];
  for (let i = 0; i < n; i++) { if (rawK[i] !== null) { kVals.push(rawK[i]!); kIdx.push(i); } }
  const smoothed = calcSMA(kVals, kS);
  const k: (number | null)[] = new Array(n).fill(null);
  for (let j = 0; j < kVals.length; j++) { if (smoothed[j] !== null) {k[kIdx[j]] = smoothed[j];} }
  const dVals: number[] = []; const dIdx2: number[] = [];
  for (let i = 0; i < n; i++) { if (k[i] !== null) { dVals.push(k[i]!); dIdx2.push(i); } }
  const dRaw = calcSMA(dVals, dP);
  const d: (number | null)[] = new Array(n).fill(null);
  for (let j = 0; j < dVals.length; j++) { if (dRaw[j] !== null) {d[dIdx2[j]] = dRaw[j];} }
  return { k, d };
}

export interface ComputeOpts {
  emaPeriod?: number;
  rsiPeriod?: number;
  bbPeriod?: number;
  bbMult?: number;
}

function computeSync(
  closes: number[], highs: number[], lows: number[], opts?: ComputeOpts,
): IndicatorOutput {
  const { emaPeriod = 21, rsiPeriod = 14, bbPeriod = 20, bbMult = 2 } = opts ?? {};
  return {
    ema: calcEMA(closes, emaPeriod),
    rsi: calcRSI(closes, rsiPeriod),
    bb: calcBollingerBands(closes, bbPeriod, bbMult),
    macd: calcMACD(closes),
    atr: calcATR(highs, lows, closes),
    stoch: calcStochastic(highs, lows, closes),
  };
}

export function useIndicatorWorker() {
  const workerRef = useRef<Worker | null>(null);
  const pendingRef = useRef<{
    resolve: (v: IndicatorOutput) => void;
    reject: (e: Error) => void;
  } | null>(null);

  useEffect(() => {
    try {
      const w = new Worker(
        new URL('../workers/indicators.worker.ts', import.meta.url),
        { type: 'module' },
      );
      workerRef.current = w;

      w.onmessage = (e: MessageEvent<IndicatorResult>) => {
        if (e.data.type === 'computeAll' && pendingRef.current) {
          pendingRef.current.resolve(e.data.result);
          pendingRef.current = null;
        }
      };

      w.onerror = (err) => {
        if (pendingRef.current) {
          pendingRef.current.reject(new Error(err.message));
          pendingRef.current = null;
        }
      };
    } catch {
      // Worker creation failed — compute() will use sync fallback
    }

    return () => {
      workerRef.current?.terminate();
      workerRef.current = null;
    };
  }, []);

  const compute = useCallback(
    (
      closes: number[],
      highs: number[],
      lows: number[],
      opts?: ComputeOpts,
    ): Promise<IndicatorOutput> => {
      const w = workerRef.current;

      if (!w) {
        return Promise.resolve(computeSync(closes, highs, lows, opts));
      }

      if (pendingRef.current) {
        pendingRef.current.reject(new Error('superseded'));
        pendingRef.current = null;
      }

      return new Promise((resolve, reject) => {
        pendingRef.current = { resolve, reject };
        w.postMessage({
          type: 'computeAll',
          payload: { closes, highs, lows, ...opts },
        });
      });
    },
    [],
  );

  return { compute };
}
