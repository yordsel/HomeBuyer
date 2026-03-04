import { LayoutGrid, Table2, Map } from 'lucide-react';

export type ViewMode = 'cards' | 'table' | 'map';

interface ViewToggleProps {
  view: ViewMode;
  onChange: (view: ViewMode) => void;
  /** Set to false to hide the map option (default: true). */
  showMap?: boolean;
}

export function ViewToggle({ view, onChange, showMap = true }: ViewToggleProps) {
  const btnBase =
    'flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors';
  const active = 'bg-blue-50 text-blue-700';
  const inactive = 'bg-white text-gray-500 hover:bg-gray-50';
  const border = 'border-r border-gray-300';

  return (
    <div className="flex rounded-lg border border-gray-300 overflow-hidden">
      <button
        onClick={() => onChange('cards')}
        className={`${btnBase} ${view === 'cards' ? active : inactive} ${border}`}
        title="Card view"
      >
        <LayoutGrid size={14} />
        Cards
      </button>
      <button
        onClick={() => onChange('table')}
        className={`${btnBase} ${view === 'table' ? active : inactive} ${showMap ? border : ''}`}
        title="Table view"
      >
        <Table2 size={14} />
        Table
      </button>
      {showMap && (
        <button
          onClick={() => onChange('map')}
          className={`${btnBase} ${view === 'map' ? active : inactive}`}
          title="Map view"
        >
          <Map size={14} />
          Map
        </button>
      )}
    </div>
  );
}
