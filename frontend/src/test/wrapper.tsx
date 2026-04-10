/**
 * Test wrapper providing QueryClient + BrowserRouter for component tests
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../components/ui/Toast';
import type { ReactNode } from 'react';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, gcTime: 0 },
  },
});

export function TestWrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ToastProvider>
          {children}
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}
