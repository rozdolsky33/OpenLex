# infra/argocd/apps/eks-demo/README.md

Verification notes for the Secrets Manager + External Secrets Operator chain (`secretstore-aws.yaml`,
`../../../kubernetes/overlays/eks-demo/externalsecret-openlex.yaml`,
`argocd-admin-externalsecret.yaml`, `app-external-secrets.yaml`,
`../../../terraform/iam_irsa_external_secrets.tf`) — see
`docs/superpowers/specs/2026-07-14-phase7-aws-rds-secrets-manager-design.md`'s 7.2. None of
this has ever run against a real cluster; this is a manual schema/consistency review, not a
live test.

**Checked against:** External Secrets Operator's official CRD reference docs,
`https://external-secrets.io/latest/api/clustersecretstore/` and
`.../api/externalsecret/` (fetched 2026-07-14). Cross-referenced against the CRD source in
`external-secrets/external-secrets` on GitHub at three points in its history to establish
which apiVersion was actually served by which release: `v0.10.7` (2024-11-23),
`v1.0.0` (2025-11-07), and `main` (current, `Chart.yaml` reports chart/app version `2.7.0`
as of this review).

**Findings:**
- `ClusterSecretStore`/`ExternalSecret` `spec` shapes (`provider.aws.service` enum
  `[SecretsManager, ParameterStore]`, `provider.aws.auth.jwt.serviceAccountRef.{name,namespace}`,
  `secretStoreRef.{name,kind}`, `target.creationPolicy` enum
  `[Owner, Orphan, Merge, None]`, `dataFrom[].extract`) all match the current documented
  schema field-for-field — no changes needed to any field path or value used in this repo's
  manifests.
- `externalsecret-openlex.yaml`'s `dataFrom.extract` pulls every top-level key from
  `openlex/app` dynamically (confirmed directly against the CRD source: `extract` is described
  as "Used to extract multiple key/value pairs from one secret" with no fixed/named-list
  behavior — that's what `spec.data[]` is for). Task 1 (7.1)'s new `DATABASE_URL` key, and any
  keys manually merged into that secret per `infra/terraform/README.md`'s updated step 5,
  flow into the `openlex-secrets` k8s Secret automatically — **confirmed, not just asserted**.
  No changes needed to this file.
- `argocd-admin-externalsecret.yaml`'s `creationPolicy: Merge` is the correct choice for
  adding keys to the chart-created `argocd-secret` without clobbering existing keys
  (`server.secretkey`, etc.) — the CRD source's description of `Merge` is exactly "does not
  create the Secret but merges data fields into the existing Secret (expects the Secret to
  already exist)," which is precisely this use case. No changes needed.
- IRSA trust policy (`iam_irsa_external_secrets.tf`)'s `sub` condition value
  (`system:serviceaccount:external-secrets:external-secrets`) matches
  `app-external-secrets.yaml`'s pinned `serviceAccount.name: external-secrets` under
  `spec.destination.namespace: external-secrets` exactly, and also matches
  `secretstore-aws.yaml`'s `auth.jwt.serviceAccountRef.{name,namespace}`. No changes needed.
- `infra/terraform/README.md`'s step 4 (hand-copying `external_secrets_role_arn` into
  `app-external-secrets.yaml`'s ServiceAccount annotation) is accurate; the
  `<EXTERNAL_SECRETS_ROLE_ARN>` placeholder is unambiguous. Confirmed `openlex-secrets` is
  referenced consistently as the `envFrom.secretRef.name` in
  `infra/kubernetes/base/{api,worker}/deployment.yaml` and the migrate job.

**Concern found — not fixed, flagged for follow-up (out of this task's scope):**
`app-external-secrets.yaml` pins the external-secrets Helm chart to `targetRevision: "0.10.*"`.
That version line is now well behind upstream: chart/app `0.10.x` was the last release before
ESO's `v1` CRD generation existed at all (`v0.10.7`, released 2024-11-23, only ever served
`v1alpha1`/`v1beta1` for `ClusterSecretStore`/`ExternalSecret`). `v1beta1` became the correct,
`storage: true` version through that whole `0.x` line, so `secretstore-aws.yaml` and
`externalsecret-openlex.yaml`/`argocd-admin-externalsecret.yaml` using
`apiVersion: external-secrets.io/v1beta1` **is currently correct for the chart version this
repo actually pins** — installing chart `0.10.*` with `installCRDs: true` will not serve
`v1` at all, so using `v1` today would break the pinned deployment, not fix it.

However, upstream has since moved on substantially: `v1.0.0` (released 2025-11-07) promoted
`v1` to `storage: true` and dropped `v1beta1` to `served: false` (i.e. the CRD no longer
accepts `v1beta1` manifests once that chart version — or later — is installed), and the
current upstream release is `2.7.0`. The field paths this repo actually uses
(`provider.aws.{service,auth.jwt.serviceAccountRef}`, `secretStoreRef`, `target.creationPolicy`,
`dataFrom[].extract`) are unchanged between `v1beta1` and `v1` — only the apiVersion string and
the CRD's served/storage flags changed — so a future chart bump would need exactly two
coordinated changes: bump `targetRevision` past `1.0.0`, and change `apiVersion` from
`external-secrets.io/v1beta1` to `external-secrets.io/v1` in `secretstore-aws.yaml`,
`externalsecret-openlex.yaml`, and `argocd-admin-externalsecret.yaml` together, in the same
change. Left unchanged here because: (a) it's not one of the specific cross-checks this task's
spec (7.2) scopes, (b) the manifests as committed are internally consistent and correct for the
chart version actually pinned, and (c) bumping a chart ~2 major generations with no live
cluster to test against is a real, untested, risky infrastructure change that deserves its own
task rather than being folded into a documentation pass.

**Outcome:** no functional or behavioral changes to any file in this chain — see git log for
this commit, which touches only this README.
