#!/usr/bin/env python3
"""Convert upstream committers.top YAML data into JSON for the static site.

Outputs into site/src/data/:
  locations/{slug}.json  - per-location rankings (3 modes + orgs + meta)
  index.json             - list of all locations w/ summary stats
  global.json            - merged ranking across all locations, deduped by login
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "locations"
OUT = ROOT / "site" / "src" / "data"

MODES = {
    "commits": "users",
    "contributions": "users_public_contributions",
    "all": "private_users",
}
ORG_MODES = {
    "commits": "organizations",
    "contributions": "public_contributions_organizations",
    "all": "private_organizations",
}


def clean_user(u):
    return {
        "rank": u.get("rank"),
        "login": u.get("login"),
        "name": u.get("name") or "",
        "avatarUrl": u.get("avatarUrl") or "",
        "contributions": u.get("contributions") or 0,
        "company": u.get("company") or "",
        "organizations": [o for o in (u.get("organizations") or "").split(",") if o],
    }


def main():
    if not SRC.is_dir():
        sys.exit(f"missing {SRC} — run scripts/fetch_upstream.sh first")
    if not OUT.parent.parent.is_dir():
        sys.exit("missing site/ — scaffold the Astro site first")
    (OUT / "locations").mkdir(parents=True, exist_ok=True)

    index = []
    merged = {}  # mode -> login -> user record

    for f in sorted(SRC.glob("*.yml")):
        slug = f.stem
        d = yaml.safe_load(f.read_text())
        generated = d.get("generated")
        if isinstance(generated, datetime):
            generated = generated.isoformat()

        loc = {
            "slug": slug,
            "title": d.get("title") or slug.replace("_", " ").title(),
            "generated": generated,
            "minFollowers": d.get("min_followers_required"),
            "totalUserCount": d.get("total_user_count"),
            "modes": {},
            "orgs": {},
        }
        for mode, key in MODES.items():
            users = [clean_user(u) for u in (d.get(key) or [])]
            loc["modes"][mode] = users
            bucket = merged.setdefault(mode, {})
            for u in users:
                prev = bucket.get(u["login"])
                if prev is None:
                    rec = dict(u)
                    # worldwide-only users get no location tag; country files add theirs
                    rec["locations"] = [] if slug == "worldwide" else [slug]
                    bucket[u["login"]] = rec
                else:
                    if slug != "worldwide" and slug not in prev["locations"]:
                        prev["locations"].append(slug)
                    if u["contributions"] > prev["contributions"]:
                        prev.update(
                            {k: u[k] for k in ("name", "avatarUrl", "contributions", "company", "organizations")}
                        )
        for mode, key in ORG_MODES.items():
            loc["orgs"][mode] = d.get(key) or []

        (OUT / "locations" / f"{slug}.json").write_text(json.dumps(loc, ensure_ascii=False))
        top = loc["modes"]["commits"][:3]
        index.append(
            {
                "slug": slug,
                "title": loc["title"],
                "generated": generated,
                "totalUserCount": loc["totalUserCount"],
                "minFollowers": loc["minFollowers"],
                "rankedUsers": len(loc["modes"]["commits"]),
                "top": [{"login": u["login"], "avatarUrl": u["avatarUrl"]} for u in top],
            }
        )

    glob = {"generated": max((i["generated"] or "" for i in index), default=None), "modes": {}}
    for mode, bucket in merged.items():
        ranked = sorted(bucket.values(), key=lambda u: -u["contributions"])
        for i, u in enumerate(ranked):
            u["rank"] = i + 1
        glob["modes"][mode] = ranked

    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False))
    (OUT / "global.json").write_text(json.dumps(glob, ensure_ascii=False))

    pub = ROOT / "site" / "public" / "data"
    page_size = 500
    for mode, ranked in glob["modes"].items():
        d = pub / "global" / mode
        d.mkdir(parents=True, exist_ok=True)
        for i in range(0, len(ranked), page_size):
            (d / f"page-{i // page_size}.json").write_text(
                json.dumps(ranked[i : i + page_size], ensure_ascii=False)
            )
        (d / "meta.json").write_text(json.dumps({"total": len(ranked), "pageSize": page_size}))
    search = [[u["login"], u["rank"], u["contributions"]] for u in glob["modes"].get("commits", [])]
    (pub / "search.json").write_text(json.dumps(search, ensure_ascii=False))

    n = len(glob["modes"].get("commits", []))
    print(f"{len(index)} locations -> {OUT}")
    print(f"global merged ranking: {n} unique users (commits mode)")


if __name__ == "__main__":
    main()
