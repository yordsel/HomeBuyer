/**
 * BuyerIntakeForm — optional inline buyer intake form.
 *
 * Seeds segment classification from turn 1. Skippable — the system works
 * without it (extraction-based flow). Designed to feel conversational,
 * not bureaucratic.
 *
 * Phase H-3 (#72) of Epic #23.
 */
import { useState, useCallback } from 'react';
import { User, ChevronRight, X } from 'lucide-react';
import type { BuyerIntakeData } from '../../types';

interface BuyerIntakeFormProps {
  onComplete: (data: BuyerIntakeData) => void;
  onSkip: () => void;
}

export function BuyerIntakeForm({ onComplete, onSkip }: BuyerIntakeFormProps) {
  const [intent, setIntent] = useState<'occupy' | 'invest' | undefined>();
  const [capital, setCapital] = useState<string>('');
  const [income, setIncome] = useState<string>('');
  const [currentRent, setCurrentRent] = useState<string>('');
  const [firstTime, setFirstTime] = useState<boolean | undefined>();

  const handleSubmit = useCallback(() => {
    const data: BuyerIntakeData = {};
    if (intent) data.intent = intent;
    if (capital) data.capital = parseFloat(capital.replace(/[^0-9.]/g, ''));
    if (income) data.income = parseFloat(income.replace(/[^0-9.]/g, ''));
    if (currentRent) data.current_rent = parseFloat(currentRent.replace(/[^0-9.]/g, ''));
    if (firstTime !== undefined) data.is_first_time_buyer = firstTime;
    onComplete(data);
  }, [intent, capital, income, currentRent, firstTime, onComplete]);

  const hasAnyData = intent || capital || income || currentRent || firstTime !== undefined;

  return (
    <div className="mx-auto max-w-lg mb-4 rounded-xl border border-blue-200 bg-gradient-to-br from-blue-50 to-white p-5 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-100 text-blue-600">
            <User size={16} />
          </div>
          <div>
            <h3 className="text-sm font-bold text-gray-900">Quick intro</h3>
            <p className="text-xs text-gray-500">Help me give you better advice (optional)</p>
          </div>
        </div>
        <button
          onClick={onSkip}
          className="p-1 rounded-full hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
          title="Skip"
        >
          <X size={16} />
        </button>
      </div>

      <div className="space-y-3">
        {/* Intent */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">
            What are you looking to do?
          </label>
          <div className="flex gap-2">
            <button
              onClick={() => setIntent('occupy')}
              className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium border transition-all ${
                intent === 'occupy'
                  ? 'bg-blue-500 text-white border-blue-500'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'
              }`}
            >
              Buy a home to live in
            </button>
            <button
              onClick={() => setIntent('invest')}
              className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium border transition-all ${
                intent === 'invest'
                  ? 'bg-emerald-500 text-white border-emerald-500'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-emerald-300'
              }`}
            >
              Invest in property
            </button>
          </div>
        </div>

        {/* Budget / Capital */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Available capital (down payment + reserves)
          </label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
            <input
              type="text"
              value={capital}
              onChange={(e) => setCapital(e.target.value)}
              placeholder="e.g. 300,000"
              className="w-full pl-7 pr-3 py-2 rounded-lg border border-gray-200 text-sm focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all"
            />
          </div>
        </div>

        {/* Income */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Annual household income
          </label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
            <input
              type="text"
              value={income}
              onChange={(e) => setIncome(e.target.value)}
              placeholder="e.g. 200,000"
              className="w-full pl-7 pr-3 py-2 rounded-lg border border-gray-200 text-sm focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all"
            />
          </div>
        </div>

        {/* Current rent */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Current monthly rent
          </label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
            <input
              type="text"
              value={currentRent}
              onChange={(e) => setCurrentRent(e.target.value)}
              placeholder="e.g. 3,500"
              className="w-full pl-7 pr-3 py-2 rounded-lg border border-gray-200 text-sm focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all"
            />
          </div>
        </div>

        {/* First-time buyer */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">
            First-time homebuyer?
          </label>
          <div className="flex gap-2">
            <button
              onClick={() => setFirstTime(true)}
              className={`flex-1 px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
                firstTime === true
                  ? 'bg-blue-500 text-white border-blue-500'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'
              }`}
            >
              Yes
            </button>
            <button
              onClick={() => setFirstTime(false)}
              className={`flex-1 px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
                firstTime === false
                  ? 'bg-blue-500 text-white border-blue-500'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'
              }`}
            >
              No
            </button>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between mt-4 pt-3 border-t border-gray-100">
        <button
          onClick={onSkip}
          className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
        >
          Skip for now
        </button>
        <button
          onClick={handleSubmit}
          disabled={!hasAnyData}
          className="flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-medium
                     bg-blue-500 text-white hover:bg-blue-600
                     disabled:bg-gray-200 disabled:text-gray-400
                     disabled:cursor-not-allowed transition-colors"
        >
          Let's go
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}
