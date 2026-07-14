import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import { setupTelemetry } from "./telemetry.ts";
import "./index.css";

// Before rendering -- DocumentLoadInstrumentation needs to be registered before the page
// finishes loading to capture the root span.
setupTelemetry();

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("#root element not found in index.html");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
