import { LoginForm } from "./LoginForm";

// Registration is disabled for this demo (see apps/api/src/openlex_api/routers/auth.py) --
// only the three seeded tier users can log in, so there's no register toggle here.
// RegisterForm.tsx stays in the tree unrouted rather than deleted, matching the backend's
// disable-not-delete choice -- trivially reversible later.
export function AuthScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="mb-4 text-lg font-semibold text-slate-900">OpenLex</h1>
        <LoginForm />
      </div>
    </div>
  );
}
