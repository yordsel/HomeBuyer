import {
  useState,
  useEffect,
  useRef,
  useCallback,
  type KeyboardEvent,
} from 'react';
import { Search, X, Loader2 } from 'lucide-react';
import { useDebounce } from '../hooks/useDebounce';
import {
  searchAddresses,
  formatResultAddress,
  type NominatimResult,
} from '../lib/nominatim';

interface AddressSearchProps {
  onSelect: (lat: number, lng: number, address: string) => void;
  disabled?: boolean;
}

export function AddressSearch({ onSelect, disabled }: AddressSearchProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<NominatimResult[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [searching, setSearching] = useState(false);

  const debouncedQuery = useDebounce(query, 400);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // ---- Nominatim search on debounced query ----
  useEffect(() => {
    if (!debouncedQuery || debouncedQuery.trim().length < 3) {
      setResults([]);
      setIsOpen(false);
      return;
    }

    let cancelled = false;
    setSearching(true);

    searchAddresses(debouncedQuery).then((data) => {
      if (cancelled) return;
      setResults(data);
      setIsOpen(data.length > 0);
      setActiveIndex(-1);
      setSearching(false);
    });

    return () => {
      cancelled = true;
    };
  }, [debouncedQuery]);

  // ---- Close on outside click ----
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, []);

  // ---- Select a result ----
  const selectResult = useCallback(
    (result: NominatimResult) => {
      const lat = parseFloat(result.lat);
      const lng = parseFloat(result.lon);
      const address = formatResultAddress(result);

      setQuery('');
      setIsOpen(false);
      setResults([]);
      onSelect(lat, lng, address);
    },
    [onSelect],
  );

  // ---- Keyboard navigation ----
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (!isOpen || results.length === 0) {
        if (e.key === 'Escape') {
          setIsOpen(false);
        }
        return;
      }

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setActiveIndex((prev) =>
            prev < results.length - 1 ? prev + 1 : 0,
          );
          break;

        case 'ArrowUp':
          e.preventDefault();
          setActiveIndex((prev) =>
            prev > 0 ? prev - 1 : results.length - 1,
          );
          break;

        case 'Enter':
          e.preventDefault();
          if (activeIndex >= 0 && activeIndex < results.length) {
            selectResult(results[activeIndex]);
          }
          break;

        case 'Escape':
          e.preventDefault();
          setIsOpen(false);
          break;
      }
    },
    [isOpen, results, activeIndex, selectResult],
  );

  // ---- Clear ----
  const handleClear = useCallback(() => {
    setQuery('');
    setResults([]);
    setIsOpen(false);
    inputRef.current?.focus();
  }, []);

  return (
    <div ref={containerRef} className="relative w-72" role="combobox" aria-expanded={isOpen} aria-haspopup="listbox">
      {/* Input */}
      <div className="relative">
        <Search
          size={16}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
        />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (!e.target.value) {
              setResults([]);
              setIsOpen(false);
            }
          }}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (results.length > 0) setIsOpen(true);
          }}
          placeholder="Search Berkeley address..."
          disabled={disabled}
          className="w-full pl-8 pr-8 py-2 text-sm border border-gray-300 rounded-lg
                     bg-white shadow-sm
                     focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
                     disabled:opacity-50 disabled:cursor-not-allowed"
          aria-autocomplete="list"
          aria-controls="address-search-listbox"
          aria-activedescendant={
            activeIndex >= 0 ? `address-option-${activeIndex}` : undefined
          }
        />

        {/* Right icon: clear or spinner */}
        {query && (
          <button
            onClick={handleClear}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-gray-400 hover:text-gray-600"
            tabIndex={-1}
            aria-label="Clear search"
          >
            {searching ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <X size={14} />
            )}
          </button>
        )}
      </div>

      {/* Dropdown */}
      {isOpen && results.length > 0 && (
        <ul
          id="address-search-listbox"
          role="listbox"
          className="absolute left-0 right-0 mt-1 max-h-60 overflow-y-auto
                     bg-white border border-gray-200 rounded-lg shadow-lg z-[1000]"
        >
          {results.map((result, idx) => {
            const formatted = formatResultAddress(result);
            return (
              <li
                key={result.place_id}
                id={`address-option-${idx}`}
                role="option"
                aria-selected={idx === activeIndex}
                onClick={() => selectResult(result)}
                onMouseEnter={() => setActiveIndex(idx)}
                className={`px-3 py-2 cursor-pointer text-sm transition-colors ${
                  idx === activeIndex
                    ? 'bg-blue-50 text-blue-900'
                    : 'text-gray-700 hover:bg-gray-50'
                }`}
              >
                <p className="font-medium truncate">{formatted}</p>
                <p className="text-xs text-gray-400 truncate mt-0.5">
                  {result.display_name}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
