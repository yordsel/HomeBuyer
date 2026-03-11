/**
 * Compact development potential card for chat inline display.
 * Shows zoning, ADU eligibility, SB9 eligibility, and unit potential.
 */
import { Building2, CheckCircle2, XCircle, AlertCircle } from 'lucide-react';
import type { DevelopmentBlockData } from '../../types';

export function ChatDevelopmentCard({ data }: { data: DevelopmentBlockData }) {
  const d = data;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-amber-50 to-orange-50 border-b border-gray-100 flex items-center gap-2">
        <Building2 size={14} className="text-amber-600" />
        <h4 className="text-sm font-semibold text-gray-900">Development Potential</h4>
      </div>

      {/* Zoning info */}
      {d.zoning && (
        <div className="px-4 py-2.5 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <span className="inline-block px-2 py-0.5 text-xs font-bold bg-indigo-100 text-indigo-700 rounded">
              {d.zoning.zone_class}
            </span>
            {d.zoning.zone_desc && (
              <span className="text-xs text-gray-500">{d.zoning.zone_desc}</span>
            )}
          </div>
          {d.zone_rule && (
            <p className="text-[10px] text-gray-400 mt-1">
              Max coverage: {d.zone_rule.max_lot_coverage_pct}% {'\u2022'}{' '}
              Height: {d.zone_rule.max_height_ft}ft
              {d.zone_rule.is_hillside ? ' \u2022 Hillside overlay' : ''}
            </p>
          )}
        </div>
      )}

      {/* Eligibility badges */}
      <div className="px-4 py-3 space-y-2">
        {d.adu && (
          <EligibilityRow
            label="ADU"
            eligible={d.adu.eligible ?? false}
            detail={
              d.adu.eligible
                ? `Up to ${d.adu.max_adu_sqft?.toLocaleString() || '?'} sqft`
                : d.adu.notes || 'Not eligible'
            }
          />
        )}
        {d.sb9 && (
          <EligibilityRow
            label="SB 9 Lot Split"
            eligible={d.sb9.eligible ?? false}
            detail={
              d.sb9.eligible
                ? `Up to ${d.sb9.max_total_units} units`
                : d.sb9.notes || 'Not eligible'
            }
          />
        )}
        {d.units?.middle_housing_eligible != null && (
          <EligibilityRow
            label="Middle Housing"
            eligible={d.units.middle_housing_eligible}
            detail={
              d.units.middle_housing_eligible
                ? `Up to ${d.units.middle_housing_max_units || d.units.effective_max_units} units`
                : 'Not eligible'
            }
          />
        )}
        {d.units && (
          <div className="flex items-center gap-2 text-xs">
            <AlertCircle size={14} className="text-blue-500 shrink-0" />
            <span className="text-gray-600">
              Max units: <strong className="font-semibold">{d.units.effective_max_units}</strong>
              {d.units.base_max_units !== d.units.effective_max_units &&
                ` (base: ${d.units.base_max_units})`}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function EligibilityRow({
  label,
  eligible,
  detail,
}: {
  label: string;
  eligible: boolean;
  detail: string;
}) {
  return (
    <div className="flex items-center gap-2 text-xs">
      {eligible ? (
        <CheckCircle2 size={14} className="text-green-500 shrink-0" />
      ) : (
        <XCircle size={14} className="text-red-400 shrink-0" />
      )}
      <span className="font-medium text-gray-700">{label}:</span>
      <span className="text-gray-500">{detail}</span>
    </div>
  );
}
