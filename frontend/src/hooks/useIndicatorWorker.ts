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

function computeSync(
  closes: number[],
  opts?: { emaPeriod?: number; rsiPeriod?: number; bbPeriod?: number; bbMult?: number },
): IndicatorOutput {
  const { emaPeriod = 21, rsiPeriod = 14, bbPeriod = 20, bbMult = 2 } = opts ?? {};
  return {
    ema: calcEMA(closes, emaPeriod),
    rsi: calcRSI(closes, rsiPeriod),
    bb: calcBollingerBands(closes, bbPeriod, bbMult),
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

  /**
   * Compute EMA, RSI, and Bollinger Bands.
   * Uses Web Worker if available, otherwise falls back to synchronous.
   */
  const compute = useCallback(
    (
      closes: number[],
      opts?: { emaPeriod?: number; rsiPeriod?: number; bbPeriod?: number; bbMult?: number },
    ): Promise<IndicatorOutput> => {
      const w = workerRef.current;

      // Fallback: synchronous computation on main thread
      if (!w) {
        return Promise.resolve(computeSync(closes, opts));
      }

      // Cancel previous pending computation (only latest matters)
      if (pendingRef.current) {
        pendingRef.current.reject(new Error('superseded'));
        pendingRef.current = null;
      }

      return new Promise((resolve, reject) => {
        pendingRef.current = { resolve, reject };
        w.postMessage({ type: 'computeAll', payload: { closes, ...opts } });
      });
    },
    [],
  );

  return { compute };
}
