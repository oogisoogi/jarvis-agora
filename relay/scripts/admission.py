#!/usr/bin/env python3
"""받아들이기 차단(은퇴) 시험 하네스 — 설계 docs/design/key-lifecycle/DESIGN-v3.md §8.

단계(phase) — 같은 로컬 D1 위에서 **코드만 바꿔 가며** 차례로 돈다(`run-admission.py` 가 서버를 갈아 끼운다):
  main    = 지금 코드. 골든 세트를 쌓고 → 차단 전 사진 → 차단(ops/admission-block.py 로) → 차단 뒤 사진 대조 +
            T1·T2·T3·T4·T5·T6⑴⑵⑶·T7·T9·T10·T11·T13 + 차단 스크립트의 경보·중단 경로. 끝에 「최종 사진」을 남긴다.
  mutant  = 판정 경로로 차단이 새는 변이 코드(T8). 최종 사진과 **달라야**(적색) 통과다.
  old     = 옛 코드(2cf9c1e · 앱 층 검사 없음). 트리거가 막아 행 0 이어야 한다(T6⑷·T15).
  race    = 앱 층 검사·멱등 사전 조회를 뺀 지금 코드 = 「검사를 통과한 뒤 차단이 커밋된」 경합 창의 재현(T12).

★서버가 주는 판정으로 서버를 재지 않는다 — 과거 불변(T1)은 서버 사진끼리, 판정 대조(T2·T9)는 파이썬 리듀서로 한다.
★개인키는 작업 폴더에만 있다(저장소 밖).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
RELAY = os.path.dirname(HERE)
ROOT = os.path.dirname(RELAY)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from threeway import Builder, canonical_bytes, http, keygen, python_state, register, send, sign_bytes, write_roster  # noqa: E402
from agora.event import new_id  # noqa: E402

NOW = "2026-09-06T01:00:00Z"
RESIDENT_LIB = os.path.expanduser("~/axdev/agora-resident/.agora/lib")   # 현역 상주 클라이언트 0.1.7
ENV_NO_NODE = {k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"}

CHECKS: list[bool] = []


def record(name, want, got, extra=""):
    ok = got == want
    CHECKS.append(ok)
    print("  %-52s 기대 %-8s 실제 %-8s %s %s" % (name, str(want)[:8], str(got)[:8], "OK" if ok else "★불일치", extra))
    return ok


def d1(sql, persist):
    r = subprocess.run([os.path.join(RELAY, "node_modules/.bin/wrangler"), "d1", "execute", "agora-relay",
                        "--local", "--persist-to", persist, "--json", "--command", sql],
                       cwd=RELAY, capture_output=True, text=True, env=ENV_NO_NODE)
    if r.returncode != 0:
        raise SystemExit("d1 실패: " + (r.stdout + r.stderr)[-400:])
    out = json.loads(r.stdout)
    return [row for part in out for row in (part.get("results") or [])]


def count(sql, persist):
    return d1(sql, persist)[0]["n"]


def ops_block(persist, base, pid, fp, *extra):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "admission-block.py"), "--target", "main",
                        "--local", "--persist-to", persist, "--participant", pid, "--fingerprint", fp,
                        "--relay-url", base, "--blocked-at", "2026-09-29T00:00:00.000Z", "--not-ours", *extra],
                       capture_output=True, text=True, env=ENV_NO_NODE)
    return r.returncode, r.stdout + r.stderr


# ── 사진(스냅숏) ──────────────────────────────────────────────────────────────
def server_rows(base, room):
    items, cur = [], "0"
    while True:
        code, body = http("GET", "%s/rooms/%s/events?limit=200&cursor=%s" % (base, room, cur))
        assert code == 200, (code, body)
        items += body["items"]
        if body["next_cursor"] is None:
            return items
        cur = body["next_cursor"]


def client_state(lib, rows, room, allowed, revoked, operators):
    """참가자 클라이언트의 리듀서(판 = lib)로 계산한 상태. lib=None 이면 이 저장소(0.1.9)."""
    if lib is None:
        return python_state(rows, room, allowed, revoked, operators, NOW)
    code = ("import json,sys\nsys.path.insert(0, sys.argv[1])\nfrom agora import reducer\n"
            "a=json.load(sys.stdin)\nclass S:\n    def fetch(self, **k): return {'items': a['rows'], 'next_cursor': None}\n"
            "c=reducer.collect(store=S(), thread_id=a['room'], allowed_signers_path=a['allowed'], revoked_path=a['revoked'])\n"
            "print(json.dumps(reducer.apply(reducer.order(c), operators=frozenset(a['ops']), now=a['now']), default=str))\n")
    r = subprocess.run([sys.executable, "-c", code, lib], input=json.dumps(
        {"rows": rows, "room": room, "allowed": allowed, "revoked": revoked, "ops": operators, "now": NOW}),
        capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("0.1.7 리듀서 실행 실패: " + r.stderr[-500:])
    return json.loads(r.stdout)


def py_view(st):
    """상태에서 판정 축만 — state_hash · 상태 · 받아들인/격리/stale 목록."""
    return {"state": st.get("state"), "state_hash": st.get("state_hash"),
            "events": sorted(e.get("node_id") for e in st.get("events") or []),
            "quarantined": sorted((q.get("node_id"), q.get("reason")) for q in st.get("quarantined") or []),
            "stale": sorted((s.get("node_id"), s.get("reason")) for s in st.get("stale") or [])}


def snap(base, rooms, roster_files, with_clients=True):
    s = {"rooms": {}, "files": {}}
    for name, room in rooms.items():
        code, st = http("GET", base + "/rooms/" + room)
        assert code == 200, (name, code, st)
        st.pop("derived_at", None)
        items = server_rows(base, room)
        rows = [{"node_id": i["event_id"], "created_at": i["created_at"], "body": i["body"]} for i in items]
        s["rooms"][name] = {
            "status": st,
            "events": [{k: i[k] for k in ("event_id", "created_at", "valid", "quarantined", "stale", "reason")}
                       for i in items],
        }
        if with_clients:
            allowed, revoked, ops = roster_files
            s["rooms"][name]["py019"] = py_view(client_state(None, rows, room, allowed, revoked, ops))
            if os.path.isdir(RESIDENT_LIB):
                s["rooms"][name]["py017"] = py_view(client_state(RESIDENT_LIB, rows, room, allowed, revoked, ops))
    for f in ("allowed_signers", "revoked_keys", "operators"):
        s["files"][f] = http("GET", base + "/participants/" + f)[1]
    code, cp = http("GET", base + "/participants/checkpoint")
    s["files"]["checkpoint"] = {k: cp.get(k) for k in ("checkpoint", "signer", "signed_at", "current", "stale")}
    return s


def builder_from_server(base, room, w):
    """서버의 사슬을 파이썬 대조군에 옮겨 담은 Builder — 다음 글의 prev·expected 를 **파이썬이** 계산한다."""
    b = Builder(room, w["dir"], w["allowed"], w["revoked"], w["ops"], NOW)
    b.rows = [{"node_id": i["event_id"], "created_at": i["created_at"], "body": i["body"]}
              for i in server_rows(base, room)]
    return b


def post_next(base, room, category, w, signer, kind, payload):
    b = builder_from_server(base, room, w)
    ev, sig = b.make(signer, kind, payload)
    return send(base, room, category, "", ev, sig, False), ev, sig


def checkpoint_post(base, signer, w, signed_at):
    code, cp = http("GET", base + "/participants/checkpoint")
    msg = {"checkpoint": cp["current"], "purpose": "agora-roster-checkpoint-v1", "signed_at": signed_at,
           "signer": signer["id"]}
    sig = sign_bytes(signer["key"], canonical_bytes(msg), w["dir"])
    return http("POST", base + "/participants/checkpoint",
                {"checkpoint": cp["current"], "signer": signer["id"], "signed_at": signed_at, "signature": sig})


def detail(body, key):
    return ((body or {}).get("detail") or {}).get(key) if isinstance(body, dict) else None


# ── 단계 main ────────────────────────────────────────────────────────────────
def phase_main(base, persist, wdir):
    K = {n: keygen(wdir, n) for n in ("alice", "bob", "carol", "op", "op2", "ghost", "ghost2", "dave")}
    members = [K[n] for n in ("alice", "bob", "carol", "op", "op2")]
    for s in members:
        code, _ = register(base, s, wdir)
        assert code in (200, 201), (s["id"], code)
    d1("UPDATE participants SET is_operator=1 WHERE participant_id IN ('op','op2')", persist)
    allowed, revoked, _ops = write_roster(wdir, members, ["op", "op2"])
    w = {"dir": wdir, "allowed": allowed, "revoked": revoked, "ops": ["op", "op2"]}
    env = {"env": {"os": "macOS", "app": "agora"}, "symptom": "멈춘다", "repro_steps": ["실행한다", "멈춘다"]}

    print("== 골든 세트 ==")
    rooms = {}
    posted = {}
    ids = {}

    def room(name, category, title, seq):
        t = new_id()
        rooms[name] = t
        b = Builder(t, wdir, allowed, revoked, w["ops"], NOW)
        for signer, kind, payload, label in seq(b, t):
            ev, sig = b.add(K[signer], kind, payload)
            code, body = send(base, t, category, title, ev, sig, kind == "genesis")
            v = (body.get("verdict") or {}).get("reducer") if isinstance(body, dict) else None
            print("  %-4s %-22s %-8s -> %s %s" % (name, label, signer, code, v))
            assert code == 201, (name, label, code, body)
            posted[name + ":" + label] = (ev, sig)
            ids[name + ":" + label] = body["event_id"]          # 적재 때 받은 값 — 뒤 대조의 기대값(서버 목록에서 뽑지 않는다)

    room("R1", "debate", "은퇴 전 토론", lambda b, t: [
        ("alice", "genesis", {"type": "debate", "title": "은퇴 전 토론", "body": "쟁점"}, "genesis"),
        ("bob", "post", {"round": 0, "body": "밥 r0"}, "bob r0"),
        ("alice", "post", {"round": 0, "body": "앨리스 r0"}, "alice r0")])
    room("R2", "problem", "운영자 abort 방", lambda b, t: [
        ("alice", "genesis", {"type": "problem", "title": "운영자 abort 방", "body": "본문", "envelope": env}, "genesis"),
        ("bob", "post", {"round": 0, "body": "답 후보"}, "bob post"),
        ("op", "abort", {"reason": "시험 — 운영자 중단"}, "op abort")])
    r3 = {}

    def r3seq(b, t):
        yield "bob", "genesis", {"type": "debate", "title": "답글 방", "body": "쟁점"}, "genesis"
        yield "alice", "post", {"round": 0, "body": "앨리스 글"}, "alice post"
        r3["alice"] = b.posted[-1][0]
        yield "bob", "post", {"round": 0, "body": "앨리스 글에 답",
                              "refs": [{"thread_id": t, "message_id": r3["alice"]["message_id"], "why": "reply"}]}, "bob reply"
    room("R3", "debate", "답글 방", r3seq)
    room("R4", "debate", "앨리스가 아직 말 안 한 방", lambda b, t: [
        ("bob", "genesis", {"type": "debate", "title": "앨리스가 아직 말 안 한 방", "body": "쟁점"}, "genesis")])
    code, body = checkpoint_post(base, K["op2"], w, "2026-09-29T00:00:00.000Z")
    record("측정 전제: op2 체크포인트 보관 = 201", 201, code)

    code, home0 = http("GET", base + "/home?participant=alice")
    record("측정 전제: 차단 전 /home(alice) 답글 있음", True, bool(home0.get("replies")))
    record("측정 전제: 차단 전 /home(alice) speak_due 에 R4", True,
           rooms["R4"] in [r["room_id"] for r in home0.get("speak_due") or []])
    rate0 = count("SELECT COALESCE(SUM(count),0) AS n FROM rate_windows WHERE bucket='pid:alice'", persist)

    print("== 차단 전 사진 ==")
    before = snap(base, rooms, (allowed, revoked, w["ops"]))
    record("측정 전제: 0.1.7 상주 리듀서로도 계산됐다", True, all("py017" in v for v in before["rooms"].values()))
    record("측정 전제: R2 = 운영자 abort 로 닫힘", "closed", before["rooms"]["R2"]["status"]["state"],
           before["rooms"]["R2"]["status"].get("close_reason"))

    print("== 차단 스크립트(ops/admission-block.py · --local) ==")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "admission-block.py"), "--target", "main", "--local",
                        "--persist-to", persist, "--check-schema"], capture_output=True, text=True, env=ENV_NO_NODE)
    record("스크립트: --check-schema(표 1·트리거 4) = 0", 0, r.returncode)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "admission-block.py"), "--target", "main", "--local",
                        "--persist-to", persist, "--participant", "jarvis-jk1gn50iw7",
                        "--fingerprint", "SHA256:" + "A" * 43, "--execute"], capture_output=True, text=True, env=ENV_NO_NODE)
    # ★rc 만 보지 않는다 — 뒤의 다른 중단도 rc 3 이라, 그 검사를 지워도 초록이 된다(impl-r2 Fable 3). 사유 문자열까지.
    record("스크립트: 우리 id + 다른 지문(오타) = 중단(3) · 사유 = 신원 대조", (3, True),
           (r.returncode, "우리 신원" in r.stdout), r.stdout.strip().splitlines()[-1][:50])
    r = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "admission-block.py"), "--target", "trial", "--local",
                        "--participant", "not-a-test-id", "--fingerprint", "SHA256:" + "B" * 43, "--shape", "registered",
                        "--not-ours", "--execute"], capture_output=True, text=True, env=ENV_NO_NODE)
    record("스크립트: 시험 릴레이 registered 인데 adm-t 머리 아님 = 중단(3) · 사유 = 머리", (3, True),
           (r.returncode, "adm-t" in r.stdout), r.stdout.strip().splitlines()[-1][:50])
    r = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "admission-block.py"), "--target", "main", "--local",
                        "--persist-to", persist, "--participant", "alice\n", "--fingerprint", "SHA256:" + "A" * 43,
                        "--not-ours"], capture_output=True, text=True, env=ENV_NO_NODE)
    record("스크립트: id 끝 개행 = 중단(3) · 사유 = 형식", (3, True), (r.returncode, "participant 형식" in r.stdout))
    rc, out = ops_block(persist, base, "bobalias", K["bob"]["fingerprint"], "--execute")
    record("스크립트: 지문이 다른 이름에 붙음 = 중단(3)", 3, rc, out.strip().splitlines()[-1][:60])
    rc, out = ops_block(persist, base, "carol", K["bob"]["fingerprint"], "--execute")
    record("스크립트: id 행 지문 불일치 = 중단(3)", 3, rc, out.strip().splitlines()[-1][:60])
    rc, out = ops_block(persist, base, "alice", K["alice"]["fingerprint"])
    record("스크립트: --execute 없으면 계획만(10) · 행 0", (10, 0),
           (rc, count("SELECT COUNT(*) AS n FROM admission_blocks", persist)))
    rc, out = ops_block(persist, base, "alice", K["alice"]["fingerprint"], "--execute")
    record("스크립트: alice 차단 = 0 · 명부 표·세 파일 동일", 0, rc, out.strip().splitlines()[-2][:70])
    rc, out = ops_block(persist, base, "op", K["op"]["fingerprint"], "--execute")
    record("스크립트: 운영자 op 차단(op2 남음) = 0", 0, rc)
    rc, out = ops_block(persist, base, "op2", K["op2"]["fingerprint"])
    record("스크립트: 마지막 현역 운영자 = 중단(3)", 3, rc, out.strip().splitlines()[-1][:60])
    rc, out = ops_block(persist, base, "alice", K["alice"]["fingerprint"], "--execute")
    record("스크립트: 이미 차단 = 11(쓰지 않음 · 대조를 대신하지 않음)", 11, rc, out.strip().splitlines()[-1][:40])
    # 행 없는 id(시험 릴레이 모양 · --shape absent)
    rc, out = ops_block(persist, base, "ghost", K["ghost"]["fingerprint"], "--shape", "absent", "--execute")
    record("스크립트: 행 없는 id 차단(--shape absent) = 0", 0, rc)
    rc, out = ops_block(persist, base, "bob", K["bob"]["fingerprint"], "--shape", "absent")
    record("스크립트: absent 기대인데 id 행 있음 = 중단(3)", 3, rc, out.strip().splitlines()[-1][:60])

    print("== 차단 뒤 사진 · 과거 불변 ==")
    after = snap(base, rooms, (allowed, revoked, w["ops"]))
    for name in rooms:
        b, a = before["rooms"][name], after["rooms"][name]
        record("T1 %s 서버 상태(state_hash 포함) 동일" % name, True, b["status"] == a["status"])
        record("T1 %s 이벤트 valid·격리·stale 동일" % name, True, b["events"] == a["events"])
        record("T9 %s 0.1.9 리듀서 판정 동일" % name, True, b["py019"] == a["py019"])
        record("T9 %s 0.1.7 리듀서 판정 동일" % name, True, b.get("py017") == a.get("py017"))
        record("T2 %s py↔ts state_hash 일치" % name, a["py019"]["state_hash"], a["status"].get("state_hash"))
    record("T3 명부 세 파일 바이트 동일", True, before["files"] == after["files"])

    print("== 새 쓰기 ==")
    n_alice = count("SELECT COUNT(*) AS n FROM events WHERE from_id='alice'", persist)
    (code, body), _, _ = post_next(base, rooms["R1"], "debate", w, K["alice"], "post", {"round": 0, "body": "은퇴 뒤"})
    record("T4 차단 id 새 글 = 401", 401, code)
    record("T4 code 4 · why=retired", (4, "retired"), (body.get("code"), detail(body, "why")))
    record("T4 원장 행 0(alice 글 수 불변)", n_alice, count("SELECT COUNT(*) AS n FROM events WHERE from_id='alice'", persist))
    record("T4 거절이 속도 예산을 안 태움(pid:alice)", rate0,
           count("SELECT COALESCE(SUM(count),0) AS n FROM rate_windows WHERE bucket='pid:alice'", persist))
    ev, sig = posted["R1:alice r0"]
    code, body = send(base, rooms["R1"], "debate", "", ev, sig, False)
    code0 = ids["R1:alice r0"]
    record("T5 차단 전 적재된 같은 글 재전송 = 200 같은 event_id", (200, code0), (code, body.get("event_id")))
    ev2 = json.loads(json.dumps(ev))
    ev2["payload"]["body"] = "같은 message_id 다른 내용"
    sig2 = sign_bytes(K["alice"]["key"], canonical_bytes(ev2), wdir)
    code, body = send(base, rooms["R1"], "debate", "", ev2, sig2, False)
    record("T5 같은 message_id 다른 내용 = 422(불변)", 422, code)

    n_p = count("SELECT COUNT(*) AS n FROM participants", persist)
    code, body = register(base, K["alice"], wdir)
    record("T6⑴ 차단 id·같은 키 재등록 = 403 code 5", (403, 5), (code, body.get("code")))
    g2 = dict(K["ghost2"], id="ghost")
    code, body = register(base, g2, wdir)
    record("T6⑵ 행 없음 + 차단 id + 새 키 = 403", (403, 5), (code, body.get("code")))
    thief = dict(K["ghost"], id="thief")
    code, body = register(base, thief, wdir)
    record("T6⑶ 행 없음 + 차단 지문 + 다른 이름 = 403", (403, 5), (code, body.get("code")))
    record("T6 새 행 0", n_p, count("SELECT COUNT(*) AS n FROM participants", persist))

    (code, body), _, _ = post_next(base, rooms["R1"], "debate", w, K["carol"], "post", {"round": 0, "body": "캐럴 r0"})
    record("T7·T13 R1(차단 id 가 쓴 방) 제3자 글 = 201 accepted",
           (201, "accepted"), (code, (body.get("verdict") or {}).get("reducer")))
    (code, body), _, _ = post_next(base, rooms["R3"], "debate", w, K["carol"], "post", {"round": 0, "body": "캐럴"})
    record("T13 R3(차단 id 글 + 답글) 제3자 글 = 201 accepted",
           (201, "accepted"), (code, (body.get("verdict") or {}).get("reducer")))
    code, _ = register(base, K["dave"], wdir)
    record("T7 차단 안 한 새 등록 = 201", 201, code)

    code, body = checkpoint_post(base, K["op"], w, "2026-09-29T01:00:00.000Z")
    record("T10 차단된 운영자 체크포인트 = 403 why=retired", (403, "retired"), (code, detail(body, "why")))
    code, body = checkpoint_post(base, K["op2"], w, "2026-09-29T01:00:01.000Z")
    record("T10 대조군 op2 체크포인트 = 201", 201, code)

    code, h = http("GET", base + "/home?participant=alice")
    record("T11 notify[0].kind = retired", "retired", ((h.get("notify") or [{}])[0]).get("kind"))
    record("T11 speak_due = [] · replies = []", ([], []), (h.get("speak_due"), h.get("replies")))
    code, hf = http("GET", base + "/home?participant=" + quote(K["alice"]["fingerprint"], safe=""))
    record("T11 지문으로 물어도 retired", "retired", ((hf.get("notify") or [{}])[0]).get("kind"))
    code, hb = http("GET", base + "/home?participant=bob")
    record("T11 대조군 bob notify 에 retired 없음", False, any(n.get("kind") == "retired" for n in hb.get("notify") or []))

    # ★명부를 바꾸는 시험이라 과거 불변(T1·T3) 대조 **뒤**, 최종 사진 **앞**에 둔다.
    # [impl codex HIGH] 사전 확인과 INSERT 사이에 같은 키로 다른 이름이 등록되면 조건부 INSERT 가 0행 → 중단 · 행 0
    g3 = keygen(wdir, "ghost3")
    late = ("INSERT INTO participants (participant_id, display_name, key_type, key_b64, fingerprint, is_operator,"
            " revoked_at, created_at) VALUES ('squatter','s','ssh-ed25519','AAAA','%s',0,NULL,'t')" % g3["fingerprint"])
    rc, out = ops_block(persist, base, "ghost3", g3["fingerprint"], "--shape", "absent", "--execute",
                        "--test-interpose-sql", late)
    record("스크립트: 사전 확인 뒤 끼어든 등록 = 중단(3) · 0행 사유", (3, True), (rc, "0행" in out),
           out.strip().splitlines()[-1][:50])
    record("스크립트: 끼어든 등록 뒤 차단 행 0", 0,
           count("SELECT COUNT(*) AS n FROM admission_blocks WHERE participant_id='ghost3'", persist))
    # [impl-r3 Fable 2] 원자 조건의 나머지 갈래 — registered(대상 id 의 지문 변경 · 대상 폐기) · absent(같은 id 선점)
    sql_p = ("INSERT INTO participants (participant_id, display_name, key_type, key_b64, fingerprint, is_operator,"
             " revoked_at, created_at) VALUES ('%s','x','ssh-ed25519','AAAA','%s',0,NULL,'t')")
    for n in ("reg1", "reg2"):
        code, _ = register(base, keygen(wdir, n), wdir)
        assert code == 201, (n, code)
    k1, k2, g5 = keygen(wdir, "reg1"), keygen(wdir, "reg2"), keygen(wdir, "ghost5")
    for label, pid, fp, shape, late in (
            # (「같은 지문의 다른 이름」은 participants.fingerprint UNIQUE 라 DB 에 존재할 수 없다 — 그 조건절은 이중 방어)
            ("registered + 대상 id 의 지문이 바뀜", "reg1", k1["fingerprint"], "registered",
             "UPDATE participants SET fingerprint='SHA256:%s' WHERE participant_id='reg1'" % ("E" * 43)),
            ("registered + 대상 폐기", "reg2", k2["fingerprint"], "registered",
             "UPDATE participants SET revoked_at='t' WHERE participant_id='reg2'"),
            ("absent + 같은 id 선점", "ghost5", g5["fingerprint"], "absent", sql_p % ("ghost5", "SHA256:" + "D" * 43))):
        rc, out = ops_block(persist, base, pid, fp, "--shape", shape, "--execute", "--test-interpose-sql", late)
        record("스크립트: 끼어들기(%s) = 중단(3) · 0행" % label, (3, True, 0),
               (rc, "0행" in out, count("SELECT COUNT(*) AS n FROM admission_blocks WHERE participant_id='%s'" % pid, persist)))
    # [impl codex MED] 동시 등록(새 행)이 있으면 명부 파일 차이를 성공으로 덮지 않는다 = 대조 미완(5)
    g4 = keygen(wdir, "ghost4")
    late2 = ("INSERT INTO participants (participant_id, display_name, key_type, key_b64, fingerprint, is_operator,"
             " revoked_at, created_at) VALUES ('newcomer','n','ssh-ed25519','%s','SHA256:%s',0,NULL,'t')"
             % (g4["pub"].split()[1], "C" * 43))
    rc, out = ops_block(persist, base, "ghost4", g4["fingerprint"], "--shape", "absent", "--execute",
                        "--test-interpose-sql", late2)
    record("스크립트: 동시 등록으로 명부 파일이 바뀜 = 대조 미완(5)", 5, rc, out.strip().splitlines()[-1][:50])
    print("== 최종 사진(뒤 단계의 기준) ==")
    final = snap(base, rooms, (allowed, revoked, w["ops"]), with_clients=False)
    state = {"rooms": rooms, "final": final, "keys": {k: v for k, v in K.items()},
             "alice_r1": posted["R1:alice r0"], "alice_r1_id": code0, "w": w}
    json.dump(state, open(os.path.join(wdir, "admission-state.json"), "w"), ensure_ascii=False)


def load(wdir):
    return json.load(open(os.path.join(wdir, "admission-state.json"), encoding="utf-8"))


# ── 단계 mutant(T8) ──────────────────────────────────────────────────────────
def phase_mutant(base, persist, wdir, label):
    st = load(wdir)
    now = snap(base, st["rooms"], None, with_clients=False)
    diffs = [n for n in st["rooms"] if now["rooms"][n] != st["final"]["rooms"][n]]
    files = now["files"] != st["final"]["files"]
    red = bool(diffs) or files
    print("  변이 %s: 방 차이 %s · 명부 파일 차이 %s" % (label, diffs, files))
    if label.startswith("M-0"):
        # 대조군(변이 0 사본) — 같은 시점에 차이가 **없어야** 뒤의 적색이 변이 때문임을 말할 수 있다(impl-r1 Fable 5).
        record("T8 대조군(변이 없음) = 최종 사진과 동일", False, red)
    else:
        record("T8 %s 가 T1/T3 을 적색으로 만든다" % label, True, red)


# ── 단계 old(T6⑷·T15) ───────────────────────────────────────────────────────
def phase_old(base, persist, wdir):
    st = load(wdir)
    K, w, rooms = st["keys"], st["w"], st["rooms"]
    n_alice = count("SELECT COUNT(*) AS n FROM events WHERE from_id='alice'", persist)
    (code, _), _, _ = post_next(base, rooms["R1"], "debate", w, K["alice"], "post", {"round": 0, "body": "옛 코드"})
    record("T15 옛 코드: 차단 id 새 글 = 실패(500)", 500, code)
    record("T15 옛 코드: 원장 행 0", n_alice, count("SELECT COUNT(*) AS n FROM events WHERE from_id='alice'", persist))
    (code, body), _, _ = post_next(base, rooms["R1"], "debate", w, K["dave"], "post", {"round": 0, "body": "데이브"})
    record("T15 옛 코드: 다른 id 정상 = 201", 201, code)
    n_p = count("SELECT COUNT(*) AS n FROM participants", persist)
    code, _ = register(base, dict(K["ghost2"], id="ghost"), wdir)
    record("T6⑷ 옛 코드: 행 없음 + 차단 id + 새 키 → 실패", True, code >= 500)
    code, _ = register(base, dict(K["ghost"], id="thief"), wdir)
    record("T6⑷ 옛 코드: 차단 지문 + 다른 이름 → 실패", True, code >= 500)
    record("T6⑷ 옛 코드: 새 행 0", n_p, count("SELECT COUNT(*) AS n FROM participants", persist))


# ── 단계 race(T12) ──────────────────────────────────────────────────────────
def phase_race(base, persist, wdir):
    st = load(wdir)
    K, w, rooms = st["keys"], st["w"], st["rooms"]
    n_alice = count("SELECT COUNT(*) AS n FROM events WHERE from_id='alice'", persist)
    (code, body), _, _ = post_next(base, rooms["R1"], "debate", w, K["alice"], "post", {"round": 0, "body": "경합"})
    record("T12⑴ 검사 통과 뒤 차단 → 트리거 → 401(500 아님)", (401, "retired"), (code, detail(body, "why")))
    record("T12⑴ 원장 행 0", n_alice, count("SELECT COUNT(*) AS n FROM events WHERE from_id='alice'", persist))
    ev, sig = st["alice_r1"]
    code, body = send(base, rooms["R1"], "debate", "", ev, sig, False)
    record("T12⑵ 같은 글 두 번째 요청(트리거 오류 먼저) = 200 같은 event_id",
           (200, st["alice_r1_id"]), (code, body.get("event_id") if isinstance(body, dict) else None))
    ev2 = json.loads(json.dumps(ev))
    ev2["payload"]["body"] = "경합 중 다른 내용"
    code, body = send(base, rooms["R1"], "debate", "", ev2, sign_bytes(K["alice"]["key"], canonical_bytes(ev2), wdir), False)
    record("T12⑶ 같은 message_id 다른 내용 = 422", 422, code)
    n_p = count("SELECT COUNT(*) AS n FROM participants", persist)
    code, body = register(base, dict(K["ghost2"], id="ghost"), wdir)
    record("T12 등록 경합: 트리거 → 403(500 아님)", (403, "retired"), (code, detail(body, "why")))
    code, body = register(base, dict(K["ghost"], id="thief"), wdir)
    record("T12 등록 경합: 차단 지문 → 403", (403, "retired"), (code, detail(body, "why")))
    record("T12 등록 경합: 새 행 0", n_p, count("SELECT COUNT(*) AS n FROM participants", persist))
    code, body = checkpoint_post(base, K["op"], w, "2026-09-29T02:00:00.000Z")
    record("T12 체크포인트 경합(충돌 키 UPSERT · BEFORE INSERT 트리거가 먼저): 403", (403, "retired"), (code, detail(body, "why")))


# ── 단계 upgrade(T14 서버 층) ─────────────────────────────────────────────────
def phase_upgrade(base, persist, tw, when):
    # ★방 목록은 **원장에서** 뽑는다 — /rooms 는 캐시라 3자 대조의 「캐시 삭제 → 자가치유」 시험 뒤엔 한 방만 남는다.
    ledger_rooms = d1("SELECT thread_id, MAX(CASE WHEN is_genesis = 1 THEN title END) AS title FROM events"
                      " GROUP BY thread_id", persist)
    rooms = {r["thread_id"]: r["thread_id"] for r in ledger_rooms}
    shot = snap(base, rooms, None, with_clients=False)
    path = os.path.join(tw, "upgrade-before.json")
    if when == "before":
        record("측정 전제: 옛 코드 + 0001 DB 에 방이 있다", True, len(rooms) >= 5, "%d개" % len(rooms))
        json.dump({"shot": shot, "titles": {r["thread_id"]: r["title"] for r in ledger_rooms}},
                  open(path, "w"), ensure_ascii=False)
        return
    prev = json.load(open(path, encoding="utf-8"))
    objs = [r["name"] for r in d1("SELECT name FROM sqlite_master WHERE name LIKE '%admission%' AND type IN ('table','trigger')", persist)]
    record("T14 0002 적용 뒤 표 1·트리거 4", 5, len(objs))
    same = [n for n in prev["shot"]["rooms"] if prev["shot"]["rooms"][n] == shot["rooms"].get(n)]
    record("T14 업그레이드·코드 교체 뒤 전 방 상태·이벤트 판정 동일", len(prev["shot"]["rooms"]), len(same))
    record("T14 명부 세 파일·체크포인트 동일", True, prev["shot"]["files"] == shot["files"])
    w = {"dir": tw, "allowed": os.path.join(tw, "allowed_signers"), "revoked": os.path.join(tw, "revoked_keys"),
         "ops": ["operator"]}
    bob = keygen(tw, "bob")
    target = [rid for rid, t in prev["titles"].items() if t == "일반 토론"]
    record("측정 전제: 열린 일반 토론방이 있다", 1, len(target))
    (code, body), _, _ = post_next(base, target[0], "debate", w, bob, "post", {"round": 0, "body": "업그레이드 뒤 새 글"})
    record("T14 기존 참가자 새 글 = 201 accepted", (201, "accepted"), (code, (body.get("verdict") or {}).get("reducer")))
    code, _ = register(base, keygen(tw, "upgnew"), tw)
    record("T14 새 등록 = 201", 201, code)
    code, h = http("GET", base + "/home?participant=bob")
    record("T14 /home = 200 · retired 없음", (200, False),
           (code, any(n.get("kind") == "retired" for n in (h.get("notify") or []))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--persist", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--phase", required=True, choices=("main", "mutant", "old", "race", "upgrade-before", "upgrade-after"))
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    os.chmod(a.workdir, 0o700)
    print("\n##### 단계 %s %s #####" % (a.phase, a.label))
    try:
        _dispatch(a)
    except BaseException as e:                  # noqa: BLE001 — 하네스 자체의 사고는 검사 불일치(1)와 가른다
        import traceback
        traceback.print_exc()
        print("== 단계 %s %s: 하네스 오류(%s) — 검사 판정 아님 ==" % (a.phase, a.label, type(e).__name__))
        return 2
    ok = all(CHECKS)
    print("== 단계 %s %s: %s (%d/%d) ==" % (a.phase, a.label, "PASS" if ok else "FAIL", sum(CHECKS), len(CHECKS)))
    return 0 if ok else 1


def _dispatch(a):
    {"main": lambda: phase_main(a.base, a.persist, a.workdir),
     "mutant": lambda: phase_mutant(a.base, a.persist, a.workdir, a.label),
     "old": lambda: phase_old(a.base, a.persist, a.workdir),
     "race": lambda: phase_race(a.base, a.persist, a.workdir),
     "upgrade-before": lambda: phase_upgrade(a.base, a.persist, a.workdir, "before"),
     "upgrade-after": lambda: phase_upgrade(a.base, a.persist, a.workdir, "after")}[a.phase]()


if __name__ == "__main__":
    sys.exit(main())
