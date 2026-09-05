#!/usr/bin/env python3
"""리허설 하네스 — **3 워커가 한 주제를 끝까지 도는 것**을 스크립트로 완주시킨다(r4).

왜 스크립트인가: 리허설 본행은 사람이 지켜보는 자리다. 그때 「명령을 어떤 순서로 치더라」를
기억으로 하면, 실패했을 때 **무엇이 실패했는지**가 사람의 기억과 섞인다. 순서를 코드로 굳혀
놓으면 실패는 언제나 **어느 단계에서, 어떤 코드로** 났는지로 남는다.

★**기본은 가짜 릴레이다.** 실물은 `--live` 를 명시할 때만 만진다 — 리허설 하네스가 실수로
  실물에 글을 쓰는 일은 「한 번이면 충분히 나쁘다」(원장은 append-only 라 되돌릴 수 없다).
★참가자 이름은 `jarvis-test-…` 만 쓴다(purge 패턴 `jarvis-test-%`). 다른 접두는 만들지 않는다.
★각 단계의 **응답 시간·오류 코드·요청 수**를 적는다. 429 를 만나면 `Retry-After` 를 존중하고
  그 사실을 표에 남긴다(어댑터가 이미 존중한다 · 여기서는 **일어났다는 것**을 기록한다).

쓰는 법:
    python3 tools/rehearsal.py                      # 가짜 릴레이(기본) · 결과 파일 생성
    python3 tools/rehearsal.py --live               # 실물 릴레이(설정의 relay.url)
    python3 tools/rehearsal.py --live --relay <url> # 실물 릴레이 주소 명시
    python3 tools/rehearsal.py --out docs/rehearsal/2026-09-07.md
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import statistics
import sys
import tempfile
import time
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agora import errors, onboard, tools                      # noqa: E402
from agora.errors import AgoraError                           # noqa: E402
from agora.store_relay import USER_AGENT                      # noqa: E402

# 시험 참가자 셋 — 이름은 계약(purge 패턴)이다. 바꾸지 마라.
PARTICIPANTS = ("jarvis-test-r1", "jarvis-test-r2", "jarvis-test-r3")
TOPIC = "리허설 — 워커 셋이 한 주제를 끝까지 돈다"


def _as(directory: str) -> None:
    """이 폴더의 참가자로 **말한다** — 설정 폴더와 서명 키를 같이 세운다.

    ★둘 중 하나만 바꾸면 서명기가 다른 참가자의 키로 서명하거나, 코어와 서명기가 다른 폴더를 본다.
      한 함수로 묶어 두면 「하나만 바꾸는 실수」가 생길 자리가 없다.
    """
    os.environ["AGORA_CONFIG_DIR"] = directory
    os.environ["AGORA_SIGNING_KEY"] = os.path.join(directory, "id_ed25519")


class Recorder:
    """단계마다 **무슨 일이 있었는지**를 한 줄로 남긴다."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.rate_limited = 0

    def step(self, name: str, who: str, fn: Any, *, store: Any = None) -> Any:
        calls_before = getattr(store, "calls", 0) if store is not None else 0
        waits_before = len(getattr(store, "waits", []) or []) if store is not None else 0
        started = time.time()
        row: dict[str, Any] = {"step": name, "who": who}
        try:
            out = fn()
            row["code"] = 0
        except AgoraError as e:
            out = None
            row["code"] = e.code
            row["detail"] = json.dumps(e.detail, ensure_ascii=False)[:160] if e.detail else ""
        row["ms"] = int((time.time() - started) * 1000)
        if store is not None:
            row["requests"] = getattr(store, "calls", 0) - calls_before
            waited = len(getattr(store, "waits", []) or []) - waits_before
            if waited:
                # ★기다렸다는 것은 429·5xx 를 만났다는 뜻이다 — 표에 남긴다.
                self.rate_limited += waited
                row["waited"] = waited
        self.rows.append(row)
        print(f"  {row['code']:>2}  {row['ms']:>6}ms  {name} ({who})", flush=True)
        return out


