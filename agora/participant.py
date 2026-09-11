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

from agora import _lock, errors
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

# ★잔재 `relay` 칸이 사전일 때 **허용되는 칸의 전부**(닫힌 스키마 · codex 1R [5]).
#   바깥만 검사하면 사전 한 겹이 그대로 계약 우회로가 된다 — 「relay: {url, token}」 이
#   조용히 통과하고 token 은 소리 없이 버려진다. 버리는 자리가 어디든 같은 병이다.
RELAY_LEGACY_KEYS = ("url", "timeout_seconds")


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


def _which(name: str) -> str | None:
    """실행 파일 찾기 — **시험이 갈아 끼울 수 있게** 한 겹 둔다(맥에는 둘 다 없다)."""
    import shutil
    return shutil.which(name)


def _winps_51_module_path(env: dict[str, str]) -> str:
    """Windows PowerShell 5.1 의 **기본** `PSModulePath`.

    ★값을 환경에서 만든다 — `%ProgramFiles%` 는 한국어·32/64비트 기계에서 다르고, 문자열을
      박아 두면 그 기계에서만 조용히 빗나간다. 없으면 널리 쓰이는 기본값으로 떨어진다.
    """
    program_files = env.get("ProgramFiles") or r"C:\Program Files"
    system_root = env.get("SystemRoot") or r"C:\Windows"
    # ⚠원시 문자열로 적는다 — `\v1.0` 은 보통 문자열에서 **수직 탭**이 된다
    #   (이 파일에서 실제로 그렇게 났다 · 눈으로는 안 보이는 종류의 오류다).
    return (program_files + r"\WindowsPowerShell\Modules;"
            + system_root + r"\system32\WindowsPowerShell\v1.0\Modules")


def _powershell_invocation(env: dict[str, str] | None = None
                           ) -> tuple[list[str], dict[str, str], str, str]:
    """윈도우에서 PowerShell 자식을 띄우는 **단 하나의 문** — (argv, env, 이름, 모듈경로).

    ★★윈도우 첫 실측(K-1 · 2026-09-11 · 테스트팀)이 여기서 막혔다(등록이 code 2 로 차단):
      **PowerShell 7 안에서 띄운 터미널이 자식에게 7용 `PSModulePath` 를 물려주는데**,
      우리가 부른 것은 `powershell`(5.1)이었다. 5.1 이 7용 보안 모듈을 집어 로드에 실패했고
      `Get-Acl` 이 죽었다. 테스터가 자식 환경의 `PSModulePath` 를 5.1 기본값으로 고정하니
      그대로 통과했다 — ★**우리 코드가 아니라 물려받은 환경이 원인이었고, 우리는 그 환경을
      물려주기만 했다.** 자식에게 무엇을 물려줄지는 부르는 쪽이 정해야 한다.
    ⇒ ⑴`pwsh`(7)가 있으면 **그것을 먼저** 부른다: 7 용 환경을 7 이 받으면 어긋남이 없다.
      ⑵`powershell`(5.1)을 부를 때는 `PSModulePath` 를 **5.1 기본값으로 고정**한다.
      ⑶실패하면 **어느 PowerShell·어느 모듈 경로**였는지 말한다(code 2 뒤에 숨기지 않는다).
    ★이 문이 하나여야 하는 이유: 자식을 띄우는 자리가 둘이 되면 한쪽만 고쳐진 채 남고,
      그 한쪽은 **그 기계에서만** 죽는다 — 개발기에서는 영원히 초록이다.
    """
    env = dict(os.environ if env is None else env)
    exe = _which("pwsh")
    if exe:
        # 7 은 자기 모듈 경로를 스스로 안다 — 물려받은 값을 그대로 둔다(고정이 오히려 해롭다).
        return ([exe, "-NoProfile", "-NonInteractive", "-Command"], env, "pwsh",
                env.get("PSModulePath", ""))
    exe = _which("powershell") or "powershell"
    env["PSModulePath"] = _winps_51_module_path(env)
    return ([exe, "-NoProfile", "-NonInteractive", "-Command"], env, "powershell",
            env["PSModulePath"])


