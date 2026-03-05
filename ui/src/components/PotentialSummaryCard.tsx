import { useState, useEffect } from 'react';
import {
  Loader2,
  Sparkles,
  ArrowRight,
  AlertTriangle,
  CheckCircle2,
  Info,
  RefreshCw,
} from 'lucide-react';
import * as api from '../lib/tauri';
import type {
  ListingData,
  PotentialSummaryResponse,
  AIPotentialSummary,
  DevelopmentPotentialResponse,
} from '../types';

interface PotentialSummaryCardProps {
  listing: ListingData;
  onViewDetails: () => void;
}

export function PotentialSummaryCard({
  listing,
  onViewDetails,
}: PotentialSummaryCardProps) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<PotentialSummaryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  function fetchSummary() {
    setLoading(true);
    setError(null);
    setData(null);

    api
      .getPropertyPotentialSummary({
        latitude: listing.latitude,
        longitude: listing.longitude,
        address: listing.address || undefined,
        lot_size_sqft: listing.lot_size_sqft ?? undefined,
        sqft: listing.sqft ?? undefined,
        neighborhood: listing.neighborhood ?? undefined,
        beds: listing.beds ?? undefined,
        baths: listing.baths ?? undefined,
        year_built: listing.year_built ?? undefined,
      })
      .then((resp) => {
        setData(resp);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
  }

  useEffect(() => {
    let cancelled = false;

    api
      .getPropertyPotentialSummary({
        latitude: listing.latitude,
        longitude: listing.longitude,
        address: listing.address || undefined,
        lot_size_sqft: listing.lot_size_sqft ?? undefined,
        sqft: listing.sqft ?? undefined,
        neighborhood: listing.neighborhood ?? undefined,
        beds: listing.beds ?? undefined,
        baths: listing.baths ?? undefined,
        year_built: listing.year_built ?? undefined,
      })
      .then((resp) => {
        if (!cancelled) {
          setData(resp);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [listing.latitude, listing.longitude]);

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles size={18} className="text-amber-500" />
          <h3 className="font-semibold text-gray-900">Development Potential</h3>
        </div>
        <button
          onClick={onViewDetails}
          className="flex items-center gap-1.5 text-xs font-medium text-blue-600
                     hover:text-blue-800 transition-colors"
        >
          View Details
          <ArrowRight size={14} />
        </button>
      </div>

      {/* Body */}
      <div className="px-6 py-4">
        {loading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={20} className="animate-spin text-blue-500 mr-2" />
            <span className="text-sm text-gray-500">
              Analyzing development potential...
            </span>
          </div>
        )}

        {!loading && error && (
          <div className="flex flex-col items-center py-6 text-center">
            <AlertTriangle size={24} className="text-amber-400 mb-2" />
            <p className="text-sm text-gray-600 mb-3">{error}</p>
            <button
              onClick={fetchSummary}
              className="flex items-center gap-1.5 text-xs font-medium text-blue-600
                         hover:text-blue-800 transition-colors"
            >
              <RefreshCw size={12} />
              Retry
            </button>
          </div>
        )}

        {!loading && data && (
          <div className="space-y-4">
            {data.ai_summary ? (
              <AISummaryContent summary={data.ai_summary} />
            ) : data.ai_error ? (
              <div className="flex items-start gap-2 text-sm text-amber-600 bg-amber-50 rounded-lg p-3">
                <Info size={16} className="shrink-0 mt-0.5" />
                <span>{data.ai_error}</span>
              </div>
            ) : null}

            <QuickPotentialStats potential={data.potential} />
          </div>
        )}
      </div>
    </div>
  );
}

function AISummaryContent({ summary }: { summary: AIPotentialSummary }) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-700 leading-relaxed">{summary.summary}</p>

      <div className="bg-blue-50 rounded-lg p-3">
        <p className="text-xs font-medium text-blue-700 uppercase tracking-wide mb-1">
          Recommendation
        </p>
        <p className="text-sm text-blue-800">{summary.recommendation}</p>
      </div>

      {summary.highlights.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">
            Highlights
          </p>
          <ul className="space-y-1">
            {summary.highlights.map((h, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-sm text-gray-700"
              >
                <CheckCircle2
                  size={14}
                  className="text-green-500 shrink-0 mt-0.5"
                />
                {h}
              </li>
            ))}
          </ul>
        </div>
      )}

      {summary.caveats.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">
            Caveats & Fine Print
          </p>
          <ul className="space-y-1">
            {summary.caveats.map((c, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-xs text-gray-500"
              >
                <AlertTriangle
                  size={12}
                  className="text-amber-400 shrink-0 mt-0.5"
                />
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function QuickPotentialStats({
  potential,
}: {
  potential: DevelopmentPotentialResponse;
}) {
  const pills: { label: string; ok: boolean }[] = [];

  if (potential.units) {
    pills.push({
      label: `Up to ${potential.units.effective_max_units} units`,
      ok: potential.units.effective_max_units > 1,
    });
  }
  if (potential.adu) {
    pills.push({
      label: potential.adu.eligible ? 'ADU Eligible' : 'No ADU',
      ok: potential.adu.eligible,
    });
  }
  if (potential.sb9) {
    pills.push({
      label: potential.sb9.can_split ? 'SB 9 Split OK' : 'No SB 9',
      ok: potential.sb9.can_split,
    });
  }
  if (potential.zoning) {
    pills.push({
      label: potential.zoning.zone_class,
      ok: true,
    });
  }

  if (pills.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5">
      {pills.map((p, i) => (
        <span
          key={i}
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
            p.ok
              ? 'bg-green-50 text-green-700 border border-green-200'
              : 'bg-gray-50 text-gray-500 border border-gray-200'
          }`}
        >
          {p.label}
        </span>
      ))}
    </div>
  );
}
