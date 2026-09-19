#!/usr/bin/env python3
"""시험용 릴레이(agora-relay-next)의 정적 자산을 만든다 — `relay/board-next/`(저장소에 안 올린다).

왜 따로 만드나
--------------
시험용 릴레이는 **본 릴레이와 같은 코드**를 다른 이름·다른 D1·workers.dev 주소로 띄운다(2026-09-19 오너 채택 ④).
참가하는 사람은 **붙여넣기 1회**로 들어와야 하므로, 그 덩어리가 가리키는 세 값이 시험용이어야 한다:
  ⑴ 릴레이 주소 = 시험용 주소  ⑵ 꾸러미 = 후보 판(이 트리를 빌드한 것)  ⑶ 그 꾸러미의 지문
그리고 ⑷ 등록 줄의 skill.md 핀 — 이것은 **페이지 빌더의 주입 함수**가 붙인다(`build_join_page.inject_skill_pin` · 단일).

무엇을 만드나
-------------
    relay/board-next/                         = relay/board 사본(dev/ 제외)
    relay/board-next/join/index.html          = docs/NEXT-RELAY-TRIAL-2026-09-19.md 의 {{…}} 자리를 채워 렌더한 참가 안내
    relay/board-next/install/agora-client-<판>.zip = 이 트리의 꾸러미(dist/ 에서 복사 · 다시 빌드하지 않는다)

⛔라이브 안내(`docs/INVITE.md`·`relay/board/join/`)는 쓰지 않는다 — 라이브 덩어리는 참가자 폴더가 ~/.config/agora 라,
  이미 본 아고라에 참가한 기계에서 붙여넣으면 그 신원의 릴레이 주소·상주 일정(기계당 1개)·표지를 덮는다.
  시험 안내는 폴더를 ~/.config/agora-next 로 가르고 상주·표지 단계를 뺀 **별도 덩어리**다.
⛔본 릴레이 주소·꾸러미 게시 자리(jarvis.godmeyou.kr)에 닿는 동작은 없다.

쓰기
----
    python3 tools/build_next_trial.py --next-url https://agora-relay-next.<계정>.workers.dev
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "relay", "board-next")
SOURCE = os.path.join("docs", "NEXT-RELAY-TRIAL-2026-09-19.md")
_SLOT_RE = re.compile(r"\{\{[A-Z_]+\}\}")


def _module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                      # type: ignore[union-attr]
    return mod


def fill(md: str, values: dict[str, str]) -> str:
    """시험 안내의 `{{…}}` 자리를 채운다. 모르는 자리가 남으면 **멈춘다**(빈 자리를 페이지에 싣지 않는다)."""
    for key, value in values.items():
        slot = "{{" + key + "}}"
        if slot not in md:
            raise SystemExit(f"시험 안내에 {slot} 자리가 없다")
        md = md.replace(slot, value)
    left = _SLOT_RE.findall(md)
    if left:
        raise SystemExit(f"안 채운 자리가 남았다: {sorted(set(left))}")
    return md


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="시험용 릴레이 정적 자산(relay/board-next/)을 만든다")
    ap.add_argument("--next-url", required=True, help="시험용 릴레이 주소(https://…workers.dev)")
    args = ap.parse_args(argv)
    if not re.match(r"^https://[a-z0-9-]+\.[a-z0-9-]+\.workers\.dev/?$", args.next_url):
        raise SystemExit("--next-url 은 workers.dev 주소여야 한다(커스텀 도메인 금지 · 본 릴레이와 섞이지 않게)")

    bjp = _module("build_join_page_next", "tools/build_join_page.py")
    bcz = _module("build_client_zip_next", "tools/build_client_zip.py")
    ver = bcz.client_version()
    zip_name = f"agora-client-{ver}.zip"
    zip_path = os.path.join(_ROOT, "dist", zip_name)
    subprocess.run([sys.executable, os.path.join(_ROOT, "tools", "build_client_zip.py"), "--out", zip_path],
                   check=True, cwd=_ROOT)
    with open(zip_path, "rb") as fh:
        zip_sha = hashlib.sha256(fh.read()).hexdigest()

    relay = args.next_url.rstrip("/")
    src = open(os.path.join(_ROOT, SOURCE), encoding="utf-8").read()
    md = fill(src, {"RELAY": relay, "ZIP_NAME": zip_name, "ZIP_SHA": zip_sha,
                    "ZIP_URL": f"{relay}/install/{zip_name}"})
    if "agora.godmeyou.kr/join" in md or "jarvis.godmeyou.kr/install" in md:
        raise SystemExit("시험 안내가 본 릴레이 참가 페이지·게시 자리를 가리킨다")
    md, added = bjp.inject_skill_pin(md, bjp.read_skill_pin())
    if added != 1:
        raise SystemExit(f"등록 줄에 핀이 붙지 않았다({added}줄) — 판본 게이트({bjp.SKILL_PIN_SINCE}) 아래 판이다")
    spec = dict(bjp.PAGES[0])
    spec["title"] = "아고라 — 시험용 릴레이 참가 안내"
    spec["desc"] = "광장 v2 를 본 릴레이와 떨어진 자리에서 먼저 써 보는 참가 안내."
    spec["footer"] = ()
    page = bjp.page_html(spec, bjp.render(md, spec["copy_blocks"]))

    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    shutil.copytree(os.path.join(_ROOT, "relay", "board"), OUT, ignore=shutil.ignore_patterns("dev"))
    # ★라이브 윈도우 안내(/join/windows)는 뺀다 — 참가자 폴더가 ~/.config/agora 라 시험용 자리에서 따르면 라이브 신원을 덮는다.
    shutil.rmtree(os.path.join(OUT, "join"), ignore_errors=True)
    os.makedirs(os.path.join(OUT, "join"), exist_ok=True)
    with open(os.path.join(OUT, "join", "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    os.makedirs(os.path.join(OUT, "install"), exist_ok=True)
    shutil.copyfile(zip_path, os.path.join(OUT, "install", zip_name))
    print(f"relay/board-next/ 생성 · 꾸러미 {zip_name} sha256 {zip_sha} · 등록 줄 핀 {added}줄")
    return 0


if __name__ == "__main__":
    sys.exit(main())
