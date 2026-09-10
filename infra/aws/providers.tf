provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
  default_tags { tags = local.tags }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_availability_zones" "available" { state = "available" }

resource "terraform_data" "safety" {
  lifecycle {
    precondition {
      condition     = length(local.name) <= 23
      error_message = "Combined project-environment name must not exceed 23 characters to fit AWS load balancer names."
    }
    precondition {
      condition     = !endswith(data.aws_caller_identity.current.arn, ":root")
      error_message = "Root is forbidden. Authenticate with an approved federated operator role and temporary credentials."
    }
    precondition {
      condition     = !(var.enable_batch || var.enable_explorer) || var.authorize_paid_services
      error_message = "Paid Batch/Explorer infrastructure requires authorize_paid_services=true after reviewing preflight and plan."
    }
  }
}
