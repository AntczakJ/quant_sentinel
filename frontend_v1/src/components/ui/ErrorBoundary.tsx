/**
 * src/components/ui/ErrorBoundary.tsx — Page-level crash isolation
 */

import { Component, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-64 gap-4">
          <div className="flex items-center gap-2 text-accent-red">
            <AlertTriangle size={20} />
            <span className="text-sm font-medium">
              {this.props.fallbackTitle ?? 'Cos poszlo nie tak'}
            </span>
          </div>
          <p className="text-xs text-th-muted max-w-md text-center">
            {this.state.error?.message ?? 'Unexpected error'}
          </p>
          <button
            onClick={this.handleRetry}
            className="flex items-center gap-1.5 px-4 py-2 bg-accent-blue/15 hover:bg-accent-blue/25 border border-accent-blue/30 rounded text-xs text-accent-blue transition-colors"
          >
            <RefreshCw size={12} />
            Sprobuj ponownie
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
