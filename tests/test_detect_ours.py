"""탐지기 1단계(`tools/detect_ours.py`) 시험 — 설계 DESIGN-v3 §8 T17 의 1단계분.

★가짜 GET 으로 잰다(네트워크 0). 가짜가 착하게만 굴면 탐지기의 「불완전」 경로가 공허해지므로
  실패·모양 이상·상한 도달·멈춘 커서를 일부러 만든다.
★pytest 없이도 돈다: `python3 tests/test_detect_ours.py`.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agora.event import event_hash, new_id, render_post  # noqa: E402
from tools import detect_ours as d                       # noqa: E402

PID = "jarvis-test0000001"
FP = "SHA256:" + "A" * 43
MAIN = "https://main.example"
TRIAL = "https://trial.example"


def ev(frm, thread, mid=None, body="x"):
    return {"v": 1, "kind": "post", "thread_id": thread, "message_id": mid or new_id(), "prev": "0" * 64,
            "expected_state": "", "from": frm, "roster": "0" * 64,
            "scrub": {"rules": "t", "blocked": 0, "redacted": 0}, "ts": "2026-09-29T00:00:00Z",
            "payload": {"round": 0, "body": body}}


class Relay:
    """본·시험 릴레이 하나씩을 흉내 내는 가짜 GET."""

    def __init__(self):
        self.rooms: dict[str, list[dict]] = {}
        self.home_rooms: list[str] | None = None      # None = rooms 의 키 전부
        self.page = 100
        self.fail: set[str] = set()                    # 이 문자열을 포함한 URL 은 연결 실패
        self.stuck_cursor = False
        self.fp_owner = PID                            # 본 릴레이에서 우리 지문이 붙은 이름
        self.id_fp = FP                                # 본 릴레이에서 우리 id 의 지문
        self.trial_ids: dict[str, str] = {}            # 시험 릴레이에 등록된 {질의값: 참가자}
        self.calls: list[str] = []
        self.trial_health = (404, "error code: 1042")  # 공개 주소 꺼짐(Cloudflare 1042)

    def add(self, room, e):
        self.rooms.setdefault(room, []).append(e)

    def __call__(self, url):
        self.calls.append(url)
        for f in self.fail:
            if f in url:
                return None, "URLError: fake"
        if url.startswith(TRIAL):
            if "/health" in url:
                return self.trial_health
            who = unquote(url.split("participant=", 1)[1])
            if who in self.trial_ids:
                return 200, {"participant": self.trial_ids[who]}
            return 404, {"code": 7, "message": "그런 참가자가 없다"}
        path = url[len(MAIN):]
        if path.startswith("/home?participant="):
            who = unquote(path.split("=", 1)[1])
            if who == PID:
                rooms = self.home_rooms if self.home_rooms is not None else list(self.rooms)
                return 200, {"participant": PID, "fingerprint": self.id_fp,
                             "rooms": [{"room_id": r} for r in rooms], "notify": []}
            if who == FP:
                return 200, {"participant": self.fp_owner, "fingerprint": FP, "rooms": [], "notify": []}
            return 404, {"code": 7}
        room = path.split("/")[2]
        cursor = int(path.split("cursor=")[1])
        allev = self.rooms.get(room, [])
        chunk = allev[cursor:cursor + self.page]
        items = [{"event_id": "ev_%016d" % (cursor + i + 1), "created_at": "t", "body": render_post(e)}
                 for i, e in enumerate(chunk)]
        more = cursor + len(chunk) < len(allev)
        nxt = (str(cursor) if self.stuck_cursor else str(cursor + len(chunk))) if more else None
        return 200, {"items": items, "next_cursor": nxt}


def setup(sent_events=(), ledger=True, trial_state="running", workers_dev="true"):
    tmp = tempfile.mkdtemp(prefix="detect-")
    cfg = os.path.join(tmp, "cfg")
    os.makedirs(cfg)
    json.dump({"id": PID, "key_fingerprint": FP}, open(os.path.join(cfg, "participant.json"), "w"))
    json.dump({"relay": {"url": MAIN}}, open(os.path.join(cfg, "config.json"), "w"))
    if ledger:
        with open(os.path.join(cfg, "ledger.jsonl"), "w") as fh:
            for e in sent_events:
                fh.write(json.dumps({"dir": "sent", "stage": "sent", "message_id": e["message_id"],
                                     "hash": event_hash(e), "hash_of": "event_canonical"}) + "\n")
    log = os.path.join(tmp, "trial.jsonl")
    with open(log, "w") as fh:
        fh.write("# 머리말\n")
        fh.write(json.dumps({"ts": "t", "state": trial_state}) + "\n")
    conf = os.path.join(tmp, "next.jsonc")
    with open(conf, "w") as fh:
        fh.write('{\n  "name": "x",\n  "workers_dev": %s,\n}\n' % workers_dev)
    return tmp, cfg, log, conf


def scan(relay, cfg, log, conf, trial=True):
    return d.run(fetch=relay, config_dir=cfg, main_url=None, trial_url=TRIAL if trial else None,
                 trial_log=log, trial_config=conf)


def reasons(rep):
    return sorted({i["reason"] for i in rep["incomplete"]})


def kinds(rep):
    return sorted({a["kind"] for a in rep["alarms"]})


# ── 시험 ────────────────────────────────────────────────────────────────────
def test_all_match_ok():
    r = Relay()
    mine = [ev(PID, "a" * 32), ev(PID, "b" * 32)]
    r.add("a" * 32, ev("bob", "a" * 32)); r.add("a" * 32, mine[0]); r.add("b" * 32, mine[1])
    tmp, cfg, log, conf = setup(mine)
    rep = scan(r, cfg, log, conf)
    assert rep["verdict"] == "OK", rep
    assert rep["counts"] == {"match": 2}
    assert d.exit_code(rep) == 0


def test_paging_101_and_201():
    """[T17 101·201번째] 쪽이 넘어가도 끝까지 본다 — 마지막 쪽의 우리 글을 잡는다."""
    for n in (101, 201):
        r = Relay()
        room = "c" * 32
        for _ in range(n - 1):
            r.add(room, ev("bob", room))
        last = ev(PID, room)
        r.add(room, last)                          # n 번째 = 우리 글(원장에 없음)
        tmp, cfg, log, conf = setup([])
        rep = scan(r, cfg, log, conf)
        assert kinds(rep) == ["unrecorded_our_name"], (n, rep)
        assert rep["alarms"][0]["event_id"] == "ev_%016d" % n


def test_unrecorded_code8_residual_is_alarm_not_action():
    """[T17 code 8 잔여] 원장에 없는 우리 글 = 「원장 미기록 — 출처 미확정」 경보(자동 조치 없음)."""
    r = Relay()
    ok, orphan = ev(PID, "d" * 32), ev(PID, "d" * 32)
    r.add("d" * 32, ok); r.add("d" * 32, orphan)
    tmp, cfg, log, conf = setup([ok])
    rep = scan(r, cfg, log, conf)
    assert rep["verdict"] == "ALARM" and d.exit_code(rep) == 1
    a = rep["alarms"][0]
    assert a["message_id"] == orphan["message_id"] and "출처 미확정" in a["detail"]
    assert "body" not in json.dumps(a)             # 본문을 인용하지 않는다


def test_hash_mismatch_same_message_id():
    r = Relay()
    mine = ev(PID, "e" * 32)
    forged = dict(mine, payload={"round": 0, "body": "다른 내용"})
    r.add("e" * 32, forged)
    tmp, cfg, log, conf = setup([mine])
    rep = scan(r, cfg, log, conf)
    assert kinds(rep) == ["unrecorded_our_name"] and "해시" in rep["alarms"][0]["detail"]


def test_eleventh_room_is_incomplete():
    """[T17 11번째 방] /home 방 상한(10)에 닿으면 「불완전」 — 없다고 세지 않는다."""
    r = Relay()
    for i in range(10):
        r.add("%032x" % i, ev("bob", "%032x" % i))
    tmp, cfg, log, conf = setup([])
    rep = scan(r, cfg, log, conf)
    assert reasons(rep) == ["home_rooms_max"] and rep["verdict"] == "INCOMPLETE"
    assert d.exit_code(rep) == 2


def test_uncached_room_seen_as_ledger_gap():
    """[T17 캐시 없는 방] /home 이 방을 못 돌려주면 원장 발신이 안 보인다 → 불완전(ledger_sent_not_seen)."""
    r = Relay()
    mine = ev(PID, "f" * 32)
    r.add("f" * 32, mine)
    r.home_rooms = []                               # rooms 캐시에 그 방이 없음
    tmp, cfg, log, conf = setup([mine])
    rep = scan(r, cfg, log, conf)
    assert reasons(rep) == ["ledger_sent_not_seen"], rep


def test_get_failures_are_incomplete():
    """[T17 GET 실패 경보] 실패를 「우리 글 없음」으로 읽지 않는다."""
    for frag, want in (("/home?participant=" + PID, "home_get_failed"), ("/events", "events_get_failed")):
        r = Relay()
        r.add("a" * 32, ev("bob", "a" * 32))
        r.fail.add(frag)
        tmp, cfg, log, conf = setup([])
        rep = scan(r, cfg, log, conf)
        assert want in reasons(rep) and rep["verdict"] == "INCOMPLETE", (frag, rep)


def test_cursor_stuck_is_incomplete():
    r = Relay()
    for _ in range(150):
        r.add("a" * 32, ev("bob", "a" * 32))
    r.stuck_cursor = True
    tmp, cfg, log, conf = setup([])
    rep = scan(r, cfg, log, conf)
    assert "cursor_stuck" in reasons(rep)


def test_cursor_field_missing_is_incomplete():
    """[impl codex] next_cursor 칸 누락을 마지막 쪽으로 읽지 않는다 — 다음 쪽의 우리 글을 놓친다."""
    r = Relay()
    for _ in range(150):
        r.add("a" * 32, ev("bob", "a" * 32))
    orig = r.__call__

    def drop(url, _orig=orig):
        st, body = _orig(url)
        if isinstance(body, dict) and "items" in body:
            body = {k: v for k, v in body.items() if k != "next_cursor"}
        return st, body
    tmp, cfg, log, conf = setup([])
    rep = d.run(fetch=drop, config_dir=cfg, main_url=None, trial_url=None, trial_log=log, trial_config=conf)
    assert reasons(rep) == ["cursor_missing"], rep


def test_http_get_incomplete_read_is_failure_not_crash():
    """[impl codex] 본문 읽기 실패(IncompleteRead)가 예외로 새지 않고 (None, 사유)가 된다."""
    import http.client
    import urllib.request as ur

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): raise http.client.IncompleteRead(b"x", 10)
    real = ur.urlopen
    ur.urlopen = lambda *a, **k: Resp()
    try:
        st, why = d.http_get("https://x.example/y")
    finally:
        ur.urlopen = real
    assert st is None and "IncompleteRead" in why


def test_ledger_missing_is_incomplete():
    r = Relay()
    tmp, cfg, log, conf = setup([], ledger=False)
    rep = scan(r, cfg, log, conf)
    assert reasons(rep) == ["ledger_missing"]


def test_main_fingerprint_other_name_and_id_mismatch():
    r = Relay()
    r.fp_owner = "someone-else"
    r.id_fp = "SHA256:" + "B" * 43
    tmp, cfg, log, conf = setup([])
    rep = scan(r, cfg, log, conf)
    assert kinds(rep) == ["main_fingerprint_other_name", "main_id_fingerprint_mismatch"]


def test_trial_registration_by_id_and_by_fingerprint():
    """[T17 시험 릴레이 id·지문 등록 경보]"""
    for key, want in ((PID, "trial_registered_id"), (FP, "trial_registered_fingerprint")):
        r = Relay()
        r.trial_ids[key] = "thief-name"
        tmp, cfg, log, conf = setup([])
        rep = scan(r, cfg, log, conf)
        assert kinds(rep) == [want], rep


def test_trial_get_failure_while_running_is_incomplete():
    r = Relay()
    r.fail.add(TRIAL)
    tmp, cfg, log, conf = setup([])
    rep = scan(r, cfg, log, conf)
    assert reasons(rep) == ["trial_get_failed"] and rep["verdict"] == "INCOMPLETE"


def test_trial_off_is_skipped_and_marked_without_get():
    """[T17 「꺼짐」 표시] 운영 기록 off + 설정 false → GET 을 부르지 않고 건너뜀을 표시."""
    r = Relay()
    tmp, cfg, log, conf = setup([], trial_state="off", workers_dev="false")
    rep = scan(r, cfg, log, conf)
    assert rep["verdict"] == "OK", rep
    trial_calls = [c for c in r.calls if c.startswith(TRIAL)]
    assert len(trial_calls) == 1 and "/health?nocache=" in trial_calls[0]    # /health 1회만(캐시 우회) · 참가자 질의 0
    trial = [x for x in rep["relays"] if x["role"] == "trial"][0]
    assert trial["state"] == "off" and "건너뜀" in trial["skipped"]


def test_trial_off_confirmed_by_json_1042():
    """[실측 2026-09-29] Accept: application/json 이면 Cloudflare 가 1042 를 JSON 본문으로 준다."""
    r = Relay()
    r.trial_health = (404, {"error_code": 1042, "error_name": "workers_dev_script_not_found"})
    tmp, cfg, log, conf = setup([], trial_state="off", workers_dev="false")
    rep = scan(r, cfg, log, conf)
    assert rep["verdict"] == "OK", rep


def test_trial_off_but_answering_is_alarm():
    """[impl-r1] 기록은 꺼짐인데 /health 가 우리 응답 — 경보 + 켜짐 기준으로 참가자 질의까지 한다."""
    r = Relay()
    r.trial_health = (200, {"ok": True, "namespace": "x"})
    r.trial_ids[PID] = "thief"
    tmp, cfg, log, conf = setup([], trial_state="off", workers_dev="false")
    rep = scan(r, cfg, log, conf)
    assert kinds(rep) == ["trial_registered_id", "trial_up_while_recorded_off"], rep
    trial = [x for x in rep["relays"] if x["role"] == "trial"][0]
    assert trial["state"] == "running"
    for st in ((None, "URLError"), (500, "x"), (200, "not json"), (404, "not found")):   # 꺼짐 확인 = 404+1042 만
        r2 = Relay()
        r2.trial_health = st
        rep2 = scan(r2, *setup([], trial_state="off", workers_dev="false")[1:])
        assert reasons(rep2) == ["trial_off_unconfirmed"] and rep2["verdict"] == "INCOMPLETE", (st, rep2)


def test_unverified_hash_match_is_incomplete():
    r = Relay()
    mine = ev(PID, "a" * 32)
    r.add("a" * 32, mine)
    tmp, cfg, log, conf = setup([])
    with open(os.path.join(cfg, "ledger.jsonl"), "w") as fh:              # 옛 행 — hash_of 없음
        fh.write(json.dumps({"dir": "sent", "stage": "sent", "message_id": mine["message_id"], "hash": "x"}) + "\n")
    rep = scan(r, cfg, log, conf)
    assert reasons(rep) == ["hash_unverified"] and rep["verdict"] == "INCOMPLETE", rep


def test_trial_log_config_mismatch_is_incomplete():
    """기록은 off 인데 설정은 true(또는 그 반대) — 어느 쪽이 참인지 모른다 → 불완전."""
    for st, wd in (("off", "true"), ("running", "false")):
        r = Relay()
        tmp, cfg, log, conf = setup([], trial_state=st, workers_dev=wd)
        rep = scan(r, cfg, log, conf)
        assert reasons(rep) == ["trial_log_config_mismatch"], (st, wd, rep)


def test_success_file_only_when_complete_and_liveness():
    """[T17 생존 경보] 불완전이면 마지막 성공을 안 남기고, 오래되면 경보."""
    r = Relay()
    tmp, cfg, log, conf = setup([], ledger=False)
    sd = os.path.join(tmp, "state")
    d.write_success(sd, scan(r, cfg, log, conf))
    assert d.liveness(sd, 3)[0] == 1                # 기록 없음 = 경보
    tmp2, cfg2, log2, conf2 = setup([])
    d.write_success(sd, scan(Relay(), cfg2, log2, conf2))
    assert d.liveness(sd, 3)[0] == 0
    epoch = json.load(open(os.path.join(sd, "last_success.json")))["epoch"]
    assert d.liveness(sd, 3, now=epoch + 3 * 3600 + 60)[0] == 1


# ── 알림(상태 변화 때만 · master 판정 2026-09-29) ──────────────────────────
def fake_inbox(tmp, ok=True):
    """인박스 헬퍼 대역 — 인자(보낸 이)와 본문을 파일에 남긴다. ok=False 면 실패(rc 1)."""
    path = os.path.join(tmp, "inbox.sh")
    out = os.path.join(tmp, "inbox.log")
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\n%s{ printf '%%s|' \"$1\"; cat; printf '\\n=====\\n'; } >> '%s'\n"
                 % ("" if ok else "exit 1\n", out))
    os.chmod(path, 0o755)
    return path, out


def sent(out):
    return [x for x in (open(out).read().split("\n=====\n") if os.path.exists(out) else []) if x.strip()]


def rep_of(verdict, alarms=(), incomplete=()):
    return {"verdict": verdict, "alarms": list(alarms), "incomplete": list(incomplete), "participant": PID,
            "checked_at": "t", "stage": "1단계"}


def test_notify_alarm_immediate_then_only_on_change():
    tmp = tempfile.mkdtemp(prefix="notify-")
    cmd, out = fake_inbox(tmp)
    a1 = rep_of("ALARM", [{"kind": "unrecorded_our_name", "relay": MAIN, "event_id": "ev_1"}])
    assert d.notify_scan(a1, tmp, cmd) and len(sent(out)) == 1
    assert sent(out)[0].startswith(d.NOTIFY_FROM + "|【경고】 탐지기 경보")
    assert d.notify_scan(a1, tmp, cmd) and len(sent(out)) == 1          # 같은 경보 = 침묵
    a2 = rep_of("ALARM", [{"kind": "unrecorded_our_name", "relay": MAIN, "event_id": "ev_2"}])
    assert d.notify_scan(a2, tmp, cmd) and len(sent(out)) == 2          # 다른 경보 = 알림
    assert d.notify_scan(rep_of("OK"), tmp, cmd) and "【해소】" in sent(out)[2]
    assert d.notify_scan(rep_of("OK"), tmp, cmd) and len(sent(out)) == 3


def test_notify_incomplete_needs_two_in_a_row():
    tmp = tempfile.mkdtemp(prefix="notify-")
    cmd, out = fake_inbox(tmp)
    inc = rep_of("INCOMPLETE", incomplete=[{"reason": "home_get_failed", "relay": MAIN}])
    d.notify_scan(inc, tmp, cmd)
    assert sent(out) == []                                              # 1회 = 침묵
    d.notify_scan(rep_of("OK"), tmp, cmd)                               # 끊기면 연속 수 초기화
    d.notify_scan(inc, tmp, cmd)
    assert sent(out) == []
    d.notify_scan(inc, tmp, cmd)
    assert len(sent(out)) == 1 and "연속 2회" in sent(out)[0]
    d.notify_scan(inc, tmp, cmd)
    assert len(sent(out)) == 1                                          # 같은 불완전 반복 = 침묵


def test_notify_first_ok_is_silent_and_failure_retries():
    tmp = tempfile.mkdtemp(prefix="notify-")
    cmd, out = fake_inbox(tmp)
    d.notify_scan(rep_of("OK"), tmp, cmd)
    assert sent(out) == []
    bad, _ = fake_inbox(tempfile.mkdtemp(), ok=False)
    a = rep_of("ALARM", [{"kind": "trial_registered_id", "relay": TRIAL}])
    assert d.notify_scan(a, tmp, bad) is False                          # 못 보냄 → 상태 안 바뀜
    assert d.notify_scan(a, tmp, cmd) and len(sent(out)) == 1           # 다음 회차가 보낸다


def test_notify_liveness_on_change_only():
    tmp = tempfile.mkdtemp(prefix="notify-")
    cmd, out = fake_inbox(tmp)
    assert d.notify_liveness(0, "정상", tmp, cmd) and sent(out) == []
    d.notify_liveness(1, "★경보 탐지기 생존: …", tmp, cmd)
    d.notify_liveness(1, "★경보 탐지기 생존: …", tmp, cmd)
    assert len(sent(out)) == 1 and "【경고】" in sent(out)[0]
    d.notify_liveness(0, "정상", tmp, cmd)
    assert len(sent(out)) == 2 and "【해소】" in sent(out)[1]


def test_notify_body_has_no_event_body():
    tmp = tempfile.mkdtemp(prefix="notify-")
    cmd, out = fake_inbox(tmp)
    r = Relay()
    orphan = ev(PID, "d" * 32, body="비밀스러운-본문-문자열")
    r.add("d" * 32, orphan)
    _, cfg, log, conf = setup([])
    d.notify_scan(scan(r, cfg, log, conf), tmp, cmd)
    assert len(sent(out)) == 1 and "비밀스러운-본문-문자열" not in sent(out)[0]


def _run_all():
    names = [n for n in sorted(globals()) if n.startswith("test_")]
    bad = 0
    for n in names:
        try:
            globals()[n]()
            print("PASS", n)
        except Exception as e:                      # noqa: BLE001
            bad += 1
            print("FAIL", n, type(e).__name__, str(e)[:300])
    print("%d/%d 통과" % (len(names) - bad, len(names)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_run_all())
