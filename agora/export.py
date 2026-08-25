"""export · import — 원장과 이벤트 원문의 반출입(설계 §4 CLI 예외 · S6-2).

★**무엇을 담고, 무엇을 절대 안 담는가**가 이 파일의 전부다.
  담는 것: 원장 줄(해시 사슬)과 **보관된 이벤트 원문**.
  ⛔안 담는 것: 개인키·토큰·참가자 설정 파일. 반출물은 남에게 건네지는 물건이고,
    한 번 건넨 것은 되부를 수 없다. 그래서 「담지 않았다」를 **믿지 않고 검사한다**
    (내보내기 전에 스캔하고, 걸리면 파일을 만들지 않는다).

★**들일 때는 사슬을 먼저 본다.** 원장은 append-only 해시 사슬이라, 깨진 원장을 들이면
  그 뒤로 쓰는 모든 줄이 깨진 토대 위에 쌓인다. 검증에 실패하면 **아무것도 쓰지 않는다** —
  절반만 들어간 원장은 없는 것보다 나쁘다(무엇이 들어왔는지 아무도 못 댄다).

★**이어붙이지 않는다.** 원장은 참가자 한 사람의 사슬이다. 두 사슬을 이으면 `prev` 가 맞지 않아
  둘 다 깨진다. 이으려면 새로 다시 쓰는 수밖에 없는데, **다시 쓸 수 있는 원장은 원장이 아니다.**
  ⇒ 대상이 비어 있을 때만 복원한다(아니면 code 2). 기계를 옮기거나 백업을 되살리는 용도다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from typing import Any

from agora import errors
from agora.errors import AgoraError
from agora.ledger import (
    GENESIS_LINK, HASH_STORED_RAW, HASH_UNKNOWN, Ledger, row_hash,
)

FORMAT_VERSION = 1

# 반출물에 있어서는 안 되는 것. **모양으로** 잡는다 — 이름으로 거르면 파일명을 바꾼 것이 지나간다.
_SECRET_SHAPES = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bxox[abps]-[A-Za-z0-9-]{10,}"),
)


def _scan_secrets(text: str) -> list[str]:
    """비밀의 **모양**이 보이면 이름을 돌려준다. 값은 절대 돌려주지 않는다."""
    return [p.pattern[:24] for p in _SECRET_SHAPES if p.search(text)]


def build(*, directory: str) -> dict[str, Any]:
    """반출물을 만든다(파일로 쓰지는 않는다 — 쓰는 것은 `dump` 다)."""
    ledger = Ledger(directory)
    rows = list(ledger.rows())
    events: dict[str, str] = {}
    for thread_id, message_id, raw in _walk_events(ledger):
        events[f"{thread_id}/{message_id}"] = base64.b64encode(raw).decode("ascii")
    doc = {"v": FORMAT_VERSION, "ledger": rows, "events": events,
           "counts": {"ledger_rows": len(rows), "events": len(events)}}
    return doc


def _walk_events(ledger: Ledger) -> Any:
    root = ledger.events_dir
    if not os.path.isdir(root):
        return
    for thread_id in sorted(os.listdir(root)):
        d = os.path.join(root, thread_id)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(d, name), "rb") as fh:
                yield thread_id, name[:-len(".json")], fh.read()


def dump(*, directory: str, out_path: str) -> dict[str, Any]:
    """반출물을 파일로 쓴다 — **비밀 스캔을 통과했을 때만.**

    ★스캔을 쓰기 **전에** 한다. 쓰고 나서 지우는 순서였다면, 그 사이에 죽은 프로세스가
      비밀이 든 파일을 남긴다. 「지웠으니 괜찮다」는 프로세스가 살아 있을 때만 참이다.
    """
    doc = build(directory=directory)
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True)
    # ★**직렬화된 문자열만 보면 아무것도 못 본다.** 원문은 base64 로 담기므로 비밀의 모양이
    #   그 안에서 사라진다 — 처음 짠 스캔이 정확히 그래서 무용지물이었고, 시험이 그것을 잡았다.
    #   ⇒ **디코드한 원문**을 함께 본다. 「검사했다」는 검사 대상이 맞을 때만 참이다.
    found = _scan_secrets(text)
    for value in doc["events"].values():
        try:
            found += _scan_secrets(base64.b64decode(value).decode("utf-8", "replace"))
        except Exception:      # noqa: BLE001 — 못 읽는 원문은 스캔 대상이 아니다
            continue
    found = sorted(set(found))
    if found:
        raise AgoraError(errors.GATE_REJECT, "반출물에 비밀 모양이 있다 — 파일을 만들지 않는다",
                         {"patterns": found, "count": len(found)})
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    return {"path_name": os.path.basename(out_path), **doc["counts"],
            "secret_scan": "clean"}


def verify_doc(doc: Any) -> dict[str, Any]:
    """반출물 자체를 검증한다 — **들이기 전에.** 세 가지를 본다.

    ⑴ 원장 사슬(링크·본문 둘 다) ⑵ 원문의 해시가 원장 행과 맞는가
    ⑶ 원장이 가리키는 원문이 실제로 들어 있는가.
    ★⑵는 **무엇의 해시인지 아는 행에서만** 한다(`hash_of`). 모르면 못 잰 것으로 세고 그 수를 돌려준다 —
      옛 반출물을 「검증했다」고 적으면 그 문장이 거짓이 된다.
    """
    if type(doc) is not dict or doc.get("v") != FORMAT_VERSION:
        return {"ok": False, "reason": "format", "want": FORMAT_VERSION}
    rows = doc.get("ledger")
    events = doc.get("events")
    if type(rows) is not list or type(events) is not dict:
        return {"ok": False, "reason": "shape"}

    prev_link = GENESIS_LINK
    for i, row in enumerate(rows, 1):
        if type(row) is not dict or "row_hash" not in row:
            return {"ok": False, "reason": "row_hash_missing", "line": i}
        if row_hash(row) != row["row_hash"]:
            return {"ok": False, "reason": "row_body_altered", "line": i}
        if row.get("prev_ledger_hash") != prev_link:
            return {"ok": False, "reason": "chain_broken", "line": i}
        prev_link = row["row_hash"]

    checked = 0
    unknown = 0
    for i, row in enumerate(rows, 1):
        kind = row.get("hash_of", HASH_UNKNOWN)
        if kind != HASH_STORED_RAW:
            unknown += 1          # 발신 행(canonical)·옛 행 — 원문 대조 대상이 아니다
            continue
        raw = _find_event(events, row.get("message_id"))
        if raw is None:
            return {"ok": False, "reason": "event_missing", "line": i}
        if hashlib.sha256(raw).hexdigest() != row.get("hash"):
            return {"ok": False, "reason": "event_hash_mismatch", "line": i}
        checked += 1
    return {"ok": True, "rows": len(rows), "events": len(events),
            "hash_checked": checked, "hash_not_applicable": unknown}


def _find_event(events: dict[str, str], message_id: str | None) -> bytes | None:
    if not message_id:
        return None
    for key, value in events.items():
        if key.endswith("/" + message_id):
            try:
                return base64.b64decode(value)
            except Exception:      # noqa: BLE001 — 못 읽으면 없는 것과 같다
                return None
    return None


def load(*, doc: Any, directory: str) -> dict[str, Any]:
    """반출물을 **빈 곳에** 복원한다. 검증 실패면 아무것도 쓰지 않는다."""
    verdict = verify_doc(doc)
    if not verdict["ok"]:
        raise AgoraError(errors.PRECONDITION, "반출물 검증 실패 — 아무것도 들이지 않는다",
                         verdict)
    ledger = Ledger(directory)
    if os.path.exists(ledger.path) and list(ledger.rows()):
        # ★이어붙이면 `prev` 가 맞지 않아 두 사슬이 다 깨진다(위 머리말 참조).
        raise AgoraError(errors.PRECONDITION, "여기 이미 원장이 있다 — 이어붙이지 않는다",
                         {"reason": "ledger_not_empty"})

    os.makedirs(directory, mode=0o700, exist_ok=True)
    for key, value in doc["events"].items():
        thread_id, _, message_id = key.partition("/")
        ledger.store_event(thread_id, message_id, base64.b64decode(value))
    with open(ledger.path, "w", encoding="utf-8") as fh:
        for row in doc["ledger"]:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    after = ledger.verify()
    if not after["ok"]:
        # 쓰고 나서 깨졌다면 우리 쓰기가 원인이다 — 조용히 두지 않는다.
        raise AgoraError(errors.PRECONDITION, "복원 후 사슬이 깨졌다", after)
    return {"restored_rows": after["rows"], "events": len(doc["events"]),
            "verify": after, "source": verdict}
