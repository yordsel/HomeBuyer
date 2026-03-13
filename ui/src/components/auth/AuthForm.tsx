import { useState, useMemo } from 'react';
import { toast } from 'sonner';
import { LogIn, UserPlus, ArrowLeft, Mail } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { authForgotPassword, authResetPassword } from '../../lib/api';
import { TOS_VERSION } from '../../pages/Terms';
import { PASSWORD_RULES, getPasswordStrength } from '../../lib/password';
import { PasswordStrengthIndicator } from './PasswordStrengthIndicator';
import { GoogleOAuthButton } from './GoogleOAuthButton';

/* -------------------------------------------------------------------------- */
/*  Theme                                                                      */
/* -------------------------------------------------------------------------- */

export interface AuthFormTheme {
  /** Tailwind bg + hover classes for the primary action button. */
  primaryBg: string;
  /** Text color classes for the primary action button. */
  primaryText: string;
  /** Focus ring classes applied to inputs. */
  focusRing: string;
  /** Color classes for text links (forgot password, toggle mode, terms). */
  linkColor: string;
  /** Color classes for the TOS checkbox. */
  checkboxColor: string;
  /** Border color classes for the loading spinner. */
  spinnerBorder: string;
  /**
   * 'simple' — renders a single <h2> heading (Login page style).
   * 'with-subtitle' — renders <h2> + <p> subtitle (Marketing modal style).
   */
  headingStyle: 'simple' | 'with-subtitle';
}

export const BLUE_THEME: AuthFormTheme = {
  primaryBg: 'bg-blue-600 hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2',
  primaryText: 'text-white',
  focusRing: 'focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500',
  linkColor: 'text-blue-600 hover:text-blue-700',
  checkboxColor: 'text-blue-600 focus:ring-blue-500',
  spinnerBorder: 'border-white border-t-transparent',
  headingStyle: 'simple',
};

export const AMBER_THEME: AuthFormTheme = {
  primaryBg: 'bg-amber-500 hover:bg-amber-400 focus:ring-2 focus:ring-amber-500 focus:ring-offset-2',
  primaryText: 'text-slate-900 font-bold',
  focusRing: 'focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500',
  linkColor: 'text-amber-600 hover:text-amber-700',
  checkboxColor: 'text-amber-600 focus:ring-amber-500',
  spinnerBorder: 'border-slate-900 border-t-transparent',
  headingStyle: 'with-subtitle',
};

/* -------------------------------------------------------------------------- */
/*  Props                                                                      */
/* -------------------------------------------------------------------------- */

export interface AuthFormProps {
  theme: AuthFormTheme;
  initialMode?: 'login' | 'register';
  /** Called when user clicks the Terms & Conditions link. */
  onShowTerms: () => void;
  /** Prefix for HTML id attributes to avoid collisions when multiple forms on page. */
  idPrefix?: string;
}

/* -------------------------------------------------------------------------- */
/*  Component                                                                  */
/* -------------------------------------------------------------------------- */