def _windows_acl_sids(path: str) -> list[str]:
    """PowerShell Get-Acl 로 접근 항목의 SID 를 낸다(허용 항목만). 실패 = 예외.

    ⚠예외 문면에 **어느 PowerShell·어느 모듈 경로**를 싣는다 — 그 두 값이 없으면 K-1 같은
      환경 사고가 「Get-Acl 이 실패했다」로만 보이고, 받는 사람은 고칠 데를 못 찾는다.
    """
    import subprocess
    cmd = (
        "(Get-Acl -LiteralPath '" + path.replace("'", "''") + "').Access | "
        "Where-Object { $_.AccessControlType -eq 'Allow' } | ForEach-Object { "
        "try { $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } "
        "catch { $_.IdentityReference.Value } }"
    )
    argv, env, shell_name, module_path = _powershell_invocation()
    r = subprocess.run(argv + [cmd], capture_output=True, text=True, timeout=20, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"[{shell_name}] " + (r.stderr or r.stdout).strip()[:160]
                           + f" | PSModulePath={module_path[:160]}")
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
    unknown += _unknown_inside_legacy(doc, extra)
    if unknown:
        # 모르는 칸을 조용히 무시하면, 언젠가 누가 여기 비밀을 넣는다.
        # ★잔재 칸 **안쪽**도 같은 규칙이다(codex 1R [5]) — 바깥만 보면 사전 한 겹이
        #   그대로 우회로가 된다. 「모르는 것을 조용히 버린다」는 버리는 자리가 어디든 같은 병이다.
        raise AgoraError(errors.PRECONDITION, "participant.json 에 계약 밖 칸이 있다",
                         {"extra": sorted(unknown)})
    # ★★계약 검증을 **이관보다 먼저** 끝낸다(codex 1R [2]).
    #   거부될 파일이 파일을 고치게 두면, 남이 준 participant.json 하나로 내 config.json 의
    #   릴레이 주소가 바뀐다 — 거부는 「아무 일도 일어나지 않았다」여야 한다.
    if doc["namespace"] != SIGN_NAMESPACE:
        raise AgoraError(errors.PRECONDITION, "namespace 불일치",
                         {"got": doc["namespace"]})
    if type(doc["operator"]) is not bool:
        raise AgoraError(errors.PRECONDITION, "operator 는 참·거짓이어야 한다", None)
    if extra:
        doc = _migrate_legacy(directory, path, doc, extra)
    return doc


# ── 잔재 칸 이관(2026-09-11 · 0.1.3 · codex 1R 봉합 반영) ────────────────────
# ★순서가 계약이다: **config.json 을 먼저 쓰고, 그것이 성공했을 때만** participant.json 을 고친다.
#   반대로 하면 이관 도중 실패했을 때 주소가 **양쪽 어디에도 없는** 상태가 만들어진다.
# ★어느 단계에서 실패하든 **load 는 실패시키지 않는다.** 실패는 경고로 말하고, 읽어 낸 값은
#   그대로 돌려준다 — 파일을 고치지 못한 것이 「참가자를 못 읽는 것」이 되면 F-3 을 형태만
#   바꿔 되풀이하는 셈이다(그때도 사람 손을 부르는 것이 문제였다).
# ★이관 전체는 **옆 파일 잠금** 아래에서 한다(codex 1R [3]). 두 프로세스가 같은 옛 파일을
#   동시에 읽으면 뒤늦은 쪽이 **이미 정리된 파일을 백업**해 원본이 백업에서 사라진다.
#   잠근 뒤에 **다시 읽는다** — 잠그기 전에 읽은 것은 이미 낡았을 수 있기 때문이다.


