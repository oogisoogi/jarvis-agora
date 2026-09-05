#!/usr/bin/env python3
"""mutate.py — 검증 하네스가 **실제로 무언가를 잰다**는 것을 증명한다.

규율:
  · 변이를 심고 → 하네스를 돌리고 → **원상복구를 먼저 하고** → 그 다음에 판정한다.
    (복구 전에 판정하다 죽으면 소스에 변이가 남는다.)
  · 변이가 적용됐는지를 **먼저 단언**한다. 안 움직인 것을 「그물이 없다」로 읽지 않기 위해서다
    — 그 둘은 다른 사건이고, 후자만 결함이다.
  · 살아남은 변이(초록)는 그 축에 그물이 없다는 뜻이므로 **실패로 보고**한다.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]

# (이름, [(파일, 찾을 것, 바꿀 것), …], 무엇을 재는가)
#   ★한 파일로 안 되는 변이가 있다 — 「한 장에서 빼고 다른 장에 더하기」는 두 파일을 함께 고쳐야
#     집계는 그대로인데 배치만 어긋나는 상태가 된다(그 상태를 하네스가 잡는지가 이 시험의 요점).
MUTATIONS = [
    # (이름, 파일, 찾을 것, 바꿀 것, 무엇을 재는가)
    ("F-9 빈칸 기본값",
     "relay/board/assets/render.js",
     "  if (value === null || value === undefined || value === '') return null;",
     "  if (value === null || value === undefined || value === '') return '알 수 없음';",
     "없는 칸을 문구로 메우면 적색이 나는가"),
    ("F-10 하단 고정 문구 누락",
     "relay/board/index.html",
     "    <p>이 화면은 서버의 계산입니다 — 정본은 서명된 이벤트입니다.</p>\n",
     "",
     "세 장 중 한 장에서 문구가 사라지면 적색이 나는가"),
    ("글자 바닥 붕괴",
     "relay/board/assets/board.css",
     "html { font-size: 125%; -webkit-text-size-adjust: 100%; }",
     "html { font-size: 112%; -webkit-text-size-adjust: 100%; }",
     "본문 글자가 18px 아래로 내려가면 적색이 나는가"),
    ("서버가 안 준 칸으로 배지를 그림",
     "relay/board/assets/render.js",
     "  if (typeof ok !== 'boolean') return null;",
     "  if (typeof ok !== 'boolean') return { label: '서명 확인됨', tone: 'ok' };",
     "없는 파생값으로 신뢰를 말하면 적색이 나는가"),
    ("이어받기 실패를 조용히 삼킴",
     "relay/board/assets/room.js",
     "  if (result.incomplete) {\n    flowEl.appendChild(errorLine('이후 발언을 더 가져오지 못했습니다 — 여기까지가 전부가 아닙니다. 새로 고쳐 주세요.'));\n  }",
     "  if (false) {\n    flowEl.appendChild(errorLine('이후 발언을 더 가져오지 못했습니다 — 여기까지가 전부가 아닙니다. 새로 고쳐 주세요.'));\n  }",
     "일부만 받은 것을 전건처럼 그리면 적색이 나는가"),
    ("본문을 innerHTML 로 그림",
     "relay/board/assets/render.js",
     "  if (opts.text !== undefined && opts.text !== null) node.textContent = String(opts.text);",
     "  if (opts.text !== undefined && opts.text !== null) node.innerHTML = String(opts.text);",
     "신뢰할 수 없는 본문을 HTML 로 그리면 적색이 나는가"),
    ("의장이 아닌 이의 권고를 결론으로 올림",
     "relay/board/assets/render.js",
     "  if (typeof chair !== 'string' || chair === '') return false;\n  return event.kind === 'resolution' && event.from === chair;",
     "  return event.kind === 'resolution';",
     "남의 글을 방의 결론으로 올리면 적색이 나는가"),
]

# 두 파일을 함께 고쳐야 성립하는 변이(집계는 같고 배치만 어긋난다)
MULTI_MUTATIONS = [
    ("하단 고정 문구 배치 어긋남(0회+2회 = 총합 정상)",
     [("relay/board/index.html",
       "    <p>이 화면은 서버의 계산입니다 — 정본은 서명된 이벤트입니다.</p>\n", ""),
      ("relay/board/room.html",
       "    <p>이 화면은 서버의 계산입니다 — 정본은 서명된 이벤트입니다.</p>\n",
       "    <p>이 화면은 서버의 계산입니다 — 정본은 서명된 이벤트입니다.</p>\n"
       "    <p>이 화면은 서버의 계산입니다 — 정본은 서명된 이벤트입니다.</p>\n")],
     "집계가 같고 배치만 다를 때도 적색이 나는가"),
]


def run_harness() -> int:
    r = subprocess.run(["bash", str(ROOT / "relay/board/dev/verify.sh")],
                       cwd=ROOT, capture_output=True, text=True)
    return r.returncode


def main() -> int:
    base = run_harness()
    print(f"기준선(변이 없음) 하네스 = {'PASS' if base == 0 else 'FAIL'}")
    if base != 0:
        print("  ⛔기준선이 이미 적색이다 — 변이 판정은 의미가 없다. 먼저 초록으로 만들어라.")
        return 2

    killed, survived, notapplied = 0, [], []
    normalized = [(n, [(f, o, w)], a) for n, f, o, w, a in MUTATIONS] + MULTI_MUTATIONS
    for name, edits, axis in normalized:
        originals = {}
        skip = None
        for rel, old, new in edits:
            path = ROOT / rel
            src = path.read_text()
            count = src.count(old)
            if count != 1:
                skip = f"{rel} 에서 찾은 자리 {count}곳(1곳이어야 한다)"
                break
            originals[path] = src
        if skip:
            notapplied.append((name, skip))
            print(f"  미적용 {name} — {skip}")
            continue
        for rel, old, new in edits:
            path = ROOT / rel
            path.write_text(originals[path].replace(old, new, 1))
        try:
            for rel, old, new in edits:
                after = (ROOT / rel).read_text()
                assert after != originals[ROOT / rel], f"{rel} 변이가 파일에 안 들어갔다"
            rc = run_harness()
        finally:
            for path, src in originals.items():
                path.write_text(src)        # ★판정보다 복구가 먼저다
        if rc != 0:
            killed += 1
            print(f"  잡음 {name} — {axis}")
        else:
            survived.append((name, axis))
            print(f"  살아남음 {name} — {axis} ← 이 축에는 그물이 없다")

    print(f"\n변이 {len(MUTATIONS) + len(MULTI_MUTATIONS)}건 · 잡음 {killed} · 살아남음 {len(survived)} · 미적용 {len(notapplied)}")
    for n, a in survived:
        print(f"  · 살아남음: {n} ({a})")
    for n, why in notapplied:
        print(f"  · 미적용: {n} ({why}) — **미측정이지 통과가 아니다**")
    return 0 if (not survived and not notapplied) else 1


if __name__ == "__main__":
    sys.exit(main())
