"""reducer 1단 — 검증 파이프와 격리 목록(설계 §2-3 ①).

운반층은 **비신뢰**다(§D1·H-2·H-4). 웹 댓글·직접 API 쓰기·구버전 클라이언트·재게시가
전부 같은 통로로 들어온다. 그러니 이 파일이 대답할 질문은 하나다:
**「읽어 온 것 중 무엇을 상태 계산에 넣어도 되는가」.**

★무효는 **지우지 않는다. 격리한다.** 지우면 「없었던 일」이 되어 사고를 재구성할 수 없고,
  삭제야말로 운반층이 이미 할 수 있는 일이다. 우리가 더할 수 있는 것은 **보이게 하는 것**뿐이다.
  그래서 격리 목록은 기본 화면에서 숨되(§3-1) `--audit` 에서 전부 드러난다.

★이 파일은 **정렬·경합 판정(§2-3 ②)도, 상태 전이(§2-3 ③)도 하지 않는다** — S2-3·S2-4 의 몫이다.
  경계를 그어 두지 않으면 「걸러졌다」와 「졌다」가 한 목록에서 섞여, 나중에 둘을 못 가른다.
"""

from __future__ import annotations

import hashlib
from typing import Any

from agora import errors, schema, sign
from agora.errors import AgoraError
from agora.event import parse_post

# 격리 사유 — 이 목록이 전부다. 새 사유를 만들면 여기에 이름을 먼저 준다.
UNPARSEABLE = "unparseable"        # 우리 서식이 아니다(웹에서 손으로 쓴 글 포함)
OVERSIZE = "oversize"              # 크기 상한 초과
SCHEMA = "schema"                  # 서식은 맞는데 계약 밖(모양·정책)
THREAD_MISMATCH = "thread_mismatch"  # 다른 스레드의 이벤트를 여기 붙였다
SIGNATURE = "signature"            # 서명 없음·BAD·명부 밖·폐기 키
REPLAY = "replay"                  # (from, message_id) 재게시

REASONS = (UNPARSEABLE, OVERSIZE, SCHEMA, THREAD_MISMATCH, SIGNATURE, REPLAY)


def _order_key(item: dict[str, Any]) -> tuple[str, str]:
    """수집 순서를 고정한다 — `createdAt` → `node_id` 사전순(§2-3 ②의 그 규칙).

    ★여기서 이 규칙을 쓰는 이유는 **경합을 판정하기 위해서가 아니라**, 재게시 중
      「어느 것이 먼저 온 것인가」를 노드마다 같게 정하기 위해서다. 순서가 흔들리면
      같은 입력에서 격리되는 쪽이 바뀌고, 그러면 노드마다 다른 사실을 갖게 된다.
      경합 판정 자체는 S2-3 이다.
    """
    return (str(item.get("created_at") or ""), str(item.get("node_id") or ""))


def fetch_all(store: Any, thread_id: str, *, limit: int = 100,
              max_pages: int = 1000) -> list[dict[str, Any]]:
    """cursor 를 끝까지 따라가 후보 전건을 모은다.

    ★한 페이지만 읽고 마는 코드가 가장 흔한 조용한 결손이다 — 화면은 정상으로 보이고
      상태만 틀린다. 그래서 페이지 순회는 reducer 쪽에 두고 시험 대상으로 삼는다.
    """
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(max_pages):
        page = store.fetch(thread_id=thread_id, cursor=cursor, limit=limit)
        rows.extend(page.get("items") or [])
        cursor = page.get("next_cursor")
        if not cursor:
            return rows
    raise AgoraError(errors.STORE, "페이지가 끝나지 않는다", {"pages": max_pages})


def collect(*, store: Any, thread_id: str, allowed_signers_path: str,
            revoked_path: str | None = None, roster_checkpoint: str | None = None,
            limit: int = 100) -> dict[str, Any]:
    """검증 파이프. 유효 목록과 격리 목록을 가른다(상태는 계산하지 않는다)."""
    rows = sorted(fetch_all(store, thread_id, limit=limit), key=_order_key)

    valid: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def drop(row: dict[str, Any], reason: str, detail: Any = None) -> None:
        quarantined.append({"node_id": row.get("node_id"),
                            "created_at": row.get("created_at"),
                            "reason": reason, "detail": detail})

    for row in rows:
        # ⑴ 서식 — 우리 서식이 아니면 여기서 끝난다.
        try:
            parsed = parse_post(row.get("body") or "")
        except AgoraError as e:
            drop(row, OVERSIZE if e.code == errors.GATE_REJECT else UNPARSEABLE,
                 {"code": e.code, "message": e.message})
            continue

        event = parsed["event"]

        # ⑵ 계약(모양·정책) — S2-1 의 닫힌 스키마를 그대로 쓴다.
        try:
            schema.validate(event)
        except AgoraError as e:
            drop(row, SCHEMA, {"code": e.code, "message": e.message, "at": e.detail})
            continue

        # ⑶ 스레드 결박 — 다른 스레드의 **유효한** 이벤트도 여기서는 무효다(§2-1).
        if event["thread_id"] != thread_id:
            drop(row, THREAD_MISMATCH,
                 {"event_thread_id": event["thread_id"], "asked": thread_id})
            continue

        # ⑷ 서명·명부·폐기 — 세 판정(ok/BAD/unsigned)을 그대로 받는다.
        verdict = sign.verify_detail(parsed["raw"], parsed["signature"],
                                     event["from"], allowed_signers_path, revoked_path)
        if verdict["verdict"] != sign.OK:
            drop(row, SIGNATURE, {"verdict": verdict["verdict"], "why": verdict["reason"]})
            continue

        # ⑸ 재게시 — 같은 (from, message_id) 는 한 번만이다.
        key = (event["from"], event["message_id"])
        if key in seen:
            drop(row, REPLAY, {"from": key[0], "message_id": key[1]})
            continue
        seen.add(key)

        valid.append({
            "node_id": row.get("node_id"), "created_at": row.get("created_at"),
            "event": event, "raw": parsed["raw"],
            # 체인은 이 해시로 이어진다(§2-1) — 다음 이벤트의 `prev` 가 이 값을 가리킨다.
            "hash": hashlib.sha256(parsed["raw"]).hexdigest(),
            "kind": event["kind"], "from": event["from"],
            "message_id": event["message_id"], "prev": event["prev"],
            "fingerprint": verdict.get("fingerprint"),
            # ★명부는 시간에 따라 바뀐다. 「그때의 명부」와 「지금 명부」가 다르면 표시만 한다 —
            #   서명 자체는 지금 명부로 검증됐고, 과거 명부 복원은 체크포인트(S5·S7)의 몫이다.
            "roster_stale": (roster_checkpoint is not None
                             and event["roster"] != roster_checkpoint),
        })

    return {"thread_id": thread_id, "fetched": len(rows),
            "valid": valid, "quarantined": quarantined}


