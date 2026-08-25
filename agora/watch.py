"""watch — 바뀐 것을 골라 읽고, 받은 것을 spool 에 남긴다(설계 §D5 · S5-2).

★**at-least-once 다.** 같은 이벤트가 두 번 올 수 있다. 그것을 막는 것은 `node_id` dedupe 이고,
  그래서 이 파일도 출력도 **exactly-once 라고 적지 않는다.**
  「한 번만 온다」고 적으면 읽는 쪽이 중복 처리를 안 만들고, 언젠가 두 번 왔을 때 조용히 틀린다.

★**목록으로 고르고 그것만 읽는다**(S4-2 실측이 건 제약). 매 주기 전 스레드를 읽으면
  참가자 한 명만으로도 시간당 한도를 넘는다(60×100 = 6000 > 5000 · docs/COST-MODEL.md).

★재시작 시 **겹쳐서** 다시 묻는다(overlap). 마지막으로 본 시각을 그대로 쓰면
  그 경계에 걸친 글이 영영 안 온다 — 시계 오차·같은 초에 여러 건이면 실제로 난다.
  겹쳐 물어 **중복이 생기는 것은 정상**이고, 그 중복은 dedupe 가 지운다.
  ⇒ 「겹쳐 묻기 + dedupe」가 한 벌이다. 하나만 두면 누락이거나 중복이다.
"""

from __future__ import annotations

import json
import os
from typing import Any

from agora import spool as spool_mod
from agora.event import parse_post

DELIVERY = "at-least-once"          # ★문서·출력이 인용하는 한 곳
OVERLAP_SECONDS = 120


class Cursor:
    """마지막으로 본 시각. **디스크에 남는다** — 재시작이 이어지려면 기억이 밖에 있어야 한다."""

    def __init__(self, directory: str) -> None:
        self.path = os.path.join(directory, "watch-cursor.json")

    def read(self) -> str | None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                return (json.load(fh) or {}).get("seen_until")
        except (OSError, ValueError):
            return None

    def write(self, seen_until: str) -> None:
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"seen_until": seen_until, "delivery": DELIVERY}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)


def _minus_overlap(ts: str | None, seconds: int) -> str | None:
    """마지막으로 본 시각에서 **뒤로 물러난** 시각. 경계에 걸친 글을 놓치지 않으려고."""
    if not ts:
        return None
    from datetime import datetime, timedelta
    try:
        moment = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment - timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def poll_once(*, store: Any, spool: Any, cursor: Cursor,
              overlap_seconds: int = OVERLAP_SECONDS) -> dict[str, Any]:
    """한 주기 — 목록에서 바뀐 것을 고르고, 그것만 읽고, 새 것만 spool 에 남긴다."""
    seen_until = cursor.read()
    since = _minus_overlap(seen_until, overlap_seconds)

    listed = store.list_threads(updated_since=since)["items"]
    new_events: list[dict[str, Any]] = []
    duplicates = 0
    latest = seen_until or ""

    for row in listed:
        latest = max(latest, row.get("updated_at") or "")
        page = store.fetch(number=row["number"])
        for item in page["items"]:
            node_id = item.get("node_id")
            if not node_id:
                continue
            if spool.seen(node_id):
                # ★겹쳐 물었으니 나오는 것이 정상이다. 조용히 지나가되 **센다** —
                #   0 이 아닌 값이 보여야 겹치기가 실제로 돌고 있다는 것을 안다.
                duplicates += 1
                continue
            spool.record(node_id=node_id, stage=spool_mod.FETCHED,
                         thread_id=item.get("thread_id"))
            new_events.append({"node_id": node_id, "number": row["number"],
                               "created_at": item.get("created_at"),
                               "summary": _summarize(item.get("body") or "")})

    if latest:
        cursor.write(latest)
    return {"delivery": DELIVERY, "listed": len(listed), "new": len(new_events),
            "duplicates": duplicates, "events": new_events}


def _summarize(body: str) -> dict[str, Any]:
    """한 줄 출력을 위한 최소 정보. **본문을 해석하지 않는다**(§5 「글은 데이터」).

    ★서식이 아니면 그렇다고만 적는다 — watch 가 판정하는 자리가 아니다(판정은 reducer).
    """
    try:
        parsed = parse_post(body)
    except Exception:      # noqa: BLE001 — 어떤 이유든 여기서는 「우리 것이 아니다」로 족하다
        return {"parsed": False}
    event = parsed["event"]
    return {"parsed": True, "kind": event.get("kind"), "from": event.get("from"),
            "thread_id": event.get("thread_id"),
            "message_id": event.get("message_id"),
            "signed": parsed["signature"] is not None}


def format_line(event: dict[str, Any]) -> str:
    """사람이 보는 한 줄. **전달 보장을 여기에도 적는다** — 출력만 보는 사람이 있다."""
    s = event["summary"]
    who = s.get("from", "?") if s.get("parsed") else "(서식 아님)"
    kind = s.get("kind", "?") if s.get("parsed") else "-"
    return (f"[agora {DELIVERY}] #{event['number']} {kind} · {who} · "
            f"{event['created_at']} · {event['node_id']}")
