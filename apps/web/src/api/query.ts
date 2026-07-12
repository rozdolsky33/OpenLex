import { requestJson } from "./client";
import { ApiError } from "./errors";
import { clearConversationId, getConversationId, setConversationId } from "./storage";
import type { DocType, QueryRequest, QueryResponse } from "./types";

export async function postQuery(
  question: string,
  options: { docType?: DocType; topK?: number } = {},
): Promise<QueryResponse> {
  const body: QueryRequest = {
    question,
    doc_type: options.docType ?? null,
    top_k: options.topK ?? 8,
    conversation_id: getConversationId(),
  };

  try {
    const response = await requestJson<QueryResponse>("/query", "POST", body);
    if (response.conversation_id) {
      setConversationId(response.conversation_id);
    }
    return response;
  } catch (err) {
    // A 404 here means the stored conversation_id is unknown/malformed server-side --
    // collapsed into one status by the API (see apps/api/routers/query.py). Clear it so the
    // *next* request starts a fresh conversation instead of retrying the same bad id forever.
    if (err instanceof ApiError && err.status === 404) {
      clearConversationId();
    }
    throw err;
  }
}
