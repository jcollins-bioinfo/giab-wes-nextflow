output "region" { value = var.region }
output "data_bucket_name" { value = aws_s3_bucket.data.id }
output "data_bucket_arn" { value = aws_s3_bucket.data.arn }
output "work_bucket_name" { value = aws_s3_bucket.work.id }
output "work_bucket_arn" { value = aws_s3_bucket.work.arn }
output "healthomics_cache_uri" { value = "s3://${aws_s3_bucket.work.id}/cache/" }
output "canonical_output_uri" { value = "s3://${aws_s3_bucket.data.id}/results/" }
output "batch_work_uri" { value = "s3://${aws_s3_bucket.work.id}/work/" }
output "healthomics_execution_role_arn" { value = aws_iam_role.project["healthomics-execution"].arn }
output "batch_job_role_arn" { value = aws_iam_role.project["batch-job"].arn }
output "batch_benchmark_job_role_arn" { value = aws_iam_role.project["batch-benchmark-job"].arn }
output "batch_execution_role_arn" { value = aws_iam_role.project["batch-execution"].arn }
output "batch_queue_name" { value = try(aws_batch_job_queue.project[0].name, null) }
output "batch_queue_arn" { value = try(aws_batch_job_queue.project[0].arn, null) }
output "batch_awscli_path" { value = "/opt/giab-awscli/bin/aws" }
output "ecr_repository_urls" { value = { for name, repository in aws_ecr_repository.project : name => repository.repository_url } }
output "log_groups" {
  value = {
    batch    = aws_cloudwatch_log_group.batch.name, healthomics = aws_cloudwatch_log_group.healthomics.name,
    explorer = aws_cloudwatch_log_group.explorer.name
  }
}
output "explorer_url" { value = try(module.explorer[0].url, null) }
output "explorer_alb_dns_name" { value = try(module.explorer[0].alb_dns_name, null) }
output "apps_delegation_name_servers" { value = try(module.explorer[0].name_servers, []) }
output "explorer_certificate_validation_records" { value = try(module.explorer[0].certificate_validation_records, []) }
output "service_role_arns" { value = { for key, role in aws_iam_role.project : key => role.arn } }
