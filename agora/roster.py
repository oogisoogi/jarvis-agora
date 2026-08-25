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


def operators(root: str | None = None, *, path: str | None = None) -> frozenset[str]:
    """운영자 목록(K-3).

    ★`path` 로 **파일을 직접** 줄 수 있다. 참가자는 저장소를 체크아웃한 채 도는 것이 아니라
      설정 폴더에 명부 **사본**을 두고 돌기 때문이다(ONBOARDING §파일). 그 경로를 못 주면
      이 함수는 저장소 루트만 볼 수 있고, 그러면 **실사용에서 운영자가 0명**이 된다 —
      그 상태로도 아무 오류가 안 난다(`abort` 할 수 있는 사람이 없을 뿐이다).
    """
    text = _read(path or _path(root or _ROOT, ROSTER_OPERATORS)).decode("utf-8", "replace")
    return frozenset(
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _has_key_lines(path: str) -> bool:
    """주석·빈 줄 말고 **키가 한 줄이라도** 있는가."""
    text = _read(path).decode("utf-8", "replace")
    return any(line.strip() and not line.lstrip().startswith("#")
               for line in text.splitlines())


def _fingerprints_of(path: str) -> frozenset[str]:
    """공개키 파일의 지문 집합. 파일이 없거나 **키가 한 줄도 없으면** 공집합이다.

    ★★「키가 없는 파일」과 「못 읽는 파일」을 가른다(2026-08-26 실물에서 터졌다).
      `ssh-keygen -l -f` 는 **주석뿐인 파일**에 `is not a public key file` 로 실패한다.
      그런데 이 저장소의 `participants/revoked_keys` 정본이 바로 그 모양이다(설명 주석 3줄) —
      즉 **명부를 문서대로 복사한 참가자는 모든 읽기가 code 2 로 죽었다.**
    ⚠그렇다고 실패를 통째로 삼키면 안 된다. 삼키는 순간 **폐기가 조용히 꺼지고**,
      그것이 이 파일이 막으려는 바로 그 사고다. 그래서 **키 줄이 있을 때의 실패만** 올린다.
    """
    if not os.path.exists(path):
        # ★★H2(codex 2026-08-26 · R-14) — **부재는 「폐기된 키가 없다」가 아니다.**
        #   예전에는 여기서 공집합을 돌려줬다. 그러면 **파일 하나를 지우는 것이 곧
        #   폐기 목록 전체를 끄는 방법**이 된다 — 그리고 아무 표시도 나지 않는다.
        #   이 파일이 막으려는 사고(폐기 키로 서명한 글이 유효로 읽히는 것)가 정확히
        #   그 상태에서 난다. ⇒ **못 읽으면 멈춘다**(fail-closed).
        # ⚠「비어 있다」를 말하고 싶으면 **파일을 만들어라** — 주석만 있어도 된다.
        #   그것이 「없다」와 「비었다」를 가르는 유일한 방법이다.
        raise AgoraError(errors.PRECONDITION, "폐기 목록 파일이 없다 — 비었음은 빈 파일로 말한다",
                         {"file": os.path.basename(path),
                          "how": "빈 파일이나 주석만 있는 파일을 두면 「폐기된 키 0건」으로 읽는다"})
    if os.path.getsize(path) == 0:
        return frozenset()          # 있는데 비었다 = 명시적 0건
    if not _has_key_lines(path):
        return frozenset()          # 주석뿐 = 명시적 0건(위 docstring 의 실사고)
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


def allowed_signers_path(root: str | None = None) -> str:
    return _path(root or _ROOT, ROSTER_ALLOWED_SIGNERS)

