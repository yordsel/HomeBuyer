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
import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Loader2, Bot, User, MessageCircle, Search } from 'lucide-react';
import { toast } from 'sonner';

import * as api from '../lib/tauri';
import { usePropertyContext } from '../context/PropertyContext';
import { MarkdownLite } from '../components/chat/MarkdownLite';
import { BlockRenderer } from '../components/chat/BlockRenderer';
import { SuggestionChips } from '../components/chat/SuggestionChips';
import { AddressSearch } from '../components/AddressSearch';
import type { ChatMessage, FaketorMessage } from '../types';

// ---------------------------------------------------------------------------
// ChatPage
// ---------------------------------------------------------------------------

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const [allToolsUsed, setAllToolsUsed] = useState<string[]>([]);

  const { activeProperty, setActiveProperty } = usePropertyContext();

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, thinking]);

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
          address: activeProperty?.address,
          neighborhood: activeProperty?.neighborhood,
          zip_code: activeProperty?.zip_code,
          beds: activeProperty?.beds,
          baths: activeProperty?.baths,
          sqft: activeProperty?.sqft,
          lot_size_sqft: activeProperty?.lot_size_sqft,
          year_built: activeProperty?.year_built,
          property_type: activeProperty?.property_type,
        });

        if (resp.error) {
          toast.error(resp.error);
          setMessages(messages); // revert
        } else {
          const toolNames = resp.tool_calls?.map((t) => t.name) ?? [];
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: resp.reply,
            blocks: resp.blocks,
            toolsUsed: toolNames,
          };
          setMessages([...updatedMessages, assistantMsg]);
          setAllToolsUsed((prev) => [...prev, ...toolNames]);

          // Auto-set active property from lookup_property results
          if (resp.blocks) {
            const propBlock = resp.blocks.find((b) => b.type === 'property_detail');
            if (propBlock?.data) {
              const pd = propBlock.data as Record<string, unknown>;
              if (pd.latitude && pd.longitude && pd.address) {
                setActiveProperty({
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
                });
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
    [input, thinking, messages, activeProperty, setActiveProperty],
  );

  // ---- Handle address search selection ----
  const handleAddressSelect = useCallback(
    (lat: number, lng: number, address: string) => {
      setActiveProperty({
        latitude: lat,
        longitude: lng,
        address,
      });
      // Auto-send a lookup message
      handleSend(`Tell me about ${address}`);
    },
    [setActiveProperty, handleSend],
  );

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
          <MessageBubble key={i} message={msg} />
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

function MessageBubble({ message }: { message: ChatMessage }) {
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
            <MarkdownLite text={message.content} />
          )}
        </div>

        {/* Rich blocks (assistant only) */}
        {!isUser && message.blocks && message.blocks.length > 0 && (
          <div className="mt-2 space-y-2">
            {message.blocks.map((block, i) => (
              <BlockRenderer key={i} block={block} />
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
