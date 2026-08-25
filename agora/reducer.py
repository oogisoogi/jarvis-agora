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

from agora import errors, protocol, schema, sign
from agora.errors import AgoraError
from agora.event import parse_post

# 격리 사유 — 이 목록이 전부다. 새 사유를 만들면 여기에 이름을 먼저 준다.
UNPARSEABLE = "unparseable"        # 우리 서식이 아니다(웹에서 손으로 쓴 글 포함)
OVERSIZE = "oversize"              # 크기 상한 초과
SCHEMA = "schema"                  # 서식은 맞는데 계약 밖(모양·정책)
THREAD_MISMATCH = "thread_mismatch"  # 다른 스레드의 이벤트를 여기 붙였다
SIGNATURE = "signature"            # 서명 없음·BAD·명부 밖·폐기 키
REPLAY = "replay"                  # (from, message_id) 재게시

# 3단(전이) 에서 붙는 사유 — 「자격」이 아니라 「절차」에서 걸린 것들이다.
OUT_OF_ROUND = "out_of_round"          # 지금 라운드의 발언이 아니다
COUNTER_REQUIRED = "counter_required"  # R2 발언인데 반론 대상이 없다
PERMISSION = "permission"              # 의장·요청자·운영자가 아닌데 그 권한의 이벤트를 냈다
KIND_NOT_ALLOWED = "kind_not_allowed"  # 이 유형의 스레드가 받지 않는 kind
BAD_TRANSITION = "bad_transition"      # 지금 상태에서 갈 수 없는 자리
UNKNOWN_TARGET = "unknown_target"      # 가리키는 이벤트가 사슬에 없다
BUDGET_EXCEEDED = "budget_exceeded"    # 라운드당 발언 예산을 넘겼다
AFTER_CLOSE = "after_close"            # 닫힌 뒤에 온 이벤트

REASONS = (UNPARSEABLE, OVERSIZE, SCHEMA, THREAD_MISMATCH, SIGNATURE, REPLAY,
           OUT_OF_ROUND, COUNTER_REQUIRED, PERMISSION, KIND_NOT_ALLOWED,
           BAD_TRANSITION, UNKNOWN_TARGET, AFTER_CLOSE, BUDGET_EXCEEDED)


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
            scrub_bundle: str | None = None, limit: int = 100) -> dict[str, Any]:
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
            # ★§8 재검사 플래그 — 발신자가 **다른 규칙 묶음**으로 걸렀다고 주장한다.
            #   거부가 아니다: 판본이 다를 뿐일 수 있다. 수신 측이 **자기 규칙으로 다시 재라**는 표시다.
            "scrub_recheck": (scrub_bundle is not None
                              and event["scrub"].get("rules") != scrub_bundle),
        })

    return {"thread_id": thread_id, "fetched": len(rows),
            "valid": valid, "quarantined": quarantined}


PROCEDURAL_FIELDS = ("type", "state", "round", "chair", "requester", "solved_by",
                     "close_reason")


def procedure_snapshot(reduced: dict[str, Any]) -> dict[str, Any]:
    """**절차만** 떼어 본 상태(§2-1b 불변식용).

    ★관계 필드(parent·refs·spawn)는 절차를 바꾸지 않아야 한다. 그것을 재려면
      「사슬의 바이트」가 아니라 「절차 칸」을 비교해야 한다 — 관계를 더하면 이벤트 바이트가
      달라지므로 `state_hash` 는 **당연히** 달라진다(그 안에 사슬의 머리가 들어 있다).
      두 질문을 한 값으로 답하려 하면 둘 중 하나는 반드시 거짓말이 된다.
    """
    return {k: reduced.get(k) for k in PROCEDURAL_FIELDS}


