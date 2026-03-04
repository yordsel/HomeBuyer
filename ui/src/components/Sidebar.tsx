import { useState } from 'react';
import {
  Search,
  MapPin,
  TrendingUp,
  Brain,
  DollarSign,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react';
import type { PageId } from '../types';

interface SidebarProps {
  currentPage: PageId;
  onNavigate: (page: PageId) => void;
}

const NAV_ITEMS: { id: PageId; label: string; icon: typeof Search }[] = [
  { id: 'predict', label: 'Predict', icon: Search },
  { id: 'neighborhoods', label: 'Neighborhoods', icon: MapPin },
  { id: 'market', label: 'Market', icon: TrendingUp },
  { id: 'model', label: 'Model', icon: Brain },
  { id: 'afford', label: 'Affordability', icon: DollarSign },
];

export function Sidebar({ currentPage, onNavigate }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={`bg-white border-r border-gray-200 flex flex-col h-full transition-all duration-200 ${
        collapsed ? 'w-[60px]' : 'w-56'
      }`}
    >
      {/* Logo / Title */}
      <div className="px-3 py-5 border-b border-gray-200 flex items-center justify-between min-h-[72px]">
        {!collapsed && (
          <div className="px-2">
            <h1 className="text-lg font-bold text-gray-900">HomeBuyer</h1>
            <p className="text-xs text-gray-500 mt-0.5">Berkeley Price Predictor</p>
          </div>
        )}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors shrink-0"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-4 space-y-1">
        {NAV_ITEMS.map((item) => {
          const isActive = currentPage === item.id;
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              title={collapsed ? item.label : undefined}
              className={`w-full flex items-center gap-3 rounded-lg text-sm font-medium transition-colors ${
                collapsed ? 'justify-center px-0 py-2.5' : 'px-3 py-2.5'
              } ${
                isActive
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
              }`}
            >
              <Icon
                size={18}
                className={`shrink-0 ${isActive ? 'text-blue-600' : 'text-gray-400'}`}
              />
              {!collapsed && item.label}
            </button>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-3 py-4 border-t border-gray-200">
        {!collapsed && <p className="text-xs text-gray-400 px-2">v0.1.0</p>}
      </div>
    </aside>
  );
}
