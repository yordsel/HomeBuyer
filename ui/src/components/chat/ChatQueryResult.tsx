/**
 * Generic SQL query result table for inline chat display.
 * Renders the query_result block from the query_database tool.
 * Dynamic columns, auto-formats currency values, caps at 50 rows.
 */
import { useState } from 'react';
import { Database, ChevronDown, ChevronUp, AlertCircle } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import type { QueryResultData } from '../../types';

const MAX_DISPLAY_ROWS = 50;

/** Columns whose values should be formatted as currency. */
const CURRENCY_PATTERNS = /price|cost|value|sale|income|rent|revenue/i;

export function ChatQueryResult({ data }: { data: Record<string, unknown> }) {
  const d = data as unknown as QueryResultData;
  const [showQuery, setShowQuery] = useState(false);

  // Error state
  if (d.error) {
    return (
      <div className="bg-white rounded-lg border border-red-200 p-4 my-2">
        <div className="flex items-center gap-2 text-red-600 text-xs font-medium mb-1">
          <AlertCircle size={14} />
          Query Error
        </div>
        <p className="text-xs text-red-500">{d.error}</p>
      </div>
    );
  }

  const columns = d.columns ?? [];
  const rows = d.rows ?? [];
  const displayRows = rows.slice(0, MAX_DISPLAY_ROWS);

  if (columns.length === 0 || rows.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4 my-2 text-center text-xs text-gray-500">
        <Database size={16} className="mx-auto mb-1 text-gray-300" />
        Query returned no results.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold text-gray-700 flex items-center gap-1.5">
            <Database size={12} className="text-gray-400" />
            Query Results
          </h4>
          <span className="text-[10px] text-gray-500">
            {d.row_count} row{d.row_count !== 1 ? 's' : ''}
          </span>
        </div>
        {d.explanation && (
          <p className="text-[11px] text-gray-500 mt-1 italic">{d.explanation}</p>
        )}
        {/* Collapsible SQL query */}
        {d.query && (
          <button
            onClick={() => setShowQuery((s) => !s)}
            className="flex items-center gap-1 mt-1.5 text-[10px] text-gray-400 hover:text-gray-600 transition-colors"
          >
            {showQuery ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            {showQuery ? 'Hide query' : 'Show query'}
          </button>
        )}
        {showQuery && d.query && (
          <pre className="mt-1.5 p-2 rounded bg-gray-100 text-[10px] text-gray-600 overflow-x-auto whitespace-pre-wrap font-mono">
            {d.query}
          </pre>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
              {columns.map((col) => (
                <th
                  key={col}
                  className={`px-3 py-2 whitespace-nowrap ${
                    isNumericColumn(col, rows) ? 'text-right' : ''
                  }`}
                >
                  {formatColumnName(col)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {displayRows.map((row, i) => (
              <tr key={i} className="hover:bg-gray-50">
                {columns.map((col) => (
                  <td
                    key={col}
                    className={`px-3 py-2 ${
                      isNumericColumn(col, rows)
                        ? 'text-right tabular-nums'
                        : ''
                    } ${
                      CURRENCY_PATTERNS.test(col) && typeof row[col] === 'number'
                        ? 'font-medium text-gray-900'
                        : 'text-gray-600'
                    }`}
                  >
                    {formatCell(col, row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      {rows.length > MAX_DISPLAY_ROWS && (
        <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 text-center">
          <p className="text-[10px] text-gray-500">
            Showing {MAX_DISPLAY_ROWS} of {rows.length} rows
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatColumnName(col: string): string {
  return col.replace(/_/g, ' ');
}

function isNumericColumn(
  col: string,
  rows: Record<string, unknown>[],
): boolean {
  // Check first non-null value in column
  for (const row of rows.slice(0, 5)) {
    const val = row[col];
    if (val != null) return typeof val === 'number';
  }
  return false;
}

function formatCell(col: string, value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'number') {
    if (CURRENCY_PATTERNS.test(col)) {
      return formatCurrency(value);
    }
    // Format large numbers with locale
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  const str = String(value);
  return str.length > 60 ? str.slice(0, 57) + '...' : str;
}
