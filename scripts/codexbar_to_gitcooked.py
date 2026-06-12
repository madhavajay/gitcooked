#!/usr/bin/env python3
"""Convert a codexbar cost export into gitcooked monthly token ledgers.

Reads the codexbar JSON (list of providers w/ daily entries) from stdin or
--in, aggregates per provider per day, and writes/merges compact monthly
files the gitcooked indexer can ingest cheaply:

    <out>/2026-06.json
    { "schema": "gitcooked-tokens-v1", "month": "2026-06",
      "providers": { "codex": {
        "days": { "2026-06-02": [in, out, costCents] },
        "harnesses": { "codex-cli": { "days": { "2026-06-02": [in, out, costCents] } } } } } }

`days` is canonical (whose subscription burned). `harnesses` is a best-effort
breakdown of the same numbers by the tool that drove them (claude-code,
codex-cli, pi, ...) — harness sums may be lower than `days` when some usage
is not attributable. Requires codexbar >= the build that emits `harnesses`
in `cost --json`; older exports just produce ledgers without harnesses.

Existing files are merged (same day overwrites — codexbar is the source of
truth for any day it reports). Run it from cron / a git hook in your profile
repo and commit the result; past months stop changing on their own.

Usage:
  codexbar cost --json | python3 codexbar_to_gitcooked.py --out path/to/YOU/gitcooked/tokens/
  python3 codexbar_to_gitcooked.py --in export.json --out tokens/
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SCHEMA = "gitcooked-tokens-v1"


def day_triple(day):
    date = day.get("date")
    if not date or len(date) != 10:
        return None, None
    inp = int(day.get("inputTokens", 0) or 0)
    inp += int(day.get("cacheReadTokens", 0) or 0) + int(day.get("cacheCreationTokens", 0) or 0)
    out = int(day.get("outputTokens", 0) or 0)
    cents = round(float(day.get("totalCost", 0) or 0) * 100)
    return date, [inp, out, cents]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", help="codexbar JSON export (default: stdin)")
    ap.add_argument("--out", required=True, help="output dir (your profile repo's gitcooked/tokens/)")
    args = ap.parse_args()

    raw = Path(args.infile).read_text() if args.infile else sys.stdin.read()
    providers = json.loads(raw)
    if isinstance(providers, dict):
        providers = [providers]

    # month -> provider -> {"days": {...}, "harnesses": {harness: {day: triple}}}
    months = defaultdict(lambda: defaultdict(lambda: {"days": {}, "harnesses": defaultdict(dict)}))
    for p in providers:
        name = str(p.get("provider", "unknown"))[:30]
        for day in p.get("daily") or []:
            date, triple = day_triple(day)
            if date:
                months[date[:7]][name]["days"][date] = triple
        for h in p.get("harnesses") or []:
            harness = str(h.get("harness", ""))[:30]
            if not harness:
                continue
            for day in h.get("daily") or []:
                date, triple = day_triple(day)
                if date:
                    months[date[:7]][name]["harnesses"][harness][date] = triple

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    for month, provs in sorted(months.items()):
        path = outdir / f"{month}.json"
        doc = {"schema": SCHEMA, "month": month, "providers": {}}
        if path.exists():
            try:
                doc = json.loads(path.read_text())
                doc["schema"] = SCHEMA
            except Exception:
                pass
        for name, data in provs.items():
            slot = doc["providers"].setdefault(name, {"days": {}})
            slot["days"].update(data["days"])
            slot["days"] = dict(sorted(slot["days"].items()))
            for harness, days in data["harnesses"].items():
                hslot = slot.setdefault("harnesses", {}).setdefault(harness, {"days": {}})
                hslot["days"].update(days)
                hslot["days"] = dict(sorted(hslot["days"].items()))
            if "harnesses" in slot:
                slot["harnesses"] = dict(sorted(slot["harnesses"].items()))
        path.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
        total = sum(v[0] + v[1] for prov in doc["providers"].values() for v in prov["days"].values())
        harnesses = sorted({h for prov in doc["providers"].values() for h in prov.get("harnesses", {})})
        suffix = f", harnesses: {', '.join(harnesses)}" if harnesses else ""
        print(f"{path}  ({len(doc['providers'])} providers, {total:,} tokens{suffix})")


if __name__ == "__main__":
    main()
