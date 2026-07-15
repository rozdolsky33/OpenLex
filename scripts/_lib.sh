#!/usr/bin/env bash
# Shared helpers for the scripts/ orchestrators: colored step output for the master scripts
# (kind-master.sh, compose-master.sh) and a small port-forward runner shared by the
# *-port-forward.sh scripts. Colors auto-disable when stdout isn't a TTY (CI, pipes) or when
# NO_COLOR is set.

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_BLUE=$'\033[34m'
else
  C_RESET=; C_BOLD=; C_DIM=; C_CYAN=; C_GREEN=; C_YELLOW=; C_RED=; C_BLUE=
fi

_STEP=0
_ts() { date +%H:%M:%S; }
_rule="──────────────────────────────────────────────────────────────"

banner() { # banner "TITLE"
  printf '\n%s%s%s%s\n' "$C_BOLD" "$C_BLUE" "$_rule" "$C_RESET"
  printf '%s%s  %s%s\n' "$C_BOLD" "$C_BLUE" "$1" "$C_RESET"
  printf '%s%s%s%s\n' "$C_BOLD" "$C_BLUE" "$_rule" "$C_RESET"
}

step() { # step "message"
  _STEP=$((_STEP + 1))
  printf '\n%s%s> [%d] %s%s %s(%s)%s\n' "$C_BOLD" "$C_CYAN" "$_STEP" "$1" "$C_RESET" "$C_DIM" "$(_ts)" "$C_RESET"
}
info() { printf '   %s%s%s\n' "$C_DIM" "$1" "$C_RESET"; }
ok()   { printf '   %s[ok] %s%s\n' "$C_GREEN" "$1" "$C_RESET"; }
warn() { printf '   %s[warn] %s%s\n' "$C_YELLOW" "$1" "$C_RESET"; }
die()  { printf '\n%s[error] %s%s\n' "$C_RED" "$1" "$C_RESET" >&2; exit 1; }

done_banner() { # done_banner "message"
  printf '\n%s%s[done] %s%s\n' "$C_BOLD" "$C_GREEN" "$1" "$C_RESET"
}

# --- port-forward runner (shared by the *-port-forward.sh scripts) ---
# kind/eks have no ingress for these services, so we background one `kubectl port-forward` per
# service and clean them all up on Ctrl-C. Usage:
#   pf <namespace> <service> <local:remote>   # ...repeat per service
#   pf_wait                                    # trap + block until Ctrl-C
_PF_PIDS=()
_pf_cleanup() {
  echo
  echo "Stopping port-forwards..."
  for pid in "${_PF_PIDS[@]}"; do kill "${pid}" 2>/dev/null || true; done
}
pf() {
  kubectl port-forward -n "$1" "svc/$2" "$3" &
  _PF_PIDS+=($!)
}
pf_wait() {
  trap _pf_cleanup EXIT INT TERM
  echo
  echo "Press Ctrl-C to stop all port-forwards."
  wait
}
