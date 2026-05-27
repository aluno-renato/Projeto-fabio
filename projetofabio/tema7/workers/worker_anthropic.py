"""
Worker simplificado usando API Anthropic no lugar do Ollama.
Mesma lógica de SQS, S3, retry e métricas.
"""
import argparse, json, logging, os, time, traceback
import boto3, requests

SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
S3_BUCKET     = os.environ["S3_BUCKET"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
MAX_RETRIES   = 3

logging.basicConfig(level=logging.INFO, format='%(asctime)s [worker-%(worker_id)s] %(message)s')

import logging
class WorkerLogger:
    def __init__(self, wid):
        self.wid = wid
        self.log = logging.getLogger(f"worker-{wid}")
    def info(self, msg): self.log.info(msg)
    def warning(self, msg): self.log.warning(msg)
    def error(self, msg): self.log.error(msg)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'prompts')

def load_prompt(name):
    path = os.path.join(PROMPTS_DIR, f"{name}.txt")
    return open(path).read() if os.path.exists(path) else f"Analyze this {name} code."

def call_anthropic(system_prompt, user_content, logger):
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}]
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            t0 = time.perf_counter()
            r = requests.post(url, headers=headers, json=payload, timeout=60)
            r.raise_for_status()
            data = r.json()
            latency = time.perf_counter() - t0
            text = data["content"][0]["text"]
            tokens_in  = data["usage"]["input_tokens"]
            tokens_out = data["usage"]["output_tokens"]
            logger.info(json.dumps({"event":"api_ok","latency_s":round(latency,3),"tokens_in":tokens_in,"tokens_out":tokens_out}))
            return {"text":text,"latency_s":latency,"tokens_prompt":tokens_in,"tokens_gen":tokens_out}
        except Exception as exc:
            wait = 2 ** attempt
            logger.warning(f"attempt {attempt} failed: {exc} — waiting {wait}s")
            if attempt == MAX_RETRIES: raise
            time.sleep(wait)

def chunk_code(code, max_chars=4000):
    if len(code) <= max_chars: return [code]
    chunks, current, current_len = [], [], 0
    for line in code.splitlines(keepends=True):
        if current_len + len(line) > max_chars and current:
            chunks.append("".join(current))
            current, current_len = [], 0
        current.append(line); current_len += len(line)
    if current: chunks.append("".join(current))
    return chunks

def process_file(task, logger):
    s3 = boto3.client("s3")
    code = s3.get_object(Bucket=S3_BUCKET, Key=task["file_key"])["Body"].read().decode()
    system_prompt = load_prompt(f"{task.get('mode','tests')}_{task.get('language','python')}")
    chunks = chunk_code(code)
    results, total_lat, total_tok_p, total_tok_g = [], 0, 0, 0
    prev_summary = ""
    for i, chunk in enumerate(chunks):
        context = f"\n[CONTEXTO ANTERIOR]\n{prev_summary}\n[FIM]\n" if prev_summary else ""
        user_content = f"Arquivo: {task['file_key']}\nChunk {i+1}/{len(chunks)}:{context}\n```{task.get('language','python')}\n{chunk}\n```"
        result = call_anthropic(system_prompt, user_content, logger)
        results.append(result["text"])
        prev_summary = result["text"][:400]
        total_lat += result["latency_s"]
        total_tok_p += result["tokens_prompt"]
        total_tok_g += result["tokens_gen"]
    return {"file_key":task["file_key"],"language":task.get("language"),"mode":task.get("mode"),
            "chunks":len(chunks),"output":"\n\n---\n\n".join(results),
            "tokens_prompt":total_tok_p,"tokens_gen":total_tok_g,"latency_s":round(total_lat,3)}

def save_result(result):
    s3 = boto3.client("s3")
    key = "results/" + result["file_key"].replace("/","__") + f".{result['mode']}.json"
    s3.put_object(Bucket=S3_BUCKET, Key=key,
                  Body=json.dumps(result, ensure_ascii=False, indent=2).encode(),
                  ContentType="application/json")
    return key

def run(worker_id):
    old_factory = logging.getLogRecordFactory()
    def factory(*args, **kwargs):
        r = old_factory(*args, **kwargs); r.worker_id = worker_id; return r
    logging.setLogRecordFactory(factory)
    logger = WorkerLogger(worker_id)
    sqs = boto3.client("sqs")
    logger.info(f"Iniciando worker {worker_id}")
    while True:
        resp = sqs.receive_message(QueueUrl=SQS_QUEUE_URL, MaxNumberOfMessages=1, WaitTimeSeconds=10)
        msgs = resp.get("Messages", [])
        if not msgs: logger.info("Fila vazia, aguardando..."); continue
        msg = msgs[0]
        task = json.loads(msg["Body"])
        logger.info(f"Processando: {task}")
        try:
            result = process_file(task, logger)
            key = save_result(result)
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
            logger.info(f"Salvo em s3://{S3_BUCKET}/{key} | tokens={result['tokens_gen']} | lat={result['latency_s']}s")
        except Exception as exc:
            logger.error(f"Erro: {exc}\n{traceback.format_exc()}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--worker-id", default="1")
    args = p.parse_args()
    run(args.worker_id)
