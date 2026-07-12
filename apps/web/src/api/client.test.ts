import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { request, setUnauthorizedHandler } from "./client";
import { ApiError } from "./errors";
import { clearToken, setToken } from "./storage";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("request", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    clearToken();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setUnauthorizedHandler(() => {});
  });

  it("attaches the Authorization header when a token is stored", async () => {
    setToken("test-token");
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, { ok: true }));

    await request("/query");

    const [, init] = vi.mocked(fetch).mock.calls[0];
    const headers = init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
  });

  it("omits the Authorization header when no token is stored", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, { ok: true }));

    await request("/healthz", { auth: false });

    const [, init] = vi.mocked(fetch).mock.calls[0];
    const headers = init?.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("throws ApiError with the response status on a non-2xx response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(422, { detail: "bad request" }));

    await expect(request("/query")).rejects.toMatchObject({
      status: 422,
      message: "bad request",
    });
  });

  it("throws an instance of ApiError specifically", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(500, {}));

    await expect(request("/query")).rejects.toBeInstanceOf(ApiError);
  });

  it("fires the registered unauthorized handler on a 401", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.mocked(fetch).mockResolvedValue(jsonResponse(401, { detail: "nope" }));

    await expect(request("/query")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledOnce();
  });
});
