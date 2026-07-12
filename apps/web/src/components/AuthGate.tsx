import type { ReactNode } from "react";
import { useAuth } from "../context/AuthContext";
import { AuthScreen } from "./AuthScreen";

export function AuthGate({ children }: { children: ReactNode }) {
  const { isAuthenticated, sessionExpired, dismissSessionExpired } = useAuth();

  if (!isAuthenticated) {
    return (
      <div>
        {sessionExpired && (
          <div className="bg-amber-50 px-4 py-2 text-center text-sm text-amber-800">
            Session expired — please log in again.{" "}
            <button
              type="button"
              className="underline"
              onClick={dismissSessionExpired}
            >
              Dismiss
            </button>
          </div>
        )}
        <AuthScreen />
      </div>
    );
  }

  return <>{children}</>;
}
