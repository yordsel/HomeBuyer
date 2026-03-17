/**
 * Full-page conversational chat interface — the primary UX for HomeBuyer.
 *
 * Features:
 * - SSE streaming for real-time text display
 * - Compact tool execution chips (not full inline cards)
 * - Address search bar for property lookup
 * - Context-aware suggestion chips
 * - Enhanced markdown rendering
 */
import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import {
  Send, Loader2, Bot, User, MessageCircle, Search,
  Home, BarChart3, GitCompare, MapPin, Building2,
  TrendingUp, DollarSign, Wrench, FileText, Database,
  Undo2, CheckCircle2, Plus,
} from 'lucide-react';
import { toast } from 'sonner';

import * as api from '../lib/api';
import { formatToolName } from '../lib/utils';
import { usePropertyContext } from '../context/PropertyContext';
import { useBuyerContext } from '../context/BuyerContext';
import type { PropertyContextData, TrackedProperty } from '../context/PropertyContext';
import { MarkdownLite } from '../components/chat/MarkdownLite';
import { BlockRenderer } from '../components/chat/BlockRenderer';
import { SuggestionChips } from '../components/chat/SuggestionChips';
import { SegmentBadge } from '../components/chat/SegmentBadge';
import { ResumeBriefingCard } from '../components/chat/ResumeBriefingCard';
import { BuyerIntakeForm } from '../components/chat/BuyerIntakeForm';
import { AddressSearch } from '../components/AddressSearch';
import { PropertyDetailModal } from '../components/context/PropertyDetailModal';
import type {
  ChatMessage,
  FaketorMessage,
  ToolEvent,
  ResponseBlock,
  BuyerIntakeData,
} from '../types';

// Icons for tool chips — gives each tool a recognizable visual
const TOOL_ICONS: Record<string, typeof Home> = {
  lookup_property: Home,
  get_price_prediction: BarChart3,
  get_comparable_sales: GitCompare,
  get_neighborhood_stats: MapPin,
  get_development_potential: Building2,
  get_market_summary: TrendingUp,
  estimate_rental_income: DollarSign,
  analyze_investment_scenarios: TrendingUp,
  estimate_sell_vs_hold: BarChart3,
  get_improvement_simulation: Wrench,
  search_properties: Search,
  lookup_permits: FileText,
  query_database: Database,
  undo_filter: Undo2,
  generate_investment_prospectus: FileText,
};

// ---------------------------------------------------------------------------
// ChatPage
// ---------------------------------------------------------------------------

interface ChatPageProps {
  conversationId?: number | null;
  onNewChat?: () => void;
}

