import { useState, useRef, useEffect } from 'react';
import { MessageCircle, Send, Loader2, Bot, User, ChevronDown, ChevronUp } from 'lucide-react';
import { toast } from 'sonner';
import * as api from '../lib/tauri';
import type { FaketorMessage } from '../types';

interface FaketorChatProps {
  latitude: number;
  longitude: number;
  address?: string;
  neighborhood?: string;
  zip_code?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  lot_size_sqft?: number;
  year_built?: number;
  property_type?: string;
  /** When true, chat is always expanded — no collapsed state or collapse button. */
  alwaysExpanded?: boolean;
  /** Override the default starter prompts. */
  starterPrompts?: string[];
  /** Callback fired after a response, with the list of backend tool names called. */
  onToolCalled?: (toolNames: string[]) => void;
}

const STARTER_PROMPTS = [
  'What improvements would add the most value?',
  'Should I sell or hold this property?',
  'What can I build on this lot?',
  'How does this neighborhood compare?',
];

export function FaketorChat(props: FaketorChatProps) {
  const [expanded, setExpanded] = useState(false);
  const [messages, setMessages] = useState<FaketorMessage[]>([]);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const [toolsUsed, setToolsUsed] = useState<string[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const isExpanded = props.alwaysExpanded || expanded;
  const activePrompts = props.starterPrompts ?? STARTER_PROMPTS;

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, thinking]);

  // Focus input when expanded
  useEffect(() => {
    if (isExpanded && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isExpanded]);

  async function handleSend(text?: string) {
    const msg = text || input.trim();
    if (!msg || thinking) return;

    setInput('');
    setThinking(true);
    setToolsUsed([]);

    const userMsg: FaketorMessage = { role: 'user', content: msg };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);

    try {
      const resp = await api.sendFaketorMessage({
        latitude: props.latitude,
        longitude: props.longitude,
        message: msg,
        history: messages, // previous messages (not including this new one)
        address: props.address,
        neighborhood: props.neighborhood,
        zip_code: props.zip_code,
        beds: props.beds,
        baths: props.baths,
        sqft: props.sqft,
        lot_size_sqft: props.lot_size_sqft,
        year_built: props.year_built,
        property_type: props.property_type,
      });

      if (resp.error) {
        toast.error(resp.error);
        // Remove the user message if there was an error
        setMessages(messages);
      } else {
        const assistantMsg: FaketorMessage = { role: 'assistant', content: resp.reply };
        setMessages([...updatedMessages, assistantMsg]);
        if (resp.tool_calls?.length) {
          const names = resp.tool_calls.map((t) => t.name);
          setToolsUsed(names);
          props.onToolCalled?.(names);
        }
      }
    } catch (err) {
      toast.error('Faketor is having trouble connecting. Try again.');
      console.error(err);
      setMessages(messages);
    } finally {
      setThinking(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  // Collapsed state — just a button bar
  if (!isExpanded) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <button
          onClick={() => setExpanded(true)}
          className="flex items-center gap-2 w-full text-left group"
        >
          <div className="flex items-center justify-center w-8 h-8 rounded-full bg-indigo-50 text-indigo-600 shrink-0">
            <MessageCircle size={16} />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-gray-900 group-hover:text-indigo-600 transition-colors">
              Ask Faketor
            </h3>
            <p className="text-xs text-gray-500 truncate">
              AI advisor — improvements, sell vs hold, development potential, comps
            </p>
          </div>
          <ChevronDown size={16} className="text-gray-400 group-hover:text-indigo-600 transition-colors" />
        </button>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-gradient-to-r from-indigo-50 to-purple-50">
        <div className="flex items-center gap-2">
          <div className="flex items-center justify-center w-7 h-7 rounded-full bg-indigo-100 text-indigo-600">
            <Bot size={14} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Faketor</h3>
            <p className="text-[10px] text-gray-500">AI Real Estate Advisor</p>
          </div>
        </div>
        {!props.alwaysExpanded && (
          <button
            onClick={() => setExpanded(false)}
            className="text-gray-400 hover:text-gray-600 p-1"
          >
            <ChevronUp size={16} />
          </button>
        )}
      </div>

      {/* Messages area */}
      <div
        ref={scrollRef}
        className="overflow-y-auto px-4 py-3 space-y-3"
        style={{ maxHeight: '400px', minHeight: '200px' }}
      >
        {messages.length === 0 && !thinking && (
          <div className="space-y-3">
            <p className="text-sm text-gray-500 text-center py-2">
              Ask me anything about this property. I can pull live data on zoning,
              improvements, comps, and more.
            </p>
            <div className="grid grid-cols-2 gap-2">
              {activePrompts.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => handleSend(prompt)}
                  className="text-left text-xs px-3 py-2 rounded-lg border border-gray-200 text-gray-600 hover:border-indigo-300 hover:text-indigo-700 hover:bg-indigo-50 transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {thinking && (
          <div className="flex items-start gap-2">
            <div className="flex items-center justify-center w-6 h-6 rounded-full bg-indigo-50 text-indigo-500 shrink-0 mt-0.5">
              <Bot size={12} />
            </div>
            <div className="bg-gray-50 rounded-lg rounded-tl-none px-3 py-2 max-w-[85%]">
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <Loader2 size={12} className="animate-spin" />
                <span>Analyzing property data...</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Tools indicator */}
      {toolsUsed.length > 0 && (
        <div className="px-4 pb-1">
          <p className="text-[10px] text-gray-400">
            Used: {toolsUsed.map(formatToolName).join(', ')}
          </p>
        </div>
      )}

      {/* Input area */}
      <div className="px-4 pb-3 pt-1">
        <div className="flex items-center gap-2 border border-gray-200 rounded-lg px-3 py-2 focus-within:border-indigo-300 focus-within:ring-1 focus-within:ring-indigo-100 transition-all">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about this property..."
            disabled={thinking}
            className="flex-1 text-sm bg-transparent outline-none placeholder-gray-400 disabled:opacity-50"
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || thinking}
            className="text-indigo-500 hover:text-indigo-700 disabled:text-gray-300 disabled:cursor-not-allowed transition-colors p-0.5"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MessageBubble({ message }: { message: FaketorMessage }) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex items-start gap-2 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className={`flex items-center justify-center w-6 h-6 rounded-full shrink-0 mt-0.5 ${
          isUser
            ? 'bg-blue-50 text-blue-500'
            : 'bg-indigo-50 text-indigo-500'
        }`}
      >
        {isUser ? <User size={12} /> : <Bot size={12} />}
      </div>
      <div
        className={`rounded-lg px-3 py-2 max-w-[85%] text-sm leading-relaxed ${
          isUser
            ? 'bg-blue-500 text-white rounded-tr-none'
            : 'bg-gray-50 text-gray-800 rounded-tl-none'
        }`}
      >
        {isUser ? (
          <p>{message.content}</p>
        ) : (
          <MarkdownLite text={message.content} />
        )}
      </div>
    </div>
  );
}

/** Minimal markdown rendering for assistant messages — bold, bullets, numbers. */
function MarkdownLite({ text }: { text: string }) {
  const paragraphs = text.split('\n\n');

  return (
    <div className="space-y-2">
      {paragraphs.map((para, i) => {
        const lines = para.split('\n');
        const isList = lines.every(
          (l) => /^\s*[-*]\s/.test(l) || /^\s*\d+\.\s/.test(l) || l.trim() === '',
        );

        if (isList) {
          return (
            <ul key={i} className="list-disc list-inside space-y-0.5">
              {lines
                .filter((l) => l.trim())
                .map((l, j) => (
                  <li key={j} className="text-sm">
                    <InlineBold text={l.replace(/^\s*[-*]\s*/, '').replace(/^\s*\d+\.\s*/, '')} />
                  </li>
                ))}
            </ul>
          );
        }

        return (
          <p key={i}>
            <InlineBold text={para.replace(/\n/g, ' ')} />
          </p>
        );
      })}
    </div>
  );
}

/** Render **bold** inline. */
function InlineBold({ text }: { text: string }) {
  const parts = text.split(/\*\*(.*?)\*\*/g);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <strong key={i} className="font-semibold">
            {part}
          </strong>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

function formatToolName(name: string): string {
  return name
    .replace(/^get_/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
