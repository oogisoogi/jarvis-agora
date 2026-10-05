#!/usr/bin/env python3
"""로컬 릴레이를 띄우고 시험을 돌린 뒤 **반드시** 프로세스 그룹째 내린다.

★서버 생명주기(워커 절대지침 1): 고아를 남기지 않는다. 시험이 실패해도 finally 에서 내린다.
★이 실행 환경의 Bash 서브셸에서는 감독 도구의 run 명령이 권한 거부라, python start_new_session 으로
  띄우고 PGID 를 잡아 killpg 한다.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RELAY = os.path.dirname(HERE)
PORT = int(os.environ.get("AGORA_PORT", "8787"))
BASE = "http://127.0.0.1:%d" % PORT


def wait_ready(proc, deadline_s=120):
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def ensure_local_schema(env):
    """로컬 D1 에 표가 없으면 **마이그레이션을 먼저 먹인다**.

    ★왜: 새 작업트리에서 처음 돌리면 표가 없어 시험 전체가 `500 no such table` 로 시작한다.
      그 500 은 「구현이 틀렸다」처럼 보이지만 **환경이 안 차려진 것**이고, 두 사건을 가르는 데
      사람 시간이 든다(master 가 새 worktree 에서 실제로 밟았다 · 2026-09-06).
    ★부재를 재는 축이니 **전제를 먼저 확인**한다: 표가 있으면 아무 일도 하지 않는다(멱등).
    """
    wrangler = os.path.join(RELAY, "node_modules/.bin/wrangler")
    probe = subprocess.run([wrangler, "d1", "execute", "agora-relay", "--local",
                            "--command", "SELECT 1 FROM events LIMIT 1;"],
                           cwd=RELAY, capture_output=True, text=True, env=env)
    if probe.returncode == 0:
        return True
    blob = (probe.stdout + probe.stderr)
    if "no such table" not in blob:
        # 표 부재가 아닌 다른 실패다 — 조용히 마이그레이션을 돌리지 않는다(원인이 가려진다).
        print("로컬 D1 점검 실패(표 부재가 아니다):", blob[-500:])
        return False
    print("로컬 D1 에 표가 없다 — 마이그레이션을 먹인다(--local).")
    r = subprocess.run([wrangler, "d1", "migrations", "apply", "agora-relay", "--local"],
                       cwd=RELAY, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print("마이그레이션 적용 실패 — 먹이는 법:")
        print("  cd relay && unset NODE_OPTIONS && "
              "npx wrangler d1 migrations apply agora-relay --local")
        print((r.stdout + r.stderr)[-800:])
        return False
    return True


def reset_local_db(env):
    """로컬 D1 을 비운다(**--local 전용** — 원격은 건드리지 않는다).

    ★왜 필요한가: 속도 제한과 신원 선점 방어는 **상태를 남기는 방어**다. 안 비우면
      두 번째 실행이 429·409 로 죽고, 그것을 「구현이 틀렸다」로 읽게 된다.
      비우는 것은 시험 환경이지 방어의 완화가 아니다(상한값은 그대로 둔다).
    """
    sql = ("DELETE FROM events; DELETE FROM rooms; DELETE FROM participants; "
           "DELETE FROM rate_windows; DELETE FROM roster_checkpoints;")
    r = subprocess.run([os.path.join(RELAY, "node_modules/.bin/wrangler"), "d1", "execute",
                        "agora-relay", "--local", "--command", sql],
                       cwd=RELAY, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print("로컬 D1 초기화 실패:", r.stdout[-500:], r.stderr[-500:])
    return r.returncode == 0


def main():
    env = {k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"}
    if not ensure_local_schema(env):
        # ★차려지지 않은 환경 위에서 시험을 돌리지 않는다 — 그 결과는 아무것도 증명하지 않는다.
        return 3
    if os.environ.get("AGORA_KEEP_DB") != "1":
        reset_local_db(env)
    log_path = os.path.join(RELAY, ".wrangler-dev.log")
    log = open(log_path, "w")
    proc = subprocess.Popen(
        [os.path.join(RELAY, "node_modules/.bin/wrangler"), "dev", "--local",
         "--port", str(PORT), "--ip", "127.0.0.1"],
        cwd=RELAY, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        env=env, start_new_session=True)
    pgid = os.getpgid(proc.pid)
    rc = 1
    try:
        if not wait_ready(proc):
            print("서버가 뜨지 않았다 — 로그 꼬리:")
            print(open(log_path, encoding="utf-8").read()[-2500:])
            return 2
        print("서버 준비 완료: %s (pgid %d)\n" % (BASE, pgid))
        cmd = [sys.executable, os.path.join(HERE, "threeway.py"), "--base", BASE] + sys.argv[1:]
        rc = subprocess.run(cmd, cwd=RELAY, env=env).returncode
    finally:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError):
                break
            time.sleep(1)
            if proc.poll() is not None:
                break
        log.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
