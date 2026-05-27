data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

data "aws_s3_bucket" "tema7" {
  bucket = var.bucket_name
}

resource "aws_sqs_queue" "dlq" {
  name = var.dlq_name
  tags = { Project = "tema7" }
}

resource "aws_sqs_queue" "tasks" {
  name                       = var.queue_name
  visibility_timeout_seconds = 900
  message_retention_seconds  = 345600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
  tags = { Project = "tema7" }
}

resource "aws_cloudwatch_metric_alarm" "dlq_alarm" {
  alarm_name          = "tema7-dlq-not-empty"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Messages in DLQ indicate repeated worker failures"
  dimensions = {
    QueueName = aws_sqs_queue.dlq.name
  }
}

resource "aws_security_group" "worker_sg" {
  name        = "tema7-worker-sg"
  description = "SSH access and internet egress"
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "worker" {
  count                  = var.worker_count
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = var.instance_type
  iam_instance_profile   = "LabInstanceProfile"
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.worker_sg.id]

  root_block_device {
    volume_size = 30
  }

  user_data = <<-USERDATA
    #!/bin/bash
    set -euo pipefail
    dnf update -y
    dnf install -y python3 python3-pip git
    curl -fsSL https://ollama.com/install.sh | sh
    systemctl enable --now ollama || true
    sleep 10
    ollama pull ${var.ollama_model}
    pip3 install boto3 requests
    cat >> /etc/environment << ENV
    SQS_QUEUE_URL=${aws_sqs_queue.tasks.url}
    SQS_DLQ_URL=${aws_sqs_queue.dlq.url}
    S3_BUCKET=${var.bucket_name}
    OLLAMA_MODEL=${var.ollama_model}
    AWS_DEFAULT_REGION=${var.aws_region}
    ENV
  USERDATA

  tags = {
    Name     = "tema7-worker-${count.index + 1}"
    Project  = "tema7"
    WorkerId = tostring(count.index + 1)
  }
}
