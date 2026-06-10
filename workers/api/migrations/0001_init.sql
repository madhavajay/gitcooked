CREATE TABLE IF NOT EXISTS users (
  login TEXT PRIMARY KEY,
  github_id INTEGER UNIQUE,
  name TEXT,
  avatar_url TEXT,
  claimed_at TEXT NOT NULL,
  socials TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS vouches (
  voucher TEXT NOT NULL,
  vouchee TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (voucher, vouchee)
);
CREATE INDEX IF NOT EXISTS idx_vouches_vouchee ON vouches (vouchee);

CREATE TABLE IF NOT EXISTS index_requests (
  login TEXT PRIMARY KEY,
  location TEXT,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS token_usage (
  login TEXT NOT NULL,
  provider TEXT NOT NULL,
  period TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  source_url TEXT,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (login, provider, period)
);