def links_of(reduced: dict[str, Any], *,
             known_threads: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """이 스레드가 가리키는 관계 링크 목록 — 해소 여부를 함께 준다(§2-1b · AC ④).

    ★없는 스레드를 가리키는 것은 **오류가 아니다.** 아직 안 열린 스레드를 가리킬 수 있다.
      그래서 거부하지 않고 `resolved: false` 로 표시만 한다.
    """
    out: list[dict[str, Any]] = []
    for entry in reduced.get("events") or []:
        payload = entry["event"]["payload"]
        found: list[tuple[str, dict[str, Any]]] = []
        if entry["kind"] == "genesis" and payload.get("parent"):
            found.append(("parent", payload["parent"]))
        for ref in payload.get("refs") or []:
            found.append(("ref", ref))
        for role, link in found:
            out.append({"role": role, "from_message_id": entry["message_id"],
                        "thread_id": link["thread_id"],
                        "message_id": link.get("message_id"),
                        "why": link.get("why"),
                        "resolved": link["thread_id"] in known_threads})
    return out


def read_view(collected: dict[str, Any], *, state: Any, audit: bool = False,
              accepted: list[dict[str, Any]] | None = None,
              quarantined: list[dict[str, Any]] | None = None,
              stale: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`agora.read` 가 돌려줄 모양(§4) — 격리는 `audit` 에서만 드러난다(§3-1).

    ★숨기는 것과 지우는 것은 다르다. 여기서 하는 일은 **기본 화면에서 빼는 것**뿐이고,
      원본은 운반층에도 `collected` 에도 그대로 있다.

    ★★**`accepted`·`quarantined` 를 받는 이유**(S7-2 실물에서 드러난 결함):
      `collected` 는 **1단**(서명·계약)만 통과한 것이다. 절차 단계(권한·라운드·상태)에서
      거부된 이벤트는 그 목록에 **여전히 「유효」로 들어 있다.** 그대로 보여 주면
      ⑴사용자는 자기 글이 **반영됐다고 오해**하고 ⑵`audit` 을 켜도 **거부 사유가 안 보인다**
      (수집 격리만 실리므로). 그래서 2단 결과를 함께 받아 **실제로 받아들여진 것**을 싣는다.
      ⚠안 넘기면 옛 동작(1단 기준)이다 — 호출자는 넘기는 쪽이 맞다.
    """
    source = accepted if accepted is not None else collected["valid"]
    view: dict[str, Any] = {
        "state": state,
        "events": [{"message_id": v["message_id"], "kind": v["kind"], "from": v["from"],
                    "ts": v["event"]["ts"], "sig": "ok",
                    "body": v["event"]["payload"].get("body")}
                   for v in source],
    }
    if audit:
        view["quarantined"] = list(collected["quarantined"] if quarantined is None
                                   else quarantined)
        # ★★**진 글도 보여 준다**(2026-08-26 실물에서 드러났다). 격리와 stale 은 다른 사건이라
        #   목록을 갈라 뒀는데, `read` 는 **둘 중 하나만** 실었다 — 그래서 경합에서 진 글은
        #   `audit` 을 켜도 **아무 데도 안 나왔다.** 쓴 사람 화면에는 rc 0 과 URL 이 찍히고,
        #   글은 영영 안 보이며, 왜인지 물을 자리가 없다. 그것이 이 저장소가 쫓는 바로 그 형태다.
        view["stale"] = list(stale or [])
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


# ── S2-5: 마감·만료·의장 승계(설계 §6 · §2-3 ④) ─────────────────────────────
# ★**이벤트가 시간을 이긴다(R-3).** 시간 전이는 이벤트가 **없을 때만** 발동하는 보조 규칙이다.
#   반대로 두면 노드 시계가 조금만 어긋나도 「어떤 노드에서는 만료, 어떤 노드에서는 진행」이 되고,
#   그 순간 두 노드는 서로 다른 사실을 갖는다.
#
# ★시각은 **주입받는다.** 프로세스의 현재 시각을 몰래 읽으면 같은 이벤트 묶음이
#   실행할 때마다 다른 상태를 내고, 그것은 재현할 수 없는 판정이 된다.

EXPIRED = "expired"
DEBATE_ROUNDS = ("r0", "r1", "r2", "r3")


def _parse_ts(value: str, where: str) -> Any:
    from datetime import datetime
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise AgoraError(errors.ARGUMENT, "시각 형식이 아니다",
                         {"where": where, "value": str(value)[:40]}) from None


def is_expired_now(gtype: str, state_name: str, deadlines: dict[str, Any],
                   now: str | None) -> bool:
    """지금 이 순간 이 스레드가 만료 상태인가 — **한 곳에서만** 답한다.

    ★루프 안(운영자 위임이 열리는가)과 루프 뒤(최종 상태)가 같은 질문을 한다.
      두 곳에 따로 적으면 「위임은 받았는데 상태는 만료가 아닌」 어긋난 판정이 나온다.
    """
    if gtype != "debate" or not now or state_name not in DEBATE_ROUNDS:
        return False
    due = deadlines.get(state_name)
    return bool(due and deadline_passed(due, now))


def deadline_passed(deadline: str, now: str, *, grace_seconds: int | None = None) -> bool:
    """마감이 지났는가 — 유예를 더한 뒤에 본다(§2-3 ④).

    ★유예(기본 300초)는 노드 시계 오차를 흡수한다. 유예가 없으면 시계가 몇 초 빠른 노드가
      혼자 먼저 만료를 선언하고, 그 노드만 다른 상태를 갖게 된다.
    """
    from datetime import timedelta
    from agora.contract_open import EXPIRED_GRACE_SECONDS
    grace = EXPIRED_GRACE_SECONDS if grace_seconds is None else grace_seconds
    return _parse_ts(now, "now") > _parse_ts(deadline, "deadline") + timedelta(seconds=grace)


# ── 3단: 유형별 전이(설계 §6 · §2-3 ③) ──────────────────────────────────────
# 유형은 「내용의 벽」이 아니라 **절차**다(§2-1b). 그래서 유형마다 받는 kind 가 다르고,
# 같은 kind 라도 낼 수 있는 사람이 다르다.
#
# ★표를 **닫아** 둔다. 「모르는 kind 는 그냥 지나가게」 두면 유형 경계가 서서히 녹는다.

# 유형 → 그 유형이 받는 kind(§6). vote 는 구속력이 없지만(M-7) 어디서나 낼 수 있다.
ALLOWED_KINDS: dict[str, frozenset[str]] = {
    "problem": frozenset({"post", "answer_selected", "close", "vote", "abort"}),
    "knowhow": frozenset({"post", "close", "vote", "abort"}),
    "debate": frozenset({"post", "advance", "resolution", "close", "delegate_chair",
                         "vote", "abort"}),
}

# S2-5 에서 실제 전이를 갖게 됐다(승계·중단). 그래서 이 집합은 이제 **비어 있는 것이 정상**이다 —
# 칸은 남겨 둔다: 다음에 또 「받되 계산 안 하는」 kind 가 생기면 같은 자리에 이름을 남긴다.
# 조용히 무시하면 「받아서 아무 일도 안 일어난 것」과 「아직 안 만든 것」이 구별되지 않는다.
DEFERRED_KINDS: frozenset[str] = frozenset()

KNOWHOW_CLOSE_REASONS = frozenset({"superseded", "archived"})


def require_chair(state: dict[str, Any], participant_id: str) -> None:
    """쓰기 경로의 권한 게이트 — 의장이 아니면 code 5.

    ★읽기 경로(reducer)와 **같은 규칙**을 쓴다. 두 곳에 따로 적으면 언젠가 갈라지고,
      갈라지는 순간 「도구는 막았는데 reducer 는 통과시키는」 무단 결의가 성립한다.
    """
    if participant_id != state.get("chair"):
        raise AgoraError(errors.PERMISSION, "의장만 할 수 있다",
                         {"chair": state.get("chair"), "from": participant_id})


def require_requester(state: dict[str, Any], participant_id: str) -> None:
    """해결 표시는 요청자만(§8 FR-5) — 아니면 code 5."""
    if participant_id != state.get("requester"):
        raise AgoraError(errors.PERMISSION, "요청자만 할 수 있다",
                         {"requester": state.get("requester"), "from": participant_id})


def usage_slot(state: dict[str, Any], participant_id: str) -> str:
    """예산 계수의 **칸 이름** — 누구의, 어느 라운드 예산인가.

    ★두 겹(로컬 사전 검사·reducer 판정)이 **같은 칸**을 봐야 한다. 각자 문자열을 만들면
      어느 날 한쪽만 바뀌고, 그때 로컬 검사는 **남의 칸을 보며 통과**시킨다 —
      그리고 그 어긋남은 예산이 실제로 넘칠 때까지 아무 표시도 내지 않는다.
    """
    if state.get("type") == "debate":
        return f"{participant_id}@r{state.get('round')}"
    return participant_id


def require_state(reduced: dict[str, Any], expected_state: str) -> None:
    """쓰기 경로의 CAS 게이트(§4 code 9) — 내가 본 상태가 지금 상태와 다르면 거부.

    ★재시도 전에 `read` 를 다시 하라는 뜻이다. 이 칸이 없으면 두 사람이 같은 자리에서
      서로 다른 역사를 쓰고, 경합 판정이 그 뒤치다꺼리를 하게 된다 —
      경합은 **막을 수 없는 동시성**을 위한 장치이지, 눈감고 쓴 글을 위한 장치가 아니다.
    """
    now = reduced.get("state_hash")
    if expected_state != now:
        raise AgoraError(errors.STATE_CONFLICT, "상태가 그 사이에 바뀌었다 — read 후 재시도",
                         {"expected_state": expected_state, "now": now})


def _state_hash(state: dict[str, Any]) -> str:
    """상태 해시 — 다음 이벤트의 `expected_state` 가 가리키는 값(§2-1).

    ★사슬의 머리(head)를 넣는다. 안 넣으면 「같은 결론에 이른 서로 다른 역사」가 같은 해시가 되고,
      그러면 CAS 가 놓치는 창이 생긴다.
    """
    from agora.event import canonical_bytes
    snapshot = {k: state.get(k) for k in
                ("type", "state", "round", "chair", "requester", "solved_by",
                 "close_reason", "head")}
    return hashlib.sha256(canonical_bytes(snapshot)).hexdigest()


def apply(ordered: dict[str, Any], *,
          operators: frozenset[str] = frozenset(),
          now: str | None = None,
          budget: dict[str, int] | None = None) -> dict[str, Any]:
    """사슬 → 상태(§6). 절차에서 걸린 것은 사유와 함께 격리 목록에 더한다.

    ⛔여기서도 `expected_state` 는 아직 대조하지 않는다 — 쓰기 경로(CAS)가 생기는 S2-5·S4 의 몫이다.
      상태 해시는 여기서 계산해 두므로, 그때 비교할 값은 이제 존재한다.
    """
    quarantined = list(ordered["quarantined"])
    chain = ordered["chain"]
    if not chain or chain[0]["kind"] != "genesis":
        # genesis 가 없으면 상태가 없다. 「빈 스레드」와 구별되게 이유를 남긴다.
        return {"thread_id": ordered["thread_id"], "state": None,
                "reason": "no_genesis", "events": [], "deferred": [],
                "stale": ordered["stale"], "quarantined": quarantined}

    genesis = chain[0]["event"]
    gtype = genesis["payload"]["type"]
    state: dict[str, Any] = {
        "type": gtype,
        "state": "r0" if gtype == "debate" else "open",
        "round": 0 if gtype == "debate" else None,
        "chair": genesis["payload"].get("chair") or genesis["from"],
        "requester": genesis["from"],
        "solved_by": None,
        "close_reason": None,
        "head": chain[0]["hash"],
    }
    accepted = [chain[0]]
    deferred: list[dict[str, Any]] = []
    post_ids = {chain[0]["message_id"]}
    # 예산은 **설정에서** 온다(§5 · AC ②). 참가자·라운드별로 따로 센다.
    limits = protocol.load_budget() if budget is None else dict(budget)
    deadlines = genesis["payload"].get("deadlines") or {}
    usage: dict[str, dict[str, int]] = {}

    def reject(entry: dict[str, Any], reason: str, detail: Any = None) -> None:
        quarantined.append({"node_id": entry["node_id"],
                            "created_at": entry["created_at"],
                            "reason": reason, "stage": "transition", "detail": detail})
        # ★★**거부돼도 사슬은 지나갔다** — head 를 여기서도 전진시킨다(L-1 · master 결정 2026-08-26 (a)안).
        #   왜: 2단(정렬·경합)은 **거부 여부를 모른 채** `prev` 만 보고 승자를 고른다.
        #   그래서 절차에서 거부된 이벤트도 **경합에서는 이미 이겨 있다.** 그런데 head 가
        #   「받아들인 이벤트」에서만 전진하면, 다음 사람은 그 이긴 이벤트의 **앞자리**를 가리키게 되고
        #   **영원히 진다.** ⇒ 구성원 1명이 이벤트 1건으로 스레드를 **영구 동결**시킬 수 있었다
        #   (실물 #4 에서 실제로 났다 — 발언 3건이 rc 0·URL 을 받고 전부 stale).
        #   ★두 층이 「머리」를 다르게 보면 그 틈이 곧 교착이다. 층을 맞춘다.
        # ⚠상태는 **안 바뀐다**(거부는 여전히 거부다 · 사유는 `read --audit` 에 남는다).
        #   바뀌는 것은 「다음 글이 어디에 붙는가」뿐이다. 그 대가로 거부 이벤트도
        #   `state_hash` 를 흔들어 동시 작성자에게 code 9(재read)를 강제한다 —
        #   그것은 정상 동작이고, 잔여 위험으로 THREAT-MODEL 에 적었다.
        state["head"] = entry["hash"]

    for entry in chain[1:]:
        kind, ev, who = entry["kind"], entry["event"], entry["from"]
        payload = ev["payload"]

        if state["state"] == "closed":
            reject(entry, AFTER_CLOSE, {"kind": kind})
            continue
        if kind not in ALLOWED_KINDS[gtype]:
            reject(entry, KIND_NOT_ALLOWED, {"type": gtype, "kind": kind})
            continue
        if kind in DEFERRED_KINDS:
            deferred.append({"node_id": entry["node_id"], "kind": kind,
                             "why": "마감·만료·승계는 S2-5"})
            accepted.append(entry)
            continue

        if kind == "vote":
            # 구속력 없음(M-7) — 받아 두되 상태를 바꾸지 않는다.
            accepted.append(entry)
            continue

        if kind == "post":
            if gtype == "debate":
                if payload.get("round") != state["round"]:
                    reject(entry, OUT_OF_ROUND,
                           {"post_round": payload.get("round"), "now": state["round"]})
                    continue
                if state["round"] == 2 and not payload.get("counter"):
                    # R2 는 반론 라운드다 — 대상 없는 발언은 라운드의 뜻을 비운다.
                    reject(entry, COUNTER_REQUIRED, {"round": 2})
                    continue
            # ★예산은 **유효 post 만** 센다(R-2). 여기까지 온 것이 유효 post 다 —
            #   경합에서 진 글·무효 글은 애초에 이 사슬에 없다.
            used = usage.setdefault(usage_slot(state, who), {"posts": 0, "chars": 0})
            over = protocol.would_exceed(body=payload.get("body") or "",
                                         used=used, budget=limits)
            if over:
                reject(entry, BUDGET_EXCEEDED, over)
                continue
            used["posts"] += 1
            used["chars"] += len(payload.get("body") or "")
            post_ids.add(entry["message_id"])
            accepted.append(entry)

        elif kind == "advance":
            if who != state["chair"]:
                reject(entry, PERMISSION, {"chair": state["chair"], "from": who})
                continue
            if payload["from_round"] != state["round"]:
                reject(entry, BAD_TRANSITION,
                       {"from_round": payload["from_round"], "now": state["round"]})
                continue
            state["round"] = payload["to_round"]
            state["state"] = DEBATE_ROUNDS[payload["to_round"]]
            accepted.append(entry)

        elif kind == "resolution":
            if who != state["chair"]:
                reject(entry, PERMISSION, {"chair": state["chair"], "from": who})
                continue
            if state["state"] != "r3":
                reject(entry, BAD_TRANSITION, {"now": state["state"], "want": "r3"})
                continue
            state["state"] = "resolved"
            accepted.append(entry)

        elif kind == "answer_selected":
            if who != state["requester"]:
                # 남이 고른 답은 상태를 바꾸지 않는다(§8 FR-5).
                reject(entry, PERMISSION, {"requester": state["requester"], "from": who})
                continue
            if payload["post_message_id"] not in post_ids:
                reject(entry, UNKNOWN_TARGET,
                       {"post_message_id": payload["post_message_id"]})
                continue
            state["state"] = "solved"
            state["solved_by"] = payload["post_message_id"]
            accepted.append(entry)

        elif kind == "close":
            if who not in (state["chair"], state["requester"]) and who not in operators:
                reject(entry, PERMISSION,
                       {"allowed": [state["chair"], state["requester"], "operator"],
                        "from": who})
                continue
            if gtype == "knowhow" and payload["reason"] not in KNOWHOW_CLOSE_REASONS:
                reject(entry, BAD_TRANSITION,
                       {"reason": payload["reason"],
                        "allowed": sorted(KNOWHOW_CLOSE_REASONS)})
                continue
            state["state"] = "closed"
            state["close_reason"] = payload["reason"]
            accepted.append(entry)

        elif kind == "delegate_chair":
            # 의장은 언제나 넘길 수 있다. 운영자는 **만료된 동안만** 대신 넘길 수 있다
            # (설계 §2-2 · 운영자 결정 2026-08-25). 조건이 없으면 운영자가 아무 때나
            # 의장을 갈아치울 수 있어 의장 권한이 형해화된다 — 그래서 조건이 규칙의 절반이다.
            if who != state["chair"]:
                if not (who in operators
                        and is_expired_now(gtype, state["state"], deadlines, now)):
                    reject(entry, PERMISSION,
                           {"chair": state["chair"], "from": who,
                            "operator_needs": "expired"})
                    continue
            state["chair"] = payload["new_chair"]
            accepted.append(entry)

        elif kind == "abort":
            # 운영자 명부(K-3)에 있는 사람만. 목록에서 이름이 빠지면 그 키의 abort 는 죽는다.
            if who not in operators:
                reject(entry, PERMISSION, {"from": who, "need": "operator"})
                continue
            state["state"] = "closed"
            state["close_reason"] = "aborted"
            state["abort_reason"] = payload["reason"]
            accepted.append(entry)

        state["head"] = entry["hash"]

    # ★만료는 **이벤트가 없을 때만** 발동한다. 지금 라운드의 마감만 본다 —
    #   앞 라운드의 마감은 advance 가 이미 지나갔으므로 따질 일이 없다(이벤트가 시간을 이긴다).
    if is_expired_now(gtype, state["state"], deadlines, now):
        state["state"] = EXPIRED

    result = dict(state)
    result.update({"thread_id": ordered["thread_id"],
                   "events": accepted, "deferred": deferred,
                   # NFR-7(K-6) — 쓴 만큼이 남는다. 토큰 단위 사용량은 도구 경계(S6-1)에서 붙는다.
                   "usage": usage, "budget": limits,
                   "stale": ordered["stale"], "quarantined": quarantined})
    result["state_hash"] = _state_hash(state)
    return result
