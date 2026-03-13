import { useState } from 'react';
import { Home } from 'lucide-react';
import { TermsPage } from './Terms';
import { AuthForm, BLUE_THEME } from '../components/auth/AuthForm';

export function LoginPage() {
  const [showTerms, setShowTerms] = useState(false);

  if (showTerms) {
    return <TermsPage onBack={() => setShowTerms(false)} />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-blue-600 text-white">
            <Home size={28} />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">HomeBuyer</h1>
          <p className="mt-1 text-sm text-gray-500">Berkeley Price Predictor</p>
        </div>

        {/* Card */}
        <div className="rounded-xl border border-gray-200 bg-white p-8 shadow-sm">
          <AuthForm theme={BLUE_THEME} onShowTerms={() => setShowTerms(true)} />
        </div>
      </div>
    </div>
  );
}
