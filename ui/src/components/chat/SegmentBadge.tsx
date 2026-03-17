/**
 * SegmentBadge — subtle segment indicator in the chat UI.
 *
 * Shows detected buyer segment and confidence level. Non-intrusive,
 * informational only. Updates in real-time on segment changes.
 *
 * Phase H-4 (#73) of Epic #23.
 */
import { UserCheck, TrendingUp } from 'lucide-react';

// Human-friendly segment names
const SEGMENT_LABELS: Record<string, string> = {
  not_viable: 'Exploring Options',
  stretcher: 'Budget Stretcher',
  first_time_buyer: 'First-Time Buyer',
  down_payment_constrained: 'Down Payment Focused',
  equity_trapped_upgrader: 'Move-Up Buyer',
  competitive_bidder: 'Competitive Bidder',
  cash_buyer: 'Cash Buyer',
  equity_leveraging_investor: 'Equity Investor',
  leveraged_investor: 'Leveraged Investor',
  value_add_investor: 'Value-Add Investor',
  appreciation_bettor: 'Appreciation Play',
};

// Color classes per intent
function getSegmentColor(segment: string): string {
  if (['cash_buyer', 'equity_leveraging_investor', 'leveraged_investor', 'value_add_investor', 'appreciation_bettor'].includes(segment)) {
    return 'bg-emerald-50 text-emerald-700 border-emerald-200';
  }
  if (segment === 'not_viable') {
    return 'bg-amber-50 text-amber-700 border-amber-200';
  }
  return 'bg-blue-50 text-blue-700 border-blue-200';
}

function getConfidenceLabel(confidence: number): string {
  if (confidence >= 0.8) return 'High';
  if (confidence >= 0.5) return 'Medium';
  return 'Low';
}

interface SegmentBadgeProps {
  segment: string;
  confidence: number;
}

export function SegmentBadge({ segment, confidence }: SegmentBadgeProps) {
  const label = SEGMENT_LABELS[segment] ?? segment.replace(/_/g, ' ');
  const colorClass = getSegmentColor(segment);
  const confLabel = getConfidenceLabel(confidence);
  const isInvestor = ['cash_buyer', 'equity_leveraging_investor', 'leveraged_investor', 'value_add_investor', 'appreciation_bettor'].includes(segment);
  const Icon = isInvestor ? TrendingUp : UserCheck;

  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all duration-300 ${colorClass}`}
      title={`Detected segment: ${label} (${Math.round(confidence * 100)}% confidence)`}
    >
      <Icon size={12} />
      <span>{label}</span>
      <span className="opacity-60">{confLabel}</span>
    </div>
  );
}
