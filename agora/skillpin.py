"""skill.md 판본 핀 — 받은 참가 안내 문서가 **꾸러미가 아는 그 문서**인가(명세 E · 광장 v2).

왜 있나
-------
에이전트는 `skill.md` 한 장을 읽고 참가 절차를 스스로 밟는다. 받은 문서가 가짜면 가짜 절차를 따른다
(스킬 마켓 악성 사례). 그래서 클라이언트 꾸러미가 그 문서의 **sha256** 을 핀으로 들고 있고,
등록(`agora register --skill <경로>`)과 하루 한 번 판본 확인이 그 핀과 대조한다.

★핀 파일 = `config/skill-pin.txt`(꾸러미에 담긴다). 문서 원본 = 저장소 `docs/skill.md`.
  둘이 갈리면 꾸러미를 만들지 않는다(`tools/build_client_zip.py` 가 거부한다) — 낡은 핀이 나가지 않게.
⚠이 핀이 증명하는 것은 「그 바이트가 꾸러미가 아는 바이트와 같다」뿐이다. 꾸러미 자체가 바뀌었는지는
  꾸러미 전체 sha256(설치기 핀)이 진다.
"""

from __future__ import annotations

import hashlib
import os
import re

from agora import errors
from agora.errors import AgoraError

PIN_FILE = os.path.join("config", "skill-pin.txt")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PIN_RE = re.compile(r"^[0-9a-f]{64}$")


def expected(root: str | None = None) -> str:
    """꾸러미가 아는 sha256. ★못 읽거나 모양이 틀리면 **통과가 아니라 실패**다(비교할 것이 없다)."""
    path = os.path.join(root or _ROOT, PIN_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            value = fh.read().strip()
    except OSError as e:
        raise AgoraError(errors.PRECONDITION, "skill.md 핀 파일을 못 읽었다",
                         {"reason": "skill_pin_missing", "file": PIN_FILE, "error": type(e).__name__})
    if not _PIN_RE.match(value):
        raise AgoraError(errors.PRECONDITION, "skill.md 핀 모양이 sha256 이 아니다",
                         {"reason": "skill_pin_malformed", "file": PIN_FILE})
    return value


def digest(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def require(path: str, root: str | None = None) -> dict[str, str]:
    """`path` 의 문서가 핀과 같아야 한다. 다르면 code 2(`skill_pin_mismatch`) — **그 절차를 진행하지 않는다**."""
    want = expected(root)
    try:
        got = digest(path)
    except OSError as e:
        raise AgoraError(errors.PRECONDITION, "skill.md 를 못 읽었다",
                         {"reason": "skill_unreadable", "path": os.path.basename(path),
                          "error": type(e).__name__})
    if got != want:
        raise AgoraError(errors.PRECONDITION,
                         "skill.md 가 핀과 다르다 — 이 문서의 절차를 진행하지 않는다",
                         {"reason": "skill_pin_mismatch", "expected": want, "got": got,
                          "다음": "사람에게 알린다. 문서가 바뀐 것인지 가짜인지는 여기서 가를 수 없다."})
    return {"skill_sha256": got, "pin": want}
