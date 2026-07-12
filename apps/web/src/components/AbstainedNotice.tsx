import type { ReactNode } from "react";

// Neutral, not alarming styling -- an abstain is the grounded-answer contract working as
// intended (no confident retrieval to answer from), not a failure. Must look visually
// distinct from ErrorBanner, which is for actual errors (401/404/5xx).
export function AbstainedNotice({ children }: { children: ReactNode }) {
  return (
    <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2">
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">
        No confident answer found
      </p>
      <p className="text-sm text-slate-600">{children}</p>
    </div>
  );
}
