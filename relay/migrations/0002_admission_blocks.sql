-- 0002_admission_blocks.sql — 받아들이기 차단(은퇴) 표 + 트리거 4(설계 docs/design/key-lifecycle/DESIGN-v3.md §5-1)
-- ★추가만 한다 — 0001 의 표·칸·행을 바꾸지 않는다. participants 에는 **트리거만** 건다(칸·행 불변).
-- ★이 표를 읽는 곳은 **새 쓰기를 받을지 말지**(POST /events · /register · /participants/checkpoint)와
--   /home 의 알림뿐이다. 명부 렌더·체크포인트·서명 검증(lookupTable·verifyDetail)·방 판정(리듀서)은
--   이 표를 읽지 않는다 — 읽게 만들면 그 방 전원의 쓰기가 멈춘다(설계 §1-3 경계 · 시험 T8·T13).
-- ★트리거가 최종 집행이다: 앱 층 검사와 INSERT 사이의 경합을 닫고, 코드를 옛 판으로 되돌려도 차단이 남는다.
-- ★차단은 되돌리지 않는다(계약). 기술적 되돌림 = 행 삭제(master).

CREATE TABLE IF NOT EXISTS admission_blocks (
  participant_id TEXT PRIMARY KEY,
  fingerprint    TEXT NOT NULL UNIQUE,   -- 차단할 키 지문(그 id 의 키 · 시험 릴레이처럼 id 행이 없어도 넣는다)
  blocked_at     TEXT NOT NULL,          -- 효력 발생점 = 이 행이 커밋된 순간
  reason         TEXT NOT NULL CHECK (reason IN ('retired'))
);

-- 등록: 차단된 **id 또는 지문**이면 새 행을 막는다(행이 없는 릴레이에서의 선점 · 우리 키로 다른 이름 등록까지).
CREATE TRIGGER IF NOT EXISTS participants_admission_block BEFORE INSERT ON participants
  WHEN EXISTS (SELECT 1 FROM admission_blocks b
                WHERE b.participant_id = NEW.participant_id OR b.fingerprint = NEW.fingerprint)
  BEGIN SELECT RAISE(ABORT, 'agora:admission_blocked'); END;

-- 새 글: 차단된 id 의 이벤트 적재를 막는다(차단 전에 적재된 행은 그대로다).
CREATE TRIGGER IF NOT EXISTS events_admission_block BEFORE INSERT ON events
  WHEN EXISTS (SELECT 1 FROM admission_blocks b WHERE b.participant_id = NEW.from_id)
  BEGIN SELECT RAISE(ABORT, 'agora:admission_blocked'); END;

-- 체크포인트: postCheckpoint 는 INSERT … ON CONFLICT DO UPDATE 라 두 경로를 모두 막는다.
CREATE TRIGGER IF NOT EXISTS checkpoints_admission_block_ins BEFORE INSERT ON roster_checkpoints
  WHEN EXISTS (SELECT 1 FROM admission_blocks b WHERE b.participant_id = NEW.signer)
  BEGIN SELECT RAISE(ABORT, 'agora:admission_blocked'); END;

CREATE TRIGGER IF NOT EXISTS checkpoints_admission_block_upd BEFORE UPDATE ON roster_checkpoints
  WHEN EXISTS (SELECT 1 FROM admission_blocks b WHERE b.participant_id = NEW.signer)
  BEGIN SELECT RAISE(ABORT, 'agora:admission_blocked'); END;
