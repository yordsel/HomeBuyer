/**
 * Full-page conversational chat interface — the primary UX for HomeBuyer.
 *
 * Features:
 * - Full-height chat layout with scrollable messages
 * - Rich inline cards rendered from structured response blocks
 * - Address search bar for property lookup
 * - Context-aware suggestion chips
 * - Enhanced markdown rendering
 */
import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Send, Loader2, Bot, User, MessageCircle, Search } from 'lucide-react';
import { toast } from 'sonner';

import * as api from '../lib/tauri';
import { usePropertyContext } from '../context/PropertyContext';
import type { PropertyContextData, TrackedProperty } from '../context/PropertyContext';
import { MarkdownLite } from '../components/chat/MarkdownLite';
import { BlockRenderer } from '../components/chat/BlockRenderer';
import { SuggestionChips } from '../components/chat/SuggestionChips';
import { AddressSearch } from '../components/AddressSearch';
import { PropertyDetailModal } from '../components/context/PropertyDetailModal';
import type {
  ChatMessage,
  FaketorMessage,
  PropertySearchResultsData,
  SearchResultProperty,
} from '../types';

// Block types to show inline in chat. Analysis blocks (prediction_card,
// comps_table, neighborhood_stats, etc.) are available in the sidebar and
// property detail modal, so we hide them from chat to reduce clutter.
const INLINE_BLOCK_TYPES = new Set([
  'property_detail',
  'property_search_results',
  'query_result',
  'investment_prospectus',
]);

