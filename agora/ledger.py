"""원장 — 무엇을 보내고 받았는지의 append-only 해시 체인.

설계 §5(H-5): 운반층(GitHub)은 댓글을 고치고 지울 수 있으므로 **감사 원장이 아니다.**
그래서 각 참가자가 자기 원장을 들고, 이벤트 **원문**을 따로 보관하며, 줄끼리 해시로 잇는다.

두 축을 **함께** 재야 원장이 원장이다:
  · **링크** — 앞줄 해시가 뒷줄에 박혀 있는가(줄을 지우거나 끼우면 깨진다)
  · **본문** — 그 줄 자체의 해시가 그 줄 내용과 맞는가(칸 하나를 고치면 깨진다)
링크만 재면 「칸 하나 고치기」라는 가장 흔한 변조를 통째로 놓친다.

쓰기는 **append 뿐**이다. 전량 재기록은 이 파일에 없다 —
사후 수정이 가능한 원장은 원장이 아니기 때문이다.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Iterator

from agora import _lock, errors
from agora.errors import AgoraError

SENT = "sent"
RECV = "recv"
STAGES = ("fetched", "delivered", "acked", "sent", "tombstone")

# ★`hash` 칸이 **무엇의 해시인지**(2026-08-25 S6-2 에서 드러난 결함의 처방).
#   같은 칸에 두 계산법이 섞여 있었다: 발신 행은 **이벤트 canonical** 해시(서명 대상)이고,
#   수신·묘비 행은 **보관된 원문(raw)** 의 sha256 이다. 값이 다른데 이름이 같으니,
#   검증하는 쪽은 무엇과 대조해야 하는지 알 수 없다 — export/import 가 그것을 하려다 걸렸다.
#   ⇒ **구분해야 하는 것은 이름을 가른다.** 오늘 세 번째 같은 형태다(뮤테이션 번호·nonce 계보).
#   ⚠옛 행에는 이 칸이 없다. 그때는 `UNKNOWN` 으로 읽고 **검증을 건너뛰되 그 수를 보고한다**
#     — 못 잰 것을 잰 것으로 세지 않는다.
HASH_EVENT_CANONICAL = "event_canonical"
HASH_STORED_RAW = "stored_raw"
HASH_UNKNOWN = "unknown"
HASH_KINDS = (HASH_EVENT_CANONICAL, HASH_STORED_RAW)

GENESIS_LINK = "0" * 64
_ROW_HASH = "row_hash"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_row(row: dict[str, Any]) -> bytes:
    """줄의 해시 입력. `row_hash` 자신은 뺀다(자기를 포함해 자기를 해시할 수 없다)."""
    body = {k: v for k, v in row.items() if k != _ROW_HASH}
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def row_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_row(row)).hexdigest()


class Ledger:
    def __init__(self, directory: str) -> None:
        self.dir = directory
        self.path = os.path.join(directory, "ledger.jsonl")
        self.events_dir = os.path.join(directory, "events")
        self.lock_path = self.path + ".lock"   # ★사이드카 — 데이터 파일 자체를 잠그지 않는다

    # ── 읽기 ────────────────────────────────────────────────────────────────
    def rows(self) -> Iterator[dict[str, Any]]:
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError as e:
                    raise AgoraError(errors.PRECONDITION, "원장 줄 파싱 실패",
                                     {"line": lineno, "error": str(e)}) from None
                yield row

    def last(self) -> dict[str, Any] | None:
        last = None
        for row in self.rows():
            last = row
        return last

    def has(self, message_id: str, *, direction: str | None = None,
            stage: str | None = None) -> bool:
        """그 message_id 의 행이 있는가. 방향·단계를 주면 **그 조합으로** 좁힌다.

        ★좁힐 수 있어야 하는 이유: 같은 message_id 에 **뜻이 다른 행**이 여럿 있을 수 있다
          (보낸 것 `sent` · 받아 건넨 것 `delivered` · 소비한 것 `acked`).
          방향·단계를 안 보고 「있다/없다」로만 물으면 발신 기록 하나가 **수신 영수증이 이미
          있는 것처럼** 보이고, 그러면 진짜 영수증이 안 써진다(수신 증거가 조용히 빈다).
        """
        for r in self.rows():
            if r.get("message_id") != message_id:
                continue
            if direction is not None and r.get("dir") != direction:
                continue
            if stage is not None and r.get("stage") != stage:
                continue
            return True
        return False

    # ── 쓰기(append 전용) ───────────────────────────────────────────────────
    def append(self, *, direction: str, message_id: str, event_hash: str,
               stage: str, node_id: str | None = None,
               ts: str | None = None,
               hash_of: str = HASH_UNKNOWN) -> dict[str, Any]:
        if direction not in (SENT, RECV):
            raise AgoraError(errors.ARGUMENT, "방향은 sent/recv 뿐이다",
                             {"direction": direction})
        if stage not in STAGES:
            raise AgoraError(errors.ARGUMENT, "계약에 없는 단계",
                             {"stage": stage, "allowed": list(STAGES)})
        if hash_of not in HASH_KINDS + (HASH_UNKNOWN,):
            raise AgoraError(errors.ARGUMENT, "해시 종류가 계약 밖",
                             {"hash_of": hash_of, "allowed": list(HASH_KINDS)})
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        with open(self.lock_path, "a+") as lock:
            _lock.acquire(lock)
            try:
                prev = self.last()
                row = {
                    "dir": direction,
                    "message_id": message_id,
                    "hash": event_hash,
                    "prev_ledger_hash": prev[_ROW_HASH] if prev else GENESIS_LINK,
                    "node_id": node_id,
                    "ts": ts or now_iso(),
                    "stage": stage,
                    "hash_of": hash_of,
                }
                row[_ROW_HASH] = row_hash(row)
                with open(self.path, "a", encoding="utf-8") as fh:   # ★append 만
                    fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                return row
            finally:
                _lock.release(lock)

    def store_event(self, thread_id: str, message_id: str, raw: bytes) -> str:
        """이벤트 **원문**을 보관한다. 운반층에서 지워져도 여기 남는다."""
        d = os.path.join(self.events_dir, thread_id)
        os.makedirs(d, mode=0o700, exist_ok=True)
        path = os.path.join(d, message_id + ".json")
        with open(path, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        return path

    # ── 검증 ────────────────────────────────────────────────────────────────
    def verify(self) -> dict[str, Any]:
        """링크와 본문을 **둘 다** 잰다. 하나만 재면 절반은 통과한다."""
        prev_link = GENESIS_LINK
        count = 0
        for i, row in enumerate(self.rows(), 1):
            count = i
            if _ROW_HASH not in row:
                return {"ok": False, "reason": "row_hash_missing", "line": i}
            if row_hash(row) != row[_ROW_HASH]:
                # 칸 하나가 고쳐졌다 — 링크만 재는 검사는 여기를 통과시킨다.
                return {"ok": False, "reason": "row_body_altered", "line": i}
            if row.get("prev_ledger_hash") != prev_link:
                # 줄이 지워졌거나 끼워졌다.
                return {"ok": False, "reason": "chain_broken", "line": i}
            prev_link = row[_ROW_HASH]
        return {"ok": True, "rows": count, "head": prev_link}
