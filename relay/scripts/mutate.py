#!/usr/bin/env python3
"""뮤테이션 검산 — **그물이 실제로 그 축을 재는지**를 잰다.

「돌려서 통과했다」와 「그 검사가 잡는다」는 다른 명제다. 여기서 재는 것은 뒤엣것이다:
소스를 한 군데 망가뜨렸을 때 **어느 시험이 빨개지는가**. 안 빨개지면 그 축은 상시 초록이다.

★복원은 **쓰기까지 try 안에서** 한다. 하네스가 복원 전에 죽으면 소스에 변이가 남는다.
★변이가 **적용됐는지 먼저 단언**한다. 안 움직이는 것은 그물 사망이 아니라 측정 실패일 수 있다.
"""
from __future__ import annotations

import os
import subprocess
import sys

RELAY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = os.environ.get("AGORA_PORT", "8791")

# (이름, 파일, 찾을 것, 바꿀 것, 실행기, 이 변이를 잡아야 하는 축)
MUTATIONS = [
    ("M1 updated_at 갱신 제거", "src/index.ts",
     "await upsertRoom(env.DB, threadId, derived, rows, createdAt);",
     'await upsertRoom(env.DB, threadId, derived, rows, "2026-01-01T00:00:00.000Z");',
     "harness", "updated_at 이 움직인다"),

    ("M2 경합 승자 부등호 뒤집기", "src/lib/reducer.ts",
     "for (const c of candidates) if (cmpKey(orderKey(c), orderKey(winner)) < 0) winner = c;",
     "for (const c of candidates) if (cmpKey(orderKey(c), orderKey(winner)) > 0) winner = c;",
     "harness", "3자 대조 세트2(경합)"),

    ("M3 principal 결박 제거", "src/index.ts",
     "  if (entry.principal !== event.from) {",
     "  if (false) {",
     "harness", "경로2c 명부 밖 키"),

    ("M4 멱등 해시 대조 제거", "src/index.ts",
     "    if (existing.hash === hash) {",
     "    if (true) {",
     "harness", "message_id 재사용(다른 내용)"),

    ("M5 스크럽 백스톱 무력화", "src/index.ts",
     "  scrub.enforce(event.payload, bundle);",
     "  void scrub.enforce;",
     "harness", "경로4b 스크럽 백스톱"),

    ("M6 canonical NFC 정규화 제거", "src/lib/canonical.ts",
     'function nfc(s: string): string {\n  return s.normalize("NFC");\n}',
     'function nfc(s: string): string {\n  return s;\n}',
     "vitest", "golden 5변형(NFD 입력)"),

    ("M8 속도 상한 부등호(off-by-one)", "src/lib/store.ts",
     "  return { ok: count <= limit, retryAfter: Math.max(1, retryAfter) };",
     "  return { ok: count < limit, retryAfter: Math.max(1, retryAfter) };",
     "vitest", "상한까지 통과 · 상한+1 차단"),

    ("M9 event_id 고정폭 제거", "src/lib/store.ts",
     '  return "ev_" + String(seq).padStart(16, "0");',
     '  return "ev_" + String(seq);',
     "vitest", "문자열 정렬 = 도착 순서"),

    ("M10 거부 시 head 전진 제거", "src/lib/reducer.ts",
     "    state.head = entry.hash;\n  };",
     "  };",
     "harness", "3자 대조 세트3·4(절차 거부 포함)"),

    ("M11 서명 파싱 예외를 원시 Error 로", "src/lib/sshsig.ts",
     'if (n < 0 || this.i + n > this.b.length) fail(SIGNATURE, "서명 블록이 짧다", { want: n });',
     'if (n < 0 || this.i + n > this.b.length) throw new Error("서명 블록이 짧다");',
     "harness", "잘린 서명 = 401(500 아님)"),

    ("M12 멱등 앞에 속도 계수 복귀", "src/index.ts",
     "  // (8) 멱등 — 같은 (from, message_id) + 같은 해시는 새 행을 만들지 않는다.",
     '  await bumpRate(env.DB, "pid:" + event.from, 60, EVENTS_PER_PID_MIN);\n'
     "  // (8) 멱등 — 같은 (from, message_id) + 같은 해시는 새 행을 만들지 않는다.",
     "harness", "재시도 뒤 정상 발언이 통과"),

    ("M13 vote 에서 head 전진 복귀", "src/lib/reducer.ts",
     "      accepted.push(entry);\n      continue;\n    }",
     "      accepted.push(entry);\n      state.head = entry.hash;\n      continue;\n    }",
     "harness", "3자 대조 세트5(vote 포함)"),

    ("M14 래퍼 제목 결박 제거", "src/index.ts",
     "  if (isGenesis && title !== event.payload.title) {",
     "  if (false) {",
     "harness", "래퍼 제목 변조 = 400"),

    ("M15 Accept 갈림 제거(사람도 JSON 을 본다)", "src/index.ts",
     "          if (prefersHtml(req.headers.get(\"Accept\"))) {",
     "          if (false) {",
     "harness", "브라우저형 Accept = 302"),

    ("M16 재등록 200 에 계약 밖 칸 부활", "src/index.ts",
     "      return json({ participant_id: participantId, fingerprint, created_at: byId.created_at }, 200);",
     '      return json({ participant_id: participantId, fingerprint, created_at: byId.created_at, status: "already" }, 200);',
     "harness", "재등록 200 본문 = 계약 세 칸"),

    ("M17 등록 201 에 계약 밖 칸 부활", "src/index.ts",
     "  return json({ participant_id: participantId, fingerprint, created_at: createdAt }, 201);",
     '  return json({ participant_id: participantId, fingerprint, created_at: createdAt, status: "created" }, 201);',
     "harness", "등록 201 본문 = 계약 세 칸"),

    ("M18 이벤트 200 에 계약 밖 칸 부활", "src/index.ts",
     "        created_at: existing.created_at,\n",
     '        created_at: existing.created_at, status: "already",\n',
     "harness", "이벤트 200 본문 = 계약 세 칸"),

    ("M19 체크포인트 signed_at 결박 제거", "src/index.ts",
     "    checkpoint, purpose: \"agora-roster-checkpoint-v1\", signed_at: signedAt, signer,",
     '    checkpoint, purpose: "agora-roster-checkpoint-v1", signer,',
     "harness", "signed_at 만 바꾼 재제출 = 401"),

    ("M7 서명 검증 결과 무시", "src/lib/sshsig.ts",
     "  const ok = await crypto.subtle.verify({ name: \"Ed25519\" }, key, sb.sig as BufferSource, signed as BufferSource);",
     "  const ok = true;",
     "vitest", "본문 변조 = BAD"),
]


