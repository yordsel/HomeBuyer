/**
 * Compact investment prospectus summary card for chat inline display.
 *
 * Shows a concise overview with key metrics and a "Download Prospectus (PDF)"
 * button. Supports single-property, curated portfolio, similar comparison,
 * and thesis modes with appropriate badges and content.
 */
import { useState } from 'react';
import { FileText, Download, Loader2, TrendingUp, GitCompare, BookOpen } from 'lucide-react';
import { formatCurrency, formatPct } from '../../lib/utils';
import type { InvestmentProspectusResponse, PropertyProspectus, PortfolioSummary } from '../../types';

export function ChatInvestmentProspectus({ data }: { data: Record<string, unknown> }) {
  const d = data as unknown as InvestmentProspectusResponse;
  const properties = d.properties ?? [];

  if (properties.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4 my-2 text-center text-xs text-gray-500">
        No prospectus data available.
      </div>
    );
  }

  const mode = d.portfolio_summary?.mode;

  // Multi-property modes
  if (d.is_multi_property && d.portfolio_summary) {
    if (mode === 'thesis') {
      return <ThesisCard summary={d.portfolio_summary} properties={properties} data={d} />;
    }
    if (mode === 'similar') {
      return <SimilarCard summary={d.portfolio_summary} properties={properties} data={d} />;
    }
    return <PortfolioCard summary={d.portfolio_summary} properties={properties} data={d} />;
  }

  // Single property
  return <PropertyCard property={properties[0]} data={d} />;
}

// ---------------------------------------------------------------------------
// Single property card
// ---------------------------------------------------------------------------

