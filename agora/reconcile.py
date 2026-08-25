"""reconcile — 운반층에서 **사라진 글**을 원장에 tombstone 으로 남긴다(설계 §5 H-5 · §8 FR-8/15).

★운반층은 댓글을 고치고 지운다(§D1). 그래서 우리 원장은 「무엇을 받았는가」뿐 아니라
  **「받은 것이 지금도 거기 있는가」**를 따로 적어야 한다. 지워졌다는 사실 자체가 사건이다.

★**tombstone 은 삭제가 아니다.** 보관된 원문(`events/<thread_id>/<message_id>.json`)은
  그대로 둔다 — 지워졌다는 기록을 남기면서 그 내용을 함께 지우면, 무엇이 지워졌는지
  아무도 못 댄다. 원장이 「사라졌다」고만 말하고 무엇이 사라졌는지는 못 말하는 셈이다.

★★**이 파일에서 가장 위험한 것은 「못 봤다」를 「지워졌다」로 적는 것이다.**
  조회가 실패했을 때·페이지를 덜 돌았을 때·응답이 비었을 때 그 차이를 안 재면,
  **원장이 거짓을 말한다.** 그리고 원장은 append-only 라 그 거짓을 지울 수 없다.
  그래서 판정은 두 값으로 나뉜다:
      `compared`      … 전 페이지를 끝까지 보고 비교했다 → 없는 것은 tombstone
      `inconclusive`  … 비교할 자격이 없다 → **아무것도 적지 않는다**(사유를 함께 돌려준다)
  ⇒ S4-3(「저장 성공 불명은 재조회할 때까지 아무 말도 하지 않는다」)과 **같은 규율의 반대편**이다.

★**아직 아무도 이 함수를 부르지 않는다**(S5-4 시점). 호출 자리는 `watch` 인데 그 CLI 는
  아직 미구현이다(S6-2). 안 한 것을 한 것처럼 적지 않으려고 여기 남긴다.

★**주기 정책 = 확정됨**(master 결정 2026-08-25 · S5-5 검수 회신). 둘 다 둔다:
  ⑴ `watch` 루프 안에서 **매 N회 폴링마다 1회**(`RECONCILE_EVERY` 기본 **20** · 설정 가능)
  ⑵ 요청 시 도는 **수동 `agora reconcile` CLI**
  근거: tombstone·누락은 주기 없이는 못 잡고, 비용은 **폴링 1회분(API 1회)**이라 상시 켜도 싸다.
  ⇒ 배선은 S6-2 이고, **기본값 20 은 케이스로 고정한다**(바뀌면 적색 — 조용히 흘러가지 않는다).
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from agora import errors, ledger as ledger_mod, spool as spool_mod
from agora.errors import AgoraError

TOMBSTONE = "tombstone"
DIRECTION = "recv"
COMPARED = "compared"
INCONCLUSIVE = "inconclusive"
MAX_PAGES = 100

# ★watch 가 이 대조를 도는 주기 — **몇 회 폴링마다 한 번**인가(master 결정 2026-08-25).
#   여기 한 곳에만 둔다. watch 쪽에 숫자를 또 적으면 두 곳이 갈라지고, 갈라진 날
#   「20 이라고 알고 있는데 실제로는 5」 같은 상태가 아무 소리 없이 성립한다.
RECONCILE_EVERY = 20


def local_message_ids(*, ledger: Any, thread_id: str) -> list[str]:
    """우리가 **보관한** 것들. 원장 행이 아니라 원문 파일을 센다.

    ★원장 행으로 세면 「적혀 있으니 있다」가 되어 자기참조가 된다(§8 고스트).
      파일은 내용을 갖고 있어서, 비교 결과를 원장에 적을 때 **무엇이 사라졌는지**까지 댈 수 있다.
    """
    d = os.path.join(ledger.events_dir, thread_id)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return sorted(n[:-len(".json")] for n in names if n.endswith(".json"))


def remote_message_ids(*, store: Any, thread_id: str,
                       max_pages: int = MAX_PAGES) -> dict[str, Any]:
    """운반층에 **지금 있는** message_id 들. 페이지를 끝까지 돈다.

    ★끝까지 못 돌면 그 사실을 돌려준다(`complete=False`). 조용히 자르면 뒤쪽 페이지의 글이
      전부 「사라진 것」이 된다 — 한 번의 절단이 원장에 지워지지 않는 거짓을 남긴다.
    """
    found: set[str] = set()
    seen_cursors: set[str] = set()
    cursor = None
    pages = 0
    items = 0
    while True:
        page = store.fetch(thread_id=thread_id, cursor=cursor)
        pages += 1
        for row in page["items"]:
            items += 1
            body = row.get("body") or ""
            for mid in _ids_in(body):
                found.add(mid)
        cursor = page.get("next_cursor")
        if not cursor:
            return {"ids": found, "complete": True, "pages": pages, "items": items}
        if cursor in seen_cursors:
            # 커서가 제자리를 돈다 — 운반층을 믿지 않는다는 말은 이런 것도 막는다는 뜻이다.
            raise AgoraError(errors.STORE, "커서가 되돌아온다 — 순회를 멈춘다",
                             {"thread_id": thread_id, "cursor": cursor})
        seen_cursors.add(cursor)
        if pages >= max_pages:
            return {"ids": found, "complete": False, "pages": pages, "items": items}


def _ids_in(body: str) -> list[str]:
    """본문에 등장하는 message_id 후보. **본문을 해석하지 않는다** — 있는지만 본다."""
    import re
    return re.findall(r"[0-9a-f]{32}", body)


def reconcile(*, store: Any, ledger: Any, thread_id: str, spool: Any = None,
              max_pages: int = MAX_PAGES) -> dict[str, Any]:
    """로컬 보관본과 운반층을 대조하고, **비교할 자격이 있을 때만** tombstone 을 적는다."""
    local = local_message_ids(ledger=ledger, thread_id=thread_id)
    remote = remote_message_ids(store=store, thread_id=thread_id, max_pages=max_pages)

    if not remote["complete"]:
        return _no_verdict(local, remote, "pages_truncated")
    if remote["items"] == 0:
        # ★스레드가 통째로 안 보인다. 「전부 지워졌다」와 「조회가 실패했다」가 **같은 모양**이다.
        #   구별할 수 없으므로 판정하지 않는다 — 사람이 보게 사유를 남긴다.
        return _no_verdict(local, remote, "empty_response")

    missing = [mid for mid in local if mid not in remote["ids"]]
    written: list[dict[str, Any]] = []
    for mid in missing:
        if ledger.has(mid, direction=DIRECTION, stage=TOMBSTONE):
            continue          # ★한 번만 적는다 — 매 주기 다시 세면 원장이 부풀기만 한다
        raw = _read_raw(ledger, thread_id, mid)
        written.append(ledger.append(direction=DIRECTION, message_id=mid,
                                     event_hash=hashlib.sha256(raw).hexdigest(),
                                     stage=TOMBSTONE, node_id=None,
                                     hash_of=ledger_mod.HASH_STORED_RAW))
    return {"verdict": COMPARED, "thread_id": thread_id,
            "local": len(local), "remote": remote["items"], "pages": remote["pages"],
            "missing": missing, "tombstoned": written,
            "acked_but_gone": _acked_but_gone(spool, missing)}


def _no_verdict(local: list[str], remote: dict[str, Any], why: str) -> dict[str, Any]:
    """판정하지 않는다. **적지 않았다는 것까지** 결과에 적는다."""
    return {"verdict": INCONCLUSIVE, "why": why, "local": len(local),
            "remote": remote["items"], "pages": remote["pages"],
            "missing": [], "tombstoned": [], "acked_but_gone": []}


def _read_raw(ledger: Any, thread_id: str, message_id: str) -> bytes:
    with open(os.path.join(ledger.events_dir, thread_id, message_id + ".json"), "rb") as fh:
        return fh.read()


def _acked_but_gone(spool: Any, missing: list[str]) -> list[str]:
    """**소비까지 한 글이 운반층에서 사라진** 경우를 따로 센다.

    ★수신 증거(영수증)는 남고 운반층 실물만 없는 상태다. 이것을 「그냥 사라진 글」과 뭉치면
      「우리가 읽고 답까지 한 글이 지워졌다」는 가장 말이 되는 사건이 계수에서 사라진다.
    """
    if spool is None:
        return []
    out = []
    for mid in missing:
        row = spool.by_message(mid)
        if row and row.get("stage") == spool_mod.ACKED:
            out.append(mid)
    return out
