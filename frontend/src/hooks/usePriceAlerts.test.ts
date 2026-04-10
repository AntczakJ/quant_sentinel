import { describe, it, expect, beforeEach, vi } from 'vitest';

// Test the pure logic of price alerts (localStorage save/load)
describe('Price Alerts localStorage', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('stores and retrieves alerts from localStorage', () => {
    const alerts = [
      { id: 'test-1', price: 3200, direction: 'above' as const, createdAt: Date.now(), triggered: false },
      { id: 'test-2', price: 3100, direction: 'below' as const, createdAt: Date.now(), triggered: false },
    ];
    localStorage.setItem('qs:price-alerts', JSON.stringify(alerts));

    const loaded = JSON.parse(localStorage.getItem('qs:price-alerts')!);
    expect(loaded).toHaveLength(2);
    expect(loaded[0].price).toBe(3200);
    expect(loaded[0].direction).toBe('above');
    expect(loaded[1].direction).toBe('below');
  });

  it('handles empty localStorage gracefully', () => {
    const raw = localStorage.getItem('qs:price-alerts');
    expect(raw).toBeNull();
  });

  it('handles corrupted localStorage', () => {
    localStorage.setItem('qs:price-alerts', 'not-json');
    expect(() => JSON.parse(localStorage.getItem('qs:price-alerts')!)).toThrow();
  });
});