function PropertyCard({
  property: p,
  data,
}: {
  property: PropertyProspectus;
  data: InvestmentProspectusResponse;
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-amber-50 to-yellow-50 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileText size={14} className="text-amber-600" />
          <h4 className="text-sm font-semibold text-gray-900">Investment Prospectus</h4>
        </div>
        <span className="text-xs text-gray-500 truncate max-w-[50%]">
          {p.address || p.neighborhood}
        </span>
      </div>

      {/* Strategy recommendation */}
      {p.recommended_approach_label && (
        <div className="px-4 py-2.5 bg-gradient-to-r from-emerald-50 to-green-50 border-b border-gray-100">
          <p className="text-xs font-bold text-gray-900">{p.recommended_approach_label}</p>
          {p.strategy_rationale && (
            <p className="text-[11px] text-gray-600 mt-0.5 line-clamp-2 leading-relaxed">
              {p.strategy_rationale}
            </p>
          )}
        </div>
      )}

      {/* Key metrics */}
      <div className="px-4 py-3 border-b border-gray-100">
        <div className="grid grid-cols-4 gap-3 text-center">
          <Metric label="Est. Value" value={formatCurrency(p.estimated_value)} />
          <Metric label="Capital" value={formatCurrency(p.capital_required)} />
          <Metric
            label="Monthly CF"
            value={formatCurrency(p.monthly_cash_flow)}
            color={p.monthly_cash_flow >= 0 ? 'green' : 'red'}
          />
          <Metric label="Return" value={formatPct(p.projected_annual_return_pct)} />
        </div>
      </div>

      {/* Download + footer */}
      <div className="px-4 py-2.5 flex items-center justify-between">
        <DownloadButton data={data} />
        <span className="text-[9px] text-gray-400">
          {p.data_sources.length} data sources
          {p.generated_at && ` \u00B7 ${new Date(p.generated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Curated Portfolio card
// ---------------------------------------------------------------------------

function PortfolioCard({
  summary,
  properties,
  data,
}: {
  summary: PortfolioSummary;
  properties: PropertyProspectus[];
  data: InvestmentProspectusResponse;
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-amber-50 to-yellow-50 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp size={14} className="text-amber-600" />
          <h4 className="text-sm font-semibold text-gray-900">Portfolio Prospectus</h4>
          <ModeBadge mode="curated" />
        </div>
        <span className="text-xs text-gray-500">{summary.property_count} Properties</span>
      </div>

      {/* Investment thesis snippet */}
      {summary.investment_thesis && (
        <div className="px-4 py-2.5 bg-gradient-to-r from-amber-50/50 to-yellow-50/50 border-b border-gray-100">
          <p className="text-[11px] text-gray-600 line-clamp-2 leading-relaxed">
            {summary.investment_thesis}
          </p>
        </div>
      )}

      {/* Portfolio metrics */}
      <div className="px-4 py-3 border-b border-gray-100">
        <div className="grid grid-cols-4 gap-3 text-center">
          <Metric label="Total Capital" value={formatCurrency(summary.total_capital_required)} />
          <Metric
            label="Monthly CF"
            value={formatCurrency(summary.total_monthly_cash_flow)}
            color={summary.total_monthly_cash_flow >= 0 ? 'green' : 'red'}
          />
          <Metric label="Avg Cap Rate" value={formatPct(summary.weighted_avg_cap_rate)} />
          <Metric label="Avg CoC" value={formatPct(summary.weighted_avg_coc)} />
        </div>
      </div>

      {/* Property list */}
      <div className="px-4 py-2 border-b border-gray-100 space-y-1">
        {properties.map((p, i) => (
          <div key={i} className="flex items-center justify-between text-xs">
            <span className="text-gray-700 truncate max-w-[55%]">{p.address || p.neighborhood}</span>
            <span className="text-gray-500">{p.recommended_approach_label || '\u2014'}</span>
          </div>
        ))}
      </div>

      {/* Download + footer */}
      <div className="px-4 py-2.5 flex items-center justify-between">
        <DownloadButton data={data} label="Download Portfolio (PDF)" />
        <span className="text-[9px] text-gray-400">
          {properties[0]?.data_sources?.length || 0} data sources
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Similar comparison card
// ---------------------------------------------------------------------------

function SimilarCard({
  summary,
  properties,
  data,
}: {
  summary: PortfolioSummary;
  properties: PropertyProspectus[];
  data: InvestmentProspectusResponse;
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitCompare size={14} className="text-blue-600" />
          <h4 className="text-sm font-semibold text-gray-900">Investment Comparison</h4>
          <ModeBadge mode="similar" />
        </div>
        <span className="text-xs text-gray-500">{summary.property_count} Properties</span>
      </div>

      {/* Shared traits */}
      {(summary.shared_traits ?? []).length > 0 && (
        <div className="px-4 py-2.5 bg-blue-50/50 border-b border-gray-100">
          <p className="text-[10px] font-medium text-blue-700 uppercase tracking-wide mb-1">Shared Traits</p>
          <div className="flex flex-wrap gap-1.5">
            {summary.shared_traits!.slice(0, 3).map((trait, i) => (
              <span key={i} className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] bg-blue-100 text-blue-700 border border-blue-200">
                {trait}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Group metrics */}
      <div className="px-4 py-3 border-b border-gray-100">
        <div className="grid grid-cols-4 gap-3 text-center">
          <Metric label="Total Capital" value={formatCurrency(summary.total_capital_required)} />
          <Metric
            label="Avg Monthly CF"
            value={formatCurrency(summary.total_monthly_cash_flow / Math.max(summary.property_count, 1))}
            color={summary.total_monthly_cash_flow >= 0 ? 'green' : 'red'}
          />
          <Metric label="Avg Cap Rate" value={formatPct(summary.weighted_avg_cap_rate)} />
          <Metric label="Avg CoC" value={formatPct(summary.weighted_avg_coc)} />
        </div>
      </div>

      {/* Property list */}
      <div className="px-4 py-2 border-b border-gray-100 space-y-1">
        {properties.map((p, i) => (
          <div key={i} className="flex items-center justify-between text-xs">
            <span className="text-gray-700 truncate max-w-[55%]">{p.address || p.neighborhood}</span>
            <span className="text-gray-500">{formatCurrency(p.monthly_cash_flow)}/mo</span>
          </div>
        ))}
      </div>

      {/* Download + footer */}
      <div className="px-4 py-2.5 flex items-center justify-between">
        <DownloadButton data={data} label="Download Comparison (PDF)" />
        <span className="text-[9px] text-gray-400">
          {properties[0]?.data_sources?.length || 0} data sources
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Thesis card
// ---------------------------------------------------------------------------

function ThesisCard({
  summary,
  properties,
  data,
}: {
  summary: PortfolioSummary;
  properties: PropertyProspectus[];
  data: InvestmentProspectusResponse;
}) {
  const exampleCount = (summary.example_property_indices ?? []).length;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-purple-50 to-violet-50 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen size={14} className="text-purple-600" />
          <h4 className="text-sm font-semibold text-gray-900">Investment Thesis</h4>
          <ModeBadge mode="thesis" />
        </div>
        <span className="text-xs text-gray-500">{summary.property_count} Properties</span>
      </div>

      {/* Thesis narrative */}
      {summary.investment_thesis && (
        <div className="px-4 py-2.5 bg-purple-50/50 border-b border-gray-100">
          <p className="text-[11px] text-gray-700 line-clamp-3 leading-relaxed">
            {summary.investment_thesis}
          </p>
        </div>
      )}

      {/* Portfolio stats */}
      <div className="px-4 py-3 border-b border-gray-100">
        <div className="grid grid-cols-4 gap-3 text-center">
          <Metric label="Properties" value={String(summary.property_count)} />
          <Metric label="Total Capital" value={formatCurrency(summary.total_capital_required)} />
          <Metric
            label="Monthly CF"
            value={formatCurrency(summary.total_monthly_cash_flow)}
            color={summary.total_monthly_cash_flow >= 0 ? 'green' : 'red'}
          />
          <Metric label="Avg CoC" value={formatPct(summary.weighted_avg_coc)} />
        </div>
      </div>

      {/* Group stats */}
      {summary.group_statistics && (
        <div className="px-4 py-2 border-b border-gray-100">
          <div className="grid grid-cols-3 gap-2 text-center">
            <MiniStat label="Avg Price" value={formatCurrency(summary.group_statistics.avg_price)} />
            <MiniStat label="Median Price" value={formatCurrency(summary.group_statistics.median_price)} />
            <MiniStat label="Avg Cap Rate" value={formatPct(summary.group_statistics.avg_cap_rate)} />
          </div>
        </div>
      )}

      {/* Example count note */}
      {exampleCount > 0 && (
        <div className="px-4 py-2 border-b border-gray-100">
          <p className="text-[10px] text-gray-500">
            {exampleCount} representative properties analyzed in detail
          </p>
        </div>
      )}

      {/* Download + footer */}
      <div className="px-4 py-2.5 flex items-center justify-between">
        <DownloadButton data={data} label="Download Thesis (PDF)" />
        <span className="text-[9px] text-gray-400">
          {properties[0]?.data_sources?.length || 0} data sources
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function Metric({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: 'green' | 'red';
}) {
  return (
    <div>
      <p className="text-[10px] text-gray-400 uppercase tracking-wide">{label}</p>
      <p
        className={`text-sm font-bold ${
          color === 'green'
            ? 'text-green-600'
            : color === 'red'
              ? 'text-red-600'
              : 'text-gray-900'
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[9px] text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-xs font-semibold text-gray-700">{value}</p>
    </div>
  );
}

function ModeBadge({ mode }: { mode: 'curated' | 'similar' | 'thesis' }) {
  const config = {
    curated: { label: 'Portfolio', bg: 'bg-amber-100', text: 'text-amber-700', border: 'border-amber-200' },
    similar: { label: 'Comparison', bg: 'bg-blue-100', text: 'text-blue-700', border: 'border-blue-200' },
    thesis: { label: 'Thesis', bg: 'bg-purple-100', text: 'text-purple-700', border: 'border-purple-200' },
  };
  const c = config[mode];

  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-medium ${c.bg} ${c.text} border ${c.border}`}>
      {c.label}
    </span>
  );
}

function DownloadButton({ data, label }: { data: InvestmentProspectusResponse; label?: string }) {
  const [loading, setLoading] = useState(false);

  async function handleDownload() {
    setLoading(true);
    try {
      const { generateProspectusPdf } = await import('../../lib/prospectus-pdf');
      await generateProspectusPdf(data);
    } catch (err) {
      console.error('PDF generation failed:', err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <button
      onClick={handleDownload}
      disabled={loading}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md
                 bg-amber-50 text-amber-700 border border-amber-200
                 hover:bg-amber-100 hover:border-amber-300
                 disabled:opacity-60 disabled:cursor-not-allowed
                 transition-colors"
    >
      {loading ? (
        <Loader2 size={12} className="animate-spin" />
      ) : (
        <Download size={12} />
      )}
      {loading ? 'Generating...' : label || 'Download Prospectus (PDF)'}
    </button>
  );
}
