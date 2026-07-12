import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loginUser, registerUser } from "./auth";

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
