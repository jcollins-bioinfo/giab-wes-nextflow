module "explorer" {
  count                    = var.enable_explorer ? 1 : 0
  source                   = "./explorer"
  name                     = local.name
  region                   = var.region
  vpc_id                   = aws_vpc.project[0].id
  subnet_ids               = aws_subnet.public[*].id
  image                    = var.explorer_image
  repository_url           = aws_ecr_repository.project["explorer"].repository_url
  execution_role_arn       = aws_iam_role.project["explorer-execution"].arn
  task_role_arn            = aws_iam_role.project["explorer-task"].arn
  log_group_name           = aws_cloudwatch_log_group.explorer.name
  domain                   = var.explorer_domain
  desired_count            = var.explorer_desired_count
  create_delegated_zone    = var.create_delegated_zone
  existing_certificate_arn = var.existing_certificate_arn
  depends_on               = [terraform_data.safety, aws_iam_role_policy.project, aws_route_table_association.public]
}
