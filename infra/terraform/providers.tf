provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "openlex"
      Environment = "eks-demo"
      ManagedBy   = "terraform"
    }
  }
}

# CloudFront/ACM specifically require us-east-1 regardless of var.region — see static-site.tf's
# aws_acm_certificate.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "openlex"
      Environment = "eks-demo"
      ManagedBy   = "terraform"
    }
  }
}
