#!/bin/bash
# scripts/deploy_workers.sh
# Instala dependências e sobe N workers em background numa instância EC2 com Ollama.
# Usage: bash deploy_workers.sh [NUM_WORKERS] [MODE]
# Exemplo: bash deploy_workers.sh 3 tests

set -euo pipefail

NUM_WORKERS=${1:-2}
MODE=${2:-tests}

echo "=== Instalando dependências Python ==="
pip install boto3 requests --quiet

echo "=== Verificando Ollama ==="
if ! command -v ollama &>/dev/null; then
  echo "Ollama não encontrado. Instalando..."
  curl -fsSL https://ollama.com/install.sh | sh
fi

# Garante que o modelo está baixado
ollama pull "${OLLAMA_MODEL:-mistral}"

echo "=== Subindo $NUM_WORKERS workers (modo: $MODE) ==="
for i in $(seq 1 "$NUM_WORKERS"); do
  LOG_FILE="/tmp/worker_${i}.log"
  WORKER_ID=$i python workers/worker.py --worker-id "$i" > "$LOG_FILE" 2>&1 &
  echo "Worker $i PID=$! log=$LOG_FILE"
done

echo ""
echo "Workers rodando. Acompanhe com:"
echo "  tail -f /tmp/worker_*.log"
echo ""
echo "Para enfileirar tarefas:"
echo "  python orchestrator/orchestrator.py --prefix repo/ --mode $MODE"
