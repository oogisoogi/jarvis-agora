"""mock 저장층 — **비신뢰 운반층을 흉내낸다.**

★단순한 저장소가 아니다. reducer 를 시험하려면 운반층이 **나쁘게 굴 수 있어야** 한다:
  서명 없는 글, 중복, 뒤바뀐 순서, 사라진 글. 그래서 주입 손잡이를 갖는다.
  「착한 mock」으로만 시험하면 reducer 의 방어를 한 번도 안 재게 된다.
"""

from __future__ import annotations

import itertools
import json
import os
from typing import Any

from agora import errors
from agora.errors import AgoraError
from agora.ledger import now_iso


class MockStore:
    def __init__(self, path: str | None = None,
                 answerable: tuple[str, ...] = ("problem",)) -> None:
        self.path = path
        self._items: list[dict[str, Any]] = []
        self._counter = itertools.count(1)
        self._answerable = set(answerable)
        self.projections: list[dict[str, Any]] = []
        self.append_calls = 0          # ★쓰기 호출 계수 — 「차단했으면 0」을 재는 데 쓴다
        self.fail_next_append: str | None = None
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self._items = json.load(fh)

    # ── Store 계약 ──────────────────────────────────────────────────────────
    def append(self, *, thread_id: str, category: str, title: str,
               body: str, is_genesis: bool) -> dict[str, Any]:
        self.append_calls += 1
        if self.fail_next_append == "store":
            self.fail_next_append = None
            raise AgoraError(errors.STORE, "저장층 오류(주입)", {"retry": True})
        if self.fail_next_append == "unknown":
            self.fail_next_append = None
            # 저장은 됐는데 응답이 유실된 상황 — 성공으로도 실패로도 단정하지 않는다.
            self._record(thread_id, category, title, body, is_genesis)
            raise AgoraError(errors.UNKNOWN_COMMIT, "저장 성공 불명 — 재조회 후 판정하라",
                             {"thread_id": thread_id})
        return self._record(thread_id, category, title, body, is_genesis)

    def _record(self, thread_id: str, category: str, title: str,
                body: str, is_genesis: bool) -> dict[str, Any]:
        item = {
            "node_id": f"MOCK_{next(self._counter):06d}",
            "thread_id": thread_id,
            "category": category,
            "title": title,
            "body": body,
            "is_genesis": is_genesis,
            "created_at": now_iso(),
        }
        self._items.append(item)
        self._save()
        return {"node_id": item["node_id"], "url": f"mock://{item['node_id']}",
                "created_at": item["created_at"]}

    def fetch(self, *, thread_id: str, cursor: str | None = None,
              limit: int = 100) -> dict[str, Any]:
        rows = [i for i in self._items if i["thread_id"] == thread_id]
        start = int(cursor) if cursor else 0
        page = rows[start:start + limit]
        nxt = str(start + limit) if start + limit < len(rows) else None
        return {"items": page, "next_cursor": nxt}

    def project(self, *, thread_id: str, state: str,
                answer_node_id: str | None = None) -> dict[str, Any]:
        self.projections.append({"thread_id": thread_id, "state": state,
                                 "answer": answer_node_id})
        return {"ok": True}

    def categories(self) -> dict[str, Any]:
        return {name: {"id": f"MOCKCAT_{name}", "is_answerable": name in self._answerable}
                for name in ("problem", "knowhow", "debate")}

    # ── 비신뢰 운반층 흉내 — 주입 손잡이 ────────────────────────────────────
    def inject_raw(self, *, thread_id: str, body: str, category: str = "debate",
                   title: str = "injected", is_genesis: bool = False,
                   created_at: str | None = None) -> dict[str, Any]:
        """우리 게이트를 **거치지 않고** 운반층에 글이 올라온 상황.

        웹 댓글·직접 API 쓰기·구버전 클라이언트가 전부 이 모양이다.
        """
        item = self._record(thread_id, category, title, body, is_genesis)
        if created_at:
            self._items[-1]["created_at"] = created_at
            self._save()
        return item

    def shuffle(self, seed: int = 0) -> None:
        """페이지 경계·정렬 가정에 기대는 코드를 흔든다."""
        import random
        random.Random(seed).shuffle(self._items)
        self._save()

    def delete_node(self, node_id: str) -> bool:
        """운반층에서 글이 **사라지는** 상황(tombstone 검출용)."""
        before = len(self._items)
        self._items = [i for i in self._items if i["node_id"] != node_id]
        self._save()
        return len(self._items) != before

    def _save(self) -> None:
        if not self.path:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._items, fh, ensure_ascii=False)
        os.replace(tmp, self.path)
