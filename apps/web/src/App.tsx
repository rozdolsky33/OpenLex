import { AuthGate } from "./components/AuthGate";
import { ChatPage } from "./components/ChatPage";
import { LegalPage } from "./components/LegalPage";
import { AuthProvider } from "./context/AuthContext";

function App() {
  // No router dependency for a single other route -- ToS/Privacy must be reachable without
  // being logged in, so it's checked before AuthProvider/AuthGate, not nested inside them.
  if (window.location.pathname.startsWith("/legal")) {
    return <LegalPage />;
  }

  return (
    <AuthProvider>
      <AuthGate>
        <ChatPage />
      </AuthGate>
    </AuthProvider>
  );
}

export default App;