def _relay_shape_problem(value: Any) -> str | None:
    """옛 `relay` 칸의 **모양**을 본다. 괜찮으면 None, 아니면 **문제의 이름**을 댄다.

    ★모양의 정의처를 여기 하나로 둔다(agy 2R [2]). 전에는 「사전 안쪽의 모르는 칸」은 거부하고
      「사전도 문자열도 아닌 값」은 경고만 내고 **조용히 지웠다** — 같은 계약을 두 자리에서 다르게
      집행한 셈이라, 사전을 피해 리스트로 적으면 검사를 지나갔다.
    ★받는 모양은 둘뿐이다: **비어 있지 않은 주소 문자열**, 또는 **`url`(+선택 `timeout_seconds`)만
      가진 사전.** 나머지는 전부 거부한다 — 모양을 추측해 옮기면 틀린 주소를 조용히 심는다.
    """
    if type(value) is str:
        return None if value.strip() else "relay(주소가 비었다)"
    if type(value) is dict:
        bad = sorted(f"relay.{k}" for k in value if k not in RELAY_LEGACY_KEYS)
        if bad:
            return ", ".join(bad)
        url = value.get("url")
        if type(url) is not str or not url.strip():
            return "relay.url(주소가 없다)"
        return None
    return f"relay(모양 불명: {type(value).__name__})"


def _unknown_inside_legacy(doc: dict[str, Any], legacy: list[str]) -> list[str]:
    """잔재 칸에서 **계약 밖으로 볼 것**의 이름을 낸다(`relay.token` · `relay(모양 불명: list)`)."""
    out: list[str] = []
    for name in legacy:
        if name != "relay":
            continue
        problem = _relay_shape_problem(doc.get(name))
        if problem:
            out.append(problem)
    return out


def _relay_patch(value: Any) -> dict[str, Any]:
    """잔재 `relay` 칸의 값을 config.json 의 모양으로 옮긴다.

    ★모양 검사는 이미 `load` 에서 끝났다(`_relay_shape_problem`) — 여기서 다시 판정하지 않는다.
      같은 규칙을 두 자리에 두면 언젠가 둘이 갈라지고, 갈라진 쪽이 우회로가 된다.
    """
    from agora.store_relay import DEFAULT_TIMEOUT_SECONDS
    if type(value) is str:
        return {"transport": "relay",
                "relay": {"url": value.strip(),
                          "timeout_seconds": DEFAULT_TIMEOUT_SECONDS}}
    relay = {"url": value["url"].strip(),
             "timeout_seconds": value.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)}
    if type(relay["timeout_seconds"]) is not int:
        relay["timeout_seconds"] = DEFAULT_TIMEOUT_SECONDS
    return {"transport": "relay", "relay": relay}


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


def _write_new_backup(path: str, text: str) -> str:
    """**아무것도 덮지 않는** 백업을 만든다 — 이름이 겹치면 옆자리를 잡는다(codex 1R [3]).

    ★`os.replace` 로 백업을 쓰면 같은 초에 두 번 이관될 때 앞 백업이 소리 없이 사라진다.
      백업의 값어치는 「덮이지 않는다」는 것뿐이므로 `O_EXCL` 로 **만들어지는 것 자체를** 건다.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{path}.bak-{stamp}"
    candidate, n = base, 2
    while True:
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            candidate, n = f"{base}-{n}", n + 1
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        return candidate


def _migrate_legacy(directory: str, path: str, doc: dict[str, Any],
                    legacy: list[str]) -> dict[str, Any]:
    """알려진 잔재 칸을 config.json 으로 옮기고, participant.json 을 계약대로 되돌린다.

    잠금을 잡지 못하면(잠글 수단이 없는 파이썬 포함) **이관을 포기하고 읽기만 살린다** —
    잠금 없이 고치는 것보다 안 고치는 편이 낫다(다음 실행이 다시 시도한다).
    """
    cleaned = {k: v for k, v in doc.items() if k in PARTICIPANT_FIELDS}
    try:
        lock = open(path + ".lock", "a+")           # noqa: SIM115 — 아래 finally 가 닫는다
    except OSError as exc:
        sys.stderr.write(f"경고: 이관 잠금 파일을 열지 못했다({exc}) — 이번엔 옮기지 않는다.\n")
        return cleaned
    try:
        _lock.acquire(lock)
        try:
            return _migrate_locked(directory, path, cleaned, legacy)
        finally:
            _lock.release(lock)
    except OSError as exc:
        sys.stderr.write(f"경고: 이관 잠금을 잡지 못했다({exc}) — 이번엔 옮기지 않는다.\n")
        return cleaned
    finally:
        lock.close()


def _config_on_disk(path: str) -> dict[str, Any] | None:
    """지금 디스크에 있는 config.json 을 읽는다 — 없으면 `{}`, 못 읽으면 **None**(= 대조 불가).

    ★None 을 「빈 설정」과 다르게 둔다: 못 읽는 것과 없는 것을 같게 보면, 파일을 깨뜨리는 것이
      곧 덮어쓰기 허가가 된다.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
    except (OSError, ValueError):
        return None
    return loaded if type(loaded) is dict else None


