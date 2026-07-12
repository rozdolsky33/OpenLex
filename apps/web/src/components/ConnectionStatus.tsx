import { useEffect, useState } from "react";
import { getHealth } from "../api/health";

const POLL_INTERVAL_MS = 30_000;

type Status = "checking" | "ok" | "degraded" | "unreachable";

const STATUS_STYLES: Record<Status, string> = {
  checking: "bg-slate-300 text-slate-700",
  ok: "bg-emerald-100 text-emerald-800",
  degraded: "bg-amber-100 text-amber-800",
  unreachable: "bg-red-100 text-red-800",
};

const STATUS_LABEL: Record<Status, string> = {
  checking: "Checking API…",
  ok: "API connected",
  degraded: "API degraded",
  unreachable: "API unreachable",
};

export function ConnectionStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const health = await getHealth();
        if (!cancelled) {
          setStatus(health.status === "ok" ? "ok" : "degraded");
        }
      } catch {
        if (!cancelled) {
          setStatus("unreachable");
        }
      }
    }

    void poll();
    const interval = setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <span className={`rounded-full px-2 py-1 text-xs font-medium ${STATUS_STYLES[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}
