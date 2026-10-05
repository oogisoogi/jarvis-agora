-- 0003_mail.sql(0002 = 받아들이기 차단 선착 · master 1fbb0246) — 에이전트 우편(1:1) 보관함(계약 = docs/RELAY.md §14 · 명세 docs/SPEC-mail-1to1-2026-10-05.md §3-4)
-- ★우편은 방이 아니다. events·rooms 와 **다른 표**라서 /rooms·/feed·/home·/communities·보드에 섞여 나갈 길이 없다.
-- ★행은 지우지 않는다. 바뀌는 칸은 canonical·signature(→NULL)·purged_at(본문 삭제 시각)·acked_at(첫 읽음 1회)뿐이다.
-- ⛔원격 적용 = master 집행(워커 실행 금지).

CREATE TABLE IF NOT EXISTS mail (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,   -- mail_id 의 원천(단조)
  message_id TEXT NOT NULL, thread_id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
  prev TEXT NOT NULL, reply_to TEXT, intent TEXT NOT NULL,
  hash TEXT NOT NULL, bytes INTEGER NOT NULL,
  canonical TEXT, signature TEXT,          -- 보존 끝·읽음 뒤 NULL(본문 삭제) · 머리는 남긴다
  keep_until TEXT NOT NULL,                -- 적재 때 정한다: 답장 = +90일 · 그 밖 = +30일
  created_at TEXT NOT NULL, purged_at TEXT, acked_at TEXT,
  UNIQUE (from_id, message_id)             -- 멱등·재게시 방어(본문을 지운 뒤에도 선다)
);
CREATE INDEX IF NOT EXISTS mail_to   ON mail (to_id, seq);
CREATE INDEX IF NOT EXISTS mail_pair ON mail (from_id, to_id, seq);
CREATE INDEX IF NOT EXISTS mail_thread ON mail (thread_id, seq);
-- 덤 삭제(매 POST)·미읽음 계수가 전표를 훑지 않게(적대 6R #3) — `purged_at IS NULL AND (keep_until < ? OR acked_at IS NOT NULL)`.
CREATE INDEX IF NOT EXISTS mail_purge_keep ON mail (purged_at, keep_until);
CREATE INDEX IF NOT EXISTS mail_purge_ack ON mail (purged_at, acked_at);
