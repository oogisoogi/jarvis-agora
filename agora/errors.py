"""오류 계약 — 종료 코드의 유일한 정의처.

설계 §4: 모든 실패는 machine-readable JSON `{code, retryable, message, detail}` 으로 나가고,
프로세스 종료 코드는 그 `code` 와 같다.

★이 파일이 코드 값의 **유일한** 정의처다. 다른 모듈은 여기서 import 한다 —
같은 숫자를 다른 파일에 다시 적으면 두 곳이 조용히 갈라진다.
"""

from __future__ import annotations

import json
from typing import Any

OK = 0                    # 성공
PRECONDITION = 2          # 전제 미비 (키·인증·설정 부재)
GATE_REJECT = 3           # 게이트 거부 (스크럽·스키마·예산·승인)
SIGNATURE = 4             # 서명/검증 실패
PERMISSION = 5            # 권한 (의장·요청자·운영자 아님)
STORE = 7                 # 저장층 오류
UNKNOWN_COMMIT = 8        # 저장 성공 불명 — 재조회 후에만 판정한다
STATE_CONFLICT = 9        # 상태 불일치 (CAS) — read 후 재시도
ARGUMENT = 10             # 인자 오류

# 실패 코드 전수. 성공(0)은 실패가 아니므로 넣지 않는다.
ALL_CODES: tuple[int, ...] = (
    PRECONDITION, GATE_REJECT, SIGNATURE, PERMISSION,
    STORE, UNKNOWN_COMMIT, STATE_CONFLICT, ARGUMENT,
)

# 재시도해도 되는 것은 저장층 축 둘뿐이다.
# 게이트 거부·권한·인자·서명은 같은 입력으로 다시 해도 같은 결과가 나온다.
RETRYABLE: frozenset[int] = frozenset({STORE, UNKNOWN_COMMIT})

NAMES: dict[int, str] = {
    PRECONDITION: "precondition",
    GATE_REJECT: "gate_reject",
    SIGNATURE: "signature",
    PERMISSION: "permission",
    STORE: "store",
    UNKNOWN_COMMIT: "unknown_commit",
    STATE_CONFLICT: "state_conflict",
    ARGUMENT: "argument",
}


class AgoraError(Exception):
    """계약대로 직렬화되는 유일한 실패 표현."""

    def __init__(self, code: int, message: str, detail: Any = None, *,
                 retryable: bool | None = None) -> None:
        if code not in ALL_CODES:
            # 계약 밖 코드로 실패를 만들려는 시도 자체가 인자 오류다.
            raise AgoraError(ARGUMENT, "계약에 없는 오류 코드", {"code": code})
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        # ★R5-②(codex 라운드 4 · master 결정 2026-09-02) — `retryable` 은 기본은 코드별이지만 **인스턴스가
        #   내릴 수 있다.** code 8 이 「재조회 후 판정」인데 원격 생성이 **이미 1회 일어난** 8(detail 에 number·node_id)을
        #   호출자가 문자 그대로 재시도하면 propose 가 매번 새 thread_id 로 새 게시물을 만든다(재현 4회 = 4 게시물).
        #   그런 8 은 false + `retry_action:"rebind"` — 원 작업 재실행이 아니라 복구 동작만 남는다.
        self.retryable_override = retryable

    @property
    def retryable(self) -> bool:
        if self.retryable_override is not None:
            return self.retryable_override
        return self.code in RETRYABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": NAMES[self.code],
            "retryable": self.retryable,
            "message": self.message,
            "detail": self.detail,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)
