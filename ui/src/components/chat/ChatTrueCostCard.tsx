import { DollarSign, Home, TrendingDown, TrendingUp, Minus } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import type { TrueCostBlockData } from '../../types';

export function ChatTrueCostCard({ data }: { data: TrueCostBlockData }) {
  const d = data;
  const items: { label: string; value: number | undefined; note?: string }[] = [
    { label: 'Principal & Interest', value: d.monthly_principal_and_interest },
    { label: 'Property Tax', value: d.monthly_property_tax },
    { label: 'Homeowners Insurance', value: d.monthly_hoi },
    { label: 'Earthquake Insurance', value: d.monthly_earthquake_insurance },
    { label: 'Maintenance Reserve', value: d.monthly_maintenance_reserve },
    ...(d.monthly_pmi ? [{ label: 'PMI', value: d.monthly_pmi, note: d.pmi_note ?? undefined }] : []),
    ...(d.monthly_hoa ? [{ label: 'HOA', value: d.monthly_hoa }] : []),
  ];

  const delta = d.monthly_delta_vs_rent;
  const dir = d.delta_direction;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-emerald-50 to-green-50 border-b border-gray-100 flex items-center gap-2">
        <Home size={14} className="text-emerald-600" />
        <h4 className="text-sm font-semibold text-gray-900">True Monthly Cost</h4>
        {d.total_monthly_cost != null && (
          <span className="ml-auto text-lg font-bold text-emerald-700">
            {formatCurrency(d.total_monthly_cost)}
          </span>
        )}
      </div>

      {/* Line-item breakdown */}
      <div className="px-4 py-3 space-y-1.5">
        {items.map((item) =>
          item.value != null ? (
            <div key={item.label} className="flex items-center justify-between text-xs">
              <span className="text-gray-600">{item.label}</span>
              <span className="font-medium text-gray-900">{formatCurrency(item.value)}</span>
            </div>
          ) : null,
        )}
      </div>

      {/* Rent comparison footer */}
      {delta != null && d.current_rent != null && (
        <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100 flex items-center justify-between text-xs">
          <span className="text-gray-500">
            <DollarSign size={10} className="inline" /> vs current rent ({formatCurrency(d.current_rent)})
          </span>
          <span
            className={`font-medium flex items-center gap-0.5 ${
              dir === 'less_than_rent'
                ? 'text-green-600'
                : dir === 'more_than_rent'
                  ? 'text-red-600'
                  : 'text-gray-500'
            }`}
          >
            {dir === 'more_than_rent' && <TrendingUp size={10} />}
            {dir === 'less_than_rent' && <TrendingDown size={10} />}
            {dir === 'equal' && <Minus size={10} />}
            {delta >= 0 ? '+' : ''}
            {formatCurrency(delta)}/mo
          </span>
        </div>
      )}
    </div>
  );
}
