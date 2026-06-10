#!/usr/bin/env bash
# gitcooked dev — fetch data (if missing), convert, run the site
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d data/locations ] || [ "${1:-}" = "--refresh" ]; then
  ./scripts/fetch_upstream.sh
fi

python3 scripts/convert.py

# derived data (regenerate if inputs exist / outputs missing)
[ -f data/graph/nodes.jsonl ] && python3 scripts/build_network.py
[ -f data/repos/repos.jsonl ] && python3 scripts/build_clusters.py
[ -f site/src/data/community.json ] || python3 scripts/fetch_community.py --limit 200
if [ ! -f site/src/data/history.json ] && [ -d committers.top/.git ]; then
  python3 scripts/extract_history.py
fi

cd site
[ -d node_modules ] || npm install
npm run dev
