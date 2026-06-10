#!/usr/bin/env python3
"""Generate a SIMULATED follower graph for UI testing only.

Writes data/graph/nodes.SIMULATED.jsonl using real ranked logins but FAKE
edges (rank-weighted preferential attachment + country homophily). Every
record carries "simulated": true and downstream tooling must propagate it.
Never mix this file into real crawl data.
"""
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "src" / "data"
OUT = ROOT / "data" / "graph" / "nodes.SIMULATED.jsonl"

random.seed(42)

index = json.loads((DATA / "index.json").read_text())
users = []  # (login, country, rank)
for loc in index:
    if loc["slug"] == "worldwide":
        continue
    locdata = json.loads((DATA / "locations" / f"{loc['slug']}.json").read_text())
    for u in locdata["modes"]["commits"][:60]:
        users.append((u["login"], loc["slug"], u["rank"]))

# dedupe keeping first
seen = set()
uniq = []
for u in users:
    if u[0] not in seen:
        seen.add(u[0])
        uniq.append(u)
users = uniq
print(f"simulating over {len(users)} users")

by_country = {}
for u in users:
    by_country.setdefault(u[1], []).append(u)

logins = [u[0] for u in users]
weights = [1.0 / (u[2] ** 0.6) for u in users]  # popular = low rank = more followers

follows = {l: set() for l in logins}
for login, country, rank in users:
    n_following = min(len(users) - 1, max(3, int(random.gauss(40, 25))))
    local = by_country[country]
    for _ in range(n_following):
        if local and random.random() < 0.45:  # country homophily
            t = random.choice(local)[0]
        else:
            t = random.choices(logins, weights=weights, k=1)[0]
        if t != login:
            follows[login].add(t)

followers = {l: set() for l in logins}
for src, ts in follows.items():
    for t in ts:
        followers[t].add(src)

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w") as f:
    for login, country, rank in users:
        f.write(
            json.dumps(
                {
                    "login": login,
                    "simulated": True,
                    "followers": sorted(followers[login]),
                    "following": sorted(follows[login]),
                    "followerCount": len(followers[login]),
                    "followingCount": len(follows[login]),
                    "truncated": False,
                    "fetchedAt": "1970-01-01T00:00:00+00:00",
                }
            )
            + "\n"
        )
edge_count = sum(len(v) for v in follows.values())
print(f"wrote {len(users)} simulated nodes, {edge_count} directed edges -> {OUT}")
