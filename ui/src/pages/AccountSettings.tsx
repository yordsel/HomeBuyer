import { useState, useEffect, useMemo } from 'react';
import { toast } from 'sonner';
import {
  Shield,
  Key,
  Activity,
  Trash2,
  AlertTriangle,
  Check,
  X,
  Monitor,
  LogIn,
  LogOut,
  UserX,
  KeyRound,
  Eye,
  EyeOff,
  Link2,
  Unlink,
  Smartphone,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import {
  authChangePassword,
  authGetActivity,
  authDeactivateAccount,
  authDeleteAccount,
  authGetLinkedAccounts,
  authUnlinkAccount,
  authGoogleAuthorize,
  authGetSessions,
  authRevokeSession,
  authRevokeAllOtherSessions,
} from '../lib/api';
import type { AuthActivityEvent, LinkedOAuthAccount, SessionInfo } from '../types';

// Mirror backend password rules
const PASSWORD_RULES = [
  { label: 'At least 8 characters', test: (pw: string) => pw.length >= 8 },
  { label: 'One uppercase letter', test: (pw: string) => /[A-Z]/.test(pw) },
  { label: 'One lowercase letter', test: (pw: string) => /[a-z]/.test(pw) },
  { label: 'One digit', test: (pw: string) => /\d/.test(pw) },
  { label: 'One special character', test: (pw: string) => /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?`~]/.test(pw) },
];

function getPasswordStrength(pw: string): { score: number; label: string; color: string } {
  const passed = PASSWORD_RULES.filter((r) => r.test(pw)).length;
  if (passed <= 2) return { score: passed, label: 'Weak', color: 'bg-red-500' };
  if (passed <= 3) return { score: passed, label: 'Fair', color: 'bg-yellow-500' };
  if (passed <= 4) return { score: passed, label: 'Good', color: 'bg-blue-500' };
  return { score: passed, label: 'Strong', color: 'bg-green-500' };
}

const EVENT_ICONS: Record<string, typeof LogIn> = {
  login_success: LogIn,
  login_failure: AlertTriangle,
  logout: LogOut,
  register: LogIn,
  password_change: Key,
  account_deactivate: UserX,
  account_delete: Trash2,
  password_reset_request: KeyRound,
  password_reset_complete: KeyRound,
  email_verified: Check,
  verification_resend: Monitor,
};

const EVENT_LABELS: Record<string, string> = {
  login_success: 'Login',
  login_failure: 'Failed login attempt',
  logout: 'Logout',
  register: 'Account created',
  password_change: 'Password changed',
  account_deactivate: 'Account deactivated',
  account_delete: 'Account deleted',
  password_reset_request: 'Password reset requested',
  password_reset_complete: 'Password reset completed',
  email_verified: 'Email verified',
  verification_resend: 'Verification resent',
};

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr + 'Z'); // assume UTC
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'Just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

function parseBrowserFromUA(ua: string | null): string {
  if (!ua) return 'Unknown';
  if (ua.includes('Chrome') && !ua.includes('Edg')) return 'Chrome';
  if (ua.includes('Edg')) return 'Edge';
  if (ua.includes('Firefox')) return 'Firefox';
  if (ua.includes('Safari') && !ua.includes('Chrome')) return 'Safari';
  return 'Other';
}

// ---------------------------------------------------------------------------
// Change Password Section
// ---------------------------------------------------------------------------

function ChangePasswordSection() {
  const { logout } = useAuth();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);

  const strength = useMemo(() => (newPassword ? getPasswordStrength(newPassword) : null), [newPassword]);
  const allRulesPassed = PASSWORD_RULES.every((r) => r.test(newPassword));
  const passwordsMatch = newPassword === confirmPassword;
  const canSubmit = currentPassword && allRulesPassed && passwordsMatch && !loading;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setLoading(true);
    try {
      await authChangePassword(currentPassword, newPassword);
      toast.success('Password changed. Please sign in again.');
      // Force re-login since all refresh tokens are revoked
      setTimeout(() => logout(), 1500);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to change password';
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50">
          <Key size={18} className="text-blue-600" />
        </div>
        <div>
          <h3 className="text-base font-semibold text-gray-900">Change Password</h3>
          <p className="text-xs text-gray-500">You'll be signed out after changing your password</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Current password</label>
          <div className="relative">
            <input
              type={showCurrent ? 'text' : 'password'}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
            <button
              type="button"
              onClick={() => setShowCurrent((v) => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              {showCurrent ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">New password</label>
          <div className="relative">
            <input
              type={showNew ? 'text' : 'password'}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
            <button
              type="button"
              onClick={() => setShowNew((v) => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              {showNew ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>

          {/* Strength bar */}
          {newPassword && strength && (
            <div className="mt-2">
              <div className="flex items-center gap-2 mb-1.5">
                <div className="h-1.5 flex-1 rounded-full bg-gray-200 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${strength.color}`}
                    style={{ width: `${(strength.score / PASSWORD_RULES.length) * 100}%` }}
                  />
                </div>
                <span className="text-xs font-medium text-gray-500">{strength.label}</span>
              </div>
              <div className="space-y-0.5">
                {PASSWORD_RULES.map((rule) => {
                  const ok = rule.test(newPassword);
                  return (
                    <div key={rule.label} className="flex items-center gap-1.5">
                      {ok ? (
                        <Check size={12} className="text-green-500" />
                      ) : (
                        <X size={12} className="text-gray-300" />
                      )}
                      <span className={`text-xs ${ok ? 'text-green-600' : 'text-gray-400'}`}>
                        {rule.label}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Confirm new password</label>
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
          {confirmPassword && !passwordsMatch && (
            <p className="mt-1 text-xs text-red-500">Passwords do not match</p>
          )}
        </div>

        <button
          type="submit"
          disabled={!canSubmit}
          className="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {loading ? 'Changing...' : 'Change Password'}
        </button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Activity Log Section
// ---------------------------------------------------------------------------

function ActivityLogSection() {
  const [events, setEvents] = useState<AuthActivityEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    authGetActivity(20)
      .then(setEvents)
      .catch(() => toast.error('Failed to load activity'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-purple-50">
          <Activity size={18} className="text-purple-600" />
        </div>
        <div>
          <h3 className="text-base font-semibold text-gray-900">Recent Activity</h3>
          <p className="text-xs text-gray-500">Login history and security events</p>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-8">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-purple-600 border-t-transparent" />
        </div>
      ) : events.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-6">No activity recorded yet</p>
      ) : (
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {events.map((ev) => {
            const Icon = EVENT_ICONS[ev.event_type] || Monitor;
            const label = EVENT_LABELS[ev.event_type] || ev.event_type;
            const isFailed = !ev.success;
            return (
              <div
                key={ev.id}
                className={`flex items-start gap-3 rounded-lg px-3 py-2.5 ${
                  isFailed ? 'bg-red-50' : 'bg-gray-50'
                }`}
              >
                <div className={`mt-0.5 ${isFailed ? 'text-red-500' : 'text-gray-400'}`}>
                  <Icon size={16} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <p className={`text-sm font-medium ${isFailed ? 'text-red-700' : 'text-gray-700'}`}>
                      {label}
                    </p>
                    <span className="text-xs text-gray-400 shrink-0 ml-2">
                      {formatRelativeTime(ev.created_at)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    {ev.ip_address && (
                      <span className="text-xs text-gray-400">{ev.ip_address}</span>
                    )}
                    {ev.user_agent && (
                      <span className="text-xs text-gray-400">
                        {parseBrowserFromUA(ev.user_agent)}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Linked Accounts Section
// ---------------------------------------------------------------------------

function LinkedAccountsSection() {
  const [accounts, setAccounts] = useState<LinkedOAuthAccount[]>([]);
  const [hasPassword, setHasPassword] = useState(true);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    authGetLinkedAccounts()
      .then((data) => {
        setAccounts(data.accounts);
        setHasPassword(data.has_password);
      })
      .catch(() => toast.error('Failed to load linked accounts'))
      .finally(() => setLoading(false));
  }, []);

  async function handleUnlink(provider: string) {
    try {
      await authUnlinkAccount(provider);
      setAccounts((prev) => prev.filter((a) => a.provider !== provider));
      toast.success(`${provider} account unlinked`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to unlink');
    }
  }

  async function handleLinkGoogle() {
    try {
      const { authorization_url } = await authGoogleAuthorize();
      window.location.href = authorization_url;
    } catch {
      toast.error('Google sign-in is not configured');
    }
  }

  const googleLinked = accounts.some((a) => a.provider === 'google');

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-green-50">
          <Link2 size={18} className="text-green-600" />
        </div>
        <div>
          <h3 className="text-base font-semibold text-gray-900">Linked Accounts</h3>
          <p className="text-xs text-gray-500">Sign in with external providers</p>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-6">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-green-600 border-t-transparent" />
        </div>
      ) : (
        <div className="space-y-3">
          {/* Google */}
          <div className="flex items-center justify-between rounded-lg border border-gray-200 p-4">
            <div className="flex items-center gap-3">
              <svg className="h-5 w-5" viewBox="0 0 24 24">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
              </svg>
              <div>
                <p className="text-sm font-medium text-gray-700">Google</p>
                {googleLinked && (
                  <p className="text-xs text-gray-400">
                    {accounts.find((a) => a.provider === 'google')?.email ?? 'Connected'}
                  </p>
                )}
              </div>
            </div>

            {googleLinked ? (
              <button
                onClick={() => handleUnlink('google')}
                disabled={!hasPassword}
                title={!hasPassword ? 'Set a password before unlinking' : 'Unlink Google account'}
                className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <Unlink size={14} />
                Unlink
              </button>
            ) : (
              <button
                onClick={handleLinkGoogle}
                className="flex items-center gap-1.5 rounded-lg border border-blue-300 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
              >
                <Link2 size={14} />
                Link
              </button>
            )}
          </div>

          {!hasPassword && (
            <p className="text-xs text-amber-600 bg-amber-50 rounded-lg px-3 py-2">
              Your account uses OAuth only. Set a password in the section above before unlinking providers.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Active Sessions Section
// ---------------------------------------------------------------------------

function ActiveSessionsSection() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    authGetSessions()
      .then(setSessions)
      .catch(() => toast.error('Failed to load sessions'))
      .finally(() => setLoading(false));
  }, []);

  async function handleRevoke(sessionId: number) {
    try {
      await authRevokeSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      toast.success('Session revoked');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to revoke session');
    }
  }

  async function handleRevokeAll() {
    try {
      const result = await authRevokeAllOtherSessions();
      toast.success(result.detail);
      // Refresh session list
      const updated = await authGetSessions();
      setSessions(updated);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to revoke sessions');
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50">
            <Smartphone size={18} className="text-indigo-600" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-gray-900">Active Sessions</h3>
            <p className="text-xs text-gray-500">Devices where you're signed in</p>
          </div>
        </div>
        {sessions.length > 1 && (
          <button
            onClick={handleRevokeAll}
            className="text-xs font-medium text-red-600 hover:text-red-700"
          >
            Sign out all others
          </button>
        )}
      </div>

      {loading ? (
        <div className="flex justify-center py-6">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
        </div>
      ) : sessions.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-6">No active sessions</p>
      ) : (
        <div className="space-y-2">
          {sessions.map((s, idx) => (
            <div
              key={s.id}
              className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2.5"
            >
              <div className="flex items-center gap-3">
                <Monitor size={16} className="text-gray-400" />
                <div>
                  <p className="text-sm font-medium text-gray-700">
                    {s.user_agent ? parseBrowserFromUA(s.user_agent) : 'Unknown browser'}
                    {idx === 0 && (
                      <span className="ml-2 inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-medium text-green-700">
                        Current
                      </span>
                    )}
                  </p>
                  <div className="flex items-center gap-2 text-xs text-gray-400">
                    {s.ip_address && <span>{s.ip_address}</span>}
                    <span>{formatRelativeTime(s.created_at)}</span>
                  </div>
                </div>
              </div>
              {idx !== 0 && (
                <button
                  onClick={() => handleRevoke(s.id)}
                  className="text-xs font-medium text-red-600 hover:text-red-700"
                >
                  Revoke
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Danger Zone (Deactivate / Delete)
// ---------------------------------------------------------------------------

function DangerZoneSection() {
  const { logout } = useAuth();
  const [action, setAction] = useState<'deactivate' | 'delete' | null>(null);
  const [password, setPassword] = useState('');
  const [confirmText, setConfirmText] = useState('');
  const [loading, setLoading] = useState(false);

  const canDelete = action === 'delete' && confirmText === 'DELETE' && password.length > 0;
  const canDeactivate = action === 'deactivate' && password.length > 0;

  async function handleAction() {
    if (!action) return;
    setLoading(true);
    try {
      if (action === 'deactivate') {
        await authDeactivateAccount(password);
        toast.success('Account deactivated');
      } else {
        await authDeleteAccount(password);
        toast.success('Account permanently deleted');
      }
      setTimeout(() => logout(), 1000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Operation failed';
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-xl border border-red-200 bg-white p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-red-50">
          <AlertTriangle size={18} className="text-red-600" />
        </div>
        <div>
          <h3 className="text-base font-semibold text-red-900">Danger Zone</h3>
          <p className="text-xs text-gray-500">These actions cannot be easily undone</p>
        </div>
      </div>

      {!action ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between rounded-lg border border-gray-200 p-4">
            <div>
              <p className="text-sm font-medium text-gray-700">Deactivate account</p>
              <p className="text-xs text-gray-400">Temporarily disable your account. You can contact us to reactivate.</p>
            </div>
            <button
              onClick={() => setAction('deactivate')}
              className="shrink-0 rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 transition-colors"
            >
              Deactivate
            </button>
          </div>
          <div className="flex items-center justify-between rounded-lg border border-red-200 p-4 bg-red-50/30">
            <div>
              <p className="text-sm font-medium text-red-700">Delete account</p>
              <p className="text-xs text-gray-400">Permanently delete your account, conversations, and all data.</p>
            </div>
            <button
              onClick={() => setAction('delete')}
              className="shrink-0 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 transition-colors"
            >
              Delete
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg bg-red-50 border border-red-200 p-4">
            <p className="text-sm font-medium text-red-800">
              {action === 'deactivate'
                ? 'Are you sure you want to deactivate your account?'
                : 'This will permanently delete your account and ALL data.'}
            </p>
            {action === 'delete' && (
              <p className="text-xs text-red-600 mt-1">
                This includes all conversations, predictions, and activity history. This action is irreversible.
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Enter your password to confirm
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-red-500 focus:ring-1 focus:ring-red-500"
            />
          </div>

          {action === 'delete' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Type <span className="font-mono font-bold">DELETE</span> to confirm
              </label>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder="DELETE"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-red-500 focus:ring-1 focus:ring-red-500"
              />
            </div>
          )}

          <div className="flex gap-3">
            <button
              onClick={() => {
                setAction(null);
                setPassword('');
                setConfirmText('');
              }}
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleAction}
              disabled={loading || (action === 'delete' ? !canDelete : !canDeactivate)}
              className="flex-1 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
            >
              {loading
                ? 'Processing...'
                : action === 'deactivate'
                  ? 'Deactivate Account'
                  : 'Permanently Delete'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export function AccountSettingsPage() {
  const { user } = useAuth();

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-6">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-100">
            <Shield size={20} className="text-blue-700" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Account Settings</h1>
            <p className="text-sm text-gray-500">{user?.email}</p>
          </div>
        </div>
      </div>

      <div className="space-y-6">
        <ChangePasswordSection />
        <LinkedAccountsSection />
        <ActiveSessionsSection />
        <ActivityLogSection />
        <DangerZoneSection />
      </div>
    </div>
  );
}
