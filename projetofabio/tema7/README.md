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
[Worker EC2 #1]                           [Worker EC2 #2..N]
  consome msg                               consome msg
  baixa código S3                           baixa código S3
  chama Ollama (localhost)                  chama Ollama (localhost)
  chunking + memória entre chunks           chunking + memória entre chunks
  salva resultado S3                        salva resultado S3
  publica métricas CloudWatch               publica métricas CloudWatch
      │                                            │
      └─────────────────┬──────────────────────────┘
                        ▼
              [S3 results/] ← Orquestrador agrega, calcula taxa de erro,
                               lê DLQ, salva _summary.json e publica no CW
```

**Componentes AWS:** EC2 (N workers via Terraform `worker_count`), SQS + DLQ
automática, S3, CloudWatch (logs + métricas customizadas + alarme de DLQ).

## Pré-requisitos

- AWS CLI configurado com credenciais do Academy
- Python 3.10+
- Terraform >= 1.5 (para provisionamento)

## Setup Rápido

### 1. Provisionar infraestrutura com Terraform

```bash
cd infra/
cp terraform.tfvars.example terraform.tfvars
# edite terraform.tfvars: bucket_name, key_name, worker_count
terraform init
terraform apply
```

O Terraform cria: S3, SQS, DLQ, IAM Role, Security Group e `worker_count` instâncias
EC2. Cada instância já instala Ollama e baixa o modelo automaticamente via user_data.

### 2. Exportar variáveis de ambiente

```bash
# Use os outputs do terraform apply:
export SQS_QUEUE_URL=$(terraform -chdir=infra output -raw sqs_queue_url)
export SQS_DLQ_URL=$(terraform -chdir=infra output -raw dlq_url)
export S3_BUCKET=$(terraform -chdir=infra output -raw s3_bucket)
export OLLAMA_MODEL="mistral"
export AWS_DEFAULT_REGION="us-east-1"
```

### 3. Fazer upload do código a analisar

```bash
bash scripts/upload_repo.sh https://github.com/aluno-renato/Projeto-fabio/tree/main
```

### 4. Subir os workers (em cada instância EC2)

```bash
# SSH na instância:
ssh -i sua-chave.pem ec2-user@<IP>
# Clonar o repositório e subir workers:
git clone https://github.com/aluno-renato/Projeto-fabio/tree/main && cd tema7
bash scripts/deploy_workers.sh 2 tests
```

### 5. Rodar o orquestrador

```bash
python orchestrator/orchestrator.py --prefix repo/ --mode tests
```

O orquestrador aguarda os resultados, lê a DLQ para calcular taxa de erro real,
publica métricas no CloudWatch e salva `results/_summary.json` no S3.

### 6. Gerar gráficos

```bash
# A partir do S3 (após execução real):
python dashboard/generate_metrics_charts.py --from-s3

# Para análise de escala (múltiplos runs com N workers diferentes):
python dashboard/generate_metrics_charts.py --multi-run run_1w.json run_2w.json run_4w.json
```

## Modos disponíveis

| Modo     | Descrição                                          |
|----------|----------------------------------------------------|
| `tests`  | Gera testes unitários (pytest / Jest)              |
| `smells` | Detecta code smells (saída JSON estruturada)       |
| `docs`   | Adiciona docstrings/JSDoc ao código                |

## Linguagens suportadas

Python, JavaScript, TypeScript, Java, Go, Ruby, C++, C.

## Prompts versionados

Todos os system prompts ficam em `prompts/`. Cada arquivo tem cabeçalho com versão
e modo. Para mudar o comportamento do modelo, edite o arquivo e incremente a versão
no cabeçalho — **nunca altere o código Python para mudar comportamento do LLM**.
Consulte `prompts/CHANGELOG_PROMPTS.md` para o histórico completo.

## Memória entre chunks

Quando um arquivo é maior que 6.000 caracteres, o worker o divide em chunks.
Para evitar que o modelo gere testes/smells duplicados entre chunks, a saída
de cada chunk é resumida e injetada como contexto no prompt do chunk seguinte:

```
[CONTEXTO DO CHUNK ANTERIOR — não repita o que já foi gerado]
<resumo compacto da saída anterior>
[FIM DO CONTEXTO]
```

## Tolerância a Falhas

| Ponto crítico           | Estratégia                                                          |
|-------------------------|---------------------------------------------------------------------|
| Ollama inacessível      | Retry com backoff `2^n` s (até MAX_RETRIES=3) → não deleta msg → SQS recoloca |
| 3 falhas consecutivas   | Worker dorme 60s (cooling down) antes de tentar próxima mensagem   |
| Mensagem falha 3× total | SQS move automaticamente para DLQ (maxReceiveCount=3)              |
| DLQ com mensagens       | CloudWatch Alarm dispara (criado pelo Terraform)                    |
| Fallback documentado    | Operador inspeciona DLQ, reinspeciona logs e decide reprocessar     |

## Métricas coletadas

| Métrica                  | Origem          | Namespace CloudWatch     |
|--------------------------|-----------------|--------------------------|
| Latência por arquivo (s) | Worker → CW     | Tema7/Workers            |
| Tokens gerados           | Worker → CW     | Tema7/Workers            |
| Tokens de prompt         | Worker → CW     | Tema7/Workers            |
| Arquivos processados     | Worker → CW     | Tema7/Workers            |
| Erros de Ollama          | Worker → CW     | Tema7/Workers            |
| Taxa de erro (%)         | Orchestrator→CW | Tema7/Workers            |
| Throughput (arq/min)     | Orchestrator→CW | Tema7/Workers            |
| Msgs na DLQ              | SQS nativo      | AWS/SQS                  |
| CPU/Mem/Disco            | CW Agent        | Tema7/Infrastructure     |

## Testando localmente (sem AWS)

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
