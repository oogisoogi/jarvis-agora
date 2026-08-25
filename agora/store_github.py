"""GitHub Discussions 운반층(설계 §D1 · S4-1).

★**운반층은 믿지 않는다.** 여기서 하는 일은 「올리고 받아 오는 것」뿐이고,
  무엇이 유효한가는 reducer 가 정한다. 그래서 이 파일에는 검증이 없다.

★`gh` 를 subprocess 로 부르는 자리를 **transport 한 곳**으로 모았다. 두 가지를 얻는다:
  ⑴ 페이지 순회·답글 순회 같은 **논리**를 네트워크 없이 시험할 수 있다(가짜 transport).
  ⑵ 실제 호출 자리가 하나뿐이라 한도·backoff(S4-2)를 한 곳에서 걸 수 있다.
  ⚠대가: 가짜 transport 로 초록이 나도 그것은 **논리가 맞다**는 뜻이지
    「GitHub 이 그렇게 답한다」는 뜻이 아니다. 실물 대조는 드라이런(S7)이 한다.

★스레드 주소는 우리 `thread_id`(128비트 hex)다. GitHub 의 번호가 아니다.
  둘을 잇는 방법은 **본문 검색**뿐이다(우리가 만든 스레드의 genesis 본문에 그 값이 들어 있다).
  그래서 조회는 한 번 찾은 번호를 **캐시**한다 — 매번 검색하면 한도를 검색으로 태운다.
"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any

from agora import errors
from agora.errors import AgoraError

# ★한도에 걸린 것은 **벽이 아니라 신호**다(§10). 429·403(secondary rate limit)은 「하지 마라」가
#   아니라 「지금은 말고」이므로 **기다렸다 다시** 한다. 반대로 문법 오류·권한 없음은 기다려도 그대로다.
#   둘을 안 가르면 ⑴영영 못 고칠 것을 계속 두드리거나 ⑵고칠 필요 없는 것을 실패로 올린다.
RATE_LIMIT_MARKERS = ("rate limit", "ratelimit", "rate_limited", "429",
                      "secondary rate", "abuse detection")

# 대기는 **곱으로** 늘린다. 같은 간격으로 재시도하면 한도가 풀리기 전에 시도를 다 써 버린다.
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_FACTOR = 2.0
BACKOFF_ATTEMPTS = 4


def is_rate_limited(err: AgoraError) -> bool:
    """이 실패가 「지금은 말고」인가 — 문자열로 판별한다(gh 는 상태 코드를 말로 준다)."""
    blob = json.dumps(err.detail, ensure_ascii=False, default=str).lower()
    return any(marker in blob for marker in RATE_LIMIT_MARKERS)


_LOOKUP = """
query($q: String!) {
  search(query: $q, type: DISCUSSION, first: 10) {
    nodes { ... on Discussion { id number title } }
  }
}
"""

_REPO = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) { id }
}
"""

