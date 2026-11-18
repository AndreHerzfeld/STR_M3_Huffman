import argparse
import csv
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
COUNTS = {1: 1000, 2: 1000, 3: 1000, 4: 10000}


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def command(args, cwd=None, output=None, log=None, timeout=240):
    args = [str(arg) for arg in args]
    stderr = subprocess.STDOUT if log is None else subprocess.PIPE
    run = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=stderr,
                           start_new_session=True)
    interrupted = None
    try:
        stdout, diagnostic = run.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        interrupted = exc
        try:
            os.killpg(run.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            stdout, diagnostic = run.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            run.kill()
            stdout, diagnostic = run.communicate()
    if output:
        output.write_bytes(stdout)
    if log:
        with log.open("ab") as file:
            file.write(("$ " + " ".join(args) + "\n").encode())
            file.write(diagnostic or b"")
            if (run.returncode or not output) and stdout:
                file.write(stdout)
    if interrupted:
        raise interrupted
    if run.returncode:
        tail = (diagnostic or stdout).decode(errors="replace").splitlines()[-8:]
        raise RuntimeError(f"{args[0]} retornou {run.returncode}\n" + "\n".join(tail))
    return stdout.decode(errors="replace")


def cpu_count(cpuinfo):
    blocks = (dict(re.findall(r"^([^:\n]+?)\s*:\s*(.*)$", block, re.M))
              for block in cpuinfo.strip().split("\n\n"))
    pairs = {(block["physical id"], block["core id"]) for block in blocks
             if "physical id" in block and "core id" in block}
    return len(pairs) or None


def machine(platform_dir, core):
    cpuinfo = Path("/proc/cpuinfo").read_text()
    model = re.search(r"^(?:model name|Hardware)\s*:\s*(.+)", cpuinfo, re.M)
    governor = Path(f"/sys/devices/system/cpu/cpu{core}/cpufreq/scaling_governor")
    os_info = Path("/etc/os-release").read_text()
    name = re.search(r"^PRETTY_NAME=(.*)", os_info, re.M)
    def optional(path):
        return path.read_text().strip() if path.is_file() else None

    save_json(platform_dir / "plataforma.json", {
        "plataforma": "Linux", "data_local": datetime.now().astimezone().isoformat(),
        "so": name.group(1).strip('"') if name else "Linux", "kernel": os.uname().release,
        "cpu": model.group(1) if model else os.uname().machine,
        "nucleos_fisicos": cpu_count(cpuinfo), "cpus_logicas": os.cpu_count(),
        "cpus_disponiveis": sorted(os.sched_getaffinity(0)), "cpu_teste": core,
        "governor_cpu_teste": optional(governor), "politica": os.sched_getscheduler(0),
        "classe_politica": {0: "SCHED_OTHER", 1: "SCHED_FIFO", 2: "SCHED_RR",
                            3: "SCHED_BATCH", 5: "SCHED_IDLE", 6: "SCHED_DEADLINE"}.get(os.sched_getscheduler(0)),
        "compilador": command(["gcc", "--version"]).splitlines()[0],
        "periodo_huffman_us": 2500, "tamanho": 2048, "alfabeto": 16, "semente": 20261118,
    })
    for name, path in {"cpuinfo.txt": "/proc/cpuinfo", "os-release.txt": "/etc/os-release"}.items():
        content = optional(Path(path))
        if content:
            (platform_dir / name).write_text(content + "\n")
    if shutil.which("lscpu") and Path("/sys/devices/system/cpu/possible").is_file():
        command(["lscpu"], output=platform_dir / "lscpu.txt")


def snapshot(platform_dir, stage, position):
    command(["ps", "-eo", "pid,comm,cls,ni,psr,pcpu,pmem", "--sort=-pcpu"],
            output=platform_dir / f"processos_etapa{stage}_{position}.txt")
    (platform_dir / f"carga_etapa{stage}_{position}.txt").write_text(
        Path("/proc/loadavg").read_text())


def gcov_result(build, gcov_dir, mode, count, core, stage, log):
    for path in build.glob("*.gcda"):
        path.unlink()
    csv_path = gcov_dir / f"{mode}_{count}.csv"
    command([build / "huffman_gcov", stage, count, core, mode],
            cwd=build, output=csv_path, log=log)
    raw = build / "huffman_gcov-huffman.gcov.json.gz"
    if raw.exists():
        raw.unlink()
    command(["gcov", "-b", "-c", "-j", "huffman_gcov-huffman.gcno"],
            cwd=build, output=gcov_dir / f"{mode}_{count}.gcov.txt", log=log)
    shutil.copyfile(raw, gcov_dir / f"{mode}_{count}.gcov.json.gz")
    with gzip.open(raw, "rt") as file:
        lines = next(item["lines"] for item in json.load(file)["files"]
                     if Path(item["file"]).name == "huffman.c")
    branches = [b for line in lines for b in line.get("branches", []) if not b.get("throw")]
    with csv_path.open() as file:
        hwm = max(float(row["tempo_us"]) for row in csv.DictReader(file))
    return {
        "linhas": [sum(line["count"] > 0 for line in lines), len(lines)],
        "desvios": [sum(b["count"] > 0 for b in branches), len(branches)],
        "linhas_nao_executadas": [line["line_number"] for line in lines if line["count"] == 0],
        "linhas_com_desvios_nao_cobertos": [line["line_number"] for line in lines
                                           if any(b["count"] == 0 for b in line.get("branches", [])
                                                  if not b.get("throw"))],
        "hwm_us": hwm, "amostras": count,
    }


def linux_run(run_dir, core):
    print("Linux · compilando e registrando a plataforma", flush=True)
    platform_dir = run_dir / "linux"
    build = ROOT / ".cache" / "linux" / run_dir.name
    data = platform_dir / "dados"
    coverage = platform_dir / "cobertura"
    for path in [data, coverage, build]:
        path.mkdir(parents=True, exist_ok=True)
    log = platform_dir / "execucao.log"
    machine(platform_dir, core)
    gcc = ["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
           ROOT / "src/linux.c", ROOT / "src/inputs.c", ROOT / "src/huffman.c"]
    command([*gcc, "-o", "huffman"], cwd=build, log=log)
    command([*gcc, "--coverage", "-o", "huffman_gcov"], cwd=build, log=log)
    for stage, count in COUNTS.items():
        print(f"Linux · etapa {stage}/4 · {count} ativações", flush=True)
        snapshot(platform_dir, stage, "antes")
        command([build / "huffman", stage, count, core, "aleatorio"],
                cwd=build, output=data / f"etapa{stage}.csv", log=log)
        snapshot(platform_dir, stage, "depois")
    print("Linux · cobertura de linhas e desvios", flush=True)
    prefixes = {str(n): gcov_result(build, coverage, "casos", n, core, 1, log)
                for n in (1, 2, 3, 4)}
    first_full = next((n for n, cov in prefixes.items()
                       if all(a == b and b for a, b in (cov["linhas"], cov["desvios"]))), None)
    # Unique sizes distinguish artifacts even though each rerun is independent.
    random = {str(stage): gcov_result(build, coverage, "aleatorio", 1000 + stage - 1,
                                     core, stage, log) for stage in COUNTS}
    save_json(coverage / "resumo.json", {"prefixos_dirigidos": prefixes,
              "primeiro_prefixo_completo": first_full, "aleatorio_por_etapa": random})


def package(run_dir, args, success):
    ra = args.ra
    named = ra and args.nome and args.repo
    stem = f"STR_M3_{ra}" if named and success else (
        f"STR_M3_RESULTADOS_{run_dir.name}" if success else f"STR_M3_PARCIAL_{run_dir.name}")
    archive = run_dir.parent / (stem + ".zip")
    if archive.exists():
        archive = run_dir.parent / f"{stem}_{run_dir.name}.zip"
    from zipfile import ZipFile, ZIP_DEFLATED
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for path in sorted(run_dir.rglob("*")):
            relative = path.relative_to(run_dir)
            if path.is_file() and relative.parts[0] != "codigo":
                bundle.write(path, relative)
        if success:
            for subdir in ("src", "esp32", "scripts"):
                for path in sorted((ROOT / subdir).rglob("*")):
                    if path.is_file() and "__pycache__" not in path.parts:
                        bundle.write(path, Path("codigo") / path.relative_to(ROOT))
            for name in ("README.md", "rodar.sh"):
                bundle.write(ROOT / name, Path("codigo") / name)
    print(f"Arquivo para enviar: {archive}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Campanha Huffman e geração do relatório.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--com-esp32", action="store_true",
                      help="autoriza gravar temporariamente a placa com backup e restauração")
    mode.add_argument("--linux-only", action="store_true", help="executa a campanha principal")
    parser.add_argument("--porta", help="porta USB serial se houver mais de uma conectada")
    parser.add_argument("--cpu", type=int, default=min(os.sched_getaffinity(0)))
    parser.add_argument("--nome", default="", help="nome completo para identificar o relatório")
    parser.add_argument("--ra", default="", help="RA individual para nomear o ZIP")
    parser.add_argument("--repo", default="", help="URL compartilhada do repositório")
    parser.add_argument("--saida", type=Path, default=ROOT / "resultados")
    parser.add_argument("--finalizar", type=Path, help="pasta extraída com resultados já coletados")
    parser.add_argument("--reusar-linux", type=Path, help="pasta linux de uma campanha anterior")
    args = parser.parse_args()
    if not (args.linux_only or args.com_esp32):
        args.linux_only = True
    if args.ra and not re.fullmatch(r"[a-zA-Z0-9.-]+", args.ra):
        parser.error("RA inválido para o nome do ZIP.")
    if args.repo and not re.fullmatch(r"https?://\S+", args.repo):
        parser.error("Passe o link compartilhado do repositório por inteiro.")
    try:
        import matplotlib
        if args.com_esp32:
            import serial
    except ImportError as exc:
        dependency = "python3-serial" if exc.name == "serial" else "python3-matplotlib"
        parser.error(f"Dependência Python indisponível. Instale {dependency} conforme o README.")
    if args.finalizar:
        if args.com_esp32 or args.reusar_linux is not None:
            parser.error("--finalizar utiliza exclusivamente os dados já coletados.")
        run_dir = args.finalizar.resolve()
        metadata_file = run_dir / "identificacao.json"
        metadata = json.loads(metadata_file.read_text())
        for key, new in [("nome", args.nome), ("ra", args.ra), ("repositorio", args.repo)]:
            if new:
                metadata[key] = new
        args.nome, args.ra, args.repo = (metadata[key] for key in ("nome", "ra", "repositorio"))
        save_json(metadata_file, metadata)
        from analyze import analyze_run
        analyze_run(run_dir)
        package(run_dir, args, True)
        return 0
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("A CPU selecionada não está disponível para este processo.")
    for binary in ("gcc", "gcov", "ps"):
        if not shutil.which(binary):
            parser.error(f"{binary} não encontrado. Veja o bloco de instalação no README.")
    run_dir = args.saida.resolve() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir.mkdir(parents=True)
    print(f"Dados desta execução: {run_dir}", flush=True)
    metadata = {"nome": args.nome, "ra": args.ra, "repositorio": args.repo,
                "esp32_solicitada": args.com_esp32}
    esp_error = None
    try:
        if args.reusar_linux:
            shutil.copytree(args.reusar_linux, run_dir / "linux")
        else:
            linux_run(run_dir, args.cpu)
        if args.com_esp32:
            from esp_collect import collect
            try:
                collect(run_dir, args.porta)
            except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired, ImportError) as exc:
                esp_error = str(exc)
                print(f"ESP32 · coleta interrompida: {esp_error}", flush=True)
        metadata["erro_esp32"] = esp_error
        save_json(run_dir / "identificacao.json", metadata)
        print("Gerando gráficos, tabelas e relatório", flush=True)
        from analyze import analyze_run
        analyze_run(run_dir)
    except (Exception, KeyboardInterrupt) as exc:
        save_json(run_dir / "falha.json", {"erro": str(exc) or type(exc).__name__})
        package(run_dir, args, False)
        raise
    package(run_dir, args, True)
    return 2 if esp_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
