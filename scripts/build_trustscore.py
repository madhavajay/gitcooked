#!/usr/bin/env python3
"""TrustScore: the gitcooked flagship metric. 0–1000, explainable.

  network attention  0–400  VouchRank (rank-weighted PageRank over follows)
  bacon index        0–200  harmonic proximity to the top-50 VouchRank anchors
                            (mean of 1/d to each anchor, rescaled to the max)
  activity           0–300  contribution-rank, log-scaled (#1 = 300)
  vouches            0–100  +20 per distinct repo-OWNER vouching you (owner
                            dedupe kills mass-vouch farms), via VOUCHED.td
                            and gitcooked.json peers
  denouncements      ≤0     −80 per distinct denouncing owner (floor −400)

Inputs: vouchrank.json, global.json, graph shards, community.json
Outputs:
  site/public/data/trust.json          compact lookup for all ranked users
  site/public/data/trust_pages/*.json  enriched chunks for the board
  site/src/data/trust_top.json         top 200 enriched (SSR)
  site/src/data/trust_map.json         login -> [trustRank, score] (profile SSR)
"""
import json
import math
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "src" / "data"
PUB = ROOT / "site" / "public" / "data"
GRAPH = ROOT / "data" / "graph"

W_VOUCHRANK = 400
W_BACON = 200
W_ACTIVITY = 300
VOUCH_PER_OWNER = 20
VOUCH_CAP = 100
DENOUNCE_PER_OWNER = -80
DENOUNCE_FLOOR = -400
ANCHORS = 50


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
    ranked = {u["login"]: u for u in glob["modes"]["commits"]}
    total_ranked = len(ranked)
    vr = json.loads((PUB / "vouchrank.json").read_text())["users"]
    community = json.loads((DATA / "community.json").read_text())
    store = load_store()

    # undirected adjacency over ranked users (for the bacon BFS)
    idx = {}
    adj = []

    def node(login):
        if login not in idx:
            idx[login] = len(adj)
            adj.append([])
        return idx[login]

    for login, rec in store.items():
        if login not in ranked:
            continue
        i = node(login)
        for conn in ("followers", "following"):
            for other in rec.get(conn) or []:
                if other in ranked:
                    j = node(other)
                    adj[i].append(j)
                    adj[j].append(i)
    names = sorted(idx, key=idx.get)
    n = len(names)

    # anchors = top-50 by vouchrank present in the graph
    anchors = [l for l, v in sorted(vr.items(), key=lambda kv: kv[1][0]) if l in idx][:ANCHORS]
    print(f"graph: {n} nodes; anchors: {len(anchors)} (top vouchrank)")

    # harmonic proximity: mean over anchors of 1/d(anchor, u)
    bacon_raw = [0.0] * n
    for a in anchors:
        dist = [-1] * n
        src = idx[a]
        dist[src] = 0
        q = deque([src])
        while q:
            u = q.popleft()
            for v in adj[u]:
                if dist[v] < 0:
                    dist[v] = dist[u] + 1
                    q.append(v)
        for i in range(n):
            if dist[i] > 0:
                bacon_raw[i] += 1.0 / dist[i]
            elif dist[i] == 0:
                bacon_raw[i] += 1.0
    mx_bacon = max(bacon_raw) or 1.0

    # modifiers: distinct owners vouching/denouncing
    vouch_owners = {}
    denounce_owners = {}
    for login, lst in (community.get("repoVouches") or {}).items():
        vouch_owners.setdefault(login, set()).update(x["repo"].split("/")[0].lower() for x in lst)
    for login, lst in (community.get("vouches") or {}).items():
        vouch_owners.setdefault(login, set()).update(x["voucher"].lower() for x in lst)
    for login, lst in (community.get("denounced") or {}).items():
        denounce_owners.setdefault(login, set()).update(x["repo"].split("/")[0].lower() for x in lst)

    log_total = math.log(total_ranked + 1)
    rows = []
    for login, u in ranked.items():
        v = vr.get(login)
        vr_pts = W_VOUCHRANK * (v[1] / 1000) if v else 0.0
        bacon_pts = W_BACON * (bacon_raw[idx[login]] / mx_bacon) if login in idx else 0.0
        act_pts = W_ACTIVITY * (1 - math.log(u["rank"]) / log_total)
        vouch_pts = min(VOUCH_CAP, VOUCH_PER_OWNER * len(vouch_owners.get(login, ())))
        den_pts = max(DENOUNCE_FLOOR, DENOUNCE_PER_OWNER * len(denounce_owners.get(login, ())))
        score = max(0, min(1000, round(vr_pts + bacon_pts + act_pts + vouch_pts + den_pts)))
        rows.append(
            {
                "login": login,
                "score": score,
                "parts": [round(vr_pts), round(bacon_pts), round(act_pts), vouch_pts, den_pts],
                "name": u.get("name") or "",
                "avatarUrl": u.get("avatarUrl") or "",
                "company": u.get("company") or "",
                "contribRank": u["rank"],
                "vrRank": v[0] if v else None,
                "crawledIn": login in idx,
            }
        )
    rows.sort(key=lambda r: (-r["score"], r["contribRank"]))
    for i, r in enumerate(rows):
        r["trustRank"] = i + 1

    compact = {r["login"]: [r["trustRank"], r["score"]] + r["parts"] for r in rows}
    PUB.mkdir(parents=True, exist_ok=True)
    (PUB / "trust.json").write_text(
        json.dumps(
            {"generatedAt": datetime.now(timezone.utc).isoformat(), "total": len(rows), "users": compact},
            ensure_ascii=False,
        )
    )
    (DATA / "trust_top.json").write_text(json.dumps(rows[:200], ensure_ascii=False))
    (DATA / "trust_map.json").write_text(
        json.dumps({r["login"]: [r["trustRank"], r["score"]] for r in rows}, ensure_ascii=False)
    )
    vouched_rows = [r for r in rows if r["parts"][3] != 0 or r["parts"][4] != 0]
    (PUB / "trust_vouched.json").write_text(json.dumps(vouched_rows, ensure_ascii=False))
    chunk_dir = PUB / "trust_pages"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    page = 500
    for p in range(0, len(rows), page):
        (chunk_dir / f"page-{p // page}.json").write_text(json.dumps(rows[p : p + page], ensure_ascii=False))
    (chunk_dir / "meta.json").write_text(json.dumps({"total": len(rows), "pageSize": page}))

    print(f"trustscore for {len(rows)} users -> trust.json / trust_top.json / {len(rows)//page + 1} chunks")
    for r in rows[:10]:
        print(f"  {r['trustRank']:>3}. {r['login']:<22} {r['score']:>4}  (vr {r['parts'][0]}, bacon {r['parts'][1]}, act {r['parts'][2]}, vouch +{r['parts'][3]}, den {r['parts'][4]})")


if __name__ == "__main__":
    main()
