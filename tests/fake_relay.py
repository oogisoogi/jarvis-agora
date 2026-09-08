"""가짜 릴레이 — 표준 라이브러리 `http.server` 로 같은 계약을 말하는 시험용 서버.

★**왜 `agora/` 가 아니라 여기 있나**: 이것은 제품 모듈이 아니라 **서버**다. 참가자에게 배포되는
  패키지 안에 「그들이 절대 실행하지 않을 서버」를 넣지 않는다. (`store_mock` 은 어댑터라 제품
  옆에 있는 것이 맞았지만, 이건 상대편이다.)

★**착하게만 굴지 않는다.** reducer·watch·어댑터의 방어를 재려면 운반층이 나쁘게 굴 수 있어야 한다:
  ⑴`refresh_updated_at=False` — 방의 갱신 시각을 **안 올린다**(RC-3: watch 가 조용히 눈이 머는 상황).
  ⑵`idempotent=False`      — 같은 message_id 를 **두 번 만든다**(서버 약속이 깨진 상황).
  ⑶`revoked_404=True`      — 폐기 목록에 404 로 답한다(「없음」을 빈 파일로 말하지 않는 서버).
  ⑷`derive_status=False`   — 방 상태를 파생하지 않는다(대조 축이 없는 서버).
  ⑸`page_size>0`           — 이벤트를 쪼개 준다(어댑터가 끝까지 이어 받는지).
  ⑹`inject_raw`            — 우리 서식이 아닌 본문을 심는다.
  ⑺`require_proof=False`   — 소유 증명 서명 없이도 등록을 받아 준다(계약을 안 지키는 서버).
  ⑻`opaque_cursor=True`    — 커서에 `=`·`&` 를 넣는다(계약이 「불투명」이라 부르는 것의 실물).
  ⑼`protocol_codes=False`  — 실패 본문의 `code` 를 계약값이 아닌 HTTP 숫자로 적는다(구 서버).
  ⑽`lie_valid=True`        — 격리돼야 할 이벤트에 `valid:true` 를 적는다(거짓말하는 파생).
  ⑾`checkpoint=…`          — 운영자 서명 체크포인트(없으면 200 + `checkpoint:null` · §3-6b).
  ⑿`forge_retry=True`      — 실패 본문에 우리 재시도 표식(`retry`)을 **위조해** 적는다.
  ⒀`operators_text`        — 운영자 명부(체크포인트 발행 권한). 비면 `POST …/checkpoint` 는 403 이다.

★**계약 확정본(`docs/RELAY.md@b2ca815`)에 맞춘다**: 실패 본문 `code` 는 PROTOCOL 코드 ·
  등록 소유 증명은 **다섯 칸**(`purpose` 포함) 서명 · 체크포인트 부재는 404 가 아니라 200 + null ·
  429 에는 `Retry-After` · 목록 상한 밖 `limit` 은 400 · 이벤트·방에 파생 덧칸을 싣는다.

⚠**이 서버 상대의 초록은 「논리가 맞다」는 뜻이지 「진짜 릴레이가 그렇게 답한다」는 뜻이 아니다.**
  그 대조는 워커 A 의 릴레이가 설 때 한다(설계 §11).
⚠★그리고 **더블이 계약을 잘 지킬수록 어떤 시험은 공허해진다** — 그래서 위 스위치들이 있다.
  계약을 지키는 쪽만 재면 「우리가 서버를 믿는 자리」가 초록 뒤에 숨는다.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agora.ledger import now_iso            # noqa: E402


class FakeRelay:
    def __init__(self, *, idempotent: bool = True, refresh_updated_at: bool = True,
                 revoked_404: bool = False, derive_status: bool = True,
                 page_size: int = 0, preempt_identity: bool = True,
                 require_proof: bool = True, opaque_cursor: bool = False,
                 protocol_codes: bool = True, lie_valid: bool = False,
                 chain_verdicts: bool = True,
                 checkpoint: dict[str, Any] | None = None,
                 checkpoint_404: bool = False, verdict: dict[str, Any] | None = None,
                 retry_after: str | None = None,
                 body_code_override: int | None = None,
                 forge_retry: bool = False, verify_events: bool = True) -> None:
        self.idempotent = idempotent
        self.refresh_updated_at = refresh_updated_at
        self.revoked_404 = revoked_404
        self.derive_status = derive_status
        self.page_size = page_size
        self.preempt_identity = preempt_identity
        self.require_proof = require_proof
        self.opaque_cursor = opaque_cursor
        self.protocol_codes = protocol_codes
        self.lie_valid = lie_valid
        self.checkpoint = checkpoint
        self.checkpoint_404 = checkpoint_404
        self.verdict = verdict
        self.retry_after = retry_after
        # ★상태와 **다른** 코드를 본문에 적는다 — 계약 §3-0 이 「둘이 갈리면 code 가 이긴다」고
        #   한 그 갈림을 실제로 만들어 본다. 갈리지 않으면 그 규칙은 시험되지 않는다.
        self.body_code_override = body_code_override
        # ★남의 서버가 **우리 내부 표식**을 흉내내는 상황. 표식이 우리 것이 아니면 판정도 우리 것이 아니다.
        self.forge_retry = forge_retry
        # ★서명 검증을 끄는 스위치 — 「검증을 안 하는 서버」를 재는 자리(우리 reducer 가 정본임을
        #   보이는 케이스가 그것을 쓴다). 기본은 **계약대로 검증한다**.
        self.verify_events = verify_events
        # ★사슬 판정(경합·닿지 않음) 스위치. 기본은 **계약대로 판정한다** — 끄는 쪽이 특수 상황이다
        #   (「판정을 안 하는 서버」 = 09-06 이전의 우리 더블이 그 상태였다).
        self.chain_verdicts = chain_verdicts
        # ★**경합을 시험이 만들 수 있게** 하는 자리: 다음 `POST /events` **직전**에 이 글을 먼저
        #   적는다(= 남이 그 자리를 먼저 차지한다). 실물에서는 밀리초 창이라 재현이 안 되므로,
        #   더블이 그 창을 **결정론으로** 연다. **줄 세운 순서대로 한 건씩** 쓰이고 사라진다 —
        #   재시도까지 밀리는 상황(= 두 번 진다)을 재려면 두 건이 필요하기 때문이다.
        self.race_queue: list[str] = []
        self.seen_queries: list[str] = []    # 서버가 실제로 읽은 질의 — 인코딩 시험이 본다
        self.rooms: dict[str, dict[str, Any]] = {}
        self.registered: dict[str, dict[str, str]] = {}
        self.roster_text: dict[str, str] = {"allowed_signers": "", "revoked_keys": "",
                                            "operators": ""}
        self.counter = 0
        self.calls: list[str] = []           # 어떤 경로가 몇 번 불렸나 — 시험이 본다
        self.status_override: dict[str, int] = {}   # 경로 접두 → 강제 상태(429·500 …)

    # ── 저장 ────────────────────────────────────────────────────────────────
    def _room(self, room_id: str, *, category: str = "", title: str = "") -> dict[str, Any]:
        room = self.rooms.get(room_id)
        if room is None:
            room = {"room_id": room_id, "category": category, "title": title,
                    "created_at": now_iso(), "updated_at": now_iso(), "events": [],
                    # ★사슬 상태 — 계약 §5 규칙 2(정렬·경합)를 더블에서도 **실제로** 돌린다.
                    "head": None, "hashes": set(),
                    # ★전이 상태 — `expected_state` 를 판정하려면 **해시 대상 8칸**이 필요하다
                    #   (계약 §2-1 · reducer 의 `_state_hash`). genesis 에서 세워진다.
                    "state": None, "post_ids": set()}
            self.rooms[room_id] = room
        return room

    def append_event(self, *, thread_id: str, category: str, title: str,
                     body: str, is_genesis: bool) -> dict[str, Any]:
        """계약 §3-2 의 세 갈래를 그대로 흉내낸다 — **새 행(201) · 멱등(200) · 재사용 충돌(422)**.

        ★agy 적대검증 2026-09-05 지적(수용): 구판은 무엇이 오든 201 을 줬고 내용(해시)을 안 봤다.
          그래서 ⑴어댑터의 **200 경로가 한 번도 안 돌았고** ⑵`message_id` 재사용 방어가
          더블 쪽에 아예 없어 **거짓 초록**이었다.
        ★`idempotent=False` 스위치는 이 세 갈래 전체를 끈다 — 「약속을 안 지키는 서버」가
          그 스위치의 뜻이기 때문이다(충돌 검사도 그 약속의 일부다).
        """
        room = self._room(thread_id, category=category, title=title)
        if is_genesis and title:
            room["title"] = title
        message_id = _message_id_of(body)
        if self.idempotent and message_id:
            for row in room["events"]:
                if row.get("message_id") != message_id:
                    continue
                if row.get("hash") != _event_hash_of(body):
                    raise _Conflict(message_id)   # 같은 id·다른 내용 = 다른 글이다(422/3)
                return dict(row, existing=True)   # ★멱등 — 새 행을 만들지 않는다(200)
        self.counter += 1
        digest = _event_hash_of(body)
        row = {"event_id": _event_id_of(self.counter), "created_at": now_iso(),
               "body": body, "is_genesis": bool(is_genesis), "message_id": message_id,
               "hash": digest}
        row.update(self._chain_verdict(room, body, digest, is_genesis))
        room["events"].append(row)
        if self.refresh_updated_at:
            room["updated_at"] = row["created_at"]
        return dict(row, existing=False)

    def inject_raw(self, *, room_id: str, body: str) -> dict[str, Any]:
        """우리 서식이 아닌 글을 심는다(웹에서 손으로 쓴 댓글에 해당)."""
        return self.append_event(thread_id=room_id, category="debate", title="",
                                 body=body, is_genesis=False)

    def _chain_verdict(self, room: dict[str, Any], body: str, digest: str,
                       is_genesis: bool) -> dict[str, Any]:
        """사슬 판정 + **전이 판정** — 계약 §5 규칙 2 와 CAS 를 더블에서도 실제로 돌린다(F-1 봉합 ⓓ).

        ★★09-06 실물 리허설이 이 자리에서 깨졌다: 실물은 `lost_race`·`unreachable` 을 냈는데
          **더블은 그런 판정을 낸 적이 없다** — 그래서 하네스는 22/22 초록이었고,
          같은 절차가 실물에서 네 건 격리됐다. ★더블이 못 내는 판정은 시험이 비어 있다.
        ★★그리고 그 봉합이 **절반이었다**(codex 2R HIGH · 2026-09-09): 사슬(`prev`)만 보고
          **`expected_state` 는 안 봤다.** 실물은 `prev` 가 맞아도 `expected_state != stateHash(state)`
          면 `stale_expected_state` 로 격리한다 — 즉 **이 티켓이 고치는 CAS 그 자체를 더블이
          판정하지 않고 있었다.** 「definitely-wrong」을 넣어도 더블은 `valid:true` 를 줬다.
          ⇒ F-1 의 핵심 시험이 **실물보다 느슨한 상대**를 쓰고 있었다.

        판정은 두 단이다(실물 `relay/src/lib/reducer.ts` 의 2단·3단 그대로):
          **2단(사슬)** — `prev` 가 지금 머리면 이긴다 · 아는 해시면 `lost_race` · 모르면 `unreachable`.
            둘 다 `stale` 이지 격리가 아니다(계약 §5 규칙 2 원문).
          **3단(전이)** — 이긴 글에 대해 `expected_state == stateHash(state)` 를 본다.
            어긋나면 `stale_expected_state` 로 **격리**하고, ⚠**머리는 전진시킨다**
            (실물 `reject()` 가 그렇게 한다 — 안 그러면 한 사람이 이벤트 하나로 방을 영구
            동결시킬 수 있다. L-1 교착 봉합).
        ⚠`vote` 는 머리를 전진시키지 않는다(계약 §5 규칙 5).
        ⚠**여기서 안 재는 것**(정직): 예산·라운드·반론 대상 같은 **상태를 안 바꾸는** 전이 규칙은
          판정하지 않는다. 해시 8칸에 영향이 없어 `expected_state` 대조를 흐리지 않기 때문이다.
          그 축은 `CONTRACT_COVERAGE` 표에 「판정 안 함」으로 적혀 있다.
        """
        if not self.chain_verdicts:
            return {"valid": True, "stale": False, "quarantined": False, "reason": None}
        if room["head"] is None:
            # 첫 글이 사슬의 시작이다. ⚠`is_genesis` 만 보고 무조건 받으면 **genesis 가 둘인 방**이
            #   생긴다(agy 1R 지적 4 · 수용) — 이미 머리가 있으면 아래 규칙으로 떨어져야 한다.
            room["head"], _ = digest, room["hashes"].add(digest)
            room["state"] = _genesis_state(body, digest)
            return {"valid": True, "stale": False, "quarantined": False, "reason": None}
        prev = _prev_of(body)
        if prev != room["head"]:
            reason = "lost_race" if prev in room["hashes"] else "unreachable"
            return {"valid": False, "stale": True, "quarantined": False, "reason": reason}
        room["hashes"].add(digest)
        state = room["state"]
        if state is not None and not _expected_state_ok(body, state):
            # ★격리해도 사슬은 지나갔다 — 머리를 전진시킨다(실물 reject() 와 같다).
            room["head"] = digest
            return {"valid": False, "stale": False, "quarantined": True,
                    "reason": "stale_expected_state"}
        kind = _kind_of(body)
        if state is not None:
            _apply_transition(room, body, kind)
        if kind != "vote":
            # vote 는 머리를 안 옮긴다(계약 §5 규칙 5).
            # ⚠문자열 검색으로 재면 **본문에 그 글자가 든 발언**까지 vote 로 읽는다
            #   (agy 1R 지적 4 · 수용) — 파싱해서 `kind` 칸을 본다.
            room["head"] = digest
        if state is not None:
            state["head"] = room["head"]
        return {"valid": True, "stale": False, "quarantined": False, "reason": None}

    def derived(self, room_id: str) -> dict[str, Any]:
        """서버가 이벤트에서 파생한 상태 — **클라 reducer 와 독립적으로** 계산한다.

        ★일부러 단순하다(close 이벤트가 있으면 닫힘 · answer_selected 가 있으면 답 선택됨).
          클라와 같은 코드를 쓰면 대조가 자기 자신과의 대조가 되어 아무것도 못 잡는다.
        """
        room = self.rooms.get(room_id) or {"events": []}
        closed = answered = False
        closed_at = None
        for row in room["events"]:
            if row.get("valid") is False:
                # ★밀린 글은 상태를 안 바꾼다 — 실물이 그렇게 답한다(09-06: close 가 unreachable 이라
                #   `closed:false` 였다). 여기서 세면 더블만 방을 닫고 시험이 또 공허해진다.
                continue
            body = row.get("body") or ""
            if '"kind":"close"' in _compact(body):
                closed, closed_at = True, row["created_at"]
            if '"kind":"answer_selected"' in _compact(body):
                answered = True
        out = {"closed": closed, "answered": answered, "closed_at": closed_at}
        # ★파생 덧칸(계약 §3-3) — 실물이 주는 축을 더블도 준다. 안 주면 3자 대조가 **더블 상대로는
        #   한 번도 안 도는 갈래**를 갖게 되고, 어댑터가 그 칸을 버려도(codex 2R HIGH) 리허설은
        #   초록이다. 값은 **더블이 계약에서 옮겨 적은 전이 규칙**으로 만든 것이라, 우리 리듀서와
        #   갈리면 리허설이 그 자리에서 붉어진다 — 그 붉음이 두 구현의 등가 증명이다.
        state = (self.rooms.get(room_id) or {}).get("state")
        if state:
            out.update({"state": state["state"], "round": state["round"],
                        "state_hash": _state_hash(state),
                        "close_reason": state["close_reason"], "chair": state["chair"],
                        "type": state["type"], "requester": state["requester"]})
        return out


class _Conflict(Exception):
    """같은 `message_id` 에 다른 내용 — 계약 §3-2 의 `message_id_reused`."""

    def __init__(self, message_id: str) -> None:
        super().__init__(message_id)
        self.message_id = message_id


def _event_hash_of(body: str) -> str:
    """이벤트의 내용 해시 — **서버가 스스로 다시 만든다**(클라 canonical 을 부르지 않는다).

    ★부르면 「우리 계산으로 우리 계산을 재는」 대조가 된다. 규칙(정렬·구분자)은 계약이 정한 것을
      여기 옮겨 적는다.
    """
    from agora.event import parse_post
    try:
        event = parse_post(body)["event"]
    except Exception:            # noqa: BLE001 — 우리 서식이 아니면 원문 그대로 잰다
        return _sha256_text(body)
    return _sha256_text(json.dumps(event, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")))


def _sha256_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _roster_digest(roster_text: dict[str, str]) -> str:
    """명부 3종의 체크포인트 해시 — 계약 §3-6b 의 「`roster.checkpoint` 와 같은 산식」.

    ★**여기서 다시 만든다**(클라 `agora.roster.checkpoint` 를 부르지 않는다): 같은 함수를 쓰면
      우리 계산으로 우리 계산을 재게 된다. 규칙은 문서가 정한 것을 옮겨 적는다 —
      논리 이름표 + 길이(8바이트 빅엔디언) + 내용, 순서는 allowed_signers → revoked_keys → operators.
    ★실측(2026-09-06): 이 산식이 **실물 릴레이의 `current` 와 일치**한다(우리 계산 = 서버 계산).
    """
    import hashlib
    h = hashlib.sha256()
    for name in ("allowed_signers", "revoked_keys", "operators"):
        blob = roster_text.get(name, "").encode("utf-8")
        h.update(f"participants/{name}".encode("utf-8"))
        h.update(len(blob).to_bytes(8, "big"))
        h.update(blob)
    return h.hexdigest()


def _compact(body: str) -> str:
    return "".join(body.split())


# 릴레이 계약 §3-7 표 — HTTP 상태 → PROTOCOL 코드. **서버 쪽 표를 여기 그대로 옮긴다**
# (클라 코드를 부르지 않는다 — 부르면 우리 매핑으로 우리 매핑을 재게 된다).
CONTRACT_CODES: dict[int, int] = {400: 10, 401: 4, 403: 5, 404: 7, 409: 9,
                                  413: 3, 422: 3, 429: 7, 500: 7, 502: 7, 503: 7}


def _register_canonical(payload: dict[str, Any]) -> bytes:
    """등록 소유 증명의 **서명 대상 바이트**(계약 §3-1) — 서버가 스스로 다시 만든다.

    ★다섯 칸이다(`purpose` 포함). 클라가 네 칸만 서명했으면 이 바이트와 안 맞아 검증이 깨진다 —
      그것이 이 더블이 잡아야 하는 사건이다. 그래서 `agora.event.canonical_bytes` 를 부르지 않고
      **여기서 다시 만든다**: 클라와 같은 함수를 쓰면 둘이 함께 틀려도 초록이 난다.
    """
    doc = {"display_name": payload.get("display_name"),
           "fingerprint": payload.get("fingerprint"),
           "participant_id": payload.get("participant_id"),
           "public_key": payload.get("public_key"),
           "purpose": "agora-register-v1"}
    return json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _checkpoint_canonical(payload: dict[str, Any]) -> bytes:
    """체크포인트 서명 대상 바이트(계약 §3-6b) — **서버가 스스로 다시 만든다.**

    ★네 칸이다: 전송에는 `purpose` 가 없고 **서버가 같은 상수를 넣어** 계산한다.
      클라가 다른 목적으로 서명한 것을 여기서 받아 줄 길이 없어야 하기 때문이다.
    """
    doc = {"checkpoint": payload.get("checkpoint"),
           "purpose": "agora-roster-checkpoint-v1",
           "signed_at": payload.get("signed_at"),
           "signer": payload.get("signer")}
    return json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


# 계약 §2-1 의 **공통 필수 칸** — ★우리 모듈에서 import 하지 않고 **여기 손으로 적는다.**
#   `agora.schema.COMMON_REQUIRED` 를 불러 오면 「우리 계산으로 우리 계산을 재는」 대조가 되어
#   **조립 결함을 정확히 못 잡는다**(더블의 존재 이유가 그것이다). 계약이 바뀌면 이 줄도 바뀌어야
#   하고, 안 바꾸면 시험이 붉어진다 — 그 붉음이 곧 「계약이 움직였다」는 신호다.
_EVENT_SKELETON = ("v", "kind", "thread_id", "message_id", "prev", "expected_state",
                   "from", "roster", "scrub", "ts", "payload")


def _event_gate(payload: dict[str, Any],
                rooms: dict[str, dict[str, Any]] | None = None,
                ) -> tuple[int, str, dict[str, Any]] | None:
    """서명 앞에 오는 값싼 검사들 — 계약 §3-2 의 **1(크기) · 3 일부(뼈대) · 4(결박) · 5(genesis 정합)**.

    ★순서가 곧 방어다: 크기·뼈대·결박은 한 건만 보고 답할 수 있고, 서명 검증보다 훨씬 싸다.
    ⚠**여기 없는 것(정직)**: 스키마 **9종 닫힌** 검증(3의 나머지)과 스크럽 백스톱(7)은 여전히 없다.
      그 둘을 더블에서 하려면 우리 모듈(`agora.schema`·`agora.scrub`)을 그대로 불러야 해서
      자기 대조가 된다. 대신 **계약이 이름을 준 뼈대 11칸**은 위처럼 손으로 적어 독립적으로 본다
      (agy 2R 2026-09-06 지적 · 부분 수용). 남는 구멍의 모양도 정직하게 적어 둔다:
      **9종별 payload 칸·봉투 정책(`execution` 표식 등)이 빠진 이벤트는 이 더블을 통과하고
      실물에서만 422 로 터진다.** 그 자리는 클라이언트 쪽 `schema.validate` 가 막고 있고,
      더블은 그것을 **재지 않는다**(= 클라이언트 조립 버그는 리허설·실물에서 잡힌다).
    """
    from agora.event import parse_post
    body = payload.get("body", "")
    if len(body.encode("utf-8")) > 64 * 1024:
        return (413, "크기 상한 초과", {"bytes": len(body.encode("utf-8"))})
    try:
        event = parse_post(body)["event"]
    except Exception:            # noqa: BLE001 — 서식은 다음 관문이 본다
        return None
    missing = [k for k in _EVENT_SKELETON if k not in event]
    if missing:
        return (400, "계약 뼈대 칸이 없다", {"missing": missing})
    is_genesis = bool(payload.get("is_genesis"))
    signed_payload = event.get("payload") if type(event.get("payload")) is dict else {}
    room = (rooms or {}).get(payload.get("thread_id")) or {}
    # 계약 §3-2 검사 4 — 요청 인자 == **서명된** 값. ★`title` 은 서명 대상 밖이라(계약이 그렇게
    #   적어 뒀다) 대조하지 않으면 **보드에 뜨는 방 제목만 서명 밖에서 바꿔치기**할 수 있다.
    #   genesis 가 아닌 글은 서명 안에 유형·제목이 없으므로, **방에 이미 적힌 값**과 댄다.
    bindings: list[tuple[str, Any, Any]] = [
        ("thread_id", payload.get("thread_id"), event.get("thread_id"))]
    if is_genesis:
        bindings.append(("category", payload.get("category"), signed_payload.get("type")))
        bindings.append(("title", payload.get("title"), signed_payload.get("title")))
    elif room.get("category"):
        bindings.append(("category", payload.get("category"), room.get("category")))
    for field, sent, signed in bindings:
        if signed is not None and sent != signed:
            return (400, "요청 인자가 서명된 값과 다르다",
                    {"field": field, "sent": sent, "signed": signed})
    if is_genesis != (event.get("kind") == "genesis"):
        return (400, "is_genesis 가 서명된 kind 와 안 맞는다",
                {"is_genesis": is_genesis, "kind": event.get("kind")})
    return None


def _event_verdict(body: str, allowed_signers: str) -> tuple[str, str]:
    """이벤트 한 건의 서명 판정 — `ok` / `BAD` / `unsigned`(계약 §4 의 3값 그대로).

    ★서버가 하는 일을 그대로 옮긴다: 펜스 안 글자를 믿지 않고 **canonical 로 다시 만들어**
      그 바이트에 서명을 보고, 그 키가 `from` **그 이름의** 키인지까지 본다
      (`ssh-keygen -Y verify -I <principal>` 이 하는 일).
    """
    import subprocess
    import tempfile
    from agora.event import canonical_bytes, parse_post
    try:
        parsed = parse_post(body)
    except Exception:            # noqa: BLE001 — 우리 서식이 아니면 서명 이전의 문제다
        return "unsigned", "not_our_format"
    event, signature = parsed["event"], parsed["signature"]
    principal = event.get("from")
    if not signature or "BEGIN SSH SIGNATURE" not in (signature or ""):
        return "unsigned", "no_signature"
    with tempfile.TemporaryDirectory() as tmp:
        sig_path = os.path.join(tmp, "e.sig")
        with open(sig_path, "w", encoding="utf-8") as fh:
            fh.write(signature)
        raw = canonical_bytes(event)
        checked = subprocess.run(
            ["ssh-keygen", "-Y", "check-novalidate", "-n", "jarvis-agora@godmeyou.kr",
             "-s", sig_path], input=raw, capture_output=True, timeout=30)
        if checked.returncode != 0:
            return "BAD", "signature_does_not_match_bytes"
        roster_path = os.path.join(tmp, "allowed_signers")
        with open(roster_path, "w", encoding="utf-8") as fh:
            fh.write(allowed_signers)
        verified = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-n", "jarvis-agora@godmeyou.kr",
             "-f", roster_path, "-I", principal or "", "-s", sig_path],
            input=raw, capture_output=True, timeout=30)
        if verified.returncode != 0:
            return "unsigned", "principal_mismatch"
    return "ok", "verified"


def _signature_matches(raw: bytes, signature: str, *,
                      principal: str | None = None,
                      allowed_signers: str | None = None) -> bool:
    """서명이 **그 바이트**에 대한 것인가 — 그리고 `principal` 이 주어지면 **그 이름의 키인가**.

    ★agy 적대검증 2026-09-06 지적(수용): `check-novalidate` 만 보면 「남의 공개키를 싣고 내 키로
      서명」이 통과한다(등록의 소유 증명이 막으려던 바로 그것). 그래서 이름이 있는 경우에는
      `ssh-keygen -Y verify -I <principal>` 까지 본다 — 계약 §4 가 하는 일 그대로다.
    """
    import subprocess
    import tempfile
    if not signature or "BEGIN SSH SIGNATURE" not in signature:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        sig_path = os.path.join(tmp, "proof.sig")
        with open(sig_path, "w", encoding="utf-8") as fh:
            fh.write(signature)
        checked = subprocess.run(
            ["ssh-keygen", "-Y", "check-novalidate", "-n", "jarvis-agora@godmeyou.kr",
             "-s", sig_path],
            input=raw, capture_output=True, timeout=30)
        if checked.returncode != 0:
            return False
        if principal is None or allowed_signers is None:
            return True
        roster_path = os.path.join(tmp, "allowed_signers")
        with open(roster_path, "w", encoding="utf-8") as fh:
            fh.write(allowed_signers)
        verified = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-n", "jarvis-agora@godmeyou.kr",
             "-f", roster_path, "-I", principal, "-s", sig_path],
            input=raw, capture_output=True, timeout=30)
        return verified.returncode == 0


# ── 계약에서 옮겨 적은 전이 규칙(PROTOCOL v1 · `agora/reducer.py` · `relay/src/lib/reducer.ts`) ──
# ★★**우리 모듈에서 import 하지 않는다.** `agora.reducer.apply` 를 부르면 「우리 계산으로 우리
#   계산을 재는」 대조가 되어 더블의 존재 이유가 사라진다(이 파일의 `_EVENT_SKELETON`·
#   `CONTRACT_CODES`·`_roster_digest` 가 같은 규율로 손으로 적혀 있다).
#   계약이 바뀌면 이 줄들이 바뀌어야 하고, **안 바꾸면 리허설이 붉어진다** — 그 붉음이 신호다.
_DEBATE_ROUNDS = ("r0", "r1", "r2", "r3")
_EXPIRED = "expired"
# 상태 해시가 덮는 8칸 — 순서는 무관하다(canonical 이 키를 정렬한다). **머리가 들어 있다**:
# 안 넣으면 「같은 결론에 이른 서로 다른 역사」가 같은 해시가 되고 CAS 에 창이 생긴다.
_HASH_FIELDS = ("type", "state", "round", "chair", "requester", "solved_by",
                "close_reason", "head")


def _state_hash(state: dict[str, Any]) -> str:
    """상태 해시 — 다음 이벤트의 `expected_state` 가 가리키는 값(계약 §2-1)."""
    snapshot = {k: state.get(k) for k in _HASH_FIELDS}
    return _sha256_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")))


def _event_of(body: str) -> dict[str, Any]:
    from agora.event import parse_post
    try:
        return parse_post(body)["event"]
    except Exception:            # noqa: BLE001 — 우리 서식이 아니면 사슬 밖이다
        return {}


def _genesis_state(body: str, digest: str) -> dict[str, Any] | None:
    """사슬의 첫 글에서 상태를 세운다. 우리 서식이 아니면 **상태가 없다**(지어내지 않는다)."""
    event = _event_of(body)
    payload = event.get("payload") if type(event.get("payload")) is dict else None
    if not event or payload is None or event.get("kind") != "genesis":
        return None
    gtype = payload.get("type")
    return {"type": gtype,
            "state": "r0" if gtype == "debate" else "open",
            "round": 0 if gtype == "debate" else None,
            "chair": payload.get("chair") or event.get("from"),
            "requester": event.get("from"),
            "solved_by": None, "close_reason": None, "head": digest}


def _event_id_of(seq: int) -> str:
    """고정폭 단조 식별자 — 계약이 정한 서식(`ev_%016d` · 실물 `relay/src/lib/store.ts`).

    ★자릿수가 곧 계약이다: 리듀서의 동률 규칙이 **문자열 사전순**이라 폭이 흔들리면 순서가 뒤집힌다.
      구판 더블은 `EV_1` 을 썼고, 그래서 클라이언트의 도착순 비교(`_arrived_after` 의 고정폭
      정규식)가 더블 상대로는 **한 번도 안 걸렸다** — 실물에서만 도는 갈래가 무검증이었다.
    """
    return "ev_" + str(seq).zfill(16)


def _expected_state_ok(body: str, state: dict[str, Any]) -> bool:
    """CAS — `expected_state` 가 **지금 상태의 해시**인가(계약 §2-1 · 실물 reducer 3단 첫 검사).

    ★만료 관대함도 함께 옮긴다: 만료된 스레드를 되살리러 쓰는 사람은 **만료가 반영된 상태**를
      보고 쓴다. ⚠더블은 마감 시각을 재지 않으므로 이 관대함이 **실물보다 넓다** — 넓은 쪽으로
      틀리는 것은 거짓 적색을 안 만든다(대신 이 축의 미탐 하나를 남긴다 · 표에 적어 둔다).
    """
    seen = _event_of(body).get("expected_state")
    if seen == _state_hash(state):
        return True
    return seen == _state_hash({**state, "state": _EXPIRED})


def _apply_transition(room: dict[str, Any], body: str, kind: str | None) -> None:
    """상태 해시 8칸을 바꾸는 전이만 적용한다 — 나머지 전이 규칙은 판정하지 않는다(표 참조).

    ★권한 조건(의장·의뢰자·운영자)은 **함께** 옮긴다: 안 옮기면 남이 낸 `advance` 로 더블의
      라운드만 움직여 이후 전건이 `stale_expected_state` 가 된다(거짓 적색의 홍수).
    """
    state, event = room["state"], _event_of(body)
    payload = event.get("payload") if type(event.get("payload")) is dict else {}
    who = event.get("from")
    if kind == "post":
        if event.get("message_id"):
            room["post_ids"].add(event["message_id"])
        return
    if kind == "advance":
        if who == state["chair"] and payload.get("from_round") == state["round"]:
            to_round = payload.get("to_round")
            if type(to_round) is int and 0 <= to_round < len(_DEBATE_ROUNDS):
                state["round"], state["state"] = to_round, _DEBATE_ROUNDS[to_round]
    elif kind == "resolution":
        if who == state["chair"] and state["state"] == "r3":
            state["state"] = "resolved"
    elif kind == "answer_selected":
        if who == state["requester"] and payload.get("post_message_id") in room["post_ids"]:
            state["state"], state["solved_by"] = "solved", payload.get("post_message_id")
    elif kind == "close":
        if who in (state["chair"], state["requester"]):
            state["state"], state["close_reason"] = "closed", payload.get("reason")
    elif kind == "delegate_chair":
        if who == state["chair"]:
            state["chair"] = payload.get("new_chair")


def verdict_of_row(row: dict[str, Any], room: dict[str, Any]) -> dict[str, Any]:
    """POST 응답의 참고용 파생 판정 — **계약이 정한 칸 이름**을 쓴다(실물 `index.ts`).

    ★구판은 `state_hash_at_that_point` 라는 **더블에만 있는 이름**을 썼다. 클라이언트가 그 이름을
      읽고 있었으므로, 실물을 상대할 때 그 칸은 **언제나 비어 있었다** — 그리고 아무도 몰랐다
      (없는 칸은 오류를 안 낸다). 이름이 갈리면 「값이 없다」와 「상대가 안 줬다」가 안 갈린다.
    """
    reducer_said = ("accepted" if row.get("valid") is not False
                    else "quarantined" if row.get("quarantined") else "stale")
    state = room.get("state")
    return {"accepted_to_ledger": True, "reducer": reducer_said,
            "reason": row.get("reason"),
            "state_hash": _state_hash(state) if state else None}


# ── 이 더블이 **무엇을 판정하고 무엇을 안 하는가**(계약 파싱 대조표) ────────────────────────
# ★★구판은 여기에 산문 한 줄을 뒀다: 「9종 스키마 검증과 스크럽 백스톱은 여전히 없다」.
#   그 문장은 정직했지만 **셀 수 없었다** — 무엇이 덮였는지, 새 구멍이 생겼는지 아무도 못 잰다
#   (codex 2R 지적). 표로 바꾸면 시험이 표를 읽고, 표가 줄어들면 그 자리가 붉어진다.
# ⚠`judged=False` 는 결함이 아니라 **경계의 선언**이다. 보이지 않는 억제는 미탐과 구별되지 않으므로,
#   안 재는 축도 **이유와 함께** 여기 남는다.
CONTRACT_COVERAGE: tuple[dict[str, Any], ...] = (
    {"check": "§3-2/1 본문 크기 상한(64KiB)", "where": "_event_gate",
     "judged": True, "why": "한 건만 보고 답할 수 있다"},
    {"check": "§2-1 봉투 뼈대 11칸", "where": "_event_gate",
     "judged": True, "why": "계약이 이름을 준 칸을 손으로 옮겨 적었다"},
    {"check": "§3-2/4 요청 인자 == 서명된 값(결박)", "where": "_event_gate",
     "judged": True, "why": "title 은 서명 밖이라 방에 적힌 값과 댄다"},
    {"check": "§3-2 서명이 이 참가자의 것인가", "where": "_event_verdict",
     "judged": True, "why": "명부 원문으로 독립 검증한다"},
    {"check": "§3-2 message_id 재사용(같은 id·다른 내용)", "where": "append_event",
     "judged": True, "why": "멱등 200 과 충돌 422 를 가른다"},
    {"check": "§5 규칙 2 사슬 경합(lost_race·unreachable)", "where": "_chain_verdict",
     "judged": True, "why": "도착순 승부를 순차 더블에서 그대로 잰다"},
    {"check": "§2-1 CAS — expected_state == stateHash(state)", "where": "_expected_state_ok",
     "judged": True, "why": "F-1 의 핵심 계약. 상태 해시 8칸을 계약에서 옮겨 적어 판정한다"},
    {"check": "§5 규칙 5 vote 는 머리를 안 옮긴다", "where": "_chain_verdict",
     "judged": True, "why": "안 옮기면 state_hash 가 갈려 3자 대조가 깨진다"},
    {"check": "전이 권한(의장·의뢰자 · advance/resolution/answer_selected/close/delegate_chair)",
     "where": "_apply_transition", "judged": True,
     "why": "상태 해시 8칸을 바꾸는 전이라 안 재면 이후 전건이 거짓 적색이 된다"},
    {"check": "§3-1 등록 소유 증명 서명", "where": "POST /register",
     "judged": True, "why": "require_proof 스위치로 켜고 끈다"},
    {"check": "§3-6b 체크포인트(운영자·서명·해시 정합)", "where": "POST /participants/checkpoint",
     "judged": True, "why": "403·401·409 를 각각 가른다"},
    {"check": "kind 9종 payload 닫힌 스키마", "where": "—", "judged": False,
     "why": "agora.schema 를 부르면 자기 대조가 된다. 클라 조립 결함은 실물에서 422 로 터진다"},
    {"check": "§3-2/7 스크럽 백스톱", "where": "—", "judged": False,
     "why": "agora.scrub 을 부르면 자기 대조가 된다. 클라 쪽 게이트가 막고 있다"},
    {"check": "운영자 abort · 만료 중 운영자 대리 위임", "where": "—", "judged": False,
     "why": "더블은 운영자 명부를 전이 단계에서 안 본다 — 그 전이는 리허설 절차에 없다"},
    {"check": "예산(posts_per_round·max_chars) · 라운드 밖 발언 · 반론 대상 필수",
     "where": "—", "judged": False,
     "why": "상태 해시 8칸을 안 바꾸므로 CAS 대조를 흐리지 않는다. 판정은 실물·우리 리듀서가 한다"},
    {"check": "마감·만료 시각 판정", "where": "_expected_state_ok", "judged": False,
     "why": "시각을 안 재고 만료 상태 해시를 **무조건** 한 번 더 허용한다 — 실물보다 넓다(미탐 1)"},
)


def _kind_of(body: str) -> str | None:
    from agora.event import parse_post
    try:
        return parse_post(body)["event"].get("kind")
    except Exception:            # noqa: BLE001 — 우리 서식이 아니면 kind 도 없다
        return None


def _prev_of(body: str) -> str | None:
    from agora.event import parse_post
    try:
        return parse_post(body)["event"].get("prev")
    except Exception:            # noqa: BLE001 — 우리 서식이 아니면 사슬 밖이다
        return None


def _message_id_of(body: str) -> str | None:
    from agora.event import parse_post
    try:
        return parse_post(body)["event"].get("message_id")
    except Exception:            # noqa: BLE001 — 우리 서식이 아니면 그냥 아니다
        return None


class _Handler(BaseHTTPRequestHandler):
    relay: FakeRelay = None            # type: ignore[assignment]

    def log_message(self, *args: Any) -> None:     # 조용히 — 시험 출력이 지저분해진다
        return

    # ── 응답 도우미 ─────────────────────────────────────────────────────────
    def _send(self, status: int, payload: Any, *, text: bool = False,
              headers: dict[str, str] | None = None) -> None:
        raw = (payload if text else json.dumps(payload, ensure_ascii=False)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",
                         "text/plain; charset=utf-8" if text else "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    def _fail(self, status: int, message: str, **detail: Any) -> None:
        """실패 본문 = `{code, message, detail}`(계약 §3-0). **code 는 PROTOCOL 코드**다.

        ★`protocol_codes=False` 면 구 서버처럼 HTTP 숫자를 적는다 — 그때 클라는 계약 밖 값을
          버리고 상태 매핑으로 내려가야 한다(그 폴백이 살아 있는지를 재는 스위치다).
        """
        code = CONTRACT_CODES.get(status, 7) if self.relay.protocol_codes else status
        if self.relay.body_code_override is not None:
            code = self.relay.body_code_override
        headers = {}
        if status == 429 and self.relay.retry_after:
            headers["Retry-After"] = self.relay.retry_after
        body = {"code": code, "message": message, "detail": detail or {}}
        if self.relay.forge_retry:
            body["retry"] = True          # 위조 — 클라가 이것을 믿으면 400 도 네 번 두드린다
        self._send(status, body, headers=headers)

    def _override(self, path: str) -> bool:
        for prefix, status in self.relay.status_override.items():
            if path.startswith(prefix):
                self._fail(status, "강제 상태")
                return True
        return False

    def _page(self, rows: list[Any], query: dict[str, list[str]],
              *, high: int, default: int) -> Any:
        """커서 페이지 — **커서는 불투명하다**(계약 §3-3·§3-5).

        ★`opaque_cursor` 면 `=`·`&` 가 든 값을 준다. 클라가 인코딩 없이 이어 붙이면 그 커서는
          다음 요청에서 **두 칸으로 쪼개져** 서버에 닿지 않는다 — 그 실패는 조용하다.
        """
        raw_limit = (query.get("limit") or [str(default)])[0]
        try:
            limit = int(raw_limit)
        except ValueError:
            limit = -1
        if limit < 1 or limit > high:
            self._fail(400, "limit 이 계약 범위 밖이다", limit=raw_limit, max=high)
            return None
        token = (query.get("cursor") or [""])[0]
        start = 0
        if token:
            digits = token.split("=")[-1] if self.relay.opaque_cursor else token
            start = int(digits) if digits.isdigit() else 0
        size = self.relay.page_size or limit
        page = rows[start:start + size]
        nxt = None
        if start + size < len(rows):
            nxt = (f"c&k=v={start + size}" if self.relay.opaque_cursor
                   else str(start + size))
        return {"items": page, "next_cursor": nxt}

    # ── GET ─────────────────────────────────────────────────────────────────
    def do_GET(self) -> None:                       # noqa: N802 — http.server 계약
        url = urlparse(self.path)
        query = parse_qs(url.query)
        self.relay.calls.append(url.path)
        self.relay.seen_queries.append(url.query)
        if self._override(url.path):
            return
        parts = [unquote(p) for p in url.path.split("/") if p]
        if parts == ["participants", "checkpoint"]:
            # ★부재는 404 가 아니라 **200 + checkpoint:null** 이다(계약 §3-6b).
            if self.relay.checkpoint_404:
                self._fail(404, "그런 경로가 없다")       # 엔드포인트가 아직 없는 상대
                return
            current = _roster_digest(self.relay.roster_text)
            if self.relay.checkpoint is None:
                self._send(200, {"checkpoint": None, "current": current, "stale": True})
                return
            self._send(200, {**self.relay.checkpoint, "current": current})
            return
        if parts[:1] == ["participants"] and len(parts) == 2:
            name = parts[1]
            if name == "revoked_keys" and self.relay.revoked_404:
                self._fail(404, "없다")
                return
            if name not in self.relay.roster_text:
                self._fail(404, "없다")
                return
            self._send(200, self.relay.roster_text[name], text=True)
            return
        if parts == ["rooms"]:
            since = (query.get("updated_since") or [None])[0]
            rows = [{"room_id": r["room_id"],
                     "node_id": (r["events"][0]["event_id"] if r["events"] else None),
                     "updated_at": r["updated_at"], "title": r["title"],
                     # 파생 덧칸(계약 §3-3) — 보드용이다. 클라는 무시해야 한다.
                     "signature_all_ok": True, "signature_bad_count": 0}
                    for r in sorted(self.relay.rooms.values(),
                                    key=lambda r: r["updated_at"], reverse=True)
                    if not since or r["updated_at"] >= since]
            page = self._page(rows, query, high=100, default=50)
            if page is not None:
                self._send(200, page)
            return
        if parts[:1] == ["rooms"] and len(parts) == 2:
            room_id = parts[1]
            if room_id not in self.relay.rooms:
                self._fail(404, "그런 방이 없다")
                return
            if not self.relay.derive_status:
                self._send(200, {"room_id": room_id})       # 파생 안 함 — 칸 자체가 없다
                return
            self._send(200, {"room_id": room_id, **self.relay.derived(room_id),
                             "signature_all_ok": True, "signature_bad_count": 0})
            return
        if parts[:1] == ["rooms"] and parts[2:] == ["events"]:
            room = self.relay.rooms.get(parts[1])
            if room is None:
                self._fail(404, "그런 방이 없다")
                return
            rows = []
            for row in room["events"]:
                item = {k: v for k, v in row.items()
                        if k not in ("message_id", "hash", "existing",
                                     "valid", "stale", "quarantined", "reason")}
                # 파생 판정 덧칸(계약 §3-5) — `lie_valid` 면 격리감에도 참을 적는다.
                if not (row.get("message_id") or self.relay.lie_valid):
                    # 우리 서식이 아닌 글 = 격리(자격 없음)
                    item.update({"valid": False, "quarantined": True,
                                 "stale": False, "reason": "permission"})
                elif row.get("valid") is False and not self.relay.lie_valid:
                    # ★경합에 진 글 = **격리가 아니라 stale**(계약 §5 규칙 2 원문) ·
                    #   전이에서 걸린 글(`stale_expected_state` 등) = **격리**다.
                    #   두 사건을 한 칸에 뭉치면 처방이 갈린다(자리를 다시 잡으면 되는가 아닌가).
                    item.update({"valid": False,
                                 "quarantined": bool(row.get("quarantined")),
                                 "stale": not row.get("quarantined"),
                                 "reason": row.get("reason")})
                else:
                    item.update({"valid": True, "quarantined": False,
                                 "stale": False, "reason": None})
                rows.append(item)
            page = self._page(rows, query, high=200, default=100)
            if page is not None:
                self._send(200, page)
            return
        self._fail(404, "그런 경로가 없다")

    # ── POST ────────────────────────────────────────────────────────────────
    def do_POST(self) -> None:                      # noqa: N802 — http.server 계약
        url = urlparse(self.path)
        self.relay.calls.append(url.path)
        if self._override(url.path):
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._fail(400, "JSON 이 아니다")
            return
        if url.path == "/events":
            # ★**서명·명부·폐기를 본다**(계약 §3-2 검사 6 → 401/code 4). 구판 더블은 이 검사를
            #   통째로 빼먹었고, 그래서 「`from` 은 의장인데 서명은 남의 키」인 글이 초록으로
            #   지나갔다 — **실물은 401(principal_mismatch)로 거부한다**(2026-09-06 라이브 실측).
            #   ⇒ 더블이 계약을 덜 지키면 그만큼 시험이 공허해진다. 같은 병의 세 번째 판이다.
            # 계약 §3-2 검사 1(크기)·3 일부(뼈대)·4(결박)·5(genesis 정합)
            if self.relay.race_queue:
                # 남이 먼저 그 자리를 차지한다(계약 §5 규칙 2 = 도착순 승부).
                racer = self.relay.race_queue.pop(0)
                self.relay.append_event(thread_id=payload.get("thread_id", ""),
                                        category=payload.get("category", ""), title="",
                                        body=racer, is_genesis=False)
            gate = _event_gate(payload, self.relay.rooms)
            if gate:
                self._fail(gate[0], gate[1], **gate[2])
                return
            if self.relay.verify_events:
                verdict, why = _event_verdict(payload.get("body", ""),
                                              self.relay.roster_text["allowed_signers"])
                if verdict != "ok":
                    self._fail(401, "서명이 이 참가자의 것이 아니다",
                               verdict=verdict, why=why)
                    return
            try:
                row = self.relay.append_event(
                    thread_id=payload["thread_id"], category=payload.get("category", ""),
                    title=payload.get("title", ""), body=payload.get("body", ""),
                    is_genesis=bool(payload.get("is_genesis")))
            except _Conflict as e:
                # 같은 id·다른 내용 = 재시도가 아니라 **다른 글**이다(계약 §3-2 · 422/code 3).
                self._fail(422, "message_id 를 다른 내용으로 다시 썼다",
                           conflict="message_id_reused", message_id=e.message_id)
                return
            out = {"event_id": row["event_id"], "url": None,
                   "created_at": row["created_at"]}
            if self.relay.verdict is not None:
                out["verdict"] = self.relay.verdict     # 참고용 파생 판정(계약 §3-2·§5)
            elif row.get("valid") is False:
                # ★**받았지만 반영 안 했다**를 그 자리에서 말한다(계약 §5 「이 칸이 새로 얻는 것」).
                #   구판 더블은 이 칸을 만든 적이 없어 클라이언트의 rc 0 이 초록으로 보였다.
                out["verdict"] = verdict_of_row(
                    row, self.relay.rooms.get(payload.get("thread_id"), {}))
            self._send(200 if row.get("existing") else 201, out)   # 멱등은 200 이다
            return
        if url.path == "/participants/checkpoint":
            # 계약 §3-6b — ⑴운영자인가(403/5) ⑵서명이 네 칸 바이트에 맞는가(401/4)
            #             ⑶서명한 해시가 **지금 내 명부**와 같은가(409/9) ⑷서식(400/10)
            signer = payload.get("signer")
            operators = {ln.strip() for ln in self.relay.roster_text.get("operators", "").splitlines()
                         if ln.strip() and not ln.lstrip().startswith("#")}
            if not payload.get("signed_at") or not payload.get("checkpoint"):
                self._fail(400, "칸이 빠졌다")
                return
            if signer not in operators:
                self._fail(403, "운영자 명부에 없다", why="not_an_operator")
                return
            if not _signature_matches(_checkpoint_canonical(payload),
                                      payload.get("signature", ""),
                                      principal=signer,
                                      allowed_signers=self.relay.roster_text["allowed_signers"]):
                self._fail(401, "서명이 계약 바이트와 안 맞는다", why="principal_mismatch")
                return
            current = _roster_digest(self.relay.roster_text)
            if payload["checkpoint"] != current:
                # ★낡은 값을 새 값처럼 두지 않는다 — `current` 를 동봉해 무엇과 다른지 말한다.
                self._fail(409, "서명한 해시가 지금 명부와 다르다", current=current)
                return
            self.relay.checkpoint = {"checkpoint": payload["checkpoint"],
                                     "signer": signer, "signed_at": payload["signed_at"],
                                     "signature": payload["signature"], "stale": False}
            self._send(201, {"checkpoint": payload["checkpoint"], "signer": signer,
                             "signed_at": payload["signed_at"]})
            return
        if url.path == "/register":
            pid = payload.get("participant_id")
            if self.relay.require_proof and not payload.get("signature"):
                # ★소유 증명(릴레이 계약 §3-1) — 없으면 「남의 공개키를 주워다 등록」이 열린다.
                self._fail(401, "소유 증명 서명이 없다", reason="proof_required")
                return
            if self.relay.require_proof and not _signature_matches(
                    _register_canonical(payload), payload.get("signature", ""),
                    principal=pid,
                    # ★**제출된 공개키**로 임시 명부를 만들어 대조한다 — 「이 서명이 이 키의 것인가」를
                    #   보는 것이 소유 증명의 전부다(남의 키를 싣고 내 키로 서명하면 여기서 걸린다).
                    allowed_signers=f"{pid} {payload.get('public_key', '').strip()}\n"):
                # ★★**다섯 칸 바이트에 대한 서명인가**(계약 §3-1). 네 칸만 서명한 클라는 여기서 걸린다 —
                #   서명 자체는 유효한데 **다른 문서의 서명**이다.
                self._fail(401, "소유 증명이 계약 바이트와 안 맞는다",
                           reason="proof_mismatch")
                return
            known = self.relay.registered.get(pid)
            if (known and self.relay.preempt_identity
                    and known.get("fingerprint") != payload.get("fingerprint")):
                # ★신원 선점 — 이미 등록된 id 에 다른 키를 붙이지 못한다(계약 §3-1 · 409/code 9).
                self._fail(409, "이미 다른 키로 등록된 id 다", reason="identity_taken")
                return
            self.relay.registered[pid] = {"public_key": payload.get("public_key", ""),
                                          "fingerprint": payload.get("fingerprint", ""),
                                          "display_name": payload.get("display_name", ""),
                                          "signature": payload.get("signature", "")}
            key_line = payload.get("public_key", "").strip()
            if key_line and key_line not in self.relay.roster_text["allowed_signers"]:
                self.relay.roster_text["allowed_signers"] += f"{pid} {key_line}\n"
            self._send(201, {"participant_id": pid, "registered": True,
                             "fingerprint": payload.get("fingerprint", ""),
                             "created_at": now_iso()})
            return
        self._fail(404, "그런 경로가 없다")


@contextlib.contextmanager
def serving(relay: FakeRelay | None = None, **kwargs: Any):
    """가짜 릴레이를 **시험 프로세스 안에서** 띄운다(고아 프로세스 0).

    ★별도 프로세스를 안 쓰는 이유: 워커 지침 §1(서버 최소화·생명주기 강제 종료).
      스레드로 띄우면 이 컨텍스트를 나가는 순간 반드시 죽는다.
    """
    relay = relay or FakeRelay(**kwargs)
    handler = type("_BoundHandler", (_Handler,), {"relay": relay})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", relay
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
