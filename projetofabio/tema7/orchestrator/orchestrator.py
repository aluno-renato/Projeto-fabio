"""
Orquestrador — varre o S3 em busca de arquivos de código e enfileira tarefas no SQS.
Execute com: python orchestrator.py --mode tests --prefix repo/src/

Depois aguarda os resultados e gera o relatório final agregado.
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path

import boto3

SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
S3_BUCKET     = os.environ["S3_BUCKET"]

# Extensões suportadas → linguagem inferida
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


def list_code_files(prefix: str) -> list[dict]:
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


def enqueue_tasks(files: list[dict], mode: str):
    """Publica uma mensagem SQS por arquivo."""
    sqs = boto3.client("sqs")
    for f in files:
        task = {**f, "mode": mode}
        sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(task),
        )
        log.info(f"Enfileirado: {task}")
    log.info(f"Total de tarefas enfileiradas: {len(files)}")


def wait_for_results(expected: int, timeout: int = 1800) -> list[dict]:
    """
    Aguarda até que todos os resultados apareçam no S3.
    Polling simples — suficiente para fins acadêmicos.
    """
    s3 = boto3.client("s3")
    deadline = time.time() + timeout
    while time.time() < deadline:
        paginator = s3.get_paginator("list_objects_v2")
        count = sum(
            1
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="results/")
            for _ in page.get("Contents", [])
        )
        log.info(f"Resultados prontos: {count}/{expected}")
        if count >= expected:
            break
        time.sleep(15)

    # Lê todos os resultados
    results = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="results/"):
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=S3_BUCKET, Key=obj["Key"])["Body"].read()
            results.append(json.loads(body))
    return results


def aggregate(results: list[dict]) -> dict:
    """Gera métricas agregadas e detecta inconsistências simples."""
    total_files        = len(results)
    total_tokens_gen   = sum(r.get("tokens_gen", 0)    for r in results)
    total_tokens_prompt= sum(r.get("tokens_prompt", 0) for r in results)
    total_latency      = sum(r.get("latency_s", 0.0)   for r in results)
    avg_latency        = total_latency / total_files if total_files else 0

    # Detecta arquivos sem output (possível falha não capturada)
    empty = [r["file_key"] for r in results if not r.get("output", "").strip()]

    summary = {
        "total_files":         total_files,
        "total_tokens_prompt": total_tokens_prompt,
        "total_tokens_gen":    total_tokens_gen,
        "total_latency_s":     round(total_latency, 2),
        "avg_latency_s":       round(avg_latency, 2),
        "files_with_empty_output": empty,
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


def save_summary(summary: dict):
    s3 = boto3.client("s3")
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
    parser.add_argument("--prefix", default="repo/", help="Prefixo S3 dos arquivos de código")
    parser.add_argument("--mode",   default="tests", choices=["tests", "smells", "docs"])
    parser.add_argument("--no-wait", action="store_true", help="Só enfileira, não aguarda resultados")
    args = parser.parse_args()

    files = list_code_files(args.prefix)
    if not files:
        log.error(f"Nenhum arquivo encontrado em s3://{S3_BUCKET}/{args.prefix}")
        raise SystemExit(1)

    enqueue_tasks(files, args.mode)

    if not args.no_wait:
        results = wait_for_results(expected=len(files))
        summary = aggregate(results)
        save_summary(summary)
