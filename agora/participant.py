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


# ★윈도우(2026-09-10 · 운영자 노트북 실기 · 0.1.1 6단계 결함): POSIX 비트는 윈도우에서
#   폴더 0o777 · 파일 0o666 으로 **고정**이라 0o700/0o600 을 만들 수도, 잴 수도 없다.
#   윈도우의 「나만 접근」은 ACL 이므로 같은 뜻을 ACL 로 잰다 — 널리 알려진 SID 세 개
#   (Everyone S-1-1-0 · BUILTIN\Users S-1-5-32-545 · Authenticated Users S-1-5-11)가
#   접근 항목에 있으면 남이 읽을 수 있는 자리다. 이름이 아니라 SID 로 비교한다(한국어
#   윈도우에서 그룹 이름은 번역돼 보인다). ACL 을 못 읽으면 통과시키지 않는다(fail-closed).
_WIN_PUBLIC_SIDS = ("S-1-1-0", "S-1-5-32-545", "S-1-5-11")


def _windows_acl_sids(path: str) -> list[str]:
    """PowerShell Get-Acl 로 접근 항목의 SID 를 낸다(허용 항목만). 실패 = 예외."""
    import subprocess
    cmd = (
        "(Get-Acl -LiteralPath '" + path.replace("'", "''") + "').Access | "
        "Where-Object { $_.AccessControlType -eq 'Allow' } | ForEach-Object { "
        "try { $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } "
        "catch { $_.IdentityReference.Value } }"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:200])
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _require_private_windows(path: str, what: str) -> None:
    try:
        sids = _windows_acl_sids(path)
    except Exception as exc:  # noqa: BLE001 — 못 읽으면 통과 아님
        raise AgoraError(
            errors.PRECONDITION,
            f"{what} 권한(ACL)을 확인하지 못했다",
            {"path": os.path.basename(path), "why": str(exc)[:120]},
        ) from exc
    public = sorted(s for s in sids if s in _WIN_PUBLIC_SIDS)
    if public:
        raise AgoraError(
            errors.PRECONDITION,
            f"{what} 은(는) 나만 접근할 수 있어야 한다 — 다른 사용자 그룹에 열려 있다",
            {"path": os.path.basename(path), "public_sids": public,
             "hint": "icacls <경로> /inheritance:r /grant:r \"%USERNAME%:(OI)(CI)F\""},
        )


def _require_mode(path: str, want: int, what: str) -> None:
    if os.name == "nt":
        _require_private_windows(path, what)
        return
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
