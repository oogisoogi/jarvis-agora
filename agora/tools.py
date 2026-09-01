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

import json
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
    # ★예산도 **설정에서** 온다(§5). 안 넘기면 reducer 가 계약 기본값으로 돌고,
    #   `config.json` 의 `budget` 칸은 **적어도 아무 일도 안 하는 칸**이 된다
    #   (예시 설정 파일이 그 칸을 광고하고 있으므로 더 나쁘다 — 껐다고 믿게 만든다).
    reduced = reducer.apply(reducer.order(collected), operators=ctx.operators,
                            budget=protocol.load_budget(ctx.config),
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
        """
        reducer.require_state(_reduce(ctx, thread_id), expected_state)

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
    settled = core.settle_unknown(store=ctx.store, ledger=ctx.ledger, event=event,
                                  event_hash=(err.detail or {}).get("event_hash") or "")
    if settled["verdict"] != core.COMMITTED:
        raise AgoraError(errors.STORE, "저장되지 않았다 — 재조회로 확인했다",
                         {"settled": settled["verdict"],
                          "message_id": event["message_id"]}) from None
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
    return state, state["head"], state["state_hash"]


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
    section, key = _parse_cursor(cursor)
    base = {k: v for k, v in view.items() if k not in READ_SECTIONS}   # 고정 메타(state·refs 밖)
    lists = {k: list(view[k]) for k in READ_SECTIONS if k in view}
    budget = READ_PAGE_BYTES
    candidate: dict[str, Any] = {}
    for _ in range(READ_FIT_ROUNDS):
        page = _fill_page(lists, section, key, budget)
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


def _parse_cursor(cursor: str | None) -> tuple[str, str | None]:
    """`<목록>:<키>` → (목록, 키). 맨몸 값은 라운드 1 형식(= events 의 message_id)이다."""
    if not cursor:
        return "events", None
    head, sep, key = cursor.partition(":")
    if sep and head in READ_SECTIONS:
        return head, key
    return "events", cursor


def _bytes_of(rows: list[dict[str, Any]]) -> int:
    return sum(len(json.dumps(r, ensure_ascii=False).encode("utf-8")) for r in rows)


def _section_key(section: str, entry: dict[str, Any], index: int) -> str:
    """이어 읽기 키 — events 는 message_id · 격리·stale 은 node_id · refs 는 위치(링크엔 고유 id 가 없다)."""
    if section == "refs":
        return str(index)
    return str(entry.get("node_id") or entry.get("message_id") or index)


def _page_sections(view: dict[str, Any], lists: dict[str, list[dict[str, Any]]],
                   section: str, key: str | None, budget: int) -> None:
    """events 뒤의 목록들을 **같은 바이트 예산** 안에서 이어 준다.

    ★못 실은 목록은 **빈 목록으로 두지 않고 이름을 댄다**(`pending`). 빈 목록은 「없다」와
      「이번 페이지엔 못 실었다」가 같아 보이고, 격리 목록에서 그 둘은 정반대 사실이다.
    ★한 페이지에 적어도 한 건은 싣는다 — 한 건이 예산보다 커도 진행은 해야 한다(무한 같은 페이지 금지).
    """
    order = list(READ_SECTIONS[1:])
    present = [s for s in order if s in lists]
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
        if section == s:
            keys = [_section_key(s, r, i) for i, r in enumerate(rows)]
            if key not in keys:
                raise AgoraError(errors.ARGUMENT, "그 cursor 가 이 스레드에 없다",
                                 {"cursor": f"{s}:{key}"})
            start = keys.index(key) + 1
        out: list[dict[str, Any]] = []
        for i in range(start, len(rows)):
            size = len(json.dumps(rows[i], ensure_ascii=False).encode("utf-8"))
            if out and budget - size < 0:
                view["next_cursor"] = f"{s}:{_section_key(s, rows[i - 1], i - 1)}"
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
            parent: dict[str, Any] | None = None) -> dict[str, Any]:
    """새 스레드. thread_id 는 **미리 만든다**(H-6 · genesis 안에 들어가야 한다)."""
    thread_id = new_id()
    payload: dict[str, Any] = {"type": type, "title": title, "body": body}
    if envelope is not None:
        payload["envelope"] = envelope
    if deadlines is not None:
        payload["deadlines"] = deadlines
    if parent is not None:
        payload["parent"] = parent
    out = _publish(ctx, kind="genesis", thread_id=thread_id, payload=payload,
                   prev=GENESIS_PREV, expected_state=GENESIS_EXPECTED_STATE,
                   category=type, title=title, is_genesis=True)
    return {"thread_id": thread_id, "number": out.get("number"),
            "url": out.get("url"), "message_id": out["message_id"],
            "usage": out["usage"]}


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
                      budget=state.get("budget") or protocol.load_budget(ctx.config))
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


def _store_from_config(cfg: dict[str, Any], directory: str | None = None) -> Any:
    """설정에서 운반층을 세운다 — **어느 저장소인지는 설정에서만 온다.**

    ★S7-1 에서 드러난 공백이다: 도구·CLI·문서는 다 있었는데 **「어느 저장소에 올리는가」를
      적는 칸이 계약에 없었다.** 그래서 CLI 로 실제 도구를 부르면 저장층 생성에서
      **날 예외**가 났다(오류 계약 밖). 문서만 보고 따라간 사람은 여기서 막힌다.
    ★없으면 **무엇이 없는지 이름을 대고** code 2 로 멈춘다. 「설정이 잘못됐다」로만 말하면
      사용자는 무엇을 고쳐야 하는지 모른다.
    """
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


def call(name: str, ctx: Context, kwargs: dict[str, Any]) -> Any:
    """이름으로 도구를 부른다(CLI·MCP 서버가 쓰는 한 줄).

    ★모르는 이름은 **여기서** 죽인다. 부르는 쪽마다 따로 검사하면 한 곳이 빠지고,
      빠진 그 경로가 계약 밖 이름을 통과시킨다.
    """
    fn = CORE_TOOLS.get(name)
    if fn is None:
        raise AgoraError(errors.ARGUMENT, "계약에 없는 도구",
                         {"tool": name, "allowed": sorted(CORE_TOOLS)})
    return fn(ctx, **kwargs)


# ── 계약 대조표(§4 = 이 표 = CLI 등록표) ────────────────────────────────────
# ★도구 이름과 함수를 **한 곳에서** 잇는다. 세 곳(설계 표·CLI 등록표·이 모듈)이
#   따로 놀면 「CLI 엔 있는데 MCP 엔 없는」 도구가 조용히 생긴다 — 시험이 셋을 대조한다.
CORE_TOOLS: dict[str, Any] = {
    "threads": threads, "read": read, "propose": propose, "say": say,
    "advance": advance, "resolve": resolve, "mark-solved": mark_solved,
    "close": close, "vote": vote, "envelope-check": envelope_check, "ack": ack,
}
