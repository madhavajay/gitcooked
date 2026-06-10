#!/usr/bin/env python3
"""VouchRank: PageRank-style trust score over the crawled follow graph.

A follow is an endorsement: edge u -> v when u follows v. Teleport vector is
weighted by contribution ranking (1/sqrt(rank)), so attention from highly
ranked committers is worth more, and scores are damped through the whole
graph the PageRank way — you can't buy it with bot followers that nobody
follows.

Output: site/public/data/vouchrank.json
  { "generatedAt": iso, "crawled": N,
    "users": { login: [vrRank, score, followers, following, contribRank] } }
score is 0-1000 (log-normalized against the max).
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "src" / "data"
GRAPH = ROOT / "data" / "graph"
OUT = ROOT / "site" / "public" / "data" / "vouchrank.json"

DAMPING = 0.85
ITERS = 40


def load_store():
    store = {}
    files = [p for p in [GRAPH / "nodes.jsonl"] if p.exists()]
    files += sorted((GRAPH / "shards").glob("*.jsonl")) if (GRAPH / "shards").is_dir() else []
    for f in files:
        for line in f.open():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("error") or rec.get("simulated"):
                continue
            store[rec["login"]] = rec
    return store


def main():
    glob = json.loads((DATA / "global.json").read_text())
    ranked = {u["login"]: u["rank"] for u in glob["modes"]["commits"]}
    meta = {u["login"]: u for u in glob["modes"]["commits"]}
    store = load_store()

    # directed endorsement edges within the ranked set: follower -> followee
    out_edges = {}
    logins = set()
    for login, rec in store.items():
        if login not in ranked:
            continue
        logins.add(login)
        for f in rec.get("following") or []:
            if f in ranked:
                out_edges.setdefault(login, set()).add(f)
        for f in rec.get("followers") or []:
            if f in ranked:
                logins.add(f)
                out_edges.setdefault(f, set()).add(login)

    idx = {l: i for i, l in enumerate(sorted(logins))}
    names = sorted(logins)
    n = len(names)
    out = [[] for _ in range(n)]
    for src, dsts in out_edges.items():
        out[idx[src]] = [idx[d] for d in dsts if d in idx]

    # teleport weighted by contribution rank
    tele = [1.0 / math.sqrt(ranked.get(l, 10**6)) for l in names]
    tsum = sum(tele)
    tele = [t / tsum for t in tele]

    pr = tele[:]
    for _ in range(ITERS):
        nxt = [0.0] * n
        dangling = 0.0
        for i in range(n):
            if out[i]:
                share = pr[i] / len(out[i])
                for j in out[i]:
                    nxt[j] += share
            else:
                dangling += pr[i]
        pr = [(1 - DAMPING) * tele[i] + DAMPING * (nxt[i] + dangling * tele[i]) for i in range(n)]

    indeg = [0] * n
    for i in range(n):
        for j in out[i]:
            indeg[j] += 1

    mx = max(pr) or 1.0
    order = sorted(range(n), key=lambda i: -pr[i])
    users = {}
    for vr_rank, i in enumerate(order, 1):
        login = names[i]
        rec = store.get(login) or {}
        score = round(1000 * (math.log1p(pr[i] / mx * 1000) / math.log1p(1000)))
        users[login] = [
            vr_rank,
            score,
            rec.get("followerCount"),
            rec.get("followingCount"),
            ranked.get(login),
            indeg[i],  # in-network endorsements (known even before the user is crawled)
        ]

    OUT.write_text(
        json.dumps(
            {
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "crawled": len(store),
                "users": users,
            },
            ensure_ascii=False,
        )
    )

    # enriched rows for the leaderboard table (SSR head + paginated chunks)
    def enrich(i):
        login = names[i]
        u = users[login]
        m = meta.get(login) or {}
        return {
            "vrRank": u[0],
            "score": u[1],
            "login": login,
            "name": m.get("name") or "",
            "avatarUrl": m.get("avatarUrl") or "",
            "company": m.get("company") or "",
            "locations": (m.get("locations") or [])[:3],
            "followers": u[2],
            "inNetwork": u[5],
            "contribRank": u[4],
        }

    rows = [enrich(i) for i in order]
    (DATA / "vouchrank_top.json").write_text(json.dumps(rows[:200], ensure_ascii=False))
    chunk_dir = OUT.parent / "vouchrank_pages"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    page_size = 500
    for p in range(0, len(rows), page_size):
        (chunk_dir / f"page-{p // page_size}.json").write_text(
            json.dumps(rows[p : p + page_size], ensure_ascii=False)
        )
    (chunk_dir / "meta.json").write_text(json.dumps({"total": len(rows), "pageSize": page_size}))
    print(f"vouchrank over {n} users ({len(store)} crawled) -> {OUT} + {len(rows) // page_size + 1} chunks")
    for i in order[:10]:
        print(f"  {users[names[i]][0]:>3}. {names[i]:<22} score {users[names[i]][1]}")


if __name__ == "__main__":
    main()
