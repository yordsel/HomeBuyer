import { useState, useEffect } from 'react';
import {
  Loader2,
  BarChart3,
  AlertTriangle,
  RefreshCw,
  Trophy,
  TrendingUp,
  Building,
  Home,
  Scissors,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import * as api from '../lib/api';
import { formatCurrency, formatCompact, formatNumber } from '../lib/utils';
import type {
  RentalAnalysisResponse,
  InvestmentScenario,
  AnnualCashFlow,
} from '../types';

interface InvestmentScenarioCardProps {
  latitude: number;
  longitude: number;
  address?: string;
  neighborhood?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  lot_size_sqft?: number;
  year_built?: number;
  list_price?: number;
  /** Pre-fetched rental analysis data. When provided, the card skips its own fetch. */
  rentalData?: RentalAnalysisResponse;
}

const SCENARIO_ICONS: Record<string, React.ReactNode> = {
  as_is: <Home size={14} />,
  adu: <Building size={14} />,
  sb9: <Scissors size={14} />,
  multi_unit: <BarChart3 size={14} />,
};

export function InvestmentScenarioCard(props: InvestmentScenarioCardProps) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<RentalAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState(0);
  const [showProjections, setShowProjections] = useState(false);

  // Use parent-provided data when available; fall back to internal fetch.
  const effectiveData = props.rentalData ?? data;

  useEffect(() => {
    // Skip fetch when the parent already provides the data.
    if (props.rentalData) return;
    fetchAnalysis();
  }, [props.latitude, props.longitude, props.rentalData, props.address, props.neighborhood, props.beds, props.baths, props.sqft, props.lot_size_sqft, props.year_built, props.list_price]);

  async function fetchAnalysis() {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getRentalAnalysis({
        latitude: props.latitude,
        longitude: props.longitude,
        address: props.address,
        neighborhood: props.neighborhood,
        beds: props.beds,
        baths: props.baths,
        sqft: props.sqft,
        lot_size_sqft: props.lot_size_sqft,
        year_built: props.year_built,
        list_price: props.list_price,
      });
      setData(resp);
      setActiveTab(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const scenarios = effectiveData?.scenarios ?? [];
  const activeScenario = scenarios[activeTab] ?? null;
  const bestName = effectiveData?.best_scenario;

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 size={18} className="text-indigo-600" />
          <h3 className="font-semibold text-gray-900">Investment Scenarios</h3>
          {scenarios.length > 1 && (
            <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full">
              {scenarios.length} scenarios
            </span>
          )}
        </div>
        {effectiveData && (
          <button
            onClick={fetchAnalysis}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600"
          >
            <RefreshCw size={12} />
            Refresh
          </button>
        )}
      </div>

      {/* Body */}
      <div>
        {loading && (
          <div className="flex items-center justify-center py-8 px-6">
            <Loader2 size={20} className="animate-spin text-indigo-500 mr-2" />
            <span className="text-sm text-gray-500">Analyzing investment scenarios...</span>
          </div>
        )}

        {!loading && error && (
          <div className="flex flex-col items-center py-6 px-6 text-center">
            <AlertTriangle size={24} className="text-amber-400 mb-2" />
            <p className="text-sm text-gray-600 mb-3">{error}</p>
            <button
              onClick={fetchAnalysis}
              className="flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:text-blue-800"
            >
              <RefreshCw size={12} />
              Retry
            </button>
          </div>
        )}

        {!loading && effectiveData && scenarios.length > 0 && (
          <>
            {/* Scenario Comparison Bar */}
            {scenarios.length > 1 && (
              <div className="px-6 py-3 bg-gradient-to-r from-indigo-50 to-purple-50 border-b border-gray-100">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                  Compare Scenarios
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {scenarios.map((s, i) => (
                    <ComparisonPill
                      key={s.scenario_type}
                      scenario={s}
                      isBest={s.scenario_name === bestName}
                      isActive={i === activeTab}
                      onClick={() => setActiveTab(i)}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Scenario Tabs */}
            {scenarios.length > 1 && (
              <div className="flex border-b border-gray-200">
                {scenarios.map((s, i) => (
                  <button
                    key={s.scenario_type}
                    onClick={() => setActiveTab(i)}
                    className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 text-sm font-medium transition-colors
                      ${
                        i === activeTab
                          ? 'text-indigo-700 border-b-2 border-indigo-600 bg-indigo-50/50'
                          : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                      }`}
                  >
                    {SCENARIO_ICONS[s.scenario_type]}
                    <span className="truncate">{s.scenario_name}</span>
                    {s.scenario_name === bestName && (
                      <Trophy size={12} className="text-amber-500 shrink-0" />
                    )}
                  </button>
                ))}
              </div>
            )}

            {/* Active Scenario Detail */}
            {activeScenario && (
              <div className="px-6 py-4 space-y-4">
                {/* Best scenario badge */}
                {activeScenario.scenario_name === bestName && scenarios.length > 1 && (
                  <div className="flex items-center gap-1.5 text-xs font-medium text-amber-700 bg-amber-50 rounded-lg px-3 py-1.5">
                    <Trophy size={14} />
                    Best scenario by cash-on-cash return
                  </div>
                )}

                {/* Development notes */}
                {activeScenario.development_notes && (
                  <div className="text-xs text-gray-500 bg-gray-50 rounded-lg px-3 py-2">
                    {activeScenario.development_notes}
                  </div>
                )}

                {/* Investment Summary */}
                <div className="grid grid-cols-3 gap-3">
                  <StatBox
                    label="Total Investment"
                    value={formatCompact(activeScenario.total_investment)}
                    sub={
                      activeScenario.additional_investment > 0
                        ? `+${formatCompact(activeScenario.additional_investment)} development`
                        : 'Property value'
                    }
                  />
                  <StatBox
                    label="Monthly Rent"
                    value={formatCurrency(activeScenario.total_monthly_rent)}
                    sub={`${activeScenario.units.length} unit${activeScenario.units.length > 1 ? 's' : ''}`}
                  />
                  <StatBox
                    label="Monthly Cash Flow"
                    value={formatCurrency(activeScenario.monthly_cash_flow)}
                    sub={activeScenario.monthly_cash_flow >= 0 ? 'Positive' : 'Negative'}
                    valueColor={activeScenario.monthly_cash_flow >= 0 ? 'text-green-700' : 'text-red-600'}
                  />
                </div>

                {/* Key Metrics */}
                <div className="flex flex-wrap gap-2">
                  <Pill label="Cap Rate" value={`${activeScenario.cap_rate_pct}%`} />
                  <Pill label="Cash-on-Cash" value={`${activeScenario.cash_on_cash_pct}%`} />
                  <Pill label="GRM" value={`${activeScenario.gross_rent_multiplier}x`} />
                  <Pill
                    label="Tax Savings"
                    value={formatCurrency(activeScenario.tax_benefits.estimated_tax_savings)}
                  />
                </div>

                {/* Units breakdown */}
                {activeScenario.units.length > 1 && (
                  <div className="bg-gray-50 rounded-lg p-3">
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                      Rent by Unit
                    </p>
                    <div className="space-y-1">
                      {activeScenario.units.map((u, i) => (
                        <div key={i} className="flex justify-between text-sm">
                          <span className="text-gray-600">
                            {formatUnitType(u.unit_type)} — {u.beds}bd/{u.baths}ba
                            {u.sqft ? `, ${formatNumber(u.sqft)}sf` : ''}
                          </span>
                          <span className="font-medium text-gray-900">
                            {formatCurrency(u.monthly_rent)}/mo
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Cash Flow Projections (collapsible) */}
                {activeScenario.projections.length > 0 && (
                  <div className="border border-gray-200 rounded-lg overflow-hidden">
                    <button
                      onClick={() => setShowProjections(!showProjections)}
                      className="w-full flex items-center justify-between px-3 py-2.5 bg-gray-50 hover:bg-gray-100 transition-colors"
                    >
                      <div className="flex items-center gap-1.5">
                        <TrendingUp size={14} className="text-indigo-600" />
                        <span className="text-sm font-medium text-gray-700">
                          Cash Flow Projections
                        </span>
                      </div>
                      {showProjections ? (
                        <ChevronUp size={16} className="text-gray-400" />
                      ) : (
                        <ChevronDown size={16} className="text-gray-400" />
                      )}
                    </button>
                    {showProjections && (
                      <div className="border-t border-gray-200 overflow-x-auto">
                        <ProjectionTable projections={activeScenario.projections} />
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Recommendation */}
            {effectiveData.recommendation_notes && (
              <div className="px-6 py-3 bg-indigo-50 border-t border-indigo-100">
                <p className="text-sm text-indigo-800">{effectiveData.recommendation_notes}</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ComparisonPill({
  scenario,
  isBest,
  isActive,
  onClick,
}: {
  scenario: InvestmentScenario;
  isBest: boolean;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg p-2 text-center transition-all border
        ${
          isActive
            ? 'border-indigo-300 bg-white shadow-sm'
            : 'border-transparent hover:bg-white/60'
        }
        ${isBest ? 'ring-1 ring-amber-300' : ''}`}
    >
      <p className="text-xs text-gray-500 truncate">{scenario.scenario_name}</p>
      <p className={`text-sm font-bold ${scenario.cash_on_cash_pct >= 0 ? 'text-green-700' : 'text-red-600'}`}>
        {scenario.cash_on_cash_pct}%
      </p>
      <p className="text-xs text-gray-400">CoC</p>
    </button>
  );
}

function StatBox({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
}) {
  return (
    <div className="bg-gray-50 rounded-lg p-3 text-center">
      <p className={`text-lg font-bold ${valueColor ?? 'text-gray-900'}`}>{value}</p>
      <p className="text-xs font-medium text-gray-500">{label}</p>
      {sub && <p className="text-xs text-gray-400">{sub}</p>}
    </div>
  );
}

function Pill({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 border border-gray-200">
      <span className="text-gray-500">{label}:</span>
      {value}
    </span>
  );
}

function ProjectionTable({ projections }: { projections: AnnualCashFlow[] }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="bg-gray-50 text-gray-500 uppercase tracking-wide">
          <th className="px-3 py-2 text-left font-medium">Year</th>
          <th className="px-3 py-2 text-right font-medium">Gross Rent</th>
          <th className="px-3 py-2 text-right font-medium">NOI</th>
          <th className="px-3 py-2 text-right font-medium">Cash Flow</th>
          <th className="px-3 py-2 text-right font-medium">Property Value</th>
          <th className="px-3 py-2 text-right font-medium">Total Equity</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {projections.map((p) => (
          <tr key={p.year} className="hover:bg-gray-50">
            <td className="px-3 py-2 font-medium text-gray-700">Yr {p.year}</td>
            <td className="px-3 py-2 text-right text-gray-600">{formatCompact(p.gross_rent)}</td>
            <td className="px-3 py-2 text-right text-gray-600">{formatCompact(p.noi)}</td>
            <td className={`px-3 py-2 text-right font-medium ${p.cash_flow >= 0 ? 'text-green-700' : 'text-red-600'}`}>
              {formatCompact(p.cash_flow)}
            </td>
            <td className="px-3 py-2 text-right text-gray-600">{formatCompact(p.property_value)}</td>
            <td className="px-3 py-2 text-right font-medium text-indigo-700">
              {formatCompact(p.cumulative_equity)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function formatUnitType(type: string): string {
  const labels: Record<string, string> = {
    main_house: 'Main House',
    adu: 'ADU',
    sb9_unit_a: 'Unit A (existing)',
    sb9_unit_b: 'Unit B (new)',
  };
  return labels[type] ?? type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
