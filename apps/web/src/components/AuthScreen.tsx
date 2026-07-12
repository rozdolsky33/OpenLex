import { CitySkyline } from "./CitySkyline";
import { LoginForm } from "./LoginForm";

// Registration is disabled for this demo (see apps/api/src/openlex_api/routers/auth.py) --
// only the three seeded tier users can log in, so there's no register toggle here.
// RegisterForm.tsx stays in the tree unrouted rather than deleted, matching the backend's
// disable-not-delete choice -- trivially reversible later.
export function AuthScreen() {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-950 px-4">
      <CitySkyline />
      {/* A soft spotlight behind the centered content, not a wall-to-wall scrim -- the
          skyline stays visible (and more visible near the edges) instead of being buried
          under a flat dark panel. */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 600px 500px at center, rgba(2,6,23,0.55), rgba(2,6,23,0.15) 55%, transparent 75%)",
        }}
      />

      <div className="relative z-10 w-full max-w-sm text-center">
        <h1 className="text-lg font-semibold text-white">OpenLex</h1>
        <p className="mx-auto mt-2 max-w-xs text-sm text-slate-300">
          NY landlord-tenant law, answered from the actual statutes and case law — with
          citations, every time.
        </p>

        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-6 text-left shadow-sm">
          <LoginForm />
        </div>
      </div>
    </div>
  );
}
