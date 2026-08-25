"""`agora keygen` — 참가자 키와 설정을 만든다.

★출력에는 **지문만** 나온다(설계 02 §S-15). 개인키도, 공개키 전문도 화면에 뿌리지 않는다.
  화면에 뿌린 것은 로그·스크롤백·캡처로 남는다.
  명부에 올릴 공개키는 파일 경로를 알려 주고 사람이 직접 붙이게 한다.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from typing import Any

from agora import errors
from agora.contract_open import SIGN_NAMESPACE
from agora.errors import AgoraError
from agora.participant import FILENAME, config_dir

KEY_NAME = "id_ed25519"


def _fingerprint(pub_path: str) -> str:
    proc = subprocess.run(["ssh-keygen", "-l", "-f", pub_path],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AgoraError(errors.PRECONDITION, "지문을 읽을 수 없다",
                         {"stderr": proc.stderr.strip()[:200]})
    for token in proc.stdout.split():
        if token.startswith("SHA256:"):
            return token
    raise AgoraError(errors.PRECONDITION, "지문 형식을 찾지 못했다", None)


def run(rest: list[str]) -> dict[str, Any]:
    participant_id = rest[0] if rest else None
    if not participant_id:
        raise AgoraError(errors.ARGUMENT, "참가자 id 가 필요하다",
                         {"usage": "agora keygen <participant-id>"})

    directory = config_dir()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)

    key_path = os.path.join(directory, KEY_NAME)
    if os.path.exists(key_path):
        # 덮어쓰면 그 키로 서명된 과거 이벤트를 아무도 검증할 수 없게 된다.
        raise AgoraError(errors.ARGUMENT, "이미 키가 있다 — 덮어쓰지 않는다",
                         {"file": KEY_NAME})

    proc = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", f"agora:{participant_id}",
         "-f", key_path, "-q"],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise AgoraError(errors.PRECONDITION, "키 생성 실패",
                         {"stderr": proc.stderr.strip()[:200]})
    os.chmod(key_path, 0o600)
    pub_path = key_path + ".pub"
    fingerprint = _fingerprint(pub_path)

    conf_path = os.path.join(directory, FILENAME)
    doc = {
        "id": participant_id,
        "display_name": participant_id,
        "key_fingerprint": fingerprint,
        "namespace": SIGN_NAMESPACE,
        "operator": False,
    }
    with open(conf_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, sort_keys=True, indent=2)
    os.chmod(conf_path, 0o600)

    return {
        "id": participant_id,
        "key_fingerprint": fingerprint,
        "namespace": SIGN_NAMESPACE,
        "public_key_file": pub_path,
        "다음": [
            "이 공개키 파일의 내용을 participants/allowed_signers 에 한 줄로 더하는 변경 제안을 올린다.",
            "형식: <participant-id> <공개키 한 줄 그대로>",
            "★개인키와 지문 외의 값은 화면에 출력하지 않았다 — 공개키는 위 파일에서 직접 복사한다.",
        ],
        "permissions": {"dir": oct(stat.S_IMODE(os.stat(directory).st_mode)),
                        "key": oct(stat.S_IMODE(os.stat(key_path).st_mode)),
                        "config": oct(stat.S_IMODE(os.stat(conf_path).st_mode))},
    }
