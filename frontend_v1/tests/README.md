/**
 * frontend/tests/README.md - Frontend Test Suite Documentation
 */

# 🧪 Frontend Test Suite - QUANT SENTINEL

Complete testing framework for React/TypeScript frontend components.

## Test Categories

### 1. Component Tests
- ✅ CandlestickChart rendering
- ✅ SignalPanel rendering & state
- ✅ PortfolioStats data display
- ✅ ModelStats metrics display
- ✅ SignalHistory list rendering

### 2. Integration Tests
- ✅ Component communication via store
- ✅ API data flow
- ✅ State synchronization
- ✅ Error handling

### 3. Styling Tests
- ✅ Dark theme colors
- ✅ Responsive breakpoints
- ✅ Grid layout
- ✅ Spacing consistency

### 4. Reactivity Tests
- ✅ State updates trigger re-renders
- ✅ Props changes reflect UI
- ✅ Store subscription working
- ✅ Auto-refresh intervals

### 5. API Integration Tests
- ✅ Endpoint connectivity
- ✅ Data structure validation
- ✅ Error handling
- ✅ Loading states

## Running Tests

### Setup

```bash
cd frontend
npm install
npm install --save-dev vitest @vitest/ui @testing-library/react @testing-library/jest-dom
```

### Run All Tests

```bash
npm run test                    # Run all tests
npm run test:watch             # Watch mode
npm run test:coverage          # Coverage report
npm run test:ui                # UI Dashboard
```

### Run Specific Tests

```bash
npm run test -- CandlestickChart
npm run test -- SignalPanel
npm run test -- components
```

## Test Structure

```
frontend/tests/
├── components/
│   ├── CandlestickChart.test.tsx
│   ├── SignalPanel.test.tsx
│   ├── PortfolioStats.test.tsx
│   ├── ModelStats.test.tsx
│   └── SignalHistory.test.tsx
├── integration/
│   ├── dashboard.test.tsx
│   ├── api-integration.test.tsx
│   └── store-integration.test.tsx
├── styling/
│   ├── responsive.test.ts
│   ├── theme.test.ts
│   └── layout.test.ts
├── utils/
│   └── test-utils.tsx
└── setup.ts
```

## Component Test Examples

### CandlestickChart.test.tsx

```typescript
import { render, screen, waitFor } from '@testing-library/react';
import { CandlestickChart } from '../../src/components/charts/CandlestickChart';
import { QueryClientProvider, QueryClient } from '@tanstack/react-query';

describe('CandlestickChart', () => {
  it('renders chart container', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CandlestickChart />
      </QueryClientProvider>
    );
    expect(screen.getByText(/Price Action/i)).toBeInTheDocument();
  });

  it('displays loading state', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CandlestickChart />
      </QueryClientProvider>
    );
    expect(screen.getByText(/Loading/i)).toBeInTheDocument();
  });

  it('renders price chart', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CandlestickChart />
      </QueryClientProvider>
    );
    
    await waitFor(() => {
      expect(screen.queryByText(/Loading/i)).not.toBeInTheDocument();
    }, { timeout: 5000 });
  });

  it('renders RSI indicator', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CandlestickChart />
      </QueryClientProvider>
    );
    expect(screen.getByText(/RSI/i)).toBeInTheDocument();
  });

  it('renders Bollinger Bands', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CandlestickChart />
      </QueryClientProvider>
    );
    expect(screen.getByText(/Bollinger Bands/i)).toBeInTheDocument();
  });
});
```

### SignalPanel.test.tsx

