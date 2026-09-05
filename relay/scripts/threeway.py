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

    # ── 세트 4: debate 전 구간 ─────────────────────────────────────────────
    # ★설계 성찰이 「안 덮였다」고 적은 전이를 실제로 태운다:
    #   advance(의장만) · r2 반론 필수 · resolution(r3 에서만) · 라운드 밖 발언 거부.
    print("\n== 세트 4: debate 전 구간(r0→r3 → resolution → close) ==")
    t7 = new_id()
    b7 = Builder(t7, args.workdir, allowed, revoked, [op["id"]], now)
    b7.add(alice, "genesis", {"type": "debate", "title": "토론", "body": "쟁점"})
    b7.add(bob, "post", {"round": 0, "body": "r0 발언"})
    b7.add(bob, "advance", {"from_round": 0, "to_round": 1})       # ← 의장이 아니다(거부되어야 한다)
    b7.add(alice, "advance", {"from_round": 0, "to_round": 1})
    r1_post, _ = b7.add(bob, "post", {"round": 1, "body": "r1 주장"})
    b7.add(bob, "post", {"round": 0, "body": "지난 라운드 발언"})    # ← 라운드 밖(거부)
    b7.add(alice, "advance", {"from_round": 1, "to_round": 2})
    b7.add(bob, "post", {"round": 2, "body": "반론 없는 r2 발언"})   # ← counter 없음(거부)
    b7.add(bob, "post", {"round": 2, "body": "반론",
                         "counter": [{"target_message_id": r1_post["message_id"],
                                      "point": "그 전제가 성립하지 않는다"}]})
    b7.add(alice, "advance", {"from_round": 2, "to_round": 3})
    b7.add(bob, "post", {"round": 3, "body": "마무리 발언"})
    b7.add(bob, "resolution", {"summary": "요약", "dissent": [],
                               "recommended_actions": [{"text": "권고", "execution": "forbidden"}]})  # ← 의장 아님(거부)
    b7.add(alice, "resolution", {"summary": "합의 요약", "dissent": [],
                                 "recommended_actions": [{"text": "이렇게 하기를 권한다",
                                                          "execution": "forbidden"}]})
    b7.add(alice, "close", {"reason": "unresolved"})
    throttled = 0
    for ev, sig in b7.posted:
        code, body = send(args.base, t7, "debate", "토론", ev, sig, ev["kind"] == "genesis")
        v = body.get("verdict", {}) if isinstance(body, dict) else {}
        if code == 429:
            throttled += 1
        print("  %-16s -> %s %-11s %s" % (ev["kind"], code, v.get("reducer"), v.get("reason") or ""))
    if throttled:
        # ★429 는 「구현이 틀렸다」가 아니라 「상한이 사용 형태와 안 맞는다」다. 조용히 넘기면
        #   뒤의 대조 불일치를 **엉뚱한 원인**으로 읽게 된다(2026-09-05 실제로 그럴 뻔했다).
        print("  ★경고: 정상 진행 중 429 가 %d 건 — 속도 상한이 사용 형태와 안 맞는다(대조 결과를 그 탓으로 읽지 마라)"
              % throttled)
    results.append(("세트4 debate 전구간", t7, b7))

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

    # (2d) ★사칭 — **등록된 키**로 서명하고 `from` 만 남의 이름으로 적는다.
    #      앞의 2b·2c 는 「명부 밖 키」만 재고 이 축을 한 번도 안 쟀다(뮤테이션 M3 가 살아남아 드러났다).
    b4c = Builder(t4, args.workdir, allowed, revoked, [op["id"]], now)
    ev_imp, _sig_unused = b4c.make(alice, "genesis", {"type": "knowhow", "title": "사칭",
                                                      "body": "본문", "envelope": env})
    ev_imp["from"] = bob["id"]                       # 이름만 바꾸고
    sig_imp = sign_bytes(alice["key"], canonical_bytes(ev_imp), args.workdir)   # 서명은 alice 키로
    code, body = send(args.base, t4, "knowhow", "사칭", ev_imp, sig_imp, True)
    record("경로2d 사칭(등록된 키 + 남의 이름)", 401, code,
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

    print("\n== agy 지적 봉합 축(2026-09-05 1라운드) ==")
    # (A) 조작된 서명 블록이 401(code 4)로 나가는가 — 원시 예외가 새면 500(code 7)이 된다.
    tA = new_id()
    bA = Builder(tA, args.workdir, allowed, revoked, [op["id"]], now)
    evA, sigA = bA.make(alice, "genesis", {"type": "knowhow", "title": "잘린 서명",
                                           "body": "본문", "envelope": env})
    import base64 as _b64
    _body = "".join(l for l in sigA.splitlines() if "-----" not in l)
    _raw = _b64.b64decode(_body)
    truncated = ("-----BEGIN SSH SIGNATURE-----\n"
                 + _b64.b64encode(_raw[:20]).decode() + "\n-----END SSH SIGNATURE-----\n")
    code, body = send(args.base, tA, "knowhow", "잘린 서명", evA, truncated, True)
    record("잘린 서명 블록 = 401(500 아님)", 401, code,
           "code=%s" % (body.get("code") if isinstance(body, dict) else "?"))
    # 길이 필드만 부풀린 변형(내용은 그대로) — 파서가 경계를 넘어 읽으려 한다
    _tamper = bytearray(_raw)
    _tamper[10:14] = (0x7fffff00).to_bytes(4, "big")
    inflated = ("-----BEGIN SSH SIGNATURE-----\n"
                + _b64.b64encode(bytes(_tamper)).decode() + "\n-----END SSH SIGNATURE-----\n")
    code, body = send(args.base, tA, "knowhow", "길이 조작", evA, inflated, True)
    record("길이 필드 조작 = 401(500 아님)", 401, code,
           "code=%s" % (body.get("code") if isinstance(body, dict) else "?"))

    # (B) 멱등 재시도가 발언 예산을 깎지 않는가 — 깎으면 정상 발언이 429 로 막힌다.
    tB = new_id()
    bB = Builder(tB, args.workdir, allowed, revoked, [op["id"]], now)
    gB, gBs = bB.add(alice, "genesis", {"type": "knowhow", "title": "재시도 예산",
                                        "body": "본문", "envelope": env})
    code, _ = send(args.base, tB, "knowhow", "재시도 예산", gB, gBs, True)
    repeats = 0
    for _ in range(35):
        c, _b = send(args.base, tB, "knowhow", "재시도 예산", gB, gBs, True)
        if c == 200:
            repeats += 1
    record("멱등 재시도 35회가 모두 200", 35, repeats)
    pB, pBs = bB.add(alice, "post", {"round": 0, "body": "재시도 뒤의 정상 발언"})
    code, body = send(args.base, tB, "knowhow", "재시도 예산", pB, pBs, False)
    record("재시도 뒤 정상 발언이 통과", 201, code,
           "code=%s" % (body.get("code") if isinstance(body, dict) else "-"))

    print("\n== 페이지·경계 축 ==")
    # 이벤트 페이지 — 나눠 받아도 전건이고 겹치지 않는다
    t_full = results[3][1]      # 세트4(debate) = 이벤트가 가장 많다
    code, one = http("GET", args.base + "/rooms/" + t_full + "/events?limit=200")
    total = len(one["items"]) if code == 200 else -1
    seen_ids, pages, cursor = [], 0, None
    while True:
        url = args.base + "/rooms/" + t_full + "/events?limit=3" + ("&cursor=" + cursor if cursor else "")
        code, page = http("GET", url)
        if code != 200:
            break
        pages += 1
        seen_ids.extend(i["event_id"] for i in page["items"])
        cursor = page.get("next_cursor")
        if not cursor or pages > 50:
            break
    record("이벤트 페이지: 합계 = 전건", total, len(seen_ids), "%d 쪽" % pages)
    record("이벤트 페이지: 중복 0", len(set(seen_ids)), len(seen_ids))
    record("이벤트 페이지: 2쪽 이상", True, pages >= 2)

    # 방 목록 페이지·updated_since
    # ★전제를 먼저 단언한다. 앞선 판본은 **캐시를 비우는 시험 뒤에** 재서 목록이 0건이었고,
    #   0 == 0 이 통과로 보였다(2026-09-05 두 번째 자기적발 — 같은 병을 또 만들었다).
    code, allrooms = http("GET", args.base + "/rooms?limit=100")
    n_open = len(allrooms["items"])
    record("측정 전제: 열린 방이 2개 이상", True, n_open >= 2, "%d개" % n_open)
    code, first = http("GET", args.base + "/rooms?limit=1")
    got, cur, guard = [], first.get("next_cursor"), 0
    got.extend(r["room_id"] for r in first["items"])
    while cur and guard < 20:
        guard += 1
        code, pg = http("GET", args.base + "/rooms?limit=1&cursor=" + cur)
        got.extend(r["room_id"] for r in pg["items"])
        cur = pg.get("next_cursor")
    record("방 목록 페이지: 합계 = 전건", n_open, len(got), "%d 쪽" % (guard + 1))
    record("방 목록 페이지: 중복 0", len(set(got)), len(got))
    newest = max(r["updated_at"] for r in allrooms["items"]) if n_open else ""
    code, since = http("GET", args.base + "/rooms?limit=100&updated_since=" + newest)
    record("updated_since = 최신값이면 0건", 0, len(since["items"]))

    # 64KB 경계 — canonical 이 상한을 넘으면 413
    big = Builder(new_id(), args.workdir, allowed, revoked, [op["id"]], now)
    huge_body = "가" * 70000
    try:
        ev_big, sig_big = big.make(alice, "genesis", {"type": "knowhow", "title": "큰 이벤트",
                                                      "body": huge_body, "envelope": env})
        code, body = send(args.base, big.thread_id, "knowhow", "큰 이벤트", ev_big, sig_big, True)
        record("64KB 초과 이벤트", 413, code,
               "code=%s" % (body.get("code") if isinstance(body, dict) else "?"))
    except SystemExit:
        raise
    except Exception as e:
        # 클라이언트(파이썬)가 먼저 막는 것도 정상이다 — 두 겹 다 있는 것이 계약이다.
        record("64KB 초과: 클라 게이트가 선차단", True, True, type(e).__name__)

    # ★그런데 그것만 재면 **서버 축은 무검증**이다(클라를 안 쓰는 발신자가 바로 그 위협이다).
    #   그래서 클라 게이트를 우회해 큰 본문을 손으로 만들어 보낸다.
    ev_small, sig_small = big.make(alice, "genesis", {"type": "knowhow", "title": "작은 것",
                                                      "body": "본문", "envelope": env})
    fat = dict(ev_small)
    fat["payload"] = dict(ev_small["payload"], body="나" * 70000)
    raw_body = "<!-- agora-event v1 -->\n```json\n" + json.dumps(fat, ensure_ascii=False) + "\n```\n" + sig_small
    code, body = http("POST", args.base + "/events", {
        "thread_id": big.thread_id, "category": "knowhow", "title": "큰 이벤트",
        "body": raw_body, "is_genesis": True})
    record("64KB 초과: 서버가 막는다", 413, code,
           "code=%s" % (body.get("code") if isinstance(body, dict) else "?"))

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
