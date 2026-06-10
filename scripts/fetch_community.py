#!/usr/bin/env python3
"""Fetch gitcooked.json community files from ranked users' profile repos.

Checks raw.githubusercontent.com/{login}/{login}/HEAD/gitcooked.json for the
top --limit ranked users plus any logins in data/community/optin.txt.
Aggregates into site/src/data/community.json:

  { "fetchedAt": iso,
    "checked": N, "found": M,
    "vouches": { "<vouchee>": [{"voucher": ..., "note": ...}] },
    "socials": { "<login>": {...} },
    "aiUsage": [ {login, provider, period, inputTokens, outputTokens} ] }

Vouches only count when the voucher is ranked and isn't the vouchee; max 20
outgoing per user (spec v0).
"""
import argparse
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "src" / "data"
OPTIN = ROOT / "data" / "community" / "optin.txt"
OUT = DATA / "community.json"


def fetch_one(login):
    url = f"https://raw.githubusercontent.com/{login}/{login}/HEAD/gitcooked.json"
    req = urllib.request.Request(url, headers={"User-Agent": "gitcooked-indexer"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status != 200:
                return login, None
            body = r.read(64 * 1024)
        return login, json.loads(body)
    except Exception:
        return login, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000, help="top N ranked users to check")
    args = ap.parse_args()

    glob = json.loads((DATA / "global.json").read_text())
    ranked = [u["login"] for u in glob["modes"]["commits"]]
    ranked_set = {r.lower() for r in ranked}

    targets = list(dict.fromkeys(ranked[: args.limit]))
    if OPTIN.exists():
        for line in OPTIN.read_text().splitlines():
            login = line.strip()
            if login and not login.startswith("#") and login not in targets:
                targets.append(login)

    vouches = {}
    socials = {}
    ai_usage = []
    found = 0

    with ThreadPoolExecutor(max_workers=16) as pool:
        for login, doc in pool.map(fetch_one, targets):
            if not isinstance(doc, dict):
                continue
            found += 1
            if isinstance(doc.get("socials"), dict):
                clean = {
                    k: v
                    for k, v in doc["socials"].items()
                    if isinstance(k, str) and isinstance(v, str) and v.startswith("http") and len(v) < 200
                }
                if clean:
                    socials[login] = clean
            entries = doc.get("vouch") or []
            if isinstance(entries, list) and login.lower() in ranked_set:
                for e in entries[:20]:
                    if isinstance(e, str):
                        e = {"login": e}
                    if not isinstance(e, dict):
                        continue
                    vouchee = str(e.get("login", "")).strip()
                    if not vouchee or vouchee.lower() == login.lower():
                        continue
                    vouches.setdefault(vouchee, []).append(
                        {"voucher": login, "note": str(e.get("note", ""))[:280]}
                    )
            usage = doc.get("ai_usage") or []
            if isinstance(usage, list):
                for u in usage[:24]:
                    if not isinstance(u, dict):
                        continue
                    try:
                        ai_usage.append(
                            {
                                "login": login,
                                "provider": str(u.get("provider", "?"))[:30],
                                "period": str(u.get("period", "?"))[:7],
                                "inputTokens": int(u.get("input_tokens", 0)),
                                "outputTokens": int(u.get("output_tokens", 0)),
                            }
                        )
                    except (TypeError, ValueError):
                        continue

    OUT.write_text(
        json.dumps(
            {
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
                "checked": len(targets),
                "found": found,
                "vouches": vouches,
                "socials": socials,
                "aiUsage": ai_usage,
            },
            ensure_ascii=False,
        )
    )
    print(f"checked {len(targets)}, found {found} gitcooked.json files")
    print(f"vouches for {len(vouches)} users, ai usage rows: {len(ai_usage)} -> {OUT}")


if __name__ == "__main__":
    main()