// ---------------------------------------------------------------------------
// ChatPage
// ---------------------------------------------------------------------------

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const [allToolsUsed, setAllToolsUsed] = useState<string[]>([]);

  const {
    activeProperty,
    setActiveProperty,
    trackProperty,
    trackProperties,
    trackedProperties,
    addBlocksToProperty,
    clearTrackedProperties,
    setSendChatMessage,
    setWorkingSetMeta,
  } = usePropertyContext();

  // Stable session ID for this conversation — ties frontend to backend working set
  const [sessionId] = useState(() => crypto.randomUUID());

  // Property detail modal state — opened when clicking an address chip/card in chat
  const [detailAddress, setDetailAddress] = useState<string | null>(null);
  const detailTracked: TrackedProperty | null = useMemo(() => {
    if (!detailAddress) return null;
    const lower = detailAddress.toLowerCase();
    // First try: find in tracked properties (case-insensitive)
    const tracked = trackedProperties.find(
      (t) => t.property.address.toLowerCase() === lower,
    );
    if (tracked) return tracked;
    // Fallback: build a minimal TrackedProperty from chat message blocks
    // so the modal can still open for properties shown in chat but not yet
    // in the tracked list (e.g. from search results or comps table)
    for (const msg of messages) {
      if (!msg.blocks) continue;
      const propBlock = msg.blocks.find(
        (b) =>
          b.type === 'property_detail' &&
          (b.data as Record<string, unknown>)?.address &&
          String((b.data as Record<string, unknown>).address).toLowerCase() === lower,
      );
      if (propBlock) {
        const pd = propBlock.data as Record<string, unknown>;
        return {
          property: {
            latitude: (pd.latitude as number) ?? 0,
            longitude: (pd.longitude as number) ?? 0,
            address: String(pd.address),
            neighborhood: pd.neighborhood as string | undefined,
            zip_code: pd.zip_code as string | undefined,
            beds: pd.beds as number | undefined,
            baths: pd.baths as number | undefined,
            sqft: pd.sqft as number | undefined,
            lot_size_sqft: pd.lot_size_sqft as number | undefined,
            year_built: pd.year_built as number | undefined,
            property_type: pd.property_type as string | undefined,
            zoning_class: pd.zoning_class as string | undefined,
            last_sale_price: pd.last_sale_price as number | undefined,
            last_sale_date: pd.last_sale_date as string | undefined,
            property_category: pd.property_category as string | undefined,
            record_type: pd.record_type as string | undefined,
          },
          blocks: msg.blocks,
          addedAt: Date.now(),
          updatedAt: Date.now(),
        };
      }
    }
    return null;
  }, [detailAddress, trackedProperties, messages]);

  // Collect known addresses for inline chip rendering in chat text
  const knownAddresses = useMemo(
    () => trackedProperties.map((t) => t.property.address),
    [trackedProperties],
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, thinking]);

  // Clear stale context on mount — each ChatPage instance is a fresh conversation
  // (sessionId is unique per mount), so sidebar shouldn't show leftovers from prior sessions
  useEffect(() => {
    clearTrackedProperties();
    setActiveProperty(null);
    setWorkingSetMeta(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // ---- Send message ----
  const handleSend = useCallback(
    async (text?: string) => {
      const msg = text || input.trim();
      if (!msg || thinking) return;

      setInput('');
      setThinking(true);

      const userMsg: ChatMessage = { role: 'user', content: msg };
      const updatedMessages = [...messages, userMsg];
      setMessages(updatedMessages);

      // Build history from previous messages (without blocks, for API compatibility)
      const history: FaketorMessage[] = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      try {
        const resp = await api.sendFaketorMessage({
          latitude: activeProperty?.latitude ?? 37.8716,
          longitude: activeProperty?.longitude ?? -122.2727,
          message: msg,
          history,
          session_id: sessionId,
          address: activeProperty?.address,
          neighborhood: activeProperty?.neighborhood,
          zip_code: activeProperty?.zip_code,
          beds: activeProperty?.beds,
          baths: activeProperty?.baths,
          sqft: activeProperty?.sqft,
          lot_size_sqft: activeProperty?.lot_size_sqft,
          year_built: activeProperty?.year_built,
          property_type: activeProperty?.property_type,
          property_category: activeProperty?.property_category,
        });

        if (resp.error) {
          toast.error(resp.error);
          setMessages(messages); // revert
        } else {
          // Propagate backend working set metadata to context
          if (resp.working_set) {
            setWorkingSetMeta(resp.working_set);
          }

          const toolNames = resp.tool_calls?.map((t) => t.name) ?? [];
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: resp.reply,
            blocks: resp.blocks,
            toolsUsed: toolNames,
          };
          setMessages([...updatedMessages, assistantMsg]);
          setAllToolsUsed((prev) => [...prev, ...toolNames]);

          // Auto-set active property from lookup_property results and
          // track properties + analysis blocks in the context sidebar
          if (resp.blocks) {
            const propBlock = resp.blocks.find(
              (b) => b.type === 'property_detail',
            );
            const searchBlock = resp.blocks.find(
              (b) => b.type === 'property_search_results',
            );

            if (propBlock?.data) {
              // Single property lookup — set active and track with all blocks
              const pd = propBlock.data as Record<string, unknown>;
              if (pd.latitude && pd.longitude && pd.address) {
                const propData: PropertyContextData = {
                  latitude: pd.latitude as number,
                  longitude: pd.longitude as number,
                  address: pd.address as string,
                  neighborhood: pd.neighborhood as string | undefined,
                  zip_code: pd.zip_code as string | undefined,
                  beds: pd.beds as number | undefined,
                  baths: pd.baths as number | undefined,
                  sqft: pd.sqft as number | undefined,
                  lot_size_sqft: pd.lot_size_sqft as number | undefined,
                  year_built: pd.year_built as number | undefined,
                  property_type: pd.property_type as string | undefined,
                  zoning_class: pd.zoning_class as string | undefined,
                  last_sale_price: pd.last_sale_price as number | undefined,
                  last_sale_date: pd.last_sale_date as string | undefined,
                  property_category: pd.property_category as string | undefined,
                  record_type: pd.record_type as string | undefined,
                };
                setActiveProperty(propData);
                // Track in sidebar with all response blocks
                trackProperty(propData, resp.blocks);
              }
            } else if (searchBlock?.data) {
              // Search results — batch-track all returned properties
              const searchData =
                searchBlock.data as unknown as PropertySearchResultsData;
              const results = searchData.results ?? [];
              const propsToTrack: PropertyContextData[] = [];

              for (const r of results) {
                if (r.latitude && r.longitude && r.address) {
                  propsToTrack.push(
                    searchResultToContextData(r),
                  );
                }
              }

              if (propsToTrack.length > 0) {
                trackProperties(propsToTrack);
                // Don't change activeProperty — user asked a broad question
              }
            } else if (activeProperty) {
              // No new property block, but we have analysis blocks for the
              // currently active property — append them
              const analysisBlocks = resp.blocks.filter(
                (b) =>
                  b.type !== 'property_detail' &&
                  b.type !== 'property_search_results' &&
                  b.type !== 'query_result',
              );
              if (analysisBlocks.length > 0) {
                addBlocksToProperty(
                  activeProperty.address,
                  analysisBlocks,
                );
              }
            }
          }
        }
      } catch (err) {
        toast.error('Faketor is having trouble connecting. Try again.');
        console.error(err);
        setMessages(messages); // revert
      } finally {
        setThinking(false);
      }
    },
    [input, thinking, messages, activeProperty, setActiveProperty, trackProperty, trackProperties, addBlocksToProperty],
  );

  // ---- Handle address search selection ----
  const handleAddressSelect = useCallback(
    (lat: number, lng: number, address: string) => {
      const propData = { latitude: lat, longitude: lng, address };
      setActiveProperty(propData);
      trackProperty(propData);
      // Auto-send a lookup message
      handleSend(`Tell me about ${address}`);
    },
    [setActiveProperty, trackProperty, handleSend],
  );

  // Register handleSend in context so sidebar components can trigger messages
  useEffect(() => {
    setSendChatMessage(handleSend);
    return () => setSendChatMessage(null);
  }, [handleSend, setSendChatMessage]);

  // ---- Keyboard ----
  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-3rem)] max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white rounded-t-xl">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-9 h-9 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-sm">
            <Bot size={18} />
          </div>
          <div>
            <h1 className="text-base font-bold text-gray-900">Faketor</h1>
            <p className="text-[11px] text-gray-500">
              {activeProperty
                ? `Analyzing: ${activeProperty.address}`
                : 'AI Real Estate Advisor \u2022 Ask about any Berkeley property'}
            </p>
          </div>
        </div>
        <AddressSearch onSelect={handleAddressSelect} />
      </div>

      {/* Messages area */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-4 space-y-4 bg-gray-50"
      >
        {/* Welcome state */}
        {messages.length === 0 && !thinking && (
          <WelcomeScreen
            onSelect={handleSend}
            hasProperty={!!activeProperty}
          />
        )}

        {/* Message list */}
        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            message={msg}
            onAddressClick={setDetailAddress}
            knownAddresses={knownAddresses}
          />
        ))}

        {/* Thinking indicator */}
        {thinking && (
          <div className="flex items-start gap-2.5">
            <div className="flex items-center justify-center w-7 h-7 rounded-full bg-indigo-100 text-indigo-600 shrink-0 mt-0.5">
              <Bot size={14} />
            </div>
            <div className="bg-white rounded-xl rounded-tl-none px-4 py-3 shadow-sm border border-gray-100 max-w-[85%]">
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <Loader2 size={14} className="animate-spin" />
                <span>Analyzing property data...</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="px-4 py-3 border-t border-gray-200 bg-white rounded-b-xl">
        {/* Suggestion chips */}
        {messages.length > 0 && !thinking && (
          <SuggestionChips
            hasProperty={!!activeProperty}
            toolsUsed={allToolsUsed}
            onSelect={handleSend}
            propertyCategory={activeProperty?.property_category}
          />
        )}

        {/* Input bar */}
        <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus-within:border-indigo-300 focus-within:ring-2 focus-within:ring-indigo-100 transition-all">
          <MessageCircle size={16} className="text-gray-400 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              activeProperty
                ? `Ask about ${activeProperty.address}...`
                : 'Ask about any Berkeley property or the market...'
            }
            disabled={thinking}
            className="flex-1 text-sm bg-transparent outline-none placeholder-gray-400 disabled:opacity-50"
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || thinking}
            className="flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-500 text-white
                       hover:bg-indigo-600 disabled:bg-gray-200 disabled:text-gray-400
                       disabled:cursor-not-allowed transition-colors shrink-0"
          >
            <Send size={14} />
          </button>
        </div>
      </div>

      {/* Property detail modal — opens when clicking an address chip in chat blocks */}
      <PropertyDetailModal
        open={!!detailAddress}
        onClose={() => setDetailAddress(null)}
        tracked={detailTracked}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function WelcomeScreen({
  onSelect,
  hasProperty,
}: {
  onSelect: (prompt: string) => void;
  hasProperty: boolean;
}) {
  const prompts = hasProperty
    ? [
        'What\u2019s this property worth?',
        'What can I build on this lot?',
        'Show comparable sales',
        'Should I sell or hold?',
      ]
    : [
        'Tell me about 1234 Cedar St',
        'What\u2019s the Berkeley market like?',
        'Compare Elmwood vs Thousand Oaks',
        'What neighborhoods have the best value?',
      ];

  return (
    <div className="flex flex-col items-center justify-center min-h-[60%] text-center px-4">
      <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg mb-4">
        <Bot size={32} />
      </div>
      <h2 className="text-xl font-bold text-gray-900 mb-1">Welcome to Faketor</h2>
      <p className="text-sm text-gray-500 mb-6 max-w-md">
        Your AI real estate advisor for Berkeley. Ask about any property, neighborhood,
        or the market — I'll pull live data and give you data-driven insights.
      </p>
      <div className="grid grid-cols-2 gap-2 w-full max-w-lg">
        {prompts.map((prompt) => (
          <button
            key={prompt}
            onClick={() => onSelect(prompt)}
            className="text-left text-sm px-4 py-3 rounded-xl border border-gray-200 text-gray-600
                       hover:border-indigo-300 hover:text-indigo-700 hover:bg-indigo-50
                       hover:shadow-sm transition-all"
          >
            <Search size={14} className="inline mr-1.5 text-gray-400" />
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}

function MessageBubble({
  message,
  onAddressClick,
  knownAddresses,
}: {
  message: ChatMessage;
  onAddressClick?: (address: string) => void;
  /** Known property addresses for inline chip rendering in text. */
  knownAddresses?: string[];
}) {
  const isUser = message.role === 'user';

  // Only show "summary" blocks inline in chat — analysis blocks live in the
  // sidebar / modal and don't need to duplicate here.
  const inlineBlocks = message.blocks?.filter((b) =>
    INLINE_BLOCK_TYPES.has(b.type),
  );

  return (
    <div className={`flex items-start gap-2.5 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div
        className={`flex items-center justify-center w-7 h-7 rounded-full shrink-0 mt-0.5 ${
          isUser
            ? 'bg-blue-100 text-blue-600'
            : 'bg-indigo-100 text-indigo-600'
        }`}
      >
        {isUser ? <User size={14} /> : <Bot size={14} />}
      </div>

      {/* Content */}
      <div className={`max-w-[85%] ${isUser ? 'items-end' : 'items-start'}`}>
        {/* Text bubble */}
        <div
          className={`rounded-xl px-4 py-2.5 shadow-sm ${
            isUser
              ? 'bg-blue-500 text-white rounded-tr-none'
              : 'bg-white text-gray-800 rounded-tl-none border border-gray-100'
          }`}
        >
          {isUser ? (
            <p className="text-sm leading-relaxed">{message.content}</p>
          ) : (
            <MarkdownLite
              text={message.content}
              knownAddresses={knownAddresses}
              onAddressClick={onAddressClick}
            />
          )}
        </div>

        {/* Rich blocks (assistant only) — only summary / reference blocks */}
        {!isUser && inlineBlocks && inlineBlocks.length > 0 && (
          <div className="mt-2 space-y-2">
            {inlineBlocks.map((block, i) => (
              <BlockRenderer key={i} block={block} onAddressClick={onAddressClick} />
            ))}
          </div>
        )}

        {/* Tools used indicator */}
        {!isUser && message.toolsUsed && message.toolsUsed.length > 0 && (
          <p className="mt-1 text-[10px] text-gray-400">
            Used: {message.toolsUsed.map(formatToolName).join(', ')}
          </p>
        )}
      </div>
    </div>
  );
}

function formatToolName(name: string): string {
  return name
    .replace(/^(get_|estimate_|analyze_|lookup_)/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Convert a search result property to PropertyContextData for tracking. */
function searchResultToContextData(
  r: SearchResultProperty,
): PropertyContextData {
  return {
    latitude: r.latitude!,
    longitude: r.longitude!,
    address: r.address,
    neighborhood: r.neighborhood,
    zip_code: r.zip_code,
    beds: r.beds,
    baths: r.baths,
    sqft: r.sqft,
    lot_size_sqft: r.lot_size_sqft,
    year_built: r.year_built,
    property_type: r.property_type,
    zoning_class: r.zoning_class ?? r.development?.zone_class,
    last_sale_price: r.last_sale_price,
    last_sale_date: r.last_sale_date,
    predicted_price: r.predicted_price,
    prediction_confidence: r.prediction_confidence,
    property_category: r.property_category,
    record_type: r.record_type,
    development_summary: r.development
      ? {
          adu_eligible: r.development.adu_eligible,
          sb9_eligible: r.development.sb9_eligible,
          effective_max_units: r.development.effective_max_units,
          middle_housing_eligible: r.development.middle_housing_eligible,
        }
      : undefined,
  };
}
