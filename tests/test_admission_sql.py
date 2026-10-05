"""받아들이기 차단 마이그레이션(`relay/migrations/0002_admission_blocks.sql`)의 DB 층 시험.

설계 DESIGN-v3 §5-1 · 시험 T6(DB 층)·T10(UPSERT 두 경로)·T12(트리거가 UNIQUE 보다 먼저)·T14(0001 위 적용·재적용).
★로컬 SQLite 로 잰다 — 원격 D1 의 트리거 지원은 T16(시험 릴레이)이 따로 잰다(설계 확신도 「중간」).
★pytest 없이도 돈다: `python3 tests/test_admission_sql.py`.
"""
from __future__ import annotations

import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M1 = os.path.join(ROOT, "relay", "migrations", "0001_init.sql")
M2 = os.path.join(ROOT, "relay", "migrations", "0002_admission_blocks.sql")
MARK = "agora:admission_blocked"


def db(with_0002=True):
    c = sqlite3.connect(":memory:")
    c.executescript(open(M1, encoding="utf-8").read())
    if with_0002:
        c.executescript(open(M2, encoding="utf-8").read())
    return c


def reg(c, pid, fp):
    c.execute("INSERT INTO participants (participant_id, display_name, key_type, key_b64, fingerprint,"
              " is_operator, revoked_at, created_at) VALUES (?,?,?,?,?,0,NULL,'t')",
              (pid, pid, "ssh-ed25519", "AAAA" + pid, fp))


def post(c, frm, mid):
    c.execute("INSERT INTO events (thread_id, message_id, from_id, kind, prev, hash, canonical, signature,"
              " category, title, is_genesis, created_at) VALUES ('t',?,?,'post','p','h','{}','s','debate','',0,'t')",
              (mid, frm))


def block(c, pid, fp):
    c.execute("INSERT INTO admission_blocks (participant_id, fingerprint, blocked_at, reason)"
              " VALUES (?,?,'t','retired')", (pid, fp))


def raises(fn, *a):
    try:
        fn(*a)
    except sqlite3.DatabaseError as e:
        return str(e)
    return None


def test_schema_objects_and_0001_untouched():
    before = db(False)
    after = db(True)
    for t in ("participants", "events", "roster_checkpoints", "rooms", "rate_windows"):
        assert before.execute("PRAGMA table_info(%s)" % t).fetchall() == \
            after.execute("PRAGMA table_info(%s)" % t).fetchall(), t
    trig = sorted(r[0] for r in after.execute("SELECT name FROM sqlite_master WHERE type='trigger'"))
    assert trig == ["checkpoints_admission_block_ins", "checkpoints_admission_block_upd",
                    "events_admission_block", "participants_admission_block"]
    # 재적용(IF NOT EXISTS) 은 무해해야 한다 — T14
    after.executescript(open(M2, encoding="utf-8").read())


def test_upgrade_existing_data_keeps_rows():
    """[T14] 0001 + 데이터 DB 에 0002 를 얹어도 행이 그대로고, 차단 전 행은 차단 뒤에도 남는다."""
    c = db(False)
    reg(c, "alice", "fa"); reg(c, "bob", "fb"); post(c, "alice", "m1")
    c.executescript(open(M2, encoding="utf-8").read())
    block(c, "alice", "fa")
    assert c.execute("SELECT COUNT(*) FROM events WHERE from_id='alice'").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM participants").fetchone()[0] == 2


def test_events_trigger():
    c = db()
    reg(c, "alice", "fa"); reg(c, "bob", "fb")
    post(c, "alice", "m1")
    block(c, "alice", "fa")
    e = raises(post, c, "alice", "m2")
    assert e and MARK in e
    post(c, "bob", "m3")                                  # 대조군 [T7]
    # [T12 · D2-5] 이미 적재된 같은 (from,message_id) 재삽입 → UNIQUE 가 아니라 **트리거가 먼저** 난다
    e = raises(post, c, "alice", "m1")
    assert e and MARK in e and "UNIQUE" not in e


def test_participants_trigger_id_or_fingerprint():
    """[T6 DB 층] 행이 없어도 막는다 — 차단 id + 새 키 / 차단 지문 + 다른 이름. 둘 다 트리거가 UNIQUE 보다 먼저."""
    c = db()
    block(c, "ours", "fp-ours")                           # 시험 릴레이 모양: id 행 없음
    assert MARK in (raises(reg, c, "ours", "fp-new") or "")
    assert MARK in (raises(reg, c, "other", "fp-ours") or "")
    reg(c, "carol", "fc")                                 # 대조군
    c2 = db()
    reg(c2, "ours", "fp-ours")
    block(c2, "ours", "fp-ours")
    e = raises(reg, c2, "ours", "fp-ours")                # 본 릴레이 모양: 같은 행 재삽입 → PK 보다 트리거 먼저
    assert e and MARK in e


def test_checkpoint_upsert_both_paths():
    """[T10] postCheckpoint 의 INSERT … ON CONFLICT DO UPDATE — 새 키·충돌 키 모두 막히고, 직접 UPDATE 도 막힌다."""
    up = ("INSERT INTO roster_checkpoints (checkpoint, signer, signature, signed_at) VALUES (?,?,?,?)"
          " ON CONFLICT(checkpoint) DO UPDATE SET signer=excluded.signer, signature=excluded.signature,"
          " signed_at=excluded.signed_at")
    c = db()
    c.execute(up, ("cp1", "bob", "s", "t"))
    block(c, "op", "fop")
    assert MARK in (raises(c.execute, up, ("cp2", "op", "s", "t")) or "")        # 새 키(INSERT)
    assert MARK in (raises(c.execute, up, ("cp1", "op", "s", "t2")) or "")       # 충돌 키(UPDATE 경로)
    assert c.execute("SELECT signer FROM roster_checkpoints WHERE checkpoint='cp1'").fetchone()[0] == "bob"
    assert MARK in (raises(c.execute, "UPDATE roster_checkpoints SET signer='op' WHERE checkpoint='cp1'") or "")
    c.execute(up, ("cp1", "bob", "s2", "t3"))                                   # 대조군
    c.execute("UPDATE roster_checkpoints SET signed_at='t4' WHERE checkpoint='cp1'")


def test_blocks_table_constraints():
    c = db()
    block(c, "a", "fa")
    assert raises(block, c, "a", "fz")                    # id PK
    assert raises(block, c, "b", "fa")                    # 지문 UNIQUE
    assert raises(c.execute, "INSERT INTO admission_blocks VALUES ('c','fc','t','revoked')")   # reason CHECK


def _run_all():
    names = [n for n in sorted(globals()) if n.startswith("test_")]
    bad = 0
    for n in names:
        try:
            globals()[n]()
            print("PASS", n)
        except Exception as e:                            # noqa: BLE001
            bad += 1
            print("FAIL", n, type(e).__name__, str(e)[:300])
    print("%d/%d 통과 · sqlite %s" % (len(names) - bad, len(names), sqlite3.sqlite_version))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_run_all())
