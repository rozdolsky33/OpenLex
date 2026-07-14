import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LegalPage } from "./LegalPage";

describe("LegalPage", () => {
  it("renders the factual data-retention summary", () => {
    render(<LegalPage />);
    expect(screen.getByText(/bcrypt hash of your password/)).toBeInTheDocument();
    expect(screen.getByText(/no payment information is collected/)).toBeInTheDocument();
  });

  it("flags both the Terms of Service and Privacy Policy sections as pending attorney review", () => {
    render(<LegalPage />);
    expect(
      screen.getByRole("heading", { name: /Terms of Service — draft, pending attorney review/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /Privacy Policy — draft, pending attorney review/ }),
    ).toBeInTheDocument();
  });

  it("links back to the app", () => {
    render(<LegalPage />);
    expect(screen.getByRole("link", { name: /Back to OpenLex/ })).toHaveAttribute("href", "/");
  });
});
