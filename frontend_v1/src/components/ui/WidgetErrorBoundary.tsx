/**
 * src/components/ui/WidgetErrorBoundary.tsx — Per-widget error boundary
 *
 * Catches errors in individual dashboard widgets without crashing the whole page.
 * Shows a compact error card with retry button.
 */

import { Component, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  widgetName?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class WidgetErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center py-6 px-4 text-center">
          <div className="w-10 h-10 rounded-full bg-accent-red/10 flex items-center justify-center mb-3">
            <AlertTriangle size={18} className="text-accent-red" />
          </div>
          <div className="text-xs font-medium text-th-secondary mb-1">
            {this.props.widgetName ?? 'Widget'} — error
          </div>
          <div className="text-[10px] text-th-dim mb-3 max-w-[200px] truncate">
            {this.state.error?.message ?? 'Unknown error'}
          </div>
          <button
            onClick={this.handleRetry}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-medium bg-accent-blue/10 text-accent-blue border border-accent-blue/20 hover:bg-accent-blue/20 transition-colors"
          >
            <RefreshCw size={10} />
            Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
