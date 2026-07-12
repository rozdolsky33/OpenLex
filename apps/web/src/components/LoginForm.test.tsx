import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginForm } from "./LoginForm";
import { AuthProvider } from "../context/AuthContext";
import { ApiError } from "../api/errors";
import * as authApi from "../api/auth";

function renderLoginForm() {
  return render(
    <AuthProvider>
      <LoginForm />
    </AuthProvider>,
  );
}

describe("LoginForm", () => {
  it("submits the typed email/password", async () => {
    const loginSpy = vi
      .spyOn(authApi, "loginUser")
      .mockResolvedValue({ access_token: "t", token_type: "bearer" });
    // AuthContext's login() also fetches /auth/me right after a successful login to populate
    // tier/usage state -- mocked here so this test stays scoped to the form's own behavior.
    vi.spyOn(authApi, "getMe").mockResolvedValue({
      email: "tenant@example.com",
      tier: "silver",
      request_count: 0,
      request_limit: 15,
      period_reset_at: new Date().toISOString(),
    });
    const user = userEvent.setup();
    renderLoginForm();

    await user.type(screen.getByLabelText("Email"), "tenant@example.com");
    await user.type(screen.getByLabelText("Password"), "supersecret1");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() => {
      expect(loginSpy).toHaveBeenCalledWith("tenant@example.com", "supersecret1");
    });
  });

  it("shows an inline error on 401 instead of crashing", async () => {
    vi.spyOn(authApi, "loginUser").mockRejectedValue(new ApiError(401, "Incorrect email or password"));
    const user = userEvent.setup();
    renderLoginForm();

    await user.type(screen.getByLabelText("Email"), "tenant@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
  });
});
