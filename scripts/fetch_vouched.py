#!/usr/bin/env python3
"""Find and ingest mitchellh/vouch VOUCHED.td files across GitHub.

Discovery: GitHub code search API, q=filename:VOUCHED.td (10 req/min limit,
max ~1000 results). Each file is a project vouching for contributors:
one handle per line, '#' comments, optional 'platform:user' prefix,
'-' prefix = denounce, optional details after a space.

Cache: data/community/vouched.jsonl (one line per repo, resumable)
The community indexer (fetch_community.py) merges these as repo-vouches.

Usage: python3 scripts/fetch_vouched.py [--max-age-days 7]
"""
import argparse
import base64
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "community" / "vouched.jsonl"


def token():
    t = os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


HEADERS = {
    "Authorization": f"bearer {token()}",
    "User-Agent": "gitcooked",
    "Accept": "application/vnd.github+json",
}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print("  rate limited, sleeping 70s", flush=True)
            time.sleep(70)
            return get(url)
        return None
    except Exception:
        return None


def search_files():
    items = []
    for page in range(1, 11):
        q = urllib.parse.quote("filename:VOUCHED.td")
        body = get(f"https://api.github.com/search/code?q={q}&per_page=100&page={page}")
        if not body or not body.get("items"):
            break
        items.extend(body["items"])
        if len(items) >= body.get("total_count", 0):
            break
        time.sleep(7)  # code search: 10 req/min
    # keep canonical locations only (root or .github), skip templates/vendored copies
    out = []
    for it in items:
        path = it["path"]
        if path in ("VOUCHED.td", ".github/VOUCHED.td"):
            out.append((it["repository"]["full_name"], path))
    return out


import re

LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def parse_vouched(text):
    vouched, denounced = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        entry = tokens[0]
        neg = False
        # bare +/- markers with the handle as the next token ("+ user" / "- user")
        if entry in ("+", "-", "*") and len(tokens) > 1:
            neg = entry == "-"
            entry = tokens[1]
            note = " ".join(tokens[2:])[:140]
        else:
            note = " ".join(tokens[1:])[:140]
            if entry.startswith("-"):
                neg = True
                entry = entry[1:]
            elif entry.startswith("+"):
                entry = entry[1:]
        entry = entry.lstrip("@")
        if ":" in entry:
            platform, _, handle = entry.partition(":")
            if platform.lower() != "github":
                continue
            entry = handle
        if not LOGIN_RE.match(entry):
            continue
        (denounced if neg else vouched).append({"login": entry, "note": note})
    return vouched, denounced


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=int, default=7)
    args = ap.parse_args()

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = {}
    if CACHE.exists():
        for line in CACHE.open():
            try:
                rec = json.loads(line)
                cache[rec["repo"]] = rec
            except Exception:
                pass
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.max_age_days)

    files = search_files()
    print(f"found {len(files)} VOUCHED.td files via code search", flush=True)

    fresh_count = 0
    with CACHE.open("a") as out:
        for repo, path in files:
            prev = cache.get(repo)
            if prev and datetime.fromisoformat(prev["fetchedAt"]) >= cutoff:
                continue
            body = get(f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(path)}")
            if not body or body.get("encoding") != "base64":
                continue
            try:
                text = base64.b64decode(body["content"]).decode("utf-8", "replace")
            except Exception:
                continue
            vouched, denounced = parse_vouched(text)
            rec = {
                "repo": repo,
                "path": path,
                "vouched": vouched,
                "denounced": denounced,
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
            }
            cache[repo] = rec
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fresh_count += 1

    total_vouches = sum(len(r["vouched"]) for r in cache.values())
    print(f"{fresh_count} files fetched this run; cache: {len(cache)} repos, {total_vouches} vouches")

    # site data: repo-level view for the /vouched page
    site_out = ROOT / "site" / "src" / "data" / "vouched_repos.json"
    repos = sorted(cache.values(), key=lambda r: -len(r["vouched"]))
    site_out.write_text(
        json.dumps(
            {
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "repos": [
                    {
                        "repo": r["repo"],
                        "path": r["path"],
                        "vouched": r["vouched"],
                        "denounced": r["denounced"],
                        "fetchedAt": r["fetchedAt"],
                    }
                    for r in repos
                ],
            },
            ensure_ascii=False,
        )
    )
    print(f"{len(repos)} repos -> {site_out}")


if __name__ == "__main__":
    main()
