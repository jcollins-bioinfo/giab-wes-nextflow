terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
provider "aws" {
  region              = "us-west-2"
  allowed_account_ids = ["400200465857"]
  default_tags { tags = { Project = "giab-wes", Environment = "demo", ManagedBy = "Terraform" } }
}
variable "image" {
  type        = string
  description = "Reviewed private ECR Explorer image with its actual immutable digest."
  validation {
    condition     = can(regex("^400200465857\\.dkr\\.ecr\\.us-west-2\\.amazonaws\\.com/giab-wes-demo-explorer@sha256:[a-f0-9]{64}$", var.image))
    error_message = "Use the qualified project Explorer ECR digest."
  }
}
variable "power" {
  type    = string
  default = "nano"
  validation {
    condition     = contains(["nano", "micro"], var.power)
    error_message = "Only the $7 Nano and $10 Micro tiers are within the authorized base-service ceiling."
  }
}
variable "authorize_first_month" {
  type    = bool
  default = false
}
variable "memory_peak_bytes" {
  type        = number
  description = "Observed Linux cgroup peak for this exact image under the selected memory/CPU limit and concurrent HTTP probe."
}
variable "memory_probe_image" {
  type        = string
  description = "Actual immutable image digest from the memory qualification receipt."
}
variable "credit_eligibility_verified" {
  type    = bool
  default = false
}
variable "renewal_decision_date" {
  type        = string
  description = "Explicit owner decision date before the next monthly period, YYYY-MM-DD."
  validation {
    condition     = can(formatdate("YYYY-MM-DD", "${var.renewal_decision_date}T00:00:00Z"))
    error_message = "A valid owner renewal or shutdown decision date is required."
  }
}
variable "validated_certificate_name" {
  type        = string
  default     = ""
  description = "Existing validated Lightsail certificate; bind only after reviewing DNS and provider URL. Empty leaves provider URL only."
}
data "aws_caller_identity" "operator" {}
resource "terraform_data" "safety" {
  lifecycle {
    precondition {
      condition     = startswith(data.aws_caller_identity.operator.arn, "arn:aws:sts::400200465857:assumed-role/giab-operator/")
      error_message = "Only the verified giab-operator assumed role may deploy."
    }
    precondition {
      condition     = var.authorize_first_month && var.credit_eligibility_verified
      error_message = "Review first-month authorization and service credit eligibility before activation."
    }
    precondition {
      condition     = var.memory_probe_image == var.image && var.memory_peak_bytes > 0 && var.memory_peak_bytes <= (var.power == "nano" ? 429496729 : 858993459)
      error_message = "This exact image needs a measured peak with at least 20% memory headroom in the selected tier."
    }
  }
}
resource "aws_lightsail_container_service" "explorer" {
  name  = "giab-wes-demo-explorer"
  power = var.power
  scale = 1
  private_registry_access {
    ecr_image_puller_role { is_active = true }
  }
  dynamic "public_domain_names" {
    for_each = var.validated_certificate_name == "" ? [] : [var.validated_certificate_name]
    content {
      certificate {
        certificate_name = public_domain_names.value
        domain_names     = ["apps.johnpatrickcollins.info"]
      }
    }
  }
  tags       = { RenewalDecisionDate = var.renewal_decision_date }
  depends_on = [terraform_data.safety]
}
resource "aws_ecr_repository_policy" "explorer_pull" {
  repository = "giab-wes-demo-explorer"
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "LightsailPullReviewedExplorer"
    Effect    = "Allow"
    Principal = { AWS = aws_lightsail_container_service.explorer.private_registry_access[0].ecr_image_puller_role[0].principal_arn }
    Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
  }] })
}
resource "aws_lightsail_container_service_deployment_version" "explorer" {
  service_name = aws_lightsail_container_service.explorer.name
  container {
    container_name = "explorer"
    image          = var.image
    ports          = { "8050" = "HTTP" }
    environment    = { EXPLORER_PREFIX = "/giab-wes-nextflow/" }
  }
  public_endpoint {
    container_name = "explorer"
    container_port = 8050
    health_check {
      path                = "/giab-wes-nextflow/readyz"
      success_codes       = "200"
      healthy_threshold   = 2
      unhealthy_threshold = 3
      interval_seconds    = 15
      timeout_seconds     = 5
    }
  }
  depends_on = [aws_ecr_repository_policy.explorer_pull]
}
output "provider_url" { value = aws_lightsail_container_service.explorer.url }
output "monthly_base_usd" { value = var.power == "nano" ? 7 : 10 }
output "renewal_decision_date" { value = var.renewal_decision_date }
output "created_at" { value = aws_lightsail_container_service.explorer.created_at }
