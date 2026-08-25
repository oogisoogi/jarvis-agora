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

from agora import schema, scrub, sign
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
