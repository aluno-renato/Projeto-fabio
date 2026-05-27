

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


SQS_QUEUE_URL  = os.environ["SQS_QUEUE_URL"]
SQS_DLQ_URL    = os.environ.get("SQS_DLQ_URL", "")
S3_BUCKET      = os.environ["S3_BUCKET"]
OLLAMA_HOST    = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL   = os.environ.get("OLLAMA_MODEL", "mistral")
MAX_RETRIES    = int(os.environ.get("MAX_RETRIES", "3"))
BACKOFF_BASE   = float(os.environ.get("BACKOFF_BASE", "2.0"))
CW_NAMESPACE   = os.environ.get("CW_NAMESPACE", "Tema7/Workers")
AWS_REGION     = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


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


# ─── CloudWatch: métricas customizadas de negócio ────────────────────────────
def put_metric(cw_client, metric_name: str, value: float, unit: str, worker_id: str):
    """Publica uma métrica customizada no CloudWatch."""
    try:
        cw_client.put_metric_data(
            Namespace=CW_NAMESPACE,
            MetricData=[{
                "MetricName": metric_name,
                "Value": value,
                "Unit": unit,
                "Dimensions": [{"Name": "WorkerId", "Value": worker_id}],
            }],
        )
    except Exception as exc:
        # Falha em métrica não deve derrubar o worker
        pass



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
            eval_count   = data.get("eval_count", 0)
            prompt_eval  = data.get("prompt_eval_count", 0)

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


def chunk_code(code: str, max_chars: int = 6000) -> list:
    """
    Divide arquivos grandes em chunks por número de caracteres,
    cortando em limites de linha para não quebrar no meio de uma função.
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


def summarize_output(text: str, max_chars: int = 800) -> str:
    """
    Extrai um resumo compacto da saída do chunk anterior para usar como
    contexto de memória no próximo chunk. Evita duplicação de testes/smells.
    Trunca para não inflar o prompt desnecessariamente.
    """
    lines = text.strip().splitlines()
    # Para smells (JSON array), extrai nomes dos smells encontrados
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            names = [item.get("smell", "") for item in parsed if isinstance(item, dict)]
            return f"Smells já identificados no chunk anterior: {', '.join(names[:10])}"
    except (json.JSONDecodeError, ValueError):
        pass
    # Para testes/docs: pega as primeiras linhas significativas
    summary_lines = [l for l in lines if l.strip() and not l.strip().startswith("#")][:12]
    summary = "\n".join(summary_lines)
    if len(summary) > max_chars:
        summary = summary[:max_chars] + "\n[... truncado ...]"
    return summary


def process_file(task: dict, logger, cw_client, worker_id: str) -> dict:
    """Processa um arquivo de código: gera testes, smells ou documentação."""
    file_key = task["file_key"]
    language = task.get("language", "python")
    mode     = task.get("mode", "tests")

    # Baixa o arquivo do S3
    s3  = boto3.client("s3")
    obj = s3.get_object(Bucket=S3_BUCKET, Key=file_key)
    code = obj["Body"].read().decode("utf-8")

    system_prompt = load_prompt(f"{mode}_{language}")
    chunks = chunk_code(code)

    results = []
    total_tokens_prompt = 0
    total_tokens_gen    = 0
    total_latency       = 0.0
    previous_summary    = ""   # memória entre chunks

    for i, chunk in enumerate(chunks):
        logger.info(json.dumps({"event": "chunk_start", "chunk": i + 1, "total": len(chunks)}))

        # Monta o conteúdo do usuário injetando contexto do chunk anterior
        if previous_summary:
            context_note = (
                f"\n\n[CONTEXTO DO CHUNK ANTERIOR — não repita o que já foi gerado]\n"
                f"{previous_summary}\n"
                f"[FIM DO CONTEXTO]\n"
            )
        else:
            context_note = ""

        user_content = (
            f"Arquivo: {file_key}\n"
            f"Chunk {i + 1}/{len(chunks)}:\n"
            f"{context_note}"
            f"\n```{language}\n{chunk}\n```"
        )

        result = call_ollama(system_prompt, user_content, logger)
        results.append(result["text"])

        # Atualiza memória para o próximo chunk
        previous_summary = summarize_output(result["text"])

        total_tokens_prompt += result["tokens_prompt"]
        total_tokens_gen    += result["tokens_gen"]
        total_latency       += result["latency_s"]

    # Publica métricas de negócio no CloudWatch
    put_metric(cw_client, "LatencyPerFile",    total_latency,       "Seconds", worker_id)
    put_metric(cw_client, "TokensGenerated",   total_tokens_gen,    "Count",   worker_id)
    put_metric(cw_client, "TokensPrompt",      total_tokens_prompt, "Count",   worker_id)
    put_metric(cw_client, "FilesProcessed",    1,                   "Count",   worker_id)
    put_metric(cw_client, "ChunksProcessed",   len(chunks),         "Count",   worker_id)

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
    logger   = get_logger(worker_id)
    sqs      = boto3.client("sqs", region_name=AWS_REGION)
    cw_client = boto3.client("cloudwatch", region_name=AWS_REGION)

    logger.info(json.dumps({"event": "start", "model": OLLAMA_MODEL, "queue": SQS_QUEUE_URL}))

    consecutive_errors = 0

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

        msg     = messages[0]
        receipt = msg["ReceiptHandle"]
        task    = json.loads(msg["Body"])
        receive_count = int(msg["Attributes"].get("ApproximateReceiveCount", 1))

        logger.info(json.dumps({"event": "task_received", "task": task, "receive_count": receive_count}))

        try:
            result = process_file(task, logger, cw_client, worker_id)
            save_result(result, logger)
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt)
            logger.info(json.dumps({"event": "task_done", "file": task.get("file_key")}))
            consecutive_errors = 0

        except requests.exceptions.ConnectionError as exc:
            # ── FALLBACK: Ollama inacessível ──────────────────────────────────
            # Estratégia: loga o erro, publica métrica de falha, NÃO deleta a
            # mensagem (SQS recoloca na fila). Após 3 falhas consecutivas o
            # worker dorme 60s antes de tentar novamente, evitando loop frenético.
            # Após maxReceiveCount=3 a mensagem vai automaticamente para a DLQ.
            consecutive_errors += 1
            put_metric(cw_client, "OllamaErrors", 1, "Count", worker_id)
            logger.error(json.dumps({
                "event":             "ollama_unreachable",
                "error":             str(exc),
                "consecutive_errors": consecutive_errors,
                "fallback_action":   "message_not_deleted_will_retry_via_sqs",
            }))
            if consecutive_errors >= 3:
                logger.warning(json.dumps({
                    "event":   "fallback_cooling_down",
                    "sleep_s": 60,
                    "reason":  "3 consecutive Ollama failures — waiting before retry",
                }))
                time.sleep(60)

        except Exception as exc:
            # Erros genéricos (S3, parsing, etc.): loga e não deleta
            put_metric(cw_client, "ProcessingErrors", 1, "Count", worker_id)
            logger.error(json.dumps({
                "event": "task_error",
                "error": str(exc),
                "trace": traceback.format_exc(),
            }))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", default="1")
    args = parser.parse_args()
    run(args.worker_id)
