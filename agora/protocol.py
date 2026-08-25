"""프로토콜 예산 — 말할 권리의 상한(설계 §5 · FR-10 · NFR-7).

★**두 겹이다.** 로컬 사전 검사(빠른 거절 · code 3)와 reducer 계수(진짜 판정).
  · 로컬 검사만 두면 **그 검사를 끈 클라이언트**가 그대로 통과한다 — 저장층은 비신뢰다(§D1).
  · reducer 만 두면 사람이 쓴 글이 올라간 **뒤에** 사라진다.
  둘 다 있어야 한다. 그리고 시험은 **로컬 검사를 끄고** 해야 진짜 판정을 잰다.

★상한은 **설정에서 온다.** 코드에 박아 두면 참가자마다 다른 예산을 줄 수 없고,
  값을 바꿔도 결과가 안 바뀌므로 「예산이 실제로 쓰이는지」를 시험할 방법이 사라진다.

★계수 대상은 **유효 post 만**이다(R-2). 경합에서 진 글·무효 글은 예산을 쓰지 않는다 —
  안 그러면 남이 경합을 걸어 내 예산을 태울 수 있다(남용 방어는 초대제가 맡는다).
"""

from __future__ import annotations

from typing import Any

from agora import errors
from agora.contract_open import (
    DEFAULT_BUDGET_MAX_CHARS, DEFAULT_BUDGET_POSTS_PER_ROUND,
)
from agora.errors import AgoraError

BUDGET_FIELDS = ("posts_per_round", "max_chars_per_round")


def load_budget(config: dict[str, Any] | None = None) -> dict[str, int]:
    """참가자 설정(config.json)에서 예산을 읽는다. 없는 칸만 계약 기본값으로 채운다."""
    cfg = (config or {}).get("budget") or {}
    budget = {"posts_per_round": DEFAULT_BUDGET_POSTS_PER_ROUND,
              "max_chars_per_round": DEFAULT_BUDGET_MAX_CHARS}
    for key in BUDGET_FIELDS:
        if key in cfg:
            value = cfg[key]
            if type(value) is not int or value < 0:
                raise AgoraError(errors.ARGUMENT, "예산 값이 0 이상의 정수가 아니다",
                                 {"key": key, "value": repr(value)[:40]})
            budget[key] = value
    return budget


def would_exceed(*, body: str, used: dict[str, int],
                 budget: dict[str, int]) -> dict[str, Any] | None:
    """이 발언을 더하면 상한을 넘는가 — 넘으면 그 사유를, 아니면 None."""
    if used["posts"] + 1 > budget["posts_per_round"]:
        return {"limit": "posts_per_round", "used": used["posts"],
                "max": budget["posts_per_round"]}
    if used["chars"] + len(body) > budget["max_chars_per_round"]:
        return {"limit": "max_chars_per_round", "used": used["chars"],
                "adding": len(body), "max": budget["max_chars_per_round"]}
    return None


def precheck(*, body: str, used: dict[str, int],
             budget: dict[str, int]) -> None:
    """로컬 사전 검사 — 넘으면 보내기 전에 code 3 으로 막는다.

    ★이것은 **예의**이지 **판정**이 아니다. 판정은 reducer 가 한다.
    """
    over = would_exceed(body=body, used=used, budget=budget)
    if over:
        raise AgoraError(errors.GATE_REJECT, "발언 예산 초과", over)
