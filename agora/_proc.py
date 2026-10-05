"""자식 프로세스를 띄우는 **단 하나의 문** — 윈도우에서 콘솔 창을 만들지 않는다.

★2026-10-05 운영자 노트북 실측(D20): 상주(`agora resident once`)는 작업 스케줄러가 pythonw(콘솔 없음)로
  10분마다 부른다. 그 안에서 `ssh-keygen`(서명 확인)·`powershell`(Get-Acl) 자식이 숨김 인자 없이 뜨자
  자식마다 새 콘솔 창이 할당돼 **한 판에 창이 16~17개 깜빡였다**(22초 · hwnd≠0).
  숨김을 자리마다 붙이면 새 자리가 생길 때 빠진다 — 그래서 문을 하나로 모은다.
두 겹: `CREATE_NO_WINDOW`(콘솔 창 자체를 안 만든다) + `STARTUPINFO(SW_HIDE)`(창이 생기는 경로가 남아도
  보이지 않게). 윈도우가 아니면 인자를 **하나도 더하지 않는다**(맥·리눅스 행동 무변경).
★부르는 쪽이 준 `creationflags` 는 OR 로 합친다(지우지 않는다) · 부르는 쪽이 준 `startupinfo` 는 그대로 둔다.
★`subprocess.run` 등을 **부를 때마다** 속성으로 찾는다 — 시험이 `subprocess.run` 을 갈아 끼우면 그대로 닿는다.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

CREATE_NO_WINDOW = 0x08000000      # 맥의 subprocess 에는 상수가 없다 — 값은 Win32 정의 그대로
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0


def hidden(kwargs: dict[str, Any]) -> dict[str, Any]:
    """윈도우면 숨김 인자를 더한 **새** dict, 아니면 받은 그대로."""
    if os.name != "nt":
        return kwargs
    kw = dict(kwargs)
    kw["creationflags"] = (kw.get("creationflags") or 0) | getattr(
        subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW)
    if kw.get("startupinfo") is None:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", STARTF_USESHOWWINDOW)
        si.wShowWindow = getattr(subprocess, "SW_HIDE", SW_HIDE)
        kw["startupinfo"] = si
    return kw


def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(*args, **hidden(kwargs))


def Popen(*args: Any, **kwargs: Any) -> subprocess.Popen:  # noqa: N802 — subprocess 이름을 그대로 쓴다
    return subprocess.Popen(*args, **hidden(kwargs))


def check_output(*args: Any, **kwargs: Any) -> Any:
    return subprocess.check_output(*args, **hidden(kwargs))
