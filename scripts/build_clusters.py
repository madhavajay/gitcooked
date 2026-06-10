#!/usr/bin/env python3
"""Build dev clusters from co-contribution data (data/repos/repos.jsonl).

Two ranked users are connected when they share a repo (owned or contributed,
weighted by 1/log2(2+repo_user_count) so mega-repos don't glue everyone
together). Communities via label propagation. Clusters are labeled by their
dominant languages and most-shared repos.

Output: site/src/data/clusters.json
"""
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "src" / "data"
SRC = ROOT / "data" / "repos" / "repos.jsonl"
OUT = DATA / "clusters.json"

random.seed(7)


def main():
    if not SRC.exists():
        raise SystemExit(f"missing {SRC} — run scripts/index_repos.py first")

    glob = json.loads((DATA / "global.json").read_text())
    ranked = {u["login"]: u for u in glob["modes"]["commits"]}

    users = {}
    repo_users = defaultdict(set)
    user_langs = defaultdict(Counter)
    for line in SRC.open():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("error") or rec["login"] not in ranked:
            continue
        users[rec["login"]] = rec
        for kind in ("owned", "contributed"):
            for r in rec.get(kind) or []:
                repo_users[r["repo"]].add(rec["login"])
                if r.get("lang"):
                    user_langs[rec["login"]][r["lang"]] += 1

    # weighted co-contribution edges
    weights = defaultdict(float)
    shared_repos = defaultdict(list)
    for repo, members in repo_users.items():
        if len(members) < 2 or len(members) > 50:
            continue
        w = 1.0 / math.log2(2 + len(members))
        ms = sorted(members)
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                key = (ms[i], ms[j])
                weights[key] += w
                shared_repos[key].append(repo)

    adj = defaultdict(dict)
    for (a, b), w in weights.items():
        adj[a][b] = w
        adj[b][a] = w

    # label propagation
    labels = {u: u for u in adj}
    nodes = list(adj)
    for _ in range(30):
        random.shuffle(nodes)
        changed = 0
        for n in nodes:
            tally = Counter()
            for m, w in adj[n].items():
                tally[labels[m]] += w
            if not tally:
                continue
            best = tally.most_common(1)[0][0]
            if best != labels[n]:
                labels[n] = best
                changed += 1
        if changed == 0:
            break

    groups = defaultdict(list)
    for u, l in labels.items():
        groups[l].append(u)

    clusters = []
    for members in groups.values():
        if len(members) < 3:
            continue
        langs = Counter()
        for u in members:
            langs.update(user_langs[u])
        repos = Counter()
        mset = set(members)
        for repo, rmembers in repo_users.items():
            n = len(rmembers & mset)
            if n >= 2:
                repos[repo] = n
        members_sorted = sorted(members, key=lambda u: ranked[u]["rank"])
        top_langs = [l for l, _ in langs.most_common(3)]
        clusters.append(
            {
                "id": len(clusters),
                "label": " / ".join(top_langs[:2]) if top_langs else "polyglot",
                "languages": top_langs,
                "size": len(members),
                "topRepos": [{"repo": r, "sharedBy": n} for r, n in repos.most_common(6)],
                "members": [
                    {
                        "login": u,
                        "rank": ranked[u]["rank"],
                        "avatarUrl": ranked[u].get("avatarUrl") or "",
                        "country": (ranked[u].get("locations") or [None])[0],
                    }
                    for u in members_sorted[:30]
                ],
            }
        )
    clusters.sort(key=lambda c: -c["size"])

    OUT.write_text(
        json.dumps(
            {
                "indexedUsers": len(users),
                "connectedUsers": len(adj),
                "clusters": clusters,
            },
            ensure_ascii=False,
        )
    )
    print(f"{len(users)} users indexed, {len(adj)} connected, {len(clusters)} clusters -> {OUT}")
    for c in clusters[:8]:
        print(f"  [{c['size']:>3}] {c['label']:<24} {', '.join(m['login'] for m in c['members'][:5])}")


if __name__ == "__main__":
    main()
