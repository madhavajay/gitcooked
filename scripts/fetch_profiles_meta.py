#!/usr/bin/env python3
"""Fetch public profile metadata (email, socials) for top ranked users.

Uses the GitHub REST API: /users/{login} (email, blog, twitter, company,
location) + /users/{login}/social_accounts (mastodon, bluesky, linkedin...).
No scraping — this is all public API data users put on their profiles.

Cache: data/profiles/meta.jsonl (committed; resumable, --max-age-days to refresh)
Output: site/src/data/profiles_meta.json  { login: {email, socials{...}} }
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "src" / "data"
CACHE = ROOT / "data" / "profiles" / "meta.jsonl"
OUT = DATA / "profiles_meta.json"


def token():
    t = os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


TOKEN = token()
HEADERS = {
    "Authorization": f"bearer {TOKEN}",
    "User-Agent": "gitcooked",
    "Accept": "application/vnd.github+json",
}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            remaining = int(r.headers.get("x-ratelimit-remaining", 9999))
            if remaining < 50:
                reset = int(r.headers.get("x-ratelimit-reset", time.time() + 600))
                wait = max(0, reset - time.time()) + 5
                print(f"  REST rate limit low, sleeping {int(wait)}s", flush=True)
                time.sleep(wait)
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 403:
            time.sleep(120)
        return None
    except Exception:
        return None


def fetch_one(login):
    user = get(f"https://api.github.com/users/{login}")
    accounts = get(f"https://api.github.com/users/{login}/social_accounts") or []
    socials = {}
    if user:
        if user.get("blog"):
            blog = user["blog"]
            socials["website"] = blog if blog.startswith("http") else f"https://{blog}"
        if user.get("twitter_username"):
            socials["twitter"] = f"https://twitter.com/{user['twitter_username']}"
    for a in accounts:
        if isinstance(a, dict) and a.get("url"):
            socials[a.get("provider", "link")] = a["url"]
    return {
        "login": login,
        "email": (user or {}).get("email"),
        "socials": socials,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=1000)
    ap.add_argument("--max-age-days", type=int, default=0)
    args = ap.parse_args()

    glob = json.loads((DATA / "global.json").read_text())
    targets = [u["login"] for u in glob["modes"]["commits"][: args.top]]

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = {}
    if CACHE.exists():
        for line in CACHE.open():
            try:
                rec = json.loads(line)
                cache[rec["login"]] = rec
            except Exception:
                pass

    fresh = set(cache)
    if args.max_age_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.max_age_days)
        fresh = {l for l, r in cache.items() if datetime.fromisoformat(r["fetchedAt"]) >= cutoff}

    todo = [t for t in targets if t not in fresh]
    print(f"fetching profile meta for {len(todo)} users ({len(cache)} cached)", flush=True)

    with CACHE.open("a") as out, ThreadPoolExecutor(max_workers=8) as pool:
        done = 0
        for rec in pool.map(fetch_one, todo):
            cache[rec["login"]] = rec
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done += 1
            if done % 100 == 0:
                out.flush()
                print(f"  {done}/{len(todo)}", flush=True)

    merged = {
        l: {"email": r.get("email"), "socials": r.get("socials") or {}}
        for l, r in cache.items()
        if r.get("email") or r.get("socials")
    }
    OUT.write_text(json.dumps(merged, ensure_ascii=False))
    print(f"{len(merged)} users with public email/socials -> {OUT}")


if __name__ == "__main__":
    main()