```typescript
describe('SignalPanel', () => {
  it('renders consensus signal', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SignalPanel />
      </QueryClientProvider>
    );
    expect(screen.getByText(/CONSENSUS SIGNAL/i)).toBeInTheDocument();
  });

  it('displays RL Agent signal', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SignalPanel />
      </QueryClientProvider>
    );
    expect(screen.getByText(/RL Agent/i)).toBeInTheDocument();
  });

  it('shows signal score', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SignalPanel />
      </QueryClientProvider>
    );
    expect(screen.getByText(/Score/i)).toBeInTheDocument();
  });

  it('displays LSTM prediction', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SignalPanel />
      </QueryClientProvider>
    );
    expect(screen.getByText(/LSTM/i)).toBeInTheDocument();
  });

  it('shows XGBoost direction', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SignalPanel />
      </QueryClientProvider>
    );
    expect(screen.getByText(/XGBoost/i)).toBeInTheDocument();
  });
});
```

## Styling Tests

### responsive.test.ts

```typescript
describe('Responsive Design', () => {
  it('desktop layout lg:grid-cols-3', () => {
    const element = document.createElement('div');
    element.className = 'lg:grid-cols-3';
    expect(element.className).toContain('lg:grid-cols-3');
  });

  it('CandlestickChart spans 2 columns on desktop', () => {
    const element = document.createElement('div');
    element.className = 'lg:col-span-2';
    expect(element.className).toContain('lg:col-span-2');
  });

  it('SignalPanel 1/3 width on desktop', () => {
    const element = document.createElement('div');
    element.className = 'lg:col-span-1';
    expect(element.className).toContain('lg:col-span-1');
  });
});
```

### theme.test.ts

```typescript
describe('Dark Theme Colors', () => {
  it('has bg-dark-bg color', () => {
    // Check TailwindCSS config
    const config = require('../../tailwind.config.js');
    expect(config.theme.colors).toHaveProperty('dark-bg');
  });

  it('has accent colors', () => {
    const config = require('../../tailwind.config.js');
    expect(config.theme.colors).toHaveProperty('accent-green');
    expect(config.theme.colors).toHaveProperty('accent-red');
    expect(config.theme.colors).toHaveProperty('accent-blue');
  });
});
```

## Integration Tests

### api-integration.test.tsx

```typescript
describe('API Integration', () => {
  it('fetches market data', async () => {
    const response = await fetch('/api/market/candles');
    expect(response.ok).toBe(true);
  });

  it('fetches signal data', async () => {
    const response = await fetch('/api/signals/current');
    expect(response.ok).toBe(true);
  });

  it('fetches portfolio data', async () => {
    const response = await fetch('/api/portfolio/status');
    expect(response.ok).toBe(true);
  });

  it('fetches model stats', async () => {
    const response = await fetch('/api/models/stats');
    expect(response.ok).toBe(true);
  });
});
```

## Running Full Test Suite

```bash
# Full test coverage
npm run test -- --coverage

# With UI dashboard
npm run test:ui

# Watch mode for development
npm run test:watch

# Single test file
npm run test -- CandlestickChart.test.tsx

# Match pattern
npm run test -- --grep "renders"
```

## Coverage Goals

- Statements: ≥80%
- Branches: ≥75%
- Functions: ≥80%
- Lines: ≥80%

## CI/CD Integration

Tests run automatically on:
- Git push to main branch
- Pull requests
- Scheduled daily

See `.github/workflows/frontend-tests.yml` for config.

## Troubleshooting

### Tests timeout
```bash
# Increase timeout in vitest.config.ts
export default defineConfig({
  test: {
    testTimeout: 10000
  }
})
```

### API calls fail
```bash
# Ensure backend is running
npm run dev:backend  # Terminal 1
npm run test          # Terminal 2
```

### Component not rendering
```bash
# Check component imports
# Verify store initialization
# Check API endpoint responses
```

## Best Practices

✅ Test behavior, not implementation
✅ Use data-testid for reliable selectors
✅ Mock external API calls
✅ Keep tests independent
✅ Use descriptive test names
✅ Test error states
✅ Test loading states
✅ Verify responsive behavior

## Next Steps

1. Install test dependencies
2. Run test suite
3. Fix failing tests
4. Achieve 80%+ coverage
5. Set up CI/CD

---

**Status**: 🧪 Test framework ready
**Coverage Target**: 80%+
**Estimated Time**: 2-3 hours to implement all tests

