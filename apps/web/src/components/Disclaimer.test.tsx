import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Disclaimer } from "./Disclaimer";

describe("Disclaimer", () => {
  it("renders the disclaimer text from the API response", () => {
    render(<Disclaimer disclaimer="Custom disclaimer from the server." />);
    expect(screen.getByText("Custom disclaimer from the server.")).toBeInTheDocument();
  });

  it("falls back to the hardcoded disclaimer when none is provided", () => {
    render(<Disclaimer disclaimer={null} />);
    expect(screen.getByText(/general legal information about New York/)).toBeInTheDocument();
  });
});
