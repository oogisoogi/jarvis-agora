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
    BUDGET_FIELDS, DEFAULT_BUDGET_MAX_CHARS, DEFAULT_BUDGET_POSTS_PER_ROUND,
    MAX_BUDGET_MAX_CHARS, MAX_BUDGET_POSTS_PER_ROUND,
)
from agora.errors import AgoraError

BUDGET_CEILING: dict[str, int] = {"posts_per_round": MAX_BUDGET_POSTS_PER_ROUND,
                                  "max_chars_per_round": MAX_BUDGET_MAX_CHARS}


def default_budget() -> dict[str, int]:
    """계약 기본값 — **설정을 안 본다**(계약 확장 9)."""
    return {"posts_per_round": DEFAULT_BUDGET_POSTS_PER_ROUND,
            "max_chars_per_round": DEFAULT_BUDGET_MAX_CHARS}


def out_of_range(budget: dict[str, Any]) -> dict[str, Any] | None:
    """방이 들고 온 예산이 계약 범위 밖인가 — 밖이면 그 사유를, 아니면 None.

    ★이것은 **모양 검사가 아니다**(모양은 schema 가 본다). 숫자가 정수이고 음수가 아니어도
      상한을 넘으면 debate 방의 독점 방지 규칙이 조용히 사라진다 — 그래서 **정책**이고,
      정책은 리듀서가 판정한다(격리 · 계약 확장 9 · master 판정 2026-09-11).
    """
    for key, ceiling in BUDGET_CEILING.items():
        if key not in budget:
            continue
        value = budget[key]
        if type(value) is not int or value < 0 or value > ceiling:
            return {"key": key, "value": repr(value)[:40], "max": ceiling}
    return None


def budget_of(genesis_payload: dict[str, Any]) -> dict[str, int]:
    """이 방의 예산 — **genesis 가 정본**이고, 칸이 없으면 계약 기본값이다.

    ⛔참가자 `config.json` 은 더 이상 예산의 출처가 아니다(계약 확장 9). 전에는 거기서 왔고,
      그래서 내 설정이 릴레이보다 느슨하면 **같은 원장이 두 상태로 읽혔다.**
    """
    budget = default_budget()
    budget.update({k: v for k, v in (genesis_payload.get("budget") or {}).items()
                   if k in BUDGET_FIELDS})
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
