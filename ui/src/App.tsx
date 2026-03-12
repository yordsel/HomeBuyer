import { useState, useCallback } from 'react';
import { Toaster } from 'sonner';
import { Sidebar } from './components/Sidebar';
import { ContextPanel } from './components/context/ContextPanel';
import { ChatPage } from './pages/Chat';
import { PredictPage } from './pages/Predict';
import { NeighborhoodsPage } from './pages/Neighborhoods';
import { MarketPage } from './pages/Market';
import { ModelInfoPage } from './pages/ModelInfo';
import { AffordPage } from './pages/Afford';
import { PotentialPage } from './pages/Potential';
import { HistoryPage } from './pages/History';
import { MarketingPage } from './pages/Marketing';
import { TermsPage } from './pages/Terms';
import { AccountSettingsPage } from './pages/AccountSettings';
import { PropertyProvider } from './context/PropertyContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import type { PageId } from './types';

function AuthenticatedApp() {
  const [currentPage, setCurrentPage] = useState<PageId>('chat');
  // Track which conversation to load in Chat; null = new conversation
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  // Key to force-remount ChatPage when starting a new conversation
  const [chatKey, setChatKey] = useState(0);

  const handleNewChat = useCallback(() => {
    setActiveConversationId(null);
    setChatKey((k) => k + 1);
    setCurrentPage('chat');
  }, []);

  const handleOpenConversation = useCallback((convId: number) => {
    setActiveConversationId(convId);
    setChatKey((k) => k + 1);
    setCurrentPage('chat');
  }, []);

  function renderPage() {
    switch (currentPage) {
      case 'chat':
        return (
          <ChatPage
            key={chatKey}
            conversationId={activeConversationId}
            onNewChat={handleNewChat}
          />
        );
      case 'predict':
        return <PredictPage onNavigate={setCurrentPage} />;
      case 'neighborhoods':
        return <NeighborhoodsPage />;
      case 'market':
        return <MarketPage />;
      case 'model':
        return <ModelInfoPage />;
      case 'afford':
        return <AffordPage />;
      case 'potential':
        return <PotentialPage />;
      case 'history':
        return <HistoryPage onOpenConversation={handleOpenConversation} />;
      case 'settings':
        return <AccountSettingsPage />;
      default:
        return (
          <ChatPage
            key={chatKey}
            conversationId={activeConversationId}
            onNewChat={handleNewChat}
          />
        );
    }
  }

  return (
    <PropertyProvider>
      <div className="flex h-screen bg-gray-50 overflow-hidden">
        <Sidebar currentPage={currentPage} onNavigate={setCurrentPage} />

        <main className="flex-1 overflow-y-auto">
          <div className="p-6 lg:p-8">
            {renderPage()}
          </div>
        </main>

        {/* Right context panel — only visible on Chat page */}
        {currentPage === 'chat' && <ContextPanel />}
      </div>
    </PropertyProvider>
  );
}

function TosUpdateModal() {
  const { acceptTos, logout } = useAuth();
  const [loading, setLoading] = useState(false);
  const [showTerms, setShowTerms] = useState(false);

  if (showTerms) {
    return <TermsPage onBack={() => setShowTerms(false)} />;
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-2xl">
        <h2 className="mb-2 text-xl font-bold text-gray-900">Updated Terms & Conditions</h2>
        <p className="mb-6 text-sm text-gray-600">
          Our Terms and Conditions have been updated. Please review and accept the new terms to
          continue using HomeBuyer.
        </p>
        <div className="flex gap-3">
          <button
            onClick={() => setShowTerms(true)}
            className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Review Terms
          </button>
          <button
            onClick={async () => {
              setLoading(true);
              try {
                await acceptTos();
              } finally {
                setLoading(false);
              }
            }}
            disabled={loading}
            className="flex-1 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Accepting...' : 'I Accept'}
          </button>
        </div>
        <button
          onClick={logout}
          className="mt-4 w-full text-center text-xs text-gray-400 hover:text-gray-600"
        >
          Sign out instead
        </button>
      </div>
    </div>
  );
}

function AppContent() {
  const { isAuthenticated, isLoading, tosUpdateRequired } = useAuth();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <MarketingPage />;
  }

  if (tosUpdateRequired) {
    return <TosUpdateModal />;
  }

  return <AuthenticatedApp />;
}

function App() {
  return (
    <AuthProvider>
      <AppContent />
      <Toaster position="bottom-right" richColors closeButton />
    </AuthProvider>
  );
}

export default App;
