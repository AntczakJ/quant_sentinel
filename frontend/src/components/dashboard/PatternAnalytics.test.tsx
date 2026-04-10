import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TestWrapper } from '../../test/wrapper';

vi.mock('../../hooks/usePollingQuery', () => ({
  usePollingQuery: (key: string) => {
    if (key === 'analysis-stats') {
      return {
        data: {
          total_trades: 20, wins: 8, losses: 12, win_rate: 0.4,
          patterns: [
            { pattern: 'Engulfing', count: 10, wins: 6, losses: 4, win_rate: 0.6 },
            { pattern: 'FVG', count: 5, wins: 1, losses: 4, win_rate: 0.2 },
          ],
        },
        isLoading: false,
      };
    }
    return {
      data: { trades: [
        { direction: 'LONG', result: 'WIN', timestamp: '2026-04-10T10:00:00Z', pattern: 'Engulfing' },
        { direction: 'SHORT', result: 'LOSS', timestamp: '2026-04-10T15:00:00Z', pattern: 'FVG' },
      ] },
      isLoading: false,
    };
  },
}));

import { PatternAnalytics } from './PatternAnalytics';

describe('PatternAnalytics', () => {
  it('renders direction stats', () => {
    render(<PatternAnalytics />, { wrapper: TestWrapper });
    expect(screen.getAllByText('LONG').length).toBeGreaterThan(0);
    expect(screen.getAllByText('SHORT').length).toBeGreaterThan(0);
  });

  it('renders pattern bars', () => {
    render(<PatternAnalytics />, { wrapper: TestWrapper });
    expect(screen.getByText('Engulfing')).toBeTruthy();
    expect(screen.getByText('FVG')).toBeTruthy();
  });

  it('renders heatmap header', () => {
    render(<PatternAnalytics />, { wrapper: TestWrapper });
    expect(screen.getByText('Session x Direction — Win Rate')).toBeTruthy();
  });
});
