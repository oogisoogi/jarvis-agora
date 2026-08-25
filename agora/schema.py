"""이벤트 스키마 — kind 9종의 **닫힌** 정의.

★닫힌 스키마인 이유: 「모르는 칸은 무시」로 두면 언젠가 누가 그 칸에 무엇을 넣고,
  서명 대상과 해석 대상이 갈라진다. 그래서 **모르는 칸은 거부**한다.

★타입은 `type(x) is T` 로 좁게 본다. `isinstance` 로 받으면 str·int 를 상속한 값이
  통과해 직렬화·비교를 바꿔 놓을 수 있다.

코드 구분(설계 §4):
  · **10(인자 오류)** — 모양이 틀렸다(칸 없음·모르는 칸·타입 틀림·값 범위 밖).
  · **3(게이트 거부)** — 모양은 맞는데 **정책**이 막는다(예: 권고가 집행 금지 표식을 안 달았다).
"""

from __future__ import annotations

from typing import Any

from agora import errors
from agora.contract_open import (
    GENESIS_EXPECTED_STATE, GENESIS_PREV, ID_HEX_LEN, KINDS,
)
from agora.errors import AgoraError
from agora.event import is_id

THREAD_TYPES = ("problem", "knowhow", "debate")
CLOSE_REASONS = ("solved", "unresolved", "superseded", "archived", "aborted", "expired")
ROUNDS = (0, 1, 2, 3)

# 모든 이벤트가 갖는 칸(설계 §2-1). `delegate` 만 선택이다.
COMMON_REQUIRED = ("v", "kind", "thread_id", "message_id", "prev", "expected_state",
                   "from", "roster", "scrub", "ts", "payload")
COMMON_OPTIONAL = ("delegate",)


def _fail(message: str, detail: Any = None, code: int = errors.ARGUMENT) -> None:
    raise AgoraError(code, message, detail)


def _need(obj: dict[str, Any], key: str, typ: type, where: str) -> Any:
    if key not in obj:
        _fail("필수 칸 누락", {"where": where, "key": key})
    value = obj[key]
    if type(value) is not typ:
        _fail("칸 타입이 다르다",
              {"where": where, "key": key, "want": typ.__name__,
               "got": type(value).__name__})
    return value


