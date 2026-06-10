#!/usr/bin/env python3
"""Resilient, resumable GitHub follower-graph crawler.

The store (data/graph/nodes.jsonl) is the cache: one JSON line per crawled
user; re-runs skip anything already crawled (unless older than --max-age-days).
Safe to stop with Ctrl-C at any time — lines are flushed as they complete.
A lock file prevents two crawlers from running at once.

Modes:
  (default)        crawl the seed set: global top 1000 + top 25 per country
  --expand         crawl the frontier: ranked users seen as followers/following
                   of already-crawled users but not yet crawled themselves
  --status         print store stats and exit
  --loop           keep running: seeds, then expand, then refresh stale; sleep
                   between passes. Good for leaving in a terminal overnight.

Options:
  --limit N          stop after N new users this pass
  --max-age-days D   re-crawl entries older than D days (default: never)

Token: `gh auth token` or GITHUB_TOKEN env. Rate-limit aware (sleeps near
exhaustion, retries with backoff on errors).

Output record:
  {login, followers: [...], following: [...], followerCount, followingCount,
   truncated, fetchedAt}  (or {login, error, fetchedAt} for dead accounts)
"""
import argparse
import atexit
import json
import os
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "src" / "data"
OUT_DIR = ROOT / "data" / "graph"
NODES = OUT_DIR / "nodes.jsonl"
LOCK = OUT_DIR / "crawler.lock"

GLOBAL_TOP = 1000
COUNTRY_TOP = 25
MAX_PAGES = 10  # x100 per connection per user
BATCH = 10  # users per first-page query

API = "https://api.github.com/graphql"
CONN = "{ totalCount pageInfo { hasNextPage endCursor } nodes { login } }"


def token():
    t = os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


def acquire_lock():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip())
            os.kill(pid, 0)
            sys.exit(f"another crawler is running (pid {pid}); remove {LOCK} if that's wrong")
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # stale lock
    LOCK.write_text(str(os.getpid()))
    atexit.register(lambda: LOCK.unlink(missing_ok=True))


def now():
    return datetime.now(timezone.utc)


