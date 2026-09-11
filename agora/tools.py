"""도구 11종 — 코어 함수 = MCP 도구(설계 §4 · **동결된 계약**).

★이 파일에는 **새 규칙이 없다.** 전이·권한·게이트·서명·운반·원장은 S1~S5 가 이미 만들었고,
  여기가 하는 일은 그것들을 **계약이 정한 순서와 이름으로 묶는 것**뿐이다.
  그래서 이 파일에서 조심할 것은 「무엇을 구현하는가」가 아니라 **「어디를 건너뛰지 않는가」**다.

★쓰기는 전부 `core.publish_event` 를 지난다 — 계약 → 스크럽 → 승인 → 서명 → 쓰기 → 원장.
  도구가 저장층을 **직접** 부르면 그 다섯 중 몇 개가 조용히 빠지고, 빠진 것은 아무도 못 본다.
  ⇒ 이 파일이 저장층 쓰기 함수를 **직접 부르지 않는다**는 것 자체가 계약이고, 시험이 그것을
    소스로 잰다. (⚠그 함수 이름을 여기 적지 않는다 — 적는 순간 이 문장이 위반이 된다.
    같은 자리를 오늘만 세 번째 밟는다: 검사기·보고서에 이어 이번엔 **주석**이었다.)

★쓰기 전 **세 가지를 같은 자리에서** 본다: 상태(CAS `expected_state`) · 권한 · 사슬 머리(`prev`).
  하나라도 밖에서 받으면 「내가 본 상태」와 「지금 상태」가 갈라진 채 글이 나간다.
  세 값은 전부 **방금 계산한 reduce 결과**에서 나온다 — 호출자가 넘기지 못하게 한다.

★읽기(`threads`)는 **비용을 숨기지 않는다.** 목록에 없는 것(유형·상태·의장)은 스레드를 열어야
  알 수 있고, 그것이 곧 API 호출이다(S4-2 실측). 그래서 몇 건을 열었는지 세어 결과에 싣고,
  **필터가 그 범위 안에서만 적용됐다는 사실도 함께 싣는다** — 안 그러면 「필터 결과 0건」이
  「그런 스레드가 없다」로 읽힌다.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from agora import ack as ack_mod
from agora import brief, core, errors, protocol, reducer, roster
from agora.contract_open import (GENESIS_EXPECTED_STATE, GENESIS_PREV,
                                 READ_PAGE_BYTES, READ_PAGE_EVENTS)
from agora.errors import AgoraError
from agora.event import new_id
from agora.ledger import now_iso

DEFAULT_THREADS_LIMIT = 20


class Context:
    """도구 한 번을 돌리는 데 필요한 것 한 벌.

    ★도구마다 이것들을 따로 찾아 오면 **어떤 도구는 원장을 안 쓰고, 어떤 도구는 명부를 안 본다**.
      한 벌로 묶어 두면 빠뜨린 것이 시그니처에서 드러난다.
    """

    def __init__(self, *, store: Any, ledger: Any, spool: Any = None,
                 allowed_signers_path: str, participant_id: str,
                 revoked_path: str | None = None,
                 config: dict[str, Any] | None = None,
                 operators: frozenset[str] = frozenset(),
                 prompt: Any = None, isatty: Any = None,
                 config_dir: str | None = None) -> None:
        self.store = store
        # ★설정 폴더는 **한 번 정해지고** 여기 적힌다(M-f 라운드 2). 층마다 다시 찾지 않는다.
        self.config_dir = config_dir
        self.ledger = ledger
        self.spool = spool
        self.allowed_signers_path = allowed_signers_path
        # ★명부는 **두 파일**이다 — 누가 참가자인가(allowed_signers)와 어느 키가 죽었나(revoked).
        #   한 쪽만 들고 다니면 폐기가 **조용히 꺼진다**(검증 함수는 지원하는데 인자가 안 간다).
        self.revoked_path = revoked_path
        self.participant_id = participant_id
        self.config = config or {}
        self.operators = operators
        self.prompt = prompt
        self.isatty = isatty


# ── 상태 읽기(모든 도구의 출발점) ───────────────────────────────────────────

def _reduce(ctx: Context, thread_id: str) -> dict[str, Any]:
    from agora import scrub
    collected = reducer.collect(store=ctx.store, thread_id=thread_id,
                                allowed_signers_path=ctx.allowed_signers_path,
                                revoked_path=ctx.revoked_path,
                                # ★이 둘이 없으면 `roster_stale`·`scrub_recheck` 가
                                #   **영원히 False** 다 — 「명부·규칙이 바뀐 뒤에 온 옛 글」을
                                #   아무도 못 알아본다. 칸은 있는데 늘 비어 있는 상태였다.
                                roster_checkpoint=_roster_digest(ctx),
                                scrub_bundle=scrub.current_bundle())
    # ★예산은 **방 genesis 가 들고 있다**(계약 확장 9 · 2026-09-11). 여기서 아무것도 안 넘기는
    #   것이 맞다 — reducer 가 그 방의 숫자를 읽는다.
    #   ⛔전에는 참가자 `config.json` 에서 왔다. 그러면 **내 설정이 릴레이보다 느슨할 때**
    #     릴레이는 `budget_exceeded` 로 격리하고 나는 받아들여 **같은 원장이 두 상태로 읽혔다**
    #     (아래 `_publish` 의 「릴레이가 받기는 했지만 반영하지 않았다」가 그 자리다).
    #     출처를 방 하나로 합치면 그 틈이 **구조적으로** 닫힌다.
    reduced = reducer.apply(reducer.order(collected), operators=ctx.operators,
                            # ★★`now` 가 없으면 **만료가 아예 안 일어난다**(`is_expired_now` 가
                            #   `now` 없이는 항상 False). 마감·만료·의장 승계(S2-5)가 통째로
                            #   실사용에서 죽어 있었다 — 시험은 `now` 를 직접 넘겨 재고 있었다.
                            now=now_iso())
    reduced["collected"] = collected
    return reduced


def _require_open(reduced: dict[str, Any]) -> dict[str, Any]:
    """상태가 없으면(genesis 부재·전부 격리) 쓰기의 전제가 없다 — code 2.

    ★`reducer.apply` 는 상태를 **평탄하게** 돌려준다(`reduced` 자신이 곧 상태이고,
      `reduced["state"]` 는 상태 **이름** 문자열이다). 여기서 그것을 한 번 못박아 둔다 —
      「상태 객체」를 따로 있는 것처럼 다루면 `state["state"]` 같은 코드가 생기고,
      그때부터 두 뜻이 한 이름에 얹힌다.
    """
    if not reduced.get("state"):
        raise AgoraError(errors.PRECONDITION, "상태를 세울 수 없다 — genesis 가 없다",
                         {"thread_id": reduced.get("thread_id"),
                          "reason": reduced.get("reason")})
    return reduced


# ── 쓰기 공통 경로 ──────────────────────────────────────────────────────────

# 릴레이가 「받았지만 반영 안 했다」고 말하는 사유 중 **다시 써 볼 값어치가 있는 것**(계약 §5-2).
#   경합에서 진 것(`lost_race`)·상태가 어긋난 것(`stale_expected_state`)은 **자리를 다시 잡으면**
#   같은 글이 그대로 유효해진다. 격리(권한·예산·라운드 밖)는 자리를 바꿔도 그대로라 재시도 대상이 아니다.
RETRYABLE_RELAY_REASONS = ("lost_race", "stale_expected_state")


def _relay_rejected(out: dict[str, Any]) -> dict[str, Any] | None:
    """릴레이가 「반영 안 했다」고 말했는가 — **접수(2xx)와 반영을 가른다**(F-1 봉합 ⓑ).

    ★09-06 리허설이 이 자리에서 깨졌다: 네 건이 `valid:false` 로 격리됐는데 클라이언트는
      **rc 0** 을 냈다. 「접수됐다」와 「반영됐다」를 한 칸으로 읽으면, 글쓴이는 자기 글이
      사라진 것을 **원장을 열어 보기 전에는 모른다**(GitHub 시절 실물 #4 의 재발).
    ⚠이 값은 **참고 판정**이다(계약 §3-5: 클라이언트는 이 칸을 상태의 근거로 쓰면 안 된다).
      그래서 우리는 이것으로 **상태를 세우지 않는다** — 「다시 보라」는 신호로만 쓰고,
      자리를 다시 잡는 판단은 **우리 리듀서**가 한다. 실패로 올릴 때도 사유를 그대로 인용한다.
    """
    verdict = out.get("relay_verdict")
    if type(verdict) is not dict:
        return None
    reducer_said = verdict.get("reducer")
    reason = verdict.get("reason")
    if reducer_said in (None, "", "accepted", "valid") and not reason:
        return None
    # ★칸 이름은 **계약이 정한 것**을 쓴다: 실물 POST 응답의 verdict 는 `state_hash` 다
    #   (relay/src/index.ts). 더블만 `state_hash_at_that_point` 를 쓰고 있었고, 그래서 이 칸은
    #   **실물을 상대할 때 언제나 비어 있었다**(codex 2R · 계약 불일치). 이름이 갈리면
    #   「값이 없다」와 「상대가 안 줬다」가 구별되지 않는다.
    return {"reducer": reducer_said, "reason": reason,
            "state_hash": verdict.get("state_hash")}


def _blind_spot(reduced: dict[str, Any]) -> list[dict[str, Any]]:
    """**우리가 못 읽는 글**이 사슬 위에 있는가 — 서명자가 우리 명부에 없는 이벤트.

    ★★F-1 의 진짜 뿌리다(09-06 원장 판독 · 이 티켓에서 규명): 의장 r1 의 명부 사본이
      r2·r3 **등재 전** 것이어서, r1 의 리듀서가 두 사람의 발언을 `unsigned` 로 격리했다.
      그래서 r1 의 세계에서는 CAS 가 **정합이었다** — 자기가 못 보는 글에게 진 것이다.
      원장이 그것을 그대로 보여 준다: 같은 방 이벤트 셋의 `roster` digest 가 **셋 다 다르다**
      (`8501f9…`(r1) · `e4b640…`(r2) · `0ca385…`(r3)).
    ⇒ 그래서 「head 를 다시 읽는다」만으로는 못 고친다. **다시 읽어도 여전히 안 보인다.**
      보이지 않는 글이 있으면 **쓰지 않는다**(fail-closed) — 명부를 받아 오라고 말한다.
    ⚠`BAD`(변조 정황)는 여기 안 넣는다: 그것은 낡음이 아니라 **위조**이고, 명부를 받아 와도
      안 사라진다. 두 사건을 한 칸에 뭉치면 처방이 갈린다.
    """
    head_row: dict[str, Any] | None = None
    for item in (reduced.get("events") or []):
        if item.get("hash") == reduced.get("head"):
            head_row = item
            break
    blind: list[dict[str, Any]] = []
    for q in reduced.get("quarantined") or []:
        if q.get("reason") != reducer.SIGNATURE:
            continue
        detail = q.get("detail") or {}
        if detail.get("verdict") != "unsigned":
            continue
        # ★사유로 가른다(시각이 아니라): `revoked` 는 **한때 명부에 있던 키**이고 `no_signature` 는
        #   서명이 아예 없는 글이다. 둘 다 `sync-roster` 로 안 풀리므로 여기서 세면 쓰기가 영원히 막힌다.
        #   여기서 세는 것은 **「모르는 서명자」** 하나뿐이다 — 그것만이 「내 사본이 낡았다」의 신호다.
        if detail.get("why") in ("revoked", "no_signature"):
            continue
        # ★우리 머리보다 **뒤에 온 것**만 센다(앞의 것은 지금 쓰는 자리를 못 건드린다).
        #   ⚠비교 규칙은 운반층에 따라 다르다(agy 1R 지적 1 · 수용): 릴레이의 `event_id` 는 계약상
        #   **고정폭 단조 증가**라 문자열 비교가 곧 도착 순서다(§3-2). 그 서식이 아니면(GitHub 시절)
        #   리듀서와 **같은 정렬 규칙**(`created_at`→`node_id`)으로 떨어진다 — 여기서만 다른 규칙을
        #   쓰면 두 곳이 갈리고, 갈린 규칙은 언젠가 서로를 반박한다.
        if head_row is not None and not _arrived_after(q, head_row):
            continue
        blind.append({"node_id": q.get("node_id"), "created_at": q.get("created_at")})
    return blind


_FIXED_WIDTH_EVENT_ID = re.compile(r"^ev_[0-9]+$")


def _arrived_after(candidate: dict[str, Any], head_row: dict[str, Any]) -> bool:
    """도착 순서 비교 — 릴레이면 `event_id`(고정폭 단조), 아니면 리듀서의 정렬 규칙."""
    left, right = str(candidate.get("node_id") or ""), str(head_row.get("node_id") or "")
    if _FIXED_WIDTH_EVENT_ID.match(left) and _FIXED_WIDTH_EVENT_ID.match(right):
        return left > right
    return reducer._order_key(candidate) > reducer._order_key(head_row)


def _accepted_by_us(ctx: Context, thread_id: str, message_id: str) -> bool | None:
    """**우리 리듀서가** 그 글을 사슬에 넣었는가 — 판정의 정본은 이쪽이다(계약 §3-5).

    ★★답은 **셋**이다(codex 3R LOW · 2026-09-09): 들어왔다(True) · 안 들어왔다(False) ·
      **못 쟀다**(None). 첫 판은 못 읽은 것을 `False` 로 접었는데, 그러면 보고서의
      `accepted_by_us:false` 가 「우리도 거부했다」와 「읽지 못해 모른다」 **두 사건**을 가리킨다.
      사람은 그 줄을 보고 다툼의 크기를 판단하는데, 두 사건은 처방이 정반대다
      (전자는 그 글을 버리면 되고, 후자는 **먼저 읽을 수 있게 만들어야** 한다).
    ★「못 쟀음」을 거짓으로 채우지 않는다 — 비어 있는 칸이 채워지는 순간이 위험한 순간이다.
    """
    try:
        reduced = _reduce(ctx, thread_id)
    except AgoraError:
        return None         # 못 읽으면 **모르는 것**이다 — 모름을 거부로도 성공으로도 접지 않는다
    return any(item.get("message_id") == message_id
               for item in (reduced.get("events") or []))


def _publish(ctx: Context, *, kind: str, thread_id: str, payload: dict[str, Any],
             prev: str, expected_state: str, category: str, title: str = "",
             is_genesis: bool = False) -> dict[str, Any]:
    """계약 → 스크럽 → 승인 → 서명 → 쓰기 → 원장. **건너뛰는 길을 두지 않는다.**"""
    event = {
        "v": 1, "kind": kind, "thread_id": thread_id, "message_id": new_id(),
        "prev": prev, "expected_state": expected_state,
        "from": ctx.participant_id, "roster": _roster_digest(ctx),
        "ts": now_iso(), "payload": payload,
    }
    core.declare_scrub(event, config_dir=ctx.config_dir)   # ★서명 대상 안 — **만들 때** 채운다

    def cas() -> None:
        """쓰기 **직전**에 상태를 다시 본다(§4 code 9).

        ★`expected_state` 는 이 호출이 시작될 때 읽은 값이다. 그 뒤 스크럽·**사람 승인**을
          지나는 동안 남이 같은 자리에 글을 올렸을 수 있고, 승인은 분 단위로 걸린다.
          그래서 검사를 **쓰기 직전으로** 민다 — 앞에서 하면 창이 열린 채로 남는다.
        ★값은 한 번 더 읽어 온다(운반층 왕복 1회 추가). 그 비용이 이 검사의 값이다 —
          「아까 본 상태」로 판정하면 검사하는 시늉만 하는 것이다.
        ★★그리고 **못 읽는 글이 있으면 아예 쓰지 않는다**(F-1 봉합 · `_blind_spot`).
          CAS 는 「내가 본 상태」를 지키는 장치라, **내가 못 보는 것**에는 눈이 멀어 있다.
        """
        fresh = _reduce(ctx, thread_id)
        blind = _blind_spot(fresh)
        if blind:
            raise AgoraError(errors.PRECONDITION,
                             "이 방에 우리 명부로 못 읽는 글이 있다 — 먼저 명부를 받아라",
                             {"reason": "roster_stale_unknown_signers",
                              "unreadable": len(blind), "events": blind[:5],
                              "how": "agora sync-roster"})
        reducer.require_state(fresh, expected_state)

    # ★재시도는 **한 번**이다(브리프 ⓐ). 두 번째도 지면 그것은 경합이 아니라 **자리를 잘못 본 것**이라
    #   사람이 봐야 한다 — 자동 반복은 남의 원장에 같은 글을 쌓는다.
    attempts = 1 if is_genesis else 2
    for attempt in range(attempts):
        if attempt:
            # 자리를 다시 잡는다: **우리 리듀서로** head·expected 를 새로 뽑고, 그 자리로 다시 서명한다.
            #   ⚠릴레이가 준 사유는 「다시 보라」는 신호일 뿐, 새 자리는 우리가 계산한다(계약 §3-5).
            fresh = _reduce(ctx, thread_id)
            state = _require_open(fresh)
            if (state["head"], state["state_hash"]) == (prev, expected_state):
                raise AgoraError(errors.STATE_CONFLICT,
                                 "릴레이는 밀렸다는데 우리 사슬은 그대로다 — 보이지 않는 글이 있다",
                                 {"reason": "rejected_but_head_unchanged",
                                  "relay": rejected, "expected_state": expected_state,
                                  "how": "agora sync-roster 로 명부를 받고 read 로 다시 봐라"})
            # 라운드가 움직였으면 **같은 글이 아니다.** 조용히 다른 라운드에 붙이지 않는다.
            # ⚠kind 마다 라운드를 적는 칸이 다르다(agy 1R 지적 2 · 수용): 발언은 `round`,
            #   전진은 `from_round` 다. 한 칸만 보면 `advance` 가 이 방어선을 그냥 지나가고,
            #   낡은 `from_round` 로 재전송돼 **원장에 무의미한 실패 한 줄**을 남긴다.
            was_round = payload.get("round")
            if was_round is None:
                was_round = payload.get("from_round")
            if was_round is not None and state.get("round") != was_round:
                raise AgoraError(errors.STATE_CONFLICT,
                                 "그 사이 라운드가 바뀌었다 — read 후 다시 써라",
                                 {"reason": "round_moved", "relay": rejected,
                                  "was": was_round, "now": state.get("round")})
            prev, expected_state = state["head"], state["state_hash"]
            event = {**event, "message_id": new_id(), "prev": prev,
                     "expected_state": expected_state, "ts": now_iso()}
            core.declare_scrub(event, config_dir=ctx.config_dir)
        try:
            out = core.publish_event(store=ctx.store, event=event, category=category,
                                     title=title, is_genesis=is_genesis,
                                     config=ctx.config, prompt=ctx.prompt,
                                     isatty=ctx.isatty, ledger=ctx.ledger,
                                     config_dir=ctx.config_dir,
                                     # genesis 에는 견줄 앞 상태가 없다(K-4 · expected_state = "")
                                     before_write=None if is_genesis else cas)
        except AgoraError as e:
            if e.code != errors.UNKNOWN_COMMIT:
                raise
            out = _settle_unknown(ctx, event, e)
        rejected = _relay_rejected(out)
        if not rejected:
            break
        if rejected.get("reason") not in RETRYABLE_RELAY_REASONS or attempt == attempts - 1:
            # ★**접수됐다고 성공이 아니다.** 사유를 그대로 얹어 실패로 올린다.
            # ★★**우리 사슬이 받았다는 것은 면제 사유가 아니다**(codex 2R HIGH · 2026-09-09 ·
            #   구판의 `_accepted_by_us` 우회를 여기서 걷어낸다). 구판은 agy 1R 의 「거짓 실패」
            #   지적을 받아 「우리 리듀서가 받았으면 성공」으로 접었는데, 그 분기가 **로컬 설정이
            #   릴레이보다 느슨한 모든 경우**에 상시로 열려 있었다: 로컬 `posts_per_round` 가 크면
            #   릴레이는 `budget_exceeded` 로 격리하고 우리는 받아들여 **rc 0** 이 난다.
            #   ⇒ 「원장에 있음 ≠ 적용됨」은 어느 쪽 리듀서를 정본으로 삼든 참이다. 상대가 반영을
            #     거부한 글은 **그 상대의 방에서는 없는 글**이고, 대화는 그 방에서 일어난다.
            # ★agy 1R 의 걱정(거짓 실패)은 **없애는 대신 드러내서** 답한다: 우리 사슬이 받았는지를
            #   `accepted_by_us` 로 실어 올린다. 사람은 「릴레이가 거부 · 우리는 수용」이라는
            #   **다툼 그 자체**를 보고 판단한다 — 조용히 성공으로 접는 것과는 다른 일이다.
            code = (errors.STATE_CONFLICT
                    if rejected.get("reason") in RETRYABLE_RELAY_REASONS
                    else errors.GATE_REJECT)
            raise AgoraError(code, "릴레이가 받기는 했지만 반영하지 않았다",
                             {"reason": rejected.get("reason"),
                              "reducer": rejected.get("reducer"),
                              "message_id": event["message_id"],
                              "attempts": attempt + 1,
                              # ★3값 그대로 싣는다(True·False·None=못 쟀음). genesis 는 견줄
                              #   앞 사슬이 없어 이 물음이 성립하지 않으므로 None 이다.
                              "accepted_by_us": None if is_genesis else _accepted_by_us(
                                  ctx, thread_id, event["message_id"]),
                              "how": "read 로 다시 보고 그 자리에서 다시 써라"})
    out["usage"] = usage_of(event)
    return out


def _settle_unknown(ctx: Context, event: dict[str, Any],
                    err: AgoraError) -> dict[str, Any]:
    """code 8(저장 성공 불명)의 **뒤처리** — 재조회로 판정한다(설계 §4).

    ★★코어는 이것을 **일부러 안 한다**: 「보냈는데 응답이 안 왔다」를 성공이나 실패로
      단정하면 ⑴안 올라간 글을 올라갔다고 믿거나 ⑵이미 올라간 글을 다시 올린다.
      그래서 코어는 그대로 올리고, **판정은 여기서** 한다 — 근거는 우리 기록이 아니라
      **운반층에 그 message_id 가 실재하는가** 하나뿐이다(기록으로 판정하면 순환이다).
    ★★이 자리가 **비어 있었다**(2026-08-26 배선 전수조사): code 8 을 던지는 곳은 셋인데
      재조회로 판정하는 곳이 **0** 이었다. `settle_unknown` 은 구현돼 있었고 시험도 있었다 —
      아무도 부르지 않았을 뿐이다. 「구현했다」와 「배선됐다」는 다른 말이다.
    ★**확정된 부재는 「불명」이 아니다.** 재조회로 안 올라간 것이 확인되면 code 7(저장층
      실패·재시도 가능)로 **좁힌다** — 8 인 채로 두면 호출자는 영원히 「모르겠다」를 받는다.
    """
    # ★R4 ④-b(codex 라운드 3) — 재조회 **자체가** 실패하면(결박 I/O 가 계속 막힘 등) 그 안쪽 오류가 그대로
    #   올라가 원래 code 8 의 복구 재료(number·node_id·url·recover)가 사라졌다. 절단 검색이면 파일을 고친 뒤에도
    #   어느 번호를 rebind 할지 응답에서 알 수 없다. ⇒ 원래 8 의 detail 을 지키고 재조회 실패를 **중첩**해 다시 8 로.
    try:
        settled = core.settle_unknown(store=ctx.store, ledger=ctx.ledger, event=event,
                                      event_hash=(err.detail or {}).get("event_hash") or "")
    except AgoraError as se:
        # ★R5-②(codex 라운드 4) — 복구 재료(number·node_id)가 있는 8 은 원격 생성이 **이미 1회** 일어난 것이다.
        #   retryable:true 로 두면 문자 그대로 따르는 호출자가 propose 를 재실행해 게시물을 또 만든다(재현 4회).
        #   ⇒ false + retry_action:"rebind". 재료가 없는 8(진짜 불명)은 코드별 기본(true · 재조회가 재시도)을 둔다.
        base = dict(err.detail or {})
        # ★R6 ⓐ(codex 라운드 5) — 「재료가 있는가」는 값의 참·거짓이 아니라 **키 존재 ∧ 비None** 이다. truthiness 로
        #   재면 number=0 이 「재료 없음」이 돼 retryable true 로 새고 원 작업이 재실행된다(재현 4회). 실물 번호는 1부터지만
        #   03 문면은 「키가 있으면」이라 코드 기준을 그렇게 잰다.
        known = base.get("number") is not None and base.get("node_id") is not None
        if known:
            base["retry_action"] = "rebind"
        raise AgoraError(errors.UNKNOWN_COMMIT, "재조회도 실패했다 — 원래 부분 커밋 정보를 보존한다",
                         {**base,
                          "settle_error": {"code": se.code, "message": se.message,
                                           "detail": se.detail}},
                         retryable=False if known else None) from None
    if settled["verdict"] == core.REJECTED:
        # ★★**원장에 있음 ≠ 적용됨**(codex 2R CRITICAL · 2026-09-09). 재조회에서 릴레이가
        #   `valid:false` 라고 답했다 — 글은 그쪽 원장에 남았지만 **반영되지 않았다.**
        #   ⇒ 성공으로 접지 않고, 정상 응답을 받았을 때와 **같은 문**으로 보낸다:
        #     `relay_verdict` 를 실어 올려 `_publish` 의 거부 처리(재시도 가능한 사유면
        #     자리를 다시 잡고, 아니면 비영 종료)가 그대로 돌게 한다.
        #   ★같은 문으로 보내는 것이 핵심이다 — 여기서 따로 판정하면 두 경로가 갈라지고,
        #     갈라진 경로 중 하나는 언젠가 다시 rc 0 을 낸다(이 결함이 정확히 그것이었다).
        return {"message_id": event["message_id"],
                "hash": (err.detail or {}).get("event_hash"),
                "settled": core.REJECTED, "ledger_row": None,
                "node_id": None, "url": None,
                # ★분류를 **릴레이가 말한 대로** 적는다(master 승인 2026-09-09). 여기 "stale" 을
                #   못박아 두면 릴레이가 격리한 글이 「밀렸다」로 보고된다 — 재시도 여부는 `reason` 이
                #   지므로 판정은 옳지만, 사람이 읽는 근거 줄이 사실과 다르다.
                "relay_verdict": {"accepted_to_ledger": True,
                                  "reducer": settled.get("reducer") or "unknown",
                                  "reason": settled.get("reason"), "state_hash": None}}
    if settled["verdict"] != core.COMMITTED:
        raise AgoraError(errors.STORE, "저장되지 않았다 — 재조회로 확인했다",
                         {"settled": settled["verdict"],
                          "message_id": event["message_id"]}) from None
    # ★★**「운반층에 있다」는 아직 「적용됐다」가 아니다**(codex 3R CRITICAL 1b · 2026-09-09).
    #   릴레이 상대라면 위에서 그쪽 판정까지 봤지만, `audit_events` 가 없는 운반층(GitHub·목)에는
    #   그 판정 자체가 없어 **존재만으로** committed 가 된다. 그런데 「원장에 있음 ≠ 적용됨」은
    #   운반층에 딸린 명제가 아니다 — **우리 리듀서가** 그 글을 사슬에 넣었는지가 정본이다.
    #   ⇒ 폴백이 이 티켓의 원 결함을 다시 여는 것을 여기서 막는다.
    #   ⚠못 읽으면(None) 성공으로도 실패로도 접지 않는다: 원래의 code 8(불명)로 되돌린다.
    mine = _accepted_by_us(ctx, event["thread_id"], event["message_id"])
    if mine is False:
        raise AgoraError(errors.STATE_CONFLICT,
                         "운반층에는 있는데 우리 사슬에는 없다 — 남이 그 자리를 차지했다",
                         {"reason": "not_in_our_chain",
                          "message_id": event["message_id"],
                          "settled": core.COMMITTED,
                          "how": "read 로 다시 보고 그 자리에서 다시 써라"}) from None
    if mine is None:
        raise AgoraError(errors.UNKNOWN_COMMIT,
                         "저장은 확인했지만 우리 사슬을 읽지 못했다 — 판정을 미룬다",
                         {**dict(err.detail or {}),
                          "settled": core.COMMITTED,
                          "reason": "chain_unreadable_after_settle"}) from None
    # 올라가 있었다. 다만 **응답을 못 받았으므로 node_id·url 은 없다** — 없는 것을 지어내지 않는다.
    return {"message_id": event["message_id"],
            "hash": (err.detail or {}).get("event_hash"),
            "settled": core.COMMITTED, "ledger_row": settled["ledger_row"],
            "node_id": None, "url": None}


def usage_of(event: dict[str, Any]) -> dict[str, Any]:
    """이 호출이 **쓴 양**(NFR-7 · M-4 — reducer 가 「도구 경계에서 붙는다」고 남긴 칸).

    ★**토큰은 세지 않는다 — 셀 수 없기 때문이다.** 이 경계에는 모델도 토크나이저도 없다.
      그래서 `tokens` 를 0 이나 추정치로 채우지 않고 **null 로 두고 사유를 적는다.**
      추정치를 넣으면 그 숫자가 곧 비용표로 인용되고, 아무도 그것이 추정인 줄 모른다
      (이 저장소가 이미 아는 형태다 — 「미측정 칸은 미측정으로 남긴다」).
    ★대신 **확실히 아는 것**을 준다: 본문 글자 수와 canonical 바이트 수.
    """
    from agora.event import canonical_bytes
    body = event["payload"].get("body")
    return {"body_chars": len(body) if type(body) is str else None,
            "event_bytes": len(canonical_bytes(event)),
            "tokens": None, "tokens_why": "미측정 — 이 경계에서는 셀 수 없다"}


def _roster_digest(ctx: Context) -> str:
    """이 이벤트가 **어느 명부를 보고** 쓰였는지(§2-1 · H-13 체크포인트).

    ★파일 내용의 해시다. 「그때 명부가 무엇이었나」를 나중에 못 대면,
      폐기된 키로 서명된 옛 글을 어떻게 볼지 정할 근거가 사라진다.
    """
    import hashlib
    try:
        with open(ctx.allowed_signers_path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        raise AgoraError(errors.PRECONDITION, "명부를 읽을 수 없다",
                         {"path_kind": "allowed_signers"}) from None


def _head_and_state(ctx: Context, thread_id: str) -> tuple[dict[str, Any], str, str]:
    """(상태, prev, expected_state) — **셋을 같은 reduce 에서** 뽑는다.

    ★호출자가 이 값들을 넘기게 두지 않는다. 넘길 수 있으면 「아까 본 상태」로 쓸 수 있고,
      그것이 CAS 가 막으려는 바로 그 상황이다.
    """
    reduced = _reduce(ctx, thread_id)
    state = _require_open(reduced)
    # ★`prev` 는 **운반층 머리**(사슬의 마지막)다 — 상태 머리가 아니다.
    #   🔴2026-09-11 사고: 여기서 상태 머리를 쓰고 있었다. `vote` 는 상태를 안 바꾸므로
    #   상태 머리가 표 앞자리에 머무는데, 그 자리는 표가 이미 차지했다 ⇒ 다음 글이 전부
    #   `lost_race` 로 죽는다(표 한 건이 방을 영구 동결 · 실측 재현 3/3).
    #   계약은 처음부터 둘을 갈라 놓았다(§5 규칙 5 · codex 5R 의 F-1 시험이 그 구분을 잰다) —
    #   갈라 놓은 것을 **부르는 쪽에서 도로 붙여 쓴 것**이 이 사고다.
    # ⚠`expected_state` 는 그대로 **상태 해시**다(CAS 의 뜻은 안 바뀐다 · 릴레이 변경 0).
    return state, reduced.get("chain_head") or state["head"], state["state_hash"]


# ── 도구 11종(설계 §4 표 순서 그대로) ───────────────────────────────────────

def threads(ctx: Context, *, type: str | None = None, status: str | None = None,
            tag: str | None = None, os: str | None = None, app: str | None = None,
            answered: bool | None = None, query: str | None = None,
            related: str | None = None, cursor: str | None = None,
            limit: int = DEFAULT_THREADS_LIMIT) -> dict[str, Any]:
    """스레드 목록. **연 만큼만 안다** — 그 사실을 결과에 적는다."""
    listed = ctx.store.list_threads(limit=limit, cursor=cursor)
    items: list[dict[str, Any]] = []
    unverifiable: list[dict[str, Any]] = []
    links_by_thread: dict[str, list[str]] = {}
    opened = 0
    for row in listed["items"]:
        page = ctx.store.fetch(number=row["number"])
        opened += 1
        thread_id = _thread_id_of(page["items"])
        if not thread_id:
            # 우리 서식이 아예 아닌 글(웹에서 손으로 연 토론 등). 스레드로 세지 않되 **센다**.
            unverifiable.append({"number": row["number"], "thread_id": None,
                                 "why": "not_our_format"})
            continue
        reduced = _reduce(ctx, thread_id)
        if not reduced.get("state"):
            # ★★**말없이 빼지 않는다**(master 지적 2026-08-26). 상태를 못 세우는 스레드는
            #   목록에서 사라지는데, 그러면 `scanned` 는 6 인데 보이는 것은 5 가 되고
            #   **그 차이를 설명하는 것이 아무 데도 없다** — 「안 보이면 없는 것과 같다」의
            #   우리 자신의 위반이다. 실물 #2 가 그랬다(구 안정키 genesis = 지금 명부로 검증 불가).
            # ★`items` 가 아니라 **따로 싣는 이유**: `items` 는 필터(type·status…)를 지나는데
            #   고아는 유형도 상태도 없어서 **필터가 도로 지워 버린다.** 그러면 같은 사고가
            #   「필터를 걸었을 때만」 다시 난다. 필터가 안 닿는 칸에 둔다.
            unverifiable.append({"number": row["number"], "thread_id": thread_id,
                                 "why": reduced.get("reason") or "no_state"})
            continue
        genesis = _genesis_payload(reduced)
        rnd = reduced["round"]
        item = {"thread_id": thread_id, "number": row["number"],
                "type": reduced["type"], "title": genesis.get("title", ""),
                "state": reduced["state"], "round": rnd,
                "chair": reduced["chair"],
                "deadline": (genesis.get("deadlines") or {}).get(
                    f"r{rnd}" if rnd is not None else "r0"),
                "updated": row.get("updated_at")}
        links_by_thread[thread_id] = [link["thread_id"]
                                      for link in reducer.links_of(reduced)]
        if _matches(item, genesis, reduced, type=type, status=status, tag=tag,
                    os=os, app=app, answered=answered, query=query):
            items.append(item)
    if related:
        items = _narrow_related(items, links_by_thread, related)
    return {"items": items, "next_cursor": listed.get("next_cursor"),
            # ★열어 본 수와 「필터가 이 범위 안에서만 돌았다」를 함께 준다.
            #   이 두 칸이 없으면 「결과 0건」이 「그런 스레드 없음」으로 읽힌다.
            "scanned": opened,
            "filtered_within_scanned": True,
            # ★열었지만 **상태를 못 세운** 것들. 필터를 안 지난다(위 주석 참조).
            "unverifiable": unverifiable}


def _thread_id_of(items: list[dict[str, Any]]) -> str | None:
    """genesis 본문에서 thread_id 를 얻는다(목록에는 없다 — S5-2 주석 참조)."""
    from agora.event import parse_post
    for row in items:
        try:
            parsed = parse_post(row.get("body") or "")
        except Exception:      # noqa: BLE001 — 우리 서식이 아니면 그냥 아니다
            continue
        tid = parsed["event"].get("thread_id")
        if tid:
            return tid
    return None


def _genesis_payload(reduced: dict[str, Any]) -> dict[str, Any]:
    chain = reduced.get("collected", {}).get("valid") or []
    for entry in chain:
        if entry["kind"] == "genesis":
            return entry["event"]["payload"]
    return {}


def _matches(item: dict[str, Any], genesis: dict[str, Any], reduced: dict[str, Any],
             **f: Any) -> bool:
    """필터. **본문을 해석하지 않는다** — 구조 필드와 제목만 본다(§5 「글은 데이터」)."""
    if f.get("type") and item["type"] != f["type"]:
        return False
    if f.get("status") and item["state"] != f["status"]:
        return False
    if f.get("answered") is not None:
        solved = reduced.get("solved_by") is not None
        if solved != f["answered"]:
            return False
    env = genesis.get("envelope") or {}
    if f.get("os") and (env.get("env") or {}).get("os") != f["os"]:
        return False
    if f.get("app") and (env.get("env") or {}).get("app") != f["app"]:
        return False
    if f.get("tag") and f["tag"] not in (genesis.get("tags") or []):
        return False
    if f.get("query") and f["query"] not in item["title"]:
        return False
    return True


def _narrow_related(items: list[dict[str, Any]], links: dict[str, list[str]],
                    related: str) -> list[dict[str, Any]]:
    """관계는 **양방향**이다(§2-1b · AC ①).

    ★A 가 B 를 refs 로 걸면 관계는 **둘 사이에** 생긴 것이지 A 에만 생긴 것이 아니다.
      「가리키는 쪽」만 돌려주면 **B 쪽에서 물었을 때 아무것도 안 나온다** — 답한 사람은
      자기 글이 어디에 인용됐는지 영영 모른다. 그래서 역방향도 함께 본다.
    ★역방향은 **스캔한 범위 안에서만** 알 수 있다(남의 스레드가 나를 가리키는지는 그 스레드를
      열어야 안다). 그 한계는 `threads` 가 이미 결과에 적는다(`scanned`·`filtered_within_scanned`).
    """
    forward = set(links.get(related) or [])          # related → 그가 가리키는 것들
    out = []
    for item in items:
        tid = item["thread_id"]
        if tid == related:
            continue                                  # 자기 자신은 관계가 아니다
        if related in (links.get(tid) or []) or tid in forward:
            out.append(item)
    return out


def read(ctx: Context, *, thread_id: str, since_event: str | None = None,
         audit: bool = False, cursor: str | None = None) -> dict[str, Any]:
    """스레드 하나를 읽는다. 격리 목록은 `audit` 에서만 드러난다(§3-1)."""
    reduced = _reduce(ctx, thread_id)
    # ★`state` 칸에 reduce 결과를 통째로 싣지 않는다 — 그 안에는 이벤트 전문·격리 목록이
    #   다시 들어 있어 같은 것을 두 번 주게 되고, 「상태」라는 이름이 무엇을 가리키는지 흐려진다.
    # ★2단(절차)까지 지난 결과를 넘긴다 — 1단만 보면 **거부된 글이 「유효」로 보인다**(S7-2 실측).
    view = reducer.read_view(reduced["collected"],
                             state=reducer.procedure_snapshot(reduced), audit=audit,
                             accepted=reduced.get("events"),
                             quarantined=reduced.get("quarantined"),
                             stale=reduced.get("stale"))
    if since_event:
        ids = [e["message_id"] for e in view["events"]]
        if since_event not in ids:
            raise AgoraError(errors.ARGUMENT, "그 message_id 가 이 스레드에 없다",
                             {"since_event": since_event})
        view["events"] = view["events"][ids.index(since_event) + 1:]
    view["state_hash"] = reduced.get("state_hash")   # ★쓰기의 CAS 인자가 여기서 나온다
    # ★관계를 **링크로** 싣는다 — `why` 와 함께(AC ②). 왜 인용했는지가 빠지면
    #   읽는 쪽은 그 링크를 따라가 보고서야 관계를 짐작해야 한다.
    view["refs"] = reducer.links_of(reduced)
    # ★★본문은 **남이 쓴 데이터**다(NFR-2 · 설계 §D1). 경계 표식으로 감싸서 내보낸다.
    #   ⚠이것은 **보조** 방어다 — 진짜 방어는 수신 대리인의 도구가 0 이라는 것이다(H-3).
    #     표식은 설득이고, 설득은 방어가 아니다. 그래도 표식이 **없으면** 읽는 쪽에는
    #     「이건 지시가 아니다」라고 말해 주는 것이 하나도 없다.
    for entry in view["events"]:
        body = entry.get("body")
        if type(body) is not str:
            continue                     # 본문 없는 이벤트(advance·close 등)는 감쌀 것이 없다
        wrapped = brief.wrap_untrusted(body)
        entry["body"] = wrapped["text"]
        entry["untrusted"] = {"label": wrapped["label"], "marker": wrapped["marker"],
                              "note": wrapped["note"]}
    # ★후보가 여럿이었다는 **사실**은 감추지 않는다(H1·R-13). audit 에서만 드러난다 —
    #   평시 화면을 시끄럽게 하지 않되, 볼 사람이 볼 때는 반드시 보이게.
    if audit:
        seen = getattr(ctx.store, "locate_candidates", None) or {}
        if thread_id in seen:
            view["transport_candidates"] = list(seen[thread_id])
        # ★검색이 **끝까지 봤는가**도 싣는다(라운드 2). 후보 목록만 보이면 「그 뒤가 잘렸다」는
        #   사실이 화면에 없고, 잘린 목록은 완전한 목록과 똑같이 생겼다.
        searched = getattr(ctx.store, "locate_search", None) or {}
        if thread_id in searched:
            view["transport_search"] = dict(searched[thread_id])
    # ★★M-d(codex 2026-08-26) — `cursor` 인자는 있는데 **아무도 안 쓰고** `next_cursor` 는
    #   늘 None 이었다. 즉 응답에 **상한이 없었다**: 스레드가 길어지면 한 호출이 얼마든 커지고,
    #   부르는 쪽은 나눠 받을 방법이 없다(인자가 있으니 **있는 줄 안다** — 더 나쁘다).
    # ★⚠자르는 것은 **화면뿐**이다. 상태·격리 판정은 위에서 이미 **전건으로** 끝났다.
    #   자른 뒤의 상태는 상태가 아니다 — 그 실수를 하면 페이지마다 다른 사실이 생긴다.
    # ★★라운드 2(codex 재검증) — 라운드 1 은 `events` 만 잘랐다. `quarantined`·`stale`·`refs` 는
    #   전건 복사라 **최종 응답의 바이트 상한이 안 잠겼다**(무효 글 700건 재현: events 1 · quarantined 700 ·
    #   119KB). 상한은 「이벤트 수」가 아니라 **응답 전체**에 있어야 한다.
    #   ⇒ 커서 하나가 네 목록을 차례로 가리킨다(`<목록>:<키>` · 맨몸 message_id = events 호환).
    # ★★R3-①(codex 라운드 2 재검증 · master#238398) — 라운드 2 는 예산을 **목록 행의 합**으로만 쟀다.
    #   첫 페이지 목록 합 65,434B ≤ 65,536 인데 실제 JSON 은 66,575B · CLI(indent 2)는 89,303B 였다.
    #   상한은 「내가 센 것」이 아니라 **전송되는 것**에 걸려야 한다 ⇒ 후보 페이지를 실제 포장(CLI·MCP)으로
    #   직렬화해 재고, 넘치면 채움 예산을 비율로 줄여 다시 채운다(수렴 · 한 건은 반드시 싣는다).
    # ★★R3-⑤(codex 라운드 2) — 커서는 **어느 모드·어느 상태에서** 만든 것인지를 자기 안에 싣는다.
    #   그전에는 audit 로 받은 커서를 평시 읽기에 넣어도, 그 사이 스레드가 바뀌어도 조용히 통과했다 —
    #   격리 목록 커서가 평시엔 「없는 목록」이라 빈 결과가 되고, refs 는 위치라 앞이 바뀌면 중복·누락이
    #   소리 없이 났다. 모드·상태가 다르면 **code 10** 이다(부르는 쪽이 비교하지 않아도 잡힌다).
    stamp = _cursor_stamp(audit=audit, state_hash=view.get("state_hash"))
    section, key = _parse_cursor(cursor, audit=audit, state_hash=view.get("state_hash"))
    base = {k: v for k, v in view.items() if k not in READ_SECTIONS}   # 고정 메타(state·refs 밖)
    lists = {k: list(view[k]) for k in READ_SECTIONS if k in view}
    budget = READ_PAGE_BYTES
    candidate: dict[str, Any] = {}
    for _ in range(READ_FIT_ROUNDS):
        page = _fill_page(lists, section, key, budget)
        if page.get("next_cursor"):
            page["next_cursor"] += stamp          # 표식은 포장 크기에 들어간다 — 재기 전에 붙인다
        candidate = {**base, **page}
        wire = _wire_size(candidate)
        if wire <= READ_PAGE_BYTES or _page_items(page) <= 1:
            break
        budget = max(1, int(budget * READ_PAGE_BYTES / wire * 0.98))
    return candidate


READ_FIT_ROUNDS = 8          # 비율 축소 재채움 상한 — 매 회 2% 여유를 두므로 보통 1~2회에 끝난다


def _wire_size(view: dict[str, Any]) -> int:
    """이 응답이 **실제로 나가는 크기** — 우리 포장 두 가지(CLI 들여쓰기 · MCP 텍스트 포장) 중 큰 쪽.

    ★목록 행의 바이트 합은 응답 크기가 아니다. 키·구분자·들여쓰기·JSON-RPC 안의 문자열 이스케이프가
      전부 전송에 실린다. 재려면 **포장한 채로** 재야 한다.
    """
    compact = json.dumps(view, ensure_ascii=False, sort_keys=True)
    pretty = json.dumps(view, ensure_ascii=False, sort_keys=True, indent=2)
    rpc = json.dumps({"jsonrpc": "2.0", "id": 0, "result": {
        "content": [{"type": "text", "text": compact}]}}, ensure_ascii=False, sort_keys=True)
    return max(len(pretty.encode("utf-8")), len(rpc.encode("utf-8")))


def _page_items(page: dict[str, Any]) -> int:
    return sum(len(page[k]) for k in READ_SECTIONS if k in page)


def _fill_page(lists: dict[str, list[dict[str, Any]]], section: str,
               key: str | None, budget: int) -> dict[str, Any]:
    """커서 위치부터 예산(목록 행 바이트) 안에서 네 목록을 차례로 채운 한 페이지."""
    page: dict[str, Any] = {}
    if section == "events":
        page["events"], tail = _page(lists.get("events") or [], key, budget)
        page["next_cursor"] = f"events:{tail}" if tail else None
        budget -= _bytes_of(page["events"])
    else:
        page["events"] = []            # 앞 페이지에서 이미 건넸다
        page["next_cursor"] = None
    _page_sections(page, lists, section, key, budget)
    return page


# 응답 안의 목록 네 개 — 커서가 이 **차례로** 가리킨다. 이름이 커서에 그대로 실린다.
READ_SECTIONS = ("events", "quarantined", "stale", "refs")


def _hash_prefix(state_hash: str | None) -> str:
    # ★R4(master 결정 2026-09-02) — 표식은 128비트(32 hex). 12자(48비트)는 우발 오인은 극소해도 충돌 저항을
    #   주장하기엔 짧았다(codex 라운드 3 논쟁점). 커서는 서버가 발급하고 그대로 되돌리는 불투명 문자열이라 비용은 길이뿐.
    return (state_hash or "")[:32]


def _cursor_stamp(*, audit: bool, state_hash: str | None) -> str:
    """커서 꼬리 `@<audit 0/1>:<state_hash 앞 32자>` — 커서가 태어난 모드·상태."""
    return f"@{1 if audit else 0}:{_hash_prefix(state_hash)}"


def _parse_cursor(cursor: str | None, *, audit: bool = False,
                  state_hash: str | None = None) -> tuple[str, str | None]:
    """`<목록>:<키>@<모드>:<상태>` → (목록, 키). 맨몸 값은 라운드 1 형식(= events 의 message_id)이다.

    ★빈 목록·빈 키·표식 없는 목록형·모드 불일치·상태 변화 = 전부 **code 10**. 조용히 첫 페이지로
      되감는 길은 없다 — 되감으면 부르는 쪽은 같은 페이지를 받으며 진행한다고 믿는다.
    """
    if not cursor:
        return "events", None
    if "@" not in cursor:
        head, sep, _key = cursor.partition(":")
        if sep and head in READ_SECTIONS:
            raise AgoraError(errors.ARGUMENT,
                             "커서에 모드·상태 표식이 없다 — 응답의 next_cursor 를 그대로 써라",
                             {"cursor": cursor})
        return "events", cursor            # 맨몸 = 라운드 1 형식 · events 전용
    body, _at, stamp = cursor.rpartition("@")
    mode, _colon, seen = stamp.partition(":")
    if mode != ("1" if audit else "0"):
        raise AgoraError(errors.ARGUMENT, "커서의 audit 모드가 이 호출과 다르다",
                         {"cursor": cursor, "audit": audit})
    if seen != _hash_prefix(state_hash):
        raise AgoraError(errors.ARGUMENT, "커서를 만든 뒤 스레드 상태가 바뀌었다 — 다시 읽어라",
                         {"cursor": cursor, "state_hash": _hash_prefix(state_hash)})
    head, sep, key = body.partition(":")
    if not sep or head not in READ_SECTIONS or not key:
        raise AgoraError(errors.ARGUMENT, "커서 문법이 틀리다 — <목록>:<키>@<모드>:<상태>",
                         {"cursor": cursor})
    return head, key


def _bytes_of(rows: list[dict[str, Any]]) -> int:
    return sum(len(json.dumps(r, ensure_ascii=False).encode("utf-8")) for r in rows)


def _section_key(section: str, entry: dict[str, Any], index: int) -> str:
    """이어 읽기 키 — events 는 message_id · 격리·stale 은 node_id · refs 는 **내용 다이제스트**.

    ★R3-⑤ — refs 는 위치를 키로 썼다(링크엔 고유 id 가 없다). 앞에 링크가 끼면 같은 위치가 다른
      링크를 가리켜 이어 읽기가 중복·누락을 낸다. 위치 대신 링크의 내용(role·출처 message_id·
      대상 thread_id·대상 message_id)을 sha256 으로 접어 앞 16자를 쓴다 — 자리가 바뀌어도 같은 링크는
      같은 키다.
    ★R4 ⑤-a(codex 라운드 3) — 같은 글이 같은 링크를 두 번 걸면(스키마·reducer 는 중복을 허용) 다이제스트가 겹쳐
      이어 읽기가 늘 첫 중복 다음으로 돌아갔다 — 「한 번 더 실린다」가 아니라 **같은 커서가 무한히 재발급**돼
      뒤 링크가 영구 누락됐다(R3 주석의 주장이 틀렸다). 그래서 목록 안의 키는 `_section_keys` 가
      다이제스트에 **발생 순번**을 붙여 만든다 — 상태 표식이 삽입 변화를 이미 거부하므로 순번은 위치 문제를 되살리지 않는다.
    """
    if section == "refs":
        raw = "|".join(str(entry.get(k) or "")
                       for k in ("role", "from_message_id", "thread_id", "message_id"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return str(entry.get("node_id") or entry.get("message_id") or index)


def _section_keys(section: str, rows: list[dict[str, Any]]) -> list[str]:
    """목록 전체의 이어 읽기 키 — 같은 다이제스트가 거듭 나오면 `<digest>.<발생 순번>` 으로 갈라 유일하게 한다."""
    keys: list[str] = []
    seen: dict[str, int] = {}
    for i, row in enumerate(rows):
        base = _section_key(section, row, i)
        if section == "refs":
            n = seen.get(base, 0)
            seen[base] = n + 1
            base = f"{base}.{n}"
        keys.append(base)
    return keys


def _page_sections(view: dict[str, Any], lists: dict[str, list[dict[str, Any]]],
                   section: str, key: str | None, budget: int) -> None:
    """events 뒤의 목록들을 **같은 바이트 예산** 안에서 이어 준다.

    ★못 실은 목록은 **빈 목록으로 두지 않고 이름을 댄다**(`pending`). 빈 목록은 「없다」와
      「이번 페이지엔 못 실었다」가 같아 보이고, 격리 목록에서 그 둘은 정반대 사실이다.
    ★한 페이지에 적어도 한 건은 싣는다 — 한 건이 예산보다 커도 진행은 해야 한다(무한 같은 페이지 금지).
    """
    order = list(READ_SECTIONS[1:])
    present = [s for s in order if s in lists]
    # ★R3-⑤ — 이 응답에 **없는** 목록을 가리키는 커서는 10 이다. audit 을 끈 채 `quarantined:` 커서를
    #   주면 검증할 목록 자체가 없어 빈 결과가 됐다 — 「없다」와 「못 본다」가 같은 화면이었다.
    if section != "events" and section not in present:
        raise AgoraError(errors.ARGUMENT, "그 목록은 이 응답에 없다 — audit 모드를 확인하라",
                         {"cursor": f"{section}:{key}", "sections": ["events", *present]})
    # 앞 목록(events)이 더 남았으면 뒤 목록은 이 페이지에 안 실린다 — 차례가 있어야 커서가 뜻을 갖는다.
    if view.get("next_cursor"):
        for s in present:
            view[s] = []
        view["pending"] = present
        return
    pending: list[str] = []
    cut = False
    for s in present:
        rows = list(lists[s])
        if cut or (section != "events" and order.index(s) < order.index(section)):
            view[s] = []               # 뒤(예산 소진) 또는 앞(이미 건넸다) — 둘 다 이 페이지엔 없다
            if cut:
                pending.append(s)
            continue
        start = 0
        keys = _section_keys(s, rows)
        if section == s:
            if key not in keys:
                raise AgoraError(errors.ARGUMENT, "그 cursor 가 이 스레드에 없다",
                                 {"cursor": f"{s}:{key}"})
            start = keys.index(key) + 1
        out: list[dict[str, Any]] = []
        for i in range(start, len(rows)):
            size = len(json.dumps(rows[i], ensure_ascii=False).encode("utf-8"))
            if out and budget - size < 0:
                view["next_cursor"] = f"{s}:{keys[i - 1]}"
                cut = True
                break
            out.append(rows[i])
            budget -= size
        view[s] = out
    if pending:
        view["pending"] = pending


def _page(events: list[dict[str, Any]], cursor: str | None,
          budget: int = READ_PAGE_BYTES) -> tuple[list[dict[str, Any]], str | None]:
    """이어 읽기 — `cursor` 다음부터, 건수·바이트 상한까지.

    ★커서는 **마지막으로 건넨 `message_id`** 다. 불투명한 토큰을 쓰지 않는 이유는
      사람이 그 값을 보고 「어디까지 봤는지」 말할 수 있어야 하기 때문이다(원장·보고에 그대로 실린다).
    ★모르는 커서는 **조용히 처음부터**가 아니라 인자 오류다 — 조용히 되감으면
      부르는 쪽은 같은 페이지를 영원히 받으면서 진행하고 있다고 믿는다.
    """
    start = 0
    if cursor:
        ids = [e.get("message_id") for e in events]
        if cursor not in ids:
            raise AgoraError(errors.ARGUMENT, "그 cursor 가 이 스레드에 없다",
                             {"cursor": cursor})
        start = ids.index(cursor) + 1
    out: list[dict[str, Any]] = []
    used = 0
    for entry in events[start:]:
        size = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
        if out and (len(out) >= READ_PAGE_EVENTS or used + size > budget):
            return out, out[-1].get("message_id")
        out.append(entry)
        used += size
    return out, None


def propose(ctx: Context, *, type: str, title: str, body: str,
            envelope: dict[str, Any] | None = None,
            deadlines: dict[str, Any] | None = None,
            parent: dict[str, Any] | None = None,
            budget: dict[str, int] | None = None) -> dict[str, Any]:
    """새 스레드. thread_id 는 **미리 만든다**(H-6 · genesis 안에 들어가야 한다).

    ★`budget` 은 **이 방이 평생 들고 다닐 예산**이다(계약 확장 9). 안 주면 칸이 아예 안 생기고
      계약 기본값으로 돈다 — 「안 적었다」와 「기본값을 적었다」가 원장에서 구별된다.
    """
    thread_id = new_id()
    payload: dict[str, Any] = {"type": type, "title": title, "body": body}
    if envelope is not None:
        payload["envelope"] = envelope
    if deadlines is not None:
        payload["deadlines"] = deadlines
    if parent is not None:
        payload["parent"] = parent
    if budget is not None:
        payload["budget"] = dict(budget)
    out = _publish(ctx, kind="genesis", thread_id=thread_id, payload=payload,
                   prev=GENESIS_PREV, expected_state=GENESIS_EXPECTED_STATE,
                   category=type, title=title, is_genesis=True)
    return {"thread_id": thread_id, "number": out.get("number"),
            "url": out.get("url"), "message_id": out["message_id"],
            "usage": out["usage"]}


# ── 박람회 여정 3종(06 증보 §4 · master 결정 2026-09-05 「계약 확장 4」) ────────
# ★셋 다 **새 규칙이 없다.** 여정의 어휘(방·로비·참가)를 손에 쥐여 줄 뿐이고, 하는 일은
#   기존 도구를 부르는 것이다 — 새 발행 경로·새 목록을 만들면 두 곳이 갈라지고,
#   갈라진 날 **한쪽만 고쳐진다**(이 저장소가 이미 아는 병 · F-07 「한 사건에 이름 셋」).
ROOM_KINDS = ("debate", "problem")
JOINED_FILENAME = "joined.json"


def enter(ctx: Context, *, topic: str, kind: str, body: str = "",
          envelope: dict[str, Any] | None = None,
          deadlines: dict[str, Any] | None = None,
          budget: dict[str, int] | None = None) -> dict[str, Any]:
    """방을 연다(J1) — genesis 이벤트 1건 · **의장은 자기 자신**이 된다.

    ★`propose` 를 부른다. 여기서 `_publish` 를 직접 부르면 계약→스크럽→승인→서명→쓰기→원장
      다섯 중 몇이 조용히 빠질 수 있다 — 새 문을 내지 않는 것이 이 함수의 계약이다.
    ★본문을 안 주면 **주제 문장이 본문**이 된다(방을 여는 손이 한 줄로 끝나야 하므로).
      지어내는 것이 아니라 같은 문장을 두 자리에 쓰는 것이고, 그 사실을 여기 적어 둔다.
    """
    if kind not in ROOM_KINDS:
        raise AgoraError(errors.ARGUMENT, "방은 debate 나 problem 이다",
                         {"kind": kind, "allowed": list(ROOM_KINDS)})
    out = propose(ctx, type=kind, title=topic, body=body or topic,
                  envelope=envelope, deadlines=deadlines, budget=budget)
    record = _remember_room(ctx, out["thread_id"], role="chair")
    return {"room_id": out["thread_id"], "thread_id": out["thread_id"],
            "kind": kind, "topic": topic, "chair": ctx.participant_id,
            "message_id": out["message_id"], "url": out.get("url"),
            "usage": out["usage"], "joined": record}


def browse(ctx: Context, *, kind: str | None = None, cursor: str | None = None,
           limit: int = DEFAULT_THREADS_LIMIT) -> dict[str, Any]:
    """로비 — **열린 방** 목록(J2).

    ★`threads` 를 부른다. 목록 로직을 새로 짜면 필터가 두 곳이 되고, 그중 하나만 고쳐지는 날이 온다.
    ★「열린」의 뜻을 **여기 한 줄로 못박는다**: `closed` 가 아닌 것. `resolved`·`expired` 는
      **들어 있다** — 권고안이 나왔거나 마감이 지난 방도 아직 닫히지 않았고, 로비에서 사라지면
      「없는 방」과 구별되지 않는다. 대신 각 행이 자기 `state` 를 들고 간다.
    ★`threads` 의 정직 칸(`scanned`·`unverifiable`)을 **그대로 들고 나온다** — 「결과 0건」이
      「그런 방이 없다」로 읽히지 않게 하는 것이 그 칸들의 존재 이유다.
    """
    listed = threads(ctx, type=kind, cursor=cursor, limit=limit)
    rooms = []
    closed = 0
    for item in listed["items"]:
        if item["state"] == "closed":
            closed += 1
            continue
        rooms.append({"room_id": item["thread_id"], "title": item["title"],
                      "kind": item["type"], "state": item["state"],
                      "round": item["round"], "chair": item["chair"],
                      "deadline": item["deadline"], "updated": item["updated"]})
    return {"rooms": rooms, "closed_excluded": closed,
            "next_cursor": listed.get("next_cursor"),
            "scanned": listed["scanned"],
            "filtered_within_scanned": listed["filtered_within_scanned"],
            "unverifiable": listed["unverifiable"]}


def join(ctx: Context, *, room_id: str) -> dict[str, Any]:
    """방에 참가한다(J2) — **로컬 동작이다**(master 결정 2026-09-05 `[master#6657207e]`).

    ★**새 이벤트 kind 를 만들지 않는다.** kind 9종은 동결이고 PROTOCOL v1 의미 변경은
      발주자 게이트다. 「참가」를 이벤트로 만들면 상태기계에 전이가 하나 생기고, 그것이 곧 규약 변경이다.
    ★⚠**`say` 의 전제 조건이 아니다.** 참가하지 않아도 발언은 된다(명부에 있으면).
      이 함수는 **확인이지 관문이 아니다** — 관문으로 만들면 기존 상태기계 의미가 바뀐다.
      그래서 결과에 `is_gate: False` 를 실어 보낸다(읽는 쪽이 관문으로 오해하지 않게).
    """
    reduced = _require_open(_reduce(ctx, room_id))
    if reduced["state"] == "closed":
        raise AgoraError(errors.PRECONDITION, "닫힌 방에는 참가할 수 없다",
                         {"room_id": room_id, "state": reduced["state"],
                          "reason": reduced.get("close_reason")})
    genesis = _genesis_payload(reduced)
    known = ctx.participant_id in roster.principals(path=ctx.allowed_signers_path)
    record = _remember_room(ctx, room_id, role="participant")
    return {"room_id": room_id, "title": genesis.get("title", ""),
            "kind": reduced["type"], "state": reduced["state"],
            "round": reduced["round"], "chair": reduced["chair"],
            "joined": record, "is_gate": False,
            # ★「지금 발언할 수 있나」와 「참가했나」는 다른 사실이다. 명부에 없으면 글은
            #   나가더라도 남들의 검증에서 격리된다 — 그 사실을 참가 시점에 알려 준다.
            "in_roster": known,
            "why": None if known else "명부에 이 참가자 id 가 없다 — 발언이 격리될 수 있다"}


def _remember_room(ctx: Context, room_id: str, *, role: str) -> dict[str, Any]:
    """참가 기록 — 설정 폴더의 `joined.json`. **원장이 아니라 메모다.**

    ★이 파일은 판정에 쓰이지 않는다(쓰이면 그 순간 관문이 된다). 「내가 어느 방에 들어갔더라」를
      다음 세션이 기억하는 자리일 뿐이고, 없어져도 프로토콜은 그대로다.
    ★쓰기는 **임시 파일 → `os.replace`** 다. 중간에 죽어 반쪽 JSON 이 남으면 다음 실행이
      그 파일을 못 읽고, 메모 하나 때문에 참가가 막힌다.
    """
    import json as _json
    import os as _os
    if not ctx.config_dir:
        return {"recorded": False, "why": "설정 폴더를 모른다"}
    path = _os.path.join(ctx.config_dir, JOINED_FILENAME)
    doc: dict[str, Any] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = _json.load(fh)
        if type(loaded) is dict:
            doc = loaded
    except (OSError, ValueError):
        doc = {}                     # 못 읽으면 메모가 없는 것이다 — 참가를 막지 않는다
    entry = {"role": role, "at": now_iso()}
    doc[room_id] = entry
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        _json.dump(doc, fh, ensure_ascii=False, sort_keys=True, indent=2)
    _os.replace(tmp, path)
    return {"recorded": True, **entry}


def say(ctx: Context, *, thread_id: str, body: str, round: int | None = None,
        counter: list[dict[str, Any]] | None = None,
        refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """발언. 라운드를 **안 주면 지금 라운드**다 — 손으로 적게 두면 어긋난 라운드가 나간다.

    ★예산은 **두 겹**이다(§5). 여기가 로컬 겹 — 넘치는 글을 **보내기 전에** code 3 으로 막는다.
      진짜 판정은 reducer 가 한다(그쪽은 `budget_exceeded` 로 격리한다 · 표식이 서로 다르다).
      로컬 겹이 없으면 사람이 쓴 글이 **올라간 뒤에** 사라지고, 그 사람은 왜 사라졌는지 모른다.
    """
    state, prev, expected = _head_and_state(ctx, thread_id)
    protocol.precheck(body=body,
                      used=(state.get("usage") or {}).get(
                          reducer.usage_slot(state, ctx.participant_id))
                      or {"posts": 0, "chars": 0},
                      budget=state.get("budget") or protocol.default_budget())
    payload: dict[str, Any] = {"round": state["round"] or 0 if round is None else round,
                               "body": body}
    if counter is not None:
        payload["counter"] = counter
    if refs is not None:
        payload["refs"] = refs
    out = _publish(ctx, kind="post", thread_id=thread_id, payload=payload,
                   prev=prev, expected_state=expected, category=state["type"])
    return {"message_id": out["message_id"], "url": out.get("url"),
            "usage": out["usage"]}


def advance(ctx: Context, *, thread_id: str, to_round: int) -> dict[str, Any]:
    """라운드 전진 — **의장만**(code 5) · 상태가 어긋나면 code 9."""
    state, prev, expected = _head_and_state(ctx, thread_id)
    reducer.require_chair(state, ctx.participant_id)
    out = _publish(ctx, kind="advance", thread_id=thread_id,
                   payload={"from_round": state["round"], "to_round": to_round},
                   prev=prev, expected_state=expected, category=state["type"])
    return {"ok": True, "message_id": out["message_id"], "usage": out["usage"]}


def resolve(ctx: Context, *, thread_id: str, summary: str,
            dissent: list[dict[str, Any]],
            recommended_actions: list[dict[str, Any]]) -> dict[str, Any]:
    """수렴 — 의장만. 권고에 집행 금지 표식이 없으면 스키마가 막는다(NFR-8 · code 3)."""
    state, prev, expected = _head_and_state(ctx, thread_id)
    reducer.require_chair(state, ctx.participant_id)
    if state.get("state") != "r3":
        # ★**로컬 겹**(예산 검사와 같은 구조 · §5): 진짜 판정은 리듀서가 하지만, 여기서 먼저 막는다.
        #   ⚠없으면 어떻게 되는지 오늘 실물에서 봤다(2026-09-08 05:17): 하네스가 r2 에서 권고안을
        #   냈고 **글은 나갔다.** 릴레이가 `bad_transition` 으로 격리해 줘서 알았을 뿐, 상대가
        #   그 칸을 안 돌려줬으면 **우리 리듀서가 격리한 글을 성공으로 보고**했을 것이다.
        #   ⇒ 남의 원장에 무효인 줄을 남기지 않는 것은 **보내기 전에** 하는 일이다.
        raise AgoraError(errors.GATE_REJECT,
                         "권고안은 r3 에서만 낼 수 있다 — 먼저 라운드를 전진시켜라",
                         {"reason": "bad_transition", "now": state.get("state"),
                          "want": "r3", "how": "agora advance to_round=3"})
    out = _publish(ctx, kind="resolution", thread_id=thread_id,
                   payload={"summary": summary, "dissent": dissent,
                            "recommended_actions": recommended_actions},
                   prev=prev, expected_state=expected, category=state["type"])
    return {"ok": True, "message_id": out["message_id"], "usage": out["usage"]}


def mark_solved(ctx: Context, *, thread_id: str, post_message_id: str) -> dict[str, Any]:
    """해결 표시 — **요청자만**(§8 FR-5 · code 5). 그리고 **화면에 투영**한다."""
    state, prev, expected = _head_and_state(ctx, thread_id)
    reducer.require_requester(state, ctx.participant_id)
    out = _publish(ctx, kind="answer_selected", thread_id=thread_id,
                   payload={"post_message_id": post_message_id},
                   prev=prev, expected_state=expected, category=state["type"])
    # ★답으로 고른 글의 **운반층 node_id** 를 찾아 넘긴다 — 없으면 화면에 답 표시가 안 된다.
    #   우리는 `message_id` 로 말하고 운반층은 `node_id` 로 말한다(그 둘을 잇는 자리가 여기다).
    verdict = _accepted(ctx, thread_id, out["message_id"])
    if not verdict["accepted"]:
        return {"ok": False, "message_id": out["message_id"], "usage": out["usage"],
                "why": verdict["why"], "state": verdict["state"],
                "projection": {"sent": False, "verified": False, "why": "not_accepted"}}
    projection = _project(ctx, thread_id=thread_id, state="solved",
                          answer_node_id=_node_id_of(ctx, thread_id, post_message_id))
    return {"ok": True, "message_id": out["message_id"], "usage": out["usage"],
            "projection": projection}


def close(ctx: Context, *, thread_id: str, reason: str) -> dict[str, Any]:
    """종결. 사유는 계약 목록 안에서만(스키마가 막는다). 그리고 **화면에 투영**한다."""
    state, prev, expected = _head_and_state(ctx, thread_id)
    out = _publish(ctx, kind="close", thread_id=thread_id, payload={"reason": reason},
                   prev=prev, expected_state=expected, category=state["type"])
    # ★올린 것과 **받아들여진 것**은 다르다 — 거부됐으면 화면을 건드리지 않는다.
    verdict = _accepted(ctx, thread_id, out["message_id"])
    if not verdict["accepted"]:
        return {"ok": False, "message_id": out["message_id"], "usage": out["usage"],
                "why": verdict["why"], "state": verdict["state"],
                "projection": {"sent": False, "verified": False, "why": "not_accepted"}}
    projection = _project(ctx, thread_id=thread_id, state="closed", close_reason=reason)
    return {"ok": True, "message_id": out["message_id"], "usage": out["usage"],
            "projection": projection}


def _accepted(ctx: Context, thread_id: str, message_id: str) -> dict[str, Any]:
    """방금 올린 이벤트를 **절차가 받아들였는가** — 올린 것과 반영된 것은 다르다.

    ★★**이 자리가 비어 있었다**(2026-08-25 FR-1 knowhow 실물 왕복에서 드러났다):
      `close` 는 이벤트를 올린 뒤 **무조건** 화면을 닫았다. 그런데 그 이벤트는 절차에서
      거부될 수 있다(knowhow 는 `solved` 로 못 닫는다 — 사유가 제한돼 있다).
      결과: **원장은 open 인데 GitHub 화면은 closed** 였다. 관전하는 사람은 끝난 줄 안다.
    ★S7-2 에서 고친 것의 **거울상**이다. 그때는 「원장 closed · 화면 열림」이었고 이번은 반대다.
      한 번은 투영을 **안 불러서**, 이번은 투영을 **조건 없이 불러서** — 같은 병의 두 얼굴이고,
      뿌리는 하나다: **투영이 프로토콜 결과에 매여 있지 않았다.**
    """
    reduced = _reduce(ctx, thread_id)
    accepted = any(e.get("message_id") == message_id for e in reduced.get("events") or [])
    why = None
    if not accepted:
        for q in reduced.get("quarantined") or []:
            why = q.get("reason")
    return {"accepted": accepted, "state": reduced.get("state"), "why": why,
            "solved_by": reduced.get("solved_by")}


def _node_id_of(ctx: Context, thread_id: str, message_id: str) -> str | None:
    """message_id → 운반층 node_id. 못 찾으면 None(투영이 답 표시를 건너뛴다)."""
    for entry in _reduce(ctx, thread_id)["collected"]["valid"]:
        if entry["message_id"] == message_id:
            return entry.get("node_id")
    return None


def _project(ctx: Context, *, thread_id: str, state: str,
             answer_node_id: str | None = None,
             close_reason: str | None = None) -> dict[str, Any]:
    """reducer 상태를 **화면에 반영만** 한다(§D1) — 그리고 **반영됐는지 재조회로 확인**한다.

    ★**이 자리가 비어 있었다**(S7-2 실물 대조에서 드러났다): `project` 는 S4-4 에서 구현됐는데
      **아무도 부르지 않았다.** 그래서 우리 원장·reducer 는 `closed` 인데 **GitHub 화면은 열린 채**였고,
      관전하는 사람은 끝난 대화를 진행 중으로 본다. 「구현했다」와 「배선됐다」는 다른 말이다
      (`reconcile` 에 이어 두 번째 같은 형태 · 그쪽은 미배선이라고 **적어 두기라도 했다**).

    ★**투영 실패는 예외로 올리지 않는다**(§D1 · S4-4 가 정한 것). 화면이 못 따라온 것과
      상태가 틀린 것은 다른 사건이고, 예외로 올리면 호출자가 그 둘을 뭉친다.
    ★**그리고 「했다」고 적지 않는다** — 보낸 것과 반영된 것은 다르다. 재조회해서
      **실제로 그렇게 보이는지** 확인하고, 확인 못 하면 `verified: False` 와 사유를 남긴다.
    ⛔원장에는 **적지 않는다.** 원장은 「무엇을 보냈나」의 사슬이고 투영은 화면이다 —
      섞으면 「화면이 안 따라왔으니 보낸 적 없다」는 잘못된 읽기가 생긴다.
    """
    try:
        kwargs: dict[str, Any] = {"thread_id": thread_id, "state": state,
                                  "answer_node_id": answer_node_id}
        if close_reason is not None and "close_reason" in _project_params(ctx.store):
            kwargs["close_reason"] = close_reason
        sent = ctx.store.project(**kwargs)
    except Exception as e:      # noqa: BLE001 — 투영 실패는 프로토콜 실패가 아니다
        return {"sent": False, "verified": False, "why": type(e).__name__}
    verified, why = _verify_projection(ctx, thread_id=thread_id, state=state)
    return {"sent": True, "result": sent, "verified": verified, "why": why}


def _project_params(store: Any) -> frozenset[str]:
    """그 저장층의 `project` 가 받는 칸 — **계약보다 넓은 칸은 있으면 쓰고 없으면 안 쓴다.**

    ★`close_reason` 은 GitHub 구현에만 있다(우리 종결 사유를 GitHub 어휘로 좁히는 자리).
      계약(`store_base`)에는 없으므로, **있는지 보고 넘긴다** — 없는 저장층에 넘기면 터진다.
    """
    import inspect
    try:
        return frozenset(inspect.signature(store.project).parameters)
    except (TypeError, ValueError):
        return frozenset()


def _verify_projection(ctx: Context, *, thread_id: str,
                       state: str) -> tuple[bool, str | None]:
    """운반층에 **실제로 그렇게 보이는지** 되묻는다. 못 물으면 「못 물었다」고 답한다."""
    check = getattr(ctx.store, "thread_status", None)
    if check is None:
        return False, "store_cannot_report_status"
    try:
        status = check(thread_id=thread_id)
    except Exception as e:      # noqa: BLE001
        return False, type(e).__name__
    if state == "closed":
        return bool(status.get("closed")), None if status.get("closed") else "still_open"
    if state == "solved":
        # ★여기도 **되묻는다.** 처음엔 무조건 True 를 돌려줬는데, 그러면 답 표시가 안 됐어도
        #   「반영됐다」고 적힌다 — 이 함수가 막으려던 바로 그 거짓이다.
        return bool(status.get("answered")), None if status.get("answered") else "not_answered"
    return False, "unknown_state"


def vote(ctx: Context, *, thread_id: str, target: str, value: int) -> dict[str, Any]:
    """투표(0/1). 값의 뜻은 reducer 가 정한다 — 여기서는 계약만 지킨다."""
    state, prev, expected = _head_and_state(ctx, thread_id)
    out = _publish(ctx, kind="vote", thread_id=thread_id,
                   payload={"target": target, "value": value},
                   prev=prev, expected_state=expected, category=state["type"])
    return {"ok": True, "message_id": out["message_id"], "usage": out["usage"]}


# ── 운영 동작(CLI 전용 · 도구 표 밖) ────────────────────────────────────────
# ★**도구 11종은 §4 에서 동결이다**(master 결정 2026-08-26 (b)안). 아래 둘은 도구가 아니라
#   **절차 개입**이다 — 참가자의 발언이 아니라 「의장이 죽었으니 갈아 끼운다」·「이 대화를
#   중단한다」이다. 그래서 MCP 표면에 올리지 않는다: 대리인 세션 손에 「의장을 갈아치워라」를
#   쥐어 주지 않는다(`mcp-serve` 와 같은 자리).
# ⚠**정직한 대가**: 의장이 죽은 스레드를 **에이전트 스스로는 못 살린다.** 운영자(사람·CLI)의
#   개입이 반드시 필요하다 — 이것은 결함이 아니라 **의도한 경계**다(master 명시).


def _require_operator(ctx: Context, what: str) -> None:
    """운영자 명부(K-3) 검사 — **보내기 전에** 막는다(code 5).

    ★reducer 도 같은 것을 본다(그쪽이 진짜 판정이다). 두 겹인 이유는 예산과 같다:
      로컬 겹이 없으면 권한 없는 사람의 글이 **올라간 뒤에** 사라지고, 그 사람은 왜인지 모른다.
      표식이 서로 다르다 — 여기는 code 5(안 나감) · reducer 는 `permission` 격리(나갔다 사라짐).
    ★명부가 **비어 있으면 아무도 못 한다.** 그것이 「명부를 안 실었다」와 같은 모양이라
      이번 세션에 명부 배선을 먼저 고쳤다(B-3) — 이 문이 뜻을 가지려면 그게 먼저였다.
    """
    if ctx.participant_id not in ctx.operators:
        raise AgoraError(errors.PERMISSION, "운영자만 할 수 있다",
                         {"action": what, "from": ctx.participant_id,
                          "operators": len(ctx.operators)})


def delegate_chair(ctx: Context, *, thread_id: str, new_chair: str) -> dict[str, Any]:
    """의장 승계 — **운영자가**, **만료된 동안만**(§2-2 · 설계 결정 2026-08-25).

    ★조건이 규칙의 절반이다: 조건이 없으면 운영자가 아무 때나 의장을 갈아치울 수 있고,
      그러면 의장 권한이 형해화된다. 그 조건은 reducer 가 본다 — 여기서는 명부만 본다.
    """
    _require_operator(ctx, "delegate_chair")
    state, prev, expected = _head_and_state(ctx, thread_id)
    out = _publish(ctx, kind="delegate_chair", thread_id=thread_id,
                   payload={"new_chair": new_chair},
                   prev=prev, expected_state=expected, category=state["type"])
    # ★★M-a(codex 2026-08-26) — **올린 것과 받아들여진 것은 다르다.**
    #   여기만 `_accepted` 를 안 타고 있었다(close·mark_solved·abort 는 전부 탄다).
    #   그래서 reducer 가 거부한 승계도 **`ok: True` 로 보고**됐다 — 부른 사람은 의장이
    #   바뀐 줄 알고, 새 의장은 `advance` 에서 code 5 를 맞는다. 무엇이 잘못인지 아무 데도 없다.
    #   ⚠조건이 까다로운 동작일수록 이 자리가 중요하다: 이 명령은 **만료 중에만** 유효하다.
    # ★오늘 이 병을 네 번째로 고친다(reconcile · 투영 · 예산 · 여기).
    #   같은 모양이 네 번 나왔으면 그건 실수가 아니라 **경로가 하나 빠진 것**이다.
    verdict = _accepted(ctx, thread_id, out["message_id"])
    if not verdict["accepted"]:
        return {"ok": False, "message_id": out["message_id"], "usage": out["usage"],
                "why": verdict["why"], "state": verdict["state"]}
    return {"ok": True, "message_id": out["message_id"], "usage": out["usage"],
            "state": verdict["state"]}


def abort(ctx: Context, *, thread_id: str, reason: str) -> dict[str, Any]:
    """대화 중단 — 운영자만(K-3). 상태는 `closed` · 사유는 `aborted` 로 남는다."""
    _require_operator(ctx, "abort")
    state, prev, expected = _head_and_state(ctx, thread_id)
    out = _publish(ctx, kind="abort", thread_id=thread_id, payload={"reason": reason},
                   prev=prev, expected_state=expected, category=state["type"])
    verdict = _accepted(ctx, thread_id, out["message_id"])
    if not verdict["accepted"]:
        return {"ok": False, "message_id": out["message_id"], "usage": out["usage"],
                "why": verdict["why"], "state": verdict["state"],
                "projection": {"sent": False, "verified": False, "why": "not_accepted"}}
    projection = _project(ctx, thread_id=thread_id, state="closed",
                          close_reason="aborted")
    return {"ok": True, "message_id": out["message_id"], "usage": out["usage"],
            "projection": projection}


def promote_knowhow(ctx: Context, *, parent_thread_id: str, title: str, body: str,
                    envelope: dict[str, Any]) -> dict[str, Any]:
    """problem 에서 배운 것을 knowhow 로 **승격**한다(04-tasks S6-5 AC ③).

    ★**새 도구를 만들지 않는다.** 도구 11종은 §4 에서 동결이고, 승격은 그중 `propose` 로
      할 수 있는 일이다(`parent` 를 단 genesis). 편의 함수는 두되 **도구 표에는 넣지 않는다** —
      넣는 순간 계약이 12종이 되고, 그것은 문서·MCP·대리인 브리프가 전부 갈라진다는 뜻이다.
    """
    # ⚠`parent` 링크에는 `why` 를 **넣지 않는다** — 계약이 그 칸을 `refs` 에만 허용한다
    #   (`schema._check_link(need_why=...)`). 승격의 이유는 본문에 적는다.
    return propose(ctx, type="knowhow", title=title, body=body, envelope=envelope,
                   parent={"thread_id": parent_thread_id})


def envelope_check(ctx: Context, *, envelope: Any) -> dict[str, Any]:
    """보내도 되는지 **묻는** 자리(§4). 던지지 않고 돌려준다 — 코어는 S3-3 것을 그대로 쓴다."""
    return core.envelope_check(envelope)


def ack(ctx: Context, *, message_id: str) -> dict[str, Any]:
    """수신 영수증(S5-3). 주체는 **참가 master 세션**이다(K-2)."""
    if ctx.spool is None:
        raise AgoraError(errors.PRECONDITION, "spool 없이는 영수증을 쓸 수 없다",
                         {"reason": "no_spool"})
    return ack_mod.ack(ledger=ctx.ledger, spool=ctx.spool, message_id=message_id)


def context_from_config(directory: str | None = None, *,
                        store: Any = None) -> Context:
    """설정 폴더에서 컨텍스트 한 벌을 세운다(CLI·MCP 서버의 공통 입구).

    ★조립을 **한 곳**에 둔다. 도구마다 따로 세우면 어떤 경로는 원장을 안 달고 어떤 경로는
      명부를 다른 데서 읽는다 — 그리고 그 차이는 사고가 나기 전까지 안 보인다.
    """
    import os as _os
    from agora.ledger import Ledger
    from agora.participant import config_dir, load
    from agora.spool import Spool
    # ★★M-f 라운드 2 → R3-②(master#238398 로 되돌림): 라운드 2 는 여기서 전역 환경변수를 고정했다.
    #   한 프로세스에 Context 둘이면 나중 것이 앞의 것을 덮고(codex 재현: A 의 금지 이름이 A 발행에서
    #   안 걸렸다), 상대경로는 cwd 가 다른 서명기에서 다른 폴더가 됐다. ⇒ **절대경로로 한 번 정하고
    #   Context 상태로만 들고 다닌다**: 코어에는 `names_path` 명시, 서명기에는 호출별 env(core.publish_event).
    d = _os.path.abspath(directory or config_dir())
    doc = load(d)
    cfg = load_config(d)
    if store is None:
        store = _store_from_config(cfg, directory=d)
    # ★명부 3종은 **설정 폴더의 사본**이다(ONBOARDING §파일 · 저장소가 정본).
    #   셋을 **같은 폴더에서** 집는다 — 하나만 다른 데서 읽으면 「그때의 명부」가 갈라진다.
    return Context(store=store, ledger=Ledger(d), spool=Spool(d),
                   allowed_signers_path=_os.path.join(d, "allowed_signers"),
                   revoked_path=_os.path.join(d, "revoked_keys"),
                   operators=roster.operators(path=_os.path.join(d, "operators")),
                   participant_id=doc["id"], config=cfg, config_dir=d)


# 운반층 이름 — 설정 `transport` 칸이 고를 수 있는 값의 전수(설계 TRANSPORT-RELAY §4).
TRANSPORTS = ("relay", "github")


def transport_of(cfg: dict[str, Any]) -> str:
    """이 설정이 **어느 운반층**을 뜻하는가 — 해석 순서를 한 곳에 못박는다.

    ⑴ `transport` 가 명시돼 있으면 그것이 이긴다(모르는 값은 code 2 · 아는 값 목록을 함께 준다).
    ⑵ 없고 `relay.url` 이 있으면 릴레이.
    ⑶ 없고 `repo` 가 있으면 GitHub(v0 설정 그대로 계속 돈다 — 어댑터를 지우지 않는다).
    ⑷ 둘 다 없으면 **릴레이가 기본**이므로 `relay.url` 이 빠진 것으로 보고한다.

    ★「기본값 = 릴레이」의 정확한 뜻: 주소를 모르는 채로 릴레이에 말을 걸 수는 없다.
      기본이란 ⑴문서·예시의 기본이 릴레이이고 ⑵**둘 다 있으면 릴레이가 이긴다**는 뜻이다.
      「아무것도 없으면 릴레이로 간다」가 아니다 — 그건 성립하지 않는다.
    """
    named = cfg.get("transport")
    if named is not None:
        if named not in TRANSPORTS:
            raise AgoraError(errors.PRECONDITION, "모르는 운반층이다",
                             {"transport": named, "known": list(TRANSPORTS),
                              "file": "config.json"})
        return named
    if (cfg.get("relay") or {}).get("url"):
        return "relay"
    if cfg.get("repo"):
        return "github"
    return "relay"


def _store_from_config(cfg: dict[str, Any], directory: str | None = None) -> Any:
    """설정에서 운반층을 세운다 — **어느 운반층인지는 설정에서만 온다.**

    ★S7-1 에서 드러난 공백이다: 도구·CLI·문서는 다 있었는데 **「어느 저장소에 올리는가」를
      적는 칸이 계약에 없었다.** 그래서 CLI 로 실제 도구를 부르면 저장층 생성에서
      **날 예외**가 났다(오류 계약 밖). 문서만 보고 따라간 사람은 여기서 막힌다.
    ★없으면 **무엇이 없는지 이름을 대고** code 2 로 멈춘다. 「설정이 잘못됐다」로만 말하면
      사용자는 무엇을 고쳐야 하는지 모른다.
    """
    if transport_of(cfg) == "relay":
        return _relay_store(cfg)
    return _github_store(cfg, directory)


def _relay_store(cfg: dict[str, Any]) -> Any:
    """릴레이 어댑터. 필요한 칸은 **주소 하나**다(카테고리 id 는 릴레이에 없는 개념이다)."""
    from agora.store_relay import DEFAULT_TIMEOUT_SECONDS, RelayStore
    relay = cfg.get("relay") or {}
    if not relay.get("url"):
        raise AgoraError(errors.PRECONDITION, "config.json 에 릴레이 주소가 없다",
                         {"missing": ["relay.url"], "file": "config.json",
                          "legacy": "구 설정(GitHub)은 repo.owner·repo.name 이다"})
    timeout = relay.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS
    if type(timeout) is not int:
        raise AgoraError(errors.PRECONDITION, "relay.timeout_seconds 는 정수여야 한다",
                         {"file": "config.json"})
    return RelayStore(relay["url"], timeout=timeout)


def _github_store(cfg: dict[str, Any], directory: str | None = None) -> Any:
    """v0 어댑터 — 지우지 않는다. 옛 설정을 그대로 들고 있는 참가자가 계속 돌 수 있어야 한다."""
    from agora.store_github import GitHubStore
    repo = cfg.get("repo") or {}
    missing = [k for k in ("owner", "name") if not repo.get(k)]
    categories = cfg.get("categories") or {}
    missing += [f"categories.{k}" for k in ("problem", "knowhow", "debate")
                if not categories.get(k)]
    if missing:
        raise AgoraError(errors.PRECONDITION, "config.json 에 저장소 설정이 없다",
                         {"missing": [f"repo.{m}" if m in ("owner", "name") else m
                                      for m in missing],
                          "file": "config.json"})
    # ★결박 원장(H1·R-13)은 **참가자 설정 폴더**에 둔다 — 저장소가 아니라 이 기계의 기억이다.
    #   경로를 안 넘기면 결박이 프로세스와 함께 사라지고, 매 세션이 검색을 새로 믿는다.
    import os as _os
    from agora.store_github import BINDINGS_FILENAME
    bindings = _os.path.join(directory, BINDINGS_FILENAME) if directory else None
    return GitHubStore(repo["owner"], repo["name"], categories,
                       bindings_path=bindings)


def load_config(directory: str) -> dict[str, Any]:
    """`config.json` — 승인 게이트 같은 **운영 설정**(§5 「끄는 길은 config.json 하나뿐」).

    ★참가자 파일(`participant.json`)과 **다른 파일**이다. 처음엔 참가자 파일에서 읽으려 했는데,
      그 파일은 계약된 칸만 허용하므로(`load` 가 모르는 칸을 거부한다) **설정을 넣는 순간
      파일 전체가 거부된다.** 즉 그 경로는 「항상 빈 설정」으로 조용히 돌고 있었고,
      그러면 「끈 적 없는데 켜져 있다」와 「켠 적 없는데 꺼져 있다」를 구별할 수 없다.
    ★**없으면 빈 설정이다 — 그리고 빈 설정의 기본은 승인 on 이다**(`core.approval_gate`).
      파일이 없다고 게이트가 열리면, 설정을 지우는 것이 곧 게이트를 끄는 방법이 된다.
    """
    import json as _json
    import os as _os
    path = _os.path.join(directory, "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = _json.load(fh)
    except OSError:
        return {}
    except ValueError as e:
        raise AgoraError(errors.PRECONDITION, "config.json 파싱 실패",
                         {"error": str(e)}) from None
    if type(doc) is not dict:
        raise AgoraError(errors.PRECONDITION, "config.json 은 객체여야 한다", None)
    return doc


# ── 인자 이름: 별칭과 번역 ──────────────────────────────────────────────────
# ★★**문서가 쓰는 이름과 함수가 받는 이름이 갈리면 사람은 발언을 못 한다**(2026-09-11 실측).
#   스킬 정본·OPERATOR·INVITE 가 전부 `--thread` 인데 함수 인자는 `thread_id` 라,
#   `read`·`say` 가 **TypeError → 「예상하지 못한 내부 오류」(code 2)** 로 죽었다.
#   사용자 화면에는 원인이 **한 글자도** 안 나온다(최후 방어가 타입만 싣는다 — 그것은 옳다).
#   ⇒ 두 가지를 여기서 한다: ⑴별칭을 정본 이름으로 바꾼다 ⑵모르는·빠진 인자는
#     **인자 오류(code 10)로 번역해 이름을 말해 준다.** 삼키지 않는 것이 이 표의 존재 이유다.
# ⚠별칭은 **문서가 이미 쓰고 있는 이름**만 넣는다. 새 이름을 여기서 발명하면 정본이 둘이 된다.
ARG_ALIASES: dict[str, str] = {
    "thread": "thread_id",
}

# **값까지** 계약을 지켜야 하는 칸 — 32자 소문자 hex(`event.is_id`).
# ★왜 이름 목록인가(codex 1R MEDIUM-5): 구판은 「키가 있는가」만 봤다. 그래서 빈 문자열·한글·
#   `null` 이 **필수 인자로 인정**됐고, `read` 는 없는 방을 빈 상태로 성공이라 답했다 —
#   사람은 「그 방에 글이 없다」로 읽는다. **없는 방과 빈 방은 다른 말이다.**
# ⚠`vote` 의 `target` 은 **일부러 뺐다**: 그 칸의 모양은 계약이 정하지 않고 reducer 가 정한다
#   (여기서 32-hex 를 강요하면 계약에 없는 규칙을 CLI 가 발명하는 것이 된다).
ID_ARGS = frozenset({"thread_id", "room_id", "message_id", "post_message_id", "since_event"})


def accepted_args(fn: Any) -> tuple[str, ...]:
    """그 함수가 받는 인자 이름(계약의 이름) — `ctx` 는 뺀다."""
    import inspect
    return tuple(n for n, p in inspect.signature(fn).parameters.items()
                 if n != "ctx" and p.kind in (p.KEYWORD_ONLY, p.POSITIONAL_OR_KEYWORD))


def required_args(fn: Any) -> tuple[str, ...]:
    """기본값이 없는 인자 — 빠지면 그 자리에서 멈춰야 하는 것들."""
    import inspect
    return tuple(n for n, p in inspect.signature(fn).parameters.items()
                 if n != "ctx" and p.default is p.empty
                 and p.kind in (p.KEYWORD_ONLY, p.POSITIONAL_OR_KEYWORD))


def normalize_args(command: str, accepted: tuple[str, ...], kwargs: dict[str, Any],
                   required: tuple[str, ...] = ()) -> dict[str, Any]:
    """별칭을 정본 이름으로 바꾸고, **모르는·빠진 인자를 code 10 으로 번역**한다.

    ★「모르는 이름」은 대개 **문서를 그대로 따른 사람**이 낸다. 그래서 거절할 때
      받는 이름을 **말해 준다** — 「모르는 인자: --thread → --thread_id 를 쓰십시오」.
      이름을 안 말하는 거절은 사람을 추측으로 돌려보낸다.
    """
    import difflib
    out: dict[str, Any] = {}
    for key, value in kwargs.items():
        canonical = ARG_ALIASES.get(key, key)
        if canonical != key and canonical in kwargs:
            raise AgoraError(errors.ARGUMENT, f"같은 인자를 두 이름으로 줬다: --{key} 와 --{canonical}",
                             {"command": command, "alias": key, "canonical": canonical})
        out[canonical] = value

    unknown = [k for k in out if k not in accepted]
    if unknown:
        first = unknown[0]
        near = difflib.get_close_matches(first, accepted, n=1, cutoff=0.6)
        tail = f" → --{near[0]} 를 쓰십시오" if near else ""
        raise AgoraError(errors.ARGUMENT, f"모르는 인자: --{first}{tail}",
                         {"command": command, "unknown": unknown,
                          "did_you_mean": near[0] if near else None,
                          "accepts": sorted(accepted)})

    missing = [k for k in required if k not in out]
    if missing:
        raise AgoraError(errors.ARGUMENT, f"빠진 인자: --{missing[0]}",
                         {"command": command, "missing": missing,
                          "accepts": sorted(accepted)})

    # ★**있는가**가 아니라 **무엇인가**를 본다(codex 1R MEDIUM-5). 검사 함수는 계약이 이미 가진
    #   것을 쓴다(`event.is_id`) — 여기서 규칙을 다시 적으면 두 곳이 갈라지는 날이 온다.
    # ★생략(`None`)은 **선택 칸에서만** 생략이다. 필수 칸의 `null` 은 「안 줬다」가 아니라
    #   「틀린 값을 줬다」로 다룬다 — 둘을 같은 칸에 두면 `--thread_id null` 이 조용히 통과한다.
    from agora.event import is_id
    for key in sorted(ID_ARGS & set(out)):
        value = out[key]
        if value is None and key not in required:
            continue
        if not is_id(value):
            raise AgoraError(errors.ARGUMENT,
                             f"--{key} 의 형식이 계약과 다르다(32자 소문자 hex)",
                             {"command": command, "key": key, "형식": "32자 소문자 hex",
                              "got_type": type(value).__name__,
                              "got_len": len(value) if type(value) is str else None})
    return out


def call(name: str, ctx: Context, kwargs: dict[str, Any]) -> Any:
    """이름으로 도구를 부른다(CLI·MCP 서버가 쓰는 한 줄).

    ★모르는 이름은 **여기서** 죽인다. 부르는 쪽마다 따로 검사하면 한 곳이 빠지고,
      빠진 그 경로가 계약 밖 이름을 통과시킨다.
    ★인자 이름도 **여기서** 맞춘다(별칭·모르는 이름·빠진 이름). 부르는 쪽에 두면
      CLI 로는 되고 MCP 로는 안 되는(또는 그 반대) 자리가 생긴다.
    """
    # ★이름 검사도 인자 검사와 **같은 한 곳**(`check_args`)이 한다. 구판은 여기에 같은 검사가
    #   한 벌 더 있었는데, 그것이 둘이 되자 하네스의 조준(M149)이 「어느 것을 쟀는지 모른다」로
    #   꺼졌다 — 이 저장소가 이미 아는 함정이다(같은 모양이 두 곳에 있으면 그 축이 조용히 빈다).
    # ⚠**순서가 곧 계약이다**: 검사를 인자 자리에 두면 파이썬이 `CORE_TOOLS[name]` 을 **먼저** 짓고
    #   계약 밖 이름이 `KeyError` 로 터진다(= 우리 code 10 이 아니라 「예상하지 못한 내부 오류」).
    #   codex 1R HIGH-1 이 지적한 그 함정을 봉합하다 같은 자리에서 **한 번 더** 밟았다 — 그래서 적는다.
    checked = check_args(name, kwargs)
    return CORE_TOOLS[name](ctx, **checked)


def check_args(name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """도구 하나의 인자를 **컨텍스트 없이** 검사한다 — 이름·빠짐·값(§id).

    ★왜 따로 떼는가(codex 1R HIGH-1): 부르는 쪽들이 `context_from_config()` 를 **먼저** 평가해
      왔다(파이썬은 인자를 왼쪽부터 짓는다). 그래서 설정이 없는 기계에서는 **인자 오류가
      설정 오류로 가려졌다** — CLI 는 10 대신 2, MCP 는 -32602 대신 -32603.
      첫 설치자는 오타를 고치는 대신 설정을 뒤진다.
    ⇒ 인자 검사는 **운반층을 세우기 전에** 끝난다. `call` 도 같은 함수를 쓴다(두 번 불러도 같다 —
      정본 이름으로 바뀐 것을 다시 넣어도 결과가 같은 함수다).
    """
    fn = CORE_TOOLS.get(name)
    if fn is None:
        raise AgoraError(errors.ARGUMENT, "계약에 없는 도구",
                         {"tool": name, "allowed": sorted(CORE_TOOLS)})
    return normalize_args(name, accepted_args(fn), kwargs, required_args(fn))


# ── 계약 대조표(§4 = 이 표 = CLI 등록표) ────────────────────────────────────
# ★도구 이름과 함수를 **한 곳에서** 잇는다. 세 곳(설계 표·CLI 등록표·이 모듈)이
#   따로 놀면 「CLI 엔 있는데 MCP 엔 없는」 도구가 조용히 생긴다 — 시험이 셋을 대조한다.
CORE_TOOLS: dict[str, Any] = {
    "threads": threads, "read": read, "propose": propose, "say": say,
    "advance": advance, "resolve": resolve, "mark-solved": mark_solved,
    "close": close, "vote": vote, "envelope-check": envelope_check, "ack": ack,
    # ★계약 확장 4(master 결정 2026-09-05 22:0x · `[master#6657207e]`) — 박람회 여정 3종.
    #   03 §4 의 「도구 11종」이 **14종**이 된다. 06 증보 §6 의 「무변경」은 master 문면 과실로
    #   판정됐고 06 에 정오표가 남았다. 조용히 늘리지 않고 여기 근거를 적는다.
    "enter": enter, "browse": browse, "join": join,
}
