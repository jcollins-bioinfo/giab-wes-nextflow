variable "account_id" {
  type        = string
  description = "Explicit target account; never inferred from a root-linked plugin session."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must contain twelve digits."
  }
}
variable "region" {
  type    = string
  default = "us-west-2"
  validation {
    condition     = var.region == "us-west-2"
    error_message = "This release is qualified/configured for us-west-2 only; review regional changes explicitly."
  }
}
variable "project" {
  type    = string
  default = "giab-wes"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}$", var.project))
    error_message = "Use 3-20 lowercase letters, numbers or hyphens."
  }
}
variable "environment" {
  type    = string
  default = "demo"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,9}$", var.environment))
    error_message = "Use 2-10 lowercase letters, numbers or hyphens."
  }
}
variable "tags" {
  type    = map(string)
  default = {}
}
variable "authorize_paid_services" {
  type        = bool
  default     = false
  description = "Explicit operator gate for compute/serving infrastructure, not authorization for analysis submission."
}
variable "work_retention_days" {
  type    = number
  default = 30
  validation {
    condition     = var.work_retention_days >= 7 && floor(var.work_retention_days) == var.work_retention_days
    error_message = "Retain disposable work for at least seven whole days; resume needs these objects."
  }
}
variable "log_retention_days" {
  type    = number
  default = 90
}
variable "enable_batch" {
  type    = bool
  default = false
}
variable "batch_max_vcpus" {
  type    = number
  default = 4
  validation {
    condition     = var.batch_max_vcpus >= 4 && var.batch_max_vcpus <= 128 && floor(var.batch_max_vcpus) == var.batch_max_vcpus
    error_message = "Batch max must be an integer from 4 to 128. Confirm the matching On-Demand/Spot quota first."
  }
}
variable "batch_use_spot" {
  type    = bool
  default = false
}
variable "batch_instance_types" {
  type    = list(string)
  default = ["c6i.xlarge", "m6i.xlarge", "r6i.xlarge"]
  validation {
    condition     = length(var.batch_instance_types) > 0 && alltrue([for t in var.batch_instance_types : can(regex("^[cmr][67][ai]\\.(xlarge|2xlarge|4xlarge|8xlarge)$", t))])
    error_message = "Only explicit reviewed x86 c/m/r6/7 a/i instance sizes are permitted; no Graviton/optimal wildcard."
  }
}
variable "batch_scratch_gib" {
  type    = number
  default = 300
  validation {
    condition     = var.batch_scratch_gib >= 100 && var.batch_scratch_gib <= 2000
    error_message = "Choose 100-2000 GiB encrypted gp3 scratch per active instance."
  }
}
variable "batch_awscli_version" {
  type        = string
  default     = "2.31.0"
  description = "Host-only Nextflow S3 staging CLI; recorded in launch-template user data, never changes scientific images."
  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.batch_awscli_version))
    error_message = "Pin a numeric AWS CLI package version."
  }
}
variable "enable_explorer" {
  type    = bool
  default = false
}
variable "explorer_image" {
  type        = string
  default     = ""
  description = "Built/scanned project ECR image addressed by @sha256 digest."
  validation {
    condition     = var.explorer_image == "" || can(regex("^[0-9]{12}\\.dkr\\.ecr\\.us-west-2\\.amazonaws\\.com/.+@sha256:[a-f0-9]{64}$", var.explorer_image))
    error_message = "Supply a us-west-2 private ECR URI pinned by SHA-256 digest."
  }
}
variable "explorer_desired_count" {
  type    = number
  default = 1
  validation {
    condition     = contains([0, 1, 2], var.explorer_desired_count)
    error_message = "Explorer count is explicitly bounded to 0-2."
  }
}
variable "explorer_domain" {
  type    = string
  default = "apps.johnpatrickcollins.info"
}
variable "create_delegated_zone" {
  type        = bool
  default     = false
  description = "Create only the apps subdomain zone. Owner must add NS records at existing parent provider."
}
variable "existing_certificate_arn" {
  type        = string
  default     = ""
  description = "Optional already-ISSUED ACM certificate in us-west-2; otherwise request DNS validation."
}
variable "enable_budget" {
  type    = bool
  default = false
}
variable "monthly_budget_usd" {
  type    = number
  default = 50
  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "Budget must be positive. Alerts do not enforce a spending cap."
  }
}
variable "budget_email" {
  type        = string
  default     = ""
  description = "Email receiving 80% actual / 100% forecast account budget alerts."
}
variable "cloud_support_image" {
  type        = string
  default     = ""
  description = "Built, reviewed support runtime at immutable ECR digest; required before enabling Batch."
  validation {
    condition     = var.cloud_support_image == "" || can(regex("@sha256:[a-f0-9]{64}$", var.cloud_support_image))
    error_message = "cloud_support_image must be digest-pinned."
  }
}
variable "batch_tool_mirrors" {
  type        = map(string)
  default     = {}
  description = "Optional verified source-to-ECR mirrors for the six scientific tools. Digest must match the preregistered source manifest."
}

variable "batch_awscli_sha256" {
  type        = string
  default     = "f5fbb3304307ce008756356fadf7855d377b4342da9911728669265ec1ec36dc"
  description = "SHA-256 observed from the official versioned AWS CLI Linux x86_64 2.31.0 bundle over TLS; update together with version after verification."
  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.batch_awscli_sha256))
    error_message = "A full SHA-256 is required for the host staging client installer."
  }
}
