#!/usr/bin/env python3
"""의장 루프 — **방을 여는 손 하나만 남기고** 나머지를 기계가 한다(설계 §2 A·B·C·D·E).

왜 이 스크립트인가
------------------
운영자가 방 하나를 끝까지 진행하려면 지금 손이 **열 번** 든다(명부 3 · 방 열기 1 · advance 3 ·
resolve 1 · close 1 · 대조 1). 그중 **사람이 정해야 하는 것은 「무엇을 이야기할까」 하나뿐**이다.
나머지는 「누가 말했나 · 시간이 됐나」를 보고 정하는 일이라 기계가 한다.

무엇을 안 하나
--------------
· ⛔**대신 서명하지 않는다** — 서명은 이 기계의 열쇠로 한다. 릴레이는 회차를 넘길 수 없다
  (그것이 설계가 지킨 성질이다). 그래서 이 루프는 **의장 기계에서** 돈다.
· ⛔**판단하지 않는다.** 권고 초안은 **결정론 템플릿**이다 — 발언을 요약한 척하지 않고,
  누가 무엇을 말했는지 **그대로 인용**하고 「사람이 읽으라」고 적는다.
  ★반대 의견을 낱말로 가려내지 않는다(「반대」가 들어갔다고 반대가 아니다). 가려낸 척하는 것이
  안 가려내는 것보다 나쁘다 — 그 자리는 비워 두고, 비웠다는 것을 본문에 적는다.
· ⛔**사람을 재촉하지 않는다.** 회차는 「전원 발언」이나 「시간 초과」로만 넘어간다.

쓰는 법
-------
    python3 tools/chair_loop.py --dry-run     # 무엇을 할지 인쇄만(아무것도 안 바꾼다)
    python3 tools/chair_loop.py               # 한 번 돈다(cron·launchd 가 10분마다 부른다)
    touch ~/.config/agora/chair-loop/STOP     # ★사람이 끄는 법 — 이 파일이 있으면 아무것도 안 한다

    python3 tools/chair_loop.py --open --topic "<주제>" --body "<발제 3줄>"   # 방 열기 + 맡기기(사람 손 1)
    python3 tools/chair_loop.py --manage <방 id>                              # 이미 연 방을 맡긴다
    # ⚠`--open` 이 방을 연 **직후** 죽으면 그 방은 목록에 없다(고아 방). 되살리는 법 = 위 `--manage`.
    #   ★이 순서는 일부러다: 먼저 열고 나중에 적으면 **없는 방을 맡는 일**은 생기지 않는다.

★**옵트인이다**: 맡긴 방(`chair-loop/manage.txt`)만 본다. 안 맡긴 방은 **읽지도 않는다** —
  「적는 것을 잊으면 아무 일도 안 일어나는」 쪽이 「잊으면 기계가 방을 닫는」 쪽보다 낫다.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from typing import Any, Callable

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agora import errors, reducer, tools                      # noqa: E402
from agora.errors import AgoraError                           # noqa: E402

# ── 설계값(전부 여기 한 곳 · 바꾸려면 이 표를 고친다) ────────────────────────
GRACE_MINUTES = 30        # 전원이 말해도 **이만큼은 기다린다**(늦게 오는 사람의 자리)
ROUND_MINUTES = 180       # 아무도 더 말하지 않아도 이만큼 지나면 넘긴다
LAST_ROUND = 3            # r3 가 마지막 회차다(r3 뒤가 권고)
RETRY_CAP = 3             # 같은 자리에서 이만큼 실패하면 그 방은 **사람에게 넘긴다**
QUOTE_CHARS = 120         # 인용 한 줄의 길이 상한(본문 예산을 지키려고)
SUMMARY_CHARS = 2000      # 권고 본문 전체의 상한 — 넘으면 자르고 **자른 사실을 적는다**
STOP_FILE = "STOP"        # 이 파일이 있으면 루프는 아무것도 하지 않는다
MANAGE_FILE = "manage.txt"   # ★루프가 맡은 방 목록 — 여기 없는 방은 **읽지도 않는다**


def managed_rooms(state_dir: str) -> set[str]:
    """루프가 맡은 방. **옵트인이다** — 목록에 없으면 손대지 않는다.

    ★★왜 옵트인인가(2026-09-11 실측이 이 설계를 바꿨다): 완성한 루프를 **실물에 드라이런**
      했더니 첫 줄이 「주제 광장 방의 회차를 넘기겠다」였다. 그 방은 9/13 저녁까지 **제안을
      모으는 자리**라 넘어가면 안 된다. 옵트아웃(제외 목록)이었으면 **적는 것을 잊는 순간**
      기계가 그 방을 닫는다 — 그리고 닫힌 방은 되돌릴 수 없다.
    ⇒ 「잊으면 아무 일도 안 일어나는」 쪽으로 기울인다. 대신 방을 여는 명령이 등록까지 해 주므로
      (`--open`) 사람 손은 **그대로 하나**다.
    """
    path = os.path.join(state_dir, MANAGE_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return set()
    return {ln.split("#")[0].strip() for ln in lines if ln.split("#")[0].strip()}


def manage(state_dir: str, thread_id: str) -> None:
    """방 하나를 루프에 맡긴다(한 줄 추가 · 중복은 안 적는다)."""
    os.makedirs(state_dir, exist_ok=True)
    if thread_id in managed_rooms(state_dir):
        return
    with open(os.path.join(state_dir, MANAGE_FILE), "a", encoding="utf-8") as fh:
        fh.write(thread_id + "\n")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_ts(text: str) -> datetime.datetime | None:
    """`2026-09-11T04:52:03Z` 를 읽는다. **못 읽으면 None** 이다.

    ★★한 번 틀렸던 자리다(agy 1R · 2026-09-11): 처음에는 못 읽으면 **1970년**으로 쳤다.
      「시간 초과 쪽으로 기울여 사람이 보게 하자」는 뜻이었는데, 실제로 일어나는 일은
      **age 가 50년이 되어 그 자리에서 회차가 넘어가는 것**이다 — 사람이 안 보는 동안
      기계가 방을 밀고 나간다. ⇒ 고장은 **전진**이 아니라 **정지 + 통보** 로 번져야 한다.
    """
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ── 방 하나를 읽는 자 ───────────────────────────────────────────────────────
def read_room(reduced: dict[str, Any]) -> dict[str, Any]:
    """방 하나에서 **판단에 필요한 것만** 뽑는다(누가 말했나 · 언제부터 이 회차인가)."""
    round_now = int(reduced.get("round") or 0)
    started_at = None
    spoke_now: set[str] = set()
    spoke_ever: set[str] = set()
    posts: list[dict[str, Any]] = []
    for row in reduced.get("events") or []:
        event = row.get("event") or {}
        kind = event.get("kind")
        who = event.get("from")
        if kind == "genesis" and started_at is None:
            started_at = row.get("created_at")
        if kind == "advance" and int((event.get("payload") or {}).get("to_round", -1)) == round_now:
            started_at = row.get("created_at")          # 이 회차가 시작된 시각
        if kind != "post":
            continue
        payload = event.get("payload") or {}
        posts.append({"from": who, "round": int(payload.get("round") or 0),
                      "body": str(payload.get("body") or ""), "at": row.get("created_at")})
        spoke_ever.add(who)
        if int(payload.get("round") or 0) == round_now:
            spoke_now.add(who)
    return {"round": round_now, "state": reduced.get("state"),
            "chair": reducer.procedure_snapshot(reduced).get("chair"),
            "started_at": started_at, "spoke_now": spoke_now, "spoke_ever": spoke_ever,
            "posts": posts}


def should_advance(room: dict[str, Any], *, now: datetime.datetime,
                   grace_minutes: int = GRACE_MINUTES,
                   round_minutes: int = ROUND_MINUTES) -> tuple[bool, str]:
    """이 회차를 넘길 때인가 — **이유와 함께** 답한다(이유 없는 판정은 감사할 수 없다)."""
    started = _parse_ts(room["started_at"] or "")
    if started is None:
        # ★모르면 **멈춘다.** 모르는 채로 미는 것이 이 루프가 할 수 있는 가장 나쁜 일이다.
        return False, "이 회차가 언제 시작됐는지 못 읽었다 — 사람이 봐야 한다"
    age = (now - started).total_seconds() / 60.0
    if age >= round_minutes:
        return True, f"시간 초과({age:.0f}분 ≥ {round_minutes}분)"
    if not room["spoke_now"]:
        return False, "이 회차에 아직 아무도 말하지 않았다"
    if not room["spoke_ever"] <= room["spoke_now"]:
        missing = sorted(room["spoke_ever"] - room["spoke_now"])
        return False, f"아직 말하지 않은 참가자 {len(missing)}명"
    if age < grace_minutes:
        # ★전원이 말했어도 기다린다 — 늦게 오는 사람이 **회차를 통째로 잃지 않게**.
        return False, f"전원 발언이지만 유예 중({age:.0f}분 < {grace_minutes}분)"
    return True, f"전원 발언({len(room['spoke_now'])}명) · 유예 지남"


# ── 권고 초안(결정론) ───────────────────────────────────────────────────────
def draft_resolution(room: dict[str, Any]) -> dict[str, Any]:
    """권고 초안을 **지어내지 않고** 만든다 — 회차별 발언을 그대로 인용한다.

    ★이 함수는 **읽은 것만 적는다.** 요약처럼 보이는 문장을 만들어 내면, 읽는 사람은
      기계가 판단했다고 믿는다. 이 자리의 정직함은 「나는 판단하지 않았다」를 본문에 적는 것이다.
    """
    posts = room["posts"]
    people = sorted({p["from"] for p in posts})
    lines = [f"[자동 수렴] 회차 {room['round'] + 1}개 · 발언 {len(posts)}건 · 참가 {len(people)}명.",
             "이 글은 의장 루프가 **기계로** 적은 것이다. 요약도 판단도 하지 않았다 —",
             "아래는 각 참가자의 **마지막 발언 첫 줄**을 그대로 옮긴 것이다.",
             "반대 의견은 자동으로 가려내지 않았다(낱말로 가려내면 틀린다). 전문은 방에 그대로 있다."]
    for who in people:
        mine = [p for p in posts if p["from"] == who]
        first_line = (mine[-1]["body"].strip().splitlines() or ["(빈 발언)"])[0]
        lines.append(f"· {who}: {first_line[:QUOTE_CHARS] or '(빈 발언)'}")
    # ★인용은 **상한을 넘지 않는다**(agy 1R): 참가자가 많으면 본문이 예산(protocol.precheck)을
    #   넘겨 `resolve` 가 code 3 으로 막히고, 재시도 상한까지 쓰면 **그 방은 영영 안 닫힌다.**
    #   ⇒ 자르되 **자른 사실을 적는다**(조용히 줄이면 읽는 사람은 전부인 줄 안다).
    body = "\n".join(lines)
    if len(body) > SUMMARY_CHARS:
        head = lines[:4]
        room_left = SUMMARY_CHARS - len("\n".join(head)) - 80
        kept: list[str] = []
        for line in lines[4:]:
            if sum(len(x) + 1 for x in kept) + len(line) > room_left:
                break
            kept.append(line)
        dropped = len(lines) - 4 - len(kept)
        body = "\n".join(head + kept + [f"…그리고 {dropped}명의 인용은 길이 상한 때문에 뺐다"
                                        " — 전문은 방에 그대로 있다."])
    return {
        "summary": body,
        # ★비워 둔 칸이다. 「없다」가 아니라 **「자동으로는 못 가려낸다」**는 뜻이고, 그 말은 위 본문에 있다.
        "dissent": [],
        "recommended_actions": [{
            "text": "이 방의 발언 전문을 사람이 읽고 다음 자리를 정한다(기계는 판단하지 않았다).",
            # ★NFR-8 — 이 자리는 언제나 권고다. 이 표식이 없으면 스키마가 code 3 으로 막는다.
            "execution": "forbidden"}],
    }


# ── 기억(멱등) ──────────────────────────────────────────────────────────────
class Marks:
    """**같은 자리를 두 번 하지 않기 위한 기억.**

    ★릴레이가 막아 주지 않느냐: `advance` 는 막아 준다(단조 증가). 그러나 **통보는 안 막아 준다** —
      기억이 없으면 루프가 돌 때마다 같은 줄이 주최자 인박스에 쌓인다. 그리고 실패한 자리를
      무한히 다시 두드리게 된다. 이 파일이 그 둘을 동시에 막는다.
    """

    def __init__(self, state_dir: str) -> None:
        self.dir = state_dir
        os.makedirs(self.dir, exist_ok=True)

    def _path(self, thread_id: str) -> str:
        return os.path.join(self.dir, f"{thread_id}.json")

    def load(self, thread_id: str) -> dict[str, Any]:
        try:
            with open(self._path(thread_id), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def done(self, thread_id: str, key: str) -> bool:
        return key in (self.load(thread_id).get("done") or {})

    def mark(self, thread_id: str, key: str, value: Any) -> None:
        doc = self.load(thread_id)
        doc.setdefault("done", {})[key] = value
        self._write(thread_id, doc)

    def failures(self, thread_id: str, key: str) -> int:
        return int((self.load(thread_id).get("failed") or {}).get(key, 0))

    def fail(self, thread_id: str, key: str, why: str) -> int:
        doc = self.load(thread_id)
        count = int((doc.setdefault("failed", {})).get(key, 0)) + 1
        doc["failed"][key] = count
        doc.setdefault("why", {})[key] = why
        self._write(thread_id, doc)
        return count

    def _write(self, thread_id: str, doc: dict[str, Any]) -> None:
        """★임시 파일에 다 쓰고 **바꿔치기**한다(agy 1R).

        곧바로 덮어쓰면 쓰는 중에 죽었을 때 **빈 파일**이 남는다. 그러면 기억이 통째로
        사라지고, 재시도 상한이 풀려 같은 자리를 영원히 두드린다(통보도 함께 쌓인다).
        """
        tmp = self._path(thread_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, sort_keys=True, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self._path(thread_id))


# ── 명부 한 줄(A) ───────────────────────────────────────────────────────────
def roster_line(directory: str | None, *, relay_url: str | None = None) -> dict[str, Any]:
    """`sync-roster` → `whoami` → `checkpoint issue` — **순서가 규칙의 절반이다**(OPERATOR §1).

    ⑴ 없이 ⑶ 을 하면 **내 낡은 사본에 서명**하게 되고 상대가 409 로 거절한다.
    ★그래서 순서를 손이 아니라 여기에 박는다.
    """
    from agora import onboard
    out: dict[str, Any] = {"steps": []}
    out["steps"].append(("sync-roster", onboard.sync_roster(
        directory=directory, relay_url=relay_url, yes=True)))
    out["steps"].append(("whoami", onboard.whoami(directory=directory)))
    out["steps"].append(("checkpoint", onboard.issue_checkpoint(
        directory=directory, relay_url=relay_url)))
    return out


# ── 루프 ────────────────────────────────────────────────────────────────────
def run(ctx: Any, *, now: datetime.datetime | None = None, state_dir: str,
        notify: Callable[[str], None] | None = None, dry_run: bool = False,
        grace_minutes: int = GRACE_MINUTES, round_minutes: int = ROUND_MINUTES,
        verify: Callable[[str], str] | None = None) -> dict[str, Any]:
    """한 번 돈다. **의장인 방만** 본다 — 남의 방은 읽지도 않는다."""
    now = now or _now()
    marks = Marks(state_dir)
    said: list[str] = []

    def tell(line: str) -> None:
        said.append(line)
        if notify and not dry_run:
            notify(line)

    if os.path.exists(os.path.join(state_dir, STOP_FILE)):
        return {"stopped": True, "why": "STOP 파일이 있다 — 사람이 껐다", "actions": [], "said": said}

    actions: list[dict[str, Any]] = []
    to_verify: list[str] = []
    mine = managed_rooms(state_dir)
    lobby = tools.browse(ctx)
    for row in lobby.get("rooms") or []:
        thread_id = row["room_id"]
        if row.get("chair") != ctx.participant_id:
            continue                                   # 남의 방 — 손대지 않는다
        if thread_id not in mine:
            continue                                   # 안 맡은 방 — 읽지도 않는다(옵트인)
        reduced = tools._reduce(ctx, thread_id)
        room = read_room(reduced)
        state = room["state"]

        def do(key: str, what: str, fn: Callable[[], Any]) -> bool:
            """한 자리를 **한 번만** 한다. 실패는 세고, 상한을 넘으면 사람에게 넘긴다."""
            if marks.done(thread_id, key):
                return False
            if marks.failures(thread_id, key) >= RETRY_CAP:
                return False
            actions.append({"room": thread_id, "action": key, "what": what,
                            "dry_run": dry_run})
            if dry_run:
                return True
            try:
                fn()
            except AgoraError as e:
                count = marks.fail(thread_id, key, f"code {e.code} {e.message}")
                tell(f"【아고라】 {thread_id[:8]} {what} 실패({count}/{RETRY_CAP}) — code {e.code} {e.message}"
                     + (" · 상한 도달, 이 자리는 사람이 봐야 한다" if count >= RETRY_CAP else ""))
                actions[-1]["error"] = e.code
                return False
            marks.mark(thread_id, key, now.isoformat())
            tell(f"【아고라】 {thread_id[:8]} {what}")
            return True

        if state in ("closed",):
            continue
        if state == "resolved":
            # ★종결 사유는 **자유 문장이 아니라 계약 목록**이다(schema.CLOSE_REASONS · 실측 code 10).
            # ★대조는 **닫기에 성공했을 때만**(agy 1R [LOW]) · 그리고 **방을 다 돈 뒤에**(agy 1R [HIGH]).
            #   여기서 바로 부르면 대조 한 건이 오래 걸리는 동안 **다른 방이 그 판을 통째로 잃는다.**
            if do(f"close@{room['round']}", "권고가 실렸다 → 방을 닫았다(archived)",
                  lambda: tools.close(ctx, thread_id=thread_id, reason="archived")):
                to_verify.append(thread_id)
            continue

        ready, why = should_advance(room, now=now, grace_minutes=grace_minutes,
                                    round_minutes=round_minutes)
        if not ready:
            actions.append({"room": thread_id, "action": "wait", "what": why})
            continue

        if room["round"] < LAST_ROUND:
            target = room["round"] + 1
            do(f"advance@{target}", f"회차 {room['round']}→{target} ({why})",
               lambda t=target: tools.advance(ctx, thread_id=thread_id, to_round=t))
            continue

        draft = draft_resolution(room)
        do(f"resolve@{room['round']}", f"마지막 회차가 끝났다 → 권고 게시 ({why})",
           lambda d=draft: tools.resolve(ctx, thread_id=thread_id, summary=d["summary"],
                                         dissent=d["dissent"],
                                         recommended_actions=d["recommended_actions"]))

    # ★방을 다 돈 **뒤에** 대조한다(느린 일은 맨 끝으로 · agy 1R [HIGH]).
    for thread_id in to_verify:
        if verify is not None and not dry_run:
            tell(f"【아고라】 {thread_id[:8]} 대조: {verify(thread_id)}")

    return {"stopped": False, "actions": actions, "said": said, "verified": to_verify}


# ── 잠금 ────────────────────────────────────────────────────────────────────
def _lock(state_dir: str) -> str | None:
    """★`mkdir` 로 잠근다 — 있으면 실패하는 **원자적** 연산이라 경합에서 하나만 이긴다."""
    path = os.path.join(state_dir, ".lock")
    try:
        os.makedirs(path)
        return path
    except FileExistsError:
        return None


def _inbox_notify(line: str) -> None:
    """주최자에게 **한 줄**로 알린다. 없으면 화면에 적는다(조용히 삼키지 않는다)."""
    helper = os.path.expanduser("~/.claude/channels/inbox-append.sh")
    if not os.path.exists(helper):
        print(line)
        return
    subprocess.run([helper, "agora-chair@chair-loop"], input=line + "\n",
                   text=True, capture_output=True, timeout=60)


def _verify(thread_id: str) -> str:
    """세션 뒤 대조(E) — `rehearsal.py --verify` 를 부르고 **한 줄로** 요약한다."""
    try:
        proc = subprocess.run([sys.executable, os.path.join(_ROOT, "tools", "rehearsal.py"),
                               "--verify", thread_id], capture_output=True, text=True,
                              timeout=180)          # ★잠금을 오래 쥐지 않는다(agy 1R)
    except subprocess.TimeoutExpired:
        return "대조가 180초 안에 안 끝났다 — 사람이 직접 돌려야 한다"
    out = (proc.stdout or proc.stderr or "").strip().splitlines()
    # ★어긋남이 있으면 **그 줄**을 올린다(마지막 줄은 「판정:」 한 줄이라 원인이 안 보인다).
    flagged = [ln.strip() for ln in out if "어긋남" in ln and "🔴" in ln]
    line = (flagged[0] if flagged else (out[-1] if out else "출력 없음"))
    return line[:200] + f" (rc={proc.returncode})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="의장 루프 — 한 번 돈다")
    ap.add_argument("--dry-run", action="store_true", help="무엇을 할지 인쇄만 한다")
    ap.add_argument("--state-dir", default=None, help="기억·잠금 자리(기본 <설정폴더>/chair-loop)")
    ap.add_argument("--grace-minutes", type=int, default=GRACE_MINUTES)
    ap.add_argument("--round-minutes", type=int, default=ROUND_MINUTES)
    ap.add_argument("--no-roster", action="store_true", help="명부 한 줄(A)을 건너뛴다")
    ap.add_argument("--dir", default=None, help="설정 폴더")
    ap.add_argument("--manage", default=None, metavar="<방 id>",
                    help="이미 연 방을 루프에 맡긴다(한 줄 추가)")
    ap.add_argument("--open", action="store_true",
                    help="방을 열고 **그 자리에서** 루프에 맡긴다(사람 손 = 이 한 줄)")
    ap.add_argument("--kind", default="debate", help="--open 의 갈래(debate·problem)")
    ap.add_argument("--topic", default=None, help="--open 의 제목")
    ap.add_argument("--body", default=None, help="--open 의 발제(3줄)")
    args = ap.parse_args(argv)

    ctx = tools.context_from_config(args.dir)
    state_dir = args.state_dir or os.path.join(ctx.config_dir, "chair-loop")
    os.makedirs(state_dir, exist_ok=True)

    if args.manage:
        manage(state_dir, args.manage)
        print(json.dumps({"managed": sorted(managed_rooms(state_dir))}, ensure_ascii=False))
        return errors.OK
    if args.open:
        if not args.topic:
            print(json.dumps({"error": "--open 은 --topic 이 필요하다"}, ensure_ascii=False))
            return errors.ARGUMENT
        out = tools.enter(ctx, topic=args.topic, kind=args.kind, body=args.body or args.topic)
        manage(state_dir, out["room_id"])
        print(json.dumps({"opened": out["room_id"], "url": out.get("url"),
                          "managed": sorted(managed_rooms(state_dir))},
                         ensure_ascii=False, indent=2))
        return errors.OK

    lock = _lock(state_dir)
    if lock is None:
        print(json.dumps({"skipped": "이미 돌고 있다(잠금)", "state_dir": state_dir},
                         ensure_ascii=False))
        return 3
    try:
        roster: Any = "건너뜀(--no-roster)"
        if not args.no_roster and not args.dry_run:
            try:
                roster_line(args.dir, relay_url=(ctx.config.get("relay") or {}).get("url"))
                roster = "sync-roster → whoami → checkpoint"
            except AgoraError as e:
                roster = f"명부 한 줄 실패: code {e.code} {e.message}"
        out = run(ctx, state_dir=state_dir, notify=_inbox_notify, dry_run=args.dry_run,
                  grace_minutes=args.grace_minutes, round_minutes=args.round_minutes,
                  verify=_verify)
        out["roster"] = roster
        print(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2))
        return errors.OK
    finally:
        os.rmdir(lock)


if __name__ == "__main__":
    sys.exit(main())
