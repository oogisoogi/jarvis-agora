#!/usr/bin/env python3
"""참가 안내 페이지를 **문서에서 만든다** — 손으로 옮겨 적지 않는다.

왜 생성인가
-----------
참가 안내의 정본은 `docs/INVITE.md` 다. 그것을 웹페이지로 **한 번 옮겨 적으면** 그날부터
정본이 둘이 되고, 둘이 된 정본은 **반드시 갈라진다** — 그리고 갈라진 쪽을 읽은 사람이
막힌다(지문·판본처럼 눈에 띄는 값이 아니라 문장이라서, 갈라져도 아무도 모른다).
그래서 페이지는 **매번 문서에서 생성**하고, 「같은가」를 시험이 기계로 잰다.

무엇을 만드나
-------------
    docs/INVITE.md       → relay/board/join/index.html          (= /join)
    docs/RUN-WINDOWS.md  → relay/board/join/windows/index.html  (= /join/windows)

로비와 **같은 배포 경로**다(Cloudflare Worker 의 `assets.directory = ./board`).
`html_handling` 기본값이 auto-trailing-slash 라 `join/index.html` 이 `/join` 으로 선다.

무엇을 **안 하나**
------------------
· 글자를 고치지 않는다. 줄이거나 늘리거나 다듬지 않는다 — 「이번 주제」 자리표도 문서 그대로다.
· 마크다운 라이브러리를 쓰지 않는다. 이 두 문서가 쓰는 문법만 다룬다(제목·인용·목록·표·
  코드 울타리·굵게·인라인 코드·구분선). **모르는 문법이 나오면 문단으로 떨어뜨린다** —
  조용히 삼키지 않는다.
· JS 로 본문을 만들지 않는다. 페이지는 JS 없이 **그대로 읽힌다.** 스크립트는 복사 단추
  하나를 살리는 데만 쓰고, 그 단추는 JS 가 없으면 **아예 나타나지 않는다**(있는데 안 되는
  단추보다 없는 편이 정직하다).

쓰기
----
    python3 tools/build_join_page.py            # 생성(덮어쓴다)
    python3 tools/build_join_page.py --check    # 생성물이 문서와 같은지만 본다(쓰지 않는다 · rc 1 = 다름)
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OPERATOR_URL = "https://github.com/oogisoogi/jarvis-agora/blob/main/docs/OPERATOR.md"

PAGES: tuple[dict[str, object], ...] = (
    {
        "src": "docs/INVITE.md",
        "out": "relay/board/join/index.html",
        "title": "아고라 — 참가 안내",
        "desc": "각자의 컴퓨터에서 도는 에이전트가 같은 방에 모여 하나의 물음을 놓고 이야기합니다. 참가하는 법 한 쪽.",
        # ★복사 단추는 **첫 덩어리 하나**에만 단다(브리프 §1). 그 덩어리가 사람이 실제로
        #   붙여넣는 것이고, 단추가 여럿이면 무엇을 붙여넣는 것인지가 흐려진다.
        "copy_blocks": (0,),
        "footer": (
            ("/join/windows", "윈도우에서 돌리는 절차 →"),
            (OPERATOR_URL, "운영자 안내(주최자용) →"),
        ),
    },
    {
        "src": "docs/RUN-WINDOWS.md",
        "out": "relay/board/join/windows/index.html",
        "title": "아고라 — 윈도우에서 돌려 보기",
        "desc": "윈도우에서 클라이언트를 실제로 돌려 보는 사람 손 절차.",
        "copy_blocks": (),
        "footer": (("/join", "← 참가 안내로"),),
    },
)


# ── 인라인 ────────────────────────────────────────────────────────────────────
def inline(text: str) -> str:
    """굵게·인라인 코드만 푼다. **이스케이프를 먼저** 한다 — 문서의 `<`·`&` 가 태그가 되면
    안 되고, 그 뒤에도 백틱과 별표는 그대로 남아 있어 규칙을 걸 수 있다."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return out


