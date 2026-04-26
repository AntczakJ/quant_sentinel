import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: (error: Error, reset: () => void) => ReactNode
}

interface State {
  error: Error | null
}

/**
 * Catches render-time errors in any descendant route. Without this, a
 * thrown render leaves the whole shell on a blank screen — Janek would
 * have to open devtools just to see "what broke". Now any throw lands
 * here, the rest of the app stays interactive (header / Cmd+K / health
 * popover keep working), and the operator gets a clear "reload" path.
 *
 * Class component is required — React's hook API still has no equivalent
 * to `componentDidCatch`. Mounted in App.tsx around `<Routes>`.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary]', error, info.componentStack)
    // Optional: ship to a JS-side observer (Sentry browser SDK, etc.).
    // Today we just log — the backend route /api/system/test-error is
    // for backend-side capture, not browser.
  }

  reset = () => this.setState({ error: null })

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    if (this.props.fallback) {
      return this.props.fallback(error, this.reset)
    }

    return (
      <div className="surface-raised rounded-xl3 p-8 max-w-2xl mx-auto mt-12">
        <div className="text-micro uppercase tracking-wider text-bear mb-2">Render error</div>
        <h2 className="text-display-sm font-display text-ink-900 leading-tight">
          Something broke on this page.
        </h2>
        <p className="text-body text-ink-700 mt-3">
          The rest of the app is still working — header navigation, Cmd+K,
          and the health popover are unaffected. Either reload to retry, or
          jump to another page.
        </p>
        <details className="mt-5">
          <summary className="text-caption text-ink-600 cursor-pointer hover:text-ink-800">
            Technical detail
          </summary>
          <pre className="mt-2 p-3 rounded-xl bg-ink-50 border border-white/[0.06] text-micro text-ink-700 overflow-auto max-h-48">
            {error.name}: {error.message}
            {error.stack ? '\n\n' + error.stack.split('\n').slice(0, 10).join('\n') : ''}
          </pre>
        </details>
        <div className="mt-6 flex gap-3">
          <button
            type="button"
            onClick={this.reset}
            className="px-4 py-2 rounded-full text-caption border border-white/15 hover:bg-white/[0.06] hover:border-white/25 transition-all"
          >
            Try again
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-full text-caption bg-gold-500/[0.12] text-gold-400 border border-gold-500/30 hover:bg-gold-500/[0.18] transition-all"
          >
            Reload page
          </button>
        </div>
      </div>
    )
  }
}
