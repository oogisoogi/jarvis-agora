"""릴레이 운반층(설계 `docs/TRANSPORT-RELAY.md` · 06 증보 §6).

★**운반층은 믿지 않는다.** 여기서 하는 일은 「올리고 받아 오는 것」뿐이고, 무엇이 유효한가는
  reducer 가 정한다. 서버가 입구에서 서명·스크럽을 한 번 더 보는 것은 **백스톱**이지 정본이 아니다.

★`store_github` 와 같은 자리에 같은 규율을 둔다:
  ⑴ 실제 호출 자리를 **transport 한 곳**으로 모은다(가짜 릴레이로 논리를 시험할 수 있고, backoff 를 한 곳에 건다).
  ⑵ **한도는 벽이 아니라 신호다**(429·5xx = 기다렸다 다시 · 400·409 는 기다려도 그대로다).
  ⑶ 성공 여부가 불분명하면 **code 8** 로 올린다 — 성공도 실패도 단정하지 않는다.

★GitHub 어댑터와 다른 점 하나: **결박(bindings)이 없다.** 방의 주소가 곧 `thread_id` 라서
  「번호↔이름」을 잇는 장치(본문 검색·결박 원장·rebind)가 통째로 필요 없다.
  ⚠그렇다고 위협이 사라진 것은 아니다 — 형태가 **서버 쪽으로** 옮겨 갔다(설계 §9·§10).

⚠**표준 라이브러리만** 쓴다(`urllib`·`json`·`ssl` 기본값). 새 외부 의존을 들이지 않으므로
  K-1(윈도우 미실행)의 범위가 넓어지지 않는다 — 다만 **윈도우에서 실행해 본 것은 아니다.**
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote, urlencode

from agora import errors
from agora.contract_open import ANSWERABLE_CATEGORY, CATEGORIES
from agora.errors import AgoraError

# 대기는 **곱으로** 늘린다(store_github 와 같은 값 · 같은 이유).
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_FACTOR = 2.0
BACKOFF_ATTEMPTS = 4

DEFAULT_TIMEOUT_SECONDS = 30

# 기다렸다 다시 하면 달라질 수 있는 상태들. 나머지는 기다려도 그대로다.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

ROSTER_FILES = ("allowed_signers", "revoked_keys", "operators")

# 목록 한 쪽의 상한 — **릴레이 계약이 정한 값**(`docs/RELAY.md` §3-3 `1..100` · §3-5 `1..200`).
# ★상한을 넘겨 보내면 서버가 400 으로 돌려준다. 부르는 쪽의 실수를 **여기서** 계약 안으로 접는다.
ROOMS_LIMIT_MAX = 100
EVENTS_LIMIT_MAX = 200

# 실패 본문이 말할 수 있는 코드 — **닫아 둔다**(릴레이 계약 §3-7 표의 여섯 값).
# ★열어 두면 서버가 우리 오류 계약에 없는 숫자를 밀어 넣어 `AgoraError` 생성 자체가 터진다.
BODY_CODES: frozenset[int] = frozenset({
    errors.GATE_REJECT, errors.SIGNATURE, errors.PERMISSION,
    errors.STORE, errors.STATE_CONFLICT, errors.ARGUMENT,
})

# 서버가 `Retry-After` 로 아무 값이나 줄 수 있으므로 **우리 쪽 상한**을 둔다.
RETRY_AFTER_CAP_SECONDS = 60.0


def _body_code(detail: Any) -> int | None:
    """실패 본문의 `code` — 릴레이 계약이 **정본이라고 못박은 칸**(RELAY.md §3-0).

    ★계약 원문: 「판정의 정본은 본문 `code` 다. HTTP 상태는 캐시·프록시·브라우저를 위한
      관례이고, 둘이 갈리면 `code` 가 이긴다.」 그래서 상태만 보던 구판을 고쳤다 —
      같은 코드가 여러 상태로 나갈 수 있다는 것이 서버 쪽 설계다(§3-7 표).
    ★단 **닫힌 집합**으로만 받는다: 계약 밖 숫자·문자열은 없는 것으로 치고 상태 매핑으로 내려간다.
      ⚠받아들인 값(정직): 이 칸은 서버가 쓴다 — 서버가 400 자리에 7 을 적으면 우리는 그것을
      재시도 가능한 실패로 읽는다. **여기서 바뀌는 것은 실패의 이름뿐이고, 무엇이 유효한
      이벤트인가는 여전히 reducer 가 정한다**(설계 §3 신뢰 경계).
    """
    if type(detail) is not dict:
        return None
    code = detail.get("code")
    return code if type(code) is int and code in BODY_CODES else None


def _map_status(status: int, detail: Any) -> AgoraError:
    """HTTP 상태 → 우리 오류 계약(설계 §5 표 · 릴레이 계약 §3-7).

    ★본문 `code` 가 있으면 그것이 이긴다(§3-0). 없거나 계약 밖이면 상태로 매핑한다 —
      계약을 안 지키는 상대(프록시·구 서버)에게도 우리는 답을 내야 하기 때문이다.
    ★상태 매핑의 기본값은 계약 표 그대로다: **401 = 4(서명) · 403 = 5(권한)**.
      구판은 둘 다 4 로 두고 `detail.reason` 이 있을 때만 5 로 갔는데, 계약은 상태로 이미
      갈라 놓았다 — 「모르면 좁은 쪽」은 계약이 말이 없을 때의 규율이지 계약을 덮는 규율이 아니다.
    """
    code = _body_code(detail)
    # ★★서버가 준 본문은 **언제나 한 겹 아래**(`detail.detail`)에 둔다 — 위층은 우리 것이다.
    #   ⚠agy 적대검증 2026-09-05 지적: 본문을 그대로 detail 로 쓰면 서버가 `retry: true` 를 적어
    #     **우리 재시도 표식을 위조**할 수 있었다(400 을 네 번 두드리게 만든다). 표식과 남의 말이
    #     같은 칸에 살면, 그 칸을 읽는 판정은 남의 것이 된다.
    #   ★`status` 를 늘 싣는 부수 효과도 있다 — 부재 판정(`roster_checkpoint`)이 그 값을 본다.
    def wrap(default: int, message: str) -> AgoraError:
        return AgoraError(code or default, message, {"status": status, "detail": detail})
    if status == 400:
        return wrap(errors.ARGUMENT, "릴레이가 요청을 거부했다")
    if status in (401, 403):
        return wrap(errors.PERMISSION if status == 403 else errors.SIGNATURE,
                    "릴레이가 신원·권한을 거부했다")
    if status == 404:
        return wrap(errors.STORE, "릴레이에 그것이 없다")
    if status == 409:
        # ★계약에서 409 는 **신원 선점(등록)** 전용이다 — CAS 경합은 여기서 안 난다(RELAY.md §3-7·§5).
        #   구판 문구(「사슬이 갈렸다 — read 후 다시」)는 릴레이에서 일어나지 않는 일을 설명했다.
        return wrap(errors.STATE_CONFLICT, "릴레이가 충돌로 거부했다 — 등록 신원 선점(계약 §3-7)")
    if status in (413, 422):
        return wrap(errors.GATE_REJECT, "릴레이 게이트가 거부했다")
    return wrap(errors.STORE, "릴레이 오류")


def _query(**params: Any) -> str:
    """질의 문자열 — **값을 반드시 인코딩한다**.

    ★`cursor` 는 계약상 **불투명**이다(RELAY.md §3-3·§3-5): 서버가 `=`·`&`·공백이 든 값을
      줘도 되고, 그것을 f-문자열로 이어 붙이면 **다음 요청에서 두 칸으로 쪼개진다.**
      그 실패는 조용하다 — 서버는 커서를 못 읽었다고만 답하거나, 첫 페이지를 다시 준다.
    """
    items = [(k, str(v)) for k, v in params.items() if v not in (None, "")]
    return ("?" + urlencode(items)) if items else ""


def _clamp(value: Any, high: int) -> int:
    """계약 범위(1..high) 안으로 접는다."""
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        return high
    return max(1, min(wanted, high))


def _exhausted(last: AgoraError | None, *, write: bool, attempts: int,
               waited: list[float]) -> AgoraError:
    """재시도를 다 썼다 — 그런데 **쓰기의 5xx 는 실패가 아니라 「모른다」**이다.

    ★agy 적대검증 2026-09-05 지적(수용): 프록시 504·워커 500 은 **서버가 이미 적재한 뒤**일 수 있다.
      그것을 code 7(저장층 실패)로 올리면 호출자가 `_settle_unknown`(재조회 판정)을 **안 탄다** —
      사용자는 실패로 읽고 새 `message_id` 로 다시 쓴다. 그 결과가 **조용한 중복**이다.
      (GitHub 시절 code 8 재시도가 게시물 4건을 만든 그 사고의 다른 입구다.)
    ★**429 는 8 이 아니다.** 계약 §3-2 의 검사 순서에서 멱등이 속도 제한보다 **앞**이므로,
      429 로 거절된 요청은 원장에 아무것도 안 남긴다 — 서버가 「안 받았다」를 명시한 것이다.
    """
    status = (last.detail or {}).get("status") if last else None
    may_have_landed = bool(write and type(status) is int and status >= 500)
    detail = {"attempts": attempts, "waited": waited, "last_status": status,
              "last": (last.detail if last else None)}
    if may_have_landed:
        return AgoraError(errors.UNKNOWN_COMMIT,
                          "릴레이가 계속 받지 않는다 — 이미 받았을 수 있다(재조회로 판정하라)",
                          detail)
    return AgoraError(errors.STORE, "릴레이가 계속 받지 않는다", detail)


def _retry_delay(err: AgoraError, fallback: float) -> float:
    """다음 시도까지 얼마나 기다릴까 — **서버가 말했으면 그 값을 존중한다**(계약 §3-7).

    ★429 에 `Retry-After` 를 붙이는 것은 계약이 필수로 둔 칸이다. 무시하고 우리 backoff 만
      쓰면 상한을 계속 두드리게 되고, 그것은 「한도는 벽이 아니라 신호다」를 어기는 것이다.
    ★그러나 **상한을 둔다**: 서버가 3600 을 주면 부르는 쪽이 한 시간 멈춘다. 상한에 걸린 경우
      우리는 그만큼만 기다리고, 그래도 429 면 시도를 소진하고 code 7 로 올린다(거짓 성공 없음).
    ⚠HTTP-date 서식은 안 읽는다 — 숫자가 아니면 우리 backoff 로 간다(모르는 값을 지어내지 않는다).
    """
    raw = (err.detail or {}).get("retry_after")
    try:
        wanted = float(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    if wanted <= 0:
        return fallback
    return min(wanted, RETRY_AFTER_CAP_SECONDS)


def relay_transport(method: str, url: str, *, payload: dict[str, Any] | None = None,
                    accept: str = "json", timeout: int = DEFAULT_TIMEOUT_SECONDS,
                    write: bool = False) -> Any:
    """실제 호출 자리 — 여기 말고는 네트워크를 만지지 않는다.

    ★`write` 가 실패 분류를 가른다. **응답을 못 받은 것**은 읽기에서는 그냥 재시도(7)지만,
      쓰기에서는 **성공 불명(8)** 이다 — 서버가 이미 받았을 수 있기 때문이다.
      반대로 **요청이 나가기 전에** 죽은 것(연결 거부·DNS)은 쓰기여도 8 이 아니라 7 이다.
      8 을 남발하면 재조회 왕복만 늘고, 8 을 안 쓰면 같은 말이 두 번 나간다.
    """
    data = None
    headers = {"Accept": "application/json" if accept == "json" else "text/plain"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:                     # 서버가 상태로 답했다
        body = e.read()
        detail: Any
        try:
            detail = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            detail = {"body_bytes": len(body)}
        if e.code in RETRY_STATUSES:
            err = AgoraError(errors.STORE, "릴레이가 지금은 받지 않는다",
                             {"status": e.code, "retry": True,
                              "retry_after": e.headers.get("Retry-After"),
                              "detail": detail})
            raise err from None
        raise _map_status(e.code, detail) from None
    except urllib.error.URLError as e:                      # 연결 자체가 안 됐다
        reason = e.reason
        sent_maybe = not isinstance(reason, (ConnectionRefusedError, socket.gaierror))
        code = errors.UNKNOWN_COMMIT if (write and sent_maybe) else errors.STORE
        raise AgoraError(code, "릴레이에 닿지 못했다",
                         {"reason": type(reason).__name__, "sent_maybe": sent_maybe,
                          "retry": code == errors.STORE}) from None
    except (TimeoutError, socket.timeout) as e:             # 보냈는데 답이 없다
        code = errors.UNKNOWN_COMMIT if write else errors.STORE
        raise AgoraError(code, "릴레이 응답이 없다",
                         {"reason": type(e).__name__, "sent_maybe": True,
                          "retry": code == errors.STORE}) from None
    if accept != "json":
        return raw.decode("utf-8", "replace")
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise AgoraError(errors.STORE, "릴레이 응답이 JSON 이 아니다",
                         {"error": type(e).__name__}) from None


def is_retryable_store(err: AgoraError) -> bool:
    """**여기서** 곧바로 다시 걸어 볼 값어치가 있는 실패인가.

    ★code 7 전부가 아니다. 7 이면서도 기다린다고 달라지지 않는 것이 있다 — 대표가 **404**다.
      그것까지 재시도하면 ⑴없는 것을 네 번 묻고 ⑵마지막에 「계속 받지 않는다」로 **감싸 버려
      원래 status 404 가 사라진다**(체크포인트 부재 판정이 그 값을 본다).
    ★그래서 「다시 걸어라」를 **transport 가 표식으로 말한다**(`detail.retry`) — 부르는 쪽이
      코드 숫자로 추측하지 않는다. 호출자 계약(`errors.RETRYABLE` 의 7·8)은 그대로다.
    """
    return err.code == errors.STORE and (err.detail or {}).get("retry") is True


class RelayStore:
    """`store_base.Store` 6함수의 릴레이 구현.

    ⚠**`number` 칸은 릴레이에서 숫자가 아니다.** 계약(`Store.list_threads`·`fetch`)이 그 이름을
      쓰기 때문에 이름은 그대로 두고, 값으로는 **방 id(= thread_id · 32자 hex)** 를 싣는다.
      `int(number)` 를 쓰면 이 어댑터가 죽는다 — **이름은 계약이고 값은 운반층이 정한다.**
    """

    def __init__(self, base_url: str, *, transport: Any = None, sleep: Any = None,
                 attempts: int = BACKOFF_ATTEMPTS,
                 timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        if not base_url:
            raise AgoraError(errors.PRECONDITION, "릴레이 주소가 없다",
                             {"missing": ["relay.url"]})
        self.base_url = base_url.rstrip("/")
        self._transport = transport or relay_transport
        self._sleep = sleep or time.sleep
        self._attempts = max(1, attempts)
        self._timeout = timeout
        self.waits: list[float] = []      # 실제로 기다린 간격 — 시험이 이것을 본다
        self.calls = 0                    # 재시도까지 센다(쓴 횟수이지 성공 횟수가 아니다)

    # ── 내부 ────────────────────────────────────────────────────────────────
    def _run(self, method: str, path: str, *, payload: dict[str, Any] | None = None,
             accept: str = "json", write: bool = False) -> Any:
        delay = BACKOFF_BASE_SECONDS
        last: AgoraError | None = None
        for attempt in range(self._attempts):
            self.calls += 1
            try:
                return self._transport(method, self.base_url + path, payload=payload,
                                       accept=accept, timeout=self._timeout, write=write)
            except AgoraError as e:
                if not is_retryable_store(e):
                    raise                 # 기다려도 그대로인 실패(그리고 code 8)는 그대로 올린다
                last = e
                if attempt == self._attempts - 1:
                    break
                wait = _retry_delay(e, delay)      # ★서버가 말한 값이 우리 곱보다 앞선다
                self.waits.append(wait)
                self._sleep(wait)
                delay *= BACKOFF_FACTOR
        raise _exhausted(last, write=write, attempts=self._attempts,
                         waited=list(self.waits))

    # ── Store 계약 ──────────────────────────────────────────────────────────
    def append(self, *, thread_id: str, category: str, title: str,
               body: str, is_genesis: bool) -> dict[str, Any]:
        """한 건 올린다. 본문은 **렌더된 게시물 원문 그대로** 간다(서식은 운반층과 무관하다).

        ★서버 멱등(같은 message_id 재전송 = 기존 행)을 **요구하되 전제하지 않는다.**
          약속은 검증 대상이므로 code 8 뒤처리(`tools._settle_unknown` 재조회 판정)는 그대로 남는다.
        ★`verdict`(릴레이 계약 §3-2·§5) = 서버가 **자기 파생으로** 내린 참고 판정이다.
          그대로 실어 올리되 이름을 `relay_verdict` 로 갈라 둔다 — 우리 판정과 **같은 칸에
          두지 않는다.** 원장에는 들어갔는데 서버 리듀서가 격리했다는 사실을 글쓴이가 그 자리에서
          알 수 있게 하는 것이 이 칸의 값이고, 판정의 정본은 여전히 우리 reducer 다(설계 §3).
        """
        out = self._run("POST", "/events", write=True, payload={
            "thread_id": thread_id, "category": category, "title": title,
            "body": body, "is_genesis": bool(is_genesis)})
        node_id = out.get("event_id") or out.get("node_id")
        if not node_id:
            # 성공도 실패도 단정하지 않는다 — 재조회 후에만 판정한다.
            raise AgoraError(errors.UNKNOWN_COMMIT,
                             "릴레이 응답에 이벤트 id 가 없다 — 재조회 후 판정하라",
                             {"thread_id": thread_id})
        row = {"node_id": node_id, "url": out.get("url"),
               "created_at": out.get("created_at")}
        if out.get("verdict") is not None:
            row["relay_verdict"] = out["verdict"]
        return row

    def fetch(self, *, thread_id: str | None = None, number: Any = None,
              cursor: str | None = None, limit: int = 100) -> dict[str, Any]:
        """한 방의 이벤트 **전건**.

        ★서버가 페이지를 나누면 **끝까지 이어 받는다.** 이벤트는 `prev` 로 엮여 있어서
          일부만 주면 reducer 가 「닿지 않는 것」으로 읽는다 — 자르는 것은 `read` 도구의 몫이다.
        """
        room = number or thread_id
        if not room:
            raise AgoraError(errors.ARGUMENT, "thread_id 나 number 가 필요하다", None)
        rows: list[dict[str, Any]] = []
        page_cursor = cursor
        seen_cursors: set[str] = set()
        while True:
            path = (f"/rooms/{quote(str(room), safe='')}/events"
                    + _query(limit=_clamp(limit, EVENTS_LIMIT_MAX), cursor=page_cursor))
            data = self._run("GET", path)
            for item in data.get("items") or []:
                rows.append({
                    "node_id": item.get("event_id") or item.get("node_id"),
                    "thread_id": thread_id or room,
                    "body": item.get("body") or "",
                    "created_at": item.get("created_at"),
                    "is_genesis": bool(item.get("is_genesis")),
                })
            page_cursor = data.get("next_cursor")
            if not page_cursor:
                break
            # ★같은 커서를 두 번 받으면 **서버가 제자리를 돈다** — 무한히 돌지 않고 멈춘다.
            if page_cursor in seen_cursors:
                raise AgoraError(errors.STORE, "릴레이가 같은 커서를 되풀이한다",
                                 {"room": room})
            seen_cursors.add(page_cursor)
        return {"items": rows, "next_cursor": None}

    def list_threads(self, *, updated_since: str | None = None,
                     limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        """방 목록 — watch 가 **읽을 것을 고르는** 자리.

        ⚠이 목록이 쓸모 있으려면 **서버가 이벤트마다 방의 `updated_at` 을 갱신**해야 한다.
          안 하면 watch 는 오류 없이 조용히 눈이 먼다(RC-3). 그 가정을 여기 적어 둔다 —
          가짜 릴레이로는 절대 안 드러나는 종류의 의존이다.
        """
        path = "/rooms" + _query(limit=_clamp(limit, ROOMS_LIMIT_MAX),
                                 updated_since=updated_since, cursor=cursor)
        data = self._run("GET", path)
        rows = []
        for item in data.get("items") or []:
            room = item.get("room_id") or item.get("number")
            rows.append({"number": room, "node_id": item.get("node_id"),
                         "updated_at": item.get("updated_at"),
                         "title": item.get("title")})
        return {"items": rows[:limit], "next_cursor": data.get("next_cursor")}

    def thread_status(self, *, thread_id: str) -> dict[str, Any]:
        """릴레이가 **이벤트에서 파생한** 상태 — 우리 reducer 와 대조하는 축이다.

        ★서버가 파생을 안 하면 **없는 사실을 지어내지 않는다**: `closed=None` + 사유.
          「모른다」와 「열려 있다」를 같은 값으로 적으면 대조가 거짓 초록을 낸다.
        """
        data = self._run("GET", f"/rooms/{quote(str(thread_id), safe='')}")
        if "closed" not in data:
            return {"closed": None, "answered": None, "closed_at": None,
                    "why": "relay_does_not_derive"}
        return {"closed": bool(data.get("closed")),
                "answered": bool(data.get("answered")),
                "closed_at": data.get("closed_at")}

    def project(self, *, thread_id: str, state: str,
                answer_node_id: str | None = None,
                close_reason: str | None = None) -> dict[str, Any]:
        """**할 것이 없다.** 릴레이 보드는 상태를 이벤트에서 파생한다(06 §6).

        ★`ok` 를 돌려주지 않는다 — 그러면 읽는 쪽은 무언가 반영됐다고 읽는다.
          이 문자열이 곧 `close`·`mark_solved` 결과의 `projection` 칸에 그대로 실린다.
        """
        return {"projected": "derived",
                "why": "릴레이 보드는 이벤트에서 파생한다 — 투영할 화면 상태가 없다"}

    def categories(self) -> dict[str, Any]:
        """릴레이에는 카테고리 id 라는 개념이 없다 — 계약 3종을 id = 이름으로 돌려준다."""
        return {name: {"id": name, "is_answerable": name == ANSWERABLE_CATEGORY}
                for name in CATEGORIES}

    # ── 계약 밖(운영 동작) ──────────────────────────────────────────────────
    def register(self, *, participant_id: str, display_name: str,
                 public_key: str, fingerprint: str,
                 signature: str | None = None) -> dict[str, Any]:
        """공개키를 릴레이 명부에 올린다(`agora register`).

        ★**키를 만들지 않는다**(그건 `keygen` 의 일이다). 이미 있는 공개키·지문을 올릴 뿐이다.
        ★`signature` = **소유 증명**(릴레이 계약 3-1 · master 통지 2026-09-05 `[master#283b2c7e]`):
          네 칸(`display_name`·`fingerprint`·`participant_id`·`public_key`)의 canonical JSON 을
          **등록하려는 그 키로** 서명한 것. 이것이 있어야 「남의 공개키를 주워다 그 이름으로 등록」이 막힌다.
        ⚠신원 선점(이미 등록된 id 에 다른 키를 붙이는 요청 거부)은 여전히 **서버가 지켜야 한다** —
          소유 증명은 「이 키의 주인이 맞다」를 보이지만 「이 id 가 그의 것이다」를 보이지는 않는다(설계 §10 잔여).
        ★서명은 **필수 칸이다**(계약 확정본 §3-1 `@b2ca815`). 없으면 여기서 멈춘다 —
          빼고 보내면 서버가 401 로 돌려주고, 사용자는 「키가 잘못됐나」를 먼저 의심한다.
          빠진 칸의 이름을 우리가 대는 것이 그 왕복을 없앤다.
        """
        if not signature:
            raise AgoraError(errors.PRECONDITION,
                             "등록 소유 증명 서명이 없다 — 릴레이 계약 §3-1 필수 칸",
                             {"missing": ["signature"]})
        payload = {"participant_id": participant_id, "display_name": display_name,
                   "public_key": public_key, "fingerprint": fingerprint,
                   "signature": signature}
        return self._run("POST", "/register", write=True, payload=payload)

    def roster_checkpoint(self) -> dict[str, Any] | None:
        """운영자 서명 체크포인트(`GET /participants/checkpoint`). **받은 것을 그대로** 돌려준다.

        ★계약 확정본(§3-6b `@b2ca815`)에서 **부재는 404 가 아니라 200 + `checkpoint: null`** 이다
          (`revoked_keys` 와 같은 이유: 「없음」과 「못 읽음」을 가른다). 그래서 여기서 `None` 으로
          접지 않는다 — `current`·`stale` 이 함께 오고, 그 두 칸이 **부재의 내용**이기 때문이다.
          부재 판정은 `checkpoint` 칸이 비었는지로 부르는 쪽이 한다(`onboard._fetch_checkpoint`).
        ★404 는 **계약을 아직 안 지키는 상대**(엔드포인트가 없는 v1 초기 배포)를 위한 폴백으로 남긴다 —
          그때만 `None` 이다. ⚠`revoked_keys` 의 404 와는 다르게 다룬다: 그쪽은 폐기를 조용히 끄는
          길이라 fail-closed 로 멈추고, 이쪽은 **아직 없는 기능**이다.
        """
        try:
            doc = self._run("GET", "/participants/checkpoint")
        except AgoraError as e:
            if e.code == errors.STORE and (e.detail or {}).get("status") == 404:
                return None
            raise
        return doc or None

    def roster(self) -> dict[str, str]:
        """명부 3종 원문. 셋을 **한 번에** 받는다 — 반쪽만 갱신되면 「그때의 명부」가 갈라진다.

        ★`revoked_keys` 가 404 면 **멈춘다.** 빈 목록으로 치지 않는다 —
          `roster._fingerprints_of` 가 파일 부재를 fail-closed 로 다루는 것과 같은 규율이다.
          **「없음」은 빈 파일로 말한다.**
        """
        out: dict[str, str] = {}
        for name in ROSTER_FILES:
            out[name] = self._run("GET", f"/participants/{name}", accept="text")
        return out
