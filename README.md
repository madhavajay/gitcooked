# gitcooked

Who's cooking on GitHub? Global + per-country rankings of the most active
committers, a follower network you can fly through, and clusters of cracked
open-source devs. A spiritual successor to [committers.top](https://committers.top).

```sh
./dev.sh            # fetch data if needed, convert, start dev server
./dev.sh --refresh  # re-pull latest upstream data first
```

## Layout

| Path | What |
|------|------|
| `data/locations/*.yml` | ranking data, one file per location (updated hourly by Action; git history = time series) |
| `collector/` | vendored Go CLI that queries GitHub GraphQL for rankings |
| `scripts/` | pipeline: convert, refresh stale, crawl followers, index repos, build network/clusters, mine history, fetch community files |
| `site/` | Astro static site (fully static — no backend required) |
| `workers/api/` | Cloudflare Worker: badges, OAuth profile claiming, vouches, index-request queue |
| `docs/gitcooked-json-spec.md` | community file spec (socials / vouch / ai_usage) |
| `TODO.md` | roadmap + deploy checklist |

## Long-running crawls

```sh
python3 scripts/crawl_followers.py --loop    # follower graph (resumable, Ctrl-C safe)
python3 scripts/crawl_followers.py --status  # progress
python3 scripts/index_repos.py --top 400     # repo co-contribution data
python3 scripts/build_network.py             # → site network view
python3 scripts/build_clusters.py            # → site clusters page
```
