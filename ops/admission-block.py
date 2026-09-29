#!/usr/bin/env python3
"""받아들이기 차단(은퇴) 실행 절차 — 설계 docs/design/key-lifecycle/DESIGN-v3.md §5-3 을 스크립트 하나로.

★불가역(계약: 차단은 되돌리지 않는다 · 기술적 되돌림 = 행 삭제 = master). 원격(--remote) 실행은 master 만.
★기본은 **계획만 출력**한다. 실제로 쓰려면 `--execute` 를 붙인다.

    # 계획(사전 확인까지 · 쓰기 0)
    python3 ops/admission-block.py --target main  --remote --participant <id> --fingerprint SHA256:…
    # 실행
    python3 ops/admission-block.py --target trial --remote --participant <id> --fingerprint SHA256:… --execute
    # 로컬 시험(wrangler dev 의 로컬 D1)
    python3 ops/admission-block.py --target main --local --participant alice --fingerprint SHA256:… --execute

순서(§5-3):
  1. 대상 D1·설정 명시 — --target 이 설정 파일(절대경로)을 고르고, 그 파일의 name·database_id 가 기대값과 같아야 한다(오배포 게이트).
  2. 사전 확인 — id 로 한 번, 지문으로 한 번 **따로** 본다(r2 D2-4):
       본 릴레이 정상 = id 행 1(지문 일치·폐기 아님) · 지문 행 = 그 id 하나
       시험 릴레이 정상 = id 행 0 · 지문 행 0
       그 밖(id 행 지문 불일치 · 지문이 다른 이름에 붙음 · 기대와 다른 모양) = **경보 · 중단**
  3. 실행 — INSERT INTO admission_blocks(…) VALUES (id, 지문, 지금, 'retired')
  4. 사후 대조 — 명부 표(participants 전 행)·체크포인트 표가 실행 전과 **같다** · (--relay-url 이 있으면) GET /participants/* 세 파일 바이트 동일
  5. **두 D1 모두 끝나기 전에는 「차단 완료」라고 보고하지 않는다** — 이 스크립트는 D1 하나의 결과만 말한다.
  6. 본 릴레이에서 우리 상주 id 를 막을 때는 상주(launchd kr.godmeyou.agora.resident)를 먼저 멈춘다 — 떠 있으면 중단.
  (§5-2) 대상이 운영자이고 차단 뒤 현역 운영자가 0명이 되면 --allow-no-operator 없이는 중단.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELAY = os.path.join(ROOT, "relay")
TARGETS = {
    # target: (설정 파일, 기대 name, 기대 database_name, 기대 database_id)
    "main": ("wrangler.jsonc", "agora-relay", "agora-relay", "cbdfaaef-a344-4a62-a4f2-381334b9f3a9"),
    "trial": ("wrangler.next.jsonc", "agora-relay-next", "agora-relay-next", "4bfe34f0-6b43-4b14-b727-89019c94ceb4"),
}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")        # index.ts /register 의 id 규칙과 같다
FP_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")                # ed25519 지문(패딩 없는 base64 43자)
RESIDENT_LABEL = "kr.godmeyou.agora.resident"
RESIDENT_ID_FILE = os.path.expanduser("~/axdev/agora-resident/.agora/participant.json")


class Stop(Exception):
    """사전 확인이 기대와 다르다 — 쓰지 않고 멈춘다."""


def gate_config(target: str) -> tuple[str, str]:
    """(설정 절대경로, database_name). 설정의 name·D1 이 기대와 다르면 멈춘다(09-17 오배포 사고 계보)."""
    fname, want_name, want_db, want_id = TARGETS[target]
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
    r = subprocess.run(cmd, cwd=RELAY, capture_output=True, text=True, env=env)
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


def snapshot(run) -> str:
    """명부·체크포인트 표 전체의 해시 — 차단은 이 둘을 한 바이트도 바꾸면 안 된다."""
    p = run("SELECT participant_id, display_name, key_type, key_b64, fingerprint, is_operator, revoked_at, created_at"
            " FROM participants ORDER BY participant_id")
    c = run("SELECT checkpoint, signer, signature, signed_at FROM roster_checkpoints ORDER BY checkpoint")
    return hashlib.sha256(json.dumps([p, c], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def relay_files(url: str) -> str:
    h = hashlib.sha256()
    for name in ("allowed_signers", "revoked_keys", "operators"):
        req = urllib.request.Request(url.rstrip("/") + "/participants/" + name,
                                     headers={"User-Agent": "agora-admission-block/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            h.update(name.encode() + b"\0" + r.read() + b"\0")
    return h.hexdigest()


def resident_running() -> bool:
    r = subprocess.run(["launchctl", "print", "gui/%d/%s" % (os.getuid(), RESIDENT_LABEL)],
                       capture_output=True, text=True)
    return r.returncode == 0


def our_resident_id() -> str | None:
    try:
        return json.load(open(RESIDENT_ID_FILE, encoding="utf-8")).get("id")
    except (OSError, ValueError):
        return None


def classify(target: str, pid: str, fp: str, by_id: list[dict], by_fp: list[dict]) -> str:
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
    if target == "main" and not by_id:
        return "본 릴레이인데 id 행이 없다 — 기대 모양(id 행 1)과 다르다"
    if target == "trial" and by_id:
        return "경보: 시험 릴레이에 이 id 가 (이 키로) 등록돼 있다 — 기대 모양(id 행 0)과 다르다"
    return "ok"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="받아들이기 차단(은퇴) — 설계 §5-3")
    ap.add_argument("--target", required=True, choices=sorted(TARGETS))
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--remote", action="store_true")
    where.add_argument("--local", action="store_true")
    ap.add_argument("--persist-to", default=None, help="(--local) wrangler dev 의 로컬 상태 폴더")
    ap.add_argument("--participant", required=True)
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--relay-url", default=None, help="사후 대조에 공개 GET /participants/* 바이트도 쓴다")
    ap.add_argument("--execute", action="store_true", help="없으면 계획만(쓰기 0)")
    ap.add_argument("--allow-no-operator", action="store_true")
    ap.add_argument("--allow-resident-running", action="store_true")
    ap.add_argument("--blocked-at", default=None, help="(시험용) 효력 시각 고정 — 기본 = 지금")
    a = ap.parse_args(argv)
    try:
        if not ID_RE.match(a.participant):
            raise Stop("participant 형식이 아니다")
        if not FP_RE.match(a.fingerprint):
            raise Stop("fingerprint 형식이 아니다(SHA256:+43자)")
        config, db = gate_config(a.target)
        wflag = "--remote" if a.remote else "--local"
        run = lambda sql: d1(config, db, wflag, sql, a.persist_to)       # noqa: E731
        print("대상 = %s · D1 %s(%s) · 설정 %s" % (a.target, db, wflag, config))

        already = run("SELECT participant_id, fingerprint, blocked_at FROM admission_blocks"
                      " WHERE participant_id = %s OR fingerprint = %s" % (q(a.participant), q(a.fingerprint)))
        if already:
            if len(already) == 1 and already[0]["participant_id"] == a.participant \
                    and already[0]["fingerprint"] == a.fingerprint:
                print("이미 차단돼 있다(%s) — 할 일 없음" % already[0]["blocked_at"])
                return 0
            raise Stop("차단 표에 이 id·지문과 **엇갈린** 행이 있다: %s" % already)
        by_id = run("SELECT participant_id, fingerprint, revoked_at, is_operator FROM participants"
                    " WHERE participant_id = %s" % q(a.participant))
        by_fp = run("SELECT participant_id FROM participants WHERE fingerprint = %s" % q(a.fingerprint))
        verdict = classify(a.target, a.participant, a.fingerprint, by_id, by_fp)
        print("사전 확인: id 행 %d · 지문 행 %s → %s" % (len(by_id), [r["participant_id"] for r in by_fp], verdict))
        if verdict != "ok":
            raise Stop(verdict)
        if by_id and by_id[0].get("is_operator"):
            left = run("SELECT COUNT(*) AS n FROM participants p WHERE p.is_operator = 1 AND p.revoked_at IS NULL"
                       " AND p.participant_id != %s AND NOT EXISTS (SELECT 1 FROM admission_blocks b"
                       " WHERE b.participant_id = p.participant_id)" % q(a.participant))[0]["n"]
            print("운영자다 — 차단 뒤 남는 현역 운영자 %d명" % left)
            if left == 0 and not a.allow_no_operator:
                raise Stop("차단 뒤 현역 운영자가 0명이 된다 — --allow-no-operator 로 명시해야 한다")
        if a.remote and a.target == "main" and a.participant == our_resident_id() and resident_running() \
                and not a.allow_resident_running:
            raise Stop("우리 상주(%s)가 떠 있다 — 먼저 멈춘다(launchctl bootout gui/%d/%s)"
                       % (RESIDENT_LABEL, os.getuid(), RESIDENT_LABEL))

        before = snapshot(run)
        files_before = relay_files(a.relay_url) if a.relay_url else None
        blocked_at = a.blocked_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        sql = ("INSERT INTO admission_blocks (participant_id, fingerprint, blocked_at, reason) VALUES (%s, %s, %s, 'retired')"
               % (q(a.participant), q(a.fingerprint), q(blocked_at)))
        if not a.execute:
            print("계획(쓰기 0): " + sql)
            print("명부·체크포인트 표 해시(실행 전) = " + before)
            return 0
        run(sql)
        got = run("SELECT blocked_at FROM admission_blocks WHERE participant_id = %s AND fingerprint = %s"
                  % (q(a.participant), q(a.fingerprint)))
        after = snapshot(run)
        files_after = relay_files(a.relay_url) if a.relay_url else None
        ok = bool(got) and after == before and files_after == files_before
        print("실행: 차단 행 %s · 명부·체크포인트 표 %s%s"
              % ("있음(%s)" % got[0]["blocked_at"] if got else "★없음",
                 "동일" if after == before else "★달라짐",
                 "" if files_before is None else " · 명부 세 파일 " + ("동일" if files_after == files_before else "★달라짐")))
        print("⚠이 D1 하나의 결과다 — 두 D1(본·시험) 모두 끝나기 전에는 「차단 완료」라고 보고하지 않는다(§5-3-5).")
        return 0 if ok else 4
    except Stop as e:
        print("중단: %s" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
