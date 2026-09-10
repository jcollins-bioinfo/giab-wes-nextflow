resource "aws_launch_template" "batch" {
  count                  = var.enable_batch ? 1 : 0
  name_prefix            = "${local.name}-batch-"
  update_default_version = true
  user_data              = base64encode(templatefile("${path.module}/templates/batch-user-data.sh.tftpl", { awscli_version = var.batch_awscli_version, awscli_sha256 = var.batch_awscli_sha256 }))
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = var.batch_scratch_gib
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }
  tag_specifications {
    resource_type = "instance"
    tags          = local.tags
  }
  tag_specifications {
    resource_type = "volume"
    tags          = local.tags
  }
}
resource "aws_batch_compute_environment" "project" {
  count        = var.enable_batch ? 1 : 0
  name_prefix  = "${local.name}-"
  type         = "MANAGED"
  state        = "ENABLED"
  service_role = aws_iam_service_linked_role.batch[0].arn
  compute_resources {
    type                = var.batch_use_spot ? "SPOT" : "EC2"
    allocation_strategy = var.batch_use_spot ? "SPOT_PRICE_CAPACITY_OPTIMIZED" : "BEST_FIT_PROGRESSIVE"
    min_vcpus           = 0
    max_vcpus           = var.batch_max_vcpus
    instance_type       = var.batch_instance_types
    instance_role       = aws_iam_instance_profile.batch[0].arn
    security_group_ids  = [aws_security_group.batch[0].id]
    subnets             = aws_subnet.public[*].id
    tags                = local.tags
    ec2_configuration { image_type = "ECS_AL2023" }
    launch_template {
      launch_template_id = aws_launch_template.batch[0].id
      version            = tostring(aws_launch_template.batch[0].latest_version)
    }
  }
  update_policy {
    job_execution_timeout_minutes = 60
    terminate_jobs_on_update      = false
  }
  lifecycle {
    create_before_destroy = true
    precondition {
      condition     = alltrue([for t in var.batch_instance_types : lookup({ xlarge = 4, "2xlarge" = 8, "4xlarge" = 16, "8xlarge" = 32 }, split(".", t)[1], 1000) <= var.batch_max_vcpus])
      error_message = "Each chosen instance must fit within batch_max_vcpus."
    }
  }
  depends_on = [aws_iam_role_policy.project, aws_route_table_association.public]
}
resource "aws_batch_job_queue" "project" {
  count    = var.enable_batch ? 1 : 0
  name     = "${local.name}-canonical"
  state    = "ENABLED"
  priority = 1
  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.project[0].arn
  }
}
# Terraform owns immutable per-tool job definitions in batch-jobs.tf.
# Nextflow overrides command and task resources, preserving the declared job role.
