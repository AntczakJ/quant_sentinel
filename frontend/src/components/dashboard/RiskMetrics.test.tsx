import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TestWrapper } from '../../test/wrapper';

// Mock the polling hook to return test data
vi.mock('../../hooks/usePollingQuery', () => ({
  usePollingQuery: () => ({
    data: {
      total: 30, wins: 10, losses: 20,
      win_rate: 0.333, avg_win: 50, avg_loss: 20,
      profit_factor: 1.25, expectancy: 3.33,
      max_consecutive_wins: 3, max_consecutive_losses: 5,
      max_drawdown: 150, total_profit: 100,
    },
    isLoading: false,
    error: null,
  }),
}));

import { RiskMetrics } from './RiskMetrics';

describe('RiskMetrics', () => {
  it('renders without crashing', () => {
    render(<RiskMetrics />, { wrapper: TestWrapper });
  });

  it('displays expectancy value', () => {
    render(<RiskMetrics />, { wrapper: TestWrapper });
    expect(screen.getByText('$3.33')).toBeTruthy();
  });

  it('displays win rate percentage', () => {
    render(<RiskMetrics />, { wrapper: TestWrapper });
    expect(screen.getByText('33.3%')).toBeTruthy();
  });

  it('displays total P&L', () => {
    render(<RiskMetrics />, { wrapper: TestWrapper });
    expect(screen.getByText('+$100.00')).toBeTruthy();
  });

  it('shows risk profile label', () => {
    render(<RiskMetrics />, { wrapper: TestWrapper });
    // profit_factor >= 1 → UMIARKOWANY
    const el = screen.getByText('UMIARKOWANY');
    expect(el).toBeTruthy();
  });
});
