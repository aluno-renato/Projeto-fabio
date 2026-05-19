variable "aws_region" {
  description = "Região AWS onde os recursos serão criados."
  type        = string
  default     = "us-east-1"
}

variable "bucket_name" {
  description = "Nome único do bucket S3 usado para entrada e saída dos arquivos."
  type        = string
}

variable "queue_name" {
  description = "Nome da fila principal SQS."
  type        = string
  default     = "tema7-tasks"
}

variable "dlq_name" {
  description = "Nome da Dead Letter Queue."
  type        = string
  default     = "tema7-dlq"
}

variable "instance_type" {
  description = "Tipo da instância EC2 usada para executar os workers."
  type        = string
  default     = "t3.large"
}

variable "key_name" {
  description = "Nome da chave SSH cadastrada na AWS."
  type        = string
}

variable "allowed_ssh_cidr" {
  description = "CIDR permitido para SSH. Em ambiente real, use seu IP público /32."
  type        = string
  default     = "0.0.0.0/0"
}
