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


def run(*, store: Any, spool: Any, cursor: Cursor, ledger: Any = None,
        interval: int = 60, once: bool = False, sleep: Any = None,
        emit: Any = None, reconcile_every: int | None = None) -> dict[str, Any]:
    """폴링 루프 — 한 줄씩 **곧바로 흘려보낸다**(Monitor 연동 · 설계 §S5).

    ★출력은 **한 줄이 한 사건**이고 즉시 flush 한다. 모아서 내보내면 감시하는 쪽에서는
      아무 일도 안 일어나는 것처럼 보이다가 한꺼번에 쏟아진다 — spool 이 막으려던 그 현상이다.

    ★`reconcile` 은 **매 주기가 아니라 N 회마다** 돈다(기본 `RECONCILE_EVERY`=20 · master 결정
      2026-08-25). 삭제 검사는 스레드의 전 페이지를 읽으므로 watch 가 아끼려던 비용을 다시 쓴다
      (S4-2 실측). 그렇다고 아예 안 돌면 tombstone 은 영영 안 잡힌다 — 그래서 주기로 둔다.

    ★`once` 는 시험을 위한 것이 아니라 **운영을 위한 것**이기도 하다(cron 으로 한 번씩 돌리는 방식).
      그래서 예외가 아니라 계약의 일부로 둔다.
    """
    from agora import reconcile as rec
    every = rec.RECONCILE_EVERY if reconcile_every is None else reconcile_every
    out = emit or _emit
    napper = sleep or _sleep
    rounds = 0
    totals = {"new": 0, "duplicates": 0, "reconciled": 0, "tombstoned": 0}
    while True:
        rounds += 1
        result = poll_once(store=store, spool=spool, cursor=cursor)
        totals["new"] += result["new"]
        totals["duplicates"] += result["duplicates"]
        for event in result["events"]:
            out(format_line(event))
        if ledger is not None and every and rounds % every == 0:
            for thread_id in _threads_seen(spool):
                verdict = rec.reconcile(store=store, ledger=ledger, thread_id=thread_id,
                                        spool=spool)
                totals["reconciled"] += 1
                totals["tombstoned"] += len(verdict["tombstoned"])
                for row in verdict["tombstoned"]:
                    out(f"[agora tombstone] {row['message_id']} · {thread_id}")
        if once:
            return {"rounds": rounds, "delivery": DELIVERY, **totals}
        napper(interval)


def _threads_seen(spool: Any) -> list[str]:
    """spool 이 아는 스레드들 — 대조 대상은 **우리가 실제로 받은 것**뿐이다."""
    seen = {row.get("thread_id") for row in spool.state().values()}
    return sorted(t for t in seen if t)


def _emit(line: str) -> None:
    import sys
    print(line, flush=True)      # ★버퍼에 두지 않는다 — 감시자는 줄 단위로 읽는다
    sys.stdout.flush()


def _sleep(seconds: int) -> None:
    import time
    time.sleep(seconds)


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
