import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TestWrapper } from '../../test/wrapper';

vi.mock('../../hooks/usePollingQuery', () => ({
  usePollingQuery: () => ({
    data: {
      drift: { xgb: { psi: 0.05, status: 'ok' }, lstm: { psi: 0.15, status: 'warn' } },
      accuracy: { xgb: { rolling_accuracy: 0.62, window: 20, trend: 'stable' } },
      calibration: {},
      alerts: ['LSTM drift detected: PSI=0.15'],
      healthy: false,
    },
    isLoading: false,
  }),
}));

import { ModelDriftAlert } from './ModelDriftAlert';

describe('ModelDriftAlert', () => {
  it('renders alert banner', () => {
    render(<ModelDriftAlert />, { wrapper: TestWrapper });
    expect(screen.getByText('1 Model Alert')).toBeTruthy();
  });
});
