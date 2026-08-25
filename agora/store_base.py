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

    def fetch(self, *, thread_id: str | None = None, number: int | None = None,
              cursor: str | None = None, limit: int = 100) -> dict[str, Any]:
        """{items: [{node_id, created_at, body, kind_hint}], next_cursor}.

        **top-level 과 reply 를 모두** 돌려줘야 한다 — 한쪽만 돌면 누락이 조용히 생긴다.

        ★`number` 는 **watch 가 목록에서 이미 알아낸 번호**를 건네는 자리다(S5-2).
          있으면 스레드를 찾는 검색 한 번이 통째로 사라진다 — 주기마다 도는 경로라 그 한 번이 크다.
        """
        ...

    def project(self, *, thread_id: str, state: str,
                answer_node_id: str | None = None) -> dict[str, Any]:
        """reducer 가 계산한 상태를 운반층 화면에 **반영만** 한다(라벨·닫기·answer 표시).

        ★이것은 **투영**이지 입력이 아니다. 여기서 실패해도 프로토콜 상태는 그대로다.
        """
        ...

    def list_threads(self, *, updated_since: str | None = None,
                     limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        """{items: [{number, node_id, updated_at, title}], next_cursor}.

        ★**watch 를 위해 신설했다(S5-2).** 인터페이스를 넓히는 것은 가볍지 않은 결정이라
          이유를 적어 둔다: S4-2 의 실측이 「매 주기 전 스레드 읽기」로는
          참가자 한 명만으로도 시간당 한도를 넘는다는 것을 보였다(60×100 = 6000 > 5000).
          그래서 watch 는 **목록으로 바뀐 것을 먼저 고르고 그것만 읽어야** 한다.
          목록을 얻을 방법이 없으면 그 제약을 지킬 수 없다.

        ★`thread_id` 를 안 돌려준다. 그 값은 genesis **본문 안**에 있어서, 목록에 실으려면
          스레드 100건의 본문을 매 주기 끌어와야 한다(점수는 그대로여도 대역폭이 커진다).
          그래서 목록의 단위는 **번호**이고, `thread_id` 는 실제로 읽을 때 본문에서 나온다.
        """
        ...

    def categories(self) -> dict[str, Any]:
        """{name: {id, is_answerable}} — 카테고리 실측용."""
        ...