def run(kind: str) -> tuple[bool, str]:
    env = {k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"}
    if kind == "harness":
        env["AGORA_PORT"] = PORT
        p = subprocess.run([sys.executable, os.path.join(RELAY, "scripts/run-local.py")],
                           cwd=RELAY, capture_output=True, text=True, env=env, timeout=600)
        tail = p.stdout[-1200:]
        return ("== 결과: PASS ==" in p.stdout), tail
    p = subprocess.run([os.path.join(RELAY, "node_modules/.bin/vitest"), "run"],
                       cwd=RELAY, capture_output=True, text=True, env=env, timeout=600)
    return (p.returncode == 0), (p.stdout[-600:] + p.stderr[-400:])


def main() -> int:
    # ★로컬 D1 표가 없으면 기준선부터 500 으로 죽는다 — 그 실패는 「그물이 없다」가 아니라
    #   「환경이 안 차려졌다」인데, 뮤테이션 결과표에서는 둘이 구별되지 않는다.
    #   run-local.py 가 같은 점검을 하지만, mutate 를 단독으로 돌리는 경로가 있으므로 여기서도 알린다.
    env0 = {k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"}
    probe = subprocess.run([os.path.join(RELAY, "node_modules/.bin/wrangler"), "d1", "execute",
                            "agora-relay", "--local", "--command", "SELECT 1 FROM events LIMIT 1;"],
                           cwd=RELAY, capture_output=True, text=True, env=env0)
    if probe.returncode != 0 and "no such table" in (probe.stdout + probe.stderr):
        print("로컬 D1 에 표가 없다 — run-local.py 가 첫 실행에서 먹인다(또는 직접):")
        print("  cd relay && unset NODE_OPTIONS && "
              "npx wrangler d1 migrations apply agora-relay --local")

    print("== 기준선(변이 없음) ==")
    base_h, _ = run("harness")
    base_v, _ = run("vitest")
    print("  하네스 %s · vitest %s" % ("PASS" if base_h else "FAIL", "PASS" if base_v else "FAIL"))
    if not (base_h and base_v):
        print("  ★기준선이 적색이면 뮤테이션 결과는 아무것도 증명하지 않는다. 중단한다.")
        return 2

    results = []
    for name, rel, old, new, kind, axis in MUTATIONS:
        path = os.path.join(RELAY, rel)
        original = open(path, encoding="utf-8").read()
        applied = False
        try:
            count = original.count(old)
            if count != 1:
                results.append((name, "NOT-APPLICABLE", "찾을 문자열이 %d 번(1이어야 한다)" % count, axis))
                continue
            open(path, "w", encoding="utf-8").write(original.replace(old, new, 1))
            applied = True
            # 변이가 실제로 적용됐는지 단언한다.
            if new not in open(path, encoding="utf-8").read():
                results.append((name, "NOT-APPLIED", "쓰였는데 안 보인다", axis))
                continue
            ok, tail = run(kind)
            results.append((name, "생존(그물 없음)" if ok else "KILLED", tail.strip().splitlines()[-1:] and "", axis))
        finally:
            if applied:
                open(path, "w", encoding="utf-8").write(original)

    print("\n== 뮤테이션 결과 ==")
    killed = 0
    for name, verdict, note, axis in results:
        mark = "OK" if verdict == "KILLED" else "★"
        if verdict == "KILLED":
            killed += 1
        print("  %-2s %-28s %-16s ← %s %s" % (mark, name, verdict, axis, note))
    print("\n  KILLED %d / %d" % (killed, len(results)))
    return 0 if killed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
