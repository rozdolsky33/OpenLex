output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  value     = module.eks.cluster_certificate_authority_data
  sensitive = true
}

output "oidc_provider_arn" {
  value = module.eks.oidc_provider_arn
}

output "route53_zone_id" {
  value = aws_route53_zone.demo.zone_id
}

output "route53_name_servers" {
  description = "Set these as the NS records for var.domain_name at your registrar"
  value       = aws_route53_zone.demo.name_servers
}

output "external_dns_role_arn" {
  description = "Paste into infra/argocd/apps/eks-demo/app-external-dns.yaml's serviceAccount.annotations"
  value       = aws_iam_role.external_dns.arn
}

output "external_secrets_role_arn" {
  description = "Paste into infra/argocd/apps/eks-demo/app-external-secrets.yaml's serviceAccount.annotations"
  value       = aws_iam_role.external_secrets.arn
}

output "ecr_repository_urls" {
  description = "Paste into infra/kubernetes/overlays/eks-demo/kustomization.yaml's images: newName fields"
  value       = { for k, v in aws_ecr_repository.this : k => v.repository_url }
}

output "web_bucket_name" {
  description = "Paste into the GitHub repo's OPENLEX_WEB_BUCKET Actions variable"
  value       = aws_s3_bucket.web.id
}

output "cloudfront_distribution_id" {
  description = "Paste into the GitHub repo's OPENLEX_CLOUDFRONT_DISTRIBUTION_ID Actions variable"
  value       = aws_cloudfront_distribution.web.id
}

output "github_actions_deploy_web_role_arn" {
  description = "Paste into the GitHub repo's OPENLEX_DEPLOY_WEB_ROLE_ARN Actions variable (GitHub reserves the GITHUB_ name prefix)"
  value       = aws_iam_role.github_actions_deploy_web.arn
}

output "github_actions_ecr_push_role_arn" {
  description = "Paste into the GitHub repo's OPENLEX_ECR_PUSH_ROLE_ARN Actions variable (used by deploy.yml to push images to ECR)"
  value       = aws_iam_role.github_actions_ecr_push.arn
}

output "image_updater_role_arn" {
  description = "Paste into app-argocd-image-updater.yaml's serviceAccount.annotations (eks.amazonaws.com/role-arn) so the updater can read ECR via IRSA"
  value       = aws_iam_role.image_updater.arn
}

# Exposed as an output (not just var.domain_name) so scripts/eks/github-deploy-vars.sh can read
# all four deploy-static values from `terraform output` uniformly — see docs/infrastructure/
# web-deploy.md.
output "domain_name" {
  description = "Base domain — feeds the GitHub repo's OPENLEX_DOMAIN Actions variable"
  value       = var.domain_name
}
