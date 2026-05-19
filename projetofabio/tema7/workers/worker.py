"""
Worker do Tema 7 — consome tarefas da fila SQS, chama o Ollama e salva no S3.
Execute com: python worker.py --worker-id 1
"""

import argparse
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

import boto3
import requests
from botocore.exceptions import ClientError

# ─── Configuração via variáveis de ambiente ───────────────────────────────────
SQS_QUEUE_URL  = os.environ["SQS_QUEUE_URL"]         # URL da fila de tarefas
SQS_DLQ_URL    = os.environ.get("SQS_DLQ_URL", "")   # Dead Letter Queue (opcional manual)
S3_BUCKET      = os.environ["S3_BUCKET"]              # Bucket para resultados
OLLAMA_HOST    = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL   = os.environ.get("OLLAMA_MODEL", "mistral")
MAX_RETRIES    = int(os.environ.get("MAX_RETRIES", "3"))
BACKOFF_BASE   = float(os.environ.get("BACKOFF_BASE", "2.0"))  # segundos

# ─── Logging estruturado ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","worker":"%(worker_id)s","msg":%(message)s}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)

def get_logger(worker_id: str):
    logger = logging.getLogger(f"worker-{worker_id}")
    old_factory = logging.getLogRecordFactory()
    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.worker_id = worker_id
        return record
    logging.setLogRecordFactory(record_factory)
    return logger


# ─── Helpers ──────────────────────────────────────────────────────────────────
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt não encontrado: {path}")
    return path.read_text(encoding="utf-8")


def call_ollama(system_prompt: str, user_content: str, logger) -> dict:
    """Chama o Ollama com retry + exponential backoff. Retorna dict com texto e métricas."""
    url = f"{OLLAMA_HOST}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            t0 = time.perf_counter()
            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            latency = time.perf_counter() - t0

            text = data["message"]["content"]
            eval_count = data.get("eval_count", 0)          # tokens gerados
            prompt_eval = data.get("prompt_eval_count", 0)  # tokens do prompt

            logger.info(json.dumps({
                "event": "ollama_ok",
                "attempt": attempt,
                "latency_s": round(latency, 3),
                "tokens_prompt": prompt_eval,
                "tokens_gen": eval_count,
            }))
            return {
                "text": text,
                "latency_s": latency,
                "tokens_prompt": prompt_eval,
                "tokens_gen": eval_count,
            }

        except (requests.RequestException, KeyError) as exc:
            wait = BACKOFF_BASE ** attempt
            logger.warning(json.dumps({
                "event": "ollama_retry",
                "attempt": attempt,
                "error": str(exc),
                "wait_s": wait,
            }))
            if attempt == MAX_RETRIES:
                raise
            time.sleep(wait)


def chunk_code(code: str, max_chars: int = 6000) -> list[str]:
    """
    Divide arquivos grandes em chunks por número de caracteres,
    tentando cortar em limites de linha para não quebrar no meio de uma função.
    """
    if len(code) <= max_chars:
        return [code]

    chunks, current = [], []
    current_len = 0
    for line in code.splitlines(keepends=True):
        if current_len + len(line) > max_chars and current:
            chunks.append("".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


def process_file(task: dict, logger) -> dict:
    """Processa um arquivo de código: gera testes, smells e documentação."""
    file_key   = task["file_key"]    # ex: "repo/src/utils.py"
    language   = task.get("language", "python")
    mode       = task.get("mode", "tests")  # tests | smells | docs

    # Baixa o arquivo do S3
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=S3_BUCKET, Key=file_key)
    code = obj["Body"].read().decode("utf-8")

    system_prompt = load_prompt(f"{mode}_{language}")
    chunks = chunk_code(code)

    results, total_tokens_prompt, total_tokens_gen, total_latency = [], 0, 0, 0.0

    for i, chunk in enumerate(chunks):
        logger.info(json.dumps({"event": "chunk_start", "chunk": i+1, "total": len(chunks)}))
        user_content = f"Arquivo: {file_key}\nChunk {i+1}/{len(chunks)}:\n\n```{language}\n{chunk}\n```"
        result = call_ollama(system_prompt, user_content, logger)
        results.append(result["text"])
        total_tokens_prompt += result["tokens_prompt"]
        total_tokens_gen    += result["tokens_gen"]
        total_latency       += result["latency_s"]

    combined_output = "\n\n---\n\n".join(results)

    return {
        "file_key":      file_key,
        "language":      language,
        "mode":          mode,
        "chunks":        len(chunks),
        "output":        combined_output,
        "tokens_prompt": total_tokens_prompt,
        "tokens_gen":    total_tokens_gen,
        "latency_s":     round(total_latency, 3),
    }


def save_result(result: dict, logger):
    """Salva o resultado em S3 como JSON."""
    s3 = boto3.client("s3")
    out_key = result["file_key"].replace("/", "__") + f".{result['mode']}.json"
    out_key = f"results/{out_key}"
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=out_key,
        Body=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    logger.info(json.dumps({"event": "saved", "s3_key": out_key}))


# ─── Loop principal ───────────────────────────────────────────────────────────
def run(worker_id: str):
    logger = get_logger(worker_id)
    sqs = boto3.client("sqs")
    logger.info(json.dumps({"event": "start", "model": OLLAMA_MODEL, "queue": SQS_QUEUE_URL}))

    while True:
        # Long-poll para reduzir chamadas vazias
        resp = sqs.receive_message(
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            AttributeNames=["ApproximateReceiveCount"],
        )
        messages = resp.get("Messages", [])
        if not messages:
            continue

        msg = messages[0]
        receipt = msg["ReceiptHandle"]
        task = json.loads(msg["Body"])
        receive_count = int(msg["Attributes"].get("ApproximateReceiveCount", 1))

        logger.info(json.dumps({"event": "task_received", "task": task, "receive_count": receive_count}))

        try:
            result = process_file(task, logger)
            save_result(result, logger)
            # Mensagem processada com sucesso → deleta da fila
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt)
            logger.info(json.dumps({"event": "task_done", "file": task.get("file_key")}))

        except Exception as exc:
            logger.error(json.dumps({"event": "task_error", "error": str(exc), "trace": traceback.format_exc()}))
            # Não deleta → SQS vai recolocar na fila até o maxReceiveCount configurado
            # depois vai para a DLQ automaticamente (configure no console)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", default="1")
    args = parser.parse_args()
    run(args.worker_id)
