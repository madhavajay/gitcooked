#!/usr/bin/env python3
"""Build the network JSON the site's graph viz consumes.

Input: data/graph/nodes.jsonl (real crawl) or nodes.SIMULATED.jsonl (--simulated).
Output: site/public/data/network.json
  { "simulated": bool, "generatedAt": iso, "nodes": [...], "links": [[si,ti,mutual], ...] }

Nodes are the induced subgraph on RANKED users only (both edge endpoints must
be ranked). Node: {id, login, avatarUrl, country, rank, contributions}.
The "simulated" flag is propagated from the input records — a viz must show a
SIMULATED watermark when true, and real/simulated inputs are never merged.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "src" / "data"
GRAPH = ROOT / "data" / "graph"
OUT = ROOT / "site" / "public" / "data" / "network.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulated", action="store_true", help="use nodes.SIMULATED.jsonl")
    ap.add_argument("--min-degree", type=int, default=1)
    ap.add_argument("--max-nodes", type=int, default=8000)
    args = ap.parse_args()

    src = GRAPH / ("nodes.SIMULATED.jsonl" if args.simulated else "nodes.jsonl")
    if not src.exists():
        raise SystemExit(f"missing {src}")

    glob = json.loads((DATA / "global.json").read_text())
    ranked = {u["login"]: u for u in glob["modes"]["commits"]}

    store = {}
    simulated = args.simulated
    for line in src.open():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("error"):
            continue
        if rec.get("simulated") and not args.simulated:
            raise SystemExit("simulated records found in real store — refusing to build")
        store[rec["login"]] = rec

    follows = {}  # src -> set(dst), all ranked
    for login, rec in store.items():
        if login not in ranked:
            continue
        out = set()
        for t in rec.get("following") or []:
            if t in ranked:
                out.add(t)
        # follower edges are "t follows login"
        follows.setdefault(login, set()).update(out)
        for t in rec.get("followers") or []:
            if t in ranked:
                follows.setdefault(t, set()).add(login)

    # mutual detection + degree
    degree = {}
    for s, ts in follows.items():
        for t in ts:
            degree[s] = degree.get(s, 0) + 1
            degree[t] = degree.get(t, 0) + 1

    keep = {l for l, d in degree.items() if d >= args.min_degree}
    if len(keep) > args.max_nodes:
        keep = set(sorted(keep, key=lambda l: -degree[l])[: args.max_nodes])

    nodes = []
    idx = {}
    for login in sorted(keep, key=lambda l: ranked[l]["rank"]):
        u = ranked[login]
        idx[login] = len(nodes)
        nodes.append(
            {
                "id": len(nodes),
                "login": login,
                "avatarUrl": u.get("avatarUrl") or "",
                "country": (u.get("locations") or [None])[0],
                "rank": u["rank"],
                "contributions": u["contributions"],
                "crawled": login in store,
            }
        )

    links = []
    seen = set()
    for s, ts in follows.items():
        if s not in idx:
            continue
        for t in ts:
            if t not in idx:
                continue
            a, b = idx[s], idx[t]
            key = (min(a, b), max(a, b))
            if key in seen:
                continue
            seen.add(key)
            mutual = 1 if (t in follows and s in follows[t]) else 0
            links.append([a, b, mutual])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "simulated": simulated,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "crawledUsers": sum(1 for n in nodes if n["crawled"]),
                "nodes": nodes,
                "links": links,
            },
            ensure_ascii=False,
        )
    )
    mutuals = sum(1 for l in links if l[2])
    print(f"{'SIMULATED ' if simulated else ''}network: {len(nodes)} nodes, {len(links)} links ({mutuals} mutual) -> {OUT}")


if __name__ == "__main__":
    main()
