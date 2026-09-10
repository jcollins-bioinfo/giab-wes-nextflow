resource "aws_vpc" "project" {
  count                = local.network ? 1 : 0
  cidr_block           = "10.84.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
  depends_on           = [terraform_data.safety]
}
resource "aws_internet_gateway" "project" {
  count  = local.network ? 1 : 0
  vpc_id = aws_vpc.project[0].id
}
resource "aws_subnet" "public" {
  count                   = local.network ? 2 : 0
  vpc_id                  = aws_vpc.project[0].id
  cidr_block              = cidrsubnet(aws_vpc.project[0].cidr_block, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "${local.name}-public-${count.index + 1}" }
}
resource "aws_route_table" "public" {
  count  = local.network ? 1 : 0
  vpc_id = aws_vpc.project[0].id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.project[0].id
  }
}
resource "aws_route_table_association" "public" {
  count          = local.network ? 2 : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}
resource "aws_vpc_endpoint" "s3" {
  count             = local.network ? 1 : 0
  vpc_id            = aws_vpc.project[0].id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public[0].id]
}
resource "aws_security_group" "batch" {
  count       = var.enable_batch ? 1 : 0
  name_prefix = "${local.name}-batch-"
  description = "No inbound; outbound TLS for registries/S3/AWS APIs and host bootstrap."
  vpc_id      = aws_vpc.project[0].id
  egress {
    description = "TLS to public services; VPC resolver traffic is handled by AWS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
