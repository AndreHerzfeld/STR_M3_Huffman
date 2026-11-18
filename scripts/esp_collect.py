"""Build, collect and restore a development board using the active ESP-IDF SDK."""
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
import zlib

from run_campaign import ROOT, COUNTS, command, save_json

TARGETS = {"ESP32": "esp32", "ESP32-S2": "esp32s2", "ESP32-S3": "esp32s3",
           "ESP32-C3": "esp32c3", "ESP32-C6": "esp32c6"}
BAUDS = ("460800", "115200")


def find_port(port):
    by_path = {p.resolve(): p for p in sorted(Path("/dev/serial/by-path").glob("*"))}
    if port:
        selected = Path(port)
        if not selected.exists():
            raise RuntimeError(f"Porta ausente: {selected}. Confira o cabo USB de dados.")
        return by_path.get(selected.resolve(), selected)
    # Prefer the persistent physical path, including for bridges without a serial number.
    names = [*Path("/dev").glob("ttyUSB*"), *Path("/dev").glob("ttyACM*")]
    matches = [by_path.get(p, p) for p in sorted(names)]
    if len(matches) != 1:
        raise RuntimeError(f"Esperava uma porta USB serial. Encontrei {len(matches)}. "
                           "Use um cabo USB de dados e, se houver mais placas, passe --porta /dev/ttyUSB0.")
    return matches[0]


def wait_port(original):
    for _ in range(50):
        if original.exists():
            return original
        time.sleep(0.2)
    raise RuntimeError(f"A porta serial {original} não reapareceu após o reset.")


def active_sdk():
    root = os.environ.get("IDF_PATH")
    tip = ("No VS Code, selecione ESP-IDF: Open ESP-IDF Terminal e confira "
           "a instalação com idf.py --version.")
    if not root:
        raise RuntimeError(f"A variável IDF_PATH está ausente. {tip}")
    idf = Path(root) / "tools" / "idf.py"
    if not idf.is_file():
        raise RuntimeError(f"idf.py não encontrado em {idf}. {tip}")
    venv = os.environ.get("IDF_PYTHON_ENV_PATH")
    python = str(Path(venv) / "bin" / "python") if venv else (
        shutil.which("python") or shutil.which("python3"))
    if not python or not os.path.isfile(python) or not os.access(python, os.X_OK):
        raise RuntimeError(f"O Python do ambiente ESP-IDF não foi localizado. {tip}")
    # Do not resolve the virtual environment's Python symlink.
    return python, idf


def parse_fuse_value(field):
    if "readable" in field and field["readable"] is not True:
        raise ValueError("eFuse de segurança não legível.")
    value = field["raw_value"] if "raw_value" in field else field["value"]
    if isinstance(value, (int, bool)):
        return int(value)
    if value in ("True", "False"):
        return int(value == "True")
    try:
        return int(value, 0)
    except (TypeError, ValueError):
        return int(value, 10)


def confirm_unprotected(path, target):
    fuses = json.loads(path.read_text())
    try:
        encryption = "FLASH_CRYPT_CNT" if target == "esp32" else "SPI_BOOT_CRYPT_CNT"
        secure_fields = ("ABS_DONE_0", "ABS_DONE_1") if target == "esp32" else ("SECURE_BOOT_EN",)
        if parse_fuse_value(fuses[encryption]).bit_count() % 2:
            raise RuntimeError("A placa usa criptografia de flash. A gravação foi bloqueada.")
        if any(parse_fuse_value(fuses[key]) for key in secure_fields):
            raise RuntimeError("A placa usa Secure Boot. A gravação foi bloqueada.")
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Não foi possível confirmar o estado dos eFuses de segurança. "
                           "A gravação foi bloqueada.") from exc


