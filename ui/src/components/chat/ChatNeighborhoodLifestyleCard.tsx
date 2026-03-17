import { MapPin, Star, Train } from 'lucide-react';
import type { NeighborhoodLifestyleBlockData, NeighborhoodLifestyleScores } from '../../types';

const FACTOR_ORDER: (keyof NeighborhoodLifestyleScores)[] = [
  'walkability',
  'transit',
  'schools',
  'dining',
  'parks',
  'safety',
];

const FACTOR_LABELS: Record<string, string> = {
  walkability: 'Walk',
  transit: 'Transit',
  schools: 'Schools',
  dining: 'Dining',
  parks: 'Parks',
  safety: 'Safety',
};

function scoreColor(score: number): string {
  if (score >= 8) return 'bg-green-500';
  if (score >= 6) return 'bg-green-400';
  if (score >= 4) return 'bg-yellow-400';
  if (score >= 2) return 'bg-orange-400';
  return 'bg-red-400';
}

export function ChatNeighborhoodLifestyleCard({ data }: { data: NeighborhoodLifestyleBlockData }) {
  const d = data;
  const comparisons = d.comparisons ?? [];

  if (comparisons.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4 my-2 text-center text-xs text-gray-500">
        No neighborhood lifestyle data available.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-teal-50 to-cyan-50 border-b border-gray-100 flex items-center gap-2">
        <MapPin size={14} className="text-teal-600" />
        <h4 className="text-sm font-semibold text-gray-900">Neighborhood Lifestyle</h4>
        <span className="text-[10px] text-gray-400 ml-auto">
          {d.neighborhoods_compared ?? comparisons.length} neighborhoods
        </span>
      </div>

      {/* Comparison grid */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
              <th className="px-3 py-2 text-left">Neighborhood</th>
              {FACTOR_ORDER.map((f) => (
                <th key={f} className="px-2 py-2 text-center">
                  {FACTOR_LABELS[f]}
                </th>
              ))}
              <th className="px-3 py-2 text-right">Score</th>
              <th className="px-3 py-2 text-left">Character</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {comparisons.map((c, i) => {
              const isBest = d.best_overall === c.neighborhood;
              return (
                <tr key={i} className={isBest ? 'bg-teal-50' : ''}>
                  <td className="px-3 py-1.5 font-medium text-gray-700 whitespace-nowrap">
                    {isBest && <Star size={10} className="text-amber-500 inline mr-1" />}
                    {c.neighborhood || '–'}
                    {c.bart_station && (
                      <span className="ml-1 text-[9px] text-gray-400">
                        <Train size={8} className="inline" /> {c.bart_minutes}min
                      </span>
                    )}
                  </td>
                  {FACTOR_ORDER.map((f) => {
                    const score = c.scores?.[f];
                    return (
                      <td key={f} className="px-2 py-1.5 text-center">
                        {score != null ? (
                          <span
                            className={`inline-block w-5 h-5 rounded text-[10px] font-bold text-white leading-5 ${scoreColor(score)}`}
                          >
                            {score}
                          </span>
                        ) : (
                          <span className="text-gray-300">–</span>
                        )}
                      </td>
                    );
                  })}
                  <td className="px-3 py-1.5 text-right font-bold text-gray-900">
                    {c.composite_score != null ? c.composite_score.toFixed(1) : '–'}
                  </td>
                  <td className="px-3 py-1.5 text-gray-500 max-w-[120px] truncate">
                    {c.character || '–'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Best per factor */}
      {d.best_per_factor && Object.keys(d.best_per_factor).length > 0 && (
        <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-1.5">
            Best Per Factor
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {FACTOR_ORDER.map((f) => {
              const best = d.best_per_factor?.[f];
              return best ? (
                <span key={f} className="text-gray-600">
                  <span className="text-gray-400">{FACTOR_LABELS[f]}:</span>{' '}
                  <span className="font-medium">{best}</span>
                </span>
              ) : null;
            })}
          </div>
        </div>
      )}
    </div>
  );
}
