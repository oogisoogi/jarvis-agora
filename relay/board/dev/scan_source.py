#!/usr/bin/env python3
"""scan_source.py — 보드 소스의 **선언문만** 보고 금지 패턴을 찾는다.

★왜 주석을 걷어내는가: 이 규율들은 자기 자신을 설명하는 주석에 그대로 등장한다.
  주석까지 세면 규율을 적어 둔 파일이 그 규율의 위반으로 보고되고(거짓 적색),
  거짓 적색이 몇 번 나면 사람은 그 검사를 끄게 된다 — 그 순간 진짜 위반도 안 잡힌다.
  그래서 주석·문자열은 자리를 유지한 채 공백으로 지우고(줄 번호 보존) 남은 코드만 본다.

★이 검사기가 실제로 무언가를 잡는지는 --selftest 가 증명한다(변이를 심어 적색이 나는지).
"""
from __future__ import annotations

import pathlib
import re
import sys

# 규칙마다 **어느 판본의 소스**를 읽는지 다르다.
#   'code'   = 주석과 문자열 안쪽을 지운 것 — 문자열에 우연히 든 낱말에 걸리지 않는다.
#   'nostr'  = 주석만 지운 것(문자열은 남김) — 기본값 **문구 자체**를 봐야 하는 규칙용.
# ★이 구분이 없으면 한쪽 규칙이 조용히 눈이 먼다(자기검사가 실제로 그것을 잡았다).
RULES = [
    ("innerHTML", "code", re.compile(r"\binnerHTML\b"),
     "본문은 textContent 로만 그린다(신뢰할 수 없는 콘텐츠)"),
    # ★배포된 주소가 확장자를 떼고 307 로 되돌리므로, `.html` 로 링크하면 이동마다 한 홉이 더 든다.
    #   도착지로 직접 걸어야 한다(`/` · `/room?id=` · `/archive`).
    ("확장자 링크", "nostr", re.compile(r"\.html"),
     "배포가 확장자를 떼고 307 로 되돌린다 — 도착지(/ · /room?id= · /archive)로 직접 걸어라"),
    ("빈칸 기본값", "nostr",
     re.compile(r"\?\?\s*['\"]|\|\|\s*['\"]|\?\?\s*`[^`$]*`|\|\|\s*`[^`$]*`"
                r"|\?\?\s*\d|\|\|\s*\d"),
     "서버가 안 준 칸을 문구로 바꾸면 「값이 없다」와 「안 줬다」가 섞인다"),
]

# ★이 검사가 보증하는 것과 못 하는 것(정직):
#   보증 = 「?? '…'」·「|| '…'」로 **글자를 바로 끼워 넣는** 반사적인 기본값을 막는다.
#   못 함 = 삼항(? :)이나 함수로 감싸 같은 일을 하는 것. 문법 축의 검사이지 의미 축이 아니다.
#   ⚠값이 **끼어 있는** 템플릿(`라운드 ${r}`)은 일부러 통과시킨다 — 그것은 없는 칸을 메우는 문구가
#     아니라 **받은 값을 그대로 적는** 것이고, 그 둘을 한 규칙으로 묶으면 규칙이 노이즈가 된다.
#   그래서 이름표 기본값은 **상수로 선언**하게 하고, 아래 목록으로 전수 공개한다.
PLACEHOLDER_DECL = re.compile(r"^const\s+([A-Z0-9_]+)\s*=\s*'([^']*)';", re.M)


def _strip(src: str, *, blank_strings: bool) -> str:
    """주석(과 선택적으로 문자열 안쪽)을 공백으로 바꾼다 — 줄 번호·열 위치 보존."""
    out = list(src)
    i, n = 0, len(src)
    state = None          # None | 'line' | 'block' | quote char
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state is None:
            if c == "/" and nxt == "/":
                state = "line"; out[i] = out[i + 1] = " "; i += 2; continue
            if c == "/" and nxt == "*":
                state = "block"; out[i] = out[i + 1] = " "; i += 2; continue
            if c in "'\"`":
                state = c if blank_strings else ("q" + c)
                i += 1; continue                   # 따옴표 자체는 남긴다(패턴이 그것을 본다)
            i += 1; continue
        if state == "line":
            if c == "\n": state = None
            else: out[i] = " "
            i += 1; continue
        if state == "block":
            if c == "*" and nxt == "/":
                out[i] = out[i + 1] = " "; state = None; i += 2; continue
            if c != "\n": out[i] = " "
            i += 1; continue
        # 문자열 안
        keep = state.startswith("q")
        quote = state[1] if keep else state
        if c == "\\":
            if not keep:
                out[i] = " "
                if i + 1 < n: out[i + 1] = " "
            i += 2; continue
        if c == quote:
            state = None; i += 1; continue
        if not keep and c != "\n": out[i] = " "
        i += 1
    return "".join(out)


