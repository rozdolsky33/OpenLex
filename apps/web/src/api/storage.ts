// Single source of truth for the two localStorage keys this app uses -- no magic strings
// duplicated at call sites. Referenced as `window.localStorage`, not the bare `localStorage`
// global -- Vitest's jsdom environment only reliably exposes browser globals reached via
// `window`, not ones inherited through the prototype chain onto the bare global scope.
const TOKEN_KEY = "openlex.token";
const CONVERSATION_ID_KEY = "openlex.conversation_id";

export function getToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export function getConversationId(): string | null {
  return window.localStorage.getItem(CONVERSATION_ID_KEY);
}

export function setConversationId(id: string): void {
  window.localStorage.setItem(CONVERSATION_ID_KEY, id);
}

export function clearConversationId(): void {
  window.localStorage.removeItem(CONVERSATION_ID_KEY);
}