export function AuthForm({ theme, initialMode = 'login', onShowTerms, idPrefix = '' }: AuthFormProps) {
  const { login, register } = useAuth();

  // ── State ──────────────────────────────────────────────────────────────
  const [mode, setMode] = useState<'login' | 'register' | 'forgot' | 'reset'>(initialMode);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [acceptedTos, setAcceptedTos] = useState(false);
  const [loading, setLoading] = useState(false);
  const [forgotSent, setForgotSent] = useState(false);
  const [resetToken, setResetToken] = useState('');
  const [newPassword, setNewPassword] = useState('');

  // ── Derived ────────────────────────────────────────────────────────────
  const passwordStrength = useMemo(() => getPasswordStrength(password), [password]);
  const allRulesPassed = passwordStrength.score === PASSWORD_RULES.length;
  const newPasswordAllPassed = PASSWORD_RULES.every((r) => r.test(newPassword));

  const inputCls = `w-full rounded-lg border border-gray-300 px-3 py-2 text-sm ${theme.focusRing}`;

  // ── Handlers ───────────────────────────────────────────────────────────

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

  // ── Render helpers ─────────────────────────────────────────────────────

  function Spinner() {
    return <span className={`h-4 w-4 animate-spin rounded-full border-2 ${theme.spinnerBorder}`} />;
  }

  function PrimaryButton({ disabled, children }: { disabled?: boolean; children: React.ReactNode }) {
    return (
      <button
        type="submit"
        disabled={disabled}
        className={`flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium ${theme.primaryBg} ${theme.primaryText} disabled:opacity-50 disabled:cursor-not-allowed transition-colors`}
      >
        {children}
      </button>
    );
  }

  // ── Forgot Password ────────────────────────────────────────────────────

  if (mode === 'forgot') {
    return (
      <>
        <button
          onClick={() => { setMode('login'); setForgotSent(false); }}
          className="mb-4 flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft size={14} /> Back to sign in
        </button>

        <h2 className="mb-2 text-lg font-semibold text-gray-900">Forgot password?</h2>
        <p className="mb-6 text-sm text-gray-500">
          Enter your email and we&apos;ll send you instructions to reset your password.
        </p>

        {forgotSent ? (
          <div className="rounded-lg bg-green-50 border border-green-200 p-4 text-center">
            <Mail size={24} className="mx-auto mb-2 text-green-600" />
            <p className="text-sm font-medium text-green-800">Check your email</p>
            <p className="text-xs text-green-600 mt-1">
              If an account with that email exists, we&apos;ve sent reset instructions.
            </p>
            <button
              onClick={() => { setMode('reset'); setForgotSent(false); }}
              className={`mt-4 text-sm font-medium ${theme.linkColor}`}
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
                className={inputCls}
                placeholder="you@example.com"
              />
            </div>
            <PrimaryButton disabled={loading}>
              {loading ? <Spinner /> : <Mail size={16} />}
              Send Reset Link
            </PrimaryButton>
          </form>
        )}
      </>
    );
  }

  // ── Reset Password ─────────────────────────────────────────────────────

  if (mode === 'reset') {
    return (
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
              className={`${inputCls} font-mono`}
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
              className={inputCls}
              placeholder="Create a strong password"
            />
            {newPassword && <PasswordStrengthIndicator password={newPassword} />}
          </div>
          <PrimaryButton disabled={loading || !newPasswordAllPassed || !resetToken}>
            {loading && <Spinner />}
            Reset Password
          </PrimaryButton>
        </form>
      </>
    );
  }

  // ── Login / Register ───────────────────────────────────────────────────

  return (
    <>
      {theme.headingStyle === 'with-subtitle' ? (
        <>
          <h2 className="mb-1 text-xl font-bold text-gray-900">
            {mode === 'login' ? 'Welcome back' : 'Create an account'}
          </h2>
          <p className="mb-6 text-sm text-gray-500">
            {mode === 'login' ? 'Sign in to access your predictions' : 'Get started with HomeBuyer'}
          </p>
        </>
      ) : (
        <h2 className="mb-6 text-lg font-semibold text-gray-900">
          {mode === 'login' ? 'Sign in to your account' : 'Create an account'}
        </h2>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        {mode === 'register' && (
          <div>
            <label htmlFor={`${idPrefix}fullName`} className="mb-1 block text-sm font-medium text-gray-700">
              Full name
            </label>
            <input
              id={`${idPrefix}fullName`}
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className={inputCls}
              placeholder="John Doe"
            />
          </div>
        )}

        <div>
          <label htmlFor={`${idPrefix}email`} className="mb-1 block text-sm font-medium text-gray-700">
            Email address
          </label>
          <input
            id={`${idPrefix}email`}
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={inputCls}
            placeholder="you@example.com"
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label htmlFor={`${idPrefix}password`} className="block text-sm font-medium text-gray-700">
              Password
            </label>
            {mode === 'login' && (
              <button
                type="button"
                onClick={() => setMode('forgot')}
                className={`text-xs font-medium ${theme.linkColor}`}
              >
                Forgot password?
              </button>
            )}
          </div>
          <input
            id={`${idPrefix}password`}
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputCls}
            placeholder={mode === 'register' ? 'Create a strong password' : 'Enter your password'}
          />
          {mode === 'register' && password.length > 0 && (
            <PasswordStrengthIndicator password={password} />
          )}
        </div>

        {mode === 'register' && (
          <label className="flex items-start gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={acceptedTos}
              onChange={(e) => setAcceptedTos(e.target.checked)}
              className={`mt-0.5 h-4 w-4 rounded border-gray-300 ${theme.checkboxColor}`}
            />
            <span>
              I agree to the{' '}
              <button
                type="button"
                onClick={onShowTerms}
                className={`font-medium underline ${theme.linkColor}`}
              >
                Terms and Conditions
              </button>
            </span>
          </label>
        )}

        <PrimaryButton disabled={loading || (mode === 'register' && (!acceptedTos || !allRulesPassed))}>
          {loading ? (
            <Spinner />
          ) : mode === 'login' ? (
            <LogIn size={16} />
          ) : (
            <UserPlus size={16} />
          )}
          {mode === 'login' ? 'Sign In' : 'Create Account'}
        </PrimaryButton>
      </form>

      <GoogleOAuthButton />

      {/* Toggle mode */}
      <div className="mt-6 text-center text-sm text-gray-500">
        {mode === 'login' ? (
          <>
            Don&apos;t have an account?{' '}
            <button onClick={() => setMode('register')} className={`font-medium ${theme.linkColor}`}>
              Create one
            </button>
          </>
        ) : (
          <>
            Already have an account?{' '}
            <button onClick={() => setMode('login')} className={`font-medium ${theme.linkColor}`}>
              Sign in
            </button>
          </>
        )}
      </div>
    </>
  );
}
