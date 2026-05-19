# Complementos adicionados

Este pacote mantém todos os arquivos originais enviados e adiciona os itens que faltavam para completar o trabalho.

## Novas pastas

```text
infra/       Terraform para criar S3, SQS, DLQ, IAM, Security Group e EC2
cloudwatch/  Configuração e instalação do CloudWatch Agent
dashboard/   Script Python para gerar gráficos de métricas
docs/        Relatório técnico e guia de execução completo
diagrams/    Diagrama Mermaid da arquitetura
```

## Novos prompts

```text
prompts/tests_javascript.txt
prompts/smells_javascript.txt
prompts/docs_javascript.txt
```

## Entregáveis cobertos

- Worker paralelo com SQS
- Orchestrator
- Chunking
- Retry com backoff
- Persistência no S3
- Logs estruturados
- Prompts versionados
- IaC com Terraform
- CloudWatch Agent
- Dashboard por gráficos
- Relatório técnico
- Diagrama de arquitetura
