# gitcooked-api worker

Backend for the dynamic bits of gitcooked: rank badges, index requests, GitHub
OAuth profile claiming, vouches. The static site works without it — these
endpoints just 404/fail gracefully until deployed.

## Endpoints

- `GET /badge/{login}.svg?scope=global|{country_slug}` — neon rank badge
- `GET /api/shield/{login}` — shields.io endpoint JSON
- `POST /api/index-request` `{login, location}` — queue a user for indexing (rate-limited 10/day/IP, deduped)
- `GET /api/index-requests` — pending queue (for the refresh pipeline)
- `GET /api/auth/login` → GitHub OAuth → `GET /api/auth/callback` → session cookie + redirect to profile
- `GET /api/me`, `PUT /api/profile` `{socials}` — claimed profile management
- `POST /api/vouch` `{vouchee, note}` / `DELETE /api/vouch/{login}` — vouches (ranked users only, max 20 outgoing)
- `GET /api/profile/{login}` — claimed status + socials + vouchedBy
- `GET /api/vouches/graph` — all vouch edges

## Badge embed

```md
[![gitcooked](https://api.gitcooked.dev/badge/YOURLOGIN.svg)](https://gitcooked.dev/u/YOURLOGIN)
[![gitcooked](https://api.gitcooked.dev/badge/YOURLOGIN.svg?scope=australia)](https://gitcooked.dev/australia)
```

## Deploy

```sh
cd workers/api
npm install -D wrangler

wrangler kv namespace create CACHE        # paste id into wrangler.jsonc
wrangler d1 create gitcooked              # paste id into wrangler.jsonc
wrangler d1 migrations apply gitcooked --remote

# GitHub OAuth app (https://github.com/settings/applications/new)
#   callback URL: https://api.gitcooked.dev/api/auth/callback
# put client id in wrangler.jsonc vars, then:
wrangler secret put GITHUB_CLIENT_SECRET
wrangler secret put SESSION_SECRET        # e.g. `openssl rand -hex 32`

wrangler deploy
```

Local dev: `wrangler dev` (uses local D1/KV; set `SITE_ORIGIN` to your astro
dev server in wrangler.jsonc vars for badge lookups).

Socials are auto-imported from the GitHub API on claim (`/users/{login}` +
`/users/{login}/social_accounts` — website, twitter, mastodon, bluesky,
linkedin); claimed users can edit via `PUT /api/profile`.
