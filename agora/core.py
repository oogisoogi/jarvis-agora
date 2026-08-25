"""코어 — 쓰기 경로 하나(설계 §4 도구 계약의 공통 뼈대).

`propose`·`say`·`advance`… 는 전부 **같은 순서**를 지나야 한다:

    ⑴ 계약(스키마) → ⑵ 스크럽 게이트 → ⑶ **주인 승인** → ⑷ 서명 → ⑸ 저장층 쓰기

★순서가 규칙의 절반이다. 게이트를 서명 **뒤에** 두면 「막혔지만 서명은 남은」 이벤트가 생기고,
  저장층 쓰기 **뒤에** 두면 이미 나간 글을 막는 셈이 된다.
  그래서 이 순서를 한 함수에 못박고, **차단 시 쓰기 호출이 0 인지**를 시험한다
  (code 3 이 났다는 것만으로는 「안 썼다」가 증명되지 않는다 — 쓰고 나서 났을 수도 있다).

★서명기는 이 게이트를 **다시** 검사한다(M-11 · S3-5). 여기의 통과는 발신자의 자기주장이고,
  기록에 남는 판정은 서명기의 것이다.
"""

from __future__ import annotations

from typing import Any

from agora import errors, schema, scrub, sign
from agora.contract_open import DEFAULT_HUMAN_APPROVAL, HUMAN_APPROVAL_REQUIRED
from agora.errors import AgoraError
from agora.event import render_post


def approval_gate(*, config: dict[str, Any] | None = None,
                  prompt: Any = None, isatty: Any = None) -> dict[str, Any]:
    """전송 전 주인 승인(설계 §5 H-1 · F-14). **기본은 on 이다.**

    ★기계가 못 잡는 것이 남기 때문에 있는 문이다 — 목록에 없는 실명·주소·자유문 개인정보는
      규칙으로 못 잡는다(§5 잔여 위험). 그 자리를 사람이 메운다.

    ★**띄울 수 없으면 보내지 않는다.** TTY 가 없다고 조용히 통과시키면, 승인 게이트는
      「사람이 볼 때만 작동하는 게이트」가 된다 — 무인 실행에서 정확히 무력해진다.
      그래서 code 3 으로 멈추고 사유 문자열을 못박는다(다른 code 3 과 구별돼야 한다).

    ★끄는 길은 **`config.json` 하나뿐**이다. 환경변수·명령행으로 끌 수 있으면
      「급해서 한 번만」이 생기고, 그 한 번이 기본값이 된다.
    """
    import sys as _sys
    cfg = config or {}
    if cfg.get("human_approval", DEFAULT_HUMAN_APPROVAL) is False:
        return {"required": False, "approved": True, "why": "config.json"}
    tty = (isatty or _sys.stdin.isatty)()
    if not tty:
        raise AgoraError(errors.GATE_REJECT, "승인을 받을 수 없다 — 전송하지 않는다",
                         {"reason": HUMAN_APPROVAL_REQUIRED})
    if not (prompt or (lambda: False))():
        raise AgoraError(errors.GATE_REJECT, "주인이 승인하지 않았다",
                         {"reason": "human_approval_denied"})
    return {"required": True, "approved": True, "why": "prompt"}


def publish_event(*, store: Any, event: dict[str, Any], category: str,
                  title: str = "", is_genesis: bool = False,
                  config: dict[str, Any] | None = None,
                  prompt: Any = None, isatty: Any = None) -> dict[str, Any]:
    """한 이벤트를 운반층에 올린다 — 위 5단계를 그 순서대로."""
    schema.validate(event)                     # ⑴ 계약
    report = scrub.enforce(event)              # ⑵ 게이트 — 여기서 막히면 아래로 못 간다
    approval = approval_gate(config=config, prompt=prompt, isatty=isatty)   # ⑶ 승인
    signed = sign.sign_event(event)            # ⑷ 서명(서명기가 게이트를 재검사한다)
    body = render_post(event, signed["signature"])
    result = store.append(thread_id=event["thread_id"], category=category,
                          title=title or event["payload"].get("title", ""),
                          body=body, is_genesis=is_genesis)   # ⑷ 쓰기
    return {"message_id": event["message_id"], "hash": signed["hash"],
            "scrub": report, "approval": approval, **result}


# ── 봉투(설계 §3-2 · FR-2) ──────────────────────────────────────────────────
# ★봉투는 **예의**가 아니라 **자격**이다. 재현 정보 없이 올린 질문은 답하는 쪽의 시간을
#   먼저 쓴다 — 그래서 결손은 「형식 미비」가 아니라 게이트 거부(3)다.

def envelope_template() -> dict[str, Any]:
    """빈 봉투 서식 — 사람이 채워 넣을 자리를 보여 준다.

    ★이 값이 **그대로 검사를 통과**해야 한다(S3-3 AC ③). 서식이 자기 검사를 못 지나면
      「서식대로 썼는데 거부당하는」 일이 생기고, 그러면 아무도 서식을 안 믿는다.
      그래서 서식은 문서에 따로 적지 않고 **여기 한 곳**에 두고 문서가 이것을 인용한다.
    """
    return {
        "env": {"os": "운영체제와 판본", "app": "프로그램과 판본", "version": "0.0.0"},
        "symptom": "무엇이 어떻게 잘못되는지 한 줄",
        "repro_steps": ["첫 단계", "둘째 단계", "그때 일어나는 일"],
        "log_excerpt": "관련 로그 몇 줄(개인 정보와 경로는 빼고)",
        "tried": ["이미 해 본 것"],
        "questions": ["묻고 싶은 것"],
    }


def envelope_check(envelope: Any) -> dict[str, Any]:
    """`agora.envelope_check` 코어(§4) — {ok, errors[], scrub_report}.

    ★**던지지 않고 돌려준다.** 이 도구는 「보내도 되나」를 묻는 자리이지 보내는 자리가 아니다.
      사람이 고칠 수 있게 사유마다 **빠진 칸 이름**을 함께 준다(AC ①).
    """
    errs: list[dict[str, Any]] = []
    try:
        schema._check_envelope(envelope if type(envelope) is dict else {})
    except AgoraError as e:
        errs.append({"code": e.code, "message": e.message, "detail": e.detail})
    report: dict[str, Any] | None = None
    try:
        report = scrub.check({"payload": {"envelope": envelope}})
        if report["blocked"]:
            errs.append({"code": errors.GATE_REJECT, "message": "스크럽 게이트 차단",
                         "detail": {"rules": [f["rule"] for f in report["findings"]],
                                    "where": [f["where"] for f in report["findings"]]}})
    except AgoraError as e:
        errs.append({"code": e.code, "message": e.message, "detail": e.detail})
    return {"ok": not errs, "errors": errs, "scrub_report": report}
