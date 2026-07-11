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
