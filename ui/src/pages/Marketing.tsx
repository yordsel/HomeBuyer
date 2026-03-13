import { useState, useMemo } from 'react';
import { toast } from 'sonner';
import { LogIn, UserPlus, X, Check, ArrowLeft, Mail } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { authGoogleAuthorize, authForgotPassword, authResetPassword } from '../lib/api';
import { TOS_VERSION, TermsPage } from './Terms';

interface PasswordRule {
  label: string;
  test: (pw: string) => boolean;
}

const PASSWORD_RULES: PasswordRule[] = [
  { label: 'At least 8 characters', test: (pw) => pw.length >= 8 },
  { label: 'One uppercase letter', test: (pw) => /[A-Z]/.test(pw) },
  { label: 'One lowercase letter', test: (pw) => /[a-z]/.test(pw) },
  { label: 'One digit', test: (pw) => /\d/.test(pw) },
  { label: 'One special character', test: (pw) => /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?`~]/.test(pw) },
];

function getPasswordStrength(pw: string): { score: number; label: string; color: string } {
  const passed = PASSWORD_RULES.filter((r) => r.test(pw)).length;
  if (passed <= 2) return { score: passed, label: 'Weak', color: 'bg-red-500' };
  if (passed <= 3) return { score: passed, label: 'Fair', color: 'bg-yellow-500' };
  if (passed <= 4) return { score: passed, label: 'Good', color: 'bg-blue-500' };
  return { score: passed, label: 'Strong', color: 'bg-green-500' };
}

/* -------------------------------------------------------------------------- */
/*  Auth Modal                                                                 */
/* -------------------------------------------------------------------------- */

function AuthModal({ onClose, initialMode = 'login' }: { onClose: () => void; initialMode?: 'login' | 'register' }) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<'login' | 'register' | 'forgot' | 'reset'>(initialMode);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [acceptedTos, setAcceptedTos] = useState(false);
  const [showTerms, setShowTerms] = useState(false);
  const [loading, setLoading] = useState(false);
  const [forgotSent, setForgotSent] = useState(false);
  const [resetToken, setResetToken] = useState('');
  const [newPassword, setNewPassword] = useState('');

  const passwordStrength = useMemo(() => getPasswordStrength(password), [password]);
  const allRulesPassed = passwordStrength.score === PASSWORD_RULES.length;
  const newPasswordStrength = useMemo(
    () => (newPassword ? getPasswordStrength(newPassword) : null),
    [newPassword],
  );
  const newPasswordAllPassed = PASSWORD_RULES.every((r) => r.test(newPassword));

  if (showTerms) {
    return (
      <div className="fixed inset-0 z-[100] overflow-y-auto bg-black/60 backdrop-blur-sm" onClick={onClose}>
        <div onClick={(e) => e.stopPropagation()}>
          <TermsPage onBack={() => setShowTerms(false)} />
        </div>
      </div>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      if (mode === 'register') {
        if (!allRulesPassed) {
          toast.error('Password does not meet all requirements');
          setLoading(false);
          return;
        }
        if (!acceptedTos) {
          toast.error('You must accept the Terms and Conditions');
          setLoading(false);
          return;
        }
        await register(email, password, fullName || undefined, TOS_VERSION);
        toast.success('Account created successfully');
      } else {
        await login(email, password);
        toast.success('Welcome back!');
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Authentication failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleForgotPassword(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await authForgotPassword(email);
      setForgotSent(true);
      toast.success('If an account exists, a reset link has been sent');
    } catch {
      toast.error('Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  async function handleResetPassword(e: React.FormEvent) {
    e.preventDefault();
    if (!newPasswordAllPassed) {
      toast.error('Password does not meet all requirements');
      return;
    }
    setLoading(true);
    try {
      await authResetPassword(resetToken, newPassword);
      toast.success('Password reset! Please sign in.');
      setMode('login');
      setResetToken('');
      setNewPassword('');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to reset password');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm px-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-2xl relative" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="absolute top-4 right-4 text-gray-400 hover:text-gray-600 transition-colors">
          <X size={20} />
        </button>

        {/* --- Forgot Password View --- */}
        {mode === 'forgot' && (
          <>
            <button
              onClick={() => { setMode('login'); setForgotSent(false); }}
              className="mb-4 flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
            >
              <ArrowLeft size={14} /> Back to sign in
            </button>

            <h2 className="mb-2 text-xl font-bold text-gray-900">Forgot password?</h2>
            <p className="mb-6 text-sm text-gray-500">
              Enter your email and we'll send you instructions to reset your password.
            </p>

            {forgotSent ? (
              <div className="rounded-lg bg-green-50 border border-green-200 p-4 text-center">
                <Mail size={24} className="mx-auto mb-2 text-green-600" />
                <p className="text-sm font-medium text-green-800">Check your email</p>
                <p className="text-xs text-green-600 mt-1">
                  If an account with that email exists, we've sent reset instructions.
                </p>
                <button
                  onClick={() => { setMode('reset'); setForgotSent(false); }}
                  className="mt-4 text-sm font-medium text-amber-600 hover:text-amber-700"
                >
                  I have a reset token
                </button>
              </div>
            ) : (
              <form onSubmit={handleForgotPassword} className="space-y-4">
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">Email address</label>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
                    placeholder="you@example.com"
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-500 px-4 py-2.5 text-sm font-bold text-slate-900 hover:bg-amber-400 disabled:opacity-50 transition-colors"
                >
                  {loading ? (
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-900 border-t-transparent" />
                  ) : (
                    <Mail size={16} />
                  )}
                  Send Reset Link
                </button>
              </form>
            )}
          </>
        )}

        {/* --- Reset Password View --- */}
        {mode === 'reset' && (
          <>
            <button
              onClick={() => setMode('login')}
              className="mb-4 flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
            >
              <ArrowLeft size={14} /> Back to sign in
            </button>

            <h2 className="mb-2 text-xl font-bold text-gray-900">Reset your password</h2>
            <p className="mb-6 text-sm text-gray-500">
              Enter the reset token from your email and choose a new password.
            </p>

            <form onSubmit={handleResetPassword} className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Reset token</label>
                <input
                  type="text"
                  required
                  value={resetToken}
                  onChange={(e) => setResetToken(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
                  placeholder="Paste token from your email"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">New password</label>
                <input
                  type="password"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
                  placeholder="Create a strong password"
                />
                {newPassword && newPasswordStrength && (
                  <div className="mt-2 space-y-2">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${newPasswordStrength.color}`}
                          style={{ width: `${(newPasswordStrength.score / PASSWORD_RULES.length) * 100}%` }}
                        />
                      </div>
                      <span className="text-xs font-medium text-gray-500">{newPasswordStrength.label}</span>
                    </div>
                    <ul className="space-y-0.5">
                      {PASSWORD_RULES.map((rule) => {
                        const passed = rule.test(newPassword);
                        return (
                          <li key={rule.label} className={`flex items-center gap-1.5 text-xs ${passed ? 'text-green-600' : 'text-gray-400'}`}>
                            {passed ? <Check size={12} /> : <X size={12} />}
                            {rule.label}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
              </div>
              <button
                type="submit"
                disabled={loading || !newPasswordAllPassed || !resetToken}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-500 px-4 py-2.5 text-sm font-bold text-slate-900 hover:bg-amber-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {loading && (
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-900 border-t-transparent" />
                )}
                Reset Password
              </button>
            </form>
          </>
        )}

        {/* --- Login / Register View --- */}
        {(mode === 'login' || mode === 'register') && (
          <>
            <h2 className="mb-1 text-xl font-bold text-gray-900">
              {mode === 'login' ? 'Welcome back' : 'Create an account'}
            </h2>
            <p className="mb-6 text-sm text-gray-500">
              {mode === 'login' ? 'Sign in to access your predictions' : 'Get started with HomeBuyer'}
            </p>

            <form onSubmit={handleSubmit} className="space-y-4">
              {mode === 'register' && (
                <div>
                  <label htmlFor="auth-fullName" className="mb-1 block text-sm font-medium text-gray-700">Full name</label>
                  <input id="auth-fullName" type="text" value={fullName} onChange={(e) => setFullName(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    placeholder="John Doe" />
                </div>
              )}
              <div>
                <label htmlFor="auth-email" className="mb-1 block text-sm font-medium text-gray-700">Email address</label>
                <input id="auth-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  placeholder="you@example.com" />
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label htmlFor="auth-password" className="block text-sm font-medium text-gray-700">Password</label>
                  {mode === 'login' && (
                    <button type="button" onClick={() => setMode('forgot')} className="text-xs text-amber-600 hover:text-amber-700 font-medium">
                      Forgot password?
                    </button>
                  )}
                </div>
                <input id="auth-password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  placeholder={mode === 'register' ? 'Create a strong password' : 'Enter your password'} />
                {mode === 'register' && password.length > 0 && (
                  <div className="mt-2 space-y-2">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${passwordStrength.color}`}
                          style={{ width: `${(passwordStrength.score / PASSWORD_RULES.length) * 100}%` }}
                        />
                      </div>
                      <span className="text-xs font-medium text-gray-500">{passwordStrength.label}</span>
                    </div>
                    <ul className="space-y-0.5">
                      {PASSWORD_RULES.map((rule) => {
                        const passed = rule.test(password);
                        return (
                          <li key={rule.label} className={`flex items-center gap-1.5 text-xs ${passed ? 'text-green-600' : 'text-gray-400'}`}>
                            {passed ? <Check size={12} /> : <X size={12} />}
                            {rule.label}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
              </div>
              {mode === 'register' && (
                <label className="flex items-start gap-2 text-sm text-gray-600">
                  <input
                    type="checkbox"
                    checked={acceptedTos}
                    onChange={(e) => setAcceptedTos(e.target.checked)}
                    className="mt-0.5 h-4 w-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500"
                  />
                  <span>
                    I agree to the{' '}
                    <button
                      type="button"
                      onClick={() => setShowTerms(true)}
                      className="font-medium text-amber-600 hover:text-amber-700 underline"
                    >
                      Terms and Conditions
                    </button>
                  </span>
                </label>
              )}
              <button type="submit" disabled={loading || (mode === 'register' && (!acceptedTos || !allRulesPassed))}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-500 px-4 py-2.5 text-sm font-bold text-slate-900 hover:bg-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                {loading ? (
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-900 border-t-transparent" />
                ) : mode === 'login' ? (
                  <LogIn size={16} />
                ) : (
                  <UserPlus size={16} />
                )}
                {mode === 'login' ? 'Sign In' : 'Create Account'}
              </button>
            </form>

            {/* Divider + Google OAuth */}
            <div className="mt-6">
              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-gray-200" />
                </div>
                <div className="relative flex justify-center text-xs">
                  <span className="bg-white px-3 text-gray-400">or</span>
                </div>
              </div>

              <button
                type="button"
                onClick={async () => {
                  try {
                    const { authorization_url } = await authGoogleAuthorize();
                    window.location.href = authorization_url;
                  } catch (err) {
                    if (err instanceof Error && err.message.includes('not configured')) {
                      toast.error('Google sign-in is not configured');
                    } else {
                      toast.error('Failed to start Google sign-in');
                    }
                  }
                }}
                className="mt-4 flex w-full items-center justify-center gap-3 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 transition-colors"
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24">
                  <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
                  <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                  <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
                  <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
                </svg>
                Continue with Google
              </button>
            </div>

            <div className="mt-6 text-center text-sm text-gray-500">
              {mode === 'login' ? (
                <>Don&apos;t have an account?{' '}
                  <button onClick={() => setMode('register')} className="font-medium text-amber-600 hover:text-amber-700">Create one</button>
                </>
              ) : (
                <>Already have an account?{' '}
                  <button onClick={() => setMode('login')} className="font-medium text-amber-600 hover:text-amber-700">Sign in</button>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  FAQ Item                                                                   */
/* -------------------------------------------------------------------------- */

function FaqItem({ question, answer }: { question: string; answer: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="bg-white rounded-xl border border-gray-200">
      <button className="w-full text-left px-6 py-4 flex items-center justify-between" onClick={() => setOpen(!open)}>
        <span className="font-semibold text-gray-900">{question}</span>
        <svg className={`w-5 h-5 text-gray-400 shrink-0 transition-transform duration-300 ${open ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d="M19 9l-7 7-7-7" /></svg>
      </button>
      <div className={`overflow-hidden transition-all duration-300 ${open ? 'max-h-96' : 'max-h-0'}`}>
        <p className="px-6 pb-4 text-gray-600 text-sm leading-relaxed">{answer}</p>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Marketing Page                                                             */
/* -------------------------------------------------------------------------- */

const FAQ_DATA = [
  { q: 'Is this actually free?', a: "Yes. We're a side project built by one developer who wanted to understand Berkeley real estate and got slightly carried away. There's no catch. There's no monetization strategy. There's barely a business plan." },
  { q: 'How accurate are the predictions?', a: "Our model has a median absolute error of about $95K on Berkeley sales. That's pretty good for a machine, but we'd never tell you to bet your life savings on it. Actually, we legally cannot tell you that. This is not financial advice." },
  { q: 'Why only Berkeley?', a: 'Because Berkeley is weird enough to be interesting and small enough that one person can build a model for it. Also, the developer lives here and has opinions about housing prices.' },
  { q: 'What is Faketor?', a: "Faketor is our AI chat agent powered by Claude. The name is a portmanteau of \"fake\" and \"realtor.\" It has access to 14 different tools \u2014 property lookup, comps, zoning, permits, rental analysis, market data, and more. It's like a real estate agent except it won't ghost you after closing." },
  { q: 'Can I use this to buy a house?', a: 'You can use this to inform your house-buying decisions. You should not use this as your sole source of truth. We are a side project, not a licensed real estate brokerage. Please also consult a human who has passed an exam.' },
  { q: 'Why should I trust an AI for real estate?', a: "You probably shouldn't trust any single source for a $1.5M decision. But our model is transparent \u2014 you can see every feature it uses, its error metrics, and how it weights different factors. That's more than most agents will show you." },
];

export function MarketingPage() {
  const [showAuth, setShowAuth] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [showTermsPage, setShowTermsPage] = useState(false);

  function openAuth(mode: 'login' | 'register' = 'login') {
    setAuthMode(mode);
    setShowAuth(true);
  }

  return (
    <div className="bg-white text-gray-900 font-sans antialiased">
      {/* Auth Modal */}
      {showAuth && <AuthModal onClose={() => setShowAuth(false)} initialMode={authMode} />}

      {/* Full-page Terms overlay */}
      {showTermsPage && (
        <div className="fixed inset-0 z-[90] overflow-y-auto bg-white">
          <TermsPage onBack={() => setShowTermsPage(false)} />
        </div>
      )}

      {/* Sticky Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-slate-900/95 backdrop-blur-sm border-b border-slate-800">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold text-white">HomeBuyer</span>
            <span className="text-xs text-slate-400 hidden sm:inline">Berkeley, CA</span>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => openAuth('login')} className="text-slate-300 hover:text-white text-sm font-medium transition-colors">Sign In</button>
            <button onClick={() => openAuth('register')} className="bg-amber-500 hover:bg-amber-400 text-slate-900 font-semibold text-sm px-5 py-2 rounded-lg transition-colors">Get Started</button>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="bg-slate-900 pt-32 pb-20 md:pt-40 md:pb-28 px-6">
        <div className="max-w-4xl mx-auto text-center">
          <h1 className="text-4xl sm:text-5xl md:text-7xl font-extrabold leading-tight mb-6"
            style={{ background: 'linear-gradient(135deg, #ffffff 0%, #fbbf24 50%, #f59e0b 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
            We built an AI that tells you your house is overpriced.
          </h1>
          <p className="text-xl text-white font-medium mb-2">You're welcome.</p>
          <p className="text-lg text-slate-400 max-w-2xl mx-auto mb-10">
            HomeBuyer is a Berkeley-specific real estate analytics tool that gives you price predictions, neighborhood data,
            and brutally honest market insights. It's like having a real estate agent who doesn't need your commission.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center mb-6">
            <button onClick={() => openAuth('register')} className="bg-amber-500 hover:bg-amber-400 text-slate-900 font-bold text-lg px-8 py-3.5 rounded-lg transition-colors">
              Get Your Reality Check
            </button>
            <button onClick={() => openAuth('login')} className="border-2 border-slate-500 hover:border-white text-white font-semibold text-lg px-8 py-3.5 rounded-lg transition-colors">
              Sign In
            </button>
          </div>
          <p className="text-sm text-slate-500 italic">
            Free account required for predictions. We promise not to spam you. We barely have email set up.
          </p>
        </div>
      </section>

      {/* Features */}
      <section className="py-20 md:py-28 px-6 bg-white">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-bold mb-3">Features That Exist and Mostly Work</h2>
            <p className="text-gray-500 text-lg">We tested them. Some of them. Recently-ish.</p>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
            {[
              { emoji: '\u{1F52E}', title: "Know What It's Worth (Approximately)", desc: "Paste a Redfin URL or click anywhere on the map. Our ML model trained on 5 years of Berkeley sales data tells you what it should sell for. It's right about 85% of the time, which is better than your uncle's gut feeling." },
              { emoji: '\u{1F916}', title: 'An AI That Knows More Than Your Agent', desc: "Ask Faketor anything about a Berkeley property. It has 14 tools at its disposal \u2014 comps, zoning, permits, rental estimates, sell-vs-hold analysis \u2014 and zero emotional attachment to closing the deal." },
              { emoji: '\u{1F4CD}', title: "Neighborhood Data That Doesn't Sugarcoat", desc: 'Median prices, price trends, days on market, sale-to-list ratios. Every Berkeley neighborhood, laid bare. No "up-and-coming" euphemisms here.' },
              { emoji: '\u{1F3D7}', title: 'Can You Build an ADU? Probably.', desc: "Zoning analysis, ADU feasibility, SB 9 lot-split eligibility, Middle Housing rules. We read the Berkeley Municipal Code so you don't have to. And honestly, neither did your contractor." },
              { emoji: '\u{1F4C8}', title: 'Watch the Market Do Whatever It Wants', desc: 'Real-time Berkeley market analytics. Mortgage rates, median prices, inventory levels. Updated regularly, ignored frequently.' },
              { emoji: '\u{1F4B0}', title: 'Math That Hurts Your Feelings', desc: "Enter your budget. See what you can actually afford in Berkeley. Spoiler: it's smaller than you think. The calculator doesn't lie, even when you want it to." },
            ].map((f, i) => (
              <div key={i} className="bg-gray-50 rounded-2xl p-7 hover:shadow-lg transition-shadow">
                <div className="text-4xl mb-4">{f.emoji}</div>
                <h3 className="text-xl font-bold mb-2">{f.title}</h3>
                <p className="text-gray-600">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Faketor Spotlight */}
      <section className="py-20 md:py-28 px-6 bg-gray-50">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl md:text-4xl font-bold mb-3">
              Meet Faketor.{' '}
              <span className="inline-flex items-center"><span className="inline-block w-2.5 h-2.5 bg-green-500 rounded-full animate-pulse mr-1" /></span>
              {' '}Your AI Agent Who Can't Be Bribed.
            </h2>
            <p className="text-gray-500 text-lg">Powered by Claude. Armed with 14 tools. Incapable of telling you what you want to hear.</p>
          </div>
          {/* Fake chat */}
          <div className="bg-white rounded-2xl shadow-xl border border-gray-200 overflow-hidden max-w-2xl mx-auto">
            <div className="bg-slate-800 px-5 py-3 flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-red-400" />
              <div className="w-3 h-3 rounded-full bg-yellow-400" />
              <div className="w-3 h-3 rounded-full bg-green-400" />
              <span className="text-slate-400 text-sm ml-2">Faketor Chat</span>
            </div>
            <div className="p-6 space-y-5">
              <div className="flex justify-end">
                <div className="bg-blue-600 text-white px-4 py-2.5 rounded-2xl rounded-br-md max-w-sm text-sm">
                  Is 1200 Cedar St a good deal at $1.2M?
                </div>
              </div>
              <div className="flex justify-start">
                <div className="bg-gray-100 px-4 py-3 rounded-2xl rounded-bl-md max-w-md text-sm space-y-2.5">
                  <p className="text-gray-800">Let me look into that...</p>
                  <div className="space-y-1">
                    {['Looking up property...', 'Getting comparable sales...', 'Running price prediction...'].map((t, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs text-gray-500">
                        <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-medium">tool</span>{t}
                      </div>
                    ))}
                  </div>
                  <p className="text-gray-800 leading-relaxed">
                    Based on 8 comparable sales in the Northside neighborhood, the predicted fair value is <strong>$1,087,000</strong>.
                    At $1.2M, you'd be paying a <strong>10.4% premium</strong>. The house hasn't been updated since 1987,
                    the roof permit was 22 years ago, and the lot is too small for an ADU. But hey, it has "character."
                  </p>
                </div>
              </div>
            </div>
          </div>
          <div className="text-center mt-8">
            <button onClick={() => openAuth('register')} className="inline-block bg-amber-500 hover:bg-amber-400 text-slate-900 font-bold px-8 py-3 rounded-lg transition-colors">
              Ask Faketor Yourself
            </button>
          </div>
        </div>
      </section>

      {/* Model Transparency */}
      <section className="py-20 md:py-28 px-6 bg-white">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl md:text-4xl font-bold mb-3">We Show Our Work. Unlike Some People.</h2>
            <p className="text-gray-500 text-lg">Our ML model page shows you exactly how bad &mdash; or good &mdash; our predictions are.</p>
          </div>
          <div className="grid md:grid-cols-3 gap-6">
            {[
              { stat: '~$95K', label: 'Median Absolute Error', note: 'Off by this much, on average. Could be worse.' },
              { stat: '0.82', label: 'R-squared', note: 'Explains this much of price variation. The rest is vibes.' },
              { stat: '30+', label: 'Features Used', note: "Including things you'd never think of, like permit history from 1985." },
            ].map((s, i) => (
              <div key={i} className="text-center bg-gray-50 rounded-2xl p-8">
                <div className="text-4xl md:text-5xl font-extrabold text-slate-800 mb-2">{s.stat}</div>
                <div className="text-sm font-semibold text-gray-700 mb-1">{s.label}</div>
                <p className="text-xs text-gray-500">{s.note}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Testimonials */}
      <section className="py-20 md:py-28 px-6 bg-gray-50">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl md:text-4xl font-bold mb-3">What People Definitely Said About Us</h2>
            <p className="text-gray-500 text-lg">These are not real testimonials. We don't have users yet. But if we did, they'd probably say this.</p>
          </div>
          <div className="grid md:grid-cols-3 gap-8">
            {[
              { stars: 5, quote: 'It told me my dream home was overpriced by $200K. I bought it anyway. It was right.', name: 'Sarah K.', detail: 'Elmwood \u00b7 Bought in 2024' },
              { stars: 4, quote: "I used HomeBuyer's affordability calculator and it ruined my weekend. 10/10 would recommend.", name: 'Mike T.', detail: 'North Berkeley \u00b7 Lost a star because the truth hurts' },
              { stars: 5, quote: "Faketor told me my lot wasn't eligible for SB 9 splitting. My contractor disagreed. Faketor was right.", name: 'Anonymous', detail: "Contractor's Former Client" },
            ].map((t, i) => (
              <div key={i} className="bg-white rounded-2xl p-7 shadow-sm">
                <div className="text-amber-400 text-lg mb-3">
                  {'★'.repeat(t.stars)}{t.stars < 5 && <span className="text-gray-300">{'★'.repeat(5 - t.stars)}</span>}
                </div>
                <p className="text-gray-700 italic mb-4">"{t.quote}"</p>
                <div className="text-sm font-semibold text-gray-900">{t.name}</div>
                <div className="text-xs text-gray-500">{t.detail}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="py-20 md:py-28 px-6 bg-white">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl md:text-4xl font-bold mb-3">Pricing That Makes Sense for Once</h2>
            <p className="text-gray-500 text-lg">Just kidding. It's free. We're not charging you to feel bad about housing prices.</p>
          </div>
          <div className="grid md:grid-cols-3 gap-8">
            {/* Denial */}
            <div className="bg-gray-50 rounded-2xl p-7 border border-gray-200">
              <h3 className="text-xl font-bold mb-1">Denial</h3>
              <div className="text-3xl font-extrabold mb-4">Free</div>
              <ul className="text-gray-600 text-sm space-y-2.5 mb-8">
                <li className="flex items-start gap-2"><span className="text-green-500 mt-0.5">&#x2713;</span> Browse neighborhoods</li>
                <li className="flex items-start gap-2"><span className="text-green-500 mt-0.5">&#x2713;</span> See median prices</li>
                <li className="flex items-start gap-2"><span className="text-green-500 mt-0.5">&#x2713;</span> Pretend you can afford it</li>
              </ul>
              <button onClick={() => openAuth('register')} className="block w-full text-center border-2 border-gray-300 hover:border-gray-400 text-gray-700 font-semibold py-2.5 rounded-lg transition-colors">
                Stay in Denial
              </button>
            </div>
            {/* Acceptance */}
            <div className="bg-amber-50 rounded-2xl p-7 border-2 border-amber-400 relative">
              <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-amber-500 text-slate-900 text-xs font-bold px-3 py-1 rounded-full">POPULAR</span>
              <h3 className="text-xl font-bold mb-1">Acceptance</h3>
              <div className="text-3xl font-extrabold mb-4">Also Free</div>
              <ul className="text-gray-600 text-sm space-y-2.5 mb-8">
                <li className="flex items-start gap-2"><span className="text-green-500 mt-0.5">&#x2713;</span> Everything in Denial</li>
                <li className="flex items-start gap-2"><span className="text-green-500 mt-0.5">&#x2713;</span> Price predictions</li>
                <li className="flex items-start gap-2"><span className="text-green-500 mt-0.5">&#x2713;</span> AI chat with Faketor</li>
                <li className="flex items-start gap-2"><span className="text-green-500 mt-0.5">&#x2713;</span> Development potential</li>
                <li className="flex items-start gap-2"><span className="text-green-500 mt-0.5">&#x2713;</span> Affordability calculator</li>
                <li className="flex items-start gap-2"><span className="text-amber-500 mt-0.5">&#x26A0;</span> Warning: contains math</li>
              </ul>
              <button onClick={() => openAuth('register')} className="block w-full text-center bg-amber-500 hover:bg-amber-400 text-slate-900 font-bold py-2.5 rounded-lg transition-colors">
                Face Reality
              </button>
            </div>
            {/* Therapy */}
            <div className="bg-gray-50 rounded-2xl p-7 border border-gray-200 opacity-75">
              <h3 className="text-xl font-bold mb-1">Therapy</h3>
              <div className="text-3xl font-extrabold mb-4">Not Included</div>
              <ul className="text-gray-400 text-sm space-y-2.5 mb-8">
                <li className="flex items-start gap-2"><span className="text-gray-300 mt-0.5">&#x2713;</span> Everything in Acceptance</li>
                <li className="flex items-start gap-2"><span className="text-gray-300 mt-0.5">&#x2713;</span> Emotional support after seeing prices</li>
                <li className="flex items-start gap-2"><span className="text-gray-300 mt-0.5">&#x2713;</span> Someone to blame</li>
                <li className="flex items-start gap-2"><span className="text-gray-300 mt-0.5">&#x2713;</span> A time machine to 2012</li>
              </ul>
              <span className="block text-center bg-gray-200 text-gray-400 font-semibold py-2.5 rounded-lg cursor-not-allowed">
                We Wish
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-20 md:py-28 px-6 bg-gray-50">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl md:text-4xl font-bold mb-3">Questions We Wish People Would Ask</h2>
          </div>
          <div className="space-y-3">
            {FAQ_DATA.map((faq, i) => <FaqItem key={i} question={faq.q} answer={faq.a} />)}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="py-20 md:py-28 px-6 bg-slate-900">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-extrabold text-white mb-4">Ready to Find Out What You Can't Afford?</h2>
          <p className="text-lg text-slate-400 mb-8">It's free, it's honest, and it only takes a minute to crush your dreams.</p>
          <button onClick={() => openAuth('register')} className="inline-block bg-amber-500 hover:bg-amber-400 text-slate-900 font-bold text-lg px-10 py-4 rounded-lg transition-colors">
            Try HomeBuyer
          </button>
          <p className="text-sm text-slate-600 mt-4">No credit card required. No feelings spared.</p>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-slate-950 py-8 px-6">
        <div className="max-w-6xl mx-auto text-center space-y-2">
          <p className="text-slate-500 text-sm">Built with questionable judgment in Berkeley, CA</p>
          <p className="text-slate-600 text-xs">HomeBuyer is a side project. Not a real estate brokerage. Not financial advice. Not even a real company.</p>
          <div className="flex justify-center gap-4 text-xs">
            <button onClick={() => { setShowTermsPage(true); window.scrollTo(0, 0); }} className="text-slate-500 hover:text-slate-300 transition-colors underline">
              Terms and Conditions
            </button>
          </div>
          <p className="text-slate-700 text-xs">&copy; 2026 HomeBuyer</p>
        </div>
      </footer>
    </div>
  );
}
