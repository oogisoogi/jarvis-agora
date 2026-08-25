"""durable spool — 「받았다 → 건넸다 → 소비했다」를 디스크에 남긴다(설계 §5 · H-11).

★**at-least-once 다.** 같은 이벤트가 두 번 올 수 있고, 그것을 막는 것은 `node_id` dedupe 다.
  exactly-once 라고 적지 않는다 — 그렇게 적으면 읽는 쪽이 중복 처리를 안 만든다.

★세 단계를 **가르는 이유**: 「전달됨」과 「소비됨」은 다른 사건이다.
  둘을 뭉치면 「받아 놓고 아무도 안 읽은 것」이 수신 증거로 계상된다(§8 FR-15).

─────────────────────────────────────────────────────────────────────────────
★★이 파일의 시험이 **실제로 무엇을 재는지** 먼저 적어 둔다(안 적으면 다음 사람이 오해한다):

  · **SIGKILL 픽스처가 재는 것 = 「메모리에만 갖고 있지 않은가」**.
    프로세스를 강제 종료해도 남는다는 것은 **write 가 커널까지 갔다**는 뜻이다.
    파이썬 버퍼에만 있거나 딕셔너리에만 있었다면 그 순간 사라진다.
  · **SIGKILL 이 재지 **못하는** 것 = fsync**. 커널 페이지 캐시는 프로세스가 죽어도 살아 있다.
    fsync 가 막는 것은 **전원 손실·커널 패닉**이고, 그것은 이 기계에서 재현하지 않는다.
  ⇒ 그래서 fsync 는 **호출됐는가**로 잰다(관측). 「전원 손실에서 살아남는가」는 **미측정**이고,
    그 사실을 숨기지 않는다. 재현 없이 「crash-safe 를 증명했다」고 적는 것이 가장 나쁘다.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import fcntl
import json
import os
from typing import Any, Iterator

from agora import errors
from agora.errors import AgoraError
from agora.ledger import now_iso

# ★M-e(2026-08-26) — **본 것과 받은 것을 가른다.** 검증을 통과하지 못한 글도 「봤다」는
#   사실은 남겨야 한다(안 남기면 매 주기 다시 읽고, 「본 적 없다」와 「보고 물리쳤다」가 같아진다).
#   그러나 그것은 **수신이 아니다** — 알림도 배달 영수증도 여기서 끝난다.
UNVERIFIED_SEEN = "unverified_seen"
FETCHED = "fetched"
DELIVERED = "delivered"
ACKED = "acked"

# 순서가 있는 단계다. 뒤로 가는 전이는 거부한다 —
# 「소비했다」가 「건넸다」로 되돌아가면 수신 증거가 조용히 사라진다.
# ⚠`unverified_seen` 을 **맨 앞**에 둔다: 명부가 바뀌어 나중에 검증되면 앞으로 갈 수 있어야 한다.
STAGES = (UNVERIFIED_SEEN, FETCHED, DELIVERED, ACKED)
_RANK = {stage: i for i, stage in enumerate(STAGES)}


_CARRIED = ("thread_id", "message_id")


def _carry(into: dict[str, Any], src: dict[str, Any]) -> None:
    """빈 칸만 채운다. **이미 있는 값은 건드리지 않는다** — 덮어쓰면 앞뒤가 갈린다."""
    for key in _CARRIED:
        if not into.get(key) and src.get(key):
            into[key] = src[key]


class Spool:
    def __init__(self, directory: str, fsync: Any = None) -> None:
        self.dir = directory
        self.path = os.path.join(directory, "spool.jsonl")
        self.lock_path = os.path.join(directory, ".spool.lock")
        # ★fsync 를 주입 가능하게 둔다. 그래야 「불렀는가」를 시험이 관측할 수 있다 —
        #   불렀는지 볼 수 없으면 지워져도 아무도 모른다.
        self._fsync = fsync or os.fsync
        self.malformed = 0        # 꼬리에서 잘린 줄 수 — 조용히 버리지 않고 센다

    # ── 읽기 ────────────────────────────────────────────────────────────────
    def rows(self) -> Iterator[dict[str, Any]]:
        """줄 단위로 읽는다. **꼬리에서 잘린 줄은 버리되 계수한다.**

        ★쓰는 도중에 죽으면 마지막 줄이 반쪽으로 남을 수 있다. 그 줄을 파싱 실패로
          전체를 못 읽는다고 하면 spool 하나가 망가져 채널 전체가 멈춘다.
          반대로 조용히 버리면 무슨 일이 있었는지 아무도 모른다 — 그래서 **버리고 센다**.
        """
        self.malformed = 0
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    self.malformed += 1
                    continue
                if type(row) is dict:
                    yield row

    def state(self) -> dict[str, dict[str, Any]]:
        """node_id → 마지막 단계. 같은 node_id 가 여러 줄이면 **가장 앞선 단계**가 이긴다.

        ★단계는 덮어쓰되 **딸린 것(thread_id·message_id)은 이어받는다.**
          뒷 줄이 그 값을 안 실었다고 앞 줄이 알던 것을 지우면, 「어느 스레드의 무엇인가」가
          단계가 진행될수록 사라진다. S5-1 에서는 이것이 안 보였다 — **소비처가 없었기 때문**이다.
          S5-3(ack)이 `message_id` 로 spool 을 찾으면서 드러났다.
        """
        out: dict[str, dict[str, Any]] = {}
        for row in self.rows():
            nid = row.get("node_id")
            if not nid:
                continue
            prev = out.get(nid)
            if prev and _RANK.get(row.get("stage"), -1) <= _RANK.get(prev["stage"], -1):
                # 단계는 안 밀렸지만, 이 줄이 새로 들고 온 딸린 값은 채워 둔다.
                _carry(prev, row)
                continue
            cur = {"stage": row.get("stage"), "thread_id": row.get("thread_id"),
                   "message_id": row.get("message_id"), "ts": row.get("ts")}
            if prev:
                _carry(cur, prev)          # 앞 줄이 알던 것을 잃지 않는다
            out[nid] = cur
        return out

    def by_message(self, message_id: str) -> dict[str, Any] | None:
        """message_id → 그 상태 행(node_id 포함). 없으면 None.

        ★도구 계약은 **message_id 로** 말하는데(§4 `agora.ack`) spool 은 운반층 식별자인
          `node_id` 로 기억한다. 그 둘을 잇는 표를 **밖에 또 만들면 두 곳이 갈라진다** —
          그래서 spool 이 자기 줄에 싣고 자기가 찾는다.
        """
        for nid, row in self.state().items():
            if row.get("message_id") == message_id:
                return {"node_id": nid, **row}
        return None

    def seen(self, node_id: str) -> bool:
        """dedupe 의 판정 — 이 node_id 를 이미 받았는가(at-least-once 의 짝)."""
        return node_id in self.state()

    def pending(self, stage: str) -> list[str]:
        """그 단계에 **머물러 있는** node_id 들. 「전달됨에 머문 것」이 곧 미소비다."""
        return sorted(nid for nid, row in self.state().items() if row["stage"] == stage)

    # ── 쓰기(append 전용) ───────────────────────────────────────────────────
    def record(self, *, node_id: str, stage: str,
               thread_id: str | None = None,
               message_id: str | None = None) -> dict[str, Any]:
        if stage not in STAGES:
            raise AgoraError(errors.ARGUMENT, "계약에 없는 단계",
                             {"stage": stage, "allowed": list(STAGES)})
        current = self.state().get(node_id)
        if current and _RANK[stage] < _RANK[current["stage"]]:
            raise AgoraError(errors.ARGUMENT, "단계는 뒤로 가지 않는다",
                             {"node_id": node_id, "from": current["stage"],
                              "to": stage})
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        row = {"node_id": node_id, "thread_id": thread_id, "stage": stage,
               "message_id": message_id, "ts": now_iso()}
        with open(self.lock_path, "a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    fh.flush()              # ★커널까지 — SIGKILL 을 이긴다
                    self._fsync(fh.fileno())  # ★디스크까지 — 전원 손실을 겨냥한다
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return row
