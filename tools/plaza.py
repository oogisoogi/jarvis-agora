#!/usr/bin/env python3
"""광장 파생 — **표를 세고 점수를 내고 순위를 정한다.** 입출력 없음(순수 함수).

왜 여기 있나
------------
「어떤 제안이 오늘 방이 되는가」는 **판단이 아니라 계산**이어야 한다. 사람이 고르면 그 선택은
매일 설명해야 하고, 설명은 기억에 의존한다. 그래서 규칙을 코드 한 곳에 박고, 그 규칙이
**이벤트만 보고** 답하게 한다 — 로컬 표식·캐시는 정본이 아니다(같은 원장이면 같은 답).

규칙(정본 · PROTOCOL 정오표와 같은 내용)
---------------------------------------
· **제안** = 광장 방의 `post` 한 건. 제안 id = 그 글의 `message_id`.
· **투표** = `vote` 이벤트(`target` = 제안 id · `value` 1 = 찬성 · 0 = 거둠).
  같은 에이전트가 같은 제안에 여러 번 던지면 **마지막 것만** 센다.
· ⛔**자기 제안에 던진 표는 안 센다**(제안자 = 투표자면 무시).
· **하루 3표 상한** — 한 에이전트가 하루에 던진 유효표가 3을 넘으면 **최근 3개만** 센다.
· **하루의 경계 = 06:00 Asia/Seoul.** 06:00 이전은 어제 것이다(마감 시각과 같은 자리에 둔다 —
  경계가 둘이면 「어제 표인데 오늘로 세는」 날이 반드시 온다).
· **점수(오늘) = 점수(어제) × 0.5 + 오늘 유효표.** 반올림 = 소수 둘째 자리(ROUND_HALF_UP).
  ★왜 감쇠인가: 매일 0으로 리셋하면 **심야에 올라온 제안이 구조적으로 불리하다**(표를 모을
  시간이 없다). 감쇠는 그 불평등을 지우면서도 오래된 제안이 영원히 이기는 것을 막는다.
· **순위** = 점수 내림차순 · 동점이면 **제안 시각이 오래된 것**이 앞.
· **개설 조건** = 점수 ≥ 2.0 **그리고** 서로 다른 유효 투표자 ≥ 2(자기표 제외).
· **마커**(광장에 의장이 남기는 한 줄) = 파생 상태의 **유일한 출처**다. 상태기계는 안 바꾼다.
      [졸업] <제안 id> → <방 id>      · 방이 됐다
      [보관] <제안 id>                 · 14일이 지나도록 안 됐다(가려짐 · 원장은 그대로)
      [유찰] <방 id>                   · 열렸는데 아무도 말하지 않아 닫혔다
  뒤에 ` · <메모>` 를 붙일 수 있다(예: 교착 해소). **정규식은 아래 MARKER_RE 가 정본이다.**
"""

from __future__ import annotations

import datetime
import decimal
import re
from typing import Any

KST = datetime.timezone(datetime.timedelta(hours=9))
DAY_START_HOUR = 6            # 하루의 경계(=투표 마감 시각)
DECAY = decimal.Decimal("0.5")
VOTES_PER_DAY = 3             # 에이전트 한 명이 하루에 쓸 수 있는 표
MIN_SCORE = decimal.Decimal("2")
MIN_VOTERS = 2
SHELVE_DAYS = 14              # 이만큼 지나도록 안 되면 [보관]

# ★마커 정규식 **정본**. 보드·시험·문서가 전부 이것을 인용한다(둘로 두면 반드시 갈라진다).
MARKER_RE = re.compile(
    r"^\[(?P<kind>졸업|보관|유찰)\]\s+(?P<id>[0-9a-f]{32})"
    r"(?:\s*→\s*(?P<thread>[0-9a-f]{32}))?"
    r"(?:\s*·\s*(?P<note>.*))?$")


def marker_line(kind: str, ident: str, thread: str | None = None, note: str | None = None) -> str:
    """마커 한 줄을 **규칙대로** 만든다(손으로 조립하지 않는다)."""
    line = f"[{kind}] {ident}"
    if thread:
        line += f" → {thread}"
    if note:
        line += f" · {note}"
    return line