export function ChatPage({ conversationId: initialConvId, onNewChat }: ChatPageProps = {}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [loadingConversation, setLoadingConversation] = useState(false);

  // Live streaming state — updated via SSE callbacks, rendered as a
  // partial assistant message at the bottom of the chat
  const [streamText, setStreamText] = useState('');
  const [streamToolEvents, setStreamToolEvents] = useState<ToolEvent[]>([]);
  const [activeToolLabel, setActiveToolLabel] = useState<string | null>(null);
  const [allToolsUsed, setAllToolsUsed] = useState<string[]>([]);

  const abortRef = useRef<AbortController | null>(null);
  // Deferred blocks: processBlocks must run AFTER onWorkingSet so that
  // setTrackedFromServer doesn't overwrite the property we just tracked.
  const deferredBlocksRef = useRef<ResponseBlock[] | null>(null);

  // Conversation persistence — use ref so callbacks always see latest value
  const convIdRef = useRef<number | null>(initialConvId ?? null);

  const {
    activeProperty,
    setActiveProperty,
    trackProperty,
    trackedProperties,
    addBlocksToProperty,
    clearTrackedProperties,
    setTrackedFromServer,
    setSendChatMessage,
    setWorkingSetMeta,
  } = usePropertyContext();

  const {
    segment,
    segmentConfidence,
    resumeBriefing,
    intakeCompleted,
    intakeData,
    updateSegment,
    setResumeBriefing,
    completeIntake,
    setPreExecuting,
    clearPreExecuting,
    dismissBriefing,
    resetBuyer,
  } = useBuyerContext();

  // Whether intake has been dismissed (skipped) for this conversation
  const [intakeSkipped, setIntakeSkipped] = useState(false);

  // Stable session ID for this conversation
  const [sessionId] = useState(() => crypto.randomUUID());

  // Property detail modal state
  const [detailAddress, setDetailAddress] = useState<string | null>(null);
  const detailTracked: TrackedProperty | null = useMemo(() => {
    if (!detailAddress) return null;
    const lower = detailAddress.toLowerCase();
    const tracked = trackedProperties.find(
      (t) => t.property.address.toLowerCase() === lower,
    );
    if (tracked) return tracked;
    for (const msg of messages) {
      if (!msg.blocks) continue;
      const propBlock = msg.blocks.find(
        (b) =>
          b.type === 'property_detail' &&
          b.data.address &&
          b.data.address.toLowerCase() === lower,
      );
      if (propBlock && propBlock.type === 'property_detail') {
        const pd = propBlock.data;
        const addr = pd.address;
        if (!addr) continue;
        return {
          property: {
            latitude: pd.latitude ?? 0,
            longitude: pd.longitude ?? 0,
            address: addr,
            neighborhood: pd.neighborhood,
            zip_code: pd.zip_code,
            beds: pd.beds,
            baths: pd.baths,
            sqft: pd.sqft,
            lot_size_sqft: pd.lot_size_sqft,
            year_built: pd.year_built,
            property_type: pd.property_type,
            zoning_class: pd.zoning_class,
            last_sale_price: pd.last_sale_price,
            last_sale_date: pd.last_sale_date,
            property_category: pd.property_category,
            record_type: pd.record_type,
          },
          blocks: msg.blocks,
          addedAt: Date.now(),
          updatedAt: Date.now(),
        };
      }
    }
    return null;
  }, [detailAddress, trackedProperties, messages]);

  const knownAddresses = useMemo(
    () => trackedProperties.map((t) => t.property.address),
    [trackedProperties],
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom on new messages or streaming updates
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streaming, streamText, streamToolEvents]);

  // Clear stale context on mount
  useEffect(() => {
    clearTrackedProperties();
    setActiveProperty(null);
    setWorkingSetMeta(null);
    resetBuyer();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Cleanup abort on unmount
  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  // ---- Load existing conversation or wait for first message to create one ----
  useEffect(() => {
    if (initialConvId) {
      setLoadingConversation(true);
      api.getConversation(initialConvId)
        .then((conv) => {
          convIdRef.current = conv.id;
          if (conv.messages && conv.messages.length > 0) {
            setMessages(conv.messages);
          }
        })
        .catch((err) => {
          toast.error(`Failed to load conversation: ${err.message}`);
        })
        .finally(() => setLoadingConversation(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialConvId]);

  // ---- Process completed response blocks (track properties, etc.) ----
  const processBlocks = useCallback(
    (blocks: ResponseBlock[]) => {
      const propBlock = blocks.find((b) => b.type === 'property_detail');

      if (propBlock && propBlock.type === 'property_detail' && propBlock.data) {
        const pd = propBlock.data;
        if (pd.latitude && pd.longitude && pd.address) {
          const propData: PropertyContextData = {
            latitude: pd.latitude,
            longitude: pd.longitude,
            address: pd.address,
            neighborhood: pd.neighborhood,
            zip_code: pd.zip_code,
            beds: pd.beds,
            baths: pd.baths,
            sqft: pd.sqft,
            lot_size_sqft: pd.lot_size_sqft,
            year_built: pd.year_built,
            property_type: pd.property_type,
            zoning_class: pd.zoning_class,
            last_sale_price: pd.last_sale_price,
            last_sale_date: pd.last_sale_date,
            property_category: pd.property_category,
            record_type: pd.record_type,
          };
          setActiveProperty(propData);
          trackProperty(propData, blocks);
        }
      } else if (activeProperty) {
        const analysisBlocks = blocks.filter(
          (b) =>
            b.type !== 'property_detail' &&
            b.type !== 'property_search_results' &&
            b.type !== 'query_result',
        );
        if (analysisBlocks.length > 0) {
          addBlocksToProperty(activeProperty.address, analysisBlocks);
        }
      }
    },
    [activeProperty, setActiveProperty, trackProperty, addBlocksToProperty],
  );

  // ---- Persist a user+assistant message pair to the backend ----
  const persistMessages = useCallback(
    async (userMsg: ChatMessage, assistantMsg: ChatMessage) => {
      try {
        let cid = convIdRef.current;

        // Create conversation on first message if needed
        if (!cid) {
          const title = userMsg.content.slice(0, 80);
          const conv = await api.createConversation(sessionId, title);
          cid = conv.id;
          convIdRef.current = cid;
        }

        // Serialize structured data to JSON strings for storage
        const toSave = [userMsg, assistantMsg].map((m) => ({
          role: m.role,
          content: m.content,
          blocks_json: m.blocks ? JSON.stringify(m.blocks) : null,
          tools_used_json: m.toolsUsed ? JSON.stringify(m.toolsUsed) : null,
          tool_events_json: m.toolEvents ? JSON.stringify(m.toolEvents) : null,
        }));

        await api.saveConversationMessages(cid, toSave);
      } catch (err) {
        // Non-critical — log but don't interrupt chat flow
        console.error('Failed to persist messages:', err);
      }
    },
    [sessionId],
  );

  // ---- Send message (streaming) ----
  const handleSend = useCallback(
    (text?: string) => {
      const msg = text || input.trim();
      if (!msg || streaming) return;

      setInput('');
      setStreaming(true);
      setStreamText('');
      setStreamToolEvents([]);
      setActiveToolLabel(null);

      const userMsg: ChatMessage = { role: 'user', content: msg };
      setMessages((prev) => [...prev, userMsg]);

      // Build history from previous messages
      const history: FaketorMessage[] = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      // Safely truncate float→int for fields the backend expects as integers.
      // Property detail data can arrive as floats from the DB or enrichment.
      const safeInt = (v: number | undefined) =>
        v != null && Number.isFinite(v) ? Math.round(v) : undefined;

      const controller = api.streamFaketorMessage(
        {
          latitude: activeProperty?.latitude,
          longitude: activeProperty?.longitude,
          message: msg,
          history,
          session_id: sessionId,
          address: activeProperty?.address,
          neighborhood: activeProperty?.neighborhood,
          zip_code: activeProperty?.zip_code,
          beds: activeProperty?.beds,
          baths: activeProperty?.baths,
          sqft: safeInt(activeProperty?.sqft),
          lot_size_sqft: safeInt(activeProperty?.lot_size_sqft),
          year_built: safeInt(activeProperty?.year_built),
          property_type: activeProperty?.property_type,
          property_category: activeProperty?.property_category,
          buyer_context: intakeData,
        },
        {
          onTextDelta: (text) => {
            setStreamText((prev) => prev + text);
            // Clear active tool label once text starts flowing again
            setActiveToolLabel(null);
          },
          onToolStart: (name, label) => {
            setActiveToolLabel(label);
            setStreamToolEvents((prev) => [
              ...prev,
              { name, label, done: false },
            ]);
          },
          onToolResult: (name, block) => {
            setActiveToolLabel(null);
            setStreamToolEvents((prev) =>
              prev.map((e) =>
                e.name === name && !e.done
                  ? { ...e, done: true, block: block ?? undefined }
                  : e,
              ),
            );
          },
          onDone: (reply, toolCalls, blocks) => {
            const toolNames = toolCalls.map((t) => t.name);
            // Collect final tool events with blocks from the done payload
            const finalToolEvents: ToolEvent[] = toolCalls.map((tc) => {
              const block = blocks.find(
                (b) => b.tool_name === tc.name,
              );
              return {
                name: tc.name,
                label: formatToolName(tc.name),
                done: true,
                block: block ?? undefined,
              };
            });

            const assistantMsg: ChatMessage = {
              role: 'assistant',
              content: reply,
              blocks,
              toolsUsed: toolNames,
              toolEvents: finalToolEvents.length > 0 ? finalToolEvents : undefined,
            };

            setMessages((prev) => [...prev, assistantMsg]);
            setAllToolsUsed((prev) => [...prev, ...toolNames]);
            setStreaming(false);
            setStreamText('');
            setStreamToolEvents([]);
            setActiveToolLabel(null);

            // Auto-save user + assistant messages
            persistMessages(userMsg, assistantMsg);

            // Defer block processing — onWorkingSet fires AFTER onDone
            // and setTrackedFromServer would overwrite what processBlocks sets.
            // Store blocks and process them after onWorkingSet arrives.
            if (blocks.length > 0) {
              deferredBlocksRef.current = blocks;
              // Fallback: if no working_set event arrives within 2s, process anyway
              setTimeout(() => {
                const pending = deferredBlocksRef.current;
                if (pending) {
                  deferredBlocksRef.current = null;
                  processBlocks(pending);
                }
              }, 2000);
            }
          },
          onWorkingSet: (meta) => {
            setWorkingSetMeta(meta);
            setTrackedFromServer(meta.sample ?? [], meta.discussed ?? []);

            // Now process deferred blocks so trackProperty runs AFTER
            // setTrackedFromServer has rebuilt the sidebar list.
            const pending = deferredBlocksRef.current;
            if (pending) {
              deferredBlocksRef.current = null;
              // Use setTimeout(0) so the setTrackedFromServer state update
              // is enqueued first, then processBlocks runs on top of it.
              setTimeout(() => processBlocks(pending), 0);
            }
          },
          onError: (message) => {
            toast.error(message);
            setStreaming(false);
            setStreamText('');
            setStreamToolEvents([]);
            setActiveToolLabel(null);
          },
          // Phase H: segment-driven redesign callbacks
          onSegmentUpdate: (data) => {
            updateSegment(data);
          },
          onResumeBriefing: (data) => {
            setResumeBriefing(data);
          },
          onPreExecutionStart: (tools) => {
            setPreExecuting(tools);
            setActiveToolLabel('Preparing analysis...');
          },
          onPreExecutionComplete: () => {
            clearPreExecuting();
          },
        },
      );

      abortRef.current = controller;
    },
    [input, streaming, messages, activeProperty, sessionId, processBlocks, setWorkingSetMeta, setTrackedFromServer, persistMessages, intakeData, updateSegment, setResumeBriefing, setPreExecuting, clearPreExecuting],
  );

  // ---- Handle address search selection ----
  const handleAddressSelect = useCallback(
    (lat: number, lng: number, address: string) => {
      const propData = { latitude: lat, longitude: lng, address };
      setActiveProperty(propData);
      trackProperty(propData);
      handleSend(`Tell me about ${address}`);
    },
    [setActiveProperty, trackProperty, handleSend],
  );

  // Handle buyer intake form submission
  const handleIntakeComplete = useCallback((data: BuyerIntakeData) => {
    completeIntake(data);
  }, [completeIntake]);

  const handleIntakeSkip = useCallback(() => {
    setIntakeSkipped(true);
  }, []);

  // Register handleSend in context
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
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold text-gray-900">Faketor</h1>
              {segment && segmentConfidence != null && (
                <SegmentBadge segment={segment} confidence={segmentConfidence} />
              )}
            </div>
            <p className="text-[11px] text-gray-500">
              {activeProperty
                ? `Analyzing: ${activeProperty.address}`
                : 'AI Real Estate Advisor \u2022 Ask about any Berkeley property'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {onNewChat && messages.length > 0 && (
            <button
              onClick={onNewChat}
              title="New conversation"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600
                         bg-gray-50 border border-gray-200 rounded-lg
                         hover:bg-gray-100 hover:text-gray-800 transition-colors"
            >
              <Plus size={14} />
              New Chat
            </button>
          )}
          <AddressSearch onSelect={handleAddressSelect} />
        </div>
      </div>

      {/* Messages area */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-4 space-y-4 bg-gray-50"
      >
        {/* Loading conversation */}
        {loadingConversation && (
          <div className="flex flex-col items-center justify-center min-h-[60%] text-center">
            <Loader2 size={32} className="animate-spin text-indigo-400 mb-3" />
            <p className="text-sm text-gray-500">Loading conversation...</p>
          </div>
        )}

        {/* Resume briefing card for returning users */}
        {resumeBriefing && (
          <ResumeBriefingCard
            briefing={resumeBriefing}
            onDismiss={dismissBriefing}
          />
        )}

        {/* Buyer intake form for new conversations (skippable) */}
        {messages.length === 0 && !streaming && !loadingConversation && !intakeCompleted && !intakeSkipped && (
          <BuyerIntakeForm
            onComplete={handleIntakeComplete}
            onSkip={handleIntakeSkip}
          />
        )}

        {/* Welcome state */}
        {messages.length === 0 && !streaming && !loadingConversation && (
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

        {/* Streaming assistant message — shows live text + tool chips */}
        {streaming && (
          <div className="flex items-start gap-2.5">
            <div className="flex items-center justify-center w-7 h-7 rounded-full bg-indigo-100 text-indigo-600 shrink-0 mt-0.5">
              <Bot size={14} />
            </div>
            <div className="max-w-[85%]">
              {/* Tool execution chips */}
              {streamToolEvents.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {streamToolEvents.map((evt, i) => (
                    <ToolChip key={`${evt.name}-${i}`} event={evt} />
                  ))}
                </div>
              )}

              {/* Streamed text or thinking indicator */}
              <div className="bg-white rounded-xl rounded-tl-none px-4 py-2.5 shadow-sm border border-gray-100">
                {streamText ? (
                  <MarkdownLite
                    text={streamText}
                    knownAddresses={knownAddresses}
                    onAddressClick={setDetailAddress}
                  />
                ) : (
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <Loader2 size={14} className="animate-spin" />
                    <span>{activeToolLabel ?? 'Thinking...'}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="px-4 py-3 border-t border-gray-200 bg-white rounded-b-xl">
        {/* Suggestion chips */}
        {messages.length > 0 && !streaming && (
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
            disabled={streaming}
            className="flex-1 text-sm bg-transparent outline-none placeholder-gray-400 disabled:opacity-50"
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || streaming}
            className="flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-500 text-white
                       hover:bg-indigo-600 disabled:bg-gray-200 disabled:text-gray-400
                       disabled:cursor-not-allowed transition-colors shrink-0"
          >
            <Send size={14} />
          </button>
        </div>
      </div>

      {/* Property detail modal */}
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
  const [funFact, setFunFact] = useState<string | null>(null);

  useEffect(() => {
    api.getRandomFunFact()
      .then((f) => setFunFact(f.display_text))
      .catch(() => {/* non-critical — silently hide */});
  }, []);

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
      {funFact && (
        <div className="mb-6 max-w-lg w-full px-4 py-3 rounded-xl bg-amber-50 border border-amber-200 text-left">
          <p className="text-xs font-semibold text-amber-700 mb-1">Did you know?</p>
          <p className="text-sm text-amber-900">{funFact}</p>
        </div>
      )}
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

// ---------------------------------------------------------------------------
// ToolChip — compact pill showing tool execution status
// ---------------------------------------------------------------------------

function ToolChip({ event }: { event: ToolEvent }) {
  const Icon = TOOL_ICONS[event.name] ?? Wrench;
  const label = formatToolName(event.name);

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-medium
        transition-all duration-300
        ${event.done
          ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
          : 'bg-indigo-50 text-indigo-600 border border-indigo-200 animate-pulse'
        }`}
    >
      {event.done ? (
        <CheckCircle2 size={10} className="text-emerald-500" />
      ) : (
        <Loader2 size={10} className="animate-spin" />
      )}
      <Icon size={10} />
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Block types that render inline in the chat (not just in the sidebar)
// ---------------------------------------------------------------------------

/** Block types that should be rendered inline below the text bubble. */
const INLINE_BLOCK_TYPES = new Set([
  'investment_prospectus',  // has download button, doesn't fit sidebar
  'market_summary',         // standalone data, no per-property sidebar slot
  'neighborhood_stats',     // standalone data, no per-property sidebar slot
]);

function InlineBlocks({
  blocks,
  onAddressClick,
}: {
  blocks: ResponseBlock[];
  onAddressClick?: (address: string) => void;
}) {
  const inline = blocks.filter((b) => INLINE_BLOCK_TYPES.has(b.type));
  if (inline.length === 0) return null;

  return (
    <div className="mt-2 space-y-2">
      {inline.map((block, i) => (
        <BlockRenderer key={`${block.type}-${i}`} block={block} onAddressClick={onAddressClick} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ToolFooter — small text below the chat bubble showing which tools ran
// ---------------------------------------------------------------------------

function ToolFooter({ events }: { events: ToolEvent[] }) {
  if (events.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-1 ml-1">
      {events.map((evt, i) => {
        const Icon = TOOL_ICONS[evt.name] ?? Wrench;
        return (
          <span
            key={`${evt.name}-${i}`}
            className="inline-flex items-center gap-0.5 text-[10px] text-gray-400"
          >
            <Icon size={9} />
            {formatToolName(evt.name)}
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MessageBubble
// ---------------------------------------------------------------------------

function MessageBubble({
  message,
  onAddressClick,
  knownAddresses,
}: {
  message: ChatMessage;
  onAddressClick?: (address: string) => void;
  knownAddresses?: string[];
}) {
  const isUser = message.role === 'user';

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

        {/* Inline cards for block types that belong in chat (e.g. prospectus with download) */}
        {!isUser && message.blocks && message.blocks.length > 0 && (
          <InlineBlocks blocks={message.blocks} onAddressClick={onAddressClick} />
        )}

        {/* Tool calls shown as small text below the bubble */}
        {!isUser && message.toolEvents && message.toolEvents.length > 0 && (
          <ToolFooter events={message.toolEvents} />
        )}
      </div>
    </div>
  );
}