@contextlib.contextmanager
def _relay(live: bool, relay_url: str | None):
    """상대를 고른다 — **기본은 가짜**다."""
    if live:
        if not relay_url:
            raise SystemExit("--live 에는 --relay <url> 또는 설정의 relay.url 이 필요하다")
        yield relay_url, None
        return
    tests_dir = os.path.join(_ROOT, "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    import fake_relay
    with fake_relay.serving() as (url, relay):
        yield url, relay


def run(*, live: bool = False, relay_url: str | None = None,
        out_path: str | None = None) -> dict[str, Any]:
    rec = Recorder()
    started_at = datetime.datetime.now(datetime.timezone.utc)
    workdir = tempfile.mkdtemp(prefix="agora-rehearsal-")
    print(f"■ 리허설 — 상대 = {'실물' if live else '가짜'} · 작업 폴더 {workdir}", flush=True)
    with _relay(live, relay_url) as (url, fake):
        dirs = {}
        for pid in PARTICIPANTS:
            d = os.path.join(workdir, pid)
            os.makedirs(d, exist_ok=True)
            _keygen(d, pid)
            dirs[pid] = d

        stores: dict[str, Any] = {}
        ctxs: dict[str, Any] = {}
        for pid in PARTICIPANTS:
            d = dirs[pid]
            _as(d)
            rec.step("register", pid,
                     lambda d=d: onboard.register(directory=d, relay_url=url, unattended=True))
            rec.step("sync-roster", pid,
                     lambda d=d: onboard.sync_roster(directory=d, relay_url=url, yes=True))
            ctx = tools.context_from_config(d)
            ctxs[pid], stores[pid] = ctx, ctx.store

        chair = PARTICIPANTS[0]
        _as(dirs[chair])
        opened = rec.step("enter(방 개설)", chair,
                          lambda: tools.enter(ctxs[chair], topic=TOPIC, kind="debate",
                                              body="리허설 발제 — 오늘 재는 것은 절차다"),
                          store=stores[chair])
        room = (opened or {}).get("room_id")
        if not room:
            return _finish(rec, started_at, live, url, room, out_path, workdir)

        for pid in PARTICIPANTS[1:]:
            _as(dirs[pid])
            rec.step("browse(로비)", pid, lambda p=pid: tools.browse(ctxs[p]), store=stores[pid])
            rec.step("join", pid, lambda p=pid: tools.join(ctxs[p], room_id=room),
                     store=stores[pid])

        for pid in PARTICIPANTS:
            _as(dirs[pid])
            rec.step("say(발언)", pid,
                     lambda p=pid: tools.say(ctxs[p], thread_id=room,
                                             body=f"{p} 의 발언 — 리허설 1라운드"),
                     store=stores[pid])

        _as(dirs[chair])
        for target in (1, 2):
            rec.step(f"advance(→r{target})", chair,
                     lambda t=target: tools.advance(ctxs[chair], thread_id=room, to_round=t),
                     store=stores[chair])

        read_out = rec.step("read(전건 읽기)", chair,
                            lambda: tools.read(ctxs[chair], thread_id=room),
                            store=stores[chair])

        # ★**받은 것을 ack 한다** — 영수증은 「본 것」이 아니라 「건네받은 것」에만 쓴다.
        #   그래서 watch 한 바퀴(`once=True`)를 먼저 돌려 spool 에 delivered 를 만든다.
        #   ⚠지름길로 `ack.deliver` 를 직접 부르지 않는다: 그러면 **검증을 안 지난 글도**
        #     영수증을 받을 수 있고, 리허설이 실제 운영 경로와 달라진다.
        reader = PARTICIPANTS[1]
        _as(dirs[reader])
        watched = rec.step("watch(한 바퀴)", reader,
                           lambda: _watch_once(ctxs[reader], dirs[reader]),
                           store=stores[reader])
        target_message = None
        for item in ((read_out or {}).get("events") or []):
            if item.get("kind") == "post" and item.get("from") == chair:
                target_message = item.get("message_id")
                break
        if target_message and (watched or {}).get("delivered"):
            rec.step("ack(수신 영수증)", reader,
                     lambda: tools.ack(ctxs[reader], message_id=target_message))

        # ★★**말하는 사람을 되돌린다.** 위에서 읽는 참가자로 바꿔 놓고 그대로 의장 일을 하면,
        #   이벤트의 `from` 은 의장인데 서명은 남의 키가 된다 — 가짜 릴레이는 서명을 안 보고
        #   통과시키지만 **실물은 401(principal_mismatch)로 거부한다**(2026-09-06 라이브 실측).
        _as(dirs[chair])
        rec.step("resolve(권고안)", chair,
                 lambda: tools.resolve(ctxs[chair], thread_id=room,
                                       summary="리허설 수렴 — 절차가 끝까지 돌았다",
                                       dissent=[{"from": PARTICIPANTS[1],
                                                 "quote": "다른 각도도 남는다"}],
                                       recommended_actions=[
                                           {"text": "다음 라운드에서 같은 절차를 반복한다",
                                            "execution": "forbidden"}]),
                 store=stores[chair])
        rec.step("close(종결)", chair,
                 lambda: tools.close(ctxs[chair], thread_id=room, reason="solved"),
                 store=stores[chair])
        rec.step("threads(종결 확인)", chair,
                 lambda: tools.threads(ctxs[chair]), store=stores[chair])
        return _finish(rec, started_at, live, url, room, out_path, workdir)


def _watch_once(ctx: Any, directory: str) -> dict[str, Any]:
    """감시 한 바퀴 — 새 글을 받아 **검증하고** spool 에 `delivered` 로 적는다(운영 경로 그대로)."""
    from agora.watch import Cursor, run as watch_run
    cursor = Cursor(os.path.join(directory, "watch-cursor.json"))
    return watch_run(store=ctx.store, spool=ctx.spool, cursor=cursor, ledger=ctx.ledger,
                     once=True, emit=lambda _line: None,
                     allowed_signers_path=ctx.allowed_signers_path,
                     revoked_path=os.path.join(directory, "revoked_keys"))


def _keygen(directory: str, participant_id: str) -> None:
    """키·`participant.json` 을 만든다 — `agora keygen` 과 **같은 코드**를 부른다.

    ★`keygen.run` 은 설정 폴더를 환경(`AGORA_CONFIG_DIR`)에서 읽는다. 리허설은 참가자가 셋이라
      **매번 그 환경을 그 참가자의 폴더로 세우고** 부른다 — 한 폴더를 셋이 쓰면 키가 겹친다.
    """
    from agora import keygen
    os.environ["AGORA_CONFIG_DIR"] = directory
    os.environ["AGORA_SIGNING_KEY"] = os.path.join(directory, "id_ed25519")
    keygen.run([participant_id])


def _finish(rec: Recorder, started_at: Any, live: bool, url: str, room: str | None,
            out_path: str | None, workdir: str) -> dict[str, Any]:
    failures = [r for r in rec.rows if r["code"] != 0]
    times = [r["ms"] for r in rec.rows]
    summary = {
        "상대": "실물" if live else "가짜",
        "릴레이": url,
        "방": room,
        "단계": len(rec.rows),
        "실패": len(failures),
        "요청_합계": sum(r.get("requests", 0) for r in rec.rows),
        "중앙값_ms": int(statistics.median(times)) if times else 0,
        "최대_ms": max(times) if times else 0,
        "한도_대기": rec.rate_limited,
        "작업_폴더": workdir,
        "user_agent": USER_AGENT,
    }
    report = _render(rec, summary, started_at, live)
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(report)
        summary["보고서"] = out_path
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    return {"summary": summary, "rows": rec.rows, "report": report}


def _render(rec: Recorder, summary: dict[str, Any], started_at: Any, live: bool) -> str:
    stamp = started_at.strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        f"# 리허설 기록 — {stamp} ({'실물' if live else '가짜'} 릴레이)",
        "",
        f"> 상대 = `{summary['릴레이']}` · UA = `{summary['user_agent']}`",
        f"> 참가자 = {' · '.join(f'`{p}`' for p in PARTICIPANTS)} · 방 = `{summary['방']}`",
        "",
        "⚠**가짜 릴레이 상대의 초록은 「절차가 맞다」는 뜻이지 「실물이 그렇게 답한다」는 뜻이 아니다.**",
        "",
        "| # | 단계 | 참가자 | code | 응답(ms) | 요청 | 대기 |",
        "|---|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(rec.rows, 1):
        lines.append(
            f"| {index} | {row['step']} | `{row['who']}` | {row['code']} | {row['ms']} | "
            f"{row.get('requests', '—')} | {row.get('waited', '—')} |")
    lines += [
        "",
        f"**요약** — 단계 {summary['단계']} · 실패 **{summary['실패']}** · 요청 합계 "
        f"{summary['요청_합계']} · 응답 중앙값 {summary['중앙값_ms']}ms · 최대 {summary['최대_ms']}ms · "
        f"한도 대기 {summary['한도_대기']}회",
        "",
        "실패가 있으면 아래에 코드와 사유를 그대로 적는다(요약하지 않는다).",
        "",
    ]
    for row in rec.rows:
        if row["code"] != 0:
            lines.append(f"- **{row['step']}**(`{row['who']}`) → code {row['code']} · "
                         f"{row.get('detail', '')}")
    if summary["실패"] == 0:
        lines.append("- 실패 없음.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="아고라 리허설 하네스(기본 = 가짜 릴레이)")
    parser.add_argument("--live", action="store_true",
                        help="실물 릴레이에 붙는다(명시하지 않으면 가짜 릴레이)")
    parser.add_argument("--relay", default=None, help="릴레이 주소(--live 와 함께)")
    parser.add_argument("--out", default=None, help="결과 표를 쓸 경로(docs/rehearsal/<날짜>.md)")
    args = parser.parse_args(argv)
    out = args.out
    if out is None:
        today = datetime.date.today().isoformat()
        out = os.path.join(_ROOT, "docs", "rehearsal",
                           f"{today}{'-live' if args.live else '-fake'}.md")
    result = run(live=args.live, relay_url=args.relay, out_path=out)
    return errors.OK if result["summary"]["실패"] == 0 else errors.STORE


if __name__ == "__main__":
    raise SystemExit(main())