def _closed(obj: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    extra = [k for k in obj if k not in allowed]
    if extra:
        _fail("계약에 없는 칸", {"where": where, "extra": sorted(extra)})


def _check_envelope(env: dict[str, Any]) -> None:
    _closed(env, ("env", "symptom", "repro_steps", "log_excerpt", "tried", "questions"),
            "envelope")
    e = _need(env, "env", dict, "envelope")
    _closed(e, ("os", "app", "version"), "envelope.env")
    _need(e, "os", str, "envelope.env")
    _need(e, "app", str, "envelope.env")
    _need(env, "symptom", str, "envelope")
    steps = _need(env, "repro_steps", list, "envelope")
    if not steps:
        _fail("재현 단계가 비었다", {"where": "envelope.repro_steps"})
    for i, st in enumerate(steps):
        if type(st) is not str:
            _fail("재현 단계는 문자열이어야 한다", {"where": f"envelope.repro_steps[{i}]"})


def _check_genesis(p: dict[str, Any]) -> None:
    _closed(p, ("type", "title", "body", "envelope", "deadlines", "chair", "parent"),
            "genesis")
    t = _need(p, "type", str, "genesis")
    if t not in THREAD_TYPES:
        _fail("스레드 유형이 계약 밖", {"type": t, "allowed": list(THREAD_TYPES)})
    _need(p, "title", str, "genesis")
    _need(p, "body", str, "genesis")
    if t in ("problem", "knowhow"):
        if "envelope" not in p:
            # 봉투 없는 problem/knowhow 는 **게이트 거부**다(모양이 아니라 정책).
            _fail("봉투 없는 problem/knowhow", {"type": t}, errors.GATE_REJECT)
        _check_envelope(_need(p, "envelope", dict, "genesis"))
    if "parent" in p:   # §2-1b 관계 — 상세 검증은 S2-7
        _need(p, "parent", dict, "genesis")


def _check_post(p: dict[str, Any]) -> None:
    _closed(p, ("round", "body", "counter", "refs"), "post")
    r = _need(p, "round", int, "post")
    if r not in ROUNDS:
        _fail("라운드가 계약 밖", {"round": r, "allowed": list(ROUNDS)})
    _need(p, "body", str, "post")
    if "counter" in p:
        for i, c in enumerate(_need(p, "counter", list, "post")):
            if type(c) is not dict:
                _fail("counter 항목은 객체여야 한다", {"where": f"post.counter[{i}]"})
            _closed(c, ("target_message_id", "point"), f"post.counter[{i}]")
            tid = _need(c, "target_message_id", str, f"post.counter[{i}]")
            if not is_id(tid):
                _fail("counter 대상 id 형식이 아니다", {"where": f"post.counter[{i}]"})
            _need(c, "point", str, f"post.counter[{i}]")


def _check_advance(p: dict[str, Any]) -> None:
    _closed(p, ("from_round", "to_round"), "advance")
    a = _need(p, "from_round", int, "advance")
    b = _need(p, "to_round", int, "advance")
    if a not in ROUNDS or b not in ROUNDS:
        _fail("라운드가 계약 밖", {"from_round": a, "to_round": b})
    # 단조 증가·건너뜀 금지는 **여기서** 막는다. 모양의 문제이기도 하다.
    if b != a + 1:
        _fail("라운드는 한 칸씩만 전진한다", {"from_round": a, "to_round": b})


def _check_resolution(p: dict[str, Any]) -> None:
    _closed(p, ("summary", "dissent", "recommended_actions"), "resolution")
    _need(p, "summary", str, "resolution")
    for i, d in enumerate(_need(p, "dissent", list, "resolution")):
        if type(d) is not dict:
            _fail("이견 항목은 객체여야 한다", {"where": f"resolution.dissent[{i}]"})
        _closed(d, ("from", "message_id", "quote"), f"resolution.dissent[{i}]")
        _need(d, "from", str, f"resolution.dissent[{i}]")
        _need(d, "quote", str, f"resolution.dissent[{i}]")
    actions = _need(p, "recommended_actions", list, "resolution")
    for i, a in enumerate(actions):
        if type(a) is not dict:
            _fail("권고 항목은 객체여야 한다", {"where": f"resolution.recommended_actions[{i}]"})
        _closed(a, ("text", "execution", "spawn"), f"resolution.recommended_actions[{i}]")
        _need(a, "text", str, f"resolution.recommended_actions[{i}]")
        # ★NFR-8 — 아고라의 결론은 언제나 권고다. 집행 금지 표식이 없으면 정책 위반(3).
        if a.get("execution") != "forbidden":
            _fail("권고에 집행 금지 표식이 없다",
                  {"where": f"resolution.recommended_actions[{i}]",
                   "want": "forbidden", "got": a.get("execution")},
                  errors.GATE_REJECT)


def _check_answer_selected(p: dict[str, Any]) -> None:
    _closed(p, ("post_message_id",), "answer_selected")
    mid = _need(p, "post_message_id", str, "answer_selected")
    if not is_id(mid):
        _fail("id 형식이 아니다", {"where": "answer_selected.post_message_id",
                                   "len": ID_HEX_LEN})


def _check_close(p: dict[str, Any]) -> None:
    _closed(p, ("reason",), "close")
    r = _need(p, "reason", str, "close")
    if r not in CLOSE_REASONS:
        _fail("종결 사유가 계약 밖", {"reason": r, "allowed": list(CLOSE_REASONS)})


def _check_delegate_chair(p: dict[str, Any]) -> None:
    _closed(p, ("new_chair",), "delegate_chair")
    _need(p, "new_chair", str, "delegate_chair")


def _check_abort(p: dict[str, Any]) -> None:
    _closed(p, ("reason",), "abort")
    _need(p, "reason", str, "abort")


def _check_vote(p: dict[str, Any]) -> None:
    _closed(p, ("target", "value"), "vote")
    t = _need(p, "target", str, "vote")
    if not is_id(t):
        _fail("id 형식이 아니다", {"where": "vote.target"})
    v = _need(p, "value", int, "vote")
    if v not in (0, 1):
        _fail("투표 값은 0 또는 1", {"value": v})


_PAYLOAD_CHECKS = {
    "genesis": _check_genesis,
    "post": _check_post,
    "advance": _check_advance,
    "resolution": _check_resolution,
    "answer_selected": _check_answer_selected,
    "close": _check_close,
    "delegate_chair": _check_delegate_chair,
    "abort": _check_abort,
    "vote": _check_vote,
}

# 계약 표(§2-2)와 이 파일이 어긋나면 그 자체가 결함이다 — import 시점에 잡는다.
assert set(_PAYLOAD_CHECKS) == set(KINDS), (
    f"스키마와 계약 kind 목록 불일치: {sorted(set(_PAYLOAD_CHECKS) ^ set(KINDS))}")


def validate(event: Any) -> dict[str, Any]:
    """공통 칸 + kind 별 payload 를 검사한다. 통과하면 그 이벤트를 그대로 돌려준다."""
    if type(event) is not dict:
        _fail("이벤트는 객체여야 한다", {"got": type(event).__name__})
    _closed(event, COMMON_REQUIRED + COMMON_OPTIONAL, "event")

    if _need(event, "v", int, "event") != 1:
        _fail("판본이 다르다", {"v": event["v"]})
    kind = _need(event, "kind", str, "event")
    if kind not in KINDS:
        _fail("계약에 없는 kind", {"kind": kind, "allowed": list(KINDS)})
    for key in ("thread_id", "message_id"):
        if not is_id(_need(event, key, str, "event")):
            _fail("id 형식이 아니다", {"key": key, "want_hex_len": ID_HEX_LEN})
    prev = _need(event, "prev", str, "event")
    expected = _need(event, "expected_state", str, "event")
    if kind == "genesis":
        if prev != GENESIS_PREV or expected != GENESIS_EXPECTED_STATE:
            _fail("genesis 의 prev·expected_state 가 계약값이 아니다",
                  {"prev": prev, "expected_state": expected,
                   "want": [GENESIS_PREV, GENESIS_EXPECTED_STATE]})
    else:
        if prev == GENESIS_PREV:
            _fail("genesis 가 아닌데 prev 가 genesis 다", {"kind": kind})
        if len(prev) != 64:
            _fail("prev 는 앞 이벤트 해시여야 한다", {"len": len(prev)})
    _need(event, "from", str, "event")
    _need(event, "roster", str, "event")
    _need(event, "scrub", dict, "event")
    _need(event, "ts", str, "event")
    _PAYLOAD_CHECKS[kind](_need(event, "payload", dict, "event"))
    return event