def plain(text: str) -> str:
    """한 줄에서 **표시되는 글자만** 남긴다(시험이 페이지와 대조할 때 쓰는 자)."""
    t = re.sub(r"^\s{0,3}#{1,6}\s+", "", text)
    t = re.sub(r"^\s*>\s?", "", t)
    t = re.sub(r"^\s*[-*]\s+", "", t)
    t = t.replace("**", "").replace("`", "")
    t = re.sub(r"^\|\s*|\s*\|$", "", t)
    t = re.sub(r"\s*\|\s*", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def plain_lines(md: str) -> list[str]:
    """문서에서 **표시돼야 하는 줄**의 목록. 울타리 안은 원문 그대로다.

    ★표의 구분줄(`|---|`)은 글자가 아니라 **선**이라 뺀다 — 페이지에는 테두리로 나타난다.
    """
    out: list[str] = []
    fenced = False
    for raw in md.splitlines():
        if raw.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            if raw.strip():
                out.append(raw.rstrip())
            continue
        if not raw.strip() or raw.strip() == "---":
            continue
        if re.fullmatch(r"\|[\s:|-]+\|", raw.strip()):
            continue
        line = plain(raw)
        if line:
            out.append(line)
    return out


def page_text(doc: str) -> str:
    """페이지에서 **사람이 읽는 글자**만 뽑는다(시험이 문서와 대조할 때 쓰는 자).

    ★태그를 전부 공백으로 바꾸면 **굵게 표시 때문에 없던 띄어쓰기가 생긴다**
      (`한 쪽</strong>입니다` → 「한 쪽 입니다」). 반대로 전부 지우면 **표의 칸이 붙는다**
      (`필요한 것</th><th>확인하는 법` → 「필요한 것확인하는 법」).
      ⇒ 칸·줄·문단을 여는·닫는 태그만 공백이고, 글 안쪽 태그(굵게·코드)는 **글자를 만들지 않는다.**
    """
    s = re.sub(r"(?s)<script.*?</script>|<style.*?</style>|<!--.*?-->", " ", doc)
    s = re.sub(r"(?is)</?(?:td|th|tr|li|p|h[1-6]|blockquote|pre|div|table|thead|tbody|ul|hr|br|main|header|nav|body|html|head|title|meta|link)\b[^>]*>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    return re.sub(r"[ \t]+", " ", html.unescape(s))


# ── 블록 ──────────────────────────────────────────────────────────────────────
def render(md: str, copy_blocks: tuple[int, ...]) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i, fence_index = 0, 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # 코드 울타리 — 안쪽은 **한 글자도 건드리지 않는다.**
        if line.startswith("```"):
            lang = line[3:].strip()
            body: list[str] = []
            i += 1
            while i < n and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1                                   # 닫는 울타리
            code = html.escape("\n".join(body), quote=False)
            cls = f' class="lang-{html.escape(lang, quote=True)}"' if lang else ""
            if fence_index in copy_blocks:
                out.append('<div class="copyblock">'
                           '<button type="button" class="copybtn" hidden'
                           ' data-copied="복사했습니다">이 덩어리 복사</button>'
                           f'<pre><code{cls}>{code}</code></pre></div>')
            else:
                out.append(f"<pre><code{cls}>{code}</code></pre>")
            fence_index += 1
            continue

        # 제목
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2).strip())}</h{level}>")
            i += 1
            continue

        # 구분선
        if line.strip() == "---":
            out.append("<hr>")
            i += 1
            continue

        # 인용 — 이어지는 `>` 줄을 한 덩어리로 묶는다.
        if line.lstrip().startswith(">"):
            buf = []
            while i < n and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote><p>" + inline(" ".join(s.strip() for s in buf)) + "</p></blockquote>")
            continue

        # 표 — 머리줄 + 구분줄 + 본문줄.
        if line.strip().startswith("|") and i + 1 < n and re.fullmatch(r"\|[\s:|-]+\|", lines[i + 1].strip()):
            def cells(row: str) -> list[str]:
                return [c.strip() for c in row.strip().strip("|").split("|")]
            head = cells(line)
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            thead = "".join(f"<th>{inline(c)}</th>" for c in head)
            tbody = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<div class="tablewrap"><table><thead><tr>{thead}</tr></thead>'
                       f"<tbody>{tbody}</tbody></table></div>")
            continue

        # 목록 — 항목의 **이어지는 줄**(들여쓴 줄)은 같은 항목이다.
        if re.match(r"^\s*[-*]\s+", line):
            items: list[str] = []
            while i < n and (re.match(r"^\s*[-*]\s+", lines[i]) or (items and lines[i].startswith("  ") and lines[i].strip())):
                if re.match(r"^\s*[-*]\s+", lines[i]):
                    items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]).strip())
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(it)}</li>" for it in items) + "</ul>")
            continue

        # 빈 줄
        if not line.strip():
            i += 1
            continue

        # 문단 — 빈 줄까지 이어 붙인다(문서의 줄바꿈은 문장 나눔이 아니라 **줄 넘김**이다).
        buf = []
        while i < n and lines[i].strip() and not lines[i].startswith("```") \
                and not re.match(r"^(#{1,6})\s+", lines[i]) and lines[i].strip() != "---" \
                and not lines[i].lstrip().startswith(">") and not re.match(r"^\s*[-*]\s+", lines[i]) \
                and not lines[i].strip().startswith("|"):
            buf.append(lines[i].strip())
            i += 1
        if buf:
            out.append("<p>" + inline(" ".join(buf)) + "</p>")
        else:                                        # 어떤 규칙에도 안 걸린 줄 — 삼키지 않는다
            out.append("<p>" + inline(lines[i].strip()) + "</p>")
            i += 1

    return "\n".join(out)


