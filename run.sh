#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ $# -lt 1 ]]; then
  echo "Usage: ./run.sh <path-to-library-root | [gui]> [additional add-library.py args]"
  echo "Example: ./run.sh \"/path/to/kontakt/lib\""
  echo "Example: ./run.sh --dry \"/path/to/kontakt/lib\""
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python add-library.py "$@"
