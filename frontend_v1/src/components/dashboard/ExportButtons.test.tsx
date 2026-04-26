import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TestWrapper } from '../../test/wrapper';
import { ExportButtons } from './ExportButtons';

describe('ExportButtons', () => {
  it('renders all export options', () => {
    render(<ExportButtons />, { wrapper: TestWrapper });
    expect(screen.getByText('Trades CSV')).toBeTruthy();
    expect(screen.getByText('Trades JSON')).toBeTruthy();
    expect(screen.getByText('Equity CSV')).toBeTruthy();
    expect(screen.getByText('Daily Report')).toBeTruthy();
  });

  it('renders Export label', () => {
    render(<ExportButtons />, { wrapper: TestWrapper });
    expect(screen.getByText('Export')).toBeTruthy();
  });
});
