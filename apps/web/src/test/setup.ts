import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// @testing-library/react's own auto-cleanup only self-registers when `afterEach` is a
// vitest *global* -- this project deliberately sets `globals: false` (vite.config.ts) so
// test files import vitest's API explicitly, so cleanup has to be wired up explicitly too.
afterEach(cleanup);

// Newer Node versions (22+) ship an experimental native Web Storage global that shadows
// jsdom's own `window.localStorage` inside Vitest's jsdom environment, leaving it present
// but non-functional unless Node is started with --localstorage-file (a flag CI's pinned
// Node 20 doesn't even recognize, so it can't just be added to the committed `test` script).
// Give the test environment a real, working Storage-shaped implementation instead of
// depending on that interaction being fixed upstream -- this never runs in an actual
// browser, where window.localStorage is always the genuine implementation.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

Object.defineProperty(window, "localStorage", {
  value: new MemoryStorage(),
  configurable: true,
});
