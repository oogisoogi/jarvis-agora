#!/usr/bin/env python3
"""받아들이기 차단 시험(admission.py)을 **코드를 갈아 끼우며** 같은 로컬 D1 위에서 차례로 돌린다.

    python3 relay/scripts/run-admission.py            # main → 변이 3(T8) → old(2cf9c1e) → race
    python3 relay/scripts/run-admission.py --only main

★로컬 전용(--local · --persist-to 로 한 폴더를 공유). 원격 D1·배포에 닿는 동작 0.
★서버 생명주기(워커 절대지침 1): 한 번에 서버 1개 · start_new_session + killpg · 실패해도 finally 에서 내린다.
★변이·옛 코드는 **사본 폴더**에서 돈다 — 작업트리의 소스를 제자리에서 고치지 않는다(돌다 죽어도 변이가 안 남는다).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RELAY = os.path.dirname(HERE)
ROOT = os.path.dirname(RELAY)
PERSIST = os.path.join(RELAY, ".wrangler", "state")
PORT = int(os.environ.get("AGORA_ADMISSION_PORT", "8797"))
BASE = "http://127.0.0.1:%d" % PORT
OLD_COMMIT = "2cf9c1e"            # 현재 배포본(설계 SURVEY §0) — 앱 층 검사가 없는 옛 코드
ENV = {k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"}

# 판정 경로로 차단이 새는 변이(T8) — 설계 §8 「verifyDetail·lookupTable·렌더 중 하나로 새는」 것.
LEAK_BLK = ('  const table = lookupTable(rows);\n',
            '  const table = lookupTable(rows);\n  const blk = new Set(((await db.prepare("SELECT participant_id FROM admission_blocks").all<any>()).results ?? []).map((r: any) => r.participant_id));\n')
MUTANTS = {
    "M-allParticipants(명부 행에 은퇴를 폐기로 섞음)": [
        ("src/lib/store.ts",
         '"SELECT participant_id, display_name, key_type, key_b64, fingerprint, is_operator, revoked_at, created_at FROM participants"',
         '"SELECT participant_id, display_name, key_type, key_b64, fingerprint, is_operator, COALESCE(revoked_at, (SELECT blocked_at FROM admission_blocks b WHERE b.participant_id = participants.participant_id)) AS revoked_at, created_at FROM participants"')],
    "M-lookupTable(서명 검증 조회표에 은퇴 표시)": [
        ("src/lib/store.ts",) + LEAK_BLK,
        ("src/lib/store.ts", "    lookup: (fp: string) => table.get(fp),\n",
         "    lookup: (fp: string) => { const e = table.get(fp); return e && blk.has(e.principal) ? { ...e, revoked: true } : e; },\n")],
    "M-render(allowed_signers 렌더에서 은퇴 제외)": [
        ("src/lib/store.ts",) + LEAK_BLK,
        ("src/lib/store.ts", "  const allowedText = renderAllowedSigners(rows);\n",
         "  const allowedText = renderAllowedSigners(rows.filter(r => !blk.has(r.participant_id)));\n")],
}
# 경합 창(T12): 앱 층 검사와 멱등 사전 조회를 뺀다 = 「검사를 통과한 뒤 INSERT 전에 차단이 커밋된」 요청.
RACE = [
    ("src/index.ts", "  if (await admissionBlock(env.DB, event.from, null)) {\n", "  if (false) {\n"),
    ("src/index.ts", "  if (existing) {\n    if (existing.hash === hash) {\n", "  if (false && existing) {\n    if (existing.hash === hash) {\n"),
    ("src/index.ts", "  if (await admissionBlock(env.DB, participantId, fingerprint)) {\n", "  if (false) {\n"),
    ("src/index.ts", "  if (await admissionBlock(env.DB, signer, null)) {\n", "  if (false) {\n"),
]


def run_local_module():
    spec = importlib.util.spec_from_file_location("run_local", os.path.join(HERE, "run-local.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                          # type: ignore[union-attr]
    return mod


def make_copy(dest: str, commit: str | None) -> str:
    """dest/relay · dest/config 를 만든다(현재 작업트리 또는 옛 커밋). node_modules·board 는 링크."""
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    if commit:
        tar = subprocess.run(["git", "archive", commit, "relay/src", "relay/wrangler.jsonc", "relay/tsconfig.json",
                              "relay/package.json", "config"], cwd=ROOT, capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", dest], input=tar, check=True)
    else:
        os.makedirs(os.path.join(dest, "relay"))
        shutil.copytree(os.path.join(RELAY, "src"), os.path.join(dest, "relay", "src"))
        for f in ("wrangler.jsonc", "tsconfig.json", "package.json"):
            shutil.copyfile(os.path.join(RELAY, f), os.path.join(dest, "relay", f))
        os.symlink(os.path.join(ROOT, "config"), os.path.join(dest, "config"))
    os.symlink(os.path.join(RELAY, "node_modules"), os.path.join(dest, "relay", "node_modules"))
    os.symlink(os.path.join(RELAY, "board"), os.path.join(dest, "relay", "board"))
    return os.path.join(dest, "relay")


def patch(relay_dir: str, edits) -> None:
    for f, old, new in edits:
        p = os.path.join(relay_dir, f)
        s = open(p, encoding="utf-8").read()
        if s.count(old) != 1:
            raise SystemExit("변이 적용 실패(%s · 일치 %d) — 측정 실패이지 그물 판정이 아니다" % (f, s.count(old)))
        open(p, "w", encoding="utf-8").write(s.replace(old, new))


def wait_ready(proc, deadline_s=120):
    end = time.time() + deadline_s
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def with_server(relay_dir: str, fn, log_name: str) -> int:
    log_path = os.path.join(tempfile.gettempdir(), "agora-admission-%s.log" % log_name)
    log = open(log_path, "w")
    proc = subprocess.Popen([os.path.join(RELAY, "node_modules/.bin/wrangler"), "dev", "--local",
                             "--port", str(PORT), "--ip", "127.0.0.1", "--persist-to", PERSIST,
                             "--config", os.path.join(relay_dir, "wrangler.jsonc")],
                            cwd=relay_dir, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            env=ENV, start_new_session=True)
    pgid = os.getpgid(proc.pid)
    try:
        if not wait_ready(proc):
            print("서버가 뜨지 않았다(%s) — 로그 꼬리:\n%s" % (log_name, open(log_path).read()[-2000:]))
            return 2
        return fn()
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


def harness(phase: str, workdir: str, label: str = "") -> int:
    return subprocess.run([sys.executable, os.path.join(HERE, "admission.py"), "--base", BASE,
                           "--persist", PERSIST, "--workdir", workdir, "--phase", phase, "--label", label],
                          cwd=ROOT, env=ENV).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default=os.path.join(tempfile.gettempdir(), "agora-admission"))
    ap.add_argument("--only", choices=("main", "mutant", "old", "race"), default=None)
    a = ap.parse_args()
    rl = run_local_module()
    if not rl.ensure_local_schema(ENV):
        return 3
    copies = os.path.join(a.workdir, "copies")
    results: list[tuple[str, int]] = []
    if a.only in (None, "main"):
        if not rl.reset_local_db(ENV):
            return 3
        results.append(("main", with_server(RELAY, lambda: harness("main", a.workdir), "main")))
    if a.only in (None, "mutant"):
        for i, (label, edits) in enumerate(MUTANTS.items()):
            d = make_copy(os.path.join(copies, "mutant%d" % i), None)
            patch(d, edits)
            results.append((label, with_server(d, lambda l=label: harness("mutant", a.workdir, l), "mutant%d" % i)))
    if a.only in (None, "old"):
        d = make_copy(os.path.join(copies, "old"), OLD_COMMIT)
        results.append(("old " + OLD_COMMIT, with_server(d, lambda: harness("old", a.workdir), "old")))
    if a.only in (None, "race"):
        d = make_copy(os.path.join(copies, "race"), None)
        patch(d, RACE)
        results.append(("race", with_server(d, lambda: harness("race", a.workdir), "race")))
    print("\n##### 종합 #####")
    for name, rc in results:
        print("  %-50s %s" % (name, "PASS" if rc == 0 else "FAIL(rc %d)" % rc))
    return 0 if results and all(rc == 0 for _, rc in results) else 1


if __name__ == "__main__":
    sys.exit(main())
