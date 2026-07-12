import { useEffect, useReducer, useState } from "react";
import { postQuery } from "../api/query";
import { ApiError } from "../api/errors";
import { getConversationId } from "../api/storage";
import type { Citation, DocType } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { ChatInput } from "./ChatInput";
import { ConnectionStatus } from "./ConnectionStatus";
import { ErrorBanner } from "./ErrorBanner";
import { MessageList } from "./MessageList";

export interface DisplayMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  citations?: Citation[];
  abstained?: boolean;
  disclaimer?: string | null;
}

interface State {
  messages: DisplayMessage[];
  pending: boolean;
}

type Action =
  | { type: "add"; message: DisplayMessage }
  | { type: "pending" }
  | { type: "settled" };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "add":
      return { ...state, messages: [...state.messages, action.message] };
    case "pending":
      return { ...state, pending: true };
    case "settled":
      return { ...state, pending: false };
  }
}

let messageIdCounter = 0;
function nextMessageId(): string {
  messageIdCounter += 1;
  return `msg-${messageIdCounter}`;
}

// There is no GET /conversations/{id}/messages endpoint (see ADR-0003) -- resuming a stored
// conversation_id means the server still has the history for retrieval/reformulation
// purposes, but this client has no way to re-render it. Shown once as a system notice rather
// than silently starting an empty-looking chat with no explanation.
const RESUMED_CONVERSATION_NOTICE =
  "Continuing a previous conversation — earlier messages aren't available to display, " +
  "but the model still has that history server-side.";

export function ChatPage() {
  const { logout } = useAuth();
  const [state, dispatch] = useReducer(reducer, { messages: [], pending: false });
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [docType, setDocType] = useState<DocType | "">("");

  useEffect(() => {
    if (getConversationId()) {
      dispatch({
        type: "add",
        message: { id: nextMessageId(), role: "system", content: RESUMED_CONVERSATION_NOTICE },
      });
    }
  }, []);

  async function handleSubmit() {
    const trimmed = question.trim();
    if (!trimmed || state.pending) {
      return;
    }

    setError(null);
    dispatch({ type: "add", message: { id: nextMessageId(), role: "user", content: trimmed } });
    dispatch({ type: "pending" });

    try {
      const response = await postQuery(trimmed, { docType: docType || undefined });
      dispatch({
        type: "add",
        message: {
          id: nextMessageId(),
          role: "assistant",
          content: response.answer,
          citations: response.citations,
          abstained: response.abstained,
          disclaimer: response.disclaimer,
        },
      });
      setQuestion("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError(
          "Your saved conversation could not be found — starting fresh. Press send again to continue.",
        );
      } else if (err instanceof ApiError && err.status === 401) {
        // AuthContext's global unauthorized handler already logs the user out and shows the
        // session-expired banner -- nothing app-specific to add here.
      } else {
        setError("Something went wrong. Please try again.");
      }
      // Deliberately not clearing `question` on error -- leaves it in the input for a
      // one-click resend rather than silently retrying (which would risk a duplicate call).
    } finally {
      dispatch({ type: "settled" });
    }
  }

  return (
    <div className="flex h-screen flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <h1 className="text-sm font-semibold text-slate-900">OpenLex</h1>
        <div className="flex items-center gap-3">
          <ConnectionStatus />
          <button type="button" onClick={logout} className="text-xs text-slate-500 underline">
            Log out
          </button>
        </div>
      </header>
      <MessageList messages={state.messages} pending={state.pending} />
      {error && <ErrorBanner message={error} />}
      <ChatInput
        question={question}
        onQuestionChange={setQuestion}
        docType={docType}
        onDocTypeChange={setDocType}
        onSubmit={handleSubmit}
        disabled={state.pending}
      />
    </div>
  );
}
