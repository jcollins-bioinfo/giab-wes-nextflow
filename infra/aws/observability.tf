resource "aws_cloudwatch_log_group" "batch" {
  name              = "/${local.name}/batch"
  retention_in_days = var.log_retention_days
  depends_on        = [terraform_data.safety]
}
resource "aws_cloudwatch_log_group" "healthomics" {
  # HealthOmics uses this fixed service log-group name. Import if already present.
  name              = "/aws/omics/WorkflowLog"
  retention_in_days = var.log_retention_days
  depends_on        = [terraform_data.safety]
}
resource "aws_cloudwatch_log_group" "explorer" {
  name              = "/${local.name}/explorer"
  retention_in_days = var.log_retention_days
  depends_on        = [terraform_data.safety]
}
