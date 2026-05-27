#!/bin/bash
# scripts/upload_repo.sh
# Faz upload de um repositório local para o S3, criando o input para o sistema.
# Usage: bash upload_repo.sh <caminho_local_do_repo>
# Exemplo: bash upload_repo.sh ~/meu_projeto

set -euo pipefail

REPO_PATH=${1:?"Informe o caminho do repositório. Ex: bash upload_repo.sh ~/meu_projeto"}
S3_BUCKET=${S3_BUCKET:?"Defina a variável S3_BUCKET"}
PREFIX="repo"

echo "Enviando arquivos de $REPO_PATH para s3://$S3_BUCKET/$PREFIX/"

aws s3 sync "$REPO_PATH" "s3://$S3_BUCKET/$PREFIX/" \
  --exclude "*.pyc" \
  --exclude "__pycache__/*" \
  --exclude ".git/*" \
  --exclude "node_modules/*" \
  --exclude "*.min.js" \
  --exclude "*.lock"

echo "Upload concluído."
