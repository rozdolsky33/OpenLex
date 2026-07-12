import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { postQuery } from "./query";
import { clearConversationId, getConversationId, setConversationId } from "./storage";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("postQuery", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    clearConversationId();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the request body matching QueryRequest, including the stored conversation_id", async () => {
    setConversationId("existing-conversation");
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(200, {
        answer: "A tenant is...",
        citations: [],
        abstained: false,
        disclaimer: "disclaimer text",
        conversation_id: "existing-conversation",
      }),
    );

    await postQuery("What is a tenant?", { docType: "statute", topK: 5 });

    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect(JSON.parse(init?.body as string)).toEqual({
      question: "What is a tenant?",
      doc_type: "statute",
      top_k: 5,
      conversation_id: "existing-conversation",
    });
  });

  it("stores the returned conversation_id", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(200, {
        answer: "A tenant is...",
        citations: [],
        abstained: false,
        disclaimer: "disclaimer text",
        conversation_id: "new-conversation",
      }),
    );

    await postQuery("What is a tenant?");

    expect(getConversationId()).toBe("new-conversation");
  });

  it("clears the stored conversation_id when the server returns 404", async () => {
    setConversationId("stale-conversation");
    vi.mocked(fetch).mockResolvedValue(jsonResponse(404, { detail: "Conversation not found" }));

    await expect(postQuery("What about pets?")).rejects.toMatchObject({ status: 404 });
    expect(getConversationId()).toBeNull();
  });
});
