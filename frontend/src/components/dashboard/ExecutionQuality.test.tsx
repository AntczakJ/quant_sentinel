import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TestWrapper } from '../../test/wrapper';

vi.mock('../../hooks/usePollingQuery', () => ({
  usePollingQuery: () => ({
    data: {
      period_days: 30, total_trades: 15, wins: 8, losses: 7,
      win_rate: 0.533, total_pnl: 250, avg_pnl: 16.67,
      fill_rate: 0.85, avg_slippage: 0.35, slippage_samples: 10,
      by_grade: {
        'A': { wins: 5, losses: 2, pnl: 200, win_rate: 0.714, total: 7 },
        'B': { wins: 3, losses: 5, pnl: 50, win_rate: 0.375, total: 8 },
      },
    },
    isLoading: false,
  }),
}));

import { ExecutionQuality } from './ExecutionQuality';

describe('ExecutionQuality', () => {
  it('renders without crashing', () => {
    render(<ExecutionQuality />, { wrapper: TestWrapper });
  });

  it('displays fill rate', () => {
    render(<ExecutionQuality />, { wrapper: TestWrapper });
    expect(screen.getByText('85.0%')).toBeTruthy();
  });

  it('displays avg slippage', () => {
    render(<ExecutionQuality />, { wrapper: TestWrapper });
    expect(screen.getByText('$0.3500')).toBeTruthy();
  });

  it('displays grade rows', () => {
    render(<ExecutionQuality />, { wrapper: TestWrapper });
    expect(screen.getByText('A')).toBeTruthy();
    expect(screen.getByText('B')).toBeTruthy();
  });
});
