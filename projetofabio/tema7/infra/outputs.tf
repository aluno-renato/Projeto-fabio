output "s3_bucket" {
  value = aws_s3_bucket.tema7.bucket
}

output "sqs_queue_url" {
  value = aws_sqs_queue.tasks.url
}

output "sqs_dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "ec2_public_ip" {
  value = aws_instance.worker.public_ip
}
