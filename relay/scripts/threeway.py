#!/usr/bin/env python3
"""3자 대조 하네스 — 파이썬 리듀서 == 서버 파생.

무엇을 재는가(docs/RELAY.md §9):
  같은 이벤트열에 대해 ⑴파이썬 `agora.reducer` 의 상태와 ⑵릴레이 `GET /rooms/:id` 의 파생이
  **전 칸 일치**하는가. `state_hash` 를 축에 넣는다 — 개별 칸만 대조하면 **사슬 머리**의 차이를 못 본다.

★대조가 갈리면 **TS 쪽이 틀린 것**이다. `agora/` 는 이 티켓에서 읽기 전용이다.
★이 파일은 `agora/` 를 **읽어서 쓰기만** 한다(수정 0). 서명은 실제 `ssh-keygen -Y sign` 으로 만든다.

쓰는 법:
  python3 relay/scripts/threeway.py --base http://127.0.0.1:8787 --workdir /tmp/agora-3way
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from agora import reducer, roster  # noqa: E402
from agora.event import canonical_bytes, new_id, render_post  # noqa: E402

NS = "jarvis-agora@godmeyou.kr"


# ── 서명 도구(테스트 전용) ───────────────────────────────────────────────────
def keygen(workdir: str, name: str) -> dict:
    """테스트용 키 한 벌. ★개인키는 작업 폴더에만 있고 저장소에 들어가지 않는다."""
    path = os.path.join(workdir, name)
    if not os.path.exists(path):
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", name, "-f", path],
                       check=True, capture_output=True)
    pub = open(path + ".pub", encoding="utf-8").read().strip()
    fp = subprocess.run(["ssh-keygen", "-l", "-f", path + ".pub"],
                        check=True, capture_output=True, text=True).stdout.split()[1]
    return {"id": name, "key": path, "pub": pub, "fingerprint": fp}


_SIGN_SEQ = [0]


def sign_bytes(key_path: str, raw: bytes, workdir: str) -> str:
    """★`ssh-keygen -Y sign` 은 `.sig` 가 이미 있으면 **덮어쓰기 프롬프트**를 띄우고,
    tty 가 없으면 **rc 0 인 채 옛 서명을 그대로 남긴다**(2026-09-05 실측).
    그러면 하네스가 앞 사람의 서명을 재사용하고, 서버는 정직하게 BAD 를 낸다 —
    ⇒ 검사기가 고장난 것을 대상이 틀린 것으로 읽게 된다. 그래서 **매번 새 파일**에 쓰고,
      **쓰였는지 실측**한 뒤에만 돌려준다."""
    _SIGN_SEQ[0] += 1
    blob = os.path.join(workdir, "sign-%06d.blob" % _SIGN_SEQ[0])
    sig_path = blob + ".sig"
    for path in (blob, sig_path):
        if os.path.exists(path):
            os.remove(path)
    with open(blob, "wb") as fh:
        fh.write(raw)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-n", NS, "-f", key_path, blob],
                   check=True, capture_output=True, stdin=subprocess.DEVNULL)
    if not os.path.exists(sig_path):
        raise SystemExit("서명 파일이 만들어지지 않았다: " + sig_path)
    with open(sig_path, encoding="utf-8") as fh:
        sig = fh.read()
    os.remove(blob)
    os.remove(sig_path)
    return sig


# ── 파이썬 리듀서(대조군) ────────────────────────────────────────────────────
class MemStore:
    """`agora.reducer.collect` 가 먹는 최소 store — 이 파일 안에서만 산다."""

    def __init__(self, rows):
        self.rows = rows

    def fetch(self, *, thread_id=None, number=None, cursor=None, limit=100):
        return {"items": list(self.rows), "next_cursor": None}


def python_state(rows, thread_id, allowed_signers_path, revoked_path, operators, now):
    collected = reducer.collect(store=MemStore(rows), thread_id=thread_id,
                                allowed_signers_path=allowed_signers_path,
                                revoked_path=revoked_path)
    ordered = reducer.order(collected)
    return reducer.apply(ordered, operators=frozenset(operators), now=now)


# ── HTTP ────────────────────────────────────────────────────────────────────
def http(method: str, url: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"content-type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body.strip().startswith(("{", "[")) else body)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, body


# ── 이벤트 조립 ──────────────────────────────────────────────────────────────
class Builder:
    """이벤트를 하나씩 쌓으면서 prev·expected_state 를 **파이썬 리듀서로** 계산한다.

    ★서버가 주는 값을 쓰지 않는다. 그러면 대조가 자기 자신을 재는 것이 된다.
    """

    def __init__(self, thread_id, workdir, allowed_path, revoked_path, operators, now):
        self.thread_id = thread_id
        self.workdir = workdir
        self.allowed_path = allowed_path
        self.revoked_path = revoked_path
        self.operators = operators
        self.now = now
        self.rows = []          # 파이썬 리듀서용(도착 순서 = created_at, node_id)
        self.posted = []        # 서버로 보낼 것

    def state(self):
        return python_state(self.rows, self.thread_id, self.allowed_path,
                            self.revoked_path, self.operators, self.now)

    def head_and_hash(self):
        st = self.state()
        if st.get("state") is None:
            return "genesis", ""
        return st["head"], st["state_hash"]

    def make(self, signer, kind, payload, *, prev=None, expected=None, roster_hash=None,
             scrub_rules="test", ts="2026-09-06T00:00:00Z"):
        if prev is None or expected is None:
            h, sh = self.head_and_hash()
            prev = h if prev is None else prev
            expected = sh if expected is None else expected
        ev = {
            "v": 1, "kind": kind, "thread_id": self.thread_id, "message_id": new_id(),
            "prev": prev, "expected_state": expected, "from": signer["id"],
            "roster": roster_hash or "0" * 64,
            "scrub": {"rules": scrub_rules, "blocked": 0, "redacted": 0},
            "ts": ts, "payload": payload,
        }
        raw = canonical_bytes(ev)
        sig = sign_bytes(signer["key"], raw, self.workdir)
        return ev, sig

    def add(self, signer, kind, payload, **kw):
        """만들어서 로컬 대조군에도 넣는다(서버 전송은 `send` 가 한다)."""
        ev, sig = self.make(signer, kind, payload, **kw)
        idx = len(self.rows) + 1
        row = {
            "node_id": "ev_%016d" % idx,
            "created_at": "2026-09-06T00:00:%02d.000Z" % idx,
            "body": render_post(ev, sig),
        }
        self.rows.append(row)
        self.posted.append((ev, sig))
        return ev, sig


def register(base, signer, workdir):
    payload_for_sig = {
        "display_name": signer["id"], "fingerprint": signer["fingerprint"],
        "participant_id": signer["id"], "public_key": signer["pub"],
        "purpose": "agora-register-v1",
    }
    sig = sign_bytes(signer["key"], canonical_bytes(payload_for_sig), workdir)
    return http("POST", base + "/register", {
        "participant_id": signer["id"], "display_name": signer["id"],
        "public_key": signer["pub"], "fingerprint": signer["fingerprint"], "signature": sig,
    })


def send(base, thread_id, category, title, ev, sig, is_genesis):
    return http("POST", base + "/events", {
        "thread_id": thread_id, "category": category, "title": title,
        "body": render_post(ev, sig), "is_genesis": is_genesis,
    })


def write_roster(workdir, signers, operators):
    allowed = os.path.join(workdir, "allowed_signers")
    revoked = os.path.join(workdir, "revoked_keys")
    ops = os.path.join(workdir, "operators")
    with open(allowed, "w", encoding="utf-8") as fh:
        for s in signers:
            fh.write("%s %s\n" % (s["id"], " ".join(s["pub"].split()[:2])))
    with open(revoked, "w", encoding="utf-8") as fh:
        fh.write("# 폐기 없음(빈 목록임을 명시)\n")
    with open(ops, "w", encoding="utf-8") as fh:
        for o in operators:
            fh.write(o + "\n")
    return allowed, revoked, ops


COMPARE_FIELDS = ["state", "state_hash", "type", "round", "chair", "requester",
                  "close_reason", "head"]


def compare(py, srv):
    rows = []
    for f in COMPARE_FIELDS:
        a = py.get(f)
        b = srv.get(f)
        if f == "head":
            b = srv.get("head", a)   # 서버는 head 를 노출하지 않는다 — state_hash 가 그것을 포함한다
        rows.append((f, a, b, a == b))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--workdir", default="/tmp/agora-3way")
    args = ap.parse_args()
    os.makedirs(args.workdir, exist_ok=True)
    os.chmod(args.workdir, 0o700)

    alice = keygen(args.workdir, "alice")
    bob = keygen(args.workdir, "bob")
    op = keygen(args.workdir, "operator")
    allowed, revoked, ops = write_roster(args.workdir, [alice, bob, op], [op["id"]])
    now = "2026-09-06T01:00:00Z"

    print("== 0. 등록(소유 증명 서명 포함) ==")
    for s in (alice, bob, op):
        code, body = register(args.base, s, args.workdir)
        print("  %-9s -> %s %s" % (s["id"], code, body.get("status") if isinstance(body, dict) else body))
    # 멱등 확인
    code, body = register(args.base, alice, args.workdir)
    print("  재등록(멱등)   -> %s %s" % (code, body.get("status") if isinstance(body, dict) else body))

    results = []

    # ── 세트 1: problem 정상 진행 ──────────────────────────────────────────
    print("\n== 세트 1: problem 정상(genesis → post → answer_selected → close) ==")
    t1 = new_id()
    b1 = Builder(t1, args.workdir, allowed, revoked, [op["id"]], now)
    env = {"env": {"os": "macOS", "app": "agora"}, "symptom": "설치가 멈춘다",
           "repro_steps": ["설치를 실행한다", "3단계에서 멈춘다"]}
    g, gs = b1.add(alice, "genesis", {"type": "problem", "title": "설치 멈춤",
                                      "body": "본문", "envelope": env})
    p, ps = b1.add(bob, "post", {"round": 0, "body": "이렇게 해 보라"})
    a, asig = b1.add(alice, "answer_selected", {"post_message_id": p["message_id"]})
    c, cs = b1.add(alice, "close", {"reason": "solved"})
    for i, (ev, sig) in enumerate(b1.posted):
        code, body = send(args.base, t1, "problem", "설치 멈춤", ev, sig, ev["kind"] == "genesis")
        v = body.get("verdict", {}) if isinstance(body, dict) else {}
        print("  %-16s -> %s %s" % (ev["kind"], code, v.get("reducer", body)))
    results.append(("세트1 problem 정상", t1, b1))

    # ── 세트 2: 사슬 경합 ─────────────────────────────────────────────────
    print("\n== 세트 2: 사슬 경합(같은 prev 로 두 사람이 동시에) ==")
    t2 = new_id()
    b2 = Builder(t2, args.workdir, allowed, revoked, [op["id"]], now)
    g2, g2s = b2.add(alice, "genesis", {"type": "problem", "title": "경합",
                                        "body": "본문", "envelope": env})
    head, sh = b2.head_and_hash()
    e_a, s_a = b2.add(bob, "post", {"round": 0, "body": "먼저 온 글"}, prev=head, expected=sh)
    e_b, s_b = b2.add(alice, "post", {"round": 0, "body": "같은 자리에 쓴 글"}, prev=head, expected=sh)
    for ev, sig in b2.posted:
        code, body = send(args.base, t2, "problem", "경합", ev, sig, ev["kind"] == "genesis")
        v = body.get("verdict", {}) if isinstance(body, dict) else {}
        print("  %-16s -> %s %s %s" % (ev["kind"], code, v.get("reducer"), v.get("reason") or ""))
    results.append(("세트2 경합", t2, b2))

    # ── 세트 3: 절차 거부(권한 없는 close · 예산 초과) ─────────────────────
    print("\n== 세트 3: 절차 거부(제3자 answer_selected) ==")
    t3 = new_id()
    b3 = Builder(t3, args.workdir, allowed, revoked, [op["id"]], now)
    g3, g3s = b3.add(alice, "genesis", {"type": "problem", "title": "절차",
                                        "body": "본문", "envelope": env})
    p3, p3s = b3.add(bob, "post", {"round": 0, "body": "답 후보"})
    bad, bads = b3.add(bob, "answer_selected", {"post_message_id": p3["message_id"]})
    for ev, sig in b3.posted:
        code, body = send(args.base, t3, "problem", "절차", ev, sig, ev["kind"] == "genesis")
        v = body.get("verdict", {}) if isinstance(body, dict) else {}
        print("  %-16s -> %s %s %s" % (ev["kind"], code, v.get("reducer"), v.get("reason") or ""))
    results.append(("세트3 절차 거부", t3, b3))

    # ── 3자 대조 ──────────────────────────────────────────────────────────
    print("\n== 3자 대조(파이썬 리듀서 == 서버 파생) ==")
    all_ok = True
    for name, tid, b in results:
        py = b.state()
        code, srv = http("GET", args.base + "/rooms/" + tid)
        if code != 200:
            print("  %-18s 서버 응답 %s %s" % (name, code, srv))
            all_ok = False
            continue
        rows = compare(py, srv)
        ok = all(r[3] for r in rows)
        all_ok = all_ok and ok
        print("  %-18s %s" % (name, "일치" if ok else "불일치"))
        for f, a, bb, same in rows:
            if not same:
                print("     %-12s python=%r server=%r" % (f, a, bb))
        print("     state=%s state_hash=%s..." % (py.get("state"), (py.get("state_hash") or "")[:16]))
        # 격리·stale 계수도 함께 본다(칸이 아니라 목록의 크기).
        code2, evs = http("GET", args.base + "/rooms/" + tid + "/events?limit=200")
        srv_valid = sum(1 for i in evs["items"] if i["valid"])
        srv_q = sum(1 for i in evs["items"] if i["quarantined"])
        srv_s = sum(1 for i in evs["items"] if i["stale"])
        py_valid, py_q, py_s = len(py.get("events") or []), len(py.get("quarantined") or []), len(py.get("stale") or [])
        same_counts = (srv_valid, srv_q, srv_s) == (py_valid, py_q, py_s)
        all_ok = all_ok and same_counts
        print("     계수 valid/격리/stale  python=%d/%d/%d server=%d/%d/%d %s"
              % (py_valid, py_q, py_s, srv_valid, srv_q, srv_s, "일치" if same_counts else "★불일치"))

    # ── 4경로 + 방어 축 실행값 ─────────────────────────────────────────────
    print("\n== 4경로 실행값(성공 · 서명 위조 · 사슬 충돌 · 봉투 위반) ==")
    checks = []

    def record(name, want, got, extra=""):
        ok = (got == want)
        checks.append(ok)
        print("  %-34s 기대 %-3s 실제 %-3s %s %s"
              % (name, want, got, "OK" if ok else "★불일치", extra))

    # (1) 성공 — 위 세트1 genesis 가 201 이었다. 여기서는 새 방으로 한 번 더.
    t4 = new_id()
    b4 = Builder(t4, args.workdir, allowed, revoked, [op["id"]], now)
    g4, g4s = b4.add(alice, "genesis", {"type": "knowhow", "title": "성공 경로",
                                        "body": "본문", "envelope": env})
    code, body = send(args.base, t4, "knowhow", "성공 경로", g4, g4s, True)
    record("경로1 정상 적재", 201, code, body.get("event_id", "") if isinstance(body, dict) else "")

    # (2) 서명 위조 — 서명한 뒤 본문을 한 글자 바꾼다(같은 서명 재사용).
    forged = json.loads(json.dumps(g4))
    forged["payload"]["body"] = "본문을 몰래 고쳤다"
    code, body = send(args.base, t4, "knowhow", "성공 경로", forged, g4s, True)
    record("경로2 서명 위조(본문 변조)", 401, code,
           (body.get("detail", {}) or {}).get("verdict", "") if isinstance(body, dict) else "")

    # (2b) 명부 밖 키 — 등록하지 않은 사람의 서명
    mallory = keygen(args.workdir, "mallory")
    b4b = Builder(t4, args.workdir, allowed, revoked, [op["id"]], now)
    gm, gms = b4b.make(mallory, "genesis", {"type": "knowhow", "title": "명부 밖",
                                            "body": "본문", "envelope": env})
    code, body = send(args.base, new_id(), "knowhow", "명부 밖", gm, gms, True)
    record("경로2b 명부 밖 키", 400, code, "(thread 결박이 먼저 걸린다)")
    gm2, gms2 = b4b.make(mallory, "genesis", {"type": "knowhow", "title": "명부 밖",
                                              "body": "본문", "envelope": env})
    code, body = send(args.base, t4, "knowhow", "명부 밖", gm2, gms2, True)
    record("경로2c 명부 밖 키(결박 통과 후)", 401, code,
           (body.get("detail", {}) or {}).get("why", "") if isinstance(body, dict) else "")

    # (3) 사슬 충돌 — 세트2 에서 진 글이 stale 로 적재됐다(거절이 아니다).
    code, evs = http("GET", args.base + "/rooms/" + results[1][1] + "/events?limit=50")
    stale_n = sum(1 for i in evs["items"] if i["stale"]) if code == 200 else -1
    record("경로3 사슬 충돌: 진 글도 원장에 남는다", 1, stale_n, "(격리가 아니라 stale)")

    # (4) 봉투 위반 — repro_steps 를 비운다
    t5 = new_id()
    b5 = Builder(t5, args.workdir, allowed, revoked, [op["id"]], now)
    bad_env = {"env": {"os": "macOS", "app": "agora"}, "symptom": "증상", "repro_steps": []}
    g5, g5s = b5.make(alice, "genesis", {"type": "problem", "title": "봉투 위반",
                                         "body": "본문", "envelope": bad_env})
    code, body = send(args.base, t5, "problem", "봉투 위반", g5, g5s, True)
    record("경로4 봉투 결손(재현 단계 0)", 422, code,
           "code=%s" % (body.get("code") if isinstance(body, dict) else "?"))

    # (4b) 스크럽 백스톱 — 본문에 이메일 형태
    t6 = new_id()
    b6 = Builder(t6, args.workdir, allowed, revoked, [op["id"]], now)
    g6, g6s = b6.make(alice, "genesis", {"type": "knowhow", "title": "스크럽",
                                         "body": "연락은 someone@example.com 으로",
                                         "envelope": env})
    code, body = send(args.base, t6, "knowhow", "스크럽", g6, g6s, True)
    record("경로4b 스크럽 백스톱(이메일 형태)", 422, code,
           "rules=%s" % ((body.get("detail", {}) or {}).get("rules") if isinstance(body, dict) else "?"))

    print("\n== 방어 축 ==")
    # 멱등 — 같은 것을 두 번 보내면 행이 안 는다
    code_a, body_a = send(args.base, t4, "knowhow", "성공 경로", g4, g4s, True)
    record("멱등 재전송(같은 내용)", 200, code_a,
           "status=%s" % (body_a.get("status") if isinstance(body_a, dict) else "?"))
    code_b, _ = http("GET", args.base + "/rooms/" + t4 + "/events?limit=50")
    n_after = len(_["items"]) if code_b == 200 else -1
    record("멱등 후 행 수 = 1", 1, n_after)

    # message_id 재사용(다른 내용) — 재시도가 아니라 다른 글이다
    reused = json.loads(json.dumps(g4))
    reused["payload"]["body"] = "같은 message_id 로 다른 내용"
    raw2 = canonical_bytes(reused)
    sig2 = sign_bytes(alice["key"], raw2, args.workdir)
    code, body = send(args.base, t4, "knowhow", "성공 경로", reused, sig2, True)
    record("message_id 재사용(다른 내용)", 422, code,
           "conflict=%s" % ((body.get("detail", {}) or {}).get("conflict") if isinstance(body, dict) else "?"))

    # updated_at 갱신 축(D-R12) — 이벤트가 쌓이면 목록의 updated_at 이 움직인다.
    # ★열린 방(세트2)으로 잰다. 앞선 판본은 **닫힌 방을 열린 목록에서** 찾아 before 가 None 이었고,
    #   "" 와의 비교가 언제나 참이라 **공허하게 통과**했다(2026-09-05 자기적발).
    open_room = results[1][1]
    code, rooms1 = http("GET", args.base + "/rooms?limit=100")
    before_map = {r["room_id"]: r["updated_at"] for r in rooms1["items"]}
    before = before_map.get(open_room)
    record("측정 전제: 그 방이 열린 목록에 있다", True, before is not None, str(before))
    b_open = results[1][2]
    p7, p7s = b_open.add(bob, "post", {"round": 0, "body": "갱신 축 확인용 발언"})
    send(args.base, open_room, "problem", "경합", p7, p7s, False)
    code, rooms2 = http("GET", args.base + "/rooms?limit=100")
    after = {r["room_id"]: r["updated_at"] for r in rooms2["items"]}.get(open_room)
    moved = (before is not None and after is not None and after > before)
    record("updated_at 이 움직인다", True, moved, "%s -> %s" % (before, after))

    # 파생 캐시 자가치유(R-7) — 캐시를 지워도 조회가 다시 채운다
    subprocess.run([os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "node_modules/.bin/wrangler"), "d1", "execute", "agora-relay",
                    "--local", "--command", "DELETE FROM rooms"],
                   capture_output=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   env={k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"})
    code, st = http("GET", args.base + "/rooms/" + results[0][1])
    code2, rooms3 = http("GET", args.base + "/rooms?closed=1&limit=100")
    healed = any(r["room_id"] == results[0][1] for r in rooms3.get("items", []))
    record("파생 캐시 자가치유(DELETE 후 조회)", True, healed,
           "state=%s" % (st.get("state") if isinstance(st, dict) else "?"))

    ok4 = all(checks)
    print("\n== 결과: %s ==" % ("PASS" if (all_ok and ok4) else "FAIL"))
    return 0 if (all_ok and ok4) else 1


if __name__ == "__main__":
    sys.exit(main())