def capture(port, data_dir, log):
    import serial
    expected = 1
    rows = None
    meta = None
    crc = 0
    started = time.monotonic()
    limit = started + 220
    while not port.exists() and time.monotonic() - started < 12:
        time.sleep(0.2)
    with serial.Serial(port=None, baudrate=115200, timeout=0.7, exclusive=True) as device:
        device.port = str(port)
        device.dtr = device.rts = False
        device.open()
        with log.open("ab") as transcript:
            transcript.write(b"\n--- captura ---\n")
            while time.monotonic() < limit:
                raw = device.readline()
                if not raw:
                    continue
                transcript.write(raw)
                value = raw.decode(errors="replace").strip()
                parts = value.split(",")
                tag = parts[0]
                if tag == "STR_META" and len(parts) == 9:
                    meta = parts[1:]
                elif tag == "STR_BEGIN" and len(parts) == 3:
                    if rows is not None or int(parts[1]) != expected or int(parts[2]) != COUNTS[expected]:
                        raise RuntimeError("Início de etapa serial fora da sequência esperada.")
                    rows = []
                    crc = 0
                elif tag == "STR_ROW" and len(parts) == 3 and rows is not None:
                    idx, us = map(int, parts[1:])
                    if idx != len(rows) + 1 or len(rows) >= COUNTS[expected] or not 0 < us <= 0xffffffff:
                        raise RuntimeError("Amostra ausente, duplicada ou inválida na serial.")
                    rows.append((idx, us))
                    crc = zlib.crc32(struct.pack("<II", idx, us), crc)
                elif tag == "STR_END" and len(parts) == 5:
                    stage, count, errors = map(int, parts[1:4])
                    if rows is None or stage != expected or count != COUNTS[expected] or len(rows) != count or errors:
                        raise RuntimeError(f"Etapa {stage}: dados incompletos ou validação Huffman falhou ({errors}).")
                    if int(parts[4], 16) != crc:
                        raise RuntimeError(f"Etapa {stage}: a verificação CRC dos dados seriais falhou.")
                    partial = data_dir / f"etapa{expected}.tmp"
                    with partial.open("w", newline="") as file:
                        writer = csv.writer(file)
                        writer.writerow(("ativacao", "tempo_us"))
                        writer.writerows(rows)
                    partial.rename(data_dir / f"etapa{expected}.csv")
                    print(f"ESP32 · etapa {expected}/4 · {count} ativações recebidas", flush=True)
                    expected += 1
                    rows = None
                elif tag == "STR_DONE" and meta and expected == len(COUNTS) + 1 and rows is None:
                    return meta
    raise RuntimeError("Tempo limite de coleta serial. Veja serial.log, experimente outra porta/cabo "
                       "e verifique se outro monitor serial está aberto.")


