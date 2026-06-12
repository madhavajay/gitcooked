# gitcooked — TODO

**The pitch: a trust graph for developers.** Who's actually connected to whom,
and who do the people who ship actually trust — derived from the follow
network (bacon index), seeded by activity rankings, sharpened by explicit
vouches & denouncements. Activity leaderboards and tokenmaxxing orbit around
that core.

**Run it:** `./dev.sh` · crawler: `python3 scripts/crawl_followers.py --loop` · status: `--status`

---

## 1 · PRIMARY — The Network & TrustScore

### TrustScore v1 (define + ship)
- [x] Spec the formula. Proposed blend, normalized 0–1000:
  - **network attention** — VouchRank (PageRank over follows, rank-weighted teleport) — *built*
  - **bacon index** — proximity to trust anchors: harmonic-mean shortest-path distance to the top-50 VouchRank devs (closer to the people everyone trusts = higher; unreachable = 0)
  - **activity** — contribution-rank percentile (the committers.top signal)
  - **modifiers** — explicit vouches add (capped, weighted by voucher trust & repo standing), denouncements subtract hard
- [x] `scripts/build_trustscore.py` — compute per-user: components + final score + per-mille breakdown (reuse the vouchrank depth-decomposition pattern)
- [x] `/trust` page: TR 0–10 pips (toolbar-PageRank style), score card w/ component bar, trust web (top supporters + trust-band clusters), lookup + submit-to-be-calculated, top board, GET ?u=
- [x] TrustScore on profile pages + in the network stats panel
- [ ] Badge scope: `?scope=trust` on the SVG badge worker
- [ ] OG cards for trust scores (the shareable artifact — this is the viral loop)

### Bacon index
- [x] Pick anchors: top-50 VouchRank, documented on /trust (revisit if anchors look gamed)
- [x] BFS from anchor set over the crawled graph → per-user distance vector; harmonic mean → bacon index
- [ ] Show on profiles: "2 hops from the core" + the actual path (reuse path finder)
- [ ] Recompute as part of the nightly network build

### Vouch / denounce augmentation
- [x] VOUCHED.td indexer (code search → 196 repos, 6.3k vouches, 46 denounced) + /vouched + /denounced pages + profile chips
- [x] gitcooked.json peer vouches (spec'd; adoption pending)
- [ ] Weight repo vouches by repo standing (stars / owner trust) — the terminal.shop mass-vouch cluster shows why equal weighting fails
- [ ] Feed weighted vouches/denouncements into TrustScore modifiers
- [ ] Vouch-edge overlay on the network view (distinct color vs follow edges)

### Network (the experience)
- [x] Crawler: resumable, sharded store committed in-repo, parallel, --loop w/ frontier expansion; nightly Action
- [x] 3D network: ego views, all-shortest-paths Kevin Bacon mode w/ fade+reorient, geo layout over real continents, zoom-loaded avatar faces w/ flag badges, country/rank/follower/repo filters, hide-unlinked + right-click pruning, stats panel
- [x] Flat follower web on profiles (phyllotaxis, score-scaled, score labels)
- [ ] Finish the frontier crawl (~10k ranked users remaining) — then `--max-age-days 30` keep-fresh mode
- [ ] Crawl beyond ranked users? (2nd-degree non-ranked devs with high follower counts — expands the trust graph's reach; bound it)
- [ ] Network perf pass at 8k+ nodes (LOD for links, worker-thread layout?)
- [ ] "people you should know" — nearby high-trust devs you don't follow yet

## 2 · SECONDARY — Activity Rankings (classic committers.top)

- [x] Full pipeline: 151 locations, hourly refresh Action, merged 38k global ranking, country pages, /u rank cards, am-i-ranked lookup, badges, OG cards, world map + charts home
- [ ] Demote in IA: home page should lead with the network/trust story, activity tables one click away (keep the map — it's the hook)
- [ ] Suspected-bot filter (contribution farming: 250 → 150k/6mo jumps; movers chart already filters >300k)
- [ ] Index-request queue → preset include extension flow (worker endpoint exists)
- [ ] Keep: hourly data Action, trend mining, movers chart

## 3 · THIRD — Tokenmaxxing

- [x] gitcooked-tokens-v1 monthly ledger spec (immutable past months, ~50B/day) + codexbar converter (now w/ per-harness breakdown) + indexer ingestion + /tokens page w/ $ burn
- [ ] Surface harness breakdown on /tokens (claude-code vs codex-cli vs pi…) — leaderboard per harness, "main character" chips
- [ ] Publish madhavajay's own ledgers as the reference implementation (dogfood)
- [ ] Burn-over-time chart (daily series are already in the ledgers)
- [ ] Get codexbar to ship the exporter natively (PR or ask steipete) — adoption depends on one-command setup

## Deploy checklist (owner actions)

1. Push to GitHub (+ `index-request` label) — hourly data + nightly network Actions start
2. Cloudflare Pages: build `cd site && npm run build`, output `site/dist`
3. `workers/api`: KV + D1 + GitHub OAuth app + 2 secrets (workers/api/README.md), route `api.gitcooked.dev`
4. Keep `crawl_followers.py --loop` running somewhere until the frontier is done

### Open issue from first run
- [ ] 0x3EF8 (20M farmed contributions) lands at trust #1 via the activity component — bot filter or activity cap needed before launch; vouch/denounce can't catch farmers nobody bothers to denounce

## Known constraints

- GitHub search follower-floor per country; free-text location matching; 5k GraphQL pts/hr bounds crawl+refresh speed
- Code search (VOUCHED.td discovery): 10 req/min, 1k result cap — partition queries if adoption explodes
- Contribution counts are gameable → TrustScore is the answer, don't over-invest in activity-side anti-cheat
