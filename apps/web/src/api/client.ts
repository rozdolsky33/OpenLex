import { ApiError } from "./errors";
import { getToken } from "./storage";

const BASE_URL = import.meta.env.VITE_API_BASE_URL;

type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

/** Registered once by AuthProvider so every call site doesn't need to duplicate
 * "on 401, log the user out" logic. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  unauthorizedHandler = handler;
}

interface RequestOptions {
  method?: string;
  body?: BodyInit;
  headers?: Record<string, string>;
  /** Attach the stored bearer token, if present. Defaults to true. */
  auth?: boolean;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, headers = {}, auth = true } = options;
  const finalHeaders: Record<string, string> = { ...headers };

  if (auth) {
    const token = getToken();
    if (token) {
      finalHeaders.Authorization = `Bearer ${token}`;
    }
  }

  // No `credentials: "include"` -- this app uses bearer-token auth, not cookies, so it
  // doesn't need (and shouldn't request) credentialed CORS mode.
  const response = await fetch(`${BASE_URL}${path}`, { method, body, headers: finalHeaders });

  if (!response.ok) {
    const parsedBody = await safeParseJson(response);

    if (response.status === 401 && unauthorizedHandler) {
      unauthorizedHandler();
    }

    const detail =
      parsedBody && typeof parsedBody === "object" && "detail" in parsedBody
        ? String((parsedBody as { detail: unknown }).detail)
        : undefined;

    throw new ApiError(response.status, detail ?? `Request failed with status ${response.status}`, parsedBody);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function requestJson<T>(
  path: string,
  method: string,
  body: unknown,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<T> {
  return request<T>(path, {
    ...options,
    method,
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
  });
}

async function safeParseJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}
