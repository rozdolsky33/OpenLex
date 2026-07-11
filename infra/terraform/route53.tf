# Zone only — no record resources. Records for app.<domain> and argocd.<domain> are created
# dynamically by external-dns (watches Ingress objects), not by Terraform, to avoid a
# chicken-and-egg with the ingress-nginx NLB hostname not existing until ArgoCD deploys it.
resource "aws_route53_zone" "demo" {
  name = var.domain_name
}
