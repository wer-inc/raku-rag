# Minimal AWS infra for a single-VM raku-rag sales/demo environment.
# One EC2 instance + security group + Elastic IP. The instance's user-data clones the repo and runs
# deploy/sales-vm/provision.sh, which stands up the verified demo stack behind nginx on port 80.
#
#   terraform init && terraform apply -var 'allow_ssh_cidr=YOUR.IP.0.0/32'
#   # then open the printed public_url
#
# Cost: ~$60-90/mo for the instance (m6i.large) + EBS + EIP. See deploy/sales-vm/README.md.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# Latest Ubuntu 24.04 (Noble) amd64 AMI from Canonical.
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_security_group" "demo" {
  name_prefix = "raku-rag-sales-"
  description = "raku-rag single-VM sales demo"

  ingress {
    description = "HTTP (demo UI)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.allow_http_cidrs
  }
  ingress {
    description = "SSH (admin)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allow_ssh_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "raku-rag-sales", project = "raku-rag", stage = "sales" }
}

resource "aws_instance" "demo" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.demo.id]

  root_block_device {
    volume_size = var.root_volume_gb
    volume_type = "gp3"
    encrypted   = true
  }

  # Clone the repo and run the provisioner on first boot. For a PRIVATE repo, set github_token
  # (a read-only PAT) — it is used only for the clone and not persisted.
  user_data = <<-CLOUDINIT
    #!/usr/bin/env bash
    set -euxo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y && apt-get install -y git
    REPO_DIR=/opt/raku-rag
    AUTH=""
    if [ -n "${var.github_token}" ]; then AUTH="${var.github_token}@"; fi
    git clone --branch "${var.repo_branch}" --depth 1 \
      "https://$${AUTH}${replace(var.repo_url, "https://", "")}" "$REPO_DIR"
    PUBLIC_BASE="http://$(curl -fsS --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4)" \
      REPO_DIR="$REPO_DIR" bash "$REPO_DIR/deploy/sales-vm/provision.sh" >>/var/log/raku-provision.log 2>&1
  CLOUDINIT

  tags = { Name = "raku-rag-sales", project = "raku-rag", stage = "sales" }
}

resource "aws_eip" "demo" {
  instance = aws_instance.demo.id
  domain   = "vpc"
  tags     = { Name = "raku-rag-sales", project = "raku-rag" }
}
