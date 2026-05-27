output "s3_bucket" {
  value = data.aws_s3_bucket.tema7.bucket
}

output "sqs_queue_url" {
  value = aws_sqs_queue.tasks.url
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "worker_public_ips" {
  value = aws_instance.worker[*].public_ip
}

output "worker_instance_ids" {
  value = aws_instance.worker[*].id
}

output "worker_count" {
  value = var.worker_count
}
