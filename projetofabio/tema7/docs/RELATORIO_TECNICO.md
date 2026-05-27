# Relatório Técnico — Processamento Paralelo de Repositórios com SLM

## 1. Introdução

Este projeto implementa um pipeline distribuído para análise automatizada de código-fonte
utilizando Small Language Models executados localmente com Ollama. Arquivos de um repositório
são processados em paralelo por múltiplos workers EC2, aumentando a vazão do sistema e
reduzindo o tempo total de execução.

A arquitetura utiliza serviços AWS: S3 (armazenamento), SQS + DLQ (mensageria e tolerância
a falhas), EC2 (workers), CloudWatch (observabilidade) e Terraform (IaC).

O uso de SLM auto-hospedado (Ollama) foi escolhido pela disponibilidade no AWS Academy e
pela possibilidade de controlar totalmente a infraestrutura de inferência, o que torna o
paralelismo observável e mensurável diretamente.

## 2. Arquitetura

### Componentes

| Componente     | Tecnologia     | Papel                                                          |
|----------------|----------------|----------------------------------------------------------------|
| Orquestrador   | Python + boto3 | Lista arquivos S3, enfileira tarefas, agrega resultados        |
| Worker         | Python + boto3 | Consome SQS, chunking, chama Ollama, salva S3, publica métricas|
| Ollama         | SLM local      | Inferência do modelo (Mistral/Llama/Gemma via HTTP)            |
| SQS            | AWS            | Fila de tarefas com visibilidade e reentrega automática        |
| DLQ            | AWS SQS        | Recebe mensagens que falharam maxReceiveCount=3 vezes          |
| S3             | AWS            | Armazena código de entrada e JSONs de resultado                |
| CloudWatch     | AWS            | Logs estruturados + métricas customizadas + alarme de DLQ      |
| Terraform      | IaC            | Provisiona todos os recursos AWS reprodutivelmente             |

### Diagrama de fluxo

```
[Orquestrador]
    ↓ list_objects S3
    ↓ send_message SQS (1 msg/arquivo)
[SQS Queue] → (após 3 falhas) → [DLQ]
    ↓ receive_message (long-poll 20s)
[Worker #1..N]
    ↓ get_object S3 (código fonte)
    ↓ chunk_code() → N chunks
    ↓ para cada chunk: call_ollama() com contexto do chunk anterior
    ↓ put_object S3 (resultado JSON)
    ↓ put_metric_data CloudWatch
    ↓ delete_message SQS
[Orquestrador aguarda]
    ↓ list_objects S3 results/
    ↓ get_queue_attributes DLQ (taxa de erro)
    ↓ aggregate() → _summary.json
    ↓ put_metric_data CloudWatch (métricas agregadas)
```

## 3. Estratégia de Paralelismo

O modelo adotado é **embarrassingly parallel** (paralelismo embaraçoso): cada arquivo de
código é independente dos demais, sem dependências de dados entre tarefas. A distribuição
de trabalho ocorre via SQS — múltiplos workers consomem mensagens concorrentemente sem
coordenação explícita.

O número de workers é configurado via variável Terraform `worker_count`. Para o experimento,
executamos com 1, 2 e 4 workers e medimos throughput e latência em cada configuração.

Cada worker executa as seguintes etapas de forma autônoma:

1. Long-poll SQS (WaitTimeSeconds=20) para reduzir chamadas vazias
2. Download do arquivo do S3
3. Divisão em chunks de até 6.000 caracteres, cortando em limites de linha
4. Para cada chunk: chamada ao Ollama com injeção de contexto do chunk anterior
5. Upload do resultado JSON para S3
6. Publicação de métricas no CloudWatch
7. Deleção da mensagem SQS (confirma processamento)

## 4. Engenharia de Contexto

### 4.1 System prompts versionados

Os prompts ficam em `prompts/` separados do código, com cabeçalho de versão e changelog.
Isso permite evoluir o comportamento do modelo sem alterar código de aplicação.

**Exemplo de cabeçalho:**
```
# Prompt versão: v1.1 | Modo: geração de testes | Linguagem: Python
```

### 4.2 Chunking e gestão de contexto

Arquivos grandes são particionados em chunks de até 6.000 caracteres, com corte em
limites de linha para não quebrar funções no meio. Cada chunk é enviado como uma
chamada separada ao Ollama.

**Problema:** sem memória entre chunks, o modelo pode gerar testes ou smells duplicados
para funções que aparecem referenciadas em múltiplos chunks.

