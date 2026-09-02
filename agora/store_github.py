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

import fcntl
import json
import os
import subprocess
import time
from contextlib import contextmanager
from typing import Any, Iterator

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


BINDINGS_FILENAME = "thread-bindings.json"

# ★H1 라운드 2(codex 2026-08-26 재검증) — 검색은 **끝까지** 본다. 첫 10건만 보면 원본이 결과 밖으로
#   밀린 가짜 응답에서 복제본을 결박한다(재현: `(100, D100)` 결박). 페이지 수에 상한을 두는 이유는
#   운반층이 무엇이든 실어 오기 때문이다 — 상한에 닿았는데도 다음 페이지가 있으면 **절단**이고,
#   절단된 결과로는 결박하지 않는다(「전부 봤다」가 아니면 「가장 이른 것」이 성립하지 않는다).
LOCATE_SEARCH_PAGE = 50
LOCATE_SEARCH_PAGES = 5


@contextmanager
def _bindings_lock(path: str) -> Iterator[None]:
    """결박 원장의 **옆 파일**에 잠근다 — 데이터 파일 자체에 걸면 `os.replace` 가 inode 를
    갈아치워 서로 다른 파일을 잠근 두 프로세스가 동시에 쓴다."""
    with open(path + ".lock", "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _load_bindings(path: str | None) -> dict[str, dict[str, Any]]:
    """결박 원장을 읽는다. **없으면 비어 있는 것이 정상**이다(아직 아무것도 안 묶었다).

    ⚠깨진 파일은 **조용히 비우지 않는다** — 그러면 결박이 사라진 것과 없던 것이 같아지고,
      파일을 부수는 것이 곧 결박을 푸는 방법이 된다.
    """
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise AgoraError(errors.PRECONDITION, "결박 원장을 읽을 수 없다",
                         {"file": BINDINGS_FILENAME, "why": str(e)}) from None
    threads = (data or {}).get("threads")
    if not isinstance(threads, dict):
        raise AgoraError(errors.PRECONDITION, "결박 원장의 모양이 다르다",
                         {"file": BINDINGS_FILENAME})
    return threads


def _save_bindings(path: str, threads: dict[str, dict[str, Any]]) -> None:
    """제자리 갈아치우기로 쓴다 — 쓰다 죽어도 반쪽 파일이 남지 않는다."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"threads": threads}, fh, ensure_ascii=False, sort_keys=True, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def is_rate_limited(err: AgoraError) -> bool:
    """이 실패가 「지금은 말고」인가 — 문자열로 판별한다(gh 는 상태 코드를 말로 준다)."""
    blob = json.dumps(err.detail, ensure_ascii=False, default=str).lower()
    return any(marker in blob for marker in RATE_LIMIT_MARKERS)


_LOOKUP = """
query($q: String!, $first: Int!, $cursor: String) {
  search(query: $q, type: DISCUSSION, first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on Discussion { id number title createdAt } }
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

_LIST = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    discussions(first: 50, after: $cursor,
                orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { id number title updatedAt }
    }
  }
}
"""

_CLOSE = """
mutation($id: ID!, $reason: DiscussionCloseReason!) {
  closeDiscussion(input: {discussionId: $id, reason: $reason}) {
    discussion { id closed closedAt }
  }
}
"""

_ANSWER = """
mutation($id: ID!) {
  markDiscussionCommentAsAnswer(input: {id: $id}) {
    discussion { id isAnswered }
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


_STATUS = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) { closed closedAt isAnswered }
  }
}
"""

# ★R3-④ — 결박 **복구**용. 받은 번호가 정말 그 thread_id 의 게시물인지 되묻는다(id · 본문만).
_VERIFY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) { id body }
  }
}
"""


