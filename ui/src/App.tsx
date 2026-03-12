import { useState } from 'react';
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
import { MarketingPage } from './pages/Marketing';
import { PropertyProvider } from './context/PropertyContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import type { PageId } from './types';

function AuthenticatedApp() {
  const [currentPage, setCurrentPage] = useState<PageId>('chat');

  function renderPage() {
    switch (currentPage) {
      case 'chat':
        return <ChatPage />;
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
      default:
        return <ChatPage />;
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

function AppContent() {
  const { isAuthenticated, isLoading } = useAuth();

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
