/**
 * ResumeBriefingCard — structured "welcome back" card for returning users.
 *
 * Shows market changes, property status updates, and stale analysis warnings
 * when a returning user's first turn triggers a `resume_briefing` SSE event.
 *
 * Phase H-5 (#74) of Epic #23.
 */
import {
  ArrowUp, ArrowDown, Home, AlertTriangle, TrendingUp,
  Package, DollarSign, X,
} from 'lucide-react';
import type { ResumeBriefingData, MarketChange } from '../../types';

function MarketChangeItem({ change }: { change: MarketChange }) {
  const isUp = change.direction === 'up';
  const Arrow = isUp ? ArrowUp : ArrowDown;
  const arrowColor = isUp ? 'text-red-500' : 'text-green-500';

  let icon = <DollarSign size={14} />;
  let label = '';
  let value = '';

  switch (change.type) {
    case 'mortgage_rate':
      icon = <TrendingUp size={14} />;
      label = 'Mortgage rates';
      value = `${change.change}% ${isUp ? 'higher' : 'lower'}`;
      break;
    case 'median_price':
      icon = <DollarSign size={14} />;
      label = 'Median price';
      value = `$${change.change.toLocaleString()} ${isUp ? 'higher' : 'lower'}`;
      break;
    case 'inventory':
      icon = <Package size={14} />;
      label = 'Inventory';
      value = `${change.change} listings ${isUp ? 'more' : 'fewer'}`;
      break;
  }

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-gray-500">{icon}</span>
      <span className="font-medium text-gray-700">{label}</span>
      <Arrow size={12} className={arrowColor} />
      <span className="text-gray-600">{value}</span>
      <span className="text-gray-400 text-xs">({change.direction === 'up' ? '+' : '-'}{Math.abs(change.change_pct)}%)</span>
    </div>
  );
}

interface ResumeBriefingCardProps {
  briefing: ResumeBriefingData;
  onDismiss: () => void;
}

export function ResumeBriefingCard({ briefing, onDismiss }: ResumeBriefingCardProps) {
  return (
    <div className="mx-auto max-w-2xl mb-4 rounded-xl border border-indigo-200 bg-gradient-to-br from-indigo-50 to-white p-4 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="flex items-center justify-center w-8 h-8 rounded-full bg-indigo-100 text-indigo-600">
            <TrendingUp size={16} />
          </div>
          <div>
            <h3 className="text-sm font-bold text-gray-900">Welcome back!</h3>
            <p className="text-xs text-gray-500">Here's what changed since your last visit</p>
          </div>
        </div>
        <button
          onClick={onDismiss}
          className="p-1 rounded-full hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
          title="Dismiss"
        >
          <X size={16} />
        </button>
      </div>

      {/* Market changes */}
      {briefing.market_changes.length > 0 && (
        <div className="mb-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
            Market Changes
          </p>
          <div className="space-y-1.5">
            {briefing.market_changes.map((change, i) => (
              <MarketChangeItem key={i} change={change} />
            ))}
          </div>
        </div>
      )}

      {/* Focus property */}
      {briefing.focus_property && (
        <div className="mb-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
            Your Property
          </p>
          <div className="flex items-center gap-2 text-sm">
            <Home size={14} className="text-gray-500" />
            <span className="font-medium text-gray-700">{briefing.focus_property.address}</span>
            <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-600">
              {briefing.focus_property.last_known_status}
            </span>
          </div>
        </div>
      )}

      {/* Stale analyses */}
      {briefing.stale_analyses && briefing.stale_analyses.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
            May Need Updating
          </p>
          <div className="space-y-1">
            {briefing.stale_analyses.map((stale, i) => (
              <div key={i} className="flex items-center gap-2 text-sm text-amber-700">
                <AlertTriangle size={12} />
                <span>{stale.tool.replace(/_/g, ' ')} for {stale.address}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
