"""
Orquestrador — varre o S3 em busca de arquivos de código e enfileira tarefas no SQS.
Execute com: python orchestrator.py --mode tests --prefix repo/src/

Ajustes v1.1:
- Agrega taxa de erro lendo contagem de mensagens na DLQ
- Calcula throughput real com base em tempo de execução medido
- Emite métricas agregadas no CloudWatch
- Salva _summary.json com campos completos que o dashboard consome
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path

import boto3

SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
SQS_DLQ_URL   = os.environ.get("SQS_DLQ_URL", "")
S3_BUCKET     = os.environ["S3_BUCKET"]
CW_NAMESPACE  = os.environ.get("CW_NAMESPACE", "Tema7/Workers")
AWS_REGION    = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

EXT_TO_LANG = {
    ".py":   "python",
    ".js":   "javascript",
    ".ts":   "typescript",
    ".java": "java",
    ".go":   "go",
    ".rb":   "ruby",
    ".cpp":  "cpp",
    ".c":    "c",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [orchestrator] %(message)s")
log = logging.getLogger("orchestrator")


def list_code_files(prefix: str) -> list:
    """Lista arquivos de código no S3 com o prefix dado."""
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    files = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            ext = Path(key).suffix.lower()
            if ext in EXT_TO_LANG:
                files.append({"file_key": key, "language": EXT_TO_LANG[ext]})
    return files


def enqueue_tasks(files: list, mode: str):
    """Publica uma mensagem SQS por arquivo."""
    sqs = boto3.client("sqs")
    for f in files:
        task = {**f, "mode": mode}
        sqs.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(task))
        log.info(f"Enfileirado: {task}")
    log.info(f"Total de tarefas enfileiradas: {len(files)}")


def get_dlq_message_count() -> int:
    """
    Lê o atributo ApproximateNumberOfMessages da DLQ para saber quantas
    mensagens falharam após maxReceiveCount tentativas.
    """
    if not SQS_DLQ_URL:
        return 0
    try:
        sqs  = boto3.client("sqs")
        resp = sqs.get_queue_attributes(
            QueueUrl=SQS_DLQ_URL,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        return int(resp["Attributes"].get("ApproximateNumberOfMessages", 0))
    except Exception as exc:
        log.warning(f"Não foi possível ler DLQ: {exc}")
        return 0


def wait_for_results(expected: int, timeout: int = 1800) -> tuple:
    """
    Aguarda até que todos os resultados apareçam no S3.
    Retorna (lista de resultados, tempo_total_segundos).
    """
    s3       = boto3.client("s3")
    deadline = time.time() + timeout
    t_start  = time.time()

    while time.time() < deadline:
        paginator = s3.get_paginator("list_objects_v2")
        count = sum(
            1
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="results/")
            for obj in page.get("Contents", [])
            if not obj["Key"].endswith("_summary.json")
        )
        log.info(f"Resultados prontos: {count}/{expected}")
        if count >= expected:
            break
        time.sleep(15)

    elapsed = time.time() - t_start

    results = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="results/"):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("_summary.json"):
                continue
            body = s3.get_object(Bucket=S3_BUCKET, Key=obj["Key"])["Body"].read()
            results.append(json.loads(body))
    return results, elapsed


def aggregate(results: list, elapsed_s: float, total_enqueued: int) -> dict:
    """Gera métricas agregadas reais e detecta inconsistências."""
    total_files         = len(results)
    total_tokens_gen    = sum(r.get("tokens_gen", 0)    for r in results)
    total_tokens_prompt = sum(r.get("tokens_prompt", 0) for r in results)
    total_latency       = sum(r.get("latency_s", 0.0)   for r in results)
    avg_latency         = total_latency / total_files if total_files else 0

    # Taxa de erro real: arquivos enfileirados mas sem resultado + DLQ
    dlq_count    = get_dlq_message_count()
    missing      = total_enqueued - total_files
    failed_total = max(missing, 0) + dlq_count
    error_rate   = (failed_total / total_enqueued * 100) if total_enqueued else 0

    # Throughput real (arquivos concluídos por minuto)
    throughput_per_min = (total_files / elapsed_s * 60) if elapsed_s > 0 else 0

    empty = [r["file_key"] for r in results if not r.get("output", "").strip()]

    summary = {
        # Campos de contagem
        "total_enqueued":      total_enqueued,
        "total_files":         total_files,
        "failed_files":        failed_total,
        "dlq_messages":        dlq_count,
        "files_with_empty_output": empty,

        # Métricas de latência e throughput
        "total_latency_s":     round(total_latency, 2),
        "avg_latency_seconds": round(avg_latency, 2),
        "elapsed_wall_s":      round(elapsed_s, 2),
        "throughput_files_per_min": round(throughput_per_min, 2),

        # Taxa de erro
        "error_rate_pct":      round(error_rate, 2),

        # Tokens
        "total_tokens_prompt": total_tokens_prompt,
        "total_tokens_gen":    total_tokens_gen,

        # Detalhes por arquivo (para o dashboard)
        "files": [
            {
                "file":      r["file_key"],
                "language":  r["language"],
                "chunks":    r.get("chunks", 1),
                "tokens_gen":r.get("tokens_gen", 0),
                "latency_s": r.get("latency_s", 0),
            }
            for r in results
        ],
    }
    return summary


def publish_summary_metrics(summary: dict):
    """Publica métricas agregadas finais no CloudWatch."""
    try:
        cw = boto3.client("cloudwatch", region_name=AWS_REGION)
        metrics = [
            ("TotalFilesProcessed",   summary["total_files"],              "Count"),
            ("TotalFilesFailed",       summary["failed_files"],             "Count"),
            ("ErrorRatePct",           summary["error_rate_pct"],           "Percent"),
            ("ThroughputFilesPerMin",  summary["throughput_files_per_min"], "Count/Second"),
            ("AvgLatencyPerFile",      summary["avg_latency_seconds"],      "Seconds"),
            ("TotalTokensGenerated",   summary["total_tokens_gen"],         "Count"),
        ]
        cw.put_metric_data(
            Namespace=CW_NAMESPACE,
            MetricData=[
                {"MetricName": name, "Value": value, "Unit": unit,
                 "Dimensions": [{"Name": "Component", "Value": "Orchestrator"}]}
                for name, value, unit in metrics
            ],
        )
        log.info("Métricas publicadas no CloudWatch")
    except Exception as exc:
        log.warning(f"Falha ao publicar métricas no CloudWatch: {exc}")


def save_summary(summary: dict):
    s3  = boto3.client("s3")
    key = "results/_summary.json"
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    log.info(f"Sumário salvo em s3://{S3_BUCKET}/{key}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orquestrador Tema 7")
    parser.add_argument("--prefix",   default="repo/",  help="Prefixo S3 dos arquivos de código")
    parser.add_argument("--mode",     default="tests",  choices=["tests", "smells", "docs"])
    parser.add_argument("--no-wait",  action="store_true", help="Só enfileira, não aguarda resultados")
    args = parser.parse_args()

    files = list_code_files(args.prefix)
    if not files:
        log.error(f"Nenhum arquivo encontrado em s3://{S3_BUCKET}/{args.prefix}")
        raise SystemExit(1)

    enqueue_tasks(files, args.mode)

    if not args.no_wait:
        results, elapsed = wait_for_results(expected=len(files))
        summary = aggregate(results, elapsed, total_enqueued=len(files))
        publish_summary_metrics(summary)
        save_summary(summary)
