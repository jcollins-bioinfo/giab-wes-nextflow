resource "aws_s3_bucket" "data" {
  bucket        = local.data_bucket
  force_destroy = false
  lifecycle { prevent_destroy = true }
  depends_on = [terraform_data.safety]
}
resource "aws_s3_bucket" "work" {
  bucket        = local.work_bucket
  force_destroy = false
  depends_on    = [terraform_data.safety]
}
locals { buckets = { data = aws_s3_bucket.data, work = aws_s3_bucket.work } }
resource "aws_s3_bucket_public_access_block" "project" {
  for_each                = local.buckets
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "project" {
  for_each = local.buckets
  bucket   = each.value.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_versioning" "project" {
  for_each = local.buckets
  bucket   = each.value.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "project" {
  for_each = local.buckets
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_policy" "project" {
  for_each = local.buckets
  bucket   = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport", Effect = "Deny", Principal = "*", Action = "s3:*"
      Resource  = [each.value.arn, "${each.value.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  # No expiration or transition of any completed data/evidence/provenance version.
  rule {
    id     = "abort-incomplete-uploads-only"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "work" {
  bucket     = aws_s3_bucket.work.id
  depends_on = [aws_s3_bucket_versioning.project]
  rule {
    id     = "disposable-nextflow-work"
    status = "Enabled"
    filter { prefix = "work/" }
    expiration { days = var.work_retention_days }
    noncurrent_version_expiration { noncurrent_days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
  # cache/ intentionally has no automatic expiration: review reuse/evidence first.
  rule {
    id     = "abort-incomplete-cache-uploads"
    status = "Enabled"
    filter { prefix = "cache/" }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}
