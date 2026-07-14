import { useEffect, useReducer, useState } from "react";
import { postQuery } from "../api/query";
import { ApiError } from "../api/errors";
import { clearConversationId, getConversationId } from "../api/storage";
import type { Citation, DocType } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { ChatInput } from "./ChatInput";
import { ConnectionStatus } from "./ConnectionStatus";
import { ErrorBanner } from "./ErrorBanner";
import { MessageBubble } from "./MessageBubble";
import { MessageList } from "./MessageList";
import { TierBadge } from "./TierBadge";

interface QuotaExceededDetail {
  error: "quota_exceeded";
  tier: string;
  limit: number;
  reset_at: string;
}

function formatQuotaExceededMessage(detail: QuotaExceededDetail): string {
  const resetTime = new Date(detail.reset_at).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  const tierLabel = detail.tier.charAt(0).toUpperCase() + detail.tier.slice(1);
  return `You've reached your ${tierLabel} tier limit (${detail.limit}/${detail.limit} requests). Resets at ${resetTime}.`;
}

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
  | { type: "settled" }
  | { type: "reset" };

const INITIAL_STATE: State = { messages: [], pending: false };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "add":
      return { ...state, messages: [...state.messages, action.message] };
    case "pending":
      return { ...state, pending: true };
    case "settled":
      return { ...state, pending: false };
    case "reset":
      return INITIAL_STATE;
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

const EXAMPLE_QUESTIONS = [
  "How much notice before a landlord can start eviction?",
  "What is the warranty of habitability?",
  "Can my landlord withhold my security deposit?",
];

export function ChatPage() {
  const { logout, user, refreshUsage } = useAuth();
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [docType, setDocType] = useState<DocType | "">("");

  function handleNewChat() {
    clearConversationId();
    dispatch({ type: "reset" });
    setError(null);
    setQuestion("");
  }

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
      if (response.usage) {
        refreshUsage(response.usage);
      }
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
      } else if (err instanceof ApiError && err.status === 429) {
        const detail = err.body as { detail?: QuotaExceededDetail } | undefined;
        if (detail?.detail) {
          setError(formatQuotaExceededMessage(detail.detail));
          if (user) {
            refreshUsage({
              ...user,
              tier: detail.detail.tier as typeof user.tier,
              request_count: detail.detail.limit,
              request_limit: detail.detail.limit,
              period_reset_at: detail.detail.reset_at,
            });
          }
        } else {
          setError("You've reached your request limit. Please try again later.");
        }
      } else {
        setError("Something went wrong. Please try again.");
      }
      // Deliberately not clearing `question` on error -- leaves it in the input for a
      // one-click resend rather than silently retrying (which would risk a duplicate call).
    } finally {
      dispatch({ type: "settled" });
    }
  }

  // A resumed conversation_id injects a system notice on mount (see the effect above) --
  // that alone shouldn't switch to the bottom-pinned transcript layout with mostly empty
  // space above it. Only an actual user/assistant exchange should.
  const hasConversation = state.messages.some((message) => message.role !== "system");
  const systemNotices = state.messages.filter((message) => message.role === "system");

  return (
    <div className="flex h-screen flex-col bg-gradient-to-b from-white to-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200/80 bg-white/80 px-4 py-3 backdrop-blur-sm">
        <h1 className="text-sm font-semibold text-slate-900">OpenLex</h1>
        <div className="flex items-center gap-3">
          <ConnectionStatus />
          {user && <TierBadge user={user} />}
          {hasConversation && (
            <button
              type="button"
              onClick={handleNewChat}
              className="rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"
            >
              New chat
            </button>
          )}
          <a href="/legal" className="text-xs text-slate-500 underline">
            Privacy &amp; Terms
          </a>
          <button type="button" onClick={logout} className="text-xs text-slate-500 underline">
            Log out
          </button>
        </div>
      </header>

      {hasConversation ? (
        <>
          <MessageList messages={state.messages} pending={state.pending} />
          {error && <ErrorBanner message={error} />}
          <div className="border-t border-slate-200 bg-white px-4 py-3">
            <div className="mx-auto w-full max-w-3xl">
              <ChatInput
                question={question}
                onQuestionChange={setQuestion}
                docType={docType}
                onDocTypeChange={setDocType}
                onSubmit={handleSubmit}
                disabled={state.pending}
              />
            </div>
          </div>
        </>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center px-4 pb-24">
          <div className="w-full max-w-2xl text-center">
            {systemNotices.length > 0 && (
              <div className="mb-6 flex flex-col gap-2">
                {systemNotices.map((notice) => (
                  <MessageBubble key={notice.id} message={notice} />
                ))}
              </div>
            )}
            <h2 className="text-2xl font-semibold text-balance text-slate-900">
              What do you need to know about NY landlord-tenant law?
            </h2>
            <p className="mt-2 text-sm text-slate-500">
              Answers are grounded in retrieved statutes and case law, with citations — this is
              legal information, not legal advice.
            </p>
            <div className="mt-6">
              <ChatInput
                question={question}
                onQuestionChange={setQuestion}
                docType={docType}
                onDocTypeChange={setDocType}
                onSubmit={handleSubmit}
                disabled={state.pending}
              />
            </div>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {EXAMPLE_QUESTIONS.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => setQuestion(example)}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"
                >
                  {example}
                </button>
              ))}
            </div>
            {error && (
              <div className="mt-4 overflow-hidden rounded-lg">
                <ErrorBanner message={error} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
