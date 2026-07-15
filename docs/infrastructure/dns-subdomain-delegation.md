# Delegating a subdomain to a Route 53 hosted zone

OpenLex serves its public endpoints under a **subdomain** of a domain you already own — e.g.
`openlex.arwest.dev` under the registered domain `arwest.dev` (substitute your own, e.g.
`openlex.example.com` under `example.com`). The subdomain's DNS is managed by an AWS **Route 53
public hosted zone**, so that `external-dns` can create `app.<subdomain>` / `argocd.<subdomain>`
records automatically and ACM can validate TLS certs.

For AWS to be authoritative for that subdomain, the **parent domain must delegate it** — by
publishing Route 53's four nameservers as `NS` records for the subdomain, at wherever the
parent domain's authoritative DNS lives (your registrar, or whatever DNS host it points at).

This is registrar-agnostic: the parent domain might be at Squarespace, Cloudflare, GoDaddy,
Namecheap, Google Cloud DNS, another Route 53 zone, etc. The mechanism is identical — only the
UI differs.

```
example.com               (parent zone — at your registrar / DNS host)
   └── NS: openlex   ─────────────►  Route 53 hosted zone "openlex.example.com"
                                        ├── SOA        (managed by AWS)
                                        ├── NS         (managed by AWS)
                                        ├── app.…      (created by external-dns)
                                        ├── argocd.…   (created by external-dns)
                                        └── _<hash>…   (ACM cert validation CNAME)
```

## Prerequisites

The Route 53 hosted zone for the subdomain must exist. In this repo it's created by Terraform
(`infra/terraform/route53.tf`, `aws_route53_zone.demo`, named from `var.domain_name`). The zone
holds **only** the AWS-managed `SOA`/`NS` records at first — the app records come later from
`external-dns`, and the ACM validation `CNAME` from the cert request.

## Step 1 — Get the subdomain's four nameservers from Route 53

Every Route 53 public hosted zone is assigned a **delegation set** of four nameservers (they
look like `ns-1186.awsdns-20.org`, `ns-251.awsdns-31.com`, `ns-672.awsdns-20.net`,
`ns-1554.awsdns-02.co.uk` — the exact names differ per zone). Get them any of these ways:

- **Terraform** (authoritative source in this repo):
  ```bash
  cd infra/terraform
  terraform output route53_name_servers
  ```
- **AWS CLI**:
  ```bash
  aws route53 get-hosted-zone --id <ZONE_ID> --query 'DelegationSet.NameServers' --output text
  ```
- **Console**: Route 53 → Hosted zones → your subdomain zone → the `NS` record whose name
  equals the zone name. Its **Value** is the four nameservers.

Copy all four. Do **not** copy the `SOA` record — only the `NS` values.

## Step 2 — Publish them as NS records at the parent domain

Go to wherever the **parent domain** (`example.com`) keeps its authoritative DNS records and
add the four nameservers as `NS` records **for the subdomain label**:

| Field | Value |
|---|---|
| **Type** | `NS` |
| **Name / Host** | the subdomain — `openlex` (or `openlex.example.com`, depending on how the UI wants it; see gotcha below) |
| **Value / Data** | one of the four Route 53 nameservers — **one NS record per nameserver, four total** |
| **TTL** | default is fine (e.g. 1 hr / 4 hrs) |

You end up with **four NS records**, all with the same name (the subdomain), each pointing at a
different `ns-*.awsdns-*` nameserver. This creates a delegation point: the parent zone now says
"for anything under `openlex.example.com`, ask AWS."

> This is a **delegation**, not a redirect. You are not copying the app's IP anywhere — you're
> handing the whole subdomain namespace to Route 53, and everything below it is then managed in
> the Route 53 zone.

## Step 3 — Verify the delegation

Delegation is live when a public resolver returns the AWS nameservers for the subdomain:

```bash
dig +short NS openlex.example.com @8.8.8.8
# expect the four ns-*.awsdns-* names back
```

Until it propagates you'll get an empty answer or `NXDOMAIN` — that's normal for the first
minutes/hours after adding the records (NS delegation typically resolves within minutes but can
take up to a few hours). Once the NS answer is correct, the app/ACM records inside the zone will
resolve too:

```bash
dig +short app.openlex.example.com     # → the ingress load balancer, once external-dns runs
```

## Gotchas

- **Confirm the DNS host you're editing is actually authoritative for the parent domain.**
  Check `dig +short NS example.com` — whatever nameservers come back are the ones serving the
  zone, and that's the panel your NS records must go in. If you edit records in a panel that
  *isn't* the authoritative host, they'll never propagate. (Domains migrated from Google
  Domains to Squarespace, for instance, keep `ns-cloud-*.googledomains.com` nameservers but are
  edited through the Squarespace DNS panel — same zone, different UI.)
- **Name field: subdomain label vs. FQDN.** Some registrars want just the label (`openlex`) and
  auto-append the parent domain; others want the full `openlex.example.com`. Both are correct as
  long as the resulting record name is `openlex.example.com` — check what the UI previews.
- **Four separate records, not one.** Add each nameserver as its own `NS` record (some UIs let
  you put all four values in one record — that's equivalent). Missing nameservers still "work"
  but reduce redundancy.
- **Don't touch the apex or copy the SOA.** You're adding `NS` records *for the subdomain*, not
  changing the parent domain's own nameservers, and never the `SOA`.
- **Trailing dots** are handled by the registrar UI — enter the nameserver hostname as shown
  (`ns-1186.awsdns-20.org`), with or without the trailing dot per what the field expects.

## Where this fits in the stack

Once delegation is live, the rest is automatic:

1. `external-dns` (running in the cluster, watching `Ingress` objects) creates `app.<subdomain>`
   and `argocd.<subdomain>` records **inside** the Route 53 zone — Terraform deliberately does
   *not* create these (`route53.tf` explains the chicken-and-egg with the ingress-nginx NLB
   hostname).
2. ACM adds a `_<hash>.<subdomain>` validation `CNAME` to the same zone to issue the TLS cert.

So this delegation is the one manual, registrar-side step; everything below the subdomain is
managed as code / by controllers from there on.
