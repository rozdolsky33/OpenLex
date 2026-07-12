// Fallback only -- always prefer the disclaimer field on the actual API response, since that
// is the canonical, server-controlled text (packages/legal_models/schemas.py's DISCLAIMER).
const FALLBACK_DISCLAIMER =
  "This tool provides general legal information about New York landlord-tenant law, not " +
  "legal advice. It is not a substitute for consultation with a licensed attorney and does " +
  "not create an attorney-client relationship.";

export function Disclaimer({ disclaimer }: { disclaimer?: string | null }) {
  return (
    <p className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-400">
      {disclaimer || FALLBACK_DISCLAIMER}
    </p>
  );
}