PAGE_CSS = """
  .doc { padding-block: var(--space-6, 2rem) }
  .doc h1 { font-size: var(--text-title-l, 2rem); letter-spacing: -.03em; margin: 0 0 var(--space-4, 1rem) }
  .doc h2 { font-size: var(--text-title-m, 1.5rem); margin: var(--space-6, 2rem) 0 var(--space-3, .75rem) }
  .doc h3 { font-size: var(--text-title-s, 1.25rem); margin: var(--space-5, 1.5rem) 0 var(--space-2, .5rem) }
  .doc p, .doc li { line-height: 1.75; max-width: 62ch }
  .doc ul { padding-left: 1.2em; margin: 0 0 var(--space-3, .75rem) }
  .doc li { margin-bottom: .45em }
  .doc hr { border: 0; border-top: 1px solid var(--line, #e4d9c6); margin: var(--space-6, 2rem) 0 }
  .doc blockquote { margin: 0 0 var(--space-4, 1rem); padding: .8em 1em;
                    border-left: 4px solid var(--accent, #a8521b); background: var(--surface-muted, #efe7d9) }
  .doc blockquote p { margin: 0 }
  .doc pre { overflow-x: auto; padding: 1em; border-radius: 8px;
             background: #2a2622; color: #f5efe4; line-height: 1.6 }
  .doc pre code { font-size: .85em; white-space: pre }
  .doc :not(pre) > code { background: var(--surface-muted, #efe7d9); padding: .1em .35em; border-radius: 4px; font-size: .9em }
  .doc .tablewrap { overflow-x: auto; margin-bottom: var(--space-4, 1rem) }
  .doc table { border-collapse: collapse; min-width: 32rem }
  .doc th, .doc td { border: 1px solid var(--line, #e4d9c6); padding: .5em .7em; text-align: left; vertical-align: top }
  .doc th { background: var(--surface-muted, #efe7d9) }
  .copyblock { position: relative }
  .copybtn { position: absolute; top: .6em; right: .6em; z-index: 1;
             font: inherit; font-size: .8rem; padding: .35em .8em; border-radius: 999px;
             border: 1px solid var(--line, #e4d9c6); background: var(--surface, #fff); color: var(--ink, #2a2622);
             cursor: pointer }
  .copybtn:hover { background: var(--surface-muted, #efe7d9) }
  .doclinks { margin: var(--space-6, 2rem) 0 var(--space-8, 3rem); display: flex; flex-wrap: wrap; gap: 1rem }
"""

