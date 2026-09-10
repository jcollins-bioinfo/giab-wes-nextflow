resource "aws_ecr_repository" "project" {
  for_each             = local.repositories
  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
  depends_on = [terraform_data.safety]
}
# Retain every tagged image (including release mirrors). Never automatically expire
# untagged images: a live ECS/HealthOmics deployment can still reference that digest.
# No ECR expiration policy is safer than a policy that deletes active release bytes.
resource "aws_ecr_repository_policy" "healthomics" {
  for_each   = setsubtract(local.repositories, toset(["explorer"]))
  repository = aws_ecr_repository.project[each.key].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "HealthOmicsProjectWorkflows", Effect = "Allow"
      Principal = { Service = "omics.amazonaws.com" }
      Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
      Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnLike = { "aws:SourceArn" = "arn:${local.partition}:omics:${var.region}:${local.account}:workflow/*" } }
    }]
  })
}