def read_view(collected: dict[str, Any], *, state: Any, audit: bool = False) -> dict[str, Any]:
    """`agora.read` 가 돌려줄 모양(§4) — 격리는 `audit` 에서만 드러난다(§3-1).

    ★숨기는 것과 지우는 것은 다르다. 여기서 하는 일은 **기본 화면에서 빼는 것**뿐이고,
      원본은 운반층에도 `collected` 에도 그대로 있다.
    """
    view: dict[str, Any] = {
        "state": state,
        "events": [{"message_id": v["message_id"], "kind": v["kind"], "from": v["from"],
                    "ts": v["event"]["ts"], "sig": "ok",
                    "body": v["event"]["payload"].get("body")}
                   for v in collected["valid"]],
    }
    if audit:
        view["quarantined"] = list(collected["quarantined"])
    return view


# ── 2단: 정렬·경합(설계 §2-3 ②) ─────────────────────────────────────────────
# 유효 이벤트들은 `prev` 로 이어진 **사슬**을 이룬다. 그런데 두 참가자가 같은 순간에
# 같은 `prev` 를 보고 글을 쓰면 사슬이 갈라진다 — 그것이 경합이다.
#
# ★경합에서 진 것은 **격리가 아니다.** 격리는 「자격이 없다」(서명·계약·결박)이고,
#   stale 은 「자격은 있는데 졌다」이다. 둘을 한 목록에 섞으면 나중에
#   「이 사람 글이 왜 안 보이나」에 답할 수 없다 — 그래서 목록을 갈라 둔다.

LOST_RACE = "lost_race"      # 같은 prev 를 두고 겨뤄서 졌다
UNREACHABLE = "unreachable"  # 가리키는 prev 가 사슬에 없다(진 쪽의 후손·부모가 격리됨)


def _winner_key(entry: dict[str, Any]) -> tuple[str, str]:
    """승자 규칙(§2-3 ②) — `createdAt` 이 이르면 이긴다. 동률이면 `node_id` 사전순.

    ★동률 규칙이 **꼭 필요하다.** 운반층 시각은 초 단위로 뭉치고, 시각만으로 고르면
      「목록에 먼저 담긴 것」이 이긴다 — 그건 페이지가 오는 순서에 따라 달라진다.
      노드마다 다른 승자를 뽑는 순간 두 노드는 서로 다른 사실을 갖게 된다.
    """
    return (str(entry.get("created_at") or ""), str(entry.get("node_id") or ""))


def order(collected: dict[str, Any]) -> dict[str, Any]:
    """유효 목록 → 사슬 + 진 것 + 닿지 않는 것.

    ★여기서 **상태를 계산하지 않는다**(§2-3 ③ = S2-4). 그리고 `expected_state` 도 아직 안 본다 —
      비교 대상인 상태 해시가 S2-4 에서 생긴다. 없는 것을 있는 척 비교하면 그 순간부터
      「검사했다」는 거짓이 스위트에 초록으로 박힌다. 그 칸은 S2-4 에서 채운다.
    """
    from agora.contract_open import GENESIS_PREV

    by_prev: dict[str, list[dict[str, Any]]] = {}
    for entry in collected["valid"]:
        by_prev.setdefault(entry["prev"], []).append(entry)

    chain: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    key = GENESIS_PREV
    while True:
        candidates = by_prev.get(key) or []
        if not candidates:
            break
        winner = min(candidates, key=_winner_key)
        for loser in candidates:
            if loser is winner:
                continue
            stale.append({"node_id": loser["node_id"], "message_id": loser["message_id"],
                          "from": loser["from"], "kind": loser["kind"],
                          "reason": LOST_RACE, "winner_node_id": winner["node_id"]})
        chain.append(winner)
        seen_hashes.add(winner["hash"])
        if winner["hash"] == key:
            # 자기 자신을 가리키는 사슬 — 무한 순회를 막는다(운반층은 무엇이든 실어 온다).
            break
        key = winner["hash"]

    lost_nodes = {s["node_id"] for s in stale}
    unreachable = [
        {"node_id": e["node_id"], "message_id": e["message_id"], "from": e["from"],
         "kind": e["kind"], "reason": UNREACHABLE, "prev": e["prev"]}
        for e in collected["valid"]
        if e["hash"] not in seen_hashes and e["node_id"] not in lost_nodes
    ]

    return {"thread_id": collected["thread_id"], "chain": chain,
            "stale": stale + unreachable,
            # 격리는 건드리지 않는다 — 다른 사건이므로 다른 목록으로 그대로 통과시킨다.
            "quarantined": collected["quarantined"]}