class Crawler:
    def __init__(self):
        self.token = token()

    def gql(self, query):
        req = urllib.request.Request(
            API,
            data=json.dumps({"query": query}).encode(),
            headers={"Authorization": f"bearer {self.token}", "Content-Type": "application/json"},
        )
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = json.load(r)
                if "data" in body and body["data"]:
                    rl = body["data"].get("rateLimit") or {}
                    if rl.get("remaining", 9999) < 100:
                        reset = datetime.fromisoformat(rl["resetAt"].replace("Z", "+00:00"))
                        wait = max(0, (reset - now()).total_seconds()) + 10
                        print(f"  rate limit low ({rl['remaining']}), sleeping {int(wait)}s", flush=True)
                        time.sleep(wait)
                    return body
                errs = body.get("errors", [])
                if any(e.get("type") == "RATE_LIMITED" for e in errs):
                    print("  rate limited, sleeping 300s", flush=True)
                    time.sleep(300)
                    continue
                return body
            except KeyboardInterrupt:
                raise
            except Exception as e:
                wait = 2**attempt * 5
                print(f"  request error ({e}), retry in {wait}s", flush=True)
                time.sleep(wait)
        return {}

    def first_page_query(self, logins):
        parts = ["rateLimit { remaining resetAt }"]
        for i, login in enumerate(logins):
            l = json.dumps(login)
            parts.append(
                f"u{i}: user(login: {l}) {{ login "
                f"followers(first: 100) {CONN} following(first: 100) {CONN} }}"
            )
        return "query { " + " ".join(parts) + " }"

    def paginate(self, login, conn, cursor):
        out = []
        pages = 1
        while cursor and pages < MAX_PAGES:
            l = json.dumps(login)
            c = json.dumps(cursor)
            q = (
                f"query {{ rateLimit {{ remaining resetAt }} user(login: {l}) "
                f"{{ {conn}(first: 100, after: {c}) {CONN} }} }}"
            )
            body = self.gql(q)
            u = (body.get("data") or {}).get("user")
            if not u:
                break
            block = u[conn]
            out.extend(n["login"] for n in block["nodes"] if n)
            cursor = block["pageInfo"]["endCursor"] if block["pageInfo"]["hasNextPage"] else None
            pages += 1
        return out, bool(cursor)

    def crawl(self, todo, limit=0, workers=8):
        if limit:
            todo = todo[:limit]
        if not todo:
            print("nothing to crawl", flush=True)
            return 0
        crawled = 0
        pool = ThreadPoolExecutor(max_workers=workers)
        with NODES.open("a") as out:
            for i in range(0, len(todo), BATCH):
                batch = todo[i : i + BATCH]
                body = self.gql(self.first_page_query(batch))
                data = body.get("data") or {}
                recs, jobs = {}, []
                for j, login in enumerate(batch):
                    u = data.get(f"u{j}")
                    if not u:
                        recs[login] = {"login": login, "error": "not_found", "fetchedAt": now().isoformat()}
                        continue
                    rec = {"login": u["login"], "fetchedAt": now().isoformat(), "truncated": False}
                    for conn in ("followers", "following"):
                        block = u[conn]
                        rec[conn] = [n["login"] for n in block["nodes"] if n]
                        if block["pageInfo"]["hasNextPage"]:
                            jobs.append((login, conn, block["pageInfo"]["endCursor"]))
                    rec["followerCount"] = u["followers"]["totalCount"]
                    rec["followingCount"] = u["following"]["totalCount"]
                    recs[login] = rec
                # paginate truncated connections concurrently across users
                futures = {pool.submit(self.paginate, lg, cn, cur): (lg, cn) for lg, cn, cur in jobs}
                for fut, (lg, cn) in futures.items():
                    more, t = fut.result()
                    recs[lg][cn].extend(more)
                    recs[lg]["truncated"] = recs[lg]["truncated"] or t
                for login in batch:
                    if login in recs:
                        out.write(json.dumps(recs[login]) + "\n")
                        crawled += 1
                out.flush()
                if (i // BATCH) % 10 == 0:
                    print(f"  {min(i + BATCH, len(todo))}/{len(todo)} crawled", flush=True)
        pool.shutdown(wait=False)
        print(f"pass done: {crawled} new", flush=True)
        return crawled


def load_store():
    """latest record per login"""
    store = {}
    if NODES.exists():
        for line in NODES.open():
            try:
                rec = json.loads(line)
                store[rec["login"]] = rec
            except Exception:
                pass
    return store


def ranked_logins():
    glob = json.loads((DATA / "global.json").read_text())
    return [u["login"] for u in glob["modes"]["commits"]]


def seed_logins():
    glob = json.loads((DATA / "global.json").read_text())
    index = json.loads((DATA / "index.json").read_text())
    s, seen = [], set()
    for u in glob["modes"]["commits"][:GLOBAL_TOP]:
        if u["login"] not in seen:
            seen.add(u["login"])
            s.append(u["login"])
    for loc in index:
        if loc["slug"] == "worldwide":
            continue
        locdata = json.loads((DATA / "locations" / f"{loc['slug']}.json").read_text())
        for u in locdata["modes"]["commits"][:COUNTRY_TOP]:
            if u["login"] not in seen:
                seen.add(u["login"])
                s.append(u["login"])
    return s


def fresh(store, max_age_days):
    if not max_age_days:
        return set(store)
    cutoff = now() - timedelta(days=max_age_days)
    out = set()
    for login, rec in store.items():
        try:
            if datetime.fromisoformat(rec["fetchedAt"]) >= cutoff:
                out.add(login)
        except Exception:
            pass
    return out


def frontier(store):
    """ranked users referenced by crawled users but not yet crawled"""
    ranked = set(ranked_logins())
    seen_edges = set()
    for rec in store.values():
        for k in ("followers", "following"):
            seen_edges.update(rec.get(k) or [])
    return sorted((seen_edges & ranked) - set(store))


def status(store):
    ok = [r for r in store.values() if "error" not in r]
    errs = len(store) - len(ok)
    edges = sum(len(r.get("followers") or []) + len(r.get("following") or []) for r in ok)
    trunc = sum(1 for r in ok if r.get("truncated"))
    dates = sorted(r["fetchedAt"] for r in store.values() if r.get("fetchedAt"))
    print(f"store: {NODES}")
    print(f"crawled: {len(ok)} users ({errs} errors, {trunc} truncated)")
    print(f"edges stored: {edges:,}")
    if dates:
        print(f"oldest: {dates[0][:19]}  newest: {dates[-1][:19]}")
    seeds_left = [s for s in seed_logins() if s not in store]
    print(f"seeds remaining: {len(seeds_left)}")
    print(f"frontier (ranked, uncrawled): {len(frontier(store))}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--expand", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--max-age-days", type=int, default=0)
    ap.add_argument("--sleep", type=int, default=600, help="seconds between --loop passes")
    args = ap.parse_args()

    store = load_store()
    if args.status:
        status(store)
        return

    acquire_lock()
    c = Crawler()

    def one_pass():
        store = load_store()
        done = fresh(store, args.max_age_days)
        todo = [s for s in seed_logins() if s not in done]
        if todo:
            print(f"seeds: {len(todo)} to crawl", flush=True)
            return c.crawl(todo, args.limit)
        if args.expand or args.loop:
            f = [x for x in frontier(store) if x not in done]
            print(f"frontier: {len(f)} ranked users to expand into", flush=True)
            return c.crawl(f, args.limit or 2000)
        print("seeds complete. use --expand for followers-of-followers.", flush=True)
        return 0

    if args.loop:
        while True:
            try:
                n = one_pass()
            except KeyboardInterrupt:
                print("\ninterrupted — progress saved", flush=True)
                return
            if n == 0:
                print(f"nothing new; sleeping {args.sleep}s", flush=True)
                time.sleep(args.sleep)
    else:
        try:
            one_pass()
        except KeyboardInterrupt:
            print("\ninterrupted — progress saved", flush=True)


if __name__ == "__main__":
    main()
