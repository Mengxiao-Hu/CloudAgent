#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt

echo "Done. Activate with: source .venv/bin/activate"
echo "Or run: .venv/bin/python run.py"
