locals {
  upstream_images = {
    bwa         = jsondecode(file("${path.module}/../../config/canonical-runtime.json")).tools.bwa.image
    samtools    = jsondecode(file("${path.module}/../../config/m3-tools.json")).tools.samtools.image
    gatk        = jsondecode(file("${path.module}/../../config/m4-tools.json")).tools.gatk.image
    deepvariant = jsondecode(file("${path.module}/../../config/m4-tools.json")).tools.deepvariant.image
    bcftools    = jsondecode(file("${path.module}/../../config/m5-tools.json")).tools.bcftools.image
    rtg         = jsondecode(file("${path.module}/../../config/m5-tools.json")).tools.rtg.image
  }
  batch_images = merge(local.upstream_images, var.batch_tool_mirrors, { support = var.cloud_support_image })
  batch_job_specs = merge(
    { for tool in ["support", "bwa", "samtools", "gatk", "deepvariant", "bcftools", "rtg"] : tool => { tool = tool, role = "batch-job" } },
    { for tool in ["support", "bcftools", "rtg"] : "${tool}-benchmark" => { tool = tool, role = "batch-benchmark-job" } }
  )
}
resource "aws_batch_job_definition" "scientific" {
  for_each              = var.enable_batch ? local.batch_job_specs : {}
  name                  = "${local.name}-${each.key}"
  type                  = "container"
  platform_capabilities = ["EC2"]
  propagate_tags        = true
  container_properties = jsonencode({
    image            = local.batch_images[each.value.tool]
    jobRoleArn       = aws_iam_role.project[each.value.role].arn
    executionRoleArn = aws_iam_role.project["batch-execution"].arn
    privileged       = false
    volumes          = [{ name = "aws-cli", host = { sourcePath = "/opt/giab-awscli" } }]
    mountPoints      = [{ sourceVolume = "aws-cli", containerPath = "/opt/giab-awscli", readOnly = true }]
    # Nextflow SubmitJob overrides the command and per-process CPU/RAM requests.
    command              = ["bash", "-lc", "exit 64"]
    resourceRequirements = [{ type = "VCPU", value = "1" }, { type = "MEMORY", value = "2048" }]
    logConfiguration = {
      logDriver = "awslogs"
      options   = { awslogs-group = aws_cloudwatch_log_group.batch.name, awslogs-region = var.region, awslogs-stream-prefix = "canonical", mode = "blocking" }
    }
  })
  retry_strategy { attempts = 1 }
  timeout { attempt_duration_seconds = 86400 }
  lifecycle {
    precondition {
      condition     = can(regex("@sha256:[a-f0-9]{64}$", local.batch_images[each.value.tool]))
      error_message = "Build and pin the support runtime before enabling Batch. All job images require immutable digests."
    }
    precondition {
      condition     = alltrue([for tool, uri in var.batch_tool_mirrors : contains(keys(local.upstream_images), tool) && try(split("@", uri)[1] == split("@", local.upstream_images[tool])[1], false)])
      error_message = "A scientific ECR mirror must preserve the preregistered upstream manifest digest and known tool key."
    }
  }
  depends_on = [aws_iam_role_policy.project]
}
output "batch_job_definitions" {
  value = { for key, definition in aws_batch_job_definition.scientific : key => "job-definition://${definition.name}:${definition.revision}" }
}
output "batch_job_definition_images" {
  value = { for key, spec in local.batch_job_specs : key => local.batch_images[spec.tool] }
}

output "batch_job_definition_inventory" {
  value = { for key, definition in aws_batch_job_definition.scientific : key => {
    name         = "${definition.name}:${definition.revision}"
    image        = local.batch_images[local.batch_job_specs[key].tool]
    job_role_arn = aws_iam_role.project[local.batch_job_specs[key].role].arn
  } }
}
