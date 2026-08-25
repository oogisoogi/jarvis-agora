"""명부와 키 수명주기 — 「이 서명을 누가 했고, 그 사람이 지금도 유효한가」.

세 파일이 한 벌이다(설계 §7·§2-1a):
  · `participants/allowed_signers` — 누가 참가자인가
  · `participants/revoked_keys`    — 어느 키가 폐기됐는가(평문 공개키 목록)
  · `participants/operators`       — 누가 운영자인가(`abort`·체크포인트 서명 권한)

★셋의 **체크포인트 해시**를 이벤트에 실어 보낸다. 그래야 「그때의 명부로는 유효했다」와
  「지금 명부로는 무효다」를 나중에 구별할 수 있다. 명부는 시간에 따라 바뀌는데
  서명은 과거에 일어난 일이기 때문이다.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Any

from agora import errors
from agora.contract_open import (
    ROSTER_ALLOWED_SIGNERS, ROSTER_OPERATORS, ROSTER_REVOKED_KEYS,
)
from agora.errors import AgoraError

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(root: str, rel: str) -> str:
    return os.path.join(root, rel)


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        # 없는 것도 상태다 — 빈 바이트로 취급하되, 체크포인트에는 그 사실이 반영된다.
        return b""


def checkpoint(root: str | None = None) -> str:
    """명부 3종의 내용 해시. 파일 하나만 바뀌어도 값이 바뀐다."""
    root = root or _ROOT
    h = hashlib.sha256()
    for rel in (ROSTER_ALLOWED_SIGNERS, ROSTER_REVOKED_KEYS, ROSTER_OPERATORS):
        blob = _read(_path(root, rel))
        # 파일 경계를 해시에 넣는다 — 안 넣으면 A의 끝과 B의 시작을 옮겨도 같은 해시가 된다.
        h.update(rel.encode("utf-8"))
        h.update(len(blob).to_bytes(8, "big"))
        h.update(blob)
    return h.hexdigest()


def operators(root: str | None = None) -> frozenset[str]:
    root = root or _ROOT
    text = _read(_path(root, ROSTER_OPERATORS)).decode("utf-8", "replace")
    return frozenset(
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def is_operator(participant_id: str, root: str | None = None) -> bool:
    return participant_id in operators(root)


def _fingerprints_of(path: str) -> frozenset[str]:
    """공개키 파일의 지문 집합. 파일이 없거나 비면 공집합이다."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return frozenset()
    proc = subprocess.run(["ssh-keygen", "-l", "-f", path],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AgoraError(errors.PRECONDITION, "폐기 목록을 읽을 수 없다",
                         {"stderr": proc.stderr.strip()[:200]})
    out: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        for p in parts:
            if p.startswith("SHA256:"):
                out.add(p)
    return frozenset(out)


def revoked_fingerprints(root: str | None = None) -> frozenset[str]:
    root = root or _ROOT
    return _fingerprints_of(_path(root, ROSTER_REVOKED_KEYS))


def allowed_signers_path(root: str | None = None) -> str:
    return _path(root or _ROOT, ROSTER_ALLOWED_SIGNERS)


def revoked_keys_path(root: str | None = None) -> str:
    return _path(root or _ROOT, ROSTER_REVOKED_KEYS)
