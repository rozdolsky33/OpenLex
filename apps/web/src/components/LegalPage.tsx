// GA checklist Phase 4 (4.1-4.3): the ToS/Privacy route itself, plus a factual data-retention
// summary this app can actually stand behind (verified against migrations/postgres/*.sql
// below), and legal copy explicitly marked as an unreviewed draft. See
// docs/superpowers/plans/2026-07-12-ga-readiness-roadmap.md's Phase 4 for why this
// deliberately stops short of real ToS/Privacy language -- that's attorney work, not
// engineering work.
const PENDING_REVIEW_NOTE =
  "Placeholder text drafted for engineering completeness only -- it has not been reviewed or " +
  "approved by an attorney and is not a binding Terms of Service or Privacy Policy. Do not " +
  "rely on it as final legal language.";

export function LegalPage() {
  return (
    <div className="min-h-screen bg-slate-50 px-4 py-10 text-slate-900">
      <div className="mx-auto max-w-2xl">
        <a href="/" className="text-sm text-slate-500 underline hover:text-slate-700">
          ← Back to OpenLex
        </a>

        <h1 className="mt-4 font-serif text-3xl font-bold tracking-tight">Terms & Privacy</h1>

        <section className="mt-8">
          <h2 className="text-lg font-semibold">What data we actually store</h2>
          <p className="mt-2 text-sm text-slate-600">
            This section is a factual summary, verified directly against the database schema
            (<code>migrations/postgres/</code>) — not legal language, and not pending review.
          </p>
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-slate-700">
            <li>
              <strong>Account:</strong> your email address and a bcrypt hash of your password
              (never the password itself).
            </li>
            <li>
              <strong>Usage tier:</strong> your subscription tier (Silver/Gold/Platinum) and a
              rolling request counter used to enforce your quota.
            </li>
            <li>
              <strong>Conversations:</strong> every question you ask, the generated answer, the
              citations returned with it, and whether the system abstained — stored so a
              conversation can continue across turns.
            </li>
            <li>
              <strong>Nothing else:</strong> no payment information is collected (there is no
              billing in this product), and no analytics or advertising trackers run in the
              app.
            </li>
          </ul>
        </section>

        <section className="mt-8">
          <h2 className="text-lg font-semibold">Who else sees your data</h2>
          <p className="mt-2 text-sm text-slate-700">
            Your question, the retrieved legal passages, and recent conversation history are
            sent to Anthropic&apos;s Claude API to generate each answer — that is the only
            third party involved. Your email and password are never sent to Anthropic; they
            stay in this application&apos;s own database.
          </p>
        </section>

        <section className="mt-8">
          <h2 className="text-lg font-semibold">How long we keep it</h2>
          <p className="mt-2 text-sm text-slate-700">
            There is currently no automated retention or deletion policy — account and
            conversation data persists in the database until manually removed by an
            administrator. Deleting a user record cascades to that user&apos;s conversations
            (foreign-key <code>ON DELETE CASCADE</code>).
          </p>
        </section>

        <section className="mt-8 rounded-lg border border-amber-300 bg-amber-50 px-4 py-4">
          <h2 className="text-lg font-semibold text-amber-900">
            Terms of Service — draft, pending attorney review
          </h2>
          <p className="mt-2 text-sm text-amber-900">{PENDING_REVIEW_NOTE}</p>
          <p className="mt-3 text-sm text-amber-900">
            Placeholder intent: this product provides general legal information about New York
            landlord-tenant law, not legal advice; it does not create an attorney-client
            relationship; use is at your own risk; the operator disclaims warranties to the
            extent permitted by law. Final language requires attorney sign-off before this
            product accepts real users at scale.
          </p>
        </section>

        <section className="mt-8 rounded-lg border border-amber-300 bg-amber-50 px-4 py-4">
          <h2 className="text-lg font-semibold text-amber-900">
            Privacy Policy — draft, pending attorney review
          </h2>
          <p className="mt-2 text-sm text-amber-900">{PENDING_REVIEW_NOTE}</p>
          <p className="mt-3 text-sm text-amber-900">
            Placeholder intent: covers your rights to access or request deletion of your data,
            any jurisdiction-specific obligations (e.g. CCPA/GDPR if applicable to your
            location), and data-security commitments. The factual &quot;what we store&quot;
            section above is accurate today; the legal commitments around it are not yet
            drafted.
          </p>
        </section>

        <p className="mt-10 text-xs text-slate-400">
          This is a proof-of-concept project, not a live legal service — see the disclaimer
          shown with every answer in the app.
        </p>
      </div>
    </div>
  );
}
