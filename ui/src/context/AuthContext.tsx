import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react';
import type { User } from '../types';
import {
  authLogin,
  authRegister,
  authGetMe,
  authLogout,
  authAcceptTos,
  getStoredToken,
  setStoredToken,
  setStoredRefreshToken,
  clearStoredToken,
  setOnAuthFailure,
} from '../lib/api';

interface AuthContextValue {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  tosUpdateRequired: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName?: string, tosVersion?: string) => Promise<void>;
  logout: () => void;
  acceptTos: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  tosUpdateRequired: false,
  login: async () => {},
  register: async () => {},
  logout: () => {},
  acceptTos: async () => {},
});

/**
 * Parse OAuth callback tokens from URL hash fragment.
 * After Google OAuth redirect, the URL looks like:
 *   /auth/callback#access_token=...&refresh_token=...
 */
function consumeOAuthTokensFromHash(): { access_token: string; refresh_token: string } | null {
  const hash = window.location.hash;
  if (!hash || !hash.includes('access_token')) return null;

  const params = new URLSearchParams(hash.slice(1));
  const access_token = params.get('access_token');
  const refresh_token = params.get('refresh_token');

  if (access_token && refresh_token) {
    // Clean up the URL (remove hash fragment)
    window.history.replaceState(null, '', window.location.pathname);
    return { access_token, refresh_token };
  }
  return null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [tosUpdateRequired, setTosUpdateRequired] = useState(false);

  const logout = useCallback(() => {
    authLogout();
    setUser(null);
    setTosUpdateRequired(false);
  }, []);

  // Register the auth failure callback so the API layer can force logout
  useEffect(() => {
    setOnAuthFailure(() => {
      setUser(null);
      setTosUpdateRequired(false);
    });
  }, []);

  // On mount, check for OAuth callback tokens OR existing stored token
  useEffect(() => {
    // Check if we're returning from OAuth
    const oauthTokens = consumeOAuthTokensFromHash();
    if (oauthTokens) {
      setStoredToken(oauthTokens.access_token);
      setStoredRefreshToken(oauthTokens.refresh_token);
    }

    const token = getStoredToken();
    if (!token) {
      setIsLoading(false);
      return;
    }

    authGetMe()
      .then((u) => setUser(u))
      .catch(() => {
        clearStoredToken();
      })
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const resp = await authLogin(email, password);
    setStoredToken(resp.access_token);
    setStoredRefreshToken(resp.refresh_token);
    setUser(resp.user);
    setTosUpdateRequired(resp.tos_update_required ?? false);
  }, []);

  const register = useCallback(
    async (email: string, password: string, fullName?: string, tosVersion?: string) => {
      const resp = await authRegister(email, password, fullName, tosVersion);
      setStoredToken(resp.access_token);
      setStoredRefreshToken(resp.refresh_token);
      setUser(resp.user);
      // Registration always accepts TOS, so no update needed
      setTosUpdateRequired(false);
    },
    [],
  );

  const acceptTos = useCallback(async () => {
    await authAcceptTos();
    setTosUpdateRequired(false);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: user !== null,
        isLoading,
        tosUpdateRequired,
        login,
        register,
        logout,
        acceptTos,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
