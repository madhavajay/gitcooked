#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGIN="${1:-$(gh api user --jq .login)}"
REPO="$LOGIN/$LOGIN"
DEST="gitcooked/tokens"
CODEXBAR="${CODEXBAR_BIN:-codexbar}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

"$CODEXBAR" cost --json 2>/dev/null > "$TMP/export.json"

mkdir -p "$TMP/tokens" "$TMP/before"
for month in $(jq -r '[.[].daily[]?.date[:7]] | unique | .[]' "$TMP/export.json"); do
  gh api "repos/$REPO/contents/$DEST/$month.json" --jq .content 2>/dev/null \
    | base64 -d 2>/dev/null > "$TMP/tokens/$month.json" || rm -f "$TMP/tokens/$month.json"
  [[ -s "$TMP/tokens/$month.json" ]] || rm -f "$TMP/tokens/$month.json"
done
cp "$TMP/tokens/"*.json "$TMP/before/" 2>/dev/null || true

python3 "$DIR/codexbar_to_gitcooked.py" --in "$TMP/export.json" --out "$TMP/tokens"

for f in "$TMP/tokens/"*.json; do
  name="$(basename "$f")"
  if cmp -s "$f" "$TMP/before/$name" 2>/dev/null; then
    echo "unchanged: $name"
    continue
  fi
  sha="$(gh api "repos/$REPO/contents/$DEST/$name" --jq .sha 2>/dev/null || true)"
  args=(--method PUT -f message="gitcooked tokens: ${name%.json}" -f content="$(base64 -i "$f" | tr -d '\n')")
  [[ -n "$sha" ]] && args+=(-f sha="$sha")
  gh api "repos/$REPO/contents/$DEST/$name" "${args[@]}" --jq '.commit.sha' > /dev/null
  echo "uploaded: $REPO/$DEST/$name"
done
