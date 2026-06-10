# gitcooked — TODO

A better committers.top. Neon, interactive, global + country rankings, dev-cluster analysis.

**Inspiration:** https://areyougoingexponential.rhys.dev/madhavajay (neon/dark, animated, personal)
**Upstream:** https://committers.top/ (cloned at `./committers.top/`)
**Run it:** `./dev.sh` (use `--refresh` to re-pull upstream data)

---

## Phase 0 — Data Foundation ✅

- [x] Vendor the Go collector into `collector/` (builds clean, stdlib-only)
- [x] Seed data from upstream `gh-pages` → `data/locations/*.yml` (151 locations, tracked in git)
- [x] Convert YAML → JSON (`scripts/convert.py` → per-location, index, merged global, paginated chunks, search index)
- [x] Merged global ranking: union of every country file **plus** the worldwide query (38,119 deduped users vs upstream's ~6k worldwide) — all country data is in global by default
- [x] Port the update Action (`.github/workflows/update_data.yml`: hourly, refreshes ≤3 stale locations via `scripts/refresh_stale.py`, commits to repo)
- [x] Snapshot retention: data lives in-repo, git history = time series (plus 24 months of history mined from upstream)

## Phase 1 — The Site ✅

- [x] Astro static site in `site/` (1,157 pages, ~12s build), neon dark theme
- [x] Home: world map w/ clusters (MapLibre, bubble per country, click → country page)
- [x] Home: stat charts (ECharts — devs by region, biggest countries, "going exponential" top movers from 24mo history)
- [x] Home: global top 10 + country card grid w/ avatars
- [x] Ranking pages (global + 150 countries): detail table first, top 10 rows neon-highlighted, mode switch (commits / contributions / incl. private), show-more pagination, avatars, username filter
- [x] `/u/{login}` rank cards for top 1000 (global + local ranks, orgs, network link) + `/u` instant lookup for all 38k
- [x] "Not ranked? Request indexing" → issue template + Worker queue endpoint
- [x] OG share cards for every country + top 1000 users (build-time generated)
- [x] Mobile responsive, count-up animations, lazy-loaded avatars
- [ ] Deploy to Cloudflare Pages (owner: create project, connect repo, build cmd `cd site && npm run build`)

## Phase 1.5 — Indexing Requests ✅ (code)

- [x] Username lookup against full search index (client-side)
- [x] `POST /api/index-request` Worker endpoint (KV rate-limit 10/day/IP, D1 dedupe) + GitHub issue template fallback
- [ ] Pipeline step: review queue (`GET /api/index-requests`) → extend preset includes

## Phase 2 — Profiles, Auth, Vouching, Badges ✅ (code; needs deploy)

- [x] `workers/api` — single Worker: OAuth, profiles, vouches, badges, index queue (see `workers/api/README.md`)
- [x] GitHub OAuth claim flow (signed session cookies, D1 user records)
- [x] Socials: **no scraping needed** — GitHub API has it all (`/users/{login}` + `/users/{login}/social_accounts`: website, twitter, mastodon, bluesky, linkedin); auto-imported on claim, editable via `PUT /api/profile`
- [x] Vouching, mitchellh/vouch model: vouches are *received from others* — either via other users' `gitcooked.json` files (decentralized, aggregated by `scripts/fetch_community.py`) or via the API for claimed users. Caps: ranked users only, 20 outgoing, no self-vouch
- [x] `gitcooked.json` community file spec (`docs/gitcooked-json-spec.md`: socials + vouch + ai_usage)
- [x] Vouch display on profiles (static from community data + live from API)
- [x] Token maxxing board `/tokens` — self-reported AI usage, fun-only, never mixed into real rankings
- [x] Rank badges: `GET /badge/{login}.svg?scope=global|{country}` neon SVG + shields.io endpoint; embed snippets on every user page
- [ ] Deploy `workers/api` (owner: `wrangler kv namespace create` + `d1 create` + GitHub OAuth app + 2 secrets — steps in workers/api/README.md)
- [ ] Vouch-edge overlay on the network view (needs deployed API + real vouches)

## Phase 3 — Network & Clusters

- [x] Follower crawler (`scripts/crawl_followers.py`): resumable JSONL store, lock file, rate-limit aware, parallel pagination, `--loop` mode (seeds → frontier expansion → stale refresh) — **runs on any machine, safe to Ctrl-C**
- [x] Seed strategy: global top 1000 + top 25 per country (3,795 seeds), then followers-of-followers frontier
- [x] Simulated graph generator for UI testing (`scripts/simulate_graph.py` — flagged `simulated`, never mixes with real data, UI shows watermark)
- [x] `/network` — 3D force graph (three.js): ego view per user, click-to-expand browsing, Kevin Bacon path finder (BFS degrees-of-separation), geo layout toggle, region colors, mutual-follow edges
- [x] Repo indexer (`scripts/index_repos.py`): owned top-starred + contributed-to for top 400
- [x] Co-contribution graph → label-propagation communities → `/clusters` page (auto-labeled by language, member avatars, shared repos)
- [x] Trend data: 24 months mined from upstream git history (`scripts/extract_history.py` → movers + per-user series)
- [ ] Crawls running: follower graph (~3.8k seeds then frontier) + repo index (top 400) — rerun `build_network.py` / `build_clusters.py` as data lands; wire into a nightly Action
- [ ] Suspected-bot filter for rankings (history shows contribution farming, e.g. jumps 250 → 150k/6mo; movers chart already filters >300k)
- [ ] Followers count as an extra profile metric / ranking dimension (already in crawl data)
- [ ] Cluster naming v2: repo topics, org affinity; cluster detail pages

## Deploy checklist (owner actions)

1. Create GitHub repo, push, add `index-request` label — Actions start refreshing data hourly
2. Cloudflare Pages: connect repo, build `cd site && npm run build`, output `site/dist`
3. `workers/api`: follow README (KV + D1 + OAuth app + secrets), route `api.gitcooked.dev`
4. Leave `python3 scripts/crawl_followers.py --loop` running to grow the network

## Known constraints (inherited from upstream)

- GitHub search can't sort by contributions → follower floor per country; low-follower devs invisible (mitigated by index requests)
- Location matching is free-text city strings (`collector/presets.go`)
- API rate limits bound refresh speed (3 locations/hour) and crawl speed (~5k GraphQL points/hr)
- Contribution counts are gameable; see suspected-bot filter above
