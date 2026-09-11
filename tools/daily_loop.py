#!/usr/bin/env python3
"""하루 한 바퀴 — **투표가 주제를 고른다**(06:10 에 한 번 돈다).

무엇을 하나
-----------
① 광장(plaza)의 제안·표를 읽어 **점수와 순위를 계산**한다(`tools/plaza.py` 가 정본 규칙).
② 개설 조건(점수 ≥ 2 · 서로 다른 투표자 ≥ 2)을 넘긴 상위 N개로 **토론방을 연다.**
③ 광장에 마커를 남긴다 — `[졸업] <제안 id> → <방 id>`. **이 줄이 파생 상태의 유일한 출처다**
   (상태기계는 건드리지 않는다 · 보드와 시험이 같은 정규식을 읽는다).
④ 14일이 지나도록 안 된 제안은 `[보관]` 으로 가린다(원장은 그대로 · 삭제 아님).
⑤ 조건을 넘긴 것이 **이틀 연속 0건**이면 최고점 하나를 연다(교착 해소 · 마커에 그렇게 적는다).
⑥ 열렸는데 **아무도 말하지 않은 방**은 권고 없이 닫고 `[유찰]` 을 남긴다(빈 방 양산 차단).

무엇을 **안 하나**
------------------
· ⛔주제를 고르지 않는다. 고르는 것은 표다.
· ⛔라이브 광장을 기본값으로 두지 않는다 — 광장 id 는 **설정에 적어야** 돈다(`--plaza` 또는 daily.json).
· ⛔모르면 **멈춘다.** 시각을 못 읽은 글은 셈에서 빼고 그 수를 보고한다(조용히 추정하지 않는다).

쓰는 법
-------
    export AGORA_SIGNING_KEY=~/.config/agora/id_ed25519   # ★손으로 칠 때 필요하다(껍데기를 안 지나므로)
    python3 tools/daily_loop.py --plaza <광장 id> --dry-run     # 오늘 무엇을 열지 인쇄만
    python3 tools/daily_loop.py                                  # 한 바퀴(launchd 06:10)
    python3 tools/daily_loop.py --date 2026-09-14                # 날짜 노브(실사격·되돌아보기)
    touch ~/.config/agora/chair-loop/STOP                        # 끄는 법(의장 루프와 같은 파일)
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import sys
from typing import Any, Callable

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agora import errors, tools                                # noqa: E402
from agora.errors import AgoraError                            # noqa: E402


def _sibling(name: str) -> Any:
    """옆 스크립트를 들인다(`tools/` 는 패키지가 아니다 — 경로로 부른다)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_ROOT, "tools", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)                               # type: ignore[union-attr]
    return mod


plaza_rules = _sibling("plaza")
chair = _sibling("chair_loop")

# ── 노브(설정 파일이 이긴다 · 하드코딩 금지) ────────────────────────────────
DEFAULTS = {
    "plaza": None,            # 광장 방 id — **없으면 아무것도 안 한다**
    "per_day": 2,             # 하루에 여는 방 수(N)
    "shelve_days": plaza_rules.SHELVE_DAYS,
    "stale_minutes": 240,     # 이만큼 지나도록 발언 0이면 [유찰]
    "deadlock_days": 2,       # 개설 0건이 이만큼 연속이면 최고점 하나를 연다
    "min_score": str(plaza_rules.MIN_SCORE),     # 개설 문턱 ①
    "min_voters": plaza_rules.MIN_VOTERS,        # 개설 문턱 ②(서로 다른 투표자)
}
CONFIG_FILE = "daily.json"


def load_config(state_dir: str) -> dict[str, Any]:
    doc = dict(DEFAULTS)
    try:
        with open(os.path.join(state_dir, CONFIG_FILE), encoding="utf-8") as fh:
            doc.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return doc


