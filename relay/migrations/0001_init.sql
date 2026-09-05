-- 0001_init.sql — 아고라 릴레이 원장(계약 = docs/RELAY.md §8)
-- ★events 는 append-only 다. UPDATE·DELETE 하는 코드가 있으면 그 자체가 결함이다.
-- ★rooms 는 파생 캐시다. DROP 해도 events 로 재계산된다(합격 기준 R-7).

CREATE TABLE IF NOT EXISTS participants (
  participant_id TEXT PRIMARY KEY,
  display_name   TEXT NOT NULL,
  key_type       TEXT NOT NULL,
  key_b64        TEXT NOT NULL,
  fingerprint    TEXT NOT NULL UNIQUE,
  is_operator    INTEGER NOT NULL DEFAULT 0,
  revoked_at     TEXT,
  created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  seq          INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id    TEXT NOT NULL,
  message_id   TEXT NOT NULL,
  from_id      TEXT NOT NULL,
  kind         TEXT NOT NULL,
  prev         TEXT NOT NULL,
  hash         TEXT NOT NULL,
  canonical    TEXT NOT NULL,
  signature    TEXT NOT NULL,
  category     TEXT NOT NULL,
  title        TEXT NOT NULL,
  is_genesis   INTEGER NOT NULL,
  created_at   TEXT NOT NULL,
  UNIQUE (from_id, message_id)
);
CREATE INDEX IF NOT EXISTS events_thread ON events (thread_id, seq);

CREATE TABLE IF NOT EXISTS rooms (
  thread_id      TEXT PRIMARY KEY,
  title          TEXT NOT NULL,
  type           TEXT NOT NULL,
  state          TEXT,
  round          INTEGER,
  chair          TEXT,
  requester      TEXT,
  closed         INTEGER NOT NULL DEFAULT 0,
  answered       INTEGER NOT NULL DEFAULT 0,
  close_reason   TEXT,
  closed_at      TEXT,
  participants   INTEGER NOT NULL DEFAULT 0,
  deadline       TEXT,
  state_hash     TEXT,
  events_counted INTEGER NOT NULL DEFAULT 0,
  signature_bad  INTEGER NOT NULL DEFAULT 0,
  updated_at     TEXT NOT NULL,
  last_seq       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rooms_open ON rooms (closed, updated_at DESC);

CREATE TABLE IF NOT EXISTS rate_windows (
  bucket       TEXT NOT NULL,
  window_start INTEGER NOT NULL,
  count        INTEGER NOT NULL,
  PRIMARY KEY (bucket, window_start)
);

-- 운영자가 서명해 올린 명부 체크포인트(docs/RELAY.md §3-6b). 서버는 서명하지 않고 보관만 한다.
CREATE TABLE IF NOT EXISTS roster_checkpoints (
  checkpoint TEXT PRIMARY KEY,
  signer     TEXT NOT NULL,
  signature  TEXT NOT NULL,
  signed_at  TEXT NOT NULL
);
