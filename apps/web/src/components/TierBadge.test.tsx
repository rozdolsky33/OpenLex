import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TierBadge } from "./TierBadge";
import type { UserStatus } from "../api/types";

function makeUser(overrides: Partial<UserStatus> = {}): UserStatus {
  return {
    email: "steve@example.com",
    tier: "gold",
    request_count: 12,
    request_limit: 50,
    period_reset_at: "2026-07-12T18:00:00Z",
    ...overrides,
  };
}

describe("TierBadge", () => {
  it("shows the tier label and usage count", () => {
    render(<TierBadge user={makeUser()} />);
    expect(screen.getByText("Gold · 12/50")).toBeInTheDocument();
  });

  it("shows the reset time once the quota is exhausted", () => {
    render(<TierBadge user={makeUser({ request_count: 50 })} />);
    expect(screen.getByText(/Gold · 50\/50 · resets/)).toBeInTheDocument();
  });

  it("renders each tier's label correctly", () => {
    const { rerender } = render(<TierBadge user={makeUser({ tier: "silver", request_limit: 15, request_count: 3 })} />);
    expect(screen.getByText("Silver · 3/15")).toBeInTheDocument();

    rerender(<TierBadge user={makeUser({ tier: "platinum", request_limit: 100, request_count: 1 })} />);
    expect(screen.getByText("Platinum · 1/100")).toBeInTheDocument();
  });
});
