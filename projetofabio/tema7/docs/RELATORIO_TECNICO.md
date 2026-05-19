# Relatório Técnico — Processamento Paralelo de Repositórios com SLM

## 1. Introdução

Este projeto implementa um pipeline distribuído para análise automatizada de código-fonte utilizando Small Language Models executados localmente com Ollama. A proposta é permitir que arquivos de um repositório sejam processados em paralelo por múltiplos workers, aumentando a vazão do sistema e reduzindo o tempo total de execução.

A arquitetura utiliza serviços da AWS para armazenamento, mensageria, execução e observabilidade. O S3 armazena os arquivos de entrada e os resultados. A fila SQS distribui as tarefas entre os workers. A DLQ recebe mensagens que falham repetidamente. A EC2 executa os workers. O CloudWatch coleta logs e métricas.

## 2. Arquitetura

A solução é composta por:

- **S3**: armazenamento dos arquivos do repositório e dos resultados gerados.
- **SQS**: fila principal de tarefas.
- **DLQ**: fila de mensagens com falha após múltiplas tentativas.
- **EC2**: ambiente de execução dos workers e do Ollama.
- **Ollama**: motor local de inferência com SLM.
- **Worker**: componente que consome mensagens, faz chunking, chama o modelo e salva a saída.
- **Orchestrator**: componente que lista arquivos, cria tarefas e consolida métricas.
- **CloudWatch**: observabilidade dos logs estruturados e métricas da infraestrutura.

## 3. Estratégia de Paralelismo

O paralelismo é baseado na divisão do repositório em tarefas independentes. Cada arquivo de código encontrado no S3 gera uma mensagem na fila SQS. Os workers consomem essas mensagens de forma concorrente, permitindo escalabilidade horizontal.

Cada worker executa as seguintes etapas:

1. Busca uma mensagem na SQS.
2. Baixa o arquivo correspondente no S3.
3. Divide o conteúdo em chunks.
4. Envia os chunks para o Ollama.
5. Aplica retry com backoff exponencial em caso de falha.
6. Salva o resultado no S3.
7. Registra logs estruturados em JSON.
8. Remove a mensagem da fila após sucesso.

## 4. Engenharia de Prompt

Os prompts foram separados do código-fonte e versionados individualmente. Isso facilita manutenção, auditoria e evolução da estratégia de geração.

Existem prompts para:

- geração de testes automatizados;
- análise de code smells;
- geração de documentação técnica.

A estrutura permite expansão para outras linguagens, como JavaScript, Java, Go ou TypeScript, mantendo o mesmo padrão.

## 5. Tolerância a Falhas

O sistema utiliza retry com backoff exponencial no worker para lidar com falhas temporárias em chamadas ao modelo. Além disso, a fila SQS está configurada com uma Dead Letter Queue. Caso uma mensagem falhe repetidamente, ela é redirecionada para a DLQ, evitando bloqueio do processamento geral.

## 6. Observabilidade

Os logs são estruturados em JSON, facilitando indexação, consulta e criação de métricas. O CloudWatch Agent coleta os logs do worker e métricas da instância EC2, como CPU, memória e disco.

As principais métricas observadas são:

- total de arquivos processados;
- total de falhas;
- latência média;
- quantidade de chunks;
- mensagens pendentes na SQS;
- mensagens na DLQ;
- throughput em arquivos por minuto.

## 7. Resultados Esperados

Espera-se que o aumento no número de workers reduza o tempo total de processamento. A métrica de throughput deve crescer conforme mais workers são adicionados, até o limite imposto por CPU, memória, rede ou capacidade de inferência do Ollama.

Os gráficos gerados pelo script `dashboard/generate_metrics_charts.py` podem ser usados no relatório final para demonstrar latência, throughput e volume processado.

## 8. Conclusão

A arquitetura proposta demonstra uma solução escalável, desacoplada e tolerante a falhas para processamento paralelo de repositórios com SLM. O uso de SQS permite distribuir tarefas entre múltiplos workers. O S3 centraliza entradas e saídas. O CloudWatch melhora a rastreabilidade operacional. A separação dos prompts torna o sistema extensível para novos modos de análise e novas linguagens.

Como melhorias futuras, recomenda-se adicionar Auto Scaling Group, containerização com ECS, dashboard em Grafana, API REST para submissão de repositórios e suporte automático a múltiplas linguagens.
