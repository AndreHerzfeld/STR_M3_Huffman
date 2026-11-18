#!/usr/bin/env bash
set -euo pipefail
KIT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
host_python=python3
if [[ -n "${IDF_PATH:-}" && -x /usr/bin/python3 ]]; then
    # The SDK's virtualenv is for Espressif tools. Ubuntu packages use system Python.
    host_python=/usr/bin/python3
fi
exec "$host_python" "$KIT_DIR/scripts/run_campaign.py" "$@"
