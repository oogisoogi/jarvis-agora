"""저장층 인터페이스 — 운반층은 **믿지 않는다**.

설계 §D1(H-2·H-4): GitHub 은 비신뢰 운반층이다. 누구든 웹에서 글을 쓰거나 API 로 직접
밀어 넣을 수 있고, 우리 CLI 는 그것을 막을 수 없다. 그래서 이 인터페이스는
「쓰기를 거부한다」를 약속하지 않는다 — **읽어 온 것을 reducer 가 걸러낸다**가 계약이다.

인터페이스가 좁은 이유: 저장층을 갈아 끼울 때 갈아 낄 면이 작아야 한다.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Store(Protocol):
    def append(self, *, thread_id: str, category: str, title: str,
               body: str, is_genesis: bool) -> dict[str, Any]:
        """운반층에 한 건 올린다. 반환 = {node_id, url, created_at}.

        ⚠성공 여부가 불분명하면 code 8(unknown_commit)로 올린다 — 성공도 실패도 단정하지 않는다.
        """
        ...

    def fetch(self, *, thread_id: str, cursor: str | None = None,
              limit: int = 100) -> dict[str, Any]:
        """{items: [{node_id, created_at, body, kind_hint}], next_cursor}.

        **top-level 과 reply 를 모두** 돌려줘야 한다 — 한쪽만 돌면 누락이 조용히 생긴다.
        """
        ...

    def project(self, *, thread_id: str, state: str,
                answer_node_id: str | None = None) -> dict[str, Any]:
        """reducer 가 계산한 상태를 운반층 화면에 **반영만** 한다(라벨·닫기·answer 표시).

        ★이것은 **투영**이지 입력이 아니다. 여기서 실패해도 프로토콜 상태는 그대로다.
        """
        ...

    def categories(self) -> dict[str, Any]:
        """{name: {id, is_answerable}} — 카테고리 실측용."""
        ...
