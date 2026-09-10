locals {
  name         = "${var.project}-${var.environment}"
  partition    = data.aws_partition.current.partition
  account      = data.aws_caller_identity.current.account_id
  network      = var.enable_batch || var.enable_explorer
  data_bucket  = "${local.name}-${var.account_id}-${var.region}-data"
  work_bucket  = "${local.name}-${var.account_id}-${var.region}-work"
  tags         = merge(var.tags, { Project = var.project, Environment = var.environment, ManagedBy = "Terraform", DataClass = "public-research" })
  data_inputs  = ["source", "reference", "index", "domain", "known-sites"]
  data_outputs = ["results", "evidence", "provenance"]
  repositories = toset(["support", "explorer", "bwa", "samtools", "gatk", "deepvariant", "bcftools", "rtg"])
}