def _migrate_locked(directory: str, path: str, cleaned: dict[str, Any],
                    legacy: list[str]) -> dict[str, Any]:
    """잠금을 쥔 채 하는 일. **다시 읽는 것으로 시작한다.**"""
    try:
        with open(path, encoding="utf-8") as fh:
            fresh = json.load(fh)
    except (OSError, ValueError):
        fresh = None
    if type(fresh) is dict:
        still = [k for k in fresh if k in LEGACY_FIELDS]
        if not still:
            # 다른 프로세스가 이미 옮겼다 — 우리가 할 일이 없다(그리고 그 파일을 백업하지 않는다).
            return {k: v for k, v in fresh.items() if k in PARTICIPANT_FIELDS}
        legacy = still
        cleaned = {k: v for k, v in fresh.items() if k in PARTICIPANT_FIELDS}
        doc: dict[str, Any] = fresh
    else:
        return cleaned

    config_path = os.path.join(directory, CONFIG_FILENAME)
    patch = _relay_patch(doc["relay"]) if "relay" in legacy else {}

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
        # ★모양을 모르는 relay 도 「이미 있는 것」으로 본다(codex 1R [4]): 남의 설정을
        #   우리가 이해하지 못한다는 이유로 덮어쓰지 않는다. 사전이 아니면 `.get` 이 터지므로
        #   **타입부터** 가른다.
        current = existing.get("relay")
        if current is not None and type(current) is not dict:
            sys.stderr.write(
                f"경고: {CONFIG_FILENAME} 의 relay 모양을 모른다({type(current).__name__})"
                " — 덮지 않고 그대로 둔다.\n")
            kept_existing = True
        else:
            kept_existing = bool((current or {}).get("url"))
        merged = dict(existing)
        if patch and not kept_existing:
            merged.setdefault("transport", patch["transport"])
            merged["relay"] = patch["relay"]
        # ★바꿀 것이 없으면 **쓰지 않는다.** 있던 설정이 이겨서 내용이 그대로인데도 다시 쓰면
        #   남의 파일을 정렬·들여쓰기만 바꿔 건드리는 셈이고, 쓰지 않아도 될 자리에서 실패할 수 있다.
        if merged != existing or not os.path.exists(config_path):
            # ★쓰기 직전에 **다시 읽어 대조한다**(agy 2R [1] — 갱신 유실).
            #   config.json 은 우리 잠금을 모르는 손도 쓴다(사람 편집기·설치기·다른 도구).
            #   잠금을 하나 더 만들어도 **그 손은 그 잠금을 안 잡으므로** 막히지 않는다 —
            #   그래서 막을 수 있는 것은 「우리가 남의 변경을 덮어쓰는 것」뿐이고,
            #   그것은 잠금이 아니라 **대조**로 막는다(읽은 뒤 달라졌으면 쓰지 않는다).
            #   ⚠남는 창(정직): 대조와 `os.replace` 사이의 짧은 틈은 여전히 있다. 0 이 아니다.
            if _config_on_disk(config_path) != existing:
                sys.stderr.write(
                    f"경고: 옮기는 사이 {CONFIG_FILENAME} 이 바뀌었다 — 덮지 않는다."
                    " participant.json 도 손대지 않았다(다음 실행에서 다시 시도한다).\n")
                return cleaned
            _write_private(config_path,
                           json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError) as exc:
        sys.stderr.write(
            f"경고: 잔재 칸 {legacy} 을(를) {CONFIG_FILENAME} 으로 옮기지 못했다({exc}) — "
            "participant.json 은 손대지 않았다. 이 칸은 이번 실행에서 무시한다.\n")
        return cleaned

    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        backup = _write_new_backup(path, raw)
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
