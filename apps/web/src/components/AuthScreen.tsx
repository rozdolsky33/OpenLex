import { useState } from "react";
import { LoginForm } from "./LoginForm";
import { RegisterForm } from "./RegisterForm";

export function AuthScreen() {
  const [mode, setMode] = useState<"login" | "register">("login");

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="mb-4 text-lg font-semibold text-slate-900">OpenLex</h1>
        <div className="mb-4 flex gap-2 text-sm">
          <button
            type="button"
            className={mode === "login" ? "font-semibold text-slate-900" : "text-slate-500"}
            onClick={() => setMode("login")}
          >
            Log in
          </button>
          <span className="text-slate-300">/</span>
          <button
            type="button"
            className={mode === "register" ? "font-semibold text-slate-900" : "text-slate-500"}
            onClick={() => setMode("register")}
          >
            Register
          </button>
        </div>
        {mode === "login" ? <LoginForm /> : <RegisterForm />}
      </div>
    </div>
  );
}