# ★스크립트는 **단추 하나**를 살리는 데만 쓴다. 없으면 단추가 나타나지 않고, 본문은 그대로 읽힌다.
COPY_JS = """
(function () {
  for (const btn of document.querySelectorAll('.copybtn')) {
    if (!navigator.clipboard) continue;
    btn.hidden = false;
    btn.addEventListener('click', async function () {
      const code = btn.parentElement.querySelector('code');
      try {
        await navigator.clipboard.writeText(code.innerText);
        const was = btn.textContent;
        btn.textContent = btn.dataset.copied;
        setTimeout(function () { btn.textContent = was; }, 1600);
      } catch (e) { /* 실패하면 아무 말도 만들지 않는다 — 사람이 직접 고르면 된다 */ }
    });
  }
})();
"""


def page_html(spec: dict[str, object], body: str) -> str:
    # ★복사 단추가 없는 쪽에는 **스크립트를 아예 넣지 않는다.** 하는 일이 없는 스크립트를 두면
    #   「이 페이지는 JS 없이 읽힌다」는 말이 눈으로 확인되지 않는다(있는데 안 쓰는 것과
    #   없는 것은 읽는 사람에게 다른 말이다).
    script = f"<script>{COPY_JS}</script>" if spec["copy_blocks"] else ""
    links = "".join(
        f'<a href="{html.escape(str(u), quote=True)}">{html.escape(t)}</a>'
        for u, t in spec["footer"]  # type: ignore[index]
    )
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(str(spec["title"]))}</title>
<meta name="description" content="{html.escape(str(spec["desc"]), quote=True)}">
<link rel="stylesheet" href="/assets/tokens.css">
<link rel="stylesheet" href="/assets/board.css">
<style>{PAGE_CSS}</style>
<!-- ★이 파일은 손으로 고치지 않는다. 정본 = {html.escape(str(spec["src"]))} ·
     고치는 법 = 그 문서를 고치고 `python3 tools/build_join_page.py` 한 줄. -->
</head>
<body>
<header class="topbar">
  <div class="wrap">
    <a class="brand" href="/">아고라</a>
    <nav class="topnav" aria-label="주요">
      <a href="/">로비</a>
      <a href="/archive">아카이브</a>
      <a class="cta" href="https://jarvis-install.godmeyou.kr/">설치 안내 →</a>
    </nav>
  </div>
</header>
<main class="wrap doc">
{body}
<p class="doclinks">{links}</p>
</main>
{script}
</body>
</html>
"""


def build(spec: dict[str, object]) -> tuple[str, str]:
    src = os.path.join(_ROOT, str(spec["src"]))
    with open(src, encoding="utf-8") as fh:
        md = fh.read()
    return os.path.join(_ROOT, str(spec["out"])), page_html(spec, render(md, spec["copy_blocks"]))  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="참가 안내 페이지를 문서에서 생성한다")
    ap.add_argument("--check", action="store_true",
                    help="쓰지 않고 대조만 한다(다르면 rc 1) — 게이트가 쓰는 길")
    args = ap.parse_args(argv)

    stale = []
    for spec in PAGES:
        out, doc = build(spec)
        if args.check:
            have = open(out, encoding="utf-8").read() if os.path.exists(out) else None
            if have != doc:
                stale.append(f"{spec['out']} ← {spec['src']}")
            continue
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(doc)
        print(f"생성 {spec['out']}  ← {spec['src']}  ({len(doc):,} 바이트)")

    if args.check:
        if stale:
            print("문서와 페이지가 다르다 — `python3 tools/build_join_page.py` 로 다시 만들어라:")
            for s in stale:
                print("  ·", s)
            return 1
        print("페이지가 문서와 같다(전건).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
