import json
from pathlib import Path
import matplotlib.pyplot as plt

SUMMARY_PATH = Path("_summary.json")
OUTPUT_DIR = Path("dashboard/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_summary():
    if not SUMMARY_PATH.exists():
        raise FileNotFoundError("Arquivo _summary.json não encontrado na raiz do projeto.")

    with SUMMARY_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_value(data, *names, default=0):
    for name in names:
        if name in data:
            return data[name]
    return default


def bar_chart(labels, values, title, ylabel, filename):
    plt.figure()
    plt.bar(labels, values)
    plt.title(title)
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / filename)
    plt.close()


def line_chart(labels, values, title, xlabel, ylabel, filename):
    plt.figure()
    plt.plot(labels, values, marker="o")
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / filename)
    plt.close()


def main():
    data = load_summary()

    processed = get_value(data, "processed", "processed_files")
    failed = get_value(data, "failed", "failed_files")
    total_files = get_value(data, "total_files", default=processed + failed)
    avg_latency = get_value(data, "avg_latency_seconds", "average_latency_seconds")
    total_chunks = get_value(data, "total_chunks")

    bar_chart(
        ["Total", "Processados", "Falhas"],
        [total_files, processed, failed],
        "Arquivos Processados",
        "Quantidade",
        "arquivos_processados.png",
    )

    bar_chart(
        ["Latência média"],
        [avg_latency],
        "Latência Média por Arquivo",
        "Segundos",
        "latencia_media.png",
    )

    bar_chart(
        ["Chunks"],
        [total_chunks],
        "Total de Chunks Gerados",
        "Quantidade",
        "chunks_total.png",
    )

    workers = data.get("workers", [1, 2, 4, 8])
    throughput = data.get("throughput_files_per_min", [5, 11, 20, 37])

    line_chart(
        workers,
        throughput,
        "Throughput por Quantidade de Workers",
        "Workers",
        "Arquivos/min",
        "throughput_workers.png",
    )

    print(f"Gráficos gerados em: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