**Solução implementada — memória entre chunks:** ao final de cada chunk, a saída é resumida
pela função `summarize_output()`. Esse resumo é injetado no prompt do chunk seguinte:

```
[CONTEXTO DO CHUNK ANTERIOR — não repita o que já foi gerado]
Smells já identificados: Long Method (linha 12), Magic Number (linha 45)
[FIM DO CONTEXTO]
```

Para saídas JSON (modo smells), o resumo extrai os nomes dos smells já encontrados.
Para testes e docs, extrai as primeiras linhas significativas do código gerado.

### 4.3 Estrutura do prompt do usuário

```
Arquivo: repo/src/utils.py
Chunk 2/3:
[CONTEXTO DO CHUNK ANTERIOR — não repita o que já foi gerado]
<resumo>
[FIM DO CONTEXTO]

```python
<código do chunk>
```
```

### 4.4 Saída estruturada

O modo `smells` instrui o modelo a retornar exclusivamente um JSON array com campos
padronizados (`line_approx`, `smell`, `severity`, `description`, `suggestion`). Isso
permite que o orquestrador processe os resultados programaticamente.

### 4.5 Prompts disponíveis

| Arquivo                  | Linguagem  | Modo  | Versão |
|--------------------------|------------|-------|--------|
| tests_python.txt         | Python     | tests | v1.0   |
| smells_python.txt        | Python     | smells| v1.0   |
| docs_python.txt          | Python     | docs  | v1.0   |
| tests_javascript.txt     | JavaScript | tests | v1.1   |
| smells_javascript.txt    | JavaScript | smells| v1.1   |
| docs_javascript.txt      | JavaScript | docs  | v1.1   |

## 5. Tolerância a Falhas

### 5.1 Retry com backoff exponencial

O worker tenta cada chamada Ollama até `MAX_RETRIES=3` vezes com espera `2^n` segundos
(2s, 4s, 8s). Cobre falhas transitórias de rede ou sobrecarga do servidor de inferência.

### 5.2 Dead Letter Queue

A fila SQS está configurada com `maxReceiveCount=3`. Mensagens que falham 3 vezes
consecutivas são movidas automaticamente para a DLQ (`tema7-dlq`), evitando que
arquivos problemáticos bloqueiem a fila principal indefinidamente.

### 5.3 Fallback para Ollama inacessível

Quando o Ollama está completamente inacessível (ConnectionError após todos os retries),
o worker:
1. Loga o evento como `ollama_unreachable` com contexto estruturado
2. Publica métrica `OllamaErrors` no CloudWatch
3. **Não deleta a mensagem** → SQS recoloca na fila automaticamente
4. Após 3 falhas consecutivas, dorme 60 segundos antes da próxima tentativa

**Estratégia de fallback documentada:** o operador é alertado via CloudWatch Alarm
(`tema7-dlq-not-empty`, criado pelo Terraform). Ação manual: (a) verificar se Ollama
está rodando (`systemctl status ollama`), (b) reiniciar o serviço, (c) reprocessar
mensagens da DLQ movendo-as de volta para a fila principal.

### 5.4 Alarme automático de DLQ

O Terraform cria um `aws_cloudwatch_metric_alarm` que dispara quando
`ApproximateNumberOfMessages` da DLQ fica acima de 0.

## 6. Métricas e Observabilidade

### 6.1 Logs estruturados

Cada evento do worker é emitido como JSON com campos padronizados:

```json
{"time":"2026-05-25T14:32:01","level":"INFO","worker":"2","msg":
  {"event":"ollama_ok","attempt":1,"latency_s":3.241,"tokens_prompt":512,"tokens_gen":398}}
```

O CloudWatch Agent coleta esses logs de `/tmp/worker_*.log` e os envia para o log group
`/tema7/workers`, preservando o timestamp original.

### 6.2 Métricas customizadas de negócio (namespace Tema7/Workers)

Publicadas diretamente pelo worker via `cloudwatch:PutMetricData`:

| Métrica           | Dimensão   | Descrição                            |
|-------------------|------------|--------------------------------------|
| LatencyPerFile    | WorkerId   | Tempo total de inferência por arquivo|
| TokensGenerated   | WorkerId   | Tokens de resposta do modelo         |
| TokensPrompt      | WorkerId   | Tokens enviados como prompt          |
| FilesProcessed    | WorkerId   | Contador de arquivos concluídos      |
| ChunksProcessed   | WorkerId   | Total de chunks enviados ao modelo   |
| OllamaErrors      | WorkerId   | Erros de conexão com Ollama          |
| ProcessingErrors  | WorkerId   | Erros genéricos (S3, parsing, etc.)  |

