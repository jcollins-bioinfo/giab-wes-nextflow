# Plans use a mocked provider: no credentials, network or infrastructure changes.
mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:sts::123456789012:assumed-role/giab-operator/test"
      user_id    = "test"
    }
  }
  mock_data "aws_partition" { defaults = { partition = "aws" } }
  mock_data "aws_availability_zones" { defaults = { names = ["us-west-2a", "us-west-2b"] } }
}
variables {
  account_id = "123456789012"
}
run "safe_defaults" {
  command = plan
  assert {
    condition     = length(aws_batch_compute_environment.project) == 0 && length(module.explorer) == 0
    error_message = "Default plan must omit paid Batch and Explorer compute."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.project["data"].block_public_policy && aws_s3_bucket_public_access_block.project["work"].block_public_acls
    error_message = "Project buckets must stay private."
  }
  assert {
    condition     = alltrue([for r in aws_ecr_repository.project : r.image_tag_mutability == "IMMUTABLE" && r.image_scanning_configuration[0].scan_on_push])
    error_message = "All tool/runtime repositories require immutable tags and image scanning."
  }
  assert {
    condition     = contains([for s in local.role_specs["batch-job"].policy.Statement : s.Effect], "Deny") && local.role_specs["explorer-task"].policy == null
    error_message = "Caller role must explicitly deny truth, and bundled Explorer must receive no AWS data access."
  }
  assert {
    condition     = length(local.batch_job_specs) == 10 && local.batch_job_specs["rtg-benchmark"].role == "batch-benchmark-job" && local.batch_job_specs["rtg"].role == "batch-job"
    error_message = "Scientific and evaluation definitions must bind distinct roles."
  }
}
run "reject_root" {
  command = plan
  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:root"
      user_id    = "123456789012"
    }
  }
  expect_failures = [terraform_data.safety]
}
run "reject_implicit_spend" {
  command = plan
  variables {
    enable_batch        = true
    cloud_support_image = "123456789012.dkr.ecr.us-west-2.amazonaws.com/giab-wes-demo/support@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
  expect_failures = [terraform_data.safety]
}
run "explorer_requires_digest_and_tls" {
  command = plan
  variables {
    enable_explorer          = true
    authorize_paid_services  = true
    explorer_image           = "123456789012.dkr.ecr.us-west-2.amazonaws.com/giab-wes-demo/explorer@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    existing_certificate_arn = "arn:aws:acm:us-west-2:123456789012:certificate/00000000-0000-0000-0000-000000000000"
  }
  override_resource {
    target = aws_ecr_repository.project["explorer"]
    values = { repository_url = "123456789012.dkr.ecr.us-west-2.amazonaws.com/giab-wes-demo/explorer" }
  }
  assert {
    condition     = length(module.explorer) == 1 && output.explorer_url == "https://apps.johnpatrickcollins.info/research/giab-wes-nextflow/explorer/"
    error_message = "Explicitly enabled Explorer must expose the expected HTTPS route."
  }
}
run "bounded_batch_with_explicit_authorization" {
  command = plan
  variables {
    enable_batch            = true
    authorize_paid_services = true
    cloud_support_image     = "123456789012.dkr.ecr.us-west-2.amazonaws.com/giab-wes-demo/support@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
  assert {
    condition     = length(aws_batch_job_definition.scientific) == 10 && aws_batch_compute_environment.project[0].compute_resources[0].min_vcpus == 0 && aws_batch_compute_environment.project[0].compute_resources[0].max_vcpus == 4
    error_message = "Batch must retain ten explicit scientific/benchmark definitions and bounded scale-to-zero defaults."
  }
}
