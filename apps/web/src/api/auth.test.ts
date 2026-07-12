import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getMe, loginUser, registerUser } from "./auth";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("loginUser", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // The single easiest contract detail to get wrong: FastAPI's OAuth2PasswordRequestForm
  // expects application/x-www-form-urlencoded with `username`/`password` fields, not JSON.
  it("sends form-encoded username/password, not JSON", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(200, { access_token: "t", token_type: "bearer" }),
    );

    await loginUser("tenant@example.com", "supersecret1");

    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.body).toBeInstanceOf(URLSearchParams);
    const body = init?.body as URLSearchParams;
    expect(body.get("username")).toBe("tenant@example.com");
    expect(body.get("password")).toBe("supersecret1");
  });
});

describe("registerUser", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends a JSON body with email/password", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(201, { id: "1", email: "tenant@example.com", created_at: "now" }),
    );

    await registerUser("tenant@example.com", "supersecret1");

    const [, init] = vi.mocked(fetch).mock.calls[0];
    const headers = init?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init?.body as string)).toEqual({
      email: "tenant@example.com",
      password: "supersecret1",
    });
  });
});

describe("getMe", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches /auth/me and returns the parsed tier/usage status", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(200, {
        email: "steve@example.com",
        tier: "gold",
        request_count: 12,
        request_limit: 50,
        period_reset_at: "2026-07-12T18:00:00Z",
      }),
    );

    const status = await getMe();

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/auth/me");
    expect(status.tier).toBe("gold");
    expect(status.request_count).toBe(12);
    expect(status.request_limit).toBe(50);
  });
});
