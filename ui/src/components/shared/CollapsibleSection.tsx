/**
 * Reusable collapsible section with title, subtitle, and chevron toggle.
 *
 * Previously duplicated in RentalIncomeCard.tsx and inlined in
 * InvestmentScenarioCard.tsx.
 */
import { ChevronDown, ChevronUp } from 'lucide-react';

interface CollapsibleSectionProps {
  title: string;
  subtitle: string;
  open: boolean;
  onToggle: () => void;
  /** Optional icon rendered before the title */
  icon?: React.ReactNode;
  children: React.ReactNode;
}

export function CollapsibleSection({
  title,
  subtitle,
  open,
  onToggle,
  icon,
  children,
}: CollapsibleSectionProps) {
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-3 py-2.5 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-1.5">
          {icon}
          <div className="text-left">
            <p className="text-sm font-medium text-gray-700">{title}</p>
            <p className="text-xs text-gray-500">{subtitle}</p>
          </div>
        </div>
        {open ? (
          <ChevronUp size={16} className="text-gray-400" />
        ) : (
          <ChevronDown size={16} className="text-gray-400" />
        )}
      </button>
      {open && <div className="px-3 py-3 border-t border-gray-200">{children}</div>}
    </div>
  );
}
