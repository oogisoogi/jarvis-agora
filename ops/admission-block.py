#!/usr/bin/env python3
"""받아들이기 차단(은퇴) 실행 절차 — 설계 docs/design/key-lifecycle/DESIGN-v3.md §5-3 을 스크립트 하나로.

★불가역(계약: 차단은 되돌리지 않는다 · 기술적 되돌림 = 행 삭제 = master). 원격(--remote) 실행은 master 만.
★기본은 **계획만 출력**한다. 실제로 쓰려면 `--execute` 를 붙인다.

    # 스키마 점검(배포 전 게이트 · 표 1 + 트리거 4 가 없으면 rc 3)
    python3 ops/admission-block.py --target main --remote --check-schema
    # 계획(사전 확인까지 · 쓰기 0)
    python3 ops/admission-block.py --target main  --remote --participant <id> --fingerprint SHA256:…
    # 실행
    python3 ops/admission-block.py --target trial --remote --participant <id> --fingerprint SHA256:… --execute
    # 로컬 시험(wrangler dev 의 로컬 D1)
    python3 ops/admission-block.py --target main --local --participant alice --fingerprint SHA256:… --execute

순서(§5-3 · 적대 검증 impl-r1 반영):
  1. 대상 D1·설정 명시 — --target 이 설정 파일(절대경로)을 고르고, 그 파일의 name·database_id 가 기대값과 같아야 한다(오배포 게이트).
  1b. **스키마 점검** — admission_blocks 표 + 트리거 4 가 이름 그대로 있어야 한다(표만 있고 트리거가 없으면 행은 들어가도 막는 것이 0).
  2. 사전 확인 — id 로 한 번, 지문으로 한 번 **따로** 본다(r2 D2-4):
       registered(본 릴레이의 우리 id) = id 행 1(지문 일치·폐기 아님) · 지문 행 = 그 id 하나
       absent(시험 릴레이의 우리 id)   = id 행 0 · 지문 행 0
       그 밖 = **경보 · 중단**
     + **우리 신원 교차 대조** — 입력 id·지문 중 하나라도 상주 participant.json 의 우리 값이면 둘 다 우리 값이어야 한다
       (시험 릴레이는 「id 행 0 · 지문 행 0」이라 오타를 못 거른다 · 한 글자 오타 = 불가역 헛차단 + id PK 선점).
     + 시험 릴레이에서 registered 모양(원격 실측용 임시 참가자)은 id 머리 `adm-t` 만 허용.
  3. 실행 — INSERT INTO admission_blocks(…) VALUES (id, 지문, 지금, 'retired')
  종료 코드: 0 실행·대조 성공 · 11 이미 차단(쓰지 않음·대조 없음) · 10 계획만(쓰기 0) · 3 중단(쓰기 0) · 4 쓰기 뒤 대조 불일치 ·
            5 쓰기 뒤 대조 미완 · 6 쓰기 결과 불명(재실행으로 확인).
  4. 사후 대조 — 실행 전에 있던 명부·체크포인트 행이 **그대로**다(새 행은 동시 등록일 수 있어 따로 표시) ·
     (--relay-url 은 대상별 고정 주소만) GET /participants/* 세 파일 바이트 동일(캐시 우회). 쓰기 뒤 대조가 실패하면
     「차단 행 있음 · 대조 미완」(rc 5)으로 말한다 — 트레이스백으로 끝내지 않는다.
  5. **두 D1 모두 끝나기 전에는 「차단 완료」라고 보고하지 않는다** — 이 스크립트는 D1 하나의 결과만 말한다.
  6. 본 릴레이에서 우리 상주 id 를 막을 때는 상주(launchd kr.godmeyou.agora.resident)를 먼저 멈춘다 — 떠 있거나
     상주 id 파일을 못 읽으면 중단(fail-closed).
  (§5-2) 대상이 운영자이고 차단 뒤 현역 운영자가 0명이 되면 --allow-no-operator 없이는 중단.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELAY = os.path.join(ROOT, "relay")
TARGETS = {
    # target: (설정 파일, 기대 name, 기대 database_name, 기대 database_id, 공개 주소)
    "main": ("wrangler.jsonc", "agora-relay", "agora-relay", "cbdfaaef-a344-4a62-a4f2-381334b9f3a9",
             "https://agora.godmeyou.kr"),
    "trial": ("wrangler.next.jsonc", "agora-relay-next", "agora-relay-next", "4bfe34f0-6b43-4b14-b727-89019c94ceb4",
              "https://agora-relay-next.oogisoogi.workers.dev"),
}
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,63}")          # index.ts /register 의 id 규칙과 같다(fullmatch)
FP_RE = re.compile(r"SHA256:[A-Za-z0-9+/]{43}")                 # ed25519 지문(패딩 없는 base64 43자 · fullmatch)
ISO_MS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")
LOCAL_URL_RE = re.compile(r"http://(127\.0\.0\.1|localhost)(:\d+)?/?")
TEST_ID_PREFIX = "adm-t"
SCHEMA = {("table", "admission_blocks"), ("trigger", "participants_admission_block"),
          ("trigger", "events_admission_block"), ("trigger", "checkpoints_admission_block_ins"),
          ("trigger", "checkpoints_admission_block_upd")}
RESIDENT_LABEL = "kr.godmeyou.agora.resident"
RESIDENT_ID_FILE = os.path.expanduser("~/axdev/agora-resident/.agora/participant.json")


class Stop(Exception):
    """사전 확인이 기대와 다르다 — 쓰지 않고 멈춘다."""


def gate_config(target: str) -> tuple[str, str]:
    """(설정 절대경로, database_name). 설정의 name·D1 이 기대와 다르면 멈춘다(09-17 오배포 사고 계보)."""
    fname, want_name, want_db, want_id, _url = TARGETS[target]
    path = os.path.join(RELAY, fname)
    text = open(path, encoding="utf-8").read()
    got = {k: re.findall(r'^\s*"%s"\s*:\s*"([^"]+)"' % k, text, re.M)
           for k in ("name", "database_name", "database_id")}
    if got["name"] != [want_name] or got["database_name"] != [want_db] or got["database_id"] != [want_id]:
        raise Stop("설정 게이트 실패: %s 의 name/database 가 기대(%s·%s)와 다르다: %s" % (path, want_name, want_id, got))
    return path, want_db


def d1(config: str, db: str, where: str, sql: str, persist: str | None = None) -> list[dict]:
    """wrangler d1 execute 한 번 → 결과 행 목록. 값은 호출 전에 정규식으로 검증된 것만 SQL 에 넣는다."""
    cmd = [os.path.join(RELAY, "node_modules/.bin/wrangler"), "d1", "execute", db, where,
           "--config", config, "--json", "--command", sql]
    if persist and where == "--local":
        cmd += ["--persist-to", persist]
    env = {k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"}
    r = subprocess.run(cmd, cwd=RELAY, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise Stop("d1 execute 실패(rc %d): %s" % (r.returncode, (r.stdout + r.stderr)[-600:]))
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise Stop("d1 execute 출력이 JSON 이 아니다: " + r.stdout[-300:]) from None
    rows: list[dict] = []
    for part in out:
        if not part.get("success", True):
            raise Stop("d1 질의 실패: %s" % part)
        rows.extend(part.get("results") or [])
    return rows


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def check_schema(run) -> None:
    got = {(r["type"], r["name"]) for r in run(
        "SELECT type, name FROM sqlite_master WHERE type IN ('table','trigger') AND name LIKE '%admission%'")}
    if got != SCHEMA:
        raise Stop("스키마 점검 실패 — 표 1·트리거 4 가 이름 그대로여야 한다. 없음 %s · 뜻밖 %s"
                   % (sorted(SCHEMA - got), sorted(got - SCHEMA)))


def rows_of(run) -> tuple[set, set]:
    """명부·체크포인트 표의 행 집합(칸 전부) — 차단은 기존 행을 한 칸도 바꾸면 안 된다."""
    p = run("SELECT participant_id, display_name, key_type, key_b64, fingerprint, is_operator, revoked_at, created_at"
            " FROM participants")
    c = run("SELECT checkpoint, signer, signature, signed_at FROM roster_checkpoints")
    return ({json.dumps(r, sort_keys=True, ensure_ascii=False) for r in p},
            {json.dumps(r, sort_keys=True, ensure_ascii=False) for r in c})


def relay_files(url: str) -> dict:
    """공개 GET 세 파일 바이트. ★캐시 우회(질의 문자열 + no-cache) — 캐시된 옛 바이트로 「동일」이라 말하지 않게."""
    out = {}
    for name in ("allowed_signers", "revoked_keys", "operators"):
        req = urllib.request.Request("%s/participants/%s?nocache=%d" % (url.rstrip("/"), name, time.time_ns()),
                                     headers={"User-Agent": "agora-admission-block/1.0",
                                              "Cache-Control": "no-cache", "Pragma": "no-cache"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                out[name] = r.read()
        except (OSError, ValueError, http.client.HTTPException) as e:
            raise Stop("명부 파일 GET 실패(%s): %s — 공개 주소가 꺼진 릴레이면 --relay-url 을 빼라" % (name, e)) from None
    return out


def resident_running() -> bool:
    r = subprocess.run(["launchctl", "print", "gui/%d/%s" % (os.getuid(), RESIDENT_LABEL)],
                       capture_output=True, text=True)
    return r.returncode == 0


def our_identity() -> tuple[str, str] | None:
    try:
        p = json.load(open(RESIDENT_ID_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid, fp = p.get("id"), p.get("key_fingerprint")
    return (pid, fp) if isinstance(pid, str) and isinstance(fp, str) else None


def classify(shape: str, pid: str, fp: str, by_id: list[dict], by_fp: list[dict]) -> str:
    """사전 확인 네 갈래(r2 D2-4). 정상이면 'ok', 아니면 멈출 사유."""
    if len(by_id) > 1:
        return "id 행이 2개 이상 — 스키마가 기대와 다르다"
    if by_id and by_id[0]["fingerprint"] != fp:
        return "경보: id 행의 지문이 다르다 — 누가 다른 키로 이 id 를 선점했다"
    others = [r["participant_id"] for r in by_fp if r["participant_id"] != pid]
    if others:
        return "경보: 이 지문이 다른 이름(%s)에 붙어 있다 — 누가 이 키로 다른 이름을 등록했다" % others
    if by_id and by_id[0].get("revoked_at"):
        return "이미 폐기된 참가자다 — 차단이 아니라 폐기 상태를 먼저 보고한다"
    if shape == "registered" and not by_id:
        return "기대 모양(id 행 1)인데 id 행이 없다"
    if shape == "absent" and by_id:
        return "경보: 기대 모양(id 행 0)인데 이 id 가 (이 키로) 등록돼 있다"
    return "ok"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="받아들이기 차단(은퇴) — 설계 §5-3")
    ap.add_argument("--target", required=True, choices=sorted(TARGETS))
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--remote", action="store_true")
    where.add_argument("--local", action="store_true")
    ap.add_argument("--persist-to", default=None, help="(--local) wrangler dev 의 로컬 상태 폴더")
    ap.add_argument("--check-schema", action="store_true", help="표 1·트리거 4 만 확인하고 끝낸다(배포 전 게이트)")
    ap.add_argument("--participant")
    ap.add_argument("--fingerprint")
    ap.add_argument("--relay-url", default=None,
                    help="사후 대조에 공개 GET 세 파일 바이트도 쓴다(원격 = 대상의 고정 주소만 · 로컬 = 127.0.0.1)")
    ap.add_argument("--execute", action="store_true", help="없으면 계획만(쓰기 0)")
    ap.add_argument("--allow-no-operator", action="store_true")
    ap.add_argument("--allow-resident-running", action="store_true")
    ap.add_argument("--blocked-at", default=None, help="(--local 시험 전용) 효력 시각 고정 — 기본 = 지금")
    ap.add_argument("--shape", choices=("registered", "absent"), default=None,
                    help="사전 확인의 기대 모양 — 기본 = 본(main) registered · 시험(trial) absent. "
                         "시험 릴레이의 원격 실측(T16)에서 임시 참가자(id 머리 adm-t)를 막을 때만 registered")
    ap.add_argument("--not-ours", action="store_true",
                    help="우리 신원이 아닌 id·지문을 막는다(시험·일반 참가자) — 없으면 입력이 우리 신원과 맞아야 한다")
    ap.add_argument("--test-interpose-sql", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--without-identity-file", action="store_true",
                    help="상주 신원 파일 없이 진행(겹침·상주 검사 0 — 사람이 따로 대조했을 때만)")
    a = ap.parse_args(argv)
    attempted = written = False
    try:
        config, db = gate_config(a.target)
        wflag = "--remote" if a.remote else "--local"
        run = lambda sql: d1(config, db, wflag, sql, a.persist_to)       # noqa: E731
        print("대상 = %s · D1 %s(%s) · 설정 %s" % (a.target, db, wflag, config))
        if a.check_schema:
            check_schema(run)
            print("스키마 점검: 표 1 · 트리거 4 있음")
            return 0
        # ★입력 검증을 DB 보다 먼저 — 틀린 입력은 원격에 한 번도 닿지 않고 멈춘다.
        if not (a.participant and ID_RE.fullmatch(a.participant)):
            raise Stop("participant 형식이 아니다")
        if not (a.fingerprint and FP_RE.fullmatch(a.fingerprint)):
            raise Stop("fingerprint 형식이 아니다(SHA256:+43자)")
        if a.test_interpose_sql is not None and not a.local:
            raise Stop("--test-interpose-sql 은 --local 시험 전용이다")
        if a.blocked_at is not None and not (a.local and ISO_MS_RE.fullmatch(a.blocked_at)):
            raise Stop("--blocked-at 은 --local 시험 전용이고 밀리초 ISO(Z) 여야 한다")
        want_url = TARGETS[a.target][4]
        if a.relay_url and not ((a.remote and a.relay_url.rstrip("/") == want_url)
                                or (a.local and LOCAL_URL_RE.fullmatch(a.relay_url))):
            raise Stop("--relay-url 은 원격이면 대상(%s)의 고정 주소 %s · 로컬이면 127.0.0.1 이어야 한다" % (a.target, want_url))
        shape = a.shape or ("registered" if a.target == "main" else "absent")
        if a.target == "trial" and shape == "registered" and not a.participant.startswith(TEST_ID_PREFIX):
            raise Stop("시험 릴레이의 registered 모양은 원격 실측용 임시 참가자(id 머리 %s)만 허용한다" % TEST_ID_PREFIX)
        ours = our_identity()
        if ours is None and not a.without_identity_file:
            # ★--not-ours 여도 멈춘다 — 파일이 없으면 「우리 것과 겹치는지」도 「상주가 떠 있는지」도 못 잰다(impl-r2 Fable 1).
            raise Stop("상주 신원 파일(%s)을 못 읽었다 — 대조 불가(사람이 따로 대조했다면 --without-identity-file)"
                       % RESIDENT_ID_FILE)
        if not a.not_ours:
            if ours is None:
                raise Stop("우리 신원 대조 불가 — 우리 id 를 막으려면 신원 파일이 있어야 한다")
            if (a.participant, a.fingerprint) != ours:
                raise Stop("입력 id·지문이 우리 신원(%s · %s)과 다르다 — 오타면 고치고, 다른 참가자면 --not-ours" % ours)
        elif ours and (a.participant == ours[0] or a.fingerprint == ours[1]):
            raise Stop("--not-ours 인데 입력이 우리 id 또는 지문과 겹친다")
        check_schema(run)
        print("스키마 점검: 표 1 · 트리거 4 있음")

        already = run("SELECT participant_id, fingerprint, blocked_at FROM admission_blocks"
                      " WHERE participant_id = %s OR fingerprint = %s" % (q(a.participant), q(a.fingerprint)))
        if already:
            if len(already) == 1 and already[0]["participant_id"] == a.participant \
                    and already[0]["fingerprint"] == a.fingerprint:
                # ★rc 0 이 아니다 — 재실행 「성공」은 이전 실행의 대조 실패(4·5·6)가 풀렸다는 증거가 아니다(impl codex).
                print("이미 차단돼 있다(%s) — 쓰지 않음 · 이전 실행의 사후 대조를 대신하지 않는다(rc 11)" % already[0]["blocked_at"])
                return 11
            raise Stop("차단 표에 이 id·지문과 **엇갈린** 행이 있다: %s" % already)
        by_id = run("SELECT participant_id, fingerprint, revoked_at, is_operator FROM participants"
                    " WHERE participant_id = %s" % q(a.participant))
        by_fp = run("SELECT participant_id FROM participants WHERE fingerprint = %s" % q(a.fingerprint))
        verdict = classify(shape, a.participant, a.fingerprint, by_id, by_fp)
        print("사전 확인(%s): id 행 %d · 지문 행 %s → %s" % (shape, len(by_id), [r["participant_id"] for r in by_fp], verdict))
        if verdict != "ok":
            raise Stop(verdict)
        if by_id and by_id[0].get("is_operator"):
            left = run("SELECT COUNT(*) AS n FROM participants p WHERE p.is_operator = 1 AND p.revoked_at IS NULL"
                       " AND p.participant_id != %s AND NOT EXISTS (SELECT 1 FROM admission_blocks b"
                       " WHERE b.participant_id = p.participant_id)" % q(a.participant))[0]["n"]
            print("운영자다 — 차단 뒤 남는 현역 운영자 %d명" % left)
            if left == 0 and not a.allow_no_operator:
                raise Stop("차단 뒤 현역 운영자가 0명이 된다 — --allow-no-operator 로 명시해야 한다")
        if a.remote and a.target == "main" and ours and a.participant == ours[0] and resident_running() \
                and not a.allow_resident_running:
            raise Stop("우리 상주(%s)가 떠 있다 — 먼저 멈춘다(launchctl bootout gui/%d/%s)"
                       % (RESIDENT_LABEL, os.getuid(), RESIDENT_LABEL))

        p0, c0 = rows_of(run)
        files0 = relay_files(a.relay_url) if a.relay_url else None
        blocked_at = a.blocked_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        # ★사전 확인의 모양 조건을 **같은 INSERT 문 안에서** 다시 건다(원자적 조건부 INSERT · impl codex HIGH).
        #   사전 SELECT 와 INSERT 사이에 누가 이 키로 다른 이름을 등록하면 행이 0 이 되고, 아래 재조회가 그것을 잡는다
        #   (등록 트리거는 차단 커밋 **뒤**의 등록만 막으므로, 그 사이에 들어온 이름은 이 조건만이 막는다).
        if shape == "registered":
            cond = ("EXISTS (SELECT 1 FROM participants WHERE participant_id = %s AND fingerprint = %s AND revoked_at IS NULL)"
                    " AND NOT EXISTS (SELECT 1 FROM participants WHERE fingerprint = %s AND participant_id != %s)"
                    % (q(a.participant), q(a.fingerprint), q(a.fingerprint), q(a.participant)))
        else:
            cond = ("NOT EXISTS (SELECT 1 FROM participants WHERE participant_id = %s OR fingerprint = %s)"
                    % (q(a.participant), q(a.fingerprint)))
        sql = ("INSERT INTO admission_blocks (participant_id, fingerprint, blocked_at, reason) SELECT %s, %s, %s, 'retired'"
               " WHERE %s" % (q(a.participant), q(a.fingerprint), q(blocked_at), cond))
        if not a.execute:
            print("계획만 — 쓰지 않았다(rc 10): " + sql)
            print("실행 전 명부 %d행 · 체크포인트 %d행" % (len(p0), len(c0)))
            return 10          # ★계획은 0 이 아니다 — --execute 를 빠뜨린 호출을 성공으로 읽지 않게(impl-r2 agy 1)
        if a.test_interpose_sql:
            run(a.test_interpose_sql)      # (--local 시험 전용) 사전 확인과 INSERT 사이에 끼어드는 쓰기를 재현한다
        print("실행 SQL: " + sql)
        attempted = True       # ★run 앞에 세운다 — 원격이 커밋한 뒤 CLI 가 실패해도 「안 썼다」고 말하지 않게(impl-r2 Fable 2)
        run(sql)
        written = True
        got = run("SELECT blocked_at FROM admission_blocks WHERE participant_id = %s AND fingerprint = %s"
                  % (q(a.participant), q(a.fingerprint)))
        if not got:
            written = attempted = False    # 0행이 확정됐다 — 「결과 불명」이 아니라 「안 썼다」
            raise Stop("조건부 INSERT 가 0행 — 사전 확인 뒤 모양이 바뀌었다(누가 이 id·키로 등록했을 수 있다) · 경보 · 사전 확인부터 다시")
        p1, c1 = rows_of(run)
        kept = p0 <= p1 and c0 <= c1
        new_rows = len(p1 - p0) + len(c1 - c0)
        files1 = relay_files(a.relay_url) if a.relay_url else None
        same_files = files1 == files0
        print("실행: 차단 행 %s · 기존 명부·체크포인트 행 %s%s%s"
              % ("있음(%s)" % got[0]["blocked_at"] if got else "★없음",
                 "그대로" if kept else "★바뀜",
                 " · 새 행 %d(동시 등록 가능 — 차단과 무관한지 확인)" % new_rows if new_rows else "",
                 "" if files0 is None else " · 명부 세 파일 " + ("동일" if same_files else "★달라짐")))
        print("⚠이 D1 하나의 결과다 — 두 D1(본·시험) 모두 끝나기 전에는 「차단 완료」라고 보고하지 않는다(§5-3-5).")
        if kept and not same_files and new_rows:
            # 동시 등록이 있으면 파일 차이의 원인을 이 스크립트가 가를 수 없다 — 성공이라 하지 않고 「대조 미완」(impl codex MED).
            print("동시 등록 %d행 때문에 명부 파일 대조를 끝내지 못했다 — 사람이 새 행·파일 차이를 대조한다(rc 5)" % new_rows)
            return 5
        return 0 if (kept and same_files) else 4
    except Stop as e:
        if written:
            print("차단 행은 썼다 · 사후 대조 미완: %s" % e)
            return 5
        if attempted:
            print("쓰기 결과 불명(쓰기 명령이 실패했지만 원격이 이미 커밋했을 수 있다): %s — 같은 명령을 다시 돌려 "
                  "「이미 차단」 또는 엇갈림으로 확인한다" % e)
            return 6
        print("중단: %s" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
