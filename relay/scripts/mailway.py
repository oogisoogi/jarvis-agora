#!/usr/bin/env python3
"""에이전트 우편(1:1) 서버 왕복 — docs/RELAY.md §14 · 명세 docs/SPEC-mail-1to1-2026-10-05.md §8.

무엇을 재는가: 실제 workerd + 실제 D1(로컬) 위에서 `POST /mail` · `GET /mail/inbox` · `POST /mail/ack` 가
명세의 검사 순서·응답 모양·상한·보존 기한을 지키는가. 서명은 실제 `ssh-keygen -Y sign` 으로 만든다.

★각 축에 **음성 대조**를 붙인다(남의 키·재사용 헤더·지난 ts·남의 대화·남의 ack …).
★이 파일은 `agora/` 를 **읽어서 쓰기만** 한다(수정 0) — canonical 직렬화는 `agora.event.canonical_bytes` 그대로.
★run-local.py 가 threeway 뒤에 부른다(같은 서버·같은 D1). 단독 실행:
  python3 relay/scripts/mailway.py --base http://127.0.0.1:8787
  (⚠상한 버킷이 남아 있으면 두 번째 실행이 429 로 갈린다 — run-local 이 D1 을 비우고 부르는 것이 정상 경로다.)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
RELAY = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from threeway import keygen, register, sign_bytes  # noqa: E402
from agora.event import canonical_bytes, new_id, render_post  # noqa: E402


def iso(t: float | None = None) -> str:
    d = dt.datetime.fromtimestamp(time.time() if t is None else t, tz=dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def http(method, url, payload=None, headers=None):
    """(상태, 본문, 응답 헤더). ★응답 헤더까지 돌려준다 — Cache-Control·CORS 부재가 계약 칸이다."""
    data = json.dumps(payload).encode() if payload is not None else None
    h = dict(headers or {})
    if data is not None:
        h["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
            hdrs = {k.lower(): v for k, v in r.headers.items()}
            return r.status, (json.loads(body) if body.strip().startswith(("{", "[")) else body), hdrs
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        hdrs = {k.lower(): v for k, v in e.headers.items()}
        try:
            return e.code, json.loads(body), hdrs
        except ValueError:
            return e.code, body, hdrs


class Mail:
    def __init__(self, base, workdir):
        self.base = base
        self.workdir = workdir

    def doc(self, sender, to, thread_id, payload, *, reply_to=None, prev="genesis", ts=None, message_id=None):
        d = {"v": 1, "kind": "mail", "message_id": message_id or new_id(), "thread_id": thread_id,
             "from": sender["id"], "to": to, "prev": prev, "roster": "0" * 64,
             "scrub": {"rules": "0" * 64, "blocked": 0, "redacted": 0},
             "ts": ts or iso(), "payload": payload}
        if reply_to:
            d["reply_to"] = reply_to
        return d

    def sign(self, signer, doc):
        return sign_bytes(signer["key"], canonical_bytes(doc), self.workdir)

    def post(self, doc, sig, mail_text=None):
        text = mail_text if mail_text is not None else canonical_bytes(doc).decode("utf-8")
        return http("POST", self.base + "/mail", {"mail": text, "signature": sig})

    def send(self, sender, to, thread_id, payload, **kw):
        d = self.doc(sender, to, thread_id, payload, **kw)
        s = self.sign(sender, d)
        code, body, hdrs = self.post(d, s)
        return d, s, code, body, hdrs

    def auth(self, signer, for_id, since="", receipts_since="", ts=None):
        ts = ts or iso()
        doc = {"for": for_id, "purpose": "agora-mail-inbox-v1", "receipts_since": receipts_since,
               "since": since, "ts": ts}
        sig = sign_bytes(signer["key"], canonical_bytes(doc), self.workdir)
        return base64.b64encode(json.dumps({"ts": ts, "signature": sig}).encode()).decode()

    def inbox(self, for_id, header, since="", receipts_since="", extra_headers=None):
        q = "for=%s" % quote(for_id, safe="")
        if since:
            q += "&since=" + quote(since, safe="")
        if receipts_since:
            q += "&receipts_since=" + quote(receipts_since, safe="")
        h = dict(extra_headers or {})
        if header is not None:
            h["X-Agora-Mail-Auth"] = header
        return http("GET", self.base + "/mail/inbox?" + q, headers=h)

    def ack(self, signer, for_id, mail_ids, ts=None):
        ts = ts or iso()
        doc = {"acked": mail_ids, "for": for_id, "purpose": "agora-mail-ack-v3", "ts": ts}
        sig = sign_bytes(signer["key"], canonical_bytes(doc), self.workdir)
        return http("POST", self.base + "/mail/ack", {"for": for_id, "mail_ids": mail_ids, "ts": ts, "signature": sig})


def letter(subject, body="본문입니다", intent="notice"):
    return {"subject": subject, "body": body, "intent": intent}


def signal_item(error_code="update.sig_mismatch", op="host.update", source="update", version="1.1.8", **over):
    key = hashlib.sha256(canonical_bytes({"error_code": error_code, "op": op, "source": source,
                                          "version": version.lower()})).hexdigest()[:32]
    now = time.time()
    it = {"signature": key, "count": 3, "source": source, "op": op, "version": version, "os": "macos-15.6",
          "error_code": error_code, "first_seen": iso(now - 3600), "last_seen": iso(now - 60)}
    it.update(over)
    return it


def d1(sql):
    """로컬 D1 에 직접 쓴다(**--local 전용** — 원격은 건드리지 않는다)."""
    env = {k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"}
    r = subprocess.run([os.path.join(RELAY, "node_modules/.bin/wrangler"), "d1", "execute", "agora-relay",
                        "--local", "--command", sql], cwd=RELAY, capture_output=True, text=True, env=env)
    return r.returncode, (r.stdout + r.stderr)[-400:]


def items_of(box):
    if not isinstance(box, dict):
        return []
    return [it for t in box.get("threads") or [] for it in t.get("items") or []]


def find(box, message_id):
    for it in items_of(box):
        if it.get("message_id") == message_id:
            return it
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--workdir", default="/tmp/agora-mailway")
    args = ap.parse_args()
    os.makedirs(args.workdir, exist_ok=True)
    os.chmod(args.workdir, 0o700)
    M = Mail(args.base, args.workdir)

    checks = []

    def record(name, want, got, note=""):
        ok = want == got
        checks.append(ok)
        print("  %s %-52s want=%-14s got=%-14s %s" % ("✓" if ok else "✗", name, str(want)[:14], str(got)[:14], note))

    def code_of(body):
        return body.get("code") if isinstance(body, dict) else None

    def why_of(body):
        det = body.get("detail") if isinstance(body, dict) else None
        return det.get("why") if isinstance(det, dict) else None

    A, B, C, D = (keygen(args.workdir, n) for n in ("mail-a", "mail-b", "mail-c", "mail-d"))
    print("== 우편 0. 등록 ==")
    for s in (A, B, C, D):
        code, _ = register(args.base, s, args.workdir)
        record("등록 %s = 201" % s["id"], 201, code)

    # ── 1. 보내기 · 멱등 · 재사용 ─────────────────────────────────────────────
    print("\n== 우편 1. 보내기 · 멱등 · message_id 재사용 ==")
    T1 = new_id()
    subj1 = "우편제목-" + new_id()[:8]
    m1, s1, code, body, hdrs = M.send(A, B["id"], T1, letter(subj1))
    record("A→B 새 우편 = 201", 201, code)
    record("201 본문 = 계약 세 칸", ["created_at", "mail_id", "thread_id"],
           sorted(body.keys()) if isinstance(body, dict) else body)
    mail_id1 = body.get("mail_id") if isinstance(body, dict) else None
    record("Cache-Control = private, no-store", "private, no-store", hdrs.get("cache-control"))
    code, body2, _ = M.post(m1, s1)
    record("같은 우편 재전송 = 200(멱등)", 200, code)
    record("멱등 200 = 같은 mail_id", mail_id1, body2.get("mail_id") if isinstance(body2, dict) else None)
    m1b = dict(m1, payload=letter(subj1, body="다른 본문"))
    code, body, _ = M.post(m1b, M.sign(A, m1b))
    record("같은 message_id 다른 본문 = 422", 422, code, "code=%s" % code_of(body))
    record("  why = message_id_reused", "message_id_reused", why_of(body))

    # ── 2. 서명·명부·받는 사람 ─────────────────────────────────────────────────
    print("\n== 우편 2. 서명 위조 · 남의 키 · 명부 밖 받는 사람 · 닫힌 칸 ==")
    mf = M.doc(A, B["id"], new_id(), letter("위조 시험"))
    sf = M.sign(A, mf)
    tampered = dict(mf, payload=letter("위조 시험", body="서명 뒤에 바꾼 본문"))
    code, body, _ = M.post(tampered, sf)
    record("본문 변조(서명 그대로) = 401", 401, code, "code=%s" % code_of(body))
    record("  verdict = BAD", "BAD", (body.get("detail") or {}).get("verdict") if isinstance(body, dict) else None)
    mc = M.doc(A, B["id"], new_id(), letter("남의 키"))
    code, body, _ = M.post(mc, M.sign(C, mc))
    record("C 키로 서명한 from=A 우편 = 401", 401, code, "why=%s" % why_of(body))
    _, _, code, body, _ = M.send(A, "nobody-here", new_id(), letter("명부 밖"))
    record("명부 밖 to = 404", 404, code)
    record("  code 2 · why=recipient_not_in_roster", (2, "recipient_not_in_roster"), (code_of(body), why_of(body)))
    mx = M.doc(A, B["id"], new_id(), letter("모르는 칸"))
    mx["extra"] = 1
    code, body, _ = M.post(mx, M.sign(A, mx))
    record("모르는 칸 = 400/10", (400, 10), (code, code_of(body)))
    ms = M.doc(A, B["id"], new_id(), letter("신호 칸 섞기"))
    ms["payload"]["items"] = []
    code, body, _ = M.post(ms, M.sign(A, ms))
    record("일반 우편에 items 칸 = 400/10", (400, 10), (code, code_of(body)))

    # ── 3. 대화 결박 · ts ────────────────────────────────────────────────────
    print("\n== 우편 3. 대화 결박 · reply_to · ts 창 ==")
    _, _, code, body, _ = M.send(C, A["id"], T1, letter("끼어들기"))
    record("C 가 A-B 대화에 쓰기 = 422", 422, code, "code=%s" % code_of(body))
    record("  why = thread_not_yours", "thread_not_yours", why_of(body))
    _, _, code, body, _ = M.send(A, B["id"], T1, letter("없는 답"), reply_to=new_id())
    record("같은 대화의 없는 reply_to = 422 reply_outside_thread", (422, "reply_outside_thread"), (code, why_of(body)))
    _, _, code, body, _ = M.send(A, B["id"], new_id(), letter("대화 밖 답"), reply_to=m1["message_id"])
    record("다른 대화 id 로 m1 에 답 = 422 reply_outside_thread", (422, "reply_outside_thread"), (code, why_of(body)))
    _, _, code, body, _ = M.send(A, B["id"], new_id(), letter("묵힌 우편"), ts=iso(time.time() - 25 * 3600))
    record("ts 25시간 전 = 422 stale_ts", (422, "stale_ts"), (code, why_of(body)))
    # 스크럽 음성 대조 — D 로 잰다(스크럽은 상한보다 앞이라 D 의 새 대화 칸을 태우지 않는다 · 아래 10 에서 쓴다).
    _, _, code, body, _ = M.send(D, A["id"], new_id(), letter("경로", body="키 파일은 /Users/someone/.ssh 에 있다"))
    record("스크럽 백스톱(경로) = 422/3", (422, 3), (code, code_of(body)))

    # ── 3-b. 대화 결박 경합 — 적재 문장 자체가 막는가(적대 1R R1-3 · 오프라인 · 실제 마이그레이션 + 실제 적재 SQL) ──
    print("\n== 우편 3-b. 대화 결박 경합(적재 문장 원자성) ==")
    import re as _re
    import sqlite3 as _sqlite3
    src = open(os.path.join(RELAY, "src", "index.ts"), encoding="utf-8").read()
    ins = _re.search(r"`(INSERT INTO mail \(.*?RETURNING seq)`", src, _re.S)
    db = _sqlite3.connect(":memory:")
    db.executescript(open(os.path.join(RELAY, "migrations", "0003_mail.sql"), encoding="utf-8").read())

    def race_insert(frm, to, tid):
        args = (new_id(), tid, frm, to, "genesis", None, "notice", "0" * 64, 1, "{}", "sig", iso(), iso())
        return db.execute(ins.group(1), args).fetchone() if ins else "no-sql"
    TR = new_id()
    record("경합: 빈 대화에 a→v 적재 = 행 1", True, bool(race_insert("a", "v", TR)))
    record("경합: 같은 대화에 b→v(조회를 앞서 통과) = 행 0", None, race_insert("b", "v", TR))
    record("경합: 같은 대화에 v→a(같은 쌍 · 역방향) = 행 1", True, bool(race_insert("v", "a", TR)))

    # ── 3-c. 읽음 SQL — mail_id 대상만(적대 2R R2-2 · 4R R4-1 · 오프라인 · 실제 ack SQL) ──
    print("\n== 우편 3-c. 읽음 SQL(mail_id 목록만 · 재생 안전) ==")
    upd = _re.search(r"`(UPDATE mail SET acked_at = \?1.*?)`", src, _re.S)
    db2 = _sqlite3.connect(":memory:")
    db2.executescript(open(os.path.join(RELAY, "migrations", "0003_mail.sql"), encoding="utf-8").read())
    same_mid, TA, TC = new_id(), new_id(), new_id()

    def put(frm, tid, mid):
        return db2.execute(ins.group(1), (mid, tid, frm, "v", "genesis", None, "notice", "0" * 64, 1, "{}", "sig",
                                          iso(), iso())).fetchone()[0]
    sa = put("a", TA, same_mid)
    sc = put("c", TC, same_mid)

    def ack_sql(seqs):
        cur = db2.execute(upd.group(1), (iso(), "v", json.dumps(seqs))) if upd else None
        return cur.rowcount if cur else "no-sql"
    record("두 발신자 · 같은 message_id · a 의 mail_id 하나 ack = 1통만", 1, ack_sql([sa]))
    record("  c 의 우편은 그대로 미읽음", None,
           db2.execute("SELECT acked_at FROM mail WHERE seq = ?", (sc,)).fetchone()[0])
    s2 = put("a", TA, new_id())
    record("같은 ack 재생(뒤에 같은 대화에 우편 적재) = 0통 · 새 우편 미읽음", (0, None),
           (ack_sql([sa]), db2.execute("SELECT acked_at FROM mail WHERE seq = ?", (s2,)).fetchone()[0]))

    # ── 4. 상한(새 대화) ──────────────────────────────────────────────────────
    print("\n== 우편 4. 새 대화 상한 ==")
    _, _, code, body, hdrs = M.send(A, B["id"], new_id(), letter("두 번째 새 대화"))
    if code == 201:
        # ★고정창 경계를 막 넘은 경우만 — 한 번 더 보내면 같은 창 안이다.
        _, _, code, body, hdrs = M.send(A, B["id"], new_id(), letter("세 번째 새 대화"))
    record("A 두 번째 새 대화(창 안) = 429", 429, code, "limit=%s" % ((body.get("detail") or {}).get("limit")
                                                                if isinstance(body, dict) else "?"))
    record("  code 7 · Retry-After 있음", (7, True), (code_of(body), bool(hdrs.get("retry-after"))))
    record("  limit = new_participant_mail_new", "new_participant_mail_new",
           (body.get("detail") or {}).get("limit") if isinstance(body, dict) else None)

    # ── 5. 수신함 ───────────────────────────────────────────────────────────
    print("\n== 우편 5. 수신함 — 본인만 · 재사용 · 시각 창 ==")
    hb = M.auth(B, B["id"])
    code, box, hdrs = M.inbox(B["id"], hb, extra_headers={"Origin": "http://localhost:8788"})
    record("B 수신함(B 키) = 200", 200, code)
    it = find(box, m1["message_id"])
    record("m1 이 B 수신함에 있다", True, it is not None)
    record("item 칸 = 계약 여섯 칸", ["created_at", "from", "mail", "mail_id", "message_id", "signature"],
           sorted(it.keys()) if it else None)
    record("mail = 서명 대상 canonical 그대로", canonical_bytes(m1).decode("utf-8"), (it or {}).get("mail"))
    record("unread_count = 1", 1, box.get("unread_count") if isinstance(box, dict) else None)
    t1 = [t for t in (box.get("threads") or []) if t.get("thread_id") == T1] if isinstance(box, dict) else []
    record("대화 묶음 peer = A · unread = 1", (A["id"], 1), (t1[0].get("peer"), t1[0].get("unread")) if t1 else None)
    record("Cache-Control = private, no-store", "private, no-store", hdrs.get("cache-control"))
    record("CORS 허용 헤더 없음(Origin 을 보내도)", None, hdrs.get("access-control-allow-origin"))
    code, _, hdrs = http("OPTIONS", args.base + "/mail/inbox", headers={"Origin": "http://localhost:8788"})
    record("OPTIONS /mail/inbox = 405 · 허용 헤더 없음", (405, None), (code, hdrs.get("access-control-allow-origin")))
    code, box2, _ = M.inbox(B["id"], M.auth(B, B["id"], since=mail_id1), since=mail_id1)
    record("since=m1 이면 m1 은 안 온다", None, find(box2, m1["message_id"]))

    code, body, _ = M.inbox(B["id"], M.auth(C, B["id"]))
    record("C 가 B 수신함(C 키 · for=B) = 401", 401, code, "why=%s" % why_of(body))
    code, body, _ = M.inbox(B["id"], M.auth(B, B["id"], ts=iso(time.time() - 600)))
    record("인증 ts 10분 전 = 401 auth_ts_window", (401, "auth_ts_window"), (code, why_of(body)))
    code, body, _ = M.inbox(B["id"], hb, since="ml_0000000000000000")
    record("B 헤더를 since 만 바꿔 재사용 = 401", 401, code, "verdict=%s" % ((body.get("detail") or {}).get("verdict")
                                                                         if isinstance(body, dict) else "?"))
    code, body, _ = M.inbox(B["id"], None)
    record("인증 헤더 없음 = 401/4", (401, 4), (code, code_of(body)))
    code, body, _ = M.inbox(B["id"], hb, since="ev_1")
    record("since 형식 오류 = 400/10", (400, 10), (code, code_of(body)))

    # ── 6. 답장 칸 ───────────────────────────────────────────────────────────
    print("\n== 우편 6. 답장 칸 — 새 대화 칸과 따로 ==")
    mb2c, sb2c, code, _, _ = M.send(B, C["id"], new_id(), letter("B 의 새 대화"))
    record("B→C 새 대화 = 201(B 새 대화 칸 소진)", 201, code)
    rb, _, code, body, _ = M.send(B, A["id"], T1, letter("답장입니다"), reply_to=m1["message_id"])
    record("B 가 m1 에 곧바로 답장 = 201(답장 칸)", 201, code, "body=%s" % (code_of(body) if code != 201 else ""))

    # ── 7. 광장 비노출 · 교차 재사용 ──────────────────────────────────────────
    print("\n== 우편 7. 광장 화면 비노출 · /events 교차 재사용 ==")
    needles = [m1["message_id"], T1, subj1, rb["message_id"]]
    for path in ("/rooms", "/rooms?closed=1", "/feed?sort=new", "/communities",
                 "/home?participant=" + A["id"], "/home?participant=" + B["id"]):
        code, body, _ = http("GET", args.base + path)
        text = json.dumps(body, ensure_ascii=False)
        record("%s 에 우편 0" % path, (200, False), (code, any(n in text for n in needles)))
    code, body, _ = http("POST", args.base + "/events", {
        "thread_id": T1, "category": "problem", "title": "", "body": render_post(m1, s1), "is_genesis": False})
    record("우편 문서를 /events 에 = 400/10", (400, 10), (code, code_of(body)))

    # ── 8. 읽음 · 영수 ───────────────────────────────────────────────────────
    print("\n== 우편 8. 읽음 표시 · 영수 · 남의 ack ==")
    code, body, _ = M.ack(C, C["id"], [mail_id1])
    record("C 가 A→B 우편에 ack = 200 · acked 0 · ignored 1", (200, 0, 1),
           (code, (body or {}).get("acked"), (body or {}).get("ignored")))
    code, body, _ = http("POST", args.base + "/mail/ack", {"for": C["id"], "mail_ids": [mail_id1], "thread_ids": [T1],
                                                         "ts": iso(), "signature": "x"})
    record("읽음 요청에 대화 칸(thread_ids) = 400/10(대화 단위 읽음은 계약에 없다)", (400, 10), (code, code_of(body)))
    code, box, _ = M.inbox(B["id"], M.auth(B, B["id"]))
    record("남의 ack 뒤 B unread_count 그대로 1", 1, box.get("unread_count") if isinstance(box, dict) else None)
    code, body, _ = M.ack(C, B["id"], [mail_id1])
    record("C 키로 for=B ack = 401", 401, code)
    code, body, _ = M.ack(B, B["id"], [mail_id1, "ml_9999999999999998"])
    record("B ack = 200 · acked 1 · ignored 1", (200, 1, 1),
           (code, (body or {}).get("acked"), (body or {}).get("ignored")))
    code, box, _ = M.inbox(B["id"], M.auth(B, B["id"]))
    record("ack 뒤 B unread_count = 0", 0, box.get("unread_count") if isinstance(box, dict) else None)
    code, boxa, _ = M.inbox(A["id"], M.auth(A, A["id"]))
    rc = [r for r in (boxa.get("receipts") or []) if r.get("message_id") == m1["message_id"]] \
        if isinstance(boxa, dict) else []
    record("A 영수에 m1(to=B)", [B["id"]], [r.get("to") for r in rc])
    first_ack = rc[0]["acked_at"] if rc else None
    ta = [t for t in (boxa.get("threads") or []) if t.get("thread_id") == T1] if isinstance(boxa, dict) else []
    record("A 는 B 의 답장을 미읽음 1 로 본다(대화 T1 · peer B)", (1, 1, B["id"]),
           (boxa.get("unread_count") if isinstance(boxa, dict) else None,
            ta[0].get("unread") if ta else None, ta[0].get("peer") if ta else None))
    code, body, _ = M.ack(B, B["id"], [mail_id1])
    record("다시 ack = acked 0(첫 시각 유지)", (200, 0), (code, (body or {}).get("acked")))
    code, boxa2, _ = M.inbox(A["id"], M.auth(A, A["id"], receipts_since=first_ack or ""),
                             receipts_since=first_ack or "")
    record("receipts_since=첫 시각 → m1 영수 다시 1(>= 경계 · 적대 6R #6 · 겹침은 클라이언트가 거른다)", 1,
           len([r for r in (boxa2.get("receipts") or []) if r.get("message_id") == m1["message_id"]])
           if isinstance(boxa2, dict) else "?")
    code, body, _ = M.ack(B, B["id"], [])
    record("빈 ack = 400/10", (400, 10), (code, code_of(body)))

    # ── 8-b. 읽음 재생 안전(적대 1R R1-1 → 4R R4-1 · 5R R5-2: **같은 요청 바이트 그대로** 재전송) ──────────
    print("\n== 우편 8-b. 같은 읽음 요청(같은 ts·서명)을 재생해도 뒤 도착 우편은 안 걸린다 ==")
    ts_r = iso()
    doc_r = {"acked": [mail_id1], "for": B["id"], "purpose": "agora-mail-ack-v3", "ts": ts_r}
    req_r = {"for": B["id"], "mail_ids": [mail_id1], "ts": ts_r,
             "signature": sign_bytes(B["key"], canonical_bytes(doc_r), args.workdir)}
    code, body, _ = http("POST", args.base + "/mail/ack", req_r)
    record("원 읽음 요청(m1) = 200", 200, code)
    for _ in range(3):
        mx, _, code, body, _ = M.send(A, B["id"], T1, letter("읽음 서명 뒤 도착"), reply_to=rb["message_id"])
        if code != 429:
            break
        time.sleep(2.2)
    record("A→B 답장(읽음 서명 뒤 도착) = 201", 201, code)
    mx_id = body.get("mail_id") if isinstance(body, dict) else None
    code, body, _ = http("POST", args.base + "/mail/ack", req_r)
    record("같은 요청 바이트 재전송 = 200 · acked 0(새 우편은 목록에 없다)", (200, 0), (code, (body or {}).get("acked")))
    code, boxb, _ = M.inbox(B["id"], M.auth(B, B["id"]))
    hit = find(boxb, mx["message_id"])
    record("  뒤 도착 우편 본문 그대로 · 미읽음 1", (True, 1),
           (bool(hit and "mail" in hit), boxb.get("unread_count") if isinstance(boxb, dict) else None))
    code, body, _ = M.ack(B, B["id"], [mx_id or ""])
    record("그 우편의 mail_id 로 ack = acked 1", (200, 1), (code, (body or {}).get("acked")))
    time.sleep(2.2)          # A 의 답장 간격(로컬 2초)을 비워 둔다 — 아래 10 의 「답장 5통」이 이 1통에 걸리지 않게

    # ── 9. 신호 우편 ─────────────────────────────────────────────────────────
    print("\n== 우편 9. 신호 우편(intent=signal) ==")
    TS = new_id()
    _, _, code, body, _ = M.send(A, C["id"], TS, {"intent": "signal", "items": [signal_item(signature="0" * 32)]})
    record("묶기 키 위조 = 400/10 signature_mismatch", (400, 10, "signature_mismatch"),
           (code, code_of(body), why_of(body)))
    _, _, code, body, _ = M.send(A, C["id"], TS, {"intent": "signal",
                                                   "items": [signal_item(first_seen=iso(time.time() - 8 * 86400))]})
    record("first_seen 8일 전 = 400/10", (400, 10), (code, code_of(body)))
    sig1, _, code, body, _ = M.send(A, C["id"], TS, {"intent": "signal", "items": [signal_item()]})
    if code == 429:
        record("신호 첫 통 = 201", 201, code, "(UTC 자정 직전 실행이 아니면 429 는 결함)")
    else:
        record("신호 첫 통 = 201(새 대화 칸이 찼어도 따로)", 201, code)
    _, _, code, body, hdrs = M.send(A, C["id"], TS, {"intent": "signal", "items": [signal_item(count=5)]})
    if code == 201:
        _, _, code, body, hdrs = M.send(A, C["id"], TS, {"intent": "signal", "items": [signal_item(count=6)]})
    record("같은 날 두 번째 신호 = 429 mail_signal_day", (429, 7, "mail_signal_day"),
           (code, code_of(body), (body.get("detail") or {}).get("limit") if isinstance(body, dict) else None))
    code, boxc, _ = M.inbox(C["id"], M.auth(C, C["id"]))
    record("C 수신함에 신호 있음", True, find(boxc, sig1["message_id"]) is not None)
    record("C unread_count = 1(신호는 세지 않는다 · B 우편 1)", 1,
           boxc.get("unread_count") if isinstance(boxc, dict) else None)

    # 읽음 뒤 본문 삭제 — B 의 ack 뒤에 POST /mail 이 왔다(신호) → 덤 삭제가 m1 본문을 지웠어야 한다.
    code, box, _ = M.inbox(B["id"], M.auth(B, B["id"]))
    it = find(box, m1["message_id"])
    record("읽음 뒤 다음 적재에서 m1 본문 삭제 = 머리만", (True, False, False),
           (bool(it and it.get("purged")), "mail" in (it or {}), "signature" in (it or {})))
    code, body, _ = M.post(m1, s1)
    record("본문 삭제 뒤 같은 서명 재게시 = 200(새 배달 0)", (200, mail_id1),
           (code, body.get("mail_id") if isinstance(body, dict) else None))

    # ── 9-b. 일일 보고(intent=daily · 명세 §1-2 · 증보 8) ────────────────────
    print("\n== 우편 9-b. 일일 보고(intent=daily) ==")
    TDy = new_id()
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    daily = {"day": today, "version": {"host": "1.1.7", "pack": "1.1.7"}, "os": "windows-11",
             "seats": {"count": 3, "roles": ["cso", "master", "worker"]},
             "doctor": {"ok": 12, "warn": 1, "fail": 1, "skip": 1,
                        "warn_ids": ["dept-awakening-seed"], "fail_ids": ["runtime-seal"]},
             "depts": {"active": 0, "tombstones": 1}, "owner_note": ""}
    _, _, code, body, _ = M.send(A, C["id"], TDy, {"intent": "daily", "daily": dict(daily, note="자유문")})
    record("일일 보고 모르는 칸 = 400/10", (400, 10), (code, code_of(body)))
    dy1, _, code, body, _ = M.send(A, C["id"], TDy, {"intent": "daily", "daily": daily})
    record("일일 보고 첫 통 = 201(신호 버킷과 따로)", 201, code)
    _, _, code, body, _ = M.send(A, C["id"], TDy, {"intent": "daily", "daily": dict(daily, owner_note="둘째")})
    record("같은 날 두 번째 일일 보고 = 429 mail_daily_day", (429, 7, "mail_daily_day"),
           (code, code_of(body), (body.get("detail") or {}).get("limit") if isinstance(body, dict) else None))
    code, boxc, _ = M.inbox(C["id"], M.auth(C, C["id"]))
    record("C 수신함에 일일 보고 있음 · unread_count 그대로 1(세지 않는다)", (True, 1),
           (find(boxc, dy1["message_id"]) is not None, boxc.get("unread_count") if isinstance(boxc, dict) else None))

    # ── 10. 연속 규칙 ────────────────────────────────────────────────────────
    print("\n== 우편 10. 같은 수신자 연속 5통 → 쿨다운 · 답장이 오면 풀린다 ==")
    TD = new_id()
    md1, _, code, _, _ = M.send(D, A["id"], TD, letter("D 의 질문"))
    record("D→A 새 대화 = 201", 201, code)
    codes = []
    last = None
    for i in range(5):
        if i:
            time.sleep(2.2)          # 로컬 답장 간격 = 2초(run-local --var)
        last, _, code, body, _ = M.send(A, D["id"], TD, letter("A 의 답 %d" % (i + 1)), reply_to=md1["message_id"])
        codes.append(code)
    record("A→D 답장 5통 = 전부 201", [201] * 5, codes)
    time.sleep(2.2)
    _, _, code, body, hdrs = M.send(A, D["id"], TD, letter("A 의 답 6"), reply_to=md1["message_id"])
    ra = int(hdrs.get("retry-after") or 0)
    record("6통째 = 429 mail_consecutive", (429, 7, "mail_consecutive"),
           (code, code_of(body), (body.get("detail") or {}).get("limit") if isinstance(body, dict) else None))
    record("  Retry-After ≈ 24시간(23h50m~24h)", True, 86400 - 600 <= ra <= 86400, "retry-after=%s" % ra)
    _, _, code, _, _ = M.send(D, A["id"], TD, letter("D 의 답"), reply_to=last["message_id"])
    record("D 가 답장 = 201", 201, code)
    time.sleep(2.2)
    _, _, code, _, _ = M.send(A, D["id"], TD, letter("A 의 답 7"), reply_to=md1["message_id"])
    record("상대 답장 뒤 A 다시 보냄 = 201(쿨다운 풀림)", 201, code)

    # ── 11. 보존 기한(TTL) — ★마지막 POST 뒤에 잰다(덤 삭제가 본문을 먼저 지우지 않게) ──
    print("\n== 우편 11. 보존 기한 지난 본문 = 머리만 ==")
    rc_, out = d1("UPDATE mail SET keep_until = '2001-01-01T00:00:00.000Z' WHERE message_id = '%s'"
                  % mb2c["message_id"])
    record("로컬 D1 keep_until 과거로(--local)", 0, rc_, out[-80:] if rc_ else "")
    code, boxc, _ = M.inbox(C["id"], M.auth(C, C["id"]))
    it = find(boxc, mb2c["message_id"])
    record("C 수신함 = 200", 200, code)
    record("기한 지난 우편 = purged:true 머리만(mail·signature 0)", (True, False, False),
           (bool(it and it.get("purged")), "mail" in (it or {}), "signature" in (it or {})))
    record("  머리 칸 = mail_id·from·message_id·created_at·purged",
           ["created_at", "from", "mail_id", "message_id", "purged"], sorted((it or {}).keys()))
    record("기한 지난 우편은 unread_count 에서 빠진다 = 0", 0,
           boxc.get("unread_count") if isinstance(boxc, dict) else None)

    # ── 12. 받는 이 축 상한(적대 6R #2 · 명세 §4-1) — ★TTL(11) 뒤: 여기 POST 의 덤 삭제가 11 의 측정을 흔들지 않게 ──
    print("\n== 우편 12. 받는 이 축 — 미읽음 상한 · 하루 유입 버킷 ==")
    E = keygen(args.workdir, "mail-e")
    code, _ = register(args.base, E, args.workdir)
    record("등록 %s = 201" % E["id"], 201, code)
    rc, out = d1("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 1000) "
                 "INSERT INTO mail (message_id, thread_id, from_id, to_id, prev, reply_to, intent, hash, bytes, "
                 "canonical, signature, keep_until, created_at) SELECT printf('%%032x', i), printf('%%032x', i), "
                 "'zz-fill', '%s', 'genesis', NULL, 'notice', 'h', 1, '{}', 's', '2099-01-01T00:00:00.000Z', "
                 "'2026-01-01T00:00:00.000Z' FROM n;" % E["id"])
    record("E 앞으로 미읽음 1000통 채우기(로컬 D1)", 0, rc, out[-80:] if rc else "")
    _, _, code, body, hdrs = M.send(C, E["id"], new_id(), letter("가득 찬 수신함"))
    record("미읽음 상한 = 429 mail_inbox_full · why recipient_inbox_full", (429, "mail_inbox_full", "recipient_inbox_full"),
           (code, (body.get("detail") or {}).get("limit") if isinstance(body, dict) else None, why_of(body)))
    _, _, code, body, _ = M.send(C, E["id"], new_id(), {"intent": "daily", "daily": {"day": iso()[:10]}})
    record("  일일 보고는 미읽음 상한을 안 탄다 = 201", 201, code)
    rc, _ = d1("DELETE FROM mail WHERE to_id = '%s' AND from_id = 'zz-fill';" % E["id"])
    win = int(time.time() // 86400) * 86400
    rc2, _ = d1("INSERT INTO rate_windows (bucket, window_start, count) VALUES ('gmail-in-day:%s', %d, 200) "
                "ON CONFLICT(bucket, window_start) DO UPDATE SET count = 200;" % (E["id"], win))
    record("E 하루 유입 칸 200 채우기(로컬 D1)", (0, 0), (rc, rc2))
    _, _, code, body, _ = M.send(C, E["id"], new_id(), letter("하루 유입 초과"))
    record("하루 유입 201통째 = 429 mail_in_day", (429, 7, "mail_in_day"),
           (code, code_of(body), (body.get("detail") or {}).get("limit") if isinstance(body, dict) else None))

    ok = all(checks)
    print("\n== 우편 결과: %s (%d/%d) ==" % ("PASS" if ok else "FAIL", sum(checks), len(checks)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
