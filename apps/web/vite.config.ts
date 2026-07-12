import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Single config file for both Vite and Vitest (defineConfig from "vitest/config" re-exports
// Vite's own defineConfig typed with an extra `test` key) -- avoids a second
// vitest.config.ts + mergeConfig for a project this size.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // docker-compose.yml maps 5173:5173 into this container -- Vite's default of binding
    // only 127.0.0.1 wouldn't be reachable from the host through that port mapping.
    host: "0.0.0.0",
    port: 5173,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    // Explicit `import { describe, it, expect } from "vitest"` in every test file instead of
    // injected globals -- avoids needing extra ESLint/tsconfig global-typing config for a
    // POC-sized test suite.
    globals: false,
  },
});
