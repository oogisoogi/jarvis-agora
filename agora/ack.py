"""ack — 수신 영수증(설계 §5 H-11 · §8 FR-15 · S5-3).

★**「수신 증거 없는 메시지는 존재하지 않는다」**(§8 위협표 「자기생성 고스트」).
  그래서 이 파일의 첫 번째 일은 영수증을 **쓰는** 것이 아니라 **못 쓰게 막는** 것이다 —
  받은 적 없는 message_id 로 영수증이 써지면, 원장은 「받았다고 적혀 있으니 받았다」는
  자기참조가 된다. 그 순간 원장은 증거가 아니라 **주장**이다.

★**전달됨 ≠ 소비됨**(§8 FR-15 · S5-1 이 계수로 갈라 둔 것). 이 파일은 그 두 사건을
  각각 다른 행으로 남긴다:
      `deliver()` → spool `delivered` + 원장 `recv/delivered`   … 「건넸다」
      `ack()`     → spool `acked`     + 원장 `recv/acked`       … 「소비했다」
  뭉치면 받아 놓고 아무도 안 읽은 것이 수신 증거로 계상된다.

★**앞 단이 뒤 단을 대신 막아 주지 않는다** — 이 슬라이스에서 실제로 확인한 것:
  `spool.record` 의 가드는 **뒤로 가는** 전이만 막는다. `fetched → acked` 는 **앞으로 가는**
  전이라 spool 이 **통과시킨다.** 그러므로 「건네지 않은 것을 소비했다고 적지 않는다」는
  **이 층이** 잡아야 한다. 시험도 그 사실(= spool 은 허용한다)을 함께 단언한다.

★**두 번 와도 영수증은 한 장이다.** 운반은 at-least-once 이고(§D5) 사람도 다시 부른다.
  원장은 append-only 라 지울 수 없으니 **쓰기 전에** 막는다.

★ack 를 **누가** 부르는가(K-2 · 설계 §D5 주): 수신 워커가 아니라 **참가 master 세션**이다.
  수신 워커는 무도구·읽기 전용이라 이 도구가 **손에 닿지 않는다**(노출표 = `cli.ROLE_TOOLS`).
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from agora import errors, spool as spool_mod
from agora.errors import AgoraError

DIRECTION = "recv"


def _event_path(ledger: Any, thread_id: str, message_id: str) -> str:
    return os.path.join(ledger.events_dir, thread_id, message_id + ".json")


def _read_event_raw(ledger: Any, thread_id: str, message_id: str) -> bytes | None:
    """보관된 **원문**을 읽는다. 없으면 None — 「받은 적 없다」의 근거다."""
    try:
        with open(_event_path(ledger, thread_id, message_id), "rb") as fh:
            return fh.read()
    except OSError:
        return None


def deliver(*, ledger: Any, spool: Any, node_id: str, thread_id: str,
            message_id: str, raw: bytes) -> dict[str, Any]:
    """받은 것을 **건넸다**고 적는다 — 원문 보관 + spool `delivered` + 원장 행.

    ★원문을 여기서 보관하는 이유: 운반층은 댓글을 고치고 지운다(§D1). 나중에 「무엇을
      받았다고 했는가」를 물을 수 있어야 영수증이 부인 방지가 된다. 해시만 남기면
      그 해시가 무엇의 해시였는지 아무도 못 댄다.
    """
    ledger.store_event(thread_id, message_id, raw)
    spool.record(node_id=node_id, stage=spool_mod.DELIVERED,
                 thread_id=thread_id, message_id=message_id)
    row = None
    if not ledger.has(message_id, direction=DIRECTION, stage=spool_mod.DELIVERED):
        row = ledger.append(direction=DIRECTION, message_id=message_id,
                            event_hash=hashlib.sha256(raw).hexdigest(),
                            stage=spool_mod.DELIVERED, node_id=node_id)
    return {"message_id": message_id, "node_id": node_id, "ledger_row": row}


def ack(*, ledger: Any, spool: Any, message_id: str) -> dict[str, Any]:
    """`agora.ack` 코어(§4) — 소비 영수증을 원장에 남긴다.

    막는 것이 셋이고, **셋 다 이 층의 일이다**:
      ⑴ spool 에 그 message_id 가 **없다** → 받은 적 없는 것이다(code 2).
      ⑵ 단계가 아직 `delivered` 에 **못 미친다** → 건네지 않은 것을 소비할 수 없다(code 2).
         ★spool 은 이것을 안 막는다(`fetched → acked` 는 앞으로 가는 전이다).
      ⑶ 보관된 **원문이 없다** → 무엇을 받았는지 못 대는 영수증은 영수증이 아니다(code 2).
    """
    row = spool.by_message(message_id)
    if row is None:
        raise AgoraError(errors.PRECONDITION, "받은 적 없는 메시지는 ack 하지 않는다",
                         {"reason": "not_received", "message_id": message_id})
    if row.get("stage") not in (spool_mod.DELIVERED, spool_mod.ACKED):
        raise AgoraError(errors.PRECONDITION, "건네지 않은 것을 소비할 수 없다",
                         {"reason": "not_delivered", "message_id": message_id,
                          "stage": row.get("stage")})
    thread_id = row.get("thread_id")
    raw = _read_event_raw(ledger, thread_id, message_id) if thread_id else None
    if raw is None:
        raise AgoraError(errors.PRECONDITION, "보관된 원문이 없다 — 무엇을 받았는지 못 댄다",
                         {"reason": "event_not_stored", "message_id": message_id,
                          "thread_id": thread_id})

    receipt = None
    if not ledger.has(message_id, direction=DIRECTION, stage=spool_mod.ACKED):
        receipt = ledger.append(direction=DIRECTION, message_id=message_id,
                                event_hash=hashlib.sha256(raw).hexdigest(),
                                stage=spool_mod.ACKED, node_id=row.get("node_id"))
        # ★원장 다음에 spool 을 민다. 순서가 뒤집히면 「소비했다고 spool 엔 적혔는데
        #   영수증은 없는」 상태가 남고, 그 차이는 계수로 안 보인다(둘 다 acked 로 세니까).
        spool.record(node_id=row["node_id"], stage=spool_mod.ACKED,
                     thread_id=thread_id, message_id=message_id)
    return {"message_id": message_id, "node_id": row.get("node_id"),
            "thread_id": thread_id, "receipt": receipt,
            "already_acked": receipt is None, "counts": receipts(spool=spool)}


def receipts(*, spool: Any) -> dict[str, int]:
    """「받았다 · 건넸다 · 소비했다」를 **계수로** 갈라 준다(§8 FR-15).

    ★한 숫자로 뭉치지 않는다. 뭉치면 「받아 놓고 아무도 안 읽은 것」이 수신 증거가 된다.
    """
    return {stage: len(spool.pending(stage)) for stage in spool_mod.STAGES}