_THREAD = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) {
      id number title createdAt body
      comments(first: 50, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id body createdAt
          replies(first: 50) {
            pageInfo { hasNextPage endCursor }
            nodes { id body createdAt }
          }
        }
      }
    }
  }
}
"""

_REPLIES = """
query($id: ID!, $cursor: String) {
  node(id: $id) {
    ... on DiscussionComment {
      replies(first: 50, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { id body createdAt }
      }
    }
  }
}
"""

_CREATE = """
mutation($repo: ID!, $category: ID!, $title: String!, $body: String!) {
  createDiscussion(input: {repositoryId: $repo, categoryId: $category,
                           title: $title, body: $body}) {
    discussion { id number url createdAt }
  }
}
"""

_COMMENT = """
mutation($discussion: ID!, $body: String!) {
  addDiscussionComment(input: {discussionId: $discussion, body: $body}) {
    comment { id url createdAt }
  }
}
"""


def gh_transport(query: str, variables: dict[str, Any], *,
                 timeout: int = 60) -> dict[str, Any]:
    """실제 호출 자리 — `gh api graphql`. 여기 말고는 네트워크를 만지지 않는다."""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is None:
            continue
        flag = "-F" if type(value) is int else "-f"
        cmd += [flag, f"{key}={value}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        err = proc.stderr.strip()[:300]
        # ★저장층 오류는 **재시도 가능**(7)이다 — 계약 위반(10)과 섞지 않는다.
        raise AgoraError(errors.STORE, "저장층 호출 실패", {"stderr": err})
    try:
        doc = json.loads(proc.stdout)
    except ValueError as e:
        raise AgoraError(errors.STORE, "저장층 응답이 JSON 이 아니다",
                         {"error": str(e)}) from None
    if doc.get("errors"):
        raise AgoraError(errors.STORE, "저장층이 오류를 돌려줬다",
                         {"errors": doc["errors"][:3]})
    return doc.get("data") or {}


class GitHubStore:
    def __init__(self, owner: str, name: str, categories: dict[str, str],
                 transport: Any = None, sleep: Any = None,
                 attempts: int = BACKOFF_ATTEMPTS) -> None:
        self.owner = owner
        self.name = name
        self._categories = dict(categories)      # 이름 → category id(S4-0 실측값)
        self._transport = transport or gh_transport
        self._sleep = sleep or time.sleep
        self._attempts = max(1, attempts)
        self.waits: list[float] = []             # 실제로 기다린 간격 — 시험이 이것을 본다
        self._numbers: dict[str, int] = {}       # thread_id → discussion number
        self._ids: dict[str, str] = {}           # thread_id → discussion node id
        self.calls = 0                           # 호출 계수 — 한도 이야기의 시작점(S4-2)

    # ── 내부 ────────────────────────────────────────────────────────────────
    def _run(self, query: str, **variables: Any) -> dict[str, Any]:
        """한 번 부른다. 한도에 걸리면 곱으로 늘어나는 간격을 두고 다시 부른다.

        ★호출 계수(`calls`)는 **재시도까지 센다.** 비용 모델이 「성공한 횟수」가 아니라
          「실제로 쓴 횟수」를 알아야 하기 때문이다.
        """
        delay = BACKOFF_BASE_SECONDS
        last: AgoraError | None = None
        for attempt in range(self._attempts):
            self.calls += 1
            try:
                return self._transport(query, variables)
            except AgoraError as e:
                if not is_rate_limited(e):
                    raise            # 기다려도 그대로인 실패는 그대로 올린다
                last = e
                if attempt == self._attempts - 1:
                    break
                self.waits.append(delay)
                self._sleep(delay)
                delay *= BACKOFF_FACTOR
        raise AgoraError(errors.STORE, "한도에 걸렸고 재시도도 실패했다",
                         {"attempts": self._attempts, "waited": list(self.waits),
                          "last": (last.detail if last else None)})

    def _locate(self, thread_id: str) -> tuple[int, str]:
        """thread_id → (번호, node id). 한 번 찾으면 캐시한다."""
        if thread_id in self._numbers:
            return self._numbers[thread_id], self._ids[thread_id]
        q = f'repo:{self.owner}/{self.name} in:body "{thread_id}"'
        data = self._run(_LOOKUP, q=q)
        nodes = ((data.get("search") or {}).get("nodes") or [])
        if not nodes:
            raise AgoraError(errors.STORE, "스레드를 찾지 못했다",
                             {"thread_id": thread_id})
        self._numbers[thread_id] = nodes[0]["number"]
        self._ids[thread_id] = nodes[0]["id"]
        return nodes[0]["number"], nodes[0]["id"]

    def _all_replies(self, comment: dict[str, Any]) -> list[dict[str, Any]]:
        """한 댓글의 답글을 **끝까지** 따라간다.

        ★답글도 페이지가 있다. 첫 페이지만 읽으면 대화의 뒷부분이 조용히 사라진다 —
          화면은 정상으로 보이고 상태만 틀린다.
        """
        block = comment.get("replies") or {}
        rows = list(block.get("nodes") or [])
        page = block.get("pageInfo") or {}
        while page.get("hasNextPage"):
            data = self._run(_REPLIES, id=comment["id"], cursor=page.get("endCursor"))
            block = ((data.get("node") or {}).get("replies") or {})
            rows.extend(block.get("nodes") or [])
            page = block.get("pageInfo") or {}
        return rows

    # ── Store 계약 ──────────────────────────────────────────────────────────
    def append(self, *, thread_id: str, category: str, title: str,
               body: str, is_genesis: bool) -> dict[str, Any]:
        if is_genesis:
            cat = self._categories.get(category)
            if not cat:
                raise AgoraError(errors.PRECONDITION, "카테고리 id 를 모른다",
                                 {"category": category})
            repo = (self._run(_REPO, owner=self.owner, name=self.name)
                    .get("repository") or {})
            if not repo.get("id"):
                raise AgoraError(errors.STORE, "저장소 id 를 못 얻었다", None)
            data = self._run(_CREATE, repo=repo["id"], category=cat,
                             title=title, body=body)
            node = ((data.get("createDiscussion") or {}).get("discussion") or {})
            if not node.get("id"):
                # 성공도 실패도 단정하지 않는다 — 재조회 후에만 판정한다(S4-3).
                raise AgoraError(errors.UNKNOWN_COMMIT,
                                 "생성 결과가 비었다 — 재조회 후 판정하라",
                                 {"thread_id": thread_id})
            self._numbers[thread_id] = node["number"]
            self._ids[thread_id] = node["id"]
            return {"node_id": node["id"], "url": node.get("url"),
                    "created_at": node.get("createdAt")}

        _number, disc_id = self._locate(thread_id)
        data = self._run(_COMMENT, discussion=disc_id, body=body)
        node = ((data.get("addDiscussionComment") or {}).get("comment") or {})
        if not node.get("id"):
            raise AgoraError(errors.UNKNOWN_COMMIT,
                             "댓글 결과가 비었다 — 재조회 후 판정하라",
                             {"thread_id": thread_id})
        return {"node_id": node["id"], "url": node.get("url"),
                "created_at": node.get("createdAt")}

    def fetch(self, *, thread_id: str, cursor: str | None = None,
              limit: int = 100) -> dict[str, Any]:
        """스레드의 **전건**(본문 + 댓글 + 답글)을 모은다.

        ★`cursor` 는 계약상 받지만 여기서는 **안 쪼갠다.** 한 스레드의 이벤트는 서로 `prev`
          로 엮여 있어서 일부만 주면 reducer 가 「닿지 않는 것」으로 잘못 읽는다.
          쪼개는 것은 스레드 **목록**(threads)의 몫이다.
        """
        number, _id = self._locate(thread_id)
        rows: list[dict[str, Any]] = []
        page_cursor: str | None = None
        first = True
        while True:
            data = self._run(_THREAD, owner=self.owner, name=self.name,
                             number=number, cursor=page_cursor)
            disc = ((data.get("repository") or {}).get("discussion") or {})
            if not disc:
                raise AgoraError(errors.STORE, "스레드를 읽지 못했다",
                                 {"thread_id": thread_id})
            if first:
                rows.append({"node_id": disc["id"], "thread_id": thread_id,
                             "body": disc.get("body") or "",
                             "created_at": disc.get("createdAt"),
                             "is_genesis": True})
                first = False
            block = disc.get("comments") or {}
            for comment in block.get("nodes") or []:
                rows.append({"node_id": comment["id"], "thread_id": thread_id,
                             "body": comment.get("body") or "",
                             "created_at": comment.get("createdAt"),
                             "is_genesis": False})
                for reply in self._all_replies(comment):
                    rows.append({"node_id": reply["id"], "thread_id": thread_id,
                                 "body": reply.get("body") or "",
                                 "created_at": reply.get("createdAt"),
                                 "is_genesis": False})
            page = block.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            page_cursor = page.get("endCursor")
        return {"items": rows, "next_cursor": None}

    def project(self, *, thread_id: str, state: str,
                answer_node_id: str | None = None) -> dict[str, Any]:
        """투영은 **아직 하지 않는다**(S4-1 범위 밖).

        ★조용히 성공을 돌려주지 않는다. 「반영했다」는 거짓이 화면과 상태를 갈라놓는다.
        """
        raise AgoraError(errors.PRECONDITION, "투영은 아직 구현되지 않았다",
                         {"reason": "slice_not_built", "slice": "S4-4"})

    def categories(self) -> dict[str, Any]:
        return {name: {"id": cid, "is_answerable": name == "problem"}
                for name, cid in self._categories.items()}
