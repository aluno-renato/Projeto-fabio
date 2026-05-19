# Tema 7 — Gerador Paralelo de Testes e Análise de Código

Sistema distribuído que distribui arquivos de código entre workers EC2, chama um
SLM (Ollama) para gerar testes, detectar code smells ou produzir documentação, e
agrega os resultados via S3.

## Arquitetura

```
[Orquestrador EC2]
      │  lista arquivos no S3
      │  publica 1 mensagem SQS por arquivo
      ▼
[SQS Queue] ──────────────────────────────────────┐
      │                                            │
[Worker EC2 #1]                           [Worker EC2 #2]
  consome msg                               consome msg
  baixa código S3                           baixa código S3
  chama Ollama (localhost)                  chama Ollama (localhost)
  salva resultado S3                        salva resultado S3
      │                                            │
      └─────────────────┬──────────────────────────┘
                        ▼
              [S3 results/] ← Orquestrador agrega e salva _summary.json
```

**Componentes AWS usados:** EC2, SQS (+ DLQ automática), S3, CloudWatch (logs via
stdout → CloudWatch Agent ou journald).

## Pré-requisitos

- AWS CLI configurado com credenciais do Academy
- Python 3.10+
- Ollama instalado nas instâncias EC2 workers

## Setup Rápido

### 1. Criar recursos AWS (manual ou via console)

- **SQS:** crie uma fila padrão chamada `tema7-tasks`. Configure uma DLQ chamada
  `tema7-dlq` com `maxReceiveCount=3`.
- **S3:** crie um bucket, ex: `tema7-codigo-SEU_NOME`.
- **EC2:** suba 2 instâncias `t3.large` (CPU) ou `g4dn.xlarge` (GPU) com Amazon
  Linux 2023. Associe uma IAM Role com permissões de SQS e S3.

### 2. Definir variáveis de ambiente (em cada instância EC2)

```bash
export SQS_QUEUE_URL="https://sqs.us-east-1.amazonaws.com/123456789/tema7-tasks"
export SQS_DLQ_URL="https://sqs.us-east-1.amazonaws.com/123456789/tema7-dlq"
export S3_BUCKET="tema7-codigo-SEU_NOME"
export OLLAMA_MODEL="mistral"   # ou llama3.2, gemma3:2b, etc.
export AWS_DEFAULT_REGION="us-east-1"
```

### 3. Instalar dependências

```bash
pip install boto3 requests
```

### 4. Fazer upload do código a analisar

```bash
bash scripts/upload_repo.sh /caminho/para/seu/repo
```

### 5. Subir os workers

```bash
# Em cada instância EC2:
bash scripts/deploy_workers.sh 2 tests
```

### 6. Rodar o orquestrador (pode ser na mesma máquina ou no seu PC)

```bash
python orchestrator/orchestrator.py --prefix repo/ --mode tests
```

O orquestrador aguarda os resultados e salva `results/_summary.json` no S3.

## Modos disponíveis

| Modo     | Descrição                                      |
|----------|------------------------------------------------|
| `tests`  | Gera testes unitários pytest                   |
| `smells` | Detecta code smells (saída JSON)               |
| `docs`   | Adiciona docstrings Google-style ao código     |

## Prompts versionados

Todos os system prompts ficam em `prompts/`. Cada arquivo tem cabeçalho com versão.
Para mudar o comportamento do modelo, edite o arquivo correspondente e incremente
a versão — **não altere o código Python**.

## Tolerância a falhas

- **Retry com backoff:** o worker tenta até `MAX_RETRIES=3` vezes com espera
  exponencial (`2^tentativa` segundos) antes de desistir.
- **DLQ:** mensagens que falharam 3 vezes são movidas automaticamente para
  `tema7-dlq` pelo SQS. Inspecione com `aws sqs receive-message --queue-url $SQS_DLQ_URL`.
- **Fallback:** se o Ollama estiver fora, o worker loga o erro e não deleta a
  mensagem, que será reprocessada por outro worker.

## O que falta implementar (para seu parceiro)

- [ ] Terraform / CloudFormation para criar SQS + S3 + IAM Role
- [ ] CloudWatch Agent para coletar logs estruturados das instâncias
- [ ] Dashboard CloudWatch com latência, throughput e tokens consumidos
- [ ] Prompts para outras linguagens (JavaScript, Java etc.) — copie o padrão de `tests_python.txt`
- [ ] Script de coleta de métricas que lê `_summary.json` e gera gráficos (matplotlib)
- [ ] Relatório técnico com os resultados experimentais

## Testando localmente (sem AWS)

Você pode rodar o worker apontando para filas/buckets locais com LocalStack:

```bash
pip install localstack awscli-local
localstack start -d
awslocal sqs create-queue --queue-name tema7-tasks
awslocal s3 mb s3://tema7-local
export SQS_QUEUE_URL="http://localhost:4566/000000000000/tema7-tasks"
export S3_BUCKET="tema7-local"
export AWS_DEFAULT_REGION="us-east-1"
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
python workers/worker.py --worker-id 1
```
