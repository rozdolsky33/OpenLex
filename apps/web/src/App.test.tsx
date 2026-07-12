import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";

describe("App", () => {
  it("renders the auth screen when no session token is stored", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "OpenLex" })).toBeInTheDocument();
  });
});
