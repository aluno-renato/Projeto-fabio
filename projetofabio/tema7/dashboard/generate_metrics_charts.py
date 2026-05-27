"""
Gera gráficos de métricas a partir do _summary.json produzido pelo orquestrador.

Uso:
    # Baixa o summary do S3 e gera os gráficos
    python generate_metrics_charts.py --from-s3

    # Usa um arquivo local (para testes)
    python generate_metrics_charts.py --summary path/para/_summary.json

    # Execuções com N workers diferentes (para gráfico de escala)
    python generate_metrics_charts.py --multi-run run1.json run2.json run3.json

Os gráficos são salvos em dashboard/output/.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

OUTPUT_DIR = Path("dashboard/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

S3_BUCKET    = os.environ.get("S3_BUCKET", "")
SUMMARY_KEY  = "results/_summary.json"


# ─── Leitura do summary ───────────────────────────────────────────────────────
def load_from_s3() -> dict:
    if not S3_BUCKET:
        sys.exit("Erro: defina a variável S3_BUCKET antes de usar --from-s3")
    s3   = boto3.client("s3")
    body = s3.get_object(Bucket=S3_BUCKET, Key=SUMMARY_KEY)["Body"].read()
    return json.loads(body)


def load_from_file(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── Helpers de plot ─────────────────────────────────────────────────────────
def bar(labels, values, title, ylabel, filename, color="#4C72B0"):
    fig, ax = plt.subplots()
    ax.bar(labels, values, color=color)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / filename, dpi=150)
    plt.close(fig)
    print(f"  Salvo: {OUTPUT_DIR / filename}")


def horizontal_bar(labels, values, title, xlabel, filename, color="#55A868"):
    fig, ax = plt.subplots()
    ax.barh(labels, values, color=color)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / filename, dpi=150)
    plt.close(fig)
    print(f"  Salvo: {OUTPUT_DIR / filename}")


def line(x_vals, y_vals, title, xlabel, ylabel, filename, color="#C44E52", marker="o"):
    fig, ax = plt.subplots()
    ax.plot(x_vals, y_vals, marker=marker, color=color, linewidth=2)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x_vals)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / filename, dpi=150)
    plt.close(fig)
    print(f"  Salvo: {OUTPUT_DIR / filename}")


# ─── Gráficos de um único run ────────────────────────────────────────────────
def generate_single_run_charts(data: dict):
    processed  = data.get("total_files", 0)
    failed     = data.get("failed_files", 0)
    enqueued   = data.get("total_enqueued", processed + failed)
    avg_lat    = data.get("avg_latency_seconds", data.get("avg_latency_s", 0))
    throughput = data.get("throughput_files_per_min", 0)
    tok_prompt = data.get("total_tokens_prompt", 0)
    tok_gen    = data.get("total_tokens_gen", 0)
    error_pct  = data.get("error_rate_pct", (failed / enqueued * 100) if enqueued else 0)

    # 1. Arquivos: processados vs falhas
    bar(
        ["Enfileirados", "Concluídos", "Falhas"],
        [enqueued, processed, failed],
        "Arquivos por status",
        "Quantidade",
        "01_arquivos_status.png",
    )

    # 2. Taxa de erro
    bar(
        ["Taxa de erro (%)"],
        [round(error_pct, 2)],
        f"Taxa de erro — {round(error_pct, 2)}%",
        "%",
        "02_taxa_erro.png",
        color="#C44E52",
    )

    # 3. Latência média por arquivo
    bar(
        ["Latência média"],
        [round(avg_lat, 2)],
        "Latência média por arquivo",
        "Segundos",
        "03_latencia_media.png",
        color="#8172B2",
    )

    # 4. Throughput
    bar(
        ["Throughput"],
        [round(throughput, 2)],
        "Throughput (arquivos/min)",
        "Arquivos/min",
        "04_throughput.png",
        color="#55A868",
    )

    # 5. Tokens
    bar(
        ["Tokens de prompt", "Tokens gerados"],
        [tok_prompt, tok_gen],
        "Consumo de tokens",
        "Tokens",
        "05_tokens.png",
        color="#4C72B0",
    )

    # 6. Latência por arquivo (se disponível)
    files = data.get("files", [])
    if files:
        names    = [Path(f["file"]).name[:20] for f in files]
        latencias = [f.get("latency_s", 0) for f in files]
        horizontal_bar(
            names, latencias,
            "Latência por arquivo",
            "Segundos",
            "06_latencia_por_arquivo.png",
        )

    print(f"\nResumo:")
    print(f"  Arquivos concluídos : {processed}/{enqueued}")
    print(f"  Taxa de erro        : {round(error_pct, 2)}%")
    print(f"  Latência média      : {round(avg_lat, 2)}s")
    print(f"  Throughput          : {round(throughput, 2)} arq/min")
    print(f"  Tokens gerados      : {tok_gen:,}")


# ─── Gráfico de escala (múltiplos runs com N workers) ────────────────────────
def generate_scale_charts(run_files: list):
    """
    Compara runs com quantidades diferentes de workers.
    Cada arquivo deve ter um campo 'worker_count' ou o número de workers
    é inferido pela ordem dos arquivos (1, 2, 4, ...).
    """
    summaries = [load_from_file(f) for f in run_files]

    worker_counts = []
    throughputs   = []
    avg_latencies = []
    error_rates   = []

    for i, s in enumerate(summaries):
        wc = s.get("worker_count", 2 ** i)  # infere 1, 2, 4, 8 se não informado
        worker_counts.append(wc)
        throughputs.append(s.get("throughput_files_per_min", 0))
        avg_latencies.append(s.get("avg_latency_seconds", s.get("avg_latency_s", 0)))
        error_rates.append(s.get("error_rate_pct", 0))

    line(
        worker_counts, throughputs,
        "Throughput × Número de Workers",
        "Workers", "Arquivos/min",
        "07_scale_throughput.png",
    )

    line(
        worker_counts, avg_latencies,
        "Latência média × Número de Workers",
        "Workers", "Segundos",
        "08_scale_latencia.png",
        color="#8172B2",
    )

    line(
        worker_counts, error_rates,
        "Taxa de erro × Número de Workers",
        "Workers", "%",
        "09_scale_erro.png",
        color="#C44E52",
    )

    print("\nDados de escala:")
    for wc, tp, lat, er in zip(worker_counts, throughputs, avg_latencies, error_rates):
        print(f"  {wc} workers → {tp:.1f} arq/min | lat {lat:.1f}s | erro {er:.1f}%")


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gerador de gráficos de métricas — Tema 7")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-s3",    action="store_true", help="Baixa _summary.json do S3")
    group.add_argument("--summary",    metavar="FILE",       help="Caminho local do _summary.json")
    group.add_argument("--multi-run",  nargs="+", metavar="FILE",
                       help="Vários _summary.json para gráfico de escala (1 por config de workers)")
    args = parser.parse_args()

    print("Gerando gráficos em:", OUTPUT_DIR)

    if args.from_s3:
        data = load_from_s3()
        generate_single_run_charts(data)

    elif args.summary:
        data = load_from_file(args.summary)
        generate_single_run_charts(data)

    elif args.multi_run:
        generate_scale_charts(args.multi_run)
        # Também gera gráfico do primeiro run individualmente
        data = load_from_file(args.multi_run[0])
        generate_single_run_charts(data)

    print("\nDone.")
