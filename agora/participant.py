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
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

from agora import errors
from agora.contract_open import PARTICIPANT_FIELDS, SIGN_NAMESPACE
from agora.errors import AgoraError

DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".config", "agora")
FILENAME = "participant.json"
CONFIG_FILENAME = "config.json"

# ★알려진 **잔재 칸** — 옛 설치기가 이 파일에 적었으나 계약(PARTICIPANT_FIELDS)에는 없는 칸.
#   계약 밖인 것은 맞지만 **정체가 분명하고 갈 자리가 있다**(2026-09-09 F-3 · 옛 설치기가
#   `"relay": "<주소>"` 를 여기 적었고, 그 주소의 자리는 config.json 이다).
#
#   ⚠모르는 칸은 **종전대로 거부한다.** 이 목록은 「계약을 넓히는 것」이 아니라
#   「우리가 만든 잔재를 우리가 치우는 것」이다 — 둘을 뭉치면 다음 사람이 여기에 칸을
#   하나 더 적는 것으로 계약을 우회한다.
#
#   ★왜 거부 대신 이관인가: 거부는 **참가자의 손을 부른다.** 실측(2026-09-10 노트북 실기)에서
#   사람이 편집기로 그 칸을 지워야 6단계가 넘어갔다. 우리가 적은 칸을 남이 지우게 하지 않는다.
LEGACY_FIELDS = ("relay",)


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
    unknown = [k for k in extra if k not in LEGACY_FIELDS]
    if unknown:
        # 모르는 칸을 조용히 무시하면, 언젠가 누가 여기 비밀을 넣는다.
        raise AgoraError(errors.PRECONDITION, "participant.json 에 계약 밖 칸이 있다",
                         {"extra": unknown})
    if extra:
        doc = _migrate_legacy(directory, path, doc, extra)
    if doc["namespace"] != SIGN_NAMESPACE:
        raise AgoraError(errors.PRECONDITION, "namespace 불일치",
                         {"got": doc["namespace"]})
    if type(doc["operator"]) is not bool:
        raise AgoraError(errors.PRECONDITION, "operator 는 참·거짓이어야 한다", None)
    return doc


# ── 잔재 칸 이관(2026-09-11 · 0.1.3) ──────────────────────────────────────────
# ★순서가 계약이다: **config.json 을 먼저 쓰고, 그것이 성공했을 때만** participant.json 을 고친다.
#   반대로 하면 이관 도중 실패했을 때 주소가 **양쪽 어디에도 없는** 상태가 만들어진다.
# ★어느 단계에서 실패하든 **load 는 실패시키지 않는다.** 실패는 경고로 말하고, 읽어 낸 값은
#   그대로 돌려준다 — 파일을 고치지 못한 것이 「참가자를 못 읽는 것」이 되면 F-3 을 형태만
#   바꿔 되풀이하는 셈이다(그때도 사람 손을 부르는 것이 문제였다).


def _relay_patch(value: Any) -> dict[str, Any]:
    """잔재 `relay` 칸의 값을 config.json 의 모양으로 옮긴다.

    옛 설치기가 적은 것은 **주소 문자열**이다(`"relay": "https://…"`). 뒤에 누가 사전으로
    적었을 경우도 받는다. 그 둘 밖의 모양은 **정체 불명**이므로 이관하지 않는다 —
    모양을 추측해 옮기면 틀린 주소를 조용히 심는다.
    """
    from agora.store_relay import DEFAULT_TIMEOUT_SECONDS
    if type(value) is str and value.strip():
        return {"transport": "relay",
                "relay": {"url": value.strip(),
                          "timeout_seconds": DEFAULT_TIMEOUT_SECONDS}}
    if type(value) is dict and type(value.get("url")) is str and value["url"].strip():
        relay = {"url": value["url"].strip(),
                 "timeout_seconds": value.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)}
        if type(relay["timeout_seconds"]) is not int:
            relay["timeout_seconds"] = DEFAULT_TIMEOUT_SECONDS
        return {"transport": "relay", "relay": relay}
    raise AgoraError(errors.PRECONDITION,
                     "participant.json 의 relay 칸 모양을 모른다 — 이관하지 않는다",
                     {"got": type(value).__name__})


def _write_private(path: str, text: str) -> None:
    """같은 폴더에 임시 파일로 쓴 뒤 자리를 바꾼다(반쯤 쓰인 파일이 남지 않는다)."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".agora-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _migrate_legacy(directory: str, path: str, doc: dict[str, Any],
                    legacy: list[str]) -> dict[str, Any]:
    """알려진 잔재 칸을 config.json 으로 옮기고, participant.json 을 계약대로 되돌린다."""
    cleaned = {k: v for k, v in doc.items() if k in PARTICIPANT_FIELDS}
    config_path = os.path.join(directory, CONFIG_FILENAME)

    try:
        patch = _relay_patch(doc["relay"]) if "relay" in legacy else {}
    except AgoraError as exc:
        # 모양을 모르면 **옮기지 않는다.** 그렇다고 읽기를 막지도 않는다 — 그 칸을 안 쓰면 될 뿐이다.
        sys.stderr.write(f"경고: {exc.message} — 그 칸은 그대로 두고 계속한다.\n")
        return cleaned

    try:
        existing: dict[str, Any] = {}
        if os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if type(loaded) is not dict:
                raise ValueError("config.json 은 객체여야 한다")
            existing = loaded
        # ★이미 있는 설정이 이긴다. 잔재는 **빈 자리를 메울 때만** 쓴다 —
        #   사람이 손으로 고친 주소를 옛 설치기가 적은 값으로 덮으면 그것은 이관이 아니라 되돌림이다.
        kept_existing = bool((existing.get("relay") or {}).get("url"))
        merged = dict(existing)
        if patch and not kept_existing:
            merged.setdefault("transport", patch["transport"])
            merged["relay"] = patch["relay"]
        _write_private(config_path,
                       json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError) as exc:
        sys.stderr.write(
            f"경고: 잔재 칸 {legacy} 을(를) {CONFIG_FILENAME} 으로 옮기지 못했다({exc}) — "
            "participant.json 은 손대지 않았다. 이 칸은 이번 실행에서 무시한다.\n")
        return cleaned

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path + ".bak-" + stamp
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        _write_private(backup, raw)
        _write_private(path,
                       json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        sys.stderr.write(
            f"경고: {CONFIG_FILENAME} 은 갱신했으나 participant.json 을 정리하지 못했다({exc}) — "
            "다음 실행에서 다시 시도한다.\n")
        return cleaned

    where = "이미 있던 설정을 그대로 두었다" if kept_existing else f"{CONFIG_FILENAME} 으로 옮겼다"
    sys.stderr.write(
        f"알림: participant.json 의 옛 칸 {legacy} 을(를) {where}"
        f"(백업 {os.path.basename(backup)}). 손볼 것 없다.\n")
    return cleaned
