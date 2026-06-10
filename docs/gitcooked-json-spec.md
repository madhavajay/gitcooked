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
- socials beyond what's on your GitHub profile (the GitHub-native ones are
  imported automatically from the API).

Indexing runs alongside the ranking refresh; claimed users (GitHub OAuth) can
also manage socials/vouches via the API without a file.
