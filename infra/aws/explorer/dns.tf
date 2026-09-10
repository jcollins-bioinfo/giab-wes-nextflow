resource "aws_route53_zone" "apps" {
  count   = var.create_delegated_zone ? 1 : 0
  name    = var.domain
  comment = "Delegate ONLY ${var.domain}; parent zone stays at current provider."
  lifecycle {
    precondition {
      condition     = var.domain == "apps.johnpatrickcollins.info"
      error_message = "Automated delegation is limited to the explicitly approved apps subdomain."
    }
  }
}
resource "aws_route53_record" "apps" {
  count   = var.create_delegated_zone ? 1 : 0
  zone_id = aws_route53_zone.apps[0].zone_id
  name    = var.domain
  type    = "A"
  alias {
    name                   = aws_lb.explorer.dns_name
    zone_id                = aws_lb.explorer.zone_id
    evaluate_target_health = true
  }
}
output "url" { value = "https://${var.domain}/research/giab-wes-nextflow/explorer/" }
output "alb_dns_name" { value = aws_lb.explorer.dns_name }
output "name_servers" { value = try(aws_route53_zone.apps[0].name_servers, []) }
output "certificate_validation_records" {
  value = var.existing_certificate_arn == "" ? [for v in aws_acm_certificate.explorer[0].domain_validation_options : {
    name = v.resource_record_name, type = v.resource_record_type, value = v.resource_record_value
  }] : []
}
