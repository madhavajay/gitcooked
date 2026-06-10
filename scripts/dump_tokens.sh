#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$HOME/dev/madhavajay/gitcooked/tokens}"
CODEXBAR="${CODEXBAR_BIN:-codexbar}"

"$CODEXBAR" cost --json 2>/dev/null | python3 "$DIR/codexbar_to_gitcooked.py" --out "$OUT"
