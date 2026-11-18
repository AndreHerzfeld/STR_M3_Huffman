"""Reproduce the tables, figures and report from the recorded activation CSVs."""
import argparse
import csv
from decimal import Decimal
import json
from pathlib import Path
from statistics import mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

K_VALUES = (10, 20, 50)
LABELS = ("Tarefa", "Comportamental", "Intertarefas", "Sistema")
COLORS = ("#147a90", "#285cac", "#7b559a", "#aa442f")
BASE_GOAL = (18, 20)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titlesize": 10, "axes.labelsize": 9, "grid.alpha": 0.2})


def csv_write(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(rows)


def read_samples(path):
    values = []
    with path.open(newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != ["ativacao", "tempo_us"]:
            raise ValueError(f"Colunas inesperadas em {path}.")
        for i, row in enumerate(reader, 1):
            ns = Decimal(row["tempo_us"]) * 1000
            if int(row["ativacao"]) != i or not ns.is_finite() or ns <= 0 or ns != int(ns):
                raise ValueError(f"Ativação inválida em {path}, posição {i}.")
            values.append(int(ns))
    return values


def windows(mask, k):
    previous = sum(mask[:k])
    result = [previous]
    for i in range(k, len(mask)):
        previous += mask[i] - mask[i - k]
        result.append(previous)
    return result


def losses(sample, deadline):
    mask = [int(t > deadline) for t in sample]
    misses = [i for i, lost in enumerate(mask, 1) if lost]
    gaps = [right - left for left, right in zip(misses, misses[1:])]
    runs = []
    for missed in misses:
        if runs and missed == runs[-1][1] + 1:
            runs[-1][1] = missed
        else:
            runs.append([missed, missed])
    burst_lengths = [last - first + 1 for first, last in runs if first != last]
    counts = {k: windows(mask, k) for k in K_VALUES}
    maxima = {k: max(series) for k, series in counts.items()}
    return {
        "perdas": misses, "distancias": gaps, "sequencias": runs,
        "isoladas": sum(a == b for a, b in runs), "rajadas": len(burst_lengths),
        "maior_rajada": max(burst_lengths, default=0), "skip_factor": min(gaps, default=None),
        "percentual_no_prazo": 100 * (len(sample) - len(misses)) / len(sample),
        "maximo_perdas_por_janela": maxima,
        "m": {k: k - maxima[k] for k in K_VALUES},
        "primeira_pior_janela": {k: counts[k].index(maxima[k]) + 1 for k in K_VALUES},
    }, counts


def summarize_spikes(sample, threshold):
    high = [t > threshold for t in sample]
    # Padding keeps the first and last observations in the same adjacency rule.
    padded = [False, *high, False]
    isolated = sum(b and not a and not c for a, b, c in zip(padded, padded[1:], padded[2:]))
    groups = sum(not a and b and c for a, b, c in zip(padded, padded[1:], padded[2:]))
    return {"isolados": isolated, "grupos": groups}


def stats(sample):
    ordered = sorted(sample)
    n = len(ordered)
    return {
        "n": n, "min_ns": ordered[0], "media_ns": mean(ordered), "hwm_ns": ordered[-1],
        "hwm99_ns": ordered[n - n // 100 - 1], "mediana_ns": ordered[(n - 1) // 2],
        "hwm_pos": sample.index(ordered[-1]) + 1,
        "picos": summarize_spikes(sample, ordered[n - n // 100 - 1]),
    }


def save_losses(target, result, counts, sample):
    csv_write(target / "perdas.csv", ["ativacao", "tempo_us"],
              ((i, sample[i - 1] / 1000) for i in result["perdas"]))
    csv_write(target / "distancias.csv", ["perda_anterior", "perda_seguinte", "distancia_ativacoes"],
              zip(result["perdas"], result["perdas"][1:], result["distancias"]))
    csv_write(target / "sequencias.csv", ["inicio", "fim", "tamanho", "classe"],
              ((a, b, b - a + 1, "isolada" if a == b else "rajada") for a, b in result["sequencias"]))
    for k, rows in counts.items():
        csv_write(target / f"janelas_k{k}.csv", ["inicio", "fim", "perdas", "cumpridos"],
                  ((i, i + k - 1, num, k - num) for i, num in enumerate(rows, 1)))


def plot_series(target, samples, overview, counts, deadline):
    def finish(fig, name):
        fig.savefig(target / f"{name}.png", dpi=172, bbox_inches="tight", facecolor="white")
        fig.savefig(target / f"{name}.pdf", bbox_inches="tight", facecolor="white")
        plt.close(fig)

    for kind in ("histogramas", "tempos", "janelas"):
        nrows = 4 if kind == "janelas" else 2
        ncols = 3 if kind == "janelas" else 2
        fig, axes = plt.subplots(nrows, ncols, figsize=(10, 7.5 if kind == "janelas" else 6),
                                 constrained_layout=True)
        for i, (sample, row) in enumerate(zip(samples, overview)):
            us = [t / 1000 for t in sample]
            color = COLORS[i]
            if kind == "janelas":
                for j, k in enumerate(K_VALUES):
                    ax = axes[i][j]
                    series = counts[i][k]
                    ax.plot(range(1, len(series) + 1), series, color=color, linewidth=0.9)
                    ax.set(title=f"{i + 1}. {LABELS[i]} · k={k}",
                           ylim=(-0.15, max(1.1, max(series) * 1.12)))
                    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=3))
                    ax.grid(axis="y")
                    if not j:
                        ax.set_ylabel("Perdas")
                    if i == 3:
                        ax.set_xlabel("Início da janela")
                continue
            ax = axes.ravel()[i]
            if kind == "histogramas":
                low, high = min(us) * 0.999, max(us) * 1.001
                bounds = [low * (high / low) ** (j / 40) for j in range(41)]
                ax.axvspan(row["hwm99_ns"] / 1000, high, color="#f4c58a", alpha=.42, label="Cauda (> HWM99)")
                ax.hist(us, bins=bounds, log=True, color=color, alpha=.78)
                ax.set(xscale="log", xlabel="Resposta (µs), escala log", ylabel="Ativações (log)")
                ax.axvline(row["hwm_ns"] / 1000, color="#222222", linewidth=1.1, label="HWM")
                ax.axvline(deadline / 1000, color="#ba1d3e", ls="--", linewidth=1.1, label="D fixo")
            else:
                ax.plot(range(1, len(us) + 1), us, color=color, linewidth=.53)
                tail = [(j, t) for j, t in enumerate(us, 1) if t > row["hwm99_ns"] / 1000]
                if tail:
                    ax.scatter(*zip(*tail), color="#aa442f", s=8, label="Acima de HWM99")
                ax.axhline(deadline / 1000, color="#ba1d3e", ls="--", linewidth=1, label="D fixo")
                ax.set(xlabel="Ativação", ylabel="Resposta (µs), escala log", yscale="log")
            ax.set_title(f"{i + 1}. {LABELS[i]} · n={len(sample):,}".replace(",", "."))
            ax.grid(axis="y")
            ax.legend(fontsize=7, loc="upper right")
        finish(fig, kind)

    fig, ax = plt.subplots(figsize=(9.5, 4.1), constrained_layout=True)
    convergence = []
    for i, sample in enumerate(samples):
        hwm = 0
        series = []
        for t in sample:
            hwm = max(hwm, t)
            series.append(hwm)
        convergence.append(series)
        ax.step(range(1, len(sample) + 1), [t / 1000 for t in series],
                where="post", label=LABELS[i], color=COLORS[i])
    ax.set(xscale="log", yscale="log", xlabel="Amostras acumuladas (escala log)",
           ylabel="HWM acumulado (µs), escala log",
           xticks=(1, 10, 20, 100, 1000, 10000),
           xticklabels=("1", "10", "20", "100", "1.000", "10.000"))
    ax.legend(ncol=2)
    ax.grid()
    finish(fig, "convergencia")
    return convergence


def plot_deadline_experiment(target, by_deadline, stage):
    fig, axes = plt.subplots(len(by_deadline), 3, figsize=(10, 2 * len(by_deadline)),
                             squeeze=False, constrained_layout=True)
    for i, (d, counts) in enumerate(by_deadline):
        for j, k in enumerate(K_VALUES):
            ax = axes[i][j]
            ax.plot(range(1, len(counts[k]) + 1), counts[k], color=COLORS[stage - 1], lw=.75)
            ax.set(title=f"D={fmt(d)} µs · k={k}", xlabel="Início da janela" if i == len(by_deadline) - 1 else "")
            ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
            if j == 0:
                ax.set_ylabel("Perdas")
    fig.savefig(target / f"janelas_etapa{stage}.png", dpi=160)
    plt.close(fig)


def fmt(ns):
    return f"{ns / 1000:.3f}".replace(".", ",")


def analyze_platform(path):
    target = path / "analise"
    target.mkdir(exist_ok=True)
    samples = [read_samples(path / "dados" / f"etapa{i}.csv") for i in range(1, 5)]
    if min(map(len, samples)) < 1000 or max(map(len, samples)) < 10000:
        raise ValueError(f"Quantidade de amostras insuficiente em {path}.")
    overview = [stats(sample) for sample in samples]
    base = overview[0]["hwm_ns"]
    fixed = (base * 120 + 99) // 100
    losses_all = []
    counts_all = []
    for i, sample in enumerate(samples, 1):
        result, counts = losses(sample, fixed)
        sub = target / f"etapa{i}"
        sub.mkdir(exist_ok=True)
        save_losses(sub, result, counts, sample)
        losses_all.append(result)
        counts_all.append(counts)
    coverage_path = path / "cobertura/resumo.json"
    coverage = json.loads(coverage_path.read_text()) if coverage_path.is_file() else None
    summaries = []
    for i, (stats_row, miss) in enumerate(zip(overview, losses_all), 1):
        cv = None
        if coverage:
            cv = coverage["aleatorio_por_etapa"][str(i)]
            if i == 1 and coverage["primeiro_prefixo_completo"]:
                cv = coverage["prefixos_dirigidos"][coverage["primeiro_prefixo_completo"]]
        summaries.append([i, "" if cv is None else 100 * cv["linhas"][0] / cv["linhas"][1],
                          "" if cv is None else 100 * cv["desvios"][0] / cv["desvios"][1],
                          stats_row["n"], *[stats_row[key] / 1000
                            for key in ("min_ns", "media_ns", "hwm_ns", "hwm99_ns")],
                          miss["percentual_no_prazo"], miss["skip_factor"],
                          *(miss["m"][k] for k in K_VALUES)])
    csv_write(target / "tabela_sintese.csv", ["etapa", "linhas_pct", "desvios_pct", "n",
              "min_us", "media_us", "hwm_us", "hwm99_us", "cumpridos_pct", "S",
              "m_k10", "m_k20", "m_k50"], summaries)
    conv = plot_series(target, samples, overview, counts_all, fixed)
    checkpoints = (10, 20, 100, 1000, 10000)
    csv_write(target / "convergencia.csv", ["etapa", "n", "hwm_acumulado_us"],
              ((i, n, hwm / 1000) for i, series in enumerate(conv, 1) for n, hwm in enumerate(series, 1)))
    csv_write(target / "convergencia_marcos.csv", ["etapa", "n", "hwm_acumulado_us"],
              ((i, n, series[n - 1] / 1000) for i, series in enumerate(conv, 1)
               for n in checkpoints if n <= len(series)))
    margins = []
    for pct in (10, 25, 50):
        d = (base * (100 + pct) + 99) // 100
        exceeded = [i for i, row in enumerate(overview, 1) if row["hwm_ns"] > d]
        margins.append([pct, d, exceeded])
    csv_write(target / "margens.csv", ["margem_pct", "limite_us", "hwm_sistema_us", "etapas_acima"],
              ((pct, d / 1000, overview[-1]["hwm_ns"] / 1000, " ".join(map(str, exceeded)))
               for pct, d, exceeded in margins))

    exp_dir = target / "experimento_D"
    exp_dir.mkdir(exist_ok=True)
    robust_system = overview[-1]["hwm99_ns"]
    deadlines = {base, robust_system, (base + robust_system) // 2}
    if len(deadlines) < 3:
        deadlines.add(fixed)
    while len(deadlines) < 3:
        deadlines.add(max(deadlines) + 1000)
    scenario_rows = []
    for i in (3, 4):
        curves = []
        for d in sorted(deadlines):
            result, counts = losses(samples[i - 1], d)
            sub = exp_dir / f"etapa{i}_D{d}ns"
            sub.mkdir(exist_ok=True)
            save_losses(sub, result, counts, samples[i - 1])
            curves.append((d, counts))
            scenario_rows.append([i, d, result["percentual_no_prazo"], result["skip_factor"],
                                  result["m"][20], result["isoladas"], result["rajadas"],
                                  result["maior_rajada"]])
        plot_deadline_experiment(exp_dir, curves, i)
    csv_write(exp_dir / "comparacao.csv", ["etapa", "D_us", "cumpridos_pct", "S",
              "m_k20", "isoladas", "rajadas", "maior_rajada"],
              ((i, d / 1000, *rest) for i, d, *rest in scenario_rows))

    m, k = BASE_GOAL
    system = samples[-1]
    min_deadline = max(sorted(system[i:i + k])[m - 1] for i in range(len(system) - k + 1))
    achiever, achieving_windows = losses(system, min_deadline)
    sub = exp_dir / f"meta_{m}_{k}_D{min_deadline}ns"
    sub.mkdir(exist_ok=True)
    save_losses(sub, achiever, achieving_windows, system)
    below, _ = losses(system, min_deadline - 1)
    goal = {"m": m, "k": k, "D_min_ns": min_deadline, "D_hwm_ns": overview[-1]["hwm_ns"],
            "m_observado": achiever["m"][k], "m_em_D_menos_1ns": below["m"][k],
            "pct_no_prazo": achiever["percentual_no_prazo"]}
    result = {"D_fixo_ns": fixed, "estatisticas": overview, "perdas": [
              {key: value for key, value in row.items() if key not in {"perdas", "distancias", "sequencias"}}
              for row in losses_all], "tabela": summaries, "margens": margins,
              "marcos": [[series[n-1] for n in checkpoints if n <= len(series)] for series in conv],
              "D_cenarios": scenario_rows, "D_meta": goal, "cobertura": coverage}
    (target / "resultados.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def analyze_run(run_dir):
    linux = analyze_platform(run_dir / "linux")
    esp = None
    esp_run = run_dir / "esp32"
    if (esp_run / "plataforma.json").is_file() and all(
            (esp_run / "dados" / f"etapa{i}.csv").is_file() for i in range(1, 5)):
        esp = analyze_platform(esp_run)
    from report import make_report
    make_report(run_dir, linux, esp)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pasta", type=Path, help="pasta com identificacao.json e linux/dados")
    analyze_run(parser.parse_args().pasta)
