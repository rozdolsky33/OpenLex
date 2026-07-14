# infra/terraform/backend.tf
#
# Real bucket/key/region/dynamodb_table values are supplied via
# `terraform init -backend-config=backend.hcl` (copy backend.hcl.example -> backend.hcl and
# fill in real values — never commit backend.hcl itself, see .gitignore) rather than
# terraform.tfvars, because Terraform backend blocks cannot reference variables or
# terraform.tfvars at all — this partial-configuration pattern is the standard way to keep
# real bucket names out of a committed file while still using a real S3 backend.
#
# See README.md's "Remote state" section for the one-time bootstrap (the S3 bucket + DynamoDB
# lock table this backend needs can't be created by the same Terraform config that needs them
# to exist first — the classic remote-state chicken-and-egg).
terraform {
  backend "s3" {
    encrypt = true
  }
}
