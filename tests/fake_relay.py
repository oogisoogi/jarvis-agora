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
                 checkpoint: dict[str, Any] | None = None,
                 checkpoint_404: bool = False, verdict: dict[str, Any] | None = None,
                 retry_after: str | None = None,
                 body_code_override: int | None = None,
                 forge_retry: bool = False) -> None:
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
                    "created_at": now_iso(), "updated_at": now_iso(), "events": []}
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
        row = {"event_id": f"EV_{self.counter}", "created_at": now_iso(),
               "body": body, "is_genesis": bool(is_genesis), "message_id": message_id,
               "hash": _event_hash_of(body)}
        room["events"].append(row)
        if self.refresh_updated_at:
            room["updated_at"] = row["created_at"]
        return dict(row, existing=False)

    def inject_raw(self, *, room_id: str, body: str) -> dict[str, Any]:
        """우리 서식이 아닌 글을 심는다(웹에서 손으로 쓴 댓글에 해당)."""
        return self.append_event(thread_id=room_id, category="debate", title="",
                                 body=body, is_genesis=False)

    def derived(self, room_id: str) -> dict[str, Any]:
        """서버가 이벤트에서 파생한 상태 — **클라 reducer 와 독립적으로** 계산한다.

        ★일부러 단순하다(close 이벤트가 있으면 닫힘 · answer_selected 가 있으면 답 선택됨).
          클라와 같은 코드를 쓰면 대조가 자기 자신과의 대조가 되어 아무것도 못 잡는다.
        """
        room = self.rooms.get(room_id) or {"events": []}
        closed = answered = False
        closed_at = None
        for row in room["events"]:
            body = row.get("body") or ""
            if '"kind":"close"' in _compact(body):
                closed, closed_at = True, row["created_at"]
            if '"kind":"answer_selected"' in _compact(body):
                answered = True
        return {"closed": closed, "answered": answered, "closed_at": closed_at}


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


def _signature_matches(raw: bytes, signature: str) -> bool:
    """서명이 **그 바이트**에 대한 것인가 — 명부와 무관한 질문(`-Y check-novalidate`)."""
    import subprocess
    import tempfile
    if not signature or "BEGIN SSH SIGNATURE" not in signature:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        sig_path = os.path.join(tmp, "proof.sig")
        with open(sig_path, "w", encoding="utf-8") as fh:
            fh.write(signature)
        proc = subprocess.run(
            ["ssh-keygen", "-Y", "check-novalidate", "-n", "jarvis-agora@godmeyou.kr",
             "-s", sig_path],
            input=raw, capture_output=True, timeout=30)
    return proc.returncode == 0


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
            current = _sha256_text("".join(self.relay.roster_text[n] for n in
                                           ("allowed_signers", "revoked_keys", "operators")))
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
                        if k not in ("message_id", "hash", "existing")}
                # 파생 판정 덧칸(계약 §3-5) — `lie_valid` 면 격리감에도 참을 적는다.
                item.update({"valid": True, "quarantined": False,
                             "stale": False, "reason": None}
                            if (row.get("message_id") or self.relay.lie_valid)
                            else {"valid": False, "quarantined": True,
                                  "stale": False, "reason": "permission"})
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
            self._send(200 if row.get("existing") else 201, out)   # 멱등은 200 이다
            return
        if url.path == "/register":
            pid = payload.get("participant_id")
            if self.relay.require_proof and not payload.get("signature"):
                # ★소유 증명(릴레이 계약 §3-1) — 없으면 「남의 공개키를 주워다 등록」이 열린다.
                self._fail(401, "소유 증명 서명이 없다", reason="proof_required")
                return
            if self.relay.require_proof and not _signature_matches(
                    _register_canonical(payload), payload.get("signature", "")):
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
