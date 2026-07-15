# ArgoCD (GitOps entrypoint)

ArgoCD itself is the only thing installed imperatively (chicken-and-egg — it can't deploy
itself from nothing). Everything else is ArgoCD-managed via an **app-of-apps** pattern: one
root `Application` per environment whose `source.path` is a directory of child `Application`
manifests.

```
install/       Helm values for `helm upgrade --install argocd argo/argo-cd` (one per environment)
projects/      AppProject per environment — scopes sourceRepos/destinations
root-apps/     root-{kind,eks-demo}.yaml — the ONLY objects a human applies by hand, per cluster
apps/
├── kind/      just app-openlex.yaml — platform components (ingress/TLS/DNS) are skipped in
│              kind entirely, see infra/kubernetes/README.md
└── eks-demo/  ingress-nginx, cert-manager (+ ClusterIssuers), external-dns, external-secrets
               (+ ClusterSecretStore), the ArgoCD admin-password ExternalSecret, the ArgoCD
               Ingress, and app-openlex.yaml
```

## Bootstrap sequence

Both environments: `scripts/kind/argocd-bootstrap.sh <kind|eks-demo>` — Helm-installs ArgoCD, then
applies that environment's AppProject and root Application. Everything under
`infra/argocd/apps/<env>/` then reconciles automatically.

`eks-demo`'s child Applications carry `argocd.argoproj.io/sync-wave` annotations to sequence
controllers before consumers — ArgoCD doesn't otherwise order unrelated Applications, and
ingress-nginx's load-balancer hostname has to exist before external-dns has anything to point
at or cert-manager's HTTP-01 challenge is reachable:

| Wave | What |
|---|---|
| `-2` | `external-secrets`, `external-dns`, `cert-manager` (platform controllers) |
| `-1` | `ingress-nginx` (needs to get an NLB hostname assigned) |
| `0`  | `ClusterIssuer`s, `ClusterSecretStore`, the ArgoCD admin-password `ExternalSecret`, the ArgoCD `Ingress` |
| `1`  | `openlex` (the app itself) |

## First-boot gotchas

- Start on `letsencrypt-staging` (already the default in the committed Ingress annotations) to
  avoid burning Let's Encrypt's production rate limit while DNS/reachability settle; switch to
  `letsencrypt-prod` once staging succeeds end-to-end.
- ArgoCD reads `admin.password` from `argocd-secret` as a bcrypt hash *plus*
  `admin.passwordMtime` — updating one without the other is ignored by some versions. If login
  with the new password fails right after the `ExternalSecret` syncs, `kubectl -n argocd
  rollout restart deploy/argocd-server`.
- A single `t4g.medium` hosts ArgoCD + all of the above + the openlex workload — if pods sit
  `Pending`, check `kubectl describe node` for allocatable pressure before assuming a manifest
  is wrong.

See `docs/infrastructure/mlops-guide.md` and `docs/infrastructure/architecture-diagrams.md` for
the fuller walkthrough, and `infra/terraform/README.md` for what has to exist in AWS first.
