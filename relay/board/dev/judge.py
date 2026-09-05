#!/usr/bin/env python3
"""judge.py — probe 가 남긴 측정 JSON 을 합격 기준으로 판정한다. 기준을 코드에 한 번만 적는다."""
import json
import pathlib
import sys

MIN_FONT_PX = 18.0      # 브리프 규율: 글자 바닥 18
MIN_CONTRAST = 4.5      # WCAG 2.1 AA 본문
ALLOWED_EXTERNAL = {"https://jarvis-install.godmeyou.kr/"}
# 배포는 확장자를 뗀 주소로 서빙한다 — 링크 전수 검사는 그 주소를 실제 파일로 되돌려 확인한다.
EXTENSIONLESS = {"/": "index.html", "/room": "room.html", "/archive": "archive.html"}
PLACEHOLDER_WORDS = ("알 수 없음", "미상", "undefined", "null", "[object Object]")
# ★양성 구조 단언 — 「없는 것을 안 그린다」만 재면, 렌더가 통째로 죽어도 그 검사는 초록이다.
#   서버가 준 값이 **실제로 그려지는지**를 함께 못박아야 그물이 생긴다.
MUST_HAVE_FIELD = {"room-resolved": "의장", "room-r2": "의장", "lobby": "의장", "archive": "종결"}
# ★권고 상자는 **의장이 낸 권고**일 때만 뜬다. room-r2 에는 의장이 아닌 이가 낸 권고가 섞여 있으므로
#   그 화면에 상자가 뜨면 이 화면이 남의 글을 방의 결론이라고 말한 것이다.
MUST_HAVE_RESOLUTION = {"room-resolved"}
MUST_NOT_HAVE_RESOLUTION = {"room-r2"}

out = pathlib.Path(sys.argv[1])
board = out.parent.parent          # relay/board
files = sorted(p for p in out.glob("*.json") if p.stem not in {"nosig", "partial", "nochair"})
if not files:
    print("  FAIL — 측정 파일이 없다(probe 가 하나도 안 돌았다)")
    sys.exit(1)

rc = 0
print(f"  {'화면':22s} {'정착':5s} {'최소글자':>8s} {'넘침':>6s} {'최저대비':>8s} {'푸터':>4s}")
for f in files:
    d = json.loads(f.read_text())
    font = d.get("minFontPx")
    over = d.get("overflowPx")
    con = (d.get("worstContrast") or {}).get("ratio")
    foot = d.get("footerCount")
    bad = []
    if d.get("settled") is not True: bad.append("정착 실패")
    if font is None or font < MIN_FONT_PX: bad.append(f"글자 {font}px < {MIN_FONT_PX}")
    if over is None or over > 0: bad.append(f"가로 넘침 {over}px")
    if con is None or con < MIN_CONTRAST: bad.append(f"대비 {con} < {MIN_CONTRAST}")
    if foot != 1: bad.append(f"하단 고정 문구 {foot}회")
    text = d.get("allText") or ""
    for w in PLACEHOLDER_WORDS:
        if w in text: bad.append(f"자리 메움 문구 「{w}」가 화면에 있다")
    stem = f.stem.rsplit("-", 1)[0]
    box = d.get("hasResolutionBox")
    if stem in MUST_HAVE_RESOLUTION and box is not True:
        bad.append("의장이 낸 권고가 있는데 권고 상자가 없다")
    if stem in MUST_NOT_HAVE_RESOLUTION and box is True:
        bad.append("의장이 내지 않은 권고를 방의 결론으로 올렸다")
    need = MUST_HAVE_FIELD.get(stem)
    if need is not None and not any(need in x for x in d.get("fields", [])):
        bad.append(f"서버가 준 「{need}」 칸이 화면에 없다(렌더가 죽었을 수 있다)")
    for href in d.get("links", []):
        if href.startswith("http"):
            if href not in ALLOWED_EXTERNAL: bad.append(f"허용 밖 바깥 링크 {href}")
        else:
            target = href.split("?")[0].split("#")[0]
            target = EXTENSIONLESS.get(target, target.lstrip("/"))
            if target and not (board / target).exists(): bad.append(f"깨진 링크 {href}")
    mark = "OK " if not bad else "FAIL"
    print(f"  {f.stem:22s} {str(d.get('settled')):5s} {str(font):>8s} {str(over):>6s} {str(con):>8s} {str(foot):>4s}  {mark}")
    for b in bad:
        print(f"      · {b}")
        rc = 1

print(f"  측정 {len(files)}건 · 판정 {'PASS' if rc == 0 else 'FAIL'}")
sys.exit(rc)
