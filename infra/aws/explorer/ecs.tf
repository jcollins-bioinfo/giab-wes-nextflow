resource "aws_ecs_cluster" "explorer" {
  name = "${var.name}-explorer"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}
resource "aws_security_group" "task" {
  name_prefix = "${var.name}-explorer-task-"
  description = "Only ALB can reach the Explorer; outbound TLS for image/log startup."
  vpc_id      = var.vpc_id
  ingress {
    description     = "Explorer from ALB only"
    from_port       = 8050
    to_port         = 8050
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    description = "ECR and CloudWatch HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_ecs_task_definition" "explorer" {
  family                   = "${var.name}-explorer"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  volume { name = "tmp" }
  container_definitions = jsonencode([{
    name                   = "explorer", image = var.image, essential = true
    readonlyRootFilesystem = true
    portMappings           = [{ containerPort = 8050, hostPort = 8050, protocol = "tcp" }]
    mountPoints            = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]
    linuxParameters        = { initProcessEnabled = true }
    stopTimeout            = 30
    healthCheck = {
      command     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8050/research/giab-wes-nextflow/explorer/healthz',timeout=3)"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
    logConfiguration = {
      logDriver = "awslogs"
      options   = { awslogs-group = var.log_group_name, awslogs-region = var.region, awslogs-stream-prefix = "explorer", mode = "blocking" }
    }
  }])
  lifecycle {
    precondition {
      condition     = startswith(var.image, "${var.repository_url}@sha256:") && can(regex("@sha256:[a-f0-9]{64}$", var.image))
      error_message = "Build, scan and pin the project's own Explorer ECR image before enabling its service."
    }
  }
}
resource "aws_ecs_service" "explorer" {
  name                               = "${var.name}-explorer"
  cluster                            = aws_ecs_cluster.explorer.id
  task_definition                    = aws_ecs_task_definition.explorer.arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "1.4.0"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60
  wait_for_steady_state              = true
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.explorer.arn
    container_name   = "explorer"
    container_port   = 8050
  }
  depends_on = [aws_lb_listener.https]
}