def room_brief(row: dict[str, Any]) -> tuple[str, str]:
    """방 제목과 발제를 **제안 원문에서** 만든다(지어내지 않는다)."""
    first = (row["body"].strip().splitlines() or ["(빈 제안)"])[0]
    title = first[:80]
    body = "\n".join([
        first,
        f"제안 {row['from']} · 득표 {row['voters']}명 · 점수 {row['score']}",
        "이 발제는 광장의 제안을 그대로 옮긴 것이다(기계가 요약하지 않았다).",
    ])
    return title, body


def plan(plaza: dict[str, Any], *, today: datetime.date, per_day: int,
         deadlock_days: int, min_score: Any = plaza_rules.MIN_SCORE,
         min_voters: int = plaza_rules.MIN_VOTERS) -> dict[str, Any]:
    """오늘 무엇을 열지 **계산만** 한다(쓰기 없음 · 시험이 여기를 직접 잰다)."""
    through = today - datetime.timedelta(days=1)          # 방금 닫힌 하루까지 접는다
    rows = plaza_rules.ranking(plaza, through=through)
    fits = plaza_rules.eligible(rows, min_score=min_score, min_voters=min_voters)
    picks = fits[:per_day]
    deadlock = False
    if not picks and rows:
        # ★교착 — 조건을 넘긴 것이 **이틀 연속 0건**이면 최고점 하나를 연다.
        #   (자기표 불산입 + 0표 개설 금지가 겹치면 영영 안 열리는 광장이 된다.)
        empty_days = 0
        for back in range(deadlock_days):
            day = through - datetime.timedelta(days=back)
            day_rows = plaza_rules.ranking(plaza, through=day)
            if not day_rows:
                break            # 그날은 후보 자체가 없었다 — 침묵이 아니라 **빈 광장**이다
            if plaza_rules.eligible(day_rows, min_score=min_score, min_voters=min_voters):
                break
            empty_days += 1
        if empty_days >= deadlock_days:
            picks = rows[:1]
            deadlock = True
    return {"through": through, "rows": rows, "picks": picks, "deadlock": deadlock}


