#!/usr/bin/env python3
"""에이전트 우편 — **실제 클라이언트**(`agora/mail.py` · 서명기 · `store_relay`) ↔ 실제 로컬 릴레이 왕복.

★mailway.py 는 시험용 서명 도우미로 릴레이를 잰다. 이 파일은 그 반대편을 잰다 — 참가자 PC 가 쓰는
  **그 코드 그대로**(keygen → register → sync-roster → mail send/sync/read/ack)가 릴레이 계약과 맞물리는가.
  두 언어의 canonical·인증 문서·신호 묶기 키가 한 바이트라도 다르면 여기서 401/400 이 난다.
★run-local.py 가 mailway 뒤에 부른다(같은 서버·같은 D1). 단독: python3 relay/scripts/clientway.py --base <url>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from agora import errors, mail, onboard, tools  # noqa: E402
from agora.errors import AgoraError  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, what: str) -> None:
    RESULTS.append((bool(ok), what))
    print(("PASS " if ok else "FAIL ") + what)


def participant(base: str, pid: str) -> tuple[str, dict[str, str]]:
    d = tempfile.mkdtemp(prefix=f"agora-clientway-{pid}-")
    env = {"AGORA_CONFIG_DIR": d, "AGORA_SIGNING_KEY": os.path.join(d, "id_ed25519")}
    os.environ.update(env)
    from agora import keygen
    keygen.run([pid])
    with open(os.path.join(REPO, "config", "skill-pin.txt"), encoding="utf-8") as fh:
        pin = fh.read().split()[0]
    onboard.register(directory=d, relay_url=base, skill_pin=pin)
    return d, env


def ctx_for(d: str, env: dict[str, str]) -> tools.Context:
    os.environ.update(env)
    onboard.sync_roster(directory=d, relay_url=None, yes=True)
    ctx = tools.context_from_config(d)
    # ★사람 승인 = 「사람이 y 를 눌렀다」로 둔다 — 자유문 우편은 겹을 탄다는 것이 계약이고, 여기서는 그 뒤를 잰다.
    ctx.isatty, ctx.prompt = (lambda: True), (lambda: True)
    return ctx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    base = ap.parse_args().base.rstrip("/")
    suffix = os.urandom(3).hex()
    alice_id, bob_id = f"cw-alice-{suffix}", f"cw-bob-{suffix}"
    d_a, env_a = participant(base, alice_id)
    d_b, env_b = participant(base, bob_id)
    ctx_a = ctx_for(d_a, env_a)
    ctx_b = ctx_for(d_b, env_b)

    # ① 보내기(자유문 · 승인 겹을 탄다) → 201
    os.environ.update(env_a)
    sent = mail.send(ctx_a, to=bob_id, subject="안녕하세요", body="실제 클라이언트로 보낸 첫 우편")
    check(sent["status"] == 201 and sent["relay"].get("mail_id", "").startswith("ml_"),
          f"클라이언트 발신 201 · mail_id ({sent['status']})")

    # ② 받기 — 서명한 인증 헤더 · 우리 손 재검증 · unread.json
    os.environ.update(env_b)
    got = mail.sync(ctx_b)
    check(got["added"] == 1 and got["quarantined"] == 0, f"수신 적재 1 · 격리 0 ({got})")
    check(got["unread"] == 1 and got["relay_unread_count"] == 1, "로컬·릴레이 미읽음 = 1")
    again = mail.sync(ctx_b)
    check(again["added"] == 0, "두 번째 판은 중복 적재 0(커서·중복 제거)")

    # ③ 답장(같은 대화 · 답장 버킷) → 201
    inbound = mail._rows(mail._path(ctx_b, mail.INBOX_FILE))[0]
    reply = mail.send(ctx_b, to=alice_id, subject="답", body="잘 받았습니다",
                      reply_to=inbound["message_id"])
    check(reply["status"] == 201 and reply["thread_id"] == sent["thread_id"], "답장 201 · 같은 대화")

    # ④ 읽기 → 릴레이 대화 단위 ack → 보낸 쪽 receipts
    shown = mail.read(ctx_b, thread=sent["thread_id"][:8])
    check(shown["relay_ack"].get("acked") == 1 and shown["unread_left"] == 0,
          f"read = 릴레이 ack 1 · 남은 미읽음 0 ({shown['relay_ack']})")
    os.environ.update(env_a)
    back = mail.sync(ctx_a)
    check(back["receipts"] >= 1 and back["added"] == 1, f"보낸 쪽: 영수 ≥1 · 답장 적재 1 ({back})")

    # ⑤ 신호 우편 — 파이썬 묶기 키를 릴레이가 같은 값으로 다시 계산하는가 · 승인 겹 예외(mail_signal)
    os.environ.update(env_b)
    ctx_b.isatty, ctx_b.prompt = (lambda: False), (lambda: False)   # 사람 없음 — 예외 경로만 지나야 한다
    now = mail.now_ms_iso()
    item = {"source": "update", "op": "host.update", "version": "1.1.8", "os": "macos-15.6",
            "error_code": "update.sig_mismatch", "count": 2, "first_seen": now, "last_seen": now}
    item["signature"] = mail.signal_signature(source="update", op="host.update",
                                              error_code="update.sig_mismatch", version="1.1.8")
    doc = mail.build(ctx_b, to=alice_id, payload={"intent": mail.SIGNAL, "items": [item]})
    out = mail._publish(ctx_b, doc)
    check(out["status"] == 201 and out["approval"].get("why") == "approval_exempt:mail_signal",
          f"신호 201 · 승인 겹 예외로 지남 ({out['status']} {out['approval']})")
    try:
        mail.send(ctx_b, to=alice_id, subject="겹", body="사람 없는 자유문")
        check(False, "사람 없는 자유문 우편이 겹을 지났다")
    except AgoraError as e:
        check(e.code == errors.GATE_REJECT, f"사람 없는 자유문 = code 3 (got {e.code})")
    os.environ.update(env_a)
    sig_side = mail.sync(ctx_a)
    # ★앞 ④ 에서 받은 답장이 아직 안 읽혀 미읽음 1 이다 — 신호를 받은 뒤에도 **그대로**여야 한다(로컬·릴레이 둘 다).
    check(sig_side["added"] == 1 and sig_side["unread"] == back["unread"] == 1
          and sig_side["relay_unread_count"] == 1,
          f"신호는 적재하되 미읽음에 안 센다 (전 {back['unread']} → 후 {sig_side['unread']} · 릴레이 {sig_side['relay_unread_count']})")

    # ⑥ 일일 보고(명세 §1-2) — owner_note 빈 통만 승인 겹 예외 mail_daily(D8-1 ⓑ) · 미읽음에 안 센다
    os.environ.update(env_b)
    day = mail.now_ms_iso()[:10]
    noted = mail.build(ctx_b, to=alice_id, payload={"intent": mail.DAILY,
                                                    "daily": {"day": day, "owner_note": "오너 말"}})
    try:
        mail._publish(ctx_b, noted)
        check(False, "사람 없는 owner_note 일일 보고가 겹을 지났다")
    except AgoraError as e:
        check(e.code == errors.GATE_REJECT, f"owner_note 든 일일 보고 · 사람 없음 = code 3 (got {e.code})")
    plain = mail.build(ctx_b, to=alice_id, payload={"intent": mail.DAILY, "daily": {
        "day": day, "version": {"host": "1.1.8"}, "doctor": {"ok": 12, "warn": 1, "fail": 0, "skip": 1,
                                                              "warn_ids": ["dept-awakening-seed"], "fail_ids": []}}})
    out = mail._publish(ctx_b, plain)
    check(out["status"] == 201 and out["approval"].get("why") == "approval_exempt:mail_daily",
          f"owner_note 빈 일일 보고 201 · 예외 mail_daily ({out['status']} {out['approval']})")
    os.environ.update(env_a)
    daily_side = mail.sync(ctx_a)
    check(daily_side["added"] == 1 and daily_side["unread"] == 1 and daily_side["relay_unread_count"] == 1,
          f"일일 보고는 적재하되 미읽음에 안 센다 ({daily_side['added']} · {daily_side['unread']} · {daily_side['relay_unread_count']})")

    passed = sum(1 for ok, _ in RESULTS if ok)
    print(f"== 클라이언트 왕복 결과: {'PASS' if passed == len(RESULTS) else 'FAIL'} ({passed}/{len(RESULTS)}) ==")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
