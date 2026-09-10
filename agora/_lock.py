"""이식 잠금 — 「같은 파일에 둘이 동시에 쓰지 않는다」를 OS 세 경우로 낸다.

★왜 이 파일이 생겼나(2026-09-10 · 운영자 노트북 실기 · 0.1.2 · 윈도우):
  `import fcntl` 이 **모듈 맨 위**에 있었다. fcntl 은 POSIX 전용이라 윈도우에서는
  `ModuleNotFoundError: fcntl` 이 **임포트 시점에** 터진다 — 그러면 그 모듈을 가져오는
  명령이 **전부** 죽는다(whoami·selfcheck·sync-roster). 실측: 6단계 register 가
  등록 HTTP 는 성공시켜 놓고 그 뒤 줄에서 죽었다. ⇒ **잠금 하나 때문에 클라이언트 전체가
  한 OS 에서 서지 못했다.**

★그래서 잠금을 **한 파일로 모은다.** 세 호출부(ledger·spool·store_github)는 이제 이 모듈만
  본다. 잠금 방식이 늘거나 바뀌어도 고칠 자리가 하나다.

★세 경우를 **가른다**(뭉치면 「잠갔다」와 「못 잠갔다」가 같은 얼굴이 된다):
  · POSIX  = `fcntl.flock(fd, LOCK_EX)` — 종전과 **완전히 같은 동작**이다.
  · 윈도우 = `msvcrt.locking(fd, LK_NBLCK, 1)` + **우리 손으로 기다린다**.
             ⚠`LK_LOCK` 을 쓰면 안 된다(codex 1R [6]): 그 상수는 **한 번 부를 때마다 안에서
             1초씩 열 번**을 기다렸다가 포기한다 — 우리가 준 상한(0.2초)을 주고도 10초가
             걸릴 수 있고, 잘못된 fd 같은 **경합이 아닌 오류**까지 그만큼 늦게 올라온다.
             ⇒ 막히면 즉시 돌아오는 `LK_NBLCK` 을 쓰고, 기다림은 우리가 짧게 나눠 잰다.
             그리고 **경합 오류만 다시 건다** — 나머지 OSError 는 그 자리에서 올린다.
             영원히 매달리지는 않는다 — 상한에 닿으면 **정직하게 실패**한다. 잠그지 못한 것을
             잠근 척하는 것이 제일 나쁘다.
  · 둘 다 없음 = **경고 한 줄 + 아무것도 안 함(no-op)**. 이 경우 동시 쓰기는 막히지 않는다.
             ★조용히 통과시키지 않는 이유: 「잠갔다」와 「잠글 수단이 없었다」가 같아 보이면
             원장이 깨진 날 아무도 원인을 찾지 못한다. 못 잰 것은 못 잰 것이라 말한다.

★잠그는 대상은 **옆에 둔 잠금 파일**이다(호출부가 그렇게 연다). 데이터 파일 자체를 잠그면
  `os.replace` 가 inode 를 갈아치워 서로 다른 파일을 잠근 두 프로세스가 동시에 쓴다.
  그 규칙은 호출부(store_github._bindings_lock)의 주석이 정본이고 여기서는 바꾸지 않는다.
"""

from __future__ import annotations

import errno
import os
import sys
import time
from typing import IO, Any

# 잠금 수단 세 경우의 이름. 문자열을 여기 한 곳에만 둔다(시험이 이 이름으로 축을 잰다).
POSIX = "fcntl"
WINDOWS = "msvcrt"
NONE = "none"

# 윈도우 재시도 상한. LK_LOCK 한 번이 약 10초이므로 기본은 여섯 번쯤 다시 거는 셈이다.
# ★환경변수로 열어 둔 이유는 시험 때문이 아니라, 잠금을 오래 쥐는 작업(대용량 sync)이 있는
#   기계에서 상한이 곧 실패선이 되기 때문이다. 값이 이상하면 기본값으로 되돌린다.
WINDOWS_WAIT_ENV = "AGORA_LOCK_WAIT_SECONDS"
WINDOWS_WAIT_DEFAULT = 60.0
_WINDOWS_LOCK_BYTES = 1
# 다시 걸기 사이의 짧은 잠. 상한을 우리가 재려면 기다림도 우리 손에 있어야 한다.
_WINDOWS_RETRY_SLEEP = 0.05
# ★「지금은 못 잠근다」로 읽는 오류만 다시 건다. 나머지(잘못된 fd·권한)는 기다려도 그대로다.
#   EDEADLOCK = _locking 이 경합에서 내는 값 · EACCES = 이미 잠긴 영역.
#   ⚠**값을 호스트 errno 표에서 고르지 마라.** 이것은 윈도우 CRT `_locking` 이 내는 값이지
#     지금 이 기계의 값이 아니다. 맥에는 `EDEADLOCK` 이라는 이름 자체가 없어서(`EDEADLK` 뿐)
#     이름으로만 모으면 ⑴맥에서는 임포트가 죽고(실제로 났다) ⑵이름을 맞춰 고쳐도 **맥의 11**을
#     담게 되어 정작 윈도우의 36을 안 받는다. 그래서 이름이 있으면 그 값을, 없으면 **36**을 쓴다.
_WINDOWS_BUSY = (getattr(errno, "EDEADLOCK", 36), errno.EACCES)

