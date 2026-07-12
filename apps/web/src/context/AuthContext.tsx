import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { loginUser, registerUser } from "../api/auth";
import { setUnauthorizedHandler } from "../api/client";
import { clearToken, getToken, setToken } from "../api/storage";

interface AuthContextValue {
  isAuthenticated: boolean;
  sessionExpired: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  dismissSessionExpired: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(() => getToken() !== null);
  const [sessionExpired, setSessionExpired] = useState(false);

  const logout = useCallback(() => {
    clearToken();
    setIsAuthenticated(false);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearToken();
      setIsAuthenticated(false);
      setSessionExpired(true);
    });
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const token = await loginUser(email, password);
    setToken(token.access_token);
    setIsAuthenticated(true);
    setSessionExpired(false);
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    await registerUser(email, password);
    await login(email, password);
  }, [login]);

  const dismissSessionExpired = useCallback(() => setSessionExpired(false), []);

  return (
    <AuthContext.Provider
      value={{ isAuthenticated, sessionExpired, login, register, logout, dismissSessionExpired }}
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