def collect(run_dir, selected_port):
    sdk_python, idf = active_sdk()
    original_port = find_port(selected_port)
    if not os.access(original_port, os.R_OK | os.W_OK):
        raise RuntimeError("Sem acesso à porta serial. Adicione seu usuário a dialout e entre de novo no Ubuntu.")
    platform_dir = run_dir / "esp32"
    data_dir = platform_dir / "dados"
    data_dir.mkdir(parents=True)
    log = platform_dir / "execucao.log"
    from serial.tools import list_ports
    # The flash backup and eFuse record stay on the owner's computer.
    private = ROOT / ".cache" / "esp32" / run_dir.name
    private.mkdir(parents=True, mode=0o700)
    backup = private / "flash-original.bin"

    def sdk(args, output=None, timeout=1200):
        return command([sdk_python, *args], cwd=ROOT / "esp32", output=output,
                       log=log, timeout=timeout)

    idf_version = sdk([idf, "--version"], timeout=45).strip()
    if not idf_version:
        raise RuntimeError("A versão do SDK não foi informada por idf.py --version.")
    print(f"ESP32 · {idf_version} do terminal ativo", flush=True)
    esptool_version = sdk(["-c", "from importlib.metadata import version; print(version('esptool'))"],
                          timeout=45).strip()
    major_text, separator, _ = esptool_version.partition(".")
    if not separator or not major_text.isdecimal():
        raise RuntimeError("Versão de esptool não identificada.")
    major = int(major_text)
    if major not in (4, 5):
        raise RuntimeError(f"Versão de esptool não contemplada pelo coletor: {major}.")

    def flash_tool(target, baud, verb, *args, output=None, timeout=240):
        cmd = ["-m", "esptool", "--chip", target, "--port", wait_port(original_port),
               "--baud", baud, verb if major == 4 else verb.replace("_", "-"), *args]
        return sdk(cmd, output=output, timeout=timeout)

    def retry(operation, label, recoverable=(RuntimeError, OSError, subprocess.TimeoutExpired)):
        for index, baud in enumerate(BAUDS):
            try:
                return operation(baud)
            except recoverable as exc:
                if index == len(BAUDS) - 1:
                    raise
                print(f"ESP32 · repetindo {label} a 115200 baud ({str(exc).splitlines()[0]})", flush=True)

    identification = private / "identificacao-esptool.txt"
    detected = retry(lambda baud: flash_tool("auto", baud, "flash_id", output=identification),
                     "identificação")
    chip = re.search(r"(?:Chip is|Chip type:\s*|Connected to)\s*(ESP32(?:-[A-Z]\d+)?)\b", detected, re.I)
    if not chip or chip.group(1).upper() not in TARGETS:
        raise RuntimeError("Modelo fora dos alvos ESP32, S2, S3, C3 e C6 disponíveis no kit.")
    target = TARGETS[chip.group(1).upper()]
    fuses = private / "efuses.json"
    sdk(["-m", "espefuse", "--chip", target, "--port", wait_port(original_port),
         "summary", "--format", "json", "--file", fuses],
        output=private / "efuses-saida.txt", timeout=90)
    confirm_unprotected(fuses, target)
    # UART bridges can also enumerate as ACM. Build UART by default unless the USB
    # vendor is Espressif or the adapter is the S2's native bootloader.
    usb_device = next((p for p in list_ports.comports() if p.device == str(original_port.resolve())), None)
    native = usb_device is not None and usb_device.vid == 0x303A
    sdk_defaults = str(ROOT / "esp32/sdkconfig.defaults")
    extra = []
    if native and target != "esp32":
        extra.append("CONFIG_ESP_CONSOLE_USB_CDC=y" if target == "esp32s2"
                     else "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y")
    if re.search(r"Features:.*Single Core", detected, re.I) and target == "esp32":
        extra.append("CONFIG_FREERTOS_UNICORE=y")
    if extra:
        extra_defaults = private / "sdkconfig.defaults.port"
        extra_defaults.write_text("\n".join(extra) + "\n")
        sdk_defaults += ";" + str(extra_defaults)
    build_options = [idf, "-B", private / "build", "-D", "IDF_TARGET=" + target,
                     "-D", f"SDKCONFIG={private / 'sdkconfig'}",
                     "-D", "SDKCONFIG_DEFAULTS=" + sdk_defaults]
    print(f"ESP32 · compilando para {target}", flush=True)
    sdk([*build_options, "build"])

    print("ESP32 · fazendo backup local de toda a flash", flush=True)
    # A full 4 MB read at 115200 baud takes about 6 minutes; the default 240 s would cut it off.
    retry(lambda baud: flash_tool(target, baud, "read_flash", "0", "ALL", backup, timeout=900),
          "backup")
    capacity = re.search(r"Detected flash size:\s*(\d+)\s*(KB|MB)", detected, re.I)
    divisor = {"KB": 1024, "MB": 1024 * 1024}
    expected = int(capacity.group(1)) * divisor[capacity.group(2).upper()] if capacity else 0
    if not expected or backup.stat().st_size != expected or expected < 2 * 1024 * 1024:
        raise RuntimeError("Tamanho do backup ou da flash incompatível. Nada foi gravado.")
    backup.chmod(0o600)

    def restore(baud):
        flash_tool(target, baud, "write_flash", "--flash_mode" if major == 4 else "--flash-mode",
                   "keep", "--flash_freq" if major == 4 else "--flash-freq", "keep",
                   "--flash_size" if major == 4 else "--flash-size", "keep", "0", backup,
                   timeout=360)

    try:
        print("ESP32 · gravando o firmware de teste e coletando pela serial", flush=True)
        retry(lambda baud: sdk([*build_options, "-p", wait_port(original_port), "-b", baud, "flash"],
                               timeout=330), "gravação temporária")
        try:
            meta = capture(wait_port(original_port),
                           data_dir, platform_dir / "serial.log")
        except (RuntimeError, OSError, ValueError):
            print("ESP32 · reiniciando a campanha serial", flush=True)
            retry(lambda baud: flash_tool(target, baud, "flash_id", output=identification), "reinício")
            meta = capture(wait_port(original_port),
                           data_dir, platform_dir / "serial.log")
        keys = ("idf", "nucleos_fisicos", "nucleos_escalonador", "revisao", "tick_hz",
                "frequencia_mhz", "tamanho", "semente")
        record = dict(zip(keys, [meta[0], *map(int, meta[1:])]))
        if record["tamanho"] != 2048 or record["semente"] != 20261118:
            raise RuntimeError("O firmware respondeu com outra configuração experimental.")
        save_json(platform_dir / "plataforma.json", {**record, "plataforma": "ESP32",
                  "esptool": esptool_version,
                  "alvo": target, "data_local": datetime.now().astimezone().isoformat(),
                  "periodo_huffman_us": 5000, "cpu_teste": 0, "alfabeto": 16,
                  "governor_cpu_teste": "frequência fixa configurada no firmware",
                  "programas": "FreeRTOS, tarefas do firmware, timer de estresse na etapa 4; sem Wi-Fi/BLE."})
    finally:
        print("ESP32 · restaurando o firmware original", flush=True)
        try:
            retry(restore, "restauração")
        except BaseException as exc:
            raise RuntimeError(f"Restauração incompleta. Backup local preservado em {backup}. "
                               "Mantenha a placa conectada e veja a seção Restauração do README.") from exc
        save_json(platform_dir / "restauracao.json", {"firmware_original_restaurado": True})
