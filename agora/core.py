"""코어 — 쓰기 경로 하나(설계 §4 도구 계약의 공통 뼈대).

`propose`·`say`·`advance`… 는 전부 **같은 순서**를 지나야 한다:

    ⑴ 계약(스키마) → ⑵ 스크럽 게이트 → ⑶ 서명 → ⑷ 저장층 쓰기

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
from agora.errors import AgoraError
from agora.event import render_post


def publish_event(*, store: Any, event: dict[str, Any], category: str,
                  title: str = "", is_genesis: bool = False) -> dict[str, Any]:
    """한 이벤트를 운반층에 올린다 — 위 4단계를 그 순서대로."""
    schema.validate(event)                     # ⑴ 계약
    report = scrub.enforce(event)              # ⑵ 게이트 — 여기서 막히면 아래로 못 간다
    signed = sign.sign_event(event)            # ⑶ 서명(서명기가 게이트를 재검사한다)
    body = render_post(event, signed["signature"])
    result = store.append(thread_id=event["thread_id"], category=category,
                          title=title or event["payload"].get("title", ""),
                          body=body, is_genesis=is_genesis)   # ⑷ 쓰기
    return {"message_id": event["message_id"], "hash": signed["hash"],
            "scrub": report, **result}


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
