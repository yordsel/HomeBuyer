import { Flame, Clock, BarChart3 } from 'lucide-react';
import type { CompetitionBlockData } from '../../types';

const LABEL_COLORS: Record<string, string> = {
  'Very Competitive': 'bg-red-100 text-red-700',
  Competitive: 'bg-orange-100 text-orange-700',
  Moderate: 'bg-yellow-100 text-yellow-700',
  'Buyer-Friendly': 'bg-green-100 text-green-700',
  'Very Buyer-Friendly': 'bg-emerald-100 text-emerald-700',
};

export function ChatCompetitionCard({ data }: { data: CompetitionBlockData }) {
  const d = data;
  const dom = d.dom_distribution;
  const badgeClass = LABEL_COLORS[d.competition_label ?? ''] ?? 'bg-gray-100 text-gray-700';

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-red-50 to-orange-50 border-b border-gray-100 flex items-center gap-2">
        <Flame size={14} className="text-red-500" />
        <h4 className="text-sm font-semibold text-gray-900">
          Competition{d.neighborhood ? `: ${d.neighborhood}` : ''}
        </h4>
        {d.competition_label && (
          <span className={`ml-auto text-[10px] font-semibold px-2 py-0.5 rounded-full ${badgeClass}`}>
            {d.competition_label}
          </span>
        )}
      </div>

      {/* Score + key stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-0 divide-x divide-gray-100">
        <div className="px-3 py-3 text-center">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide">Score</p>
          <p className="text-xl font-bold text-gray-900 mt-0.5">
            {d.competition_score != null ? d.competition_score.toFixed(0) : '–'}
          </p>
          <p className="text-[9px] text-gray-400">/ 100</p>
        </div>
        <MetricCell
          label="Sale / List"
          value={d.sale_to_list_median != null ? `${(d.sale_to_list_median * 100).toFixed(1)}%` : '–'}
        />
        <MetricCell
          label="Above Asking"
          value={d.above_asking_pct != null ? `${d.above_asking_pct.toFixed(0)}%` : '–'}
        />
        <MetricCell
          label="Inventory"
          value={d.months_of_inventory != null ? `${d.months_of_inventory.toFixed(1)} mo` : '–'}
        />
      </div>

      {/* DOM distribution */}
      {dom && (
        <div className="px-4 py-2.5 border-t border-gray-100">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-1.5 flex items-center gap-1">
            <Clock size={10} />
            Days on Market
          </p>
          <div className="flex items-center gap-4 text-xs">
            {dom.median != null && (
              <span className="text-gray-700">
                <span className="font-medium">{dom.median}</span> median
              </span>
            )}
            {dom.p25 != null && dom.p75 != null && (
              <span className="text-gray-500">
                {dom.p25}–{dom.p75} (IQR)
              </span>
            )}
            {dom.under_7_days_pct != null && (
              <span className="text-gray-500">{dom.under_7_days_pct.toFixed(0)}% under 7d</span>
            )}
          </div>
        </div>
      )}

      {/* Score components */}
      {d.score_components && (
        <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-1.5 flex items-center gap-1">
            <BarChart3 size={10} />
            Score Breakdown
          </p>
          <div className="grid grid-cols-4 gap-2 text-xs">
            {Object.entries(d.score_components).map(([key, val]) => (
              <div key={key} className="text-center">
                <p className="font-medium text-gray-900">{val != null ? val.toFixed(0) : '–'}</p>
                <p className="text-[9px] text-gray-400">{formatScoreLabel(key)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Interpretation */}
      {d.interpretation && (
        <div className="px-4 py-2 border-t border-gray-100 text-xs text-gray-500">
          {d.interpretation}
        </div>
      )}
    </div>
  );
}

function MetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-3 py-3 text-center">
      <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-sm font-bold text-gray-900 mt-0.5">{value}</p>
    </div>
  );
}

function formatScoreLabel(key: string): string {
  return key
    .replace(/_score$/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
