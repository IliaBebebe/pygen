#!/usr/bin/env bash
# ==============================================================================
# PyGen Linux Installer (No root / No sudo)
# ==============================================================================
set -e

PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo "[!] Ошибка: Python 3 не найден в системе. Установите python3."
    exit 1
fi

SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/run.py" ]; then
    "$PYTHON_BIN" "$SCRIPT_DIR/run.py" --install
else
    TEMP_PY="/tmp/pygen_setup_$$.py"
    if ! curl -fsSL "https://rexcorp.space/p" -o "$TEMP_PY" 2>/dev/null || [ ! -s "$TEMP_PY" ]; then
        curl -fsSL "https://raw.githubusercontent.com/IliaBebebe/pygen/main/run.py" -o "$TEMP_PY"
    fi
    "$PYTHON_BIN" "$TEMP_PY" --install
    rm -f "$TEMP_PY"
fi