_warned = False


def _load_backend() -> tuple[str, Any]:
    """무엇으로 잠글 수 있는지 **실측**한다(플랫폼 이름으로 추측하지 않는다).

    ★`os.name == "nt"` 로 가르지 않는 이유: 그것은 「어느 OS 인가」를 재는 것이지
      「이 파이썬이 그 모듈을 갖고 있는가」를 재는 것이 아니다. 우리를 다치게 한 것은
      후자다(모듈 부재). 그리고 임포트를 재 보는 것이 언제나 더 싸다.
    """
    try:
        import fcntl  # noqa: PLC0415 — 있는지 없는지를 여기서 잰다
    except ImportError:
        pass
    else:
        return POSIX, fcntl
    try:
        import msvcrt  # noqa: PLC0415
    except ImportError:
        return NONE, None
    return WINDOWS, msvcrt


_BACKEND, _MOD = _load_backend()


def backend() -> str:
    """지금 쓰는 잠금 수단의 이름. 시험과 진단이 이 값으로 축을 가른다."""
    return _BACKEND


def reload_backend() -> str:
    """잠금 수단을 다시 잰다(시험 전용 — 모듈을 가린 채 이 함수를 부른다).

    ★모듈 최상단에서 한 번만 재면 시험이 「없는 경우」를 만들 수 없다. 그렇다고 매번 재면
      호출마다 임포트를 한다 — 그래서 **평소엔 한 번, 시험은 명시적으로** 다시 재게 한다.
    """
    global _BACKEND, _MOD, _warned
    _BACKEND, _MOD = _load_backend()
    _warned = False
    return _BACKEND


def _warn_once() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    sys.stderr.write(
        "경고: 이 파이썬에는 파일 잠금 수단이 없다(fcntl·msvcrt 둘 다 없음) — "
        "동시에 두 프로세스가 쓰면 원장이 섞일 수 있다.\n")


def _windows_wait_seconds() -> float:
    raw = os.environ.get(WINDOWS_WAIT_ENV)
    if not raw:
        return WINDOWS_WAIT_DEFAULT
    try:
        value = float(raw)
    except ValueError:
        return WINDOWS_WAIT_DEFAULT
    return value if value > 0 else WINDOWS_WAIT_DEFAULT


def acquire(fh: IO[Any]) -> str:
    """독점 잠금을 건다. 돌려주는 값은 **무엇으로 잠갔는가**(세 이름 중 하나)다.

    ★POSIX 는 종전 코드와 한 글자도 다르지 않다 — 이 이식의 성공 조건은 「윈도우가 된다」가
      아니라 「맥·리눅스에서 아무것도 달라지지 않는다」이기 때문이다.
    """
    if _BACKEND == POSIX:
        _MOD.flock(fh.fileno(), _MOD.LOCK_EX)
        return POSIX
    if _BACKEND == WINDOWS:
        _windows_lock(fh)
        return WINDOWS
    _warn_once()
    return NONE


def release(fh: IO[Any]) -> str:
    """잠금을 푼다. 잠근 수단과 **같은 수단으로** 푼다."""
    if _BACKEND == POSIX:
        _MOD.flock(fh.fileno(), _MOD.LOCK_UN)
        return POSIX
    if _BACKEND == WINDOWS:
        fh.seek(0)
        _MOD.locking(fh.fileno(), _MOD.LK_UNLCK, _WINDOWS_LOCK_BYTES)
        return WINDOWS
    return NONE


def _windows_lock(fh: IO[Any]) -> None:
    """막히면 즉시 돌아오는 잠금(`LK_NBLCK`)을 **될 때까지** 다시 건다.

    ★상한에 닿으면 마지막 OSError 를 그대로 올린다. 「기다리다 지쳤다」를 성공으로 바꾸면
      두 프로세스가 같은 원장에 동시에 쓴다 — 그 사고는 잠금이 없는 것보다 나쁘다.
      (없는 것은 경고라도 나오지만, 이쪽은 잠근 줄 안다.)
    ★경합이 아닌 오류는 **한 번도 다시 걸지 않는다.** 기다려도 달라지지 않는 것을 기다리면
      진짜 원인이 상한만큼 늦게 드러난다(codex 1R [6]).
    """
    deadline = time.monotonic() + _windows_wait_seconds()
    while True:
        fh.seek(0)
        try:
            _MOD.locking(fh.fileno(), _MOD.LK_NBLCK, _WINDOWS_LOCK_BYTES)
            return
        except OSError as exc:
            if exc.errno not in _WINDOWS_BUSY:
                raise
            if time.monotonic() >= deadline:
                raise
            time.sleep(_WINDOWS_RETRY_SLEEP)
