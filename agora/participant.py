"""참가자 로컬 상태 — `~/.config/agora/participant.json`.

★이 파일에는 **비밀이 없다**(설계 §2-1a K-5). 담는 것은 지문뿐이고 개인키는 ssh-agent 나
  권한이 잠긴 키 파일에 있다. 그래서 이 파일이 새어도 서명 능력은 새지 않는다.

그럼에도 권한을 검사하는 이유: 권한이 헐거우면 **다른 프로세스가 내 참가자 id 를 바꿔치기**할 수 있다.
서명은 못 만들어도 「내가 누구라고 말하는가」를 바꾸는 것만으로 사고가 난다.
"""

from __future__ import annotations

import json
import os
import stat
from typing import Any

from agora import errors
from agora.contract_open import PARTICIPANT_FIELDS, SIGN_NAMESPACE
from agora.errors import AgoraError

DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".config", "agora")
FILENAME = "participant.json"


def config_dir() -> str:
    # ★절대경로로 돌려준다(R3-② · master#238398). 상대경로를 그대로 두면 cwd 가 다른 프로세스(서명기는
    #   저장소 루트 고정)가 **다른 폴더**를 본다 — 같은 문자열이 두 자리를 가리키는 셈이다.
    return os.path.abspath(os.environ.get("AGORA_CONFIG_DIR") or DEFAULT_DIR)


def _require_mode(path: str, want: int, what: str) -> None:
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode != want:
        raise AgoraError(
            errors.PRECONDITION,
            f"{what} 권한이 {oct(want)} 이어야 한다",
            {"path": os.path.basename(path), "mode": oct(mode), "want": oct(want)},
        )


def load(directory: str | None = None) -> dict[str, Any]:
    directory = directory or config_dir()
    path = os.path.join(directory, FILENAME)
    if not os.path.isdir(directory):
        raise AgoraError(errors.PRECONDITION, "참가자 설정 폴더가 없다",
                         {"dir": os.path.basename(directory)})
    _require_mode(directory, 0o700, "설정 폴더")
    if not os.path.exists(path):
        raise AgoraError(errors.PRECONDITION, "participant.json 이 없다",
                         {"file": FILENAME})
    _require_mode(path, 0o600, "participant.json")

    with open(path, encoding="utf-8") as fh:
        try:
            doc = json.load(fh)
        except ValueError as e:
            raise AgoraError(errors.PRECONDITION, "participant.json 파싱 실패",
                             {"error": str(e)}) from None
    if type(doc) is not dict:
        raise AgoraError(errors.PRECONDITION, "participant.json 은 객체여야 한다", None)

    missing = [f for f in PARTICIPANT_FIELDS if f not in doc]
    if missing:
        raise AgoraError(errors.PRECONDITION, "participant.json 필수 칸 누락",
                         {"missing": missing})
    extra = [k for k in doc if k not in PARTICIPANT_FIELDS]
    if extra:
        # 모르는 칸을 조용히 무시하면, 언젠가 누가 여기 비밀을 넣는다.
        raise AgoraError(errors.PRECONDITION, "participant.json 에 계약 밖 칸이 있다",
                         {"extra": extra})
    if doc["namespace"] != SIGN_NAMESPACE:
        raise AgoraError(errors.PRECONDITION, "namespace 불일치",
                         {"got": doc["namespace"]})
    if type(doc["operator"]) is not bool:
        raise AgoraError(errors.PRECONDITION, "operator 는 참·거짓이어야 한다", None)
    return doc
