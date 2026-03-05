import { useState } from 'react';
import { Toaster } from 'sonner';
import { Sidebar } from './components/Sidebar';
import { PredictPage } from './pages/Predict';
import { NeighborhoodsPage } from './pages/Neighborhoods';
import { MarketPage } from './pages/Market';
import { ModelInfoPage } from './pages/ModelInfo';
import { AffordPage } from './pages/Afford';
import { PotentialPage } from './pages/Potential';
import { PropertyProvider } from './context/PropertyContext';
import { FaketorFAB } from './components/FaketorFAB';
import type { PageId } from './types';

function App() {
  const [currentPage, setCurrentPage] = useState<PageId>('predict');

  function renderPage() {
    switch (currentPage) {
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
        return <PredictPage onNavigate={setCurrentPage} />;
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

        <Toaster position="bottom-right" richColors closeButton />
      </div>
      <FaketorFAB />
    </PropertyProvider>
  );
}

export default App;
