import { useState } from 'react';
import {
  MessageCircle,
  Search,
  MapPin,
  TrendingUp,
  Brain,
  DollarSign,
  Layers,
  ChevronsLeft,
  ChevronsRight,
  LogOut,
  User,
  History,
  Settings,
} from 'lucide-react';
import type { PageId } from '../types';
import { useAuth } from '../context/AuthContext';

interface SidebarProps {
  currentPage: PageId;
  onNavigate: (page: PageId) => void;
}

const NAV_ITEMS: { id: PageId; label: string; icon: typeof Search }[] = [
  { id: 'chat', label: 'Chat', icon: MessageCircle },
  { id: 'history', label: 'History', icon: History },
  { id: 'predict', label: 'Predict', icon: Search },
  { id: 'neighborhoods', label: 'Neighborhoods', icon: MapPin },
  { id: 'market', label: 'Market', icon: TrendingUp },
  { id: 'model', label: 'Model', icon: Brain },
  { id: 'afford', label: 'Affordability', icon: DollarSign },
  { id: 'potential', label: 'Potential', icon: Layers },
];

export function Sidebar({ currentPage, onNavigate }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const { user, logout } = useAuth();

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

      {/* User menu */}
      <div className="px-3 py-3 border-t border-gray-200">
        {user && (
          <div className={`flex items-center ${collapsed ? 'justify-center' : 'gap-2 px-2'}`}>
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-700">
              <User size={14} />
            </div>
            {!collapsed && (
              <div className="flex-1 min-w-0">
                <p className="truncate text-xs font-medium text-gray-700">
                  {user.full_name || user.email}
                </p>
                {user.full_name && (
                  <p className="truncate text-[10px] text-gray-400">{user.email}</p>
                )}
              </div>
            )}
            <button
              onClick={() => onNavigate('settings')}
              title="Account settings"
              className="shrink-0 p-1 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
            >
              <Settings size={14} />
            </button>
            <button
              onClick={logout}
              title="Sign out"
              className="shrink-0 p-1 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
            >
              <LogOut size={14} />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