def strip_html_comments(src: str) -> str:
    """HTML 주석을 자리를 지킨 채 지운다 — 규칙을 설명하는 주석이 그 규칙의 위반으로 잡히지 않게."""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        if src.startswith("<!--", i):
            j = src.find("-->", i + 4)
            j = n if j == -1 else j + 3
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def strip_comments(src: str) -> str:
    """주석만 지운다(문자열은 남긴다)."""
    return _strip(src, blank_strings=False)


def strip_js(src: str) -> str:
    """주석과 문자열 안쪽을 함께 지운다."""
    return _strip(src, blank_strings=True)


def scan(paths):
    hits = []
    for p in paths:
        src = p.read_text()
        views = {
            "code": strip_js(src) if p.suffix == ".js" else strip_html_comments(src),
            "nostr": strip_comments(src) if p.suffix == ".js" else strip_html_comments(src),
        }
        for name, view, rx, why in RULES:
            for lineno, line in enumerate(views[view].split("\n"), start=1):
                if rx.search(line):
                    hits.append((str(p), lineno, name, why))
    return sorted(hits)


def placeholders(paths):
    """선언된 이름표 기본값 전수 — 보이지 않는 억제는 미탐과 구별되지 않는다."""
    found = []
    for p in paths:
        if p.suffix != ".js":
            continue
        for m in PLACEHOLDER_DECL.finditer(strip_comments(p.read_text())):
            if m.group(2).startswith("("):
                found.append((str(p), m.group(1), m.group(2)))
    return found


def selftest() -> int:
    """★검사기가 죽어 있지 않다는 것을 증명한다 — 변이를 심어 적색이 나는지 본다."""
    cases = [
        ("innerHTML", "node.innerHTML = body;", True),
        ("innerHTML", "// node.innerHTML = body;", False),
        ("innerHTML", "const s = 'innerHTML';", False),
        ("빈칸 기본값", "const t = room.chair ?? '알 수 없음';", True),
        ("빈칸 기본값", "/* ?? '알 수 없음' 을 넣지 마라 */", False),
        ("빈칸 기본값", "const t = room.chair || '없음';", True),
        ("없음", "const t = labelOf(TYPE, room.type);", False),
        ("빈칸 기본값", "const t = a ?? `모름`;", True),
        ("빈칸 기본값", "const t = a ?? `라운드 ${r}`;", False),
        ("빈칸 기본값", "const n = room.participants ?? 0;", True),
        ("빈칸 기본값", "const n = room.participants || 0;", True),
        ("확장자 링크", 'href="index.html"', True),
        ("확장자 링크", "`room.html?id=${x}`", True),
        ("확장자 링크", "// /room.html 은 307 로 되돌린다", False),
        ("확장자 링크", "<!-- room.html 은 307 -->", False),
        ("확장자 링크", 'href="/room?id=x"', False),
    ]
    bad = 0
    for name, snippet, should_hit in cases:
        is_html = "<!--" in snippet or snippet.lstrip().startswith("<")
        views = ({"code": strip_html_comments(snippet), "nostr": strip_html_comments(snippet)}
                 if is_html else {"code": strip_js(snippet), "nostr": strip_comments(snippet)})
        got = any(rx.search(views[view]) for _, view, rx, _ in RULES)
        ok = got is should_hit
        print(f"  {'OK  ' if ok else 'FAIL'} [{name}] {'적발 기대' if should_hit else '통과 기대'}: {snippet}")
        if not ok:
            bad += 1
    print(f"  자기검사 {len(cases)}건 · 실패 {bad}건")
    return 1 if bad else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "relay/board")
    paths = sorted([*root.glob("assets/*.js"), *root.glob("*.html")])
    hits = scan(paths)
    for path, lineno, name, why in hits:
        print(f"    위반 {path}:{lineno} [{name}] — {why}")
    ph = placeholders(paths)
    print(f"  선언된 이름표 기본값 {len(ph)}건(억제 전수 공개):")
    for path, const, value in ph:
        print(f"    · {path} {const} = {value}")
    print(f"  검사 파일 {len(paths)}개 · 위반 {len(hits)}건")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
