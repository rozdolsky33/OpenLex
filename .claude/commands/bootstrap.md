---
description: Bring up or tear down an OpenLex local environment (docker-compose or kind) end-to-end, and troubleshoot if a step fails.
argument-hint: [compose|kind] [up|down]
---

Drive an OpenLex local environment. Follow the **`local-environment`** skill for the procedure
and the troubleshooting matrix.

Requested action: `$ARGUMENTS` (e.g. `kind up`, `compose down`).

1. Parse the environment (`compose` or `kind`) and action (`up` or `down`) from `$ARGUMENTS`.
   If either is missing or ambiguous, ask before doing anything.
2. For **`down`**, confirm with the user first — `kind` down deletes the cluster and `compose`
   down removes volumes (`-v`). Then run the master script.
3. For **`up`**, run the master script and let it stream its colored step output:
   - `scripts/compose-master.sh up` or `scripts/kind-master.sh up`
   - If a prerequisite is missing (`.env` keys, `GHCR_*` for kind), fix/prompt per the skill,
     then re-run — the masters are idempotent.
4. If `up` finished but the app misbehaves — chat returns "NO CONFIDENT ANSWER FOUND", login
   401s, Grafana shows "No data", postgres-exporter is `CreateContainerConfigError` — use the
   skill's troubleshooting matrix to diagnose (verify server-side first) and fix, then confirm.
5. Do **not** start the blocking port-forwards yourself. After a successful `up`, tell the user
   which port-forward scripts to run and which URLs to open (kind: web/API + observability).

Never hand-patch ArgoCD-managed resources on kind (selfHeal reverts them) — change git and sync.
