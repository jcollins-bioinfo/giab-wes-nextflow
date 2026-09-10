locals {
  # Shared authoritative template permits a non-spending IAM bootstrap and exact
  # subsequent Terraform import without a second hand-written permissions set.
  role_specs = jsondecode(templatefile("${path.module}/iam-roles.json.tftpl", {
    partition = local.partition, account = var.account_id, region = var.region,
    name      = local.name, data_bucket = local.data_bucket, work_bucket = local.work_bucket
  }))
}
resource "aws_iam_role" "project" {
  for_each             = local.role_specs
  name                 = "${local.name}-${each.key}"
  description          = "GIAB WES ${each.key}; Terraform-owned project-scoped temporary service credentials"
  assume_role_policy   = jsonencode(each.value.trust)
  max_session_duration = 3600
  depends_on           = [terraform_data.safety]
}
resource "aws_iam_role_policy" "project" {
  for_each = { for key, spec in local.role_specs : key => spec if spec.policy != null }
  name     = "project-access"
  role     = aws_iam_role.project[each.key].id
  policy   = jsonencode(each.value.policy)
}
resource "aws_iam_instance_profile" "batch" {
  count = var.enable_batch ? 1 : 0
  name  = "${local.name}-batch-instance"
  role  = aws_iam_role.project["batch-instance"].name
}
resource "aws_iam_service_linked_role" "batch" {
  count            = var.enable_batch ? 1 : 0
  aws_service_name = "batch.amazonaws.com"
  description      = "AWS-managed Batch infrastructure service role; import if account already has one."
}
