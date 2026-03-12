/**
 * Conversation history page — browse, search, resume, and manage past chats.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  MessageCircle, Search, Trash2, Pencil, Check, X, Loader2, Clock,
} from 'lucide-react';
import { toast } from 'sonner';

import * as api from '../lib/api';
import type { Conversation } from '../types';

interface HistoryPageProps {
  onOpenConversation: (conversationId: number) => void;
}

export function HistoryPage({ onOpenConversation }: HistoryPageProps) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const fetchConversations = useCallback(async () => {
    try {
      const data = await api.listConversations();
      setConversations(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load conversations');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  const handleDelete = async (id: number) => {
    try {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      setDeletingId(null);
      toast.success('Conversation deleted');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete');
    }
  };

  const handleRename = async (id: number) => {
    const trimmed = editTitle.trim();
    if (!trimmed) return;
    try {
      await api.updateConversationTitle(id, trimmed);
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, title: trimmed } : c)),
      );
      setEditingId(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to rename');
    }
  };

  const filtered = search
    ? conversations.filter((c) =>
        (c.title ?? '').toLowerCase().includes(search.toLowerCase()),
      )
    : conversations;

  function formatDate(dateStr: string) {
    const d = new Date(dateStr + 'Z');
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHrs = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHrs < 24) return `${diffHrs}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh]">
        <Loader2 size={32} className="animate-spin text-indigo-400 mb-3" />
        <p className="text-sm text-gray-500">Loading conversations...</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Conversation History</h1>
        <p className="text-sm text-gray-500">
          Browse and resume your past conversations with Faketor.
        </p>
      </div>

      {/* Search */}
      {conversations.length > 0 && (
        <div className="mb-4">
          <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-3 py-2
                          focus-within:border-indigo-300 focus-within:ring-2 focus-within:ring-indigo-100 transition-all">
            <Search size={16} className="text-gray-400 shrink-0" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search conversations..."
              className="flex-1 text-sm bg-transparent outline-none placeholder-gray-400"
            />
          </div>
        </div>
      )}

      {/* Empty state */}
      {conversations.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-gray-100 text-gray-400 mb-4">
            <MessageCircle size={32} />
          </div>
          <h2 className="text-lg font-semibold text-gray-700 mb-1">No conversations yet</h2>
          <p className="text-sm text-gray-500">
            Start a new chat with Faketor to see your conversations here.
          </p>
        </div>
      )}

      {/* Conversation list */}
      <div className="space-y-2">
        {filtered.map((conv) => (
          <div
            key={conv.id}
            className="group bg-white border border-gray-200 rounded-xl px-4 py-3
                       hover:border-indigo-200 hover:shadow-sm transition-all cursor-pointer"
          >
            <div className="flex items-start justify-between gap-3">
              {/* Click to open */}
              <div
                className="flex-1 min-w-0"
                onClick={() => {
                  if (editingId !== conv.id && deletingId !== conv.id) {
                    onOpenConversation(conv.id);
                  }
                }}
              >
                {editingId === conv.id ? (
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleRename(conv.id);
                        if (e.key === 'Escape') setEditingId(null);
                      }}
                      className="flex-1 text-sm font-medium bg-gray-50 border border-gray-200 rounded px-2 py-1 outline-none
                                 focus:border-indigo-300 focus:ring-1 focus:ring-indigo-100"
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                    />
                    <button
                      onClick={(e) => { e.stopPropagation(); handleRename(conv.id); }}
                      className="p-1 text-emerald-600 hover:bg-emerald-50 rounded transition-colors"
                    >
                      <Check size={14} />
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setEditingId(null); }}
                      className="p-1 text-gray-400 hover:bg-gray-100 rounded transition-colors"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ) : (
                  <>
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {conv.title || 'Untitled conversation'}
                    </p>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="flex items-center gap-1 text-xs text-gray-400">
                        <Clock size={11} />
                        {formatDate(conv.updated_at)}
                      </span>
                      <span className="text-xs text-gray-400">
                        {conv.message_count} message{conv.message_count !== 1 ? 's' : ''}
                      </span>
                    </div>
                  </>
                )}
              </div>

              {/* Actions */}
              {editingId !== conv.id && (
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                  {deletingId === conv.id ? (
                    <>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(conv.id); }}
                        className="px-2 py-1 text-xs font-medium text-red-600 bg-red-50 border border-red-200 rounded
                                   hover:bg-red-100 transition-colors"
                      >
                        Confirm
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setDeletingId(null); }}
                        className="px-2 py-1 text-xs font-medium text-gray-500 bg-gray-50 border border-gray-200 rounded
                                   hover:bg-gray-100 transition-colors"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditingId(conv.id);
                          setEditTitle(conv.title ?? '');
                        }}
                        title="Rename"
                        className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setDeletingId(conv.id); }}
                        title="Delete"
                        className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                      >
                        <Trash2 size={13} />
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* No results */}
        {search && filtered.length === 0 && conversations.length > 0 && (
          <div className="text-center py-8">
            <p className="text-sm text-gray-500">No conversations match "{search}"</p>
          </div>
        )}
      </div>
    </div>
  );
}
