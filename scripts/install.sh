#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Jarvis v5 install =="
echo "Root: $ROOT"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found"
  exit 1
fi

echo "== Step 1: bootstrap =="
python3 "$ROOT/scripts/bootstrap.py" --root "$ROOT"

echo
echo "== Step 2: generate config =="
python3 "$ROOT/scripts/generate_config.py" --root "$ROOT"

echo
echo "== Step 3: validate =="
python3 "$ROOT/scripts/validate.py" --root "$ROOT"

echo
echo "Jarvis v5 scaffold install completed successfully."
echo "Next recommended steps:"
echo "  1. review config/*.yaml"
echo "  2. fill real Discord IDs / tokens / model endpoints"
echo "  3. run doctor.py once it is added"
echo "  4. run smoke_test.py once it is added"
