/**
 * Clickable address chip for use in chat block cards.
 * When clicked, triggers the onAddressClick callback to open
 * the PropertyDetailModal for that address.
 */
import { Home } from 'lucide-react';

interface AddressChipProps {
  address: string;
  onClick: (address: string) => void;
  /** Max characters before truncation. */
  maxLength?: number;
}

export function AddressChip({ address, onClick, maxLength }: AddressChipProps) {
  const display = maxLength && address.length > maxLength
    ? address.slice(0, maxLength) + '…'
    : address;

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick(address);
      }}
      title={address}
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                 bg-indigo-50 text-indigo-700 hover:bg-indigo-100
                 hover:text-indigo-800 transition-colors cursor-pointer
                 text-xs font-medium leading-snug max-w-full"
    >
      <Home size={10} className="shrink-0" />
      <span className="truncate">{display}</span>
    </button>
  );
}
