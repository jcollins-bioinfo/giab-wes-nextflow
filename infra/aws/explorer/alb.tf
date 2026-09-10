resource "aws_security_group" "alb" {
  name_prefix = "${var.name}-alb-"
  description = "Public TLS and HTTP redirect only"
  vpc_id      = var.vpc_id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_vpc_security_group_egress_rule" "alb_to_task" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.task.id
  from_port                    = 8050
  to_port                      = 8050
  ip_protocol                  = "tcp"
}
resource "aws_lb" "explorer" {
  name                       = "${var.name}-explorer"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = var.subnet_ids
  drop_invalid_header_fields = true
}
resource "aws_lb_target_group" "explorer" {
  name                 = "${var.name}-explorer"
  vpc_id               = var.vpc_id
  target_type          = "ip"
  port                 = 8050
  protocol             = "HTTP"
  deregistration_delay = 30
  health_check {
    path                = "/research/giab-wes-nextflow/explorer/readyz"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.explorer.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.explorer.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.existing_certificate_arn != "" ? var.existing_certificate_arn : aws_acm_certificate_validation.explorer[0].certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.explorer.arn
  }
}
