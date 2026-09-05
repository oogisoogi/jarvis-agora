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

⚠**이 서버 상대의 초록은 「논리가 맞다」는 뜻이지 「진짜 릴레이가 그렇게 답한다」는 뜻이 아니다.**
  그 대조는 워커 A 의 릴레이가 설 때 한다(설계 §11).
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agora.ledger import now_iso            # noqa: E402


class FakeRelay:
    def __init__(self, *, idempotent: bool = True, refresh_updated_at: bool = True,
                 revoked_404: bool = False, derive_status: bool = True,
                 page_size: int = 0, preempt_identity: bool = True,
                 require_proof: bool = True) -> None:
        self.idempotent = idempotent
        self.refresh_updated_at = refresh_updated_at
        self.revoked_404 = revoked_404
        self.derive_status = derive_status
        self.page_size = page_size
        self.preempt_identity = preempt_identity
        self.require_proof = require_proof
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
        room = self._room(thread_id, category=category, title=title)
        if is_genesis and title:
            room["title"] = title
        message_id = _message_id_of(body)
        if self.idempotent and message_id:
            for row in room["events"]:
                if row.get("message_id") == message_id:
                    return row              # ★멱등 — 새 행을 만들지 않는다
        self.counter += 1
        row = {"event_id": f"EV_{self.counter}", "created_at": now_iso(),
               "body": body, "is_genesis": bool(is_genesis), "message_id": message_id}
        room["events"].append(row)
        if self.refresh_updated_at:
            room["updated_at"] = row["created_at"]
        return row

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


def _compact(body: str) -> str:
    return "".join(body.split())


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
    def _send(self, status: int, payload: Any, *, text: bool = False) -> None:
        raw = (payload if text else json.dumps(payload, ensure_ascii=False)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",
                         "text/plain; charset=utf-8" if text else "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _override(self, path: str) -> bool:
        for prefix, status in self.relay.status_override.items():
            if path.startswith(prefix):
                self._send(status, {"code": status, "message": "강제 상태"})
                return True
        return False

    # ── GET ─────────────────────────────────────────────────────────────────
    def do_GET(self) -> None:                       # noqa: N802 — http.server 계약
        url = urlparse(self.path)
        query = parse_qs(url.query)
        self.relay.calls.append(url.path)
        if self._override(url.path):
            return
        parts = [p for p in url.path.split("/") if p]
        if parts[:1] == ["participants"] and len(parts) == 2:
            name = parts[1]
            if name == "revoked_keys" and self.relay.revoked_404:
                self._send(404, {"code": 404, "message": "없다"})
                return
            if name not in self.relay.roster_text:
                self._send(404, {"code": 404, "message": "없다"})
                return
            self._send(200, self.relay.roster_text[name], text=True)
            return
        if parts == ["rooms"]:
            since = (query.get("updated_since") or [None])[0]
            rows = [{"room_id": r["room_id"],
                     "node_id": (r["events"][0]["event_id"] if r["events"] else None),
                     "updated_at": r["updated_at"], "title": r["title"]}
                    for r in sorted(self.relay.rooms.values(),
                                    key=lambda r: r["updated_at"], reverse=True)
                    if not since or r["updated_at"] >= since]
            self._send(200, {"items": rows, "next_cursor": None})
            return
        if parts[:1] == ["rooms"] and len(parts) == 2:
            room_id = parts[1]
            if room_id not in self.relay.rooms:
                self._send(404, {"code": 404, "message": "그런 방이 없다"})
                return
            if not self.relay.derive_status:
                self._send(200, {"room_id": room_id})       # 파생 안 함 — 칸 자체가 없다
                return
            self._send(200, {"room_id": room_id, **self.relay.derived(room_id)})
            return
        if parts[:1] == ["rooms"] and parts[2:] == ["events"]:
            room = self.relay.rooms.get(parts[1])
            if room is None:
                self._send(404, {"code": 404, "message": "그런 방이 없다"})
                return
            rows = [{k: v for k, v in row.items() if k != "message_id"}
                    for row in room["events"]]
            cursor = (query.get("cursor") or ["0"])[0]
            start = int(cursor) if cursor.isdigit() else 0
            size = self.relay.page_size or len(rows) or 1
            page = rows[start:start + size]
            nxt = str(start + size) if start + size < len(rows) else None
            self._send(200, {"items": page, "next_cursor": nxt})
            return
        self._send(404, {"code": 404, "message": "그런 경로가 없다"})

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
            self._send(400, {"code": 400, "message": "JSON 이 아니다"})
            return
        if url.path == "/events":
            row = self.relay.append_event(
                thread_id=payload["thread_id"], category=payload.get("category", ""),
                title=payload.get("title", ""), body=payload.get("body", ""),
                is_genesis=bool(payload.get("is_genesis")))
            self._send(201, {"event_id": row["event_id"], "url": None,
                             "created_at": row["created_at"]})
            return
        if url.path == "/register":
            pid = payload.get("participant_id")
            if self.relay.require_proof and not payload.get("signature"):
                # ★소유 증명(릴레이 계약 3-1) — 없으면 「남의 공개키를 주워다 등록」이 열린다.
                self._send(401, {"code": 401, "message": "소유 증명 서명이 없다",
                                 "reason": "proof_required"})
                return
            known = self.relay.registered.get(pid)
            if (known and self.relay.preempt_identity
                    and known.get("fingerprint") != payload.get("fingerprint")):
                # ★신원 선점 — 이미 등록된 id 에 다른 키를 붙이지 못한다.
                self._send(409, {"code": 409, "message": "이미 다른 키로 등록된 id 다",
                                 "reason": "identity_taken"})
                return
            self.relay.registered[pid] = {"public_key": payload.get("public_key", ""),
                                          "fingerprint": payload.get("fingerprint", ""),
                                          "display_name": payload.get("display_name", ""),
                                          "signature": payload.get("signature", "")}
            key_line = payload.get("public_key", "").strip()
            if key_line and key_line not in self.relay.roster_text["allowed_signers"]:
                self.relay.roster_text["allowed_signers"] += f"{pid} {key_line}\n"
            self._send(201, {"participant_id": pid, "registered": True})
            return
        self._send(404, {"code": 404, "message": "그런 경로가 없다"})


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
