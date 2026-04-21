import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="app-shell flex h-screen items-center justify-center bg-background px-6">
          <div className="hero-panel max-w-xl animate-fade-in px-8 py-10 text-center">
            <div className="eyebrow mb-4">Application recovery</div>
            <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-[24px] bg-destructive/10 ring-1 ring-destructive/15">
              <AlertTriangle className="h-7 w-7 text-destructive" />
            </div>
            <h2 className="mb-2 text-2xl font-bold text-destructive">Something went wrong</h2>
            <p className="mb-6 text-sm leading-relaxed text-muted-foreground">
              {this.state.error?.message || 'An unexpected error occurred. Please try refreshing the page.'}
            </p>
            <div className="flex flex-wrap items-center justify-center gap-3">
              <button
                onClick={() => this.setState({ hasError: false, error: null })}
                className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition-all hover:opacity-90 active:scale-95"
              >
                <RotateCcw className="h-4 w-4" />
                Try Again
              </button>
              <button
                onClick={() => window.location.reload()}
                className="inline-flex items-center gap-2 rounded-xl border border-border/70 bg-background/75 px-5 py-2.5 text-sm font-medium transition-colors hover:bg-accent"
              >
                Reload App
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
