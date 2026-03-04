interface StatCardProps {
  label: string;
  value: string;
  subtitle?: string;
  color?: 'default' | 'green' | 'red' | 'blue';
}

const COLOR_MAP = {
  default: 'text-gray-900',
  green: 'text-green-600',
  red: 'text-red-600',
  blue: 'text-blue-600',
};

export function StatCard({ label, value, subtitle, color = 'default' }: StatCardProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${COLOR_MAP[color]}`}>{value}</p>
      {subtitle && <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>}
    </div>
  );
}
