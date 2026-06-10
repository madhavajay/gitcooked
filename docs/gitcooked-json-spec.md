# gitcooked.json — community file spec v0

Put a `gitcooked.json` at the root of your GitHub profile repo
(`github.com/YOU/YOU`). gitcooked indexes these files for ranked users.
Everything is optional. You can never write facts about yourself that others
must assert (vouches you *receive* only ever come from other people's files).

```json
{
  "$schema": "https://gitcooked.dev/schema/gitcooked-v0.json",
  "socials": {
    "website": "https://example.com",
    "twitter": "https://twitter.com/you",
    "mastodon": "https://mastodon.social/@you",
    "bluesky": "https://bsky.app/profile/you.example.com",
    "linkedin": "https://www.linkedin.com/in/you"
  },
  "vouch": [
    "some-dev-you-trust",
    { "login": "another-dev", "note": "shipped great rust together" }
  ],
  "ai_usage": [
    { "provider": "anthropic", "period": "2026-05", "input_tokens": 120000000, "output_tokens": 4200000 },
    { "provider": "openai", "period": "2026-05", "input_tokens": 9000000, "output_tokens": 800000 }
  ]
}
```

Rules:

- `vouch`: max 20 entries counted. Entries for yourself are ignored. Only
  vouches from **ranked** users count toward display.
- `ai_usage`: self-reported, **for fun only** — shown on the token-maxxing
  board, never mixed into contribution rankings. `period` is `YYYY-MM`.
  Tools like codexbar can emit these numbers.

## Token ledger files (preferred for codexbar users)

Instead of inline `ai_usage`, set `"token_files": true` in `gitcooked.json`
and publish monthly ledgers at `gitcooked/tokens/YYYY-MM.json` in the same
profile repo:

```json
{
  "schema": "gitcooked-tokens-v0",
  "month": "2026-06",
  "providers": {
    "codex":  { "days": { "2026-06-02": [695627814, 1038540, 44494] } },
    "claude": { "days": { "2026-06-02": [18647422, 157550, 0] } }
  }
}
```

Each day is `[inputTokens, outputTokens, costCents]` (cache reads count as
input). Why this shape:

- **immutable past** — a finished month never changes, so indexers fetch it
  once and cache forever; only the current month is re-fetched
- **tiny** — one array per active day, ~50 bytes/day vs ~1KB/day in raw
  codexbar exports (no modelBreakdowns, no repeated totals)
- **append-friendly** — your exporter just rewrites the current month file

Convert a codexbar JSON export with `scripts/codexbar_to_gitcooked.py`:

```sh
codexbar cost --json | python3 scripts/codexbar_to_gitcooked.py --out ~/src/YOU/gitcooked/tokens/
```
- socials beyond what's on your GitHub profile (the GitHub-native ones are
  imported automatically from the API).

Indexing runs alongside the ranking refresh; claimed users (GitHub OAuth) can
also manage socials/vouches via the API without a file.
