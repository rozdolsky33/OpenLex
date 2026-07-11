# Local state by default — fine for a solo-dev demo cluster that gets torn down and recreated
# (see docs/infrastructure/aws-eks-cost-estimate.md's "don't run EKS 24/7" guidance). Upgrade to
# a remote backend (S3 + DynamoDB lock table) once more than one person/machine touches this,
# or once you stop tearing the cluster down between sessions:
#
# terraform {
#   backend "s3" {
#     bucket         = "<your-tfstate-bucket>"
#     key            = "openlex/eks-demo/terraform.tfstate"
#     region         = "us-east-1"
#     dynamodb_table = "<your-tflock-table>"
#     encrypt        = true
#   }
# }
