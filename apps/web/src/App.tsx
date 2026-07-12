import { AuthGate } from "./components/AuthGate";
import { ChatPage } from "./components/ChatPage";
import { AuthProvider } from "./context/AuthContext";

function App() {
  return (
    <AuthProvider>
      <AuthGate>
        <ChatPage />
      </AuthGate>
    </AuthProvider>
  );
}

export default App;
