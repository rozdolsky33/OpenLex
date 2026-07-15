#!/usr/bin/env bash
# Master orchestrator for the local docker-compose environment.
#
#   scripts/compose-master.sh up     # full setup: bootstrap -> health-wait -> ingest -> seed
#   scripts/compose-master.sh down   # stop the stack and remove volumes
#
# `up` chains the individual scripts under scripts/compose/ and scripts/seed/ and is idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"
cd "${SCRIPT_DIR}/.."

CMD="${1:-}"

up() {
  banner "compose-master: UP  (docker-compose dev stack)"

  step "Pre-flight: .env with required keys"
  if [ ! -f .env ]; then
    cp .env.example .env
    warn "Created .env from .env.example."
    die "Set ANTHROPIC_API_KEY and NY_OPEN_LEG_API_KEY in .env, then re-run."
  fi
  for key in ANTHROPIC_API_KEY NY_OPEN_LEG_API_KEY; do
    val="$(sed -n -E "s/^${key}=(.*)$/\1/p" .env | head -1)"
    [ -n "${val}" ] || die "${key} is empty in .env -- set it before bringing the stack up."
  done
  ok ".env has the required keys"

  step "Bootstrap stack (uv sync, pre-commit, docker compose up --build)"
  scripts/compose/bootstrap.sh

  step "Wait for the API to report healthy"
  local healthy=""
  for _ in $(seq 1 60); do
    if curl -fsS http://localhost:8000/healthz 2>/dev/null | grep -q '"status":"ok"'; then
      healthy=1; break
    fi
    sleep 3
  done
  [ -n "${healthy}" ] && ok "API healthy at http://localhost:8000/healthz" || warn "API not healthy yet -- continuing anyway"

  step "Ingest corpus (statutes + cases)"
  scripts/compose/ingest.sh all
  ok "corpus ingested"

  step "Seed demo users"
  scripts/seed/seed-demo-users.sh
  ok "demo users seeded"

  done_banner "docker-compose stack is up and populated."
  info "Web UI : http://localhost:5173"
  info "API    : http://localhost:8000  (docs at /docs)"
  info "Grafana: http://localhost:3000  (anonymous Viewer)"
  info "Log in with the DEMO_* credentials from your .env."
}

down() {
  banner "compose-master: DOWN  (stop stack + remove volumes)"
  step "docker compose down -v --remove-orphans"
  docker compose down -v --remove-orphans
  done_banner "docker-compose stack torn down."
}

case "${CMD}" in
  up)   up ;;
  down) down ;;
  *)    die "Usage: $(basename "$0") {up|down}" ;;
esac