def run(ctx: Any, *, state_dir: str, plaza_id: str, now: datetime.datetime | None = None,
        config: dict[str, Any] | None = None, notify: Callable[[str], None] | None = None,
        dry_run: bool = False) -> dict[str, Any]:
    """한 바퀴. **쓰기는 셋뿐이다** — 방 개설 · 마커 · 유찰 종료."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    conf = dict(DEFAULTS, **(config or {}))
    marks = chair.Marks(state_dir)
    said: list[str] = []
    did: list[dict[str, Any]] = []

    def tell(line: str) -> None:
        said.append(line)
        if notify and not dry_run:
            notify(line)

    if os.path.exists(os.path.join(state_dir, chair.STOP_FILE)):
        return {"stopped": True, "why": "STOP 파일이 있다 — 사람이 껐다", "opened": [],
                "said": said, "actions": did, "unverifiable": 0}

    reduced = tools._reduce(ctx, plaza_id)
    plaza = plaza_rules.read_plaza(reduced.get("events") or [])
    # ★**못 본 글을 말한다**(2026-09-11 실사격이 잡은 자리 · master 판정 [master#31af314b]).
    #   광장에 글이 있는데 **명부 밖·서명 실패**면 리듀서가 상태에서 빼 버리고, 파생층은 그 글의
    #   존재 자체를 모른다 ⇒ 전에는 출력이 `ranking: [] · unreadable: 0` 으로 **완벽하게 침묵했다.**
    #   ⇒ 「후보가 없다」와 「후보를 못 봤다」가 **같은 화면**이었다.
    #   실사격 실측: 참가자 하나의 제안 2 + 표 1 이 `not_in_roster` 로 통째로 빠졌는데 경고 0.
    #   라이브에서 이게 나면 글쓴이는 원장에 있으니 올라갔다고 믿고 보드는 「제안 없음」이라 말한다.
    # ⛔출력만 늘리고 통보를 안 붙이면 아무도 안 본다 — **통보까지가 봉합이다.**
    dropped = list(reduced.get("quarantined") or [])
    unverifiable = len(dropped)
    if unverifiable:
        reasons = sorted({str(q.get("reason")) for q in dropped})
        tell(f"【아고라】 광장에서 {unverifiable}건을 상태에 못 넣었다 — 명부·서명을 봐야 한다"
             f"({' · '.join(reasons)}). 그 글들은 이 판의 셈에서 빠졌다.")
    today = plaza_rules.day_of(now)
    sheet = plan(plaza, today=today, per_day=int(conf["per_day"]),
                 deadlock_days=int(conf["deadlock_days"]),
                 min_score=conf.get("min_score", plaza_rules.MIN_SCORE),
                 min_voters=int(conf.get("min_voters", plaza_rules.MIN_VOTERS)))

    def post_marker(kind: str, ident: str, thread: str | None = None,
                    note: str | None = None) -> None:
        line = plaza_rules.marker_line(kind, ident, thread, note)
        key = f"marker:{kind}:{ident}"
        if marks.done(plaza_id, key) or marks.failures(plaza_id, key) >= chair.RETRY_CAP:
            return
        did.append({"action": key, "what": line, "dry_run": dry_run})
        if dry_run:
            return
        try:
            tools.say(ctx, thread_id=plaza_id, body=line)
        except AgoraError as e:
            count = marks.fail(plaza_id, key, f"code {e.code} {e.message}")
            tell(f"【아고라】 광장 마커 실패({count}/{chair.RETRY_CAP}) — {line} · code {e.code}")
            return
        marks.mark(plaza_id, key, now.isoformat())
        tell(f"【아고라】 광장 {line}")

    # ① 오늘의 방 — 상위 N(또는 교착 해소 1)
    opened: list[dict[str, str]] = []
    for row in sheet["picks"]:
        key = f"open:{row['id']}"
        if marks.done(plaza_id, key) or marks.failures(plaza_id, key) >= chair.RETRY_CAP:
            continue
        title, body = room_brief(row)
        did.append({"action": key, "what": f"방 개설 · {title}", "dry_run": dry_run})
        if dry_run:
            continue
        try:
            out = tools.enter(ctx, topic=title, kind="debate", body=body)
        except AgoraError as e:
            count = marks.fail(plaza_id, key, f"code {e.code} {e.message}")
            tell(f"【아고라】 방 개설 실패({count}/{chair.RETRY_CAP}) — code {e.code} {e.message}")
            continue
        marks.mark(plaza_id, key, out["room_id"])
        chair.manage(state_dir, out["room_id"])            # 의장 루프가 이어받는다
        opened.append({"proposal": row["id"], "room": out["room_id"]})
        tell(f"【아고라】 방을 열었다 · {title} · {out['room_id'][:8]}"
             + (" (교착 해소)" if sheet["deadlock"] else ""))
        post_marker("졸업", row["id"], out["room_id"],
                    "교착 해소" if sheet["deadlock"] else None)

    # ② 오래된 제안은 가린다
    for pid in plaza_rules.to_shelve(plaza, now=now, days=int(conf["shelve_days"])):
        post_marker("보관", pid)

    # ③ 열렸는데 아무도 말하지 않은 방 — 권고 없이 닫는다
    graduated = [m for m in plaza["markers"] if m["kind"] == "졸업" and m.get("thread")]
    dead = {m["id"] for m in plaza["markers"] if m["kind"] == "유찰"}
    for marker in graduated:
        thread_id = marker["thread"]
        if thread_id in dead:
            continue
        room = chair.read_room(tools._reduce(ctx, thread_id))
        if room["state"] == "closed" or room["posts"]:
            continue
        started = chair._parse_ts(room["started_at"] or "")
        if started is None:
            tell(f"【아고라】 {thread_id[:8]} 시작 시각을 못 읽었다 — 사람이 봐야 한다")
            continue
        if (now - started).total_seconds() / 60.0 < float(conf["stale_minutes"]):
            continue
        key = f"stale:{thread_id}"
        if marks.done(plaza_id, key) or marks.failures(plaza_id, key) >= chair.RETRY_CAP:
            continue
        did.append({"action": key, "what": "발언 0 → 유찰", "dry_run": dry_run})
        if dry_run:
            continue
        try:
            tools.close(ctx, thread_id=thread_id, reason="unresolved")
        except AgoraError as e:
            marks.fail(plaza_id, key, f"code {e.code} {e.message}")
            continue
        marks.mark(plaza_id, key, now.isoformat())
        tell(f"【아고라】 {thread_id[:8]} 아무도 말하지 않아 닫았다(유찰)")
        post_marker("유찰", thread_id, None, "발언 0")

    return {"stopped": False, "opened": opened, "actions": did, "said": said,
            "today": str(today), "through": str(sheet["through"]),
            "deadlock": sheet["deadlock"], "unreadable": plaza["unreadable"],
            # ★`unreadable`(시각을 못 읽은 글)과 **다른 축**이다: 이쪽은 「자격이 없어 상태에
            #   안 들어간 글」이다. 둘을 한 칸에 뭉치면 「명부가 낡았다」와 「시각이 깨졌다」가
            #   같은 숫자로 보이고, 처방이 다른 두 사건이 한 이름을 갖는다.
            "unverifiable": unverifiable,
            "ranking": [{"id": r["id"], "score": str(r["score"]), "voters": r["voters"]}
                        for r in sheet["rows"][:5]]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="하루 한 바퀴 — 투표가 주제를 고른다")
    ap.add_argument("--plaza", default=None, help="광장 방 id(설정보다 우선)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", default=None, help="이 날짜로 친다(YYYY-MM-DD · 실사격·되돌아보기)")
    ap.add_argument("--state-dir", default=None)
    ap.add_argument("--per-day", type=int, default=None)
    ap.add_argument("--dir", default=None)
    args = ap.parse_args(argv)

    ctx = tools.context_from_config(args.dir)
    state_dir = args.state_dir or os.path.join(ctx.config_dir, "chair-loop")
    os.makedirs(state_dir, exist_ok=True)
    conf = load_config(state_dir)
    if args.per_day is not None:
        conf["per_day"] = args.per_day
    plaza_id = args.plaza or conf.get("plaza")
    if not plaza_id:
        print(json.dumps({"skipped": "광장 id 가 설정에 없다 — --plaza 나 daily.json 이 필요하다",
                          "config": os.path.join(state_dir, CONFIG_FILE)}, ensure_ascii=False))
        return errors.ARGUMENT

    now = None
    if args.date:
        # ★날짜 노브: 그날 **06:10 KST** 로 친다(개설 시각과 같은 자리).
        day = datetime.date.fromisoformat(args.date)
        now = datetime.datetime.combine(day, datetime.time(6, 10), plaza_rules.KST)

    lock = chair._lock(state_dir)
    if lock is None:
        print(json.dumps({"skipped": "이미 돌고 있다(잠금)"}, ensure_ascii=False))
        return 3
    try:
        out = run(ctx, state_dir=state_dir, plaza_id=plaza_id, now=now, config=conf,
                  notify=chair._inbox_notify, dry_run=args.dry_run)
        print(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2, default=str))
        return errors.OK
    finally:
        os.rmdir(lock)


def _guarded(argv: list[str] | None = None) -> int:
    """최후 방어 — 계약 실패를 **계약 모양으로** 낸다(설계 §4).

    ★왜(2026-09-11 실사격): `AGORA_SIGNING_KEY` 없이 문서대로 치면 파이썬 **역추적**이 쏟아졌다.
      메시지는 그 안에 있었지만(「서명 키가 지정되지 않았다」) 사람이 읽는 첫 화면은 스택이고,
      그 화면에는 **무엇을 해야 하는지가 없다.** 「오류가 났다」와 「원인을 말했다」는 다른 사건이다.
    ★rc 는 계약 코드 그대로 낸다 — launchd·상위 스크립트가 보는 유일한 칸이다.
    """
    try:
        return main(argv)
    except AgoraError as e:
        print(json.dumps({"code": e.code, "name": errors.NAMES.get(e.code, "error"),
                          "message": e.message, "detail": e.detail},
                         ensure_ascii=False), file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(_guarded())
