/**
 * Tests for indicator math functions (same logic as in worker + hook fallback)
 */
import { describe, it, expect } from 'vitest';

// Inline implementations matching the worker
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
  let gainSum = 0, lossSum = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) gainSum += d; else lossSum -= d;
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

function calcATR(highs: number[], lows: number[], closes: number[], period = 14): (number | null)[] {
  const n = closes.length;
  const out: (number | null)[] = new Array(n).fill(null);
  if (n < 2) return out;
  const tr: number[] = [highs[0] - lows[0]];
  for (let i = 1; i < n; i++) {
    tr.push(Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i - 1]), Math.abs(lows[i] - closes[i - 1])));
  }
  if (n < period) return out;
  let atr = 0;
  for (let i = 0; i < period; i++) atr += tr[i];
  atr /= period;
  out[period - 1] = atr;
  for (let i = period; i < n; i++) {
    atr = (atr * (period - 1) + tr[i]) / period;
    out[i] = atr;
  }
  return out;
}

// Test data: 30 ascending closes
const closes = Array.from({ length: 30 }, (_, i) => 3000 + i * 5 + Math.sin(i) * 10);
const highs = closes.map(c => c + 3);
const lows = closes.map(c => c - 3);

describe('EMA', () => {
  it('returns nulls for insufficient data', () => {
    const result = calcEMA([100, 200], 5);
    expect(result.every(v => v === null)).toBe(true);
  });

  it('computes EMA(5) correctly', () => {
    const result = calcEMA(closes, 5);
    // First 4 should be null
    expect(result[0]).toBeNull();
    expect(result[3]).toBeNull();
    // 5th value should be SMA of first 5
    const sma5 = closes.slice(0, 5).reduce((a, b) => a + b, 0) / 5;
    expect(result[4]).toBeCloseTo(sma5, 4);
    // Later values should not be null
    expect(result[result.length - 1]).not.toBeNull();
  });

  it('EMA tracks trend direction', () => {
    const result = calcEMA(closes, 5);
    const nonNull = result.filter((v): v is number => v !== null);
    // In an uptrend, EMA should generally increase
    const increasing = nonNull.slice(1).every((v, i) => v >= nonNull[i] - 1);
    expect(increasing).toBe(true);
  });
});

describe('RSI', () => {
  it('returns nulls for insufficient data', () => {
    const result = calcRSI([100, 200, 150], 14);
    expect(result.every(v => v === null)).toBe(true);
  });

  it('RSI is between 0 and 100', () => {
    const result = calcRSI(closes, 14);
    const nonNull = result.filter((v): v is number => v !== null);
    expect(nonNull.length).toBeGreaterThan(0);
    for (const v of nonNull) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(100);
    }
  });

  it('uptrend RSI is above 50', () => {
    const uptrend = Array.from({ length: 30 }, (_, i) => 3000 + i * 10);
    const result = calcRSI(uptrend, 14);
    const lastVal = result[result.length - 1];
    expect(lastVal).not.toBeNull();
    expect(lastVal!).toBeGreaterThan(50);
  });
});

describe('ATR', () => {
  it('returns positive values for valid data', () => {
    const result = calcATR(highs, lows, closes, 14);
    const nonNull = result.filter((v): v is number => v !== null);
    expect(nonNull.length).toBeGreaterThan(0);
    for (const v of nonNull) {
      expect(v).toBeGreaterThan(0);
    }
  });

  it('ATR reflects range width', () => {
    // Constant range of 6 (high - low)
    const result = calcATR(highs, lows, closes, 14);
    const lastVal = result[result.length - 1]!;
    // Should be close to 6 (the high-low range)
    expect(lastVal).toBeGreaterThan(4);
    expect(lastVal).toBeLessThan(12);
  });
});
