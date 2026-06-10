#!/usr/bin/env bash
# Seed/refresh data/ from committers.top gh-pages branch
set -euo pipefail
cd "$(dirname "$0")/.."

UPSTREAM_DIR="committers.top"

if [ ! -d "$UPSTREAM_DIR/.git" ]; then
  git clone https://github.com/ashkulz/committers.top.git "$UPSTREAM_DIR"
fi

git -C "$UPSTREAM_DIR" fetch origin gh-pages
mkdir -p data
git -C "$UPSTREAM_DIR" archive origin/gh-pages _data/locations | tar -x --strip-components=1 -C data
git -C "$UPSTREAM_DIR" archive origin/gh-pages rank_only | tar -x -C data
echo "Fetched $(ls data/locations | wc -l | tr -d ' ') location files into data/locations"