class GitHubStore:
    def __init__(self, owner: str, name: str, categories: dict[str, str],
                 transport: Any = None, sleep: Any = None,
                 attempts: int = BACKOFF_ATTEMPTS,
                 bindings_path: str | None = None) -> None:
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
        # ★H1(R-13) — thread_id 를 **어느 Discussion 에 결박했는지**를 디스크에 남긴다.
        #   없으면 매 세션이 검색 결과를 새로 믿는다 = 복제본이 끼어들 자리가 매번 열린다.
        self._bindings_path = bindings_path
        self._bindings: dict[str, dict[str, Any]] = _load_bindings(bindings_path)
        # 후보가 둘 이상이었다는 **사실**을 감추지 않는다 — audit 이 이것을 싣는다.
        self.locate_candidates: dict[str, list[int]] = {}
        # ★검색이 **몇 건을 봤고 끝까지 봤는가** — 후보 목록과 다른 사실이다(라운드 2).
        #   후보 10건이 보여도 그 뒤가 잘렸으면 「원본이 없었다」와 「원본을 못 봤다」가 같아진다.
        self.locate_search: dict[str, dict[str, Any]] = {}

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
        """thread_id → (번호, node id). **결박된 것만 믿는다.**

        ★H1(codex 2026-08-26 · R-13) — 예전에는 검색 결과 `nodes[0]` 를 검증 없이 채택했다.
          그러면 **서명 능력이 없는 사람도 운반체를 갈아치울 수 있다**: 이미 서명된 genesis 를
          그대로 복사해 새 Discussion 을 만들면, 그 복제본은 **단독으로는 서명 검증을 통과**한다
          (서명은 이벤트 바이트에 대한 것이지 「어느 게시물에 실렸는가」에 대한 것이 아니다).
          남는 것은 검색 순서뿐이고, 검색 순서는 **우리 것이 아니다.**
        ★그래서 두 겹으로 막는다:
          ⑴ **결박** — 한 번 정한 (thread_id → number) 를 참가자 설정에 남기고, 이후에는
             그 번호만 쓴다. 후보에 없으면 **멈춘다**(조용히 다른 것을 고르지 않는다).
          ⑵ **첫 결박의 결정 규칙** — `nodes[0]`(운반층이 정한 순서)이 아니라
             **genesis 게시 시각이 가장 이른 것**. 복제본은 원본보다 먼저 존재할 수 없다.
        ⚠**이것은 탈취를 「불가능」하게 만들지 않는다** — 결박 전 첫 조회를 이기면 여전히 진다.
          그때도 후보가 여럿이었다는 사실은 `locate_candidates` 로 audit 에 남는다.
        ★라운드 2 로 그 창은 **남이 만든 스레드에 처음 합류하는 조회**로 좁혀졌다: 우리가 만든 스레드는
          생성 자리에서 묶이고(`append`), 검색은 끝까지 보거나 절단이면 결박을 거부한다(`_search`).
        """
        if thread_id in self._numbers:
            return self._numbers[thread_id], self._ids[thread_id]
        nodes, truncated = self._search(thread_id)
        if not nodes:
            raise AgoraError(errors.STORE, "스레드를 찾지 못했다",
                             {"thread_id": thread_id, "truncated": truncated})
        if len(nodes) > 1:
            self.locate_candidates[thread_id] = sorted(n["number"] for n in nodes)
        # ★R3-③(codex 라운드 2 · master#238398) — 결박을 판단하기 **직전에** 원장을 다시 읽는다. 시작 때
        #   읽은 메모리 사본만 보면, 동료 프로세스가 뒤늦게 묶은 결박을 이 인스턴스는 못 보고
        #   (절단 검색이면) code 7 로 헛되이 실패한다 — 무결성은 _bind 의 재읽기가 지키지만 가용성이 샜다.
        self._refresh_bindings()
        bound = self._bindings.get(thread_id)
        if bound:
            chosen = next((n for n in nodes if n["number"] == bound["number"]), None)
            if chosen is None:
                # ★경보다. 결박된 번호가 후보에 없다 = 원본이 사라졌거나 남이 갈아치웠다.
                #   ⚠절단됐으면 「없다」가 아니라 「못 봤다」다 — 같은 경보에 다른 사유를 단다.
                raise AgoraError(
                    errors.STORE, "결박된 게시물이 후보에 없다 — 운반층을 믿지 않는다",
                    {"thread_id": thread_id, "bound": bound["number"],
                     "found": sorted(n["number"] for n in nodes),
                     "truncated": truncated})
            if chosen["id"] != bound["node_id"]:
                raise AgoraError(
                    errors.STORE, "결박된 게시물의 node id 가 다르다",
                    {"thread_id": thread_id, "bound": bound["node_id"]})
        else:
            # ★절단된 결과로는 **결박하지 않는다.** 「가장 이른 것」은 전부 봤을 때만 뜻이 있다 —
            #   못 본 페이지에 원본이 있으면 지금 고르는 것이 곧 복제본이다.
            if truncated:
                raise AgoraError(
                    errors.STORE, "검색 결과가 절단됐다 — 전부 보지 못했으므로 결박하지 않는다",
                    {"thread_id": thread_id, "seen": len(nodes),
                     "pages": LOCATE_SEARCH_PAGES})
            # ★가장 이른 것. 시각이 같거나 없으면 **번호가 작은 것**으로 갈라 준다
            #   (결정론 — 같은 입력에 늘 같은 답이 나와야 결박이 의미를 갖는다).
            chosen = min(nodes, key=lambda n: (n.get("createdAt") or "", n["number"]))
            self._bind(thread_id, chosen)
        self._numbers[thread_id] = chosen["number"]
        self._ids[thread_id] = chosen["id"]
        return chosen["number"], chosen["id"]

    def _search(self, thread_id: str) -> tuple[list[dict[str, Any]], bool]:
        """thread_id 를 본문에 담은 Discussion 을 **페이지를 넘겨 가며** 모은다.

        돌려주는 것 = (후보 전건, 절단 여부). 절단 = 페이지 상한에 닿았는데 다음 페이지가 남았다.
        ★pageInfo 가 없는 응답(옛 가짜 운반층)은 「다음 없음」으로 읽는다 — 없는 칸을 있다고
          추측하지 않는다.
        """
        q = f'repo:{self.owner}/{self.name} in:body "{thread_id}"'
        nodes: list[dict[str, Any]] = []
        cursor: str | None = None
        pages = 0
        page: dict[str, Any] = {}
        while True:
            data = self._run(_LOOKUP, q=q, first=LOCATE_SEARCH_PAGE, cursor=cursor)
            block = data.get("search") or {}
            nodes.extend(n for n in (block.get("nodes") or []) if n)
            page = block.get("pageInfo") or {}
            pages += 1
            if not page.get("hasNextPage") or pages >= LOCATE_SEARCH_PAGES:
                break
            cursor = page.get("endCursor")
        truncated = bool(page.get("hasNextPage"))
        self.locate_search[thread_id] = {"candidates": len(nodes), "pages": pages,
                                         "truncated": truncated}
        return nodes, truncated

    def _refresh_bindings(self) -> None:
        """디스크 원장이 정본이다 — 잠금 아래 다시 읽어 메모리 사본을 갈아 끼운다(경로 없으면 그대로)."""
        if not self._bindings_path:
            return
        with _bindings_lock(self._bindings_path):
            self._bindings = _load_bindings(self._bindings_path)

    def _bind(self, thread_id: str, node: dict[str, Any]) -> None:
        """결박을 디스크에 남긴다. 경로가 없으면 이 프로세스 안에서만 산다.

        ★★라운드 2(codex 재검증 신규 HIGH) — 그전에는 **자기 메모리 사본을 통째로** 갈아치웠다.
          두 프로세스가 각자 시작 때 읽은 사본에 하나씩 더해 쓰면 **뒤에 쓴 쪽이 앞의 결박을 지운다**
          (lost update · 재현: A 결박 뒤 B 결박 → 파일엔 B 만). 제자리 갈아치우기는 반쪽 파일만 막지
          이것은 못 막는다. ⇒ **잠금 안에서 최신 원장을 다시 읽고, 거기에 더해서, 그것을 쓴다.**
        ★같은 thread_id 가 **이미 다른 게시물에** 묶여 있으면 덮어쓰지 않고 멈춘다(code 2).
          덮어쓰는 순간 결박은 「먼저 쓴 사람 것」이 되고, 그것은 검색 순서를 믿는 것과 같다.
        """
        entry = {"number": node["number"], "node_id": node["id"]}
        if not self._bindings_path:
            self._bindings[thread_id] = entry
            return
        with _bindings_lock(self._bindings_path):
            current = _load_bindings(self._bindings_path)
            existing = current.get(thread_id)
            if existing and existing != entry:
                raise AgoraError(
                    errors.PRECONDITION, "같은 thread_id 가 이미 다른 게시물에 결박돼 있다",
                    {"thread_id": thread_id, "bound": existing["number"],
                     "attempted": entry["number"], "file": BINDINGS_FILENAME,
                     "layer": "binding"})
            current[thread_id] = entry
            # ★R3-④(codex 라운드 2 신규 MEDIUM) — 디스크에 **남긴 뒤에만** 기억한다. 그전에는 쓰기가
            #   OSError 로 실패해도 메모리는 이미 묶여 있어(재현 `MEMORY_BOUND True`) 이 프로세스만
            #   「결박됐다」고 믿었다 — 재시작하면 사라지는 결박이다. 실패는 날것으로 새지 않고
            #   계약 코드로 나간다(`layer=binding` — 호출자가 「어느 겹이 실패했는가」를 안다).
            try:
                _save_bindings(self._bindings_path, current)
            except OSError as e:
                raise AgoraError(errors.PRECONDITION, "결박 원장을 쓸 수 없다",
                                 {"thread_id": thread_id, "file": BINDINGS_FILENAME,
                                  "why": str(e), "layer": "binding"}) from None
            self._bindings = current          # 병합본이 이제 이 프로세스의 기억이다

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
            # ★★라운드 2 — 만든 **그 자리에서** 묶는다. 그전에는 번호를 메모리에만 두고
            #   첫 `_locate` 까지 기다렸다 ⇒ 「결박 전 첫 조회」 창이 짧은 것이 아니라
            #   **다음 조회까지 시간 상한 없이** 열려 있었다(codex 재현 `H1_CREATE_BINDING_EXISTS False`).
            #   우리가 방금 만든 게시물보다 더 확실한 원본은 없다 — 검색을 기다릴 이유가 없다.
            try:
                self._bind(thread_id, node)
            except AgoraError as e:
                # ★★R3-④ — 게시물은 **이미 생겼는데** 결박을 못 남겼다 = 부분 커밋이다. 날것 예외로
                #   새면 호출자는 「생성 실패」로 읽고 다시 만든다(중복 게시물) — 그리고 재시작한 세션은
                #   이 스레드를 결박 없이 본다. 그래서 **code 8(저장 성공 불명)** 로 올린다: 재조회 판정
                #   (`settle_unknown` → fetch → `_locate` → 절단 아닌 검색이면 거기서 묶인다)이 그대로 닿고,
                #   detail 에 **받은 번호·node id·url** 을 실어 절단 등으로 재조회가 막히면 `rebind` 로
                #   그 번호를 확인해 묶을 수 있게 한다. 실패한 겹(cause)은 감추지 않는다.
                raise AgoraError(errors.UNKNOWN_COMMIT,
                                 "게시물은 만들어졌는데 결박을 못 남겼다 — 재조회 또는 rebind 로 복구하라",
                                 {"thread_id": thread_id, "number": node["number"],
                                  "node_id": node["id"], "url": node.get("url"),
                                  "cause_code": e.code, "cause": e.detail,
                                  "recover": "rebind"}) from None
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

    def rebind(self, *, thread_id: str, number: int, node_id: str) -> dict[str, Any]:
        """결박 **복구** — 생성은 됐는데 결박을 못 남긴 스레드(code 8 · `recover=rebind`)를 그 번호로 묶는다.

        ★번호를 **믿지 않는다.** 운반층에 되물어 ⑴그 번호의 게시물 node id 가 받은 것과 같고
          ⑵본문에 이 thread_id 가 들어 있을 때만 묶는다 — 아니면 손으로 준 번호 하나로 결박을
          갈아치우는 길이 되고, 그것은 R-13 이 막으려던 바로 그 문이다.
        ★결박 자체는 `_bind` 가 한다(잠금·재읽기·충돌 code 2 그대로) — 복구 경로가 따로 쓰면
          그 경로만 병합을 건너뛴다.
        """
        data = self._run(_VERIFY, owner=self.owner, name=self.name, number=number)
        disc = (((data.get("repository") or {}).get("discussion")) or {})
        if not disc.get("id"):
            raise AgoraError(errors.STORE, "복구하려는 번호의 게시물을 읽지 못했다",
                             {"thread_id": thread_id, "number": number})
        if disc["id"] != node_id or thread_id not in (disc.get("body") or ""):
            raise AgoraError(errors.PRECONDITION,
                             "복구하려는 번호가 그 스레드의 게시물이 아니다 — 묶지 않는다",
                             {"thread_id": thread_id, "number": number,
                              "id_matches": disc["id"] == node_id,
                              "body_has_thread_id": thread_id in (disc.get("body") or "")})
        node = {"number": number, "id": node_id}
        self._bind(thread_id, node)
        self._numbers[thread_id] = number
        self._ids[thread_id] = node_id
        return {"thread_id": thread_id, "number": number, "node_id": node_id,
                "bound": True}

    def list_threads(self, *, updated_since: str | None = None,
                     limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        """바뀐 순서로 스레드 목록을 준다 — watch 가 **읽을 것을 고르는** 자리(S4-2 제약).

        ★`updated_since` 보다 오래된 것이 나오면 **거기서 멈춘다.** 최신순으로 오므로
          그 뒤는 볼 필요가 없다 — 목록을 끝까지 도는 것 자체가 비용이다.
        """
        data = self._run(_LIST, owner=self.owner, name=self.name, cursor=cursor)
        block = ((data.get("repository") or {}).get("discussions") or {})
        rows: list[dict[str, Any]] = []
        stopped = False
        for node in block.get("nodes") or []:
            if updated_since and (node.get("updatedAt") or "") < updated_since:
                stopped = True
                break
            rows.append({"number": node["number"], "node_id": node["id"],
                         "updated_at": node.get("updatedAt"),
                         "title": node.get("title")})
        page = block.get("pageInfo") or {}
        nxt = None if stopped or not page.get("hasNextPage") else page.get("endCursor")
        return {"items": rows[:limit], "next_cursor": nxt}

    def fetch(self, *, thread_id: str | None = None, number: int | None = None,
              cursor: str | None = None, limit: int = 100) -> dict[str, Any]:
        """스레드의 **전건**(본문 + 댓글 + 답글)을 모은다.

        ★`cursor` 는 계약상 받지만 여기서는 **안 쪼갠다.** 한 스레드의 이벤트는 서로 `prev`
          로 엮여 있어서 일부만 주면 reducer 가 「닿지 않는 것」으로 잘못 읽는다.
          쪼개는 것은 스레드 **목록**(threads)의 몫이다.
        """
        # ★번호를 이미 알면 검색을 통째로 건너뛴다 — 주기마다 도는 경로라 그 한 번이 크다.
        if number is None:
            if thread_id is None:
                raise AgoraError(errors.ARGUMENT, "thread_id 나 number 가 필요하다", None)
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

    # reducer 상태 → GitHub 종결 사유. 우리 어휘가 그쪽 어휘보다 넓으므로 좁혀서 보낸다.
    CLOSE_REASONS = {"solved": "RESOLVED", "answered": "RESOLVED",
                     "unresolved": "OUTDATED", "superseded": "DUPLICATE",
                     "archived": "OUTDATED", "aborted": "OUTDATED",
                     "expired": "OUTDATED"}

    def project(self, *, thread_id: str, state: str,
                answer_node_id: str | None = None,
                close_reason: str | None = None) -> dict[str, Any]:
        """reducer 가 계산한 상태를 **화면에 반영만** 한다(§D1 · H-7).

        ★이것은 **투영이지 입력이 아니다.** 여기서 실패해도 프로토콜 상태는 그대로다 —
          그래서 실패를 예외로 올리지 않고 **결과에 적어** 돌려준다. 화면이 못 따라온 것과
          상태가 틀린 것은 다른 사건인데, 예외로 올리면 호출자가 그 둘을 뭉치게 된다.

        ★라벨은 **하지 않는다.** 라벨을 붙이려면 없는 라벨을 만들어야 하고, 그것은
          스레드가 아니라 **저장소를 바꾸는 일**이라 승인 범위 밖이다.
          안 한 것을 「했다」로 적지 않고, 결과에 그 사실과 이유를 남긴다.
        """
        done: dict[str, Any] = {"labels": "not_implemented",
                                "labels_why": "라벨 생성 = 저장소 수준 변경 · 승인 범위 밖"}
        _number, disc_id = self._locate(thread_id)
        if answer_node_id:
            try:
                self._run(_ANSWER, id=answer_node_id)
                done["answer"] = "marked"
            except AgoraError as e:
                done["answer"] = "failed"
                done["answer_error"] = e.detail
        if state == "closed":
            reason = self.CLOSE_REASONS.get(close_reason or "", "RESOLVED")
            try:
                self._run(_CLOSE, id=disc_id, reason=reason)
                done["closed"] = reason
            except AgoraError as e:
                done["closed"] = "failed"
                done["close_error"] = e.detail
        return done

    def thread_status(self, *, thread_id: str) -> dict[str, Any]:
        """운반층에 **지금 어떻게 보이는지** 되묻는다(§D1 투영 확인 · S7-2)."""
        number, _disc_id = self._locate(thread_id)
        data = self._run(_STATUS, owner=self.owner, name=self.name, number=number)
        node = (((data.get("repository") or {}).get("discussion")) or {})
        return {"closed": bool(node.get("closed")),
                "answered": bool(node.get("isAnswered")),
                "closed_at": node.get("closedAt")}

    def categories(self) -> dict[str, Any]:
        return {name: {"id": cid, "is_answerable": name == "problem"}
                for name, cid in self._categories.items()}
