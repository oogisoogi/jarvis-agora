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
        self.fetch_calls = 0           # ★읽기 호출 계수 — 「바뀐 것만 읽었는가」를 재는 데 쓴다
        self.list_calls = 0
        self._by_number: dict[int, str] = {}
        self._numbers: dict[str, int] = {}
        self._updated: dict[str, str] = {}
        self.fail_next_append: str | None = None
        # ★읽기도 실패할 수 있어야 한다. 「조회가 실패한 것」을 「지워진 것」으로 적는지
        #   재려면 mock 이 읽기에서도 나쁘게 굴어야 한다(S5-4).
        self.fail_next_fetch: str | None = None
        self.fail_projection = False     # ★투영은 받았는데 화면은 안 바뀌는 상황(S7-2 실물)
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self._items = json.load(fh)
            # ★번호·갱신 시각은 저장하지 않고 **되세운다.** 저장하면 두 곳이 갈라질 수 있고,
            #   되세우면 언제나 글과 같은 말을 한다. (안 되세우면 재시작한 프로세스에는
            #   목록이 비어 보인다 — watch 재시작 픽스처가 그것을 잡았다.)
            for item in self._items:
                self.touch(item["thread_id"], item["created_at"])
            # ★번호도 이어서 센다. 안 그러면 **재시작한 프로세스가 같은 node_id 를 다시 발급**하고,
            #   그 글은 dedupe 에 「이미 본 것」으로 걸려 영영 안 온다.
            #   실물 운반층의 node_id 는 전역 고유하므로, 그렇지 않은 mock 은 거짓 초록을 만든다
            #   (watch 재시작 픽스처가 이것을 잡았다 — 새 글이 조용히 사라졌다).
            used = [int(i["node_id"].rsplit("_", 1)[-1]) for i in self._items
                    if i.get("node_id", "").startswith("MOCK_")]
            self._counter = itertools.count(max(used) + 1 if used else 1)

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
        if self.fail_next_append == "unknown_lost":
            # ★같은 code 8 인데 **저장까지 안 된** 쪽. 두 갈래를 다 열 수 있어야
            #   재조회 판정이 「올라갔다」와 「안 올라갔다」를 실제로 가르는지 잰다.
            self.fail_next_append = None
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
        self.touch(thread_id, item["created_at"])
        self._save()
        return {"node_id": item["node_id"], "url": f"mock://{item['node_id']}",
                "created_at": item["created_at"]}

    def fetch(self, *, thread_id: str | None = None, number: int | None = None,
              cursor: str | None = None, limit: int = 100) -> dict[str, Any]:
        if thread_id is None and number is not None:
            thread_id = self._by_number.get(number)
        if thread_id is None:
            raise AgoraError(errors.ARGUMENT, "thread_id 나 number 가 필요하다", None)
        self.fetch_calls += 1
        if self.fail_next_fetch == "store":
            self.fail_next_fetch = None
            raise AgoraError(errors.STORE, "조회 실패(주입)", {"retry": True})
        if self.fail_next_fetch == "empty":
            # 스레드가 통째로 안 보이는 상황 — 「전부 지워졌다」와 모양이 같다.
            self.fail_next_fetch = None
            return {"items": [], "next_cursor": None}
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

    def list_threads(self, *, updated_since: str | None = None,
                     limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        self.list_calls += 1
        rows = []
        for tid, number in sorted(self._numbers.items(), key=lambda kv: kv[1]):
            updated = self._updated.get(tid, "")
            if updated_since and updated < updated_since:
                continue
            rows.append({"number": number, "node_id": f"MOCKDISC_{number}",
                         "updated_at": updated, "title": f"thread {number}"})
        rows.sort(key=lambda r: (r["updated_at"], r["number"]))
        offset = int(cursor) if cursor else 0
        window = rows[offset:offset + limit]
        more = str(offset + limit) if offset + limit < len(rows) else None
        return {"items": window, "next_cursor": more}

    def touch(self, thread_id: str, updated_at: str) -> None:
        """스레드가 「바뀌었다」고 표시한다 — watch 픽스처가 시간을 직접 준다."""
        if thread_id not in self._numbers:
            number = len(self._numbers) + 1
            self._numbers[thread_id] = number
            self._by_number[number] = thread_id
        self._updated[thread_id] = updated_at

    def thread_status(self, *, thread_id: str) -> dict[str, Any]:
        """**투영된 것만** 반영해서 돌려준다 — mock 이 착하게 굴면 방어를 안 재게 된다.

        ★`fail_projection` 을 켜면 투영을 받아 놓고 **화면은 안 바뀐 것처럼** 답한다.
          실물에서 실제로 그랬다(투영을 아무도 안 불러 원장만 닫혀 있었다).
        """
        if self.fail_projection:
            return {"closed": False, "answered": False}
        last = [p for p in self.projections if p["thread_id"] == thread_id]
        state = last[-1]["state"] if last else "open"
        return {"closed": state == "closed", "answered": state in ("solved", "closed")}

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
            # ★갱신 시각도 함께 되돌린다. 안 그러면 목록은 「지금」이라고 말하고
            #   본문은 옛날이라고 말해, watch 픽스처가 시간을 못 정한다.
            self.touch(thread_id, created_at)
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
