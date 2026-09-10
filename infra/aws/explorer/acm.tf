resource "aws_acm_certificate" "explorer" {
  count             = var.existing_certificate_arn == "" ? 1 : 0
  domain_name       = var.domain
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
}
resource "aws_route53_record" "validation" {
  for_each = var.create_delegated_zone && var.existing_certificate_arn == "" ? {
    for v in aws_acm_certificate.explorer[0].domain_validation_options : v.domain_name => v
  } : {}
  zone_id = aws_route53_zone.apps[0].zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  ttl     = 300
  records = [each.value.resource_record_value]
}
resource "aws_acm_certificate_validation" "explorer" {
  count                   = var.existing_certificate_arn == "" ? 1 : 0
  certificate_arn         = aws_acm_certificate.explorer[0].arn
  validation_record_fqdns = var.create_delegated_zone ? [for r in aws_route53_record.validation : r.fqdn] : null
  timeouts { create = "30m" }
}
