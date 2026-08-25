"""이벤트 직렬화 — canonical JSON 과 해시.

서명은 **바이트에 걸린다.** 그러므로 같은 이벤트가 어느 기계·어느 편집기·어느 줄바꿈에서도
**같은 바이트**로 떨어져야 한다. 그 규칙을 여기 한 곳에 못박는다(설계 §D4·H-12).

규칙 (전부 검증 대상):
  · UTF-8 · **NFC 정규화**(키와 문자열 값 모두 — macOS 파일명·한글 입력기가 NFD 를 만든다)
  · 키 **정렬** · 구분자에 공백 없음 · **개행 없음**
  · **중복 키 거부**(파싱 시 — json 기본은 마지막 것을 조용히 채택한다)
  · 최대 64KB
  · **부동소수·NaN·Infinity 거부** — 우리 스키마에 실수가 없고, 실수는 표현이 기계마다 갈린다.
    「지금 안 쓰니 괜찮다」가 아니라 **들어올 길을 막는다**(들어오면 서명이 조용히 갈라진다).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import unicodedata
from typing import Any

from agora import errors
from agora.contract_open import ID_HEX_LEN, MAX_EVENT_BYTES
from agora.errors import AgoraError


def new_id() -> str:
    """128비트 CSPRNG 식별자(hex 32자) — thread_id·message_id 공용(설계 §2-1·H-13)."""
    return secrets.token_hex(ID_HEX_LEN // 2)


def is_id(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == ID_HEX_LEN
        and all(c in "0123456789abcdef" for c in value)
    )


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _normalize_newlines(text: str) -> str:
    """문자열 **안**의 줄바꿈을 LF 로 통일한다.

    ⚠**이것은 설계가 아직 명시하지 않은 자리라, 잠정 채택이고 조율자 확인 대상이다.**
    (H-12 는 「CRLF 처리 규칙을 명문화하라」고만 했고 어느 쪽인지는 안 정했다.)

    채택 이유: 줄바꿈은 **글쓴 사람의 플랫폼이 남긴 흔적**이지 내용이 아니다.
    통일하지 않으면 같은 본문을 Windows 에서 쓴 사람과 다른 곳에서 쓴 사람의
    **해시가 갈라지고**, 「같은 이벤트는 같은 바이트」라는 전제가 OS 경계에서 무너진다.
    golden 벡터가 증명하려는 것이 정확히 그 전제다.

    잃는 것(정직 고지): 본문에 CR 을 **데이터로** 넣고 싶은 경우를 표현할 수 없다.
    토론 본문에서 그럴 일이 없다고 보고 통일 쪽을 골랐다. 뒤집으려면 이 함수 하나만 바꾸면 된다.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _canonicalize(node: Any, path: str = "$") -> Any:
    """정규화된 파이썬 구조를 만든다. 여기서 타입을 좁게 잡는 것이 곧 서명 안정성이다."""
    if node is None or type(node) is bool:
        return node
    if type(node) is int:
        return node
    if type(node) is float:
        raise AgoraError(errors.ARGUMENT, "이벤트에 실수를 담을 수 없다", {"path": path})
    if type(node) is str:
        return _nfc(_normalize_newlines(node))
    if type(node) is list:
        return [_canonicalize(v, f"{path}[{i}]") for i, v in enumerate(node)]
    if type(node) is dict:
        out: dict[str, Any] = {}
        for k, v in node.items():
            if type(k) is not str:
                raise AgoraError(errors.ARGUMENT, "키는 문자열이어야 한다", {"path": path})
            nk = _nfc(_normalize_newlines(k))
            if nk in out:
                # NFD/NFC 로 다르게 쓴 두 키가 정규화 후 같아지는 경우도 중복이다.
                raise AgoraError(errors.ARGUMENT, "정규화 후 키 충돌",
                                 {"path": path, "key": nk})
            out[nk] = _canonicalize(v, f"{path}.{nk}")
        return out
    # ★서브클래스(예: str 을 상속한 타입)는 위 `type(x) is` 검사에서 걸러진다.
    #   isinstance 로 받으면 __str__ 을 덮어쓴 값이 서명 입력을 바꿀 수 있다.
    raise AgoraError(errors.ARGUMENT, "직렬화할 수 없는 타입",
                     {"path": path, "type": type(node).__name__})


def canonical_bytes(event: Any) -> bytes:
    """이벤트 → 서명 입력 바이트. 이 함수의 출력이 곧 서명 대상이다."""
    normalized = _canonicalize(event)
    text = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if "\n" in text or "\r" in text:
        # separators 로 개행이 생길 일은 없지만, 생기면 서명 입력이 줄 단위 도구에 잘린다.
        raise AgoraError(errors.ARGUMENT, "canonical 에 개행이 있다", None)
    raw = text.encode("utf-8")
    if len(raw) > MAX_EVENT_BYTES:
        raise AgoraError(errors.GATE_REJECT, "이벤트 크기 상한 초과",
                         {"bytes": len(raw), "limit": MAX_EVENT_BYTES})
    return raw


def event_hash(event: Any) -> str:
    return hashlib.sha256(canonical_bytes(event)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for k, v in pairs:
        nk = _nfc(_normalize_newlines(k))
        if nk in seen:
            raise AgoraError(errors.ARGUMENT, "중복 키", {"key": nk})
        seen[nk] = v
    return seen


def parse_event(text: str | bytes) -> dict[str, Any]:
    """운반층에서 온 JSON 을 읽는다. **중복 키를 조용히 삼키지 않는다.**

    json 기본 동작은 중복 키에서 마지막 값을 채택한다 — 그러면 서명 대상과
    해석 대상이 갈라지고, 그 틈으로 「서명은 맞는데 내용이 다른」 이벤트가 들어온다.
    """
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as e:
            raise AgoraError(errors.ARGUMENT, "UTF-8 이 아니다", {"error": str(e)}) from None
    if len(text.encode("utf-8")) > MAX_EVENT_BYTES:
        raise AgoraError(errors.GATE_REJECT, "이벤트 크기 상한 초과",
                         {"bytes": len(text.encode("utf-8")), "limit": MAX_EVENT_BYTES})
    try:
        obj = json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_float=_no_float)
    except AgoraError:
        raise
    except ValueError as e:
        raise AgoraError(errors.ARGUMENT, "JSON 파싱 실패", {"error": str(e)}) from None
    if type(obj) is not dict:
        raise AgoraError(errors.ARGUMENT, "이벤트는 객체여야 한다",
                         {"type": type(obj).__name__})
    return obj


def _no_float(literal: str) -> Any:
    raise AgoraError(errors.ARGUMENT, "이벤트에 실수를 담을 수 없다", {"literal": literal})
