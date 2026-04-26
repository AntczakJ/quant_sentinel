import { describe, it, expect } from 'vitest';
import { isCircuitOpen } from './client';

describe('API client', () => {
  it('exports isCircuitOpen function', () => {
    expect(typeof isCircuitOpen).toBe('function');
  });

  it('circuit starts closed', () => {
    expect(isCircuitOpen()).toBe(false);
  });
});

describe('API client exports', () => {
  it('exports all API namespaces', async () => {
    const client = await import('./client');
    expect(client.marketAPI).toBeDefined();
    expect(client.signalsAPI).toBeDefined();
    expect(client.portfolioAPI).toBeDefined();
    expect(client.modelsAPI).toBeDefined();
    expect(client.trainingAPI).toBeDefined();
    expect(client.healthAPI).toBeDefined();
    expect(client.analysisAPI).toBeDefined();
    expect(client.agentAPI).toBeDefined();
    expect(client.exportAPI).toBeDefined();
    expect(client.modelMonitorAPI).toBeDefined();
    expect(client.newsAPI).toBeDefined();
    expect(client.backtestAPI).toBeDefined();
    expect(client.riskAPI).toBeDefined();
  });

  it('marketAPI has expected methods', async () => {
    const { marketAPI } = await import('./client');
    expect(typeof marketAPI.getCandles).toBe('function');
    expect(typeof marketAPI.getTicker).toBe('function');
    expect(typeof marketAPI.getIndicators).toBe('function');
  });

  it('riskAPI has halt/resume/getStatus', async () => {
    const { riskAPI } = await import('./client');
    expect(typeof riskAPI.getStatus).toBe('function');
    expect(typeof riskAPI.halt).toBe('function');
    expect(typeof riskAPI.resume).toBe('function');
  });

  it('exportAPI has download methods', async () => {
    const { exportAPI } = await import('./client');
    expect(typeof exportAPI.downloadTrades).toBe('function');
    expect(typeof exportAPI.downloadEquity).toBe('function');
    expect(typeof exportAPI.getDailyReport).toBe('function');
    expect(typeof exportAPI.getExecutionQuality).toBe('function');
  });
});
