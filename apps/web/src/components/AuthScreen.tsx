import { CitySkyline } from "./CitySkyline";
import { LoginForm } from "./LoginForm";

const FEATURES = [
  "Grounded answers with real citations, never invented",
  "Abstains rather than guessing when the sources fall short",
  "Legal information, not legal advice",
];

// Registration is disabled for this demo (see apps/api/src/openlex_api/routers/auth.py) --
// only the three seeded tier users can log in, so there's no register toggle here.
// RegisterForm.tsx stays in the tree unrouted rather than deleted, matching the backend's
// disable-not-delete choice -- trivially reversible later.
export function AuthScreen() {
  return (
    <div className="flex min-h-screen bg-slate-50">
      {/* Brand panel -- hidden below md, the login form stands alone on mobile. Only one
          <h1>"OpenLex"</h1> exists page-wide (in the form panel) so getByRole("heading")
          lookups stay unambiguous; the wordmark here is decorative, not a heading. */}
      <div className="relative hidden w-1/2 overflow-hidden bg-slate-900 md:flex md:flex-col md:justify-between">
        <CitySkyline />
        {/* Scrim behind the tagline/features block only -- the sky gradient inside
            CitySkyline already keeps the top (logo) readable on its own. */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-2/3 bg-gradient-to-t from-slate-950/95 via-slate-950/50 to-transparent" />

        <div className="relative z-10 p-10">
          <span className="text-sm font-semibold tracking-wide text-white">OpenLex</span>
        </div>

        <div className="relative z-10 p-10 pb-16">
          <p className="text-2xl font-semibold text-balance text-white">
            NY landlord-tenant law, answered from the actual statutes and case law.
          </p>
          <p className="mt-3 max-w-sm text-sm text-slate-300">
            Ask a question and get an answer built only from retrieved RPAPL, RPL, and GOL
            sections plus Court of Appeals case law — with citations, every time.
          </p>
          <ul className="mt-6 flex flex-col gap-2">
            {FEATURES.map((feature) => (
              <li key={feature} className="flex items-start gap-2 text-sm text-slate-300">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-amber-400" />
                {feature}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Form panel */}
      <div className="flex w-full flex-col items-center justify-center px-4 md:w-1/2">
        <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="mb-4 text-lg font-semibold text-slate-900">OpenLex</h1>
          <LoginForm />
        </div>
      </div>
    </div>
  );
}
