#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  Prism — terminal launcher (macOS)
#  Sets up a local venv on first run, then launches the REPL.
# ═══════════════════════════════════════════════════════════════
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo ""
echo "🌈  Starting Prism…"
echo "─────────────────────────────────────────"

# Pick a Python 3 (prefer Homebrew 3.12 for a modern Tcl/Tk & clean pip).
PY="$(command -v python3.12 || command -v python3)"
if [ -z "$PY" ]; then
    echo "❌  Python 3 not found. Install it from https://python.org or 'brew install python@3.12'."
    exit 1
fi

VENV="$DIR/.venv"
if [ ! -d "$VENV" ]; then
    echo "📦  First run — creating virtual environment…"
    "$PY" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip setuptools packaging
    echo "📦  Installing dependencies (this can take a minute)…"
    "$VENV/bin/pip" install --quiet -r "$DIR/requirements.txt"
    echo "   ✅  Ready."
fi

echo ""
"$VENV/bin/python" "$DIR/prism.py" "$@"
