/**
 * Shared loading and error state components for data-fetching cards.
 *
 * Previously duplicated across RentalIncomeCard.tsx and
 * InvestmentScenarioCard.tsx.
 */
import { Loader2, AlertTriangle, RefreshCw } from 'lucide-react';

interface CardLoadingProps {
  /** Message shown next to spinner (e.g., "Analyzing rental income...") */
  message: string;
  /** Spinner color class (default: text-green-500) */
  spinnerColor?: string;
}

export function CardLoading({ message, spinnerColor = 'text-green-500' }: CardLoadingProps) {
  return (
    <div className="flex items-center justify-center py-8">
      <Loader2 size={20} className={`animate-spin ${spinnerColor} mr-2`} />
      <span className="text-sm text-gray-500">{message}</span>
    </div>
  );
}

interface CardErrorProps {
  /** Error message to display */
  message: string;
  /** Callback when user clicks "Retry" */
  onRetry: () => void;
}

export function CardError({ message, onRetry }: CardErrorProps) {
  return (
    <div className="flex flex-col items-center py-6 text-center">
      <AlertTriangle size={24} className="text-amber-400 mb-2" />
      <p className="text-sm text-gray-600 mb-3">{message}</p>
      <button
        onClick={onRetry}
        className="flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:text-blue-800"
      >
        <RefreshCw size={12} />
        Retry
      </button>
    </div>
  );
}