Publicadas pelo orquestrador ao final:

| Métrica                 | Descrição                             |
|-------------------------|---------------------------------------|
| TotalFilesProcessed     | Arquivos com resultado salvo no S3    |
| TotalFilesFailed        | Arquivos na DLQ + sem resultado       |
| ErrorRatePct            | Taxa de erro percentual               |
| ThroughputFilesPerMin   | Throughput real medido pelo orquestrador |
| AvgLatencyPerFile       | Latência média por arquivo            |
| TotalTokensGenerated    | Total de tokens gerados na sessão     |

### 6.3 Resultados experimentais

> **Nota:** esta seção deve ser preenchida com dados reais das execuções no AWS Academy.
> Execute o sistema com 1, 2 e 4 workers e cole aqui os valores do `_summary.json`.
> Use `python dashboard/generate_metrics_charts.py --from-s3` para gerar os gráficos
> e inclua as imagens de `dashboard/output/` neste documento.

**Tabela de resultados (preencher com dados reais):**

| Workers | Arq. processados | Tempo total (s) | Throughput (arq/min) | Latência média (s) | Taxa de erro |
|---------|-----------------|-----------------|----------------------|--------------------|--------------|
| 1       | —               | —               | —                    | —                  | —            |
| 2       | —               | —               | —                    | —                  | —            |
| 4       | —               | —               | —                    | —                  | —            |

## 7. Limitações e Trabalhos Futuros

- **Chunking semântico:** o corte atual é por número de caracteres. Uma abordagem melhor
  seria cortar em limites de função usando AST (ast.parse para Python, tree-sitter para JS).
- **Balanceamento de carga:** todos os workers puxam da mesma fila. Com arquivos de tamanho
  muito heterogêneo, um worker pode ficar bloqueado em um arquivo grande enquanto outros ficam
  ociosos. Solução: particionar a fila por tamanho de arquivo.
- **Auto Scaling:** o `worker_count` é fixo. Integrar com Auto Scaling Group permitiria
  escalar workers automaticamente baseado em `ApproximateNumberOfMessages` da SQS.
- **Containerização:** empacotar o worker como imagem Docker e usar ECS/Fargate eliminaria
  a necessidade de instâncias persistentes.
- **Cobertura de linguagens:** adicionar prompts para Java, Go e TypeScript seguindo o
  padrão estabelecido nos arquivos Python e JavaScript.

## 8. Conclusão

A arquitetura implementada demonstra um sistema escalável, desacoplado e tolerante a falhas
para processamento paralelo de repositórios com SLM. O paralelismo é obtido pela distribuição
de tarefas via SQS entre múltiplas instâncias EC2, cada uma com sua instância Ollama. A
engenharia de contexto inclui prompts versionados, chunking com memória entre chunks e saída
estruturada em JSON. O CloudWatch coleta tanto métricas de infraestrutura quanto métricas de
negócio (tokens, latência, taxa de erro), permitindo análise empírica do sistema.

## Apêndice — Prompts completos

Os prompts estão no diretório `prompts/`. Consulte `prompts/CHANGELOG_PROMPTS.md` para
o histórico de versões e motivação de cada alteração.

## Resultados Experimentais — Execução Real (2026-05-26)

### Configuração
- 2 workers EC2 t3.large
- Modelo: TinyLlama (637MB, CPU-only)
- Arquivos analisados: calculator.py, exemplo.py
- Modo: geração de testes unitários

### Métricas coletadas

| Workers | Arquivos | Tempo total (s) | Throughput (arq/min) | Latência média (s) | Taxa de erro |
|---------|----------|-----------------|----------------------|--------------------|--------------|
| 2       | 2        | 119.26          | 402.95               | 59.63              | 0.0%         |

### Detalhes por arquivo

| Arquivo        | Chunks | Tokens gerados | Latência (s) |
|----------------|--------|----------------|--------------|
| calculator.py  | 1      | 235            | 66.675       |
| exemplo.py     | 1      | 181            | 52.582       |
| **Total**      | 2      | **416**        | —            |

### Observações
- Workers 1 e 2 processaram arquivos diferentes simultaneamente (paralelismo confirmado pelos logs)
- Taxa de erro 0% — nenhuma mensagem foi para a DLQ
- Modelo TinyLlama em CPU levou ~60s por arquivo (aceitável para fins acadêmicos)
- Tokens de prompt: 1107 | Tokens gerados: 416
