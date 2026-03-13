import { Component, type ReactNode } from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Top-level error boundary that prevents the entire app from going blank
 * on unhandled React rendering errors.
 *
 * Displays a friendly recovery UI with a "Reload" button instead of a
 * white screen.
 */
export class GlobalErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Log for debugging — can be wired to a reporting service later
    console.error('[GlobalErrorBoundary] Uncaught render error:', error, info.componentStack);
  }

  handleReload = () => {
    window.location.reload();
  };

  handleDismiss = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
          <div className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-8 shadow-sm text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-50">
              <AlertTriangle size={28} className="text-red-500" />
            </div>
            <h2 className="mb-2 text-lg font-semibold text-gray-900">
              Something went wrong
            </h2>
            <p className="mb-6 text-sm text-gray-500">
              An unexpected error occurred. You can try reloading the page or
              dismissing this message.
            </p>
            {this.state.error && (
              <pre className="mb-6 rounded-lg bg-gray-50 p-3 text-left text-xs text-gray-600 overflow-auto max-h-32">
                {this.state.error.message}
              </pre>
            )}
            <div className="flex gap-3 justify-center">
              <button
                onClick={this.handleDismiss}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Dismiss
              </button>
              <button
                onClick={this.handleReload}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
              >
                <RotateCcw size={14} />
                Reload Page
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
