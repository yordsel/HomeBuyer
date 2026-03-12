import { useState, useMemo } from 'react';
import { toast } from 'sonner';
import { Home, LogIn, UserPlus, Check, X, ArrowLeft, Mail } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { authForgotPassword, authResetPassword, authGoogleAuthorize } from '../lib/api';
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
  if (passed <= 1) return { score: passed, label: 'Weak', color: 'bg-red-500' };
  if (passed <= 2) return { score: passed, label: 'Weak', color: 'bg-red-500' };
  if (passed <= 3) return { score: passed, label: 'Fair', color: 'bg-yellow-500' };
  if (passed <= 4) return { score: passed, label: 'Good', color: 'bg-blue-500' };
  return { score: passed, label: 'Strong', color: 'bg-green-500' };
}

export function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<'login' | 'register' | 'forgot' | 'reset'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [acceptedTos, setAcceptedTos] = useState(false);
  const [showTerms, setShowTerms] = useState(false);
  const [loading, setLoading] = useState(false);
  const [resetToken, setResetToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [forgotSent, setForgotSent] = useState(false);

  const passwordStrength = useMemo(() => getPasswordStrength(password), [password]);
  const allRulesPassed = passwordStrength.score === PASSWORD_RULES.length;

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
    if (!allRulesPassed) {
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

  const newPasswordStrength = useMemo(
    () => (newPassword ? getPasswordStrength(newPassword) : null),
    [newPassword],
  );
  const newPasswordAllPassed = PASSWORD_RULES.every((r) => r.test(newPassword));

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

          {/* --- Forgot Password View --- */}
          {mode === 'forgot' && (
            <>
              <button
                onClick={() => { setMode('login'); setForgotSent(false); }}
                className="mb-4 flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
              >
                <ArrowLeft size={14} /> Back to sign in
              </button>

              <h2 className="mb-2 text-lg font-semibold text-gray-900">Forgot password?</h2>
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
                    className="mt-4 text-sm font-medium text-blue-600 hover:text-blue-700"
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
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      placeholder="you@example.com"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={loading}
                    className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                  >
                    {loading ? (
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
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

              <h2 className="mb-2 text-lg font-semibold text-gray-900">Reset your password</h2>
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
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
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
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
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
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                >
                  {loading && (
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  )}
                  Reset Password
                </button>
              </form>
            </>
          )}

          {/* --- Login / Register View --- */}
          {(mode === 'login' || mode === 'register') && (
            <>
              <h2 className="mb-6 text-lg font-semibold text-gray-900">
                {mode === 'login' ? 'Sign in to your account' : 'Create an account'}
              </h2>

              <form onSubmit={handleSubmit} className="space-y-4">
                {mode === 'register' && (
                  <div>
                    <label htmlFor="fullName" className="mb-1 block text-sm font-medium text-gray-700">
                      Full name
                    </label>
                    <input
                      id="fullName"
                      type="text"
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      placeholder="John Doe"
                    />
                  </div>
                )}

                <div>
                  <label htmlFor="email" className="mb-1 block text-sm font-medium text-gray-700">
                    Email address
                  </label>
                  <input
                    id="email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    placeholder="you@example.com"
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label htmlFor="password" className="block text-sm font-medium text-gray-700">
                      Password
                    </label>
                    {mode === 'login' && (
                      <button
                        type="button"
                        onClick={() => setMode('forgot')}
                        className="text-xs text-blue-600 hover:text-blue-700 font-medium"
                      >
                        Forgot password?
                      </button>
                    )}
                  </div>
                  <input
                    id="password"
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    placeholder={mode === 'register' ? 'Create a strong password' : 'Enter your password'}
                  />
                  {mode === 'register' && password.length > 0 && (
                    <div className="mt-2 space-y-2">
                      {/* Strength bar */}
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${passwordStrength.color}`}
                            style={{ width: `${(passwordStrength.score / PASSWORD_RULES.length) * 100}%` }}
                          />
                        </div>
                        <span className="text-xs font-medium text-gray-500">{passwordStrength.label}</span>
                      </div>
                      {/* Rule checklist */}
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
                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>
                      I agree to the{' '}
                      <button
                        type="button"
                        onClick={() => setShowTerms(true)}
                        className="font-medium text-blue-600 hover:text-blue-700 underline"
                      >
                        Terms and Conditions
                      </button>
                    </span>
                  </label>
                )}

                <button
                  type="submit"
                  disabled={loading || (mode === 'register' && (!acceptedTos || !allRulesPassed))}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {loading ? (
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
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
                    <path
                      d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
                      fill="#4285F4"
                    />
                    <path
                      d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                      fill="#34A853"
                    />
                    <path
                      d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                      fill="#FBBC05"
                    />
                    <path
                      d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                      fill="#EA4335"
                    />
                  </svg>
                  Continue with Google
                </button>
              </div>

              {/* Toggle mode */}
              <div className="mt-6 text-center text-sm text-gray-500">
                {mode === 'login' ? (
                  <>
                    Don&apos;t have an account?{' '}
                    <button
                      onClick={() => setMode('register')}
                      className="font-medium text-blue-600 hover:text-blue-700"
                    >
                      Create one
                    </button>
                  </>
                ) : (
                  <>
                    Already have an account?{' '}
                    <button
                      onClick={() => setMode('login')}
                      className="font-medium text-blue-600 hover:text-blue-700"
                    >
                      Sign in
                    </button>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
