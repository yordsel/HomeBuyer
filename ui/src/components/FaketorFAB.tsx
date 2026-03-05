import { useState } from 'react';
import { Bot, X } from 'lucide-react';
import { FaketorChat } from './FaketorChat';
import { usePropertyContext } from '../context/PropertyContext';

/**
 * Floating Action Button that opens a Faketor chat overlay.
 * Mounted globally in App.tsx — only visible when a property is selected.
 * Uses PropertyContext to know which property to chat about.
 */
export function FaketorFAB() {
  const [open, setOpen] = useState(false);
  const { lastProperty } = usePropertyContext();

  // Hide entirely until a property prediction is available
  if (!lastProperty) return null;

  return (
    <>
      {/* Chat window overlay */}
      {open && (
        <div
          className="fixed bottom-20 right-6 w-[380px] rounded-xl shadow-2xl border border-gray-200 bg-white overflow-hidden"
          style={{ height: '520px', zIndex: 10000 }}
        >
          <FaketorChat
            key={`${lastProperty.latitude}-${lastProperty.longitude}`}
            latitude={lastProperty.latitude}
            longitude={lastProperty.longitude}
            address={lastProperty.address}
            alwaysExpanded
          />
        </div>
      )}

      {/* FAB button */}
      <button
        onClick={() => setOpen(!open)}
        className={`fixed bottom-6 right-6 flex items-center justify-center w-14 h-14 rounded-full shadow-lg
                    transition-all duration-200 hover:scale-105 active:scale-95
                    ${open
                      ? 'bg-gray-700 hover:bg-gray-800 text-white'
                      : 'bg-gradient-to-br from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white'
                    }`}
        aria-label={open ? 'Close Faketor chat' : 'Open Faketor chat'}
        style={{ zIndex: 10000 }}
      >
        {open ? <X size={22} /> : <Bot size={22} />}
      </button>
    </>
  );
}
