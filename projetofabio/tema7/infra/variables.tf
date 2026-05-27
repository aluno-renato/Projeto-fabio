variable "bucket_name" {
  description = "Nome do bucket S3 para armazenar código e resultados"
  type        = string
}

variable "queue_name" {
  description = "Nome da fila SQS de tarefas"
  type        = string
  default     = "tema7-tasks"
}

variable "dlq_name" {
  description = "Nome da Dead Letter Queue"
  type        = string
  default     = "tema7-dlq"
}

variable "instance_type" {
  description = "Tipo de instância EC2 para os workers"
  type        = string
  default     = "t3.large"
}

variable "key_name" {
  description = "Nome do par de chaves EC2 para acesso SSH"
  type        = string
}

variable "allowed_ssh_cidr" {
  description = "CIDR permitido para SSH (use o seu IP: ex. 203.0.113.0/32)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "worker_count" {
  description = "Número de instâncias EC2 worker a provisionar (paralelismo real)"
  type        = number
  default     = 2
}

variable "ollama_model" {
  description = "Modelo Ollama a baixar automaticamente nas instâncias"
  type        = string
  default     = "mistral"
}

variable "aws_region" {
  description = "Região AWS"
  type        = string
  default     = "us-east-1"
}
