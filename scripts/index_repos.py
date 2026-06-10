#!/usr/bin/env python3
"""Index popular repos per ranked user (owned top-starred + contributed-to).

Output: data/repos/repos.jsonl — one line per user:
  {login, owned: [{repo, stars, lang}], contributed: [{repo, stars, lang}], fetchedAt}

Resumable like the follower crawler. Shares the GraphQL rate budget.
Usage: python3 scripts/index_repos.py [--top N]
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "src" / "data"
OUT = ROOT / "data" / "repos" / "repos.jsonl"
API = "https://api.github.com/graphql"
BATCH = 10

REPO_FIELDS = "{ nameWithOwner stargazerCount primaryLanguage { name } }"


def token():
    t = os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


TOKEN = token()


def gql(query):
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = json.load(r)
            rl = (body.get("data") or {}).get("rateLimit") or {}
            if rl.get("remaining", 9999) < 100:
                print(f"  rate limit low, sleeping 600s", flush=True)
                time.sleep(600)
            if "data" in body:
                return body
        except Exception as e:
            time.sleep(2**attempt * 5)
    return {}


def query_for(logins):
    parts = ["rateLimit { remaining resetAt }"]
    for i, login in enumerate(logins):
        l = json.dumps(login)
        parts.append(
            f"u{i}: user(login: {l}) {{ login "
            f"repositories(first: 15, orderBy: {{field: STARGAZERS, direction: DESC}}, ownerAffiliations: OWNER, isFork: false) {{ nodes {REPO_FIELDS} }} "
            f"repositoriesContributedTo(first: 15, contributionTypes: [COMMIT, PULL_REQUEST], includeUserRepositories: false) {{ nodes {REPO_FIELDS} }} }}"
        )
    return "query { " + " ".join(parts) + " }"


def clean(nodes):
    out = []
    for n in nodes or []:
        if not n:
            continue
        out.append(
            {
                "repo": n["nameWithOwner"],
                "stars": n["stargazerCount"],
                "lang": (n.get("primaryLanguage") or {}).get("name"),
            }
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=400)
    args = ap.parse_args()

    glob = json.loads((DATA / "global.json").read_text())
    targets = [u["login"] for u in glob["modes"]["commits"][: args.top]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        for line in OUT.open():
            try:
                done.add(json.loads(line)["login"])
            except Exception:
                pass
    todo = [t for t in targets if t not in done]
    print(f"indexing repos for {len(todo)} users ({len(done)} done)", flush=True)

    with OUT.open("a") as out:
        for i in range(0, len(todo), BATCH):
            batch = todo[i : i + BATCH]
            data = (gql(query_for(batch)).get("data")) or {}
            for j, login in enumerate(batch):
                u = data.get(f"u{j}")
                rec = {"login": login, "fetchedAt": datetime.now(timezone.utc).isoformat()}
                if u:
                    rec["owned"] = clean(u["repositories"]["nodes"])
                    rec["contributed"] = clean(u["repositoriesContributedTo"]["nodes"])
                else:
                    rec["error"] = "not_found"
                out.write(json.dumps(rec) + "\n")
            out.flush()
            if (i // BATCH) % 5 == 0:
                print(f"  {min(i + BATCH, len(todo))}/{len(todo)}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
