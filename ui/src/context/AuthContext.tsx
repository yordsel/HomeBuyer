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

  // On mount, check for existing token and validate it
  useEffect(() => {
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
