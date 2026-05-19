# Como executar o projeto completo

## 1. Criar infraestrutura com Terraform

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
```

Edite o arquivo `terraform.tfvars` com:

```hcl
bucket_name      = "nome-unico-do-bucket"
key_name         = "nome-da-chave-ssh"
allowed_ssh_cidr = "seu-ip/32"
```

Depois execute:

```bash
terraform init
terraform plan
terraform apply
```

## 2. Subir o repositório para o S3

Na raiz do projeto:

```bash
bash scripts/upload_repo.sh
```

## 3. Executar o orchestrator

```bash
python orchestrator/orchestrator.py
```

## 4. Executar workers

```bash
bash scripts/deploy_workers.sh 4
```

## 5. Ativar CloudWatch Agent

```bash
bash cloudwatch/install_cloudwatch_agent.sh
```

## 6. Gerar gráficos

Após a criação do `_summary.json`:

```bash
python dashboard/generate_metrics_charts.py
```

Os gráficos serão salvos em:

```text
dashboard/output/
```
