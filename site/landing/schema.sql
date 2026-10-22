-- The landing page's waiting list (D1). Applied once by the captain:
--   npx wrangler d1 execute lcars-landing --remote --file schema.sql
-- Only what the page's privacy note says is kept.
CREATE TABLE IF NOT EXISTS signups (
  id      INTEGER PRIMARY KEY,
  email   TEXT NOT NULL UNIQUE COLLATE NOCASE,  -- lower-cased by the worker too
  use     TEXT,                                 -- what they would use it for, optional, <= 280
  consent INTEGER NOT NULL CHECK (consent = 1), -- the box ticked: write to me when hosted opens
  created TEXT NOT NULL                         -- UTC, ISO 8601, to the second
);

-- The rate limit: a salted hash of the address and when, kept an hour.
CREATE TABLE IF NOT EXISTS rate (
  k  TEXT NOT NULL,
  at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rate_k_at ON rate (k, at);
