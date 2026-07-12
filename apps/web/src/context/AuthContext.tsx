import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { getMe, loginUser, registerUser } from "../api/auth";
import { setUnauthorizedHandler } from "../api/client";
import type { UserStatus } from "../api/types";
import { clearConversationId, clearToken, getToken, setToken } from "../api/storage";

interface AuthContextValue {
  isAuthenticated: boolean;
  sessionExpired: boolean;
  user: UserStatus | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  dismissSessionExpired: () => void;
  refreshUsage: (usage: UserStatus) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(() => getToken() !== null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [user, setUser] = useState<UserStatus | null>(null);

  const logout = useCallback(() => {
    clearToken();
    // Also drop any stored conversation_id: without this, logging in as a different demo
    // user (Bob/Steve/Jennifer share one browser during a tier demo) would silently resume
    // the previous user's conversation, and every fresh login would land on the bottom-pinned
    // "continuing a previous conversation" view instead of the centered landing screen.
    clearConversationId();
    setIsAuthenticated(false);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearToken();
      clearConversationId();
      setIsAuthenticated(false);
      setUser(null);
      setSessionExpired(true);
    });
  }, []);

  // Covers a page refresh with an already-stored token: there's no in-memory user yet, so
  // fetch it once on mount. A 401 here (expired/invalid token) is handled by the
  // unauthorizedHandler registered above -- no separate error handling needed.
  useEffect(() => {
    if (isAuthenticated) {
      getMe().then(setUser).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const token = await loginUser(email, password);
    setToken(token.access_token);
    setIsAuthenticated(true);
    setSessionExpired(false);
    setUser(await getMe());
  }, []);

  const register = useCallback(
    async (email: string, password: string) => {
      await registerUser(email, password);
      await login(email, password);
    },
    [login],
  );

  const dismissSessionExpired = useCallback(() => setSessionExpired(false), []);

  const refreshUsage = useCallback((usage: UserStatus) => setUser(usage), []);

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated,
        sessionExpired,
        user,
        login,
        register,
        logout,
        dismissSessionExpired,
        refreshUsage,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