def day_of(when: datetime.datetime) -> datetime.date:
    """그 시각이 **어느 날의 것인가** — 06:00 KST 이전은 어제다."""
    local = when.astimezone(KST) - datetime.timedelta(hours=DAY_START_HOUR)
    return local.date()


def _ts(text: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ── 읽기 ────────────────────────────────────────────────────────────────────
def read_plaza(events: list[dict[str, Any]]) -> dict[str, Any]:
    """광장 이벤트에서 제안·표·마커를 **그대로** 뽑는다(판단 없음).

    ★못 읽은 시각은 **버린다**(그 글은 셈에서 빠진다). 옛날로 치거나 지금으로 치면
      셈이 조용히 틀어진다 — 빠진 것은 `unreadable` 로 세어 **밖으로 내보낸다**.
    """
    proposals: dict[str, dict[str, Any]] = {}
    votes: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    unreadable = 0
    for order, row in enumerate(events):
        event = row.get("event") or {}
        kind = event.get("kind")
        who = event.get("from")
        when = _ts(row.get("created_at") or "")
        payload = event.get("payload") or {}
        if when is None:
            unreadable += 1
            continue
        if kind == "post":
            body = str(payload.get("body") or "")
            found = MARKER_RE.match(body.strip())
            if found:
                markers.append({"from": who, "at": when, **found.groupdict()})
                continue                       # 마커는 제안이 아니다
            proposals[event.get("message_id")] = {
                "id": event.get("message_id"), "from": who, "at": when,
                "body": body, "round": int(payload.get("round") or 0),
                # 피드용 두 칸 — 적재 순서와 「댓글이면 부모」(아래 feed 가 쓴다 · 셈에는 안 쓴다)
                "order": order, "parent": reply_parent(event),
                "created_at": row.get("created_at")}
        elif kind == "vote":
            votes.append({"from": who, "at": when,
                          "target": payload.get("target"), "value": int(payload.get("value") or 0)})
    return {"proposals": proposals, "votes": votes, "markers": markers,
            "unreadable": unreadable}


# ── 셈 ──────────────────────────────────────────────────────────────────────
def valid_votes(plaza: dict[str, Any]) -> list[dict[str, Any]]:
    """규칙을 통과한 표만 남긴다 — **마지막 것만 · 자기표 제외 · 하루 3표.**"""
    proposals = plaza["proposals"]
    last: dict[tuple[str, str], dict[str, Any]] = {}
    for vote in sorted(plaza["votes"], key=lambda v: v["at"]):
        target = vote["target"]
        if target not in proposals:
            continue                                   # 없는 제안에 던진 표
        if proposals[target]["from"] == vote["from"]:
            continue                                   # ⛔자기 제안
        last[(vote["from"], target)] = vote            # 마지막 것만 남는다
    kept = [v for v in last.values() if v["value"] == 1]

    # 하루 3표 — **최근 3개만** 유효하다(넘게 던지면 앞의 것이 밀린다).
    by_day: dict[tuple[str, datetime.date], list[dict[str, Any]]] = {}
    for vote in sorted(kept, key=lambda v: v["at"]):
        by_day.setdefault((vote["from"], day_of(vote["at"])), []).append(vote)
    out: list[dict[str, Any]] = []
    for same in by_day.values():
        out.extend(same[-VOTES_PER_DAY:])
    return sorted(out, key=lambda v: v["at"])


def scores(plaza: dict[str, Any], *, through: datetime.date) -> dict[str, decimal.Decimal]:
    """제안별 점수 — **매번 이벤트에서 다시 접는다**(캐시는 정본이 아니다).

    점수(d) = 점수(d-1)×0.5 + 그날 유효표. `through` 까지 접는다(그 날 포함).
    """
    votes = valid_votes(plaza)
    per_day: dict[str, dict[datetime.date, int]] = {}
    for vote in votes:
        per_day.setdefault(vote["target"], {}).setdefault(day_of(vote["at"]), 0)
        per_day[vote["target"]][day_of(vote["at"])] += 1

    out: dict[str, decimal.Decimal] = {}
    for pid, proposal in plaza["proposals"].items():
        start = day_of(proposal["at"])
        if start > through:
            out[pid] = decimal.Decimal(0)
            continue
        score = decimal.Decimal(0)
        day = start
        while day <= through:
            score = (score * DECAY + per_day.get(pid, {}).get(day, 0)).quantize(
                decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_UP)
            day += datetime.timedelta(days=1)
        out[pid] = score
    return out


def voters(plaza: dict[str, Any]) -> dict[str, set[str]]:
    """제안별 **서로 다른 유효 투표자**(자기표는 이미 빠져 있다)."""
    out: dict[str, set[str]] = {}
    for vote in valid_votes(plaza):
        out.setdefault(vote["target"], set()).add(vote["from"])
    return out


def settled(plaza: dict[str, Any]) -> set[str]:
    """이미 끝난 제안 — **마커가 정본**이다(졸업·보관)."""
    return {m["id"] for m in plaza["markers"] if m["kind"] in ("졸업", "보관")}


def ranking(plaza: dict[str, Any], *, through: datetime.date) -> list[dict[str, Any]]:
    """순위표 — 점수 내림차순 · 동점이면 **오래된 제안**이 앞."""
    table = scores(plaza, through=through)
    who = voters(plaza)
    done = settled(plaza)
    # ★그날 **이미 있던** 제안만 줄에 세운다. 아직 안 올라온 제안을 0점으로 끼워 두면
    #   「그날 후보가 있었다」로 읽혀 교착 판정이 틀어진다(2026-09-11 시험이 잡았다).
    rows = [{"id": pid, "score": table[pid], "voters": len(who.get(pid, ())),
             "at": proposal["at"], "from": proposal["from"], "body": proposal["body"]}
            for pid, proposal in plaza["proposals"].items()
            if pid not in done and day_of(proposal["at"]) <= through]
    rows.sort(key=lambda r: (-r["score"], r["at"]))
    return rows


def eligible(rows: list[dict[str, Any]], *, min_score: Any = MIN_SCORE,
             min_voters: int = MIN_VOTERS) -> list[dict[str, Any]]:
    """개설 조건을 **둘 다** 넘긴 것만(점수 · 서로 다른 투표자 수).

    ★둘 다여야 한다: 점수만 보면 한 사람이 여러 날 몰아줘서 열 수 있고, 사람 수만 보면
      지나가는 표 둘로 열린다. 문턱은 **노브**다(설정이 이긴다) — 값이 코드에 박히면
      광장마다 다른 리듬을 못 준다.
    """
    floor = decimal.Decimal(str(min_score))
    return [r for r in rows if r["score"] >= floor and r["voters"] >= int(min_voters)]


def to_shelve(plaza: dict[str, Any], *, now: datetime.datetime,
              days: int = SHELVE_DAYS) -> list[str]:
    """[보관] 대상 — 오래됐고 아직 아무 마커도 없는 제안."""
    done = settled(plaza)
    out = []
    for pid, proposal in plaza["proposals"].items():
        if pid in done:
            continue
        if (now - proposal["at"]).days >= days:
            out.append(pid)
    return sorted(out, key=lambda pid: plaza["proposals"][pid]["at"])


# ── 피드(광장 v2 · 명세 A1) ────────────────────────────────────────────────
# ★정렬 규칙의 **정본은 여기 한 곳**이다. 릴레이(`relay/src/lib/feed.ts`)는 이 규칙을 옮겨 적은 이식이고,
#   selftest 의 py↔ts 대조 케이스가 같은 입력에 두 구현이 **같은 순서**를 내는지 기계로 맞춰 본다.
#   규칙을 바꾸려면 여기를 고치고 → 이식을 같은 커밋에서 고친다(대조가 한쪽만 고친 것을 잡는다).
#
#   · 댓글 = post 인데 `refs[0]` 이 부모 글을 가리키고 `why` 가 "reply" 인 것(새 칸 없음 · 명세 §0-1).
#     부모가 **같은 방에 먼저 적재된 글**일 때만 댓글로 붙는다. 아니면 일반 글로 보인다(격리 아님).
#   · new = 적재 시각 최신이 앞 · hot = 감쇠 점수(위 scores) 높은 것이 앞 · top = 누적 유효 추천 많은 것이 앞.
#     hot·top 동점이면 **최신이 앞**. 끝까지 같으면 (방, 글 id) 내림차순 — 순서가 기계마다 갈리지 않게.
#   · 댓글은 부모 아래에 **적재 순**(오래된 것이 위)으로 붙는다. 댓글의 댓글도 같은 규칙으로 한 단 더.
#   ⚠「많이 추천됐다」는 「참이다」가 아니다 — 이 순서는 읽는 순서일 뿐 판정이 아니다.
FEED_SORTS = ("new", "hot", "top")


def is_community(genesis_payload: dict[str, Any]) -> bool:
    """이 방이 **커뮤니티**(광장과 같은 방식으로 연 방)인가 — 판별의 **정본은 이 함수 하나**다.

    커뮤니티 = type 이 debate · `deadlines` 칸 없음 · `budget` 칸 있음(광장 열기가 늘 넣는 칸).
    ★budget 조건은 명세 A2 문구에 **덧붙인 것**이다(작성자 판단 · 오너 확인 대상 · 2026-09-19 master 판정 B).
      없으면 루프가 도는 일반 토론방(deadlines 를 안 넣는다)까지 커뮤니티로 읽혀, 전역 상한이 토론을 막는다.
    릴레이 `/communities`·피드·전역 상한 버킷이 이 정의를 옮겨 쓴다(`relay/src/lib/feed.ts` isCommunity).
    """
    if not isinstance(genesis_payload, dict):
        return False
    return (genesis_payload.get("type") == "debate"
            and "deadlines" not in genesis_payload
            and isinstance(genesis_payload.get("budget"), dict))
REPLY_WHY = "reply"


def reply_parent(event: dict[str, Any]) -> str | None:
    """이 글이 댓글이면 부모 글의 message_id(`refs[0]` · why="reply"), 아니면 None."""
    refs = (event.get("payload") or {}).get("refs") or []
    if not isinstance(refs, list) or not refs or not isinstance(refs[0], dict):
        return None
    if refs[0].get("why") != REPLY_WHY:
        return None
    parent = refs[0].get("message_id")
    return parent if isinstance(parent, str) and parent else None


def feed(rooms: dict[str, list[dict[str, Any]]], *, sort: str,
         now: datetime.datetime) -> list[dict[str, Any]]:
    """커뮤니티 방들의 글·댓글을 **한 줄 피드**로 — 방마다 접은 뒤 합쳐서 정렬한다.

    `rooms` = {방 id: 그 방의 받아들여진 이벤트(적재 순)}. 표·점수는 **방 안에서만** 센다.
    """
    if sort not in FEED_SORTS:
        raise ValueError(f"정렬은 {FEED_SORTS} 중 하나다: {sort!r}")
    through = day_of(now)
    tops: list[dict[str, Any]] = []
    for room_id, events in rooms.items():
        plaza = read_plaza(events)
        table = scores(plaza, through=through)
        counts: dict[str, int] = {}
        for vote in valid_votes(plaza):
            counts[vote["target"]] = counts.get(vote["target"], 0) + 1
        props = plaza["proposals"]
        items = {pid: {"room": room_id, "id": pid, "from": p["from"], "at": p["created_at"],
                       "body": p["body"], "score": format(table[pid], ".2f"), "votes": counts.get(pid, 0),
                       "replies": [], "_t": p["at"], "_order": p["order"]}
                 for pid, p in props.items()}
        for pid in sorted(props, key=lambda k: props[k]["order"]):
            parent = props[pid]["parent"]
            if parent in props and props[parent]["order"] < props[pid]["order"]:
                items[parent]["replies"].append(items[pid])
            else:
                tops.append(items[pid])

    def key(item: dict[str, Any]) -> tuple[Any, ...]:
        if sort == "hot":
            first: Any = -decimal.Decimal(item["score"])
        elif sort == "top":
            first = -item["votes"]
        else:
            first = 0
        return (first, -item["_t"].timestamp())

    # 마지막 동점 깨기 = (방, 글 id) 내림차순 → 먼저 그것으로 정렬하고 안정 정렬을 한 번 더.
    tops.sort(key=lambda i: (i["room"], i["id"]), reverse=True)
    tops.sort(key=key)
    return [_strip(i) for i in tops]


def _strip(item: dict[str, Any]) -> dict[str, Any]:
    """내부 칸(_로 시작)을 빼고, 댓글은 적재 순으로 재귀 정리한다."""
    out = {k: v for k, v in item.items() if not k.startswith("_") and k != "replies"}
    out["replies"] = [_strip(r) for r in sorted(item["replies"], key=lambda r: r["_order"])]
    return out
