import type { Tier, UserStatus } from "../api/types";

const TIER_LABEL: Record<Tier, string> = {
  silver: "Silver",
  gold: "Gold",
  platinum: "Platinum",
};

const TIER_STYLES: Record<Tier, string> = {
  silver: "bg-slate-200 text-slate-700",
  gold: "bg-amber-100 text-amber-800",
  platinum: "bg-violet-100 text-violet-800",
};

const EXHAUSTED_STYLE = "bg-red-100 text-red-800";

function formatResetTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function TierBadge({ user }: { user: UserStatus }) {
  const exhausted = user.request_count >= user.request_limit;
  const style = exhausted ? EXHAUSTED_STYLE : TIER_STYLES[user.tier];
  const label = exhausted
    ? `${TIER_LABEL[user.tier]} · ${user.request_count}/${user.request_limit} · resets ${formatResetTime(user.period_reset_at)}`
    : `${TIER_LABEL[user.tier]} · ${user.request_count}/${user.request_limit}`;

  return <span className={`rounded-full px-2 py-1 text-xs font-medium ${style}`}>{label}</span>;
}
