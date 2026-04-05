/**
 * drawings/storage.ts — Persist user drawings in localStorage.
 */

import type { Drawing } from './types';

const PREFIX = 'qs-drawings';

function key(symbol: string, interval: string): string {
  return `${PREFIX}:${symbol}:${interval}`;
}

export function saveDrawings(symbol: string, interval: string, drawings: Drawing[]): void {
  try {
    localStorage.setItem(key(symbol, interval), JSON.stringify(drawings));
  } catch { /* quota exceeded — silently ignore */ }
}

export function loadDrawings(symbol: string, interval: string): Drawing[] {
  try {
    const raw = localStorage.getItem(key(symbol, interval));
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function clearDrawings(symbol: string, interval: string): void {
  localStorage.removeItem(key(symbol, interval));
}

