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

# 시험 참가자 셋 — **접두 `jarvis-test-` 가 계약**이다(purge 패턴 `jarvis-test-%`). 접두는 바꾸지 마라.
PARTICIPANTS = ("jarvis-test-r1", "jarvis-test-r2", "jarvis-test-r3")


def _participants(suffix: str | None) -> tuple[str, ...]:
    """이번 실행이 쓸 이름 셋.

    ★`--fresh-ids` 를 주면 접두는 그대로 두고 **꼬리만** 붙인다. 왜 필요한가: 실물 릴레이는 같은
      이름에 다른 키로 다시 등록하는 것을 **409 로 막는다**(옳다 — 이름 도둑질 방지). 그래서
      purge 없이 실물을 두 번 돌릴 수 없고, purge 는 운영자의 일이라 워커가 못 한다.
      ⇒ 재실행이 필요한 자리에서 **운영자를 기다리지 않도록** 꼬리를 붙인다. 접두가 같으므로
        purge 패턴에는 그대로 걸린다(= 정리 계약은 안 깨진다).
    ⚠기본값은 **끄기**다. 이름이 매번 달라지면 원장을 나중에 읽는 사람이 「누가 누구였나」를 못 맞춘다.
    """
    if not suffix:
        return PARTICIPANTS
    return tuple(f"{name}-{suffix}" for name in PARTICIPANTS)
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
        out_path: str | None = None, suffix: str | None = None) -> dict[str, Any]:
    participants = _participants(suffix)
    rec = Recorder()
    started_at = datetime.datetime.now(datetime.timezone.utc)
    workdir = tempfile.mkdtemp(prefix="agora-rehearsal-")
    print(f"■ 리허설 — 상대 = {'실물' if live else '가짜'} · 작업 폴더 {workdir}", flush=True)
    with _relay(live, relay_url) as (url, fake):
        dirs = {}
        for pid in participants:
            d = os.path.join(workdir, pid)
            os.makedirs(d, exist_ok=True)
            _keygen(d, pid)
            dirs[pid] = d

        stores: dict[str, Any] = {}
        ctxs: dict[str, Any] = {}
        # ★★**등재를 전부 마친 뒤에 명부를 받는다**(F-1 의 뿌리 · 09-06 원장이 증명).
        #   전에는 참가자마다 「등재 → 즉시 명부」였다. 그러면 **첫 참가자의 사본에는 뒤에 온
        #   둘이 없다** — 그 사본으로는 두 사람의 발언이 `unsigned` 로 격리되고, 의장은
        #   자기가 못 보는 글에게 진다(원장의 `roster` digest 가 셋 다 달랐다:
        #   `8501f9…`(r1) · `e4b640…`(r2) · `0ca385…`(r3)).
        #   ⇒ 순서 하나가 「밀린 글 4건」을 만들었다. 리허설은 순서를 굳히는 자리다.
        for pid in participants:
            _as(dirs[pid])
            rec.step("register", pid,
                     lambda d=dirs[pid]: onboard.register(directory=d, relay_url=url,
                                                          unattended=True))
        if any(r["step"] == "register" and r["code"] != 0 for r in rec.rows):
            # ★**등재가 안 됐으면 그 다음은 재는 시늉이다.** 여기서 멈추고 표를 낸다
            #   (전에는 그대로 진행하다 설정 부재로 **역추적**이 났다 — 스택트레이스는 기록이 아니다).
            print("  ⛔등재 실패 — 이어서 진행하지 않는다(표만 낸다).", flush=True)
            return _finish(rec, started_at, live, url, None, out_path, workdir, participants)
        for pid in participants:
            d = dirs[pid]
            _as(d)
            rec.step("sync-roster(등재 전건 뒤)", pid,
                     lambda d=d: onboard.sync_roster(directory=d, relay_url=url, yes=True))
            ctx = tools.context_from_config(d)
            ctxs[pid], stores[pid] = ctx, ctx.store
        if any(r["step"].startswith("sync-roster") and r["code"] != 0 for r in rec.rows):
            # ★★**명부가 반쪽이면 그 다음은 재는 시늉이다**(codex 2R MEDIUM · 2026-09-09).
            #   등재 실패에는 중단문이 있었는데 sync 실패에는 없었다 — 그런데 F-1 의 뿌리가
            #   바로 **반쪽 명부**였다(의장 사본에 뒤에 온 둘이 없어 그들의 발언이 격리됐다).
            #   ⇒ 부분 명부로 방을 열면 이 하네스는 **자기가 재려는 결함을 스스로 만든다.**
            #   ⚠genesis 에는 CAS 도 `_blind_spot` 도 안 걸린다(견줄 앞 상태가 없다) —
            #     그래서 이 자리가 마지막 문이다. 여기서 안 막으면 아무도 안 막는다.
            print("  ⛔명부 동기화 실패 — POST 0건으로 멈춘다(표만 낸다).", flush=True)
            return _finish(rec, started_at, live, url, None, out_path, workdir, participants)

        chair = participants[0]
        _as(dirs[chair])
        opened = rec.step("enter(방 개설)", chair,
                          lambda: tools.enter(ctxs[chair], topic=TOPIC, kind="debate",
                                              body="리허설 발제 — 오늘 재는 것은 절차다"),
                          store=stores[chair])
        room = (opened or {}).get("room_id")
        if not room:
            return _finish(rec, started_at, live, url, room, out_path, workdir, participants)

        for pid in participants[1:]:
            _as(dirs[pid])
            rec.step("browse(로비)", pid, lambda p=pid: tools.browse(ctxs[p]), store=stores[pid])
            rec.step("join", pid, lambda p=pid: tools.join(ctxs[p], room_id=room),
                     store=stores[pid])

        for pid in participants:
            _as(dirs[pid])
            rec.step("say(발언)", pid,
                     lambda p=pid: tools.say(ctxs[p], thread_id=room,
                                             body=f"{p} 의 발언 — 리허설 1라운드"),
                     store=stores[pid])

        # ★쓰기 묶음이 끝날 때마다 **원장에게 물어본다** — 「초록이었다」가 아니라 「원장이 뭐라 하는가」.
        _triple_step(rec, ctxs[chair], stores[chair], room, "3자 대조(발언 뒤)", chair)

        _as(dirs[chair])
        # ★**r3 까지 간다.** 권고안(`resolution`)은 계약상 **r3 에서만** 성립한다
        #   (reducer: `state != "r3"` → `bad_transition`). 전에는 r2 에서 곧장 권고안을 냈고,
        #   릴레이는 그것을 격리했는데 **클라이언트가 rc 0 을 냈다** — 09-06 원장의 밀림 4건에
        #   가려 이 결함이 안 보였다. ★한 결함이 다른 결함을 가리면, 앞의 것을 고치는 순간
        #   뒤의 것이 드러난다(2026-09-08 실물 재실행에서 실제로 그렇게 드러났다).
        for target in (1, 2, 3):
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
        reader = participants[1]
        _as(dirs[reader])
        watched = rec.step("watch(한 바퀴)", reader,
                           lambda: _watch_once(ctxs[reader], dirs[reader]),
                           store=stores[reader])
        target_message = None
        for item in ((read_out or {}).get("events") or []):
            if item.get("kind") == "post" and item.get("from") == chair:
                target_message = item.get("message_id")
                break
        # ★★**조용히 건너뛰지 않는다**(agy 적대검증 2026-09-06 지적 · 수용): 앞 단계가 아무것도
        #   건네지 못했을 때 ack 단계를 빼면, 실패가 「단계 없음」으로 사라지고 요약은 **실패 0**
        #   으로 초록이 된다. 못 하는 상황이면 **못 했다고 적는다.**
        rec.step("ack(수신 영수증)", reader,
                 lambda: _ack_or_explain(ctxs[reader], target_message, watched))

        # ★★**말하는 사람을 되돌린다.** 위에서 읽는 참가자로 바꿔 놓고 그대로 의장 일을 하면,
        #   이벤트의 `from` 은 의장인데 서명은 남의 키가 된다 — 가짜 릴레이는 서명을 안 보고
        #   통과시키지만 **실물은 401(principal_mismatch)로 거부한다**(2026-09-06 라이브 실측).
        _as(dirs[chair])
        rec.step("resolve(권고안)", chair,
                 lambda: tools.resolve(ctxs[chair], thread_id=room,
                                       summary="리허설 수렴 — 절차가 끝까지 돌았다",
                                       dissent=[{"from": participants[1],
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
        # ★마지막 대조 — 여기서 **닫혔다고 말하는 두 리듀서**가 같은 말을 해야 완주다.
        _triple_step(rec, ctxs[chair], stores[chair], room, "3자 대조(종결 뒤)", chair,
                     expect_closed=True)
        return _finish(rec, started_at, live, url, room, out_path, workdir, participants)


def _ack_or_explain(ctx: Any, message_id: str | None, watched: dict[str, Any] | None) -> Any:
    """영수증을 쓴다 — 쓸 수 없으면 **그 사실을 실패로 올린다**(건너뛰지 않는다)."""
    if not message_id:
        raise AgoraError(errors.PRECONDITION, "ack 할 글을 못 찾았다 — 읽기 단계가 비었다",
                         {"reason": "no_post_to_ack"})
    if not (watched or {}).get("delivered"):
        raise AgoraError(errors.PRECONDITION, "감시가 아무것도 건네지 않았다 — ack 할 것이 없다",
                         {"reason": "nothing_delivered", "watch": watched})
    return tools.ack(ctx, message_id=message_id)


def _relay_rows(store: Any, room: str) -> list[dict[str, Any]]:
    """릴레이 원장 + **그쪽 판정**을 그대로 가져온다(대조 전용 문 · `audit_events`)."""
    audit = getattr(store, "audit_events", None)
    if audit is None:
        return []
    return audit(thread_id=room)


def _invalid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("valid") is False]


def _local_state(ctx: Any, room: str) -> dict[str, Any]:
    """우리 리듀서의 판정 — **정본은 이쪽**이다(계약 §3-5)."""
    from agora import tools as _t
    reduced = _t._reduce(ctx, room)
    # ★우리 리듀서에는 `closed` 칸이 없다 — **상태가 곧 그것**이다(`state == "closed"`).
    #   불린 칸을 지어내면 없는 사실을 대조하게 된다(첫 판에 실제로 그렇게 적었다가 잡혔다).
    return {"state": reduced.get("state"), "round": reduced.get("round"),
            "closed": reduced.get("state") == "closed",
            # ★우리 리듀서에는 `answered` 칸이 없다 — **답이 골라졌는가 = `solved_by` 가 찼는가**다.
            #   이름이 다르다고 대조를 건너뛰면 축 하나가 조용히 빈다.
            "answered": bool(reduced.get("solved_by")),
            "state_hash": reduced.get("state_hash"),
            "close_reason": reduced.get("close_reason"), "head": reduced.get("head"),
            "quarantined": len(reduced.get("quarantined") or []),
            "stale": len(reduced.get("stale") or [])}


def triple_check(ctx: Any, store: Any, room: str) -> dict[str, Any]:
    """3자 대조 — **릴레이 원장 · 우리 기록 · 파생 상태**를 한자리에서 댄다(브리프 ⓒ·ⓕ).

    ★09-06 이 이 대조를 **사람이 나중에 손으로** 했다: 하네스는 22/22 초록이었고, 릴레이 원장을
      열어 보고서야 네 건이 밀렸다는 것을 알았다. ★대조가 하네스 밖에 있으면 그 대조는
      **하기로 한 사람이 잊는 순간 사라진다.** 그래서 안으로 넣는다.
    ★세 축이 각각 무엇을 말하는가: 릴레이 `valid` = 그쪽 리듀서가 받아들였나 ·
      우리 reducer = **정본 판정** · 파생 상태(state·round·closed) = 두 리듀서가 같은 결론인가.
    """
    rows = _relay_rows(store, room)
    invalid = _invalid_rows(rows)
    local = _local_state(ctx, room)
    mismatch: list[str] = []
    # ★★대조 축을 **못 읽는 것은 초록이 아니다**(codex 2R HIGH · 2026-09-09). 구판은 목록
    #   실패를 `"unavailable"` 이라고 적어 두고 그대로 지나갔다 — 그러면 「축이 일치했다」와
    #   「축을 못 봤다」가 같은 rc 0 이 된다. `--verify` 의 rc 0 은 **원장이 그렇다고 말했다**는
    #   뜻이어야 하므로, 읽기 실패는 fail-closed 로 **mismatch 에 센다.**
    try:
        derived = dict(store.thread_status(thread_id=room) or {}) \
            if hasattr(store, "thread_status") else {}
    except Exception as e:       # noqa: BLE001 — 못 읽었다는 사실 자체가 판정이다
        derived = {}
        mismatch.append(f"릴레이 파생 상태를 못 읽었다(fail-closed): {type(e).__name__}: {e}")
    if derived.get("why") == "relay_does_not_derive":
        # ★상대가 파생을 **안 하는** 것과 우리가 **못 읽은** 것은 다른 사건이지만, 대조에
        #   미치는 영향은 같다: 견줄 축이 없다. 3자 대조가 2자 대조로 조용히 줄어드는 것을 막는다.
        mismatch.append("릴레이가 상태를 파생하지 않는다 — 3자 대조의 한 축이 비었다")
    # ★방 목록 행에는 파생 `state`·`round` 가 더 있다(계약 §3-3). 방 조회에 없는 칸이라
    #   따로 주워 와 **댈 수 있는 축을 다 댄다**(agy 1R 지적 5 · 부분 수용).
    try:
        for item in (store.list_threads(limit=100) or {}).get("items") or []:
            if str(item.get("number") or item.get("room_id") or "") == room:
                for field in ("state", "round", "answered", "closed"):
                    if field in item and field not in derived:
                        derived[field] = item[field]
                break
    except Exception as e:       # noqa: BLE001 — 목록을 못 받은 것도 **미측정**이다
        derived.setdefault("list_threads", "unavailable")
        mismatch.append(f"릴레이 방 목록(list_threads)을 못 읽었다(fail-closed): "
                        f"{type(e).__name__}: {e}")
    # ★`state_hash` 를 **여기 넣는 것이 이 봉합의 알맹이다**(codex 2R HIGH). 구판은 이 값을
    #   양쪽 다 **출력만** 하고 대조하지 않았다 — 서로 다른 역사가 같은 이름·라운드에 이를 수
    #   있으므로(그래서 해시에 head 가 들어간다) 이 축이 빠지면 대조가 가장 중요한 것을 놓친다.
    for field in ("closed", "answered", "state", "round", "state_hash", "close_reason"):
        theirs = derived.get(field)
        if field not in derived or field not in local:
            continue            # 상대가 안 파생하는 칸은 **대조하지 않는다**(모른다 ≠ 같다)
        ours = local[field]
        if theirs is None and ours is None:
            continue
        same = (bool(theirs) == bool(ours)) if field in ("closed", "answered") \
            else (theirs == ours)
        if not same:
            mismatch.append(f"{field}: 릴레이 {theirs} vs 우리 {ours}")
    if invalid:
        mismatch.append(f"릴레이가 반영 안 한 글 {len(invalid)}건: "
                        + ", ".join(f"{r.get('node_id')}({r.get('reason')})" for r in invalid[:5]))
    return {"events": len(rows), "invalid": len(invalid), "local": local,
            "relay_derived": derived, "mismatch": mismatch,
            "rows": [{"node_id": r.get("node_id"), "valid": r.get("valid"),
                      "reason": r.get("reason")} for r in rows]}


def verify(room_ids: list[str], *, directory: str | None = None,
           relay_url: str | None = None) -> int:
    """`--verify <room-id> …` — **읽기만** 하고 3자 대조 표를 낸다(rc 0 = 무효 0·파생 일치).

    ★스터디팀 시험 모임이 이 명령으로 판정한다: 「초록이었다」가 아니라 **원장이 뭐라고 하는가**.
    ⛔쓰기 0. 라이브에 붙어도 이 명령은 남의 원장에 한 줄도 안 쓴다.
    """
    from agora.participant import config_dir as _config_dir
    directory = directory or _config_dir()
    _as(directory)
    store = None
    if relay_url:
        from agora.store_relay import RelayStore
        store = RelayStore(relay_url)
    ctx = tools.context_from_config(directory, store=store)
    failed = 0
    for room in room_ids:
        out = triple_check(ctx, ctx.store, room)
        print(f"\n■ 방 {room} — 이벤트 {out['events']} · 무효 {out['invalid']}")
        print("  | event_id | valid | reason |")
        print("  |---|---|---|")
        for r in out["rows"]:
            print(f"  | {r['node_id']} | {r['valid']} | {r['reason'] or '—'} |")
        print(f"  우리 리듀서 = state {out['local']['state']} · round {out['local']['round']} · "
              f"closed {out['local']['closed']} · answered {out['local']['answered']} · "
              f"격리 {out['local']['quarantined']} · 밀림 {out['local']['stale']}")
        print(f"  우리 사슬   = head {str(out['local']['head'])[:12]}… · "
              f"state_hash {str(out['local']['state_hash'])[:12]}… · "
              f"close_reason {out['local']['close_reason'] or '—'}")
        print(f"  릴레이 파생 = {json.dumps(out['relay_derived'], ensure_ascii=False)}")
        for line in out["mismatch"]:
            print(f"  🔴 어긋남 — {line}")
        if out["mismatch"]:
            failed += 1
    print(f"\n판정: 방 {len(room_ids)} 중 어긋남 {failed}")
    return errors.OK if failed == 0 else errors.STORE


def _triple_step(rec: Recorder, ctx: Any, store: Any, room: str, label: str,
                 who: str, *, expect_closed: bool | None = None) -> None:
    """3자 대조를 **단계로** 남긴다 — 어긋나면 그 단계가 실패다(요약의 「실패」에 들어간다)."""
    def check() -> dict[str, Any]:
        out = triple_check(ctx, store, room)
        problems = list(out["mismatch"])
        if expect_closed is not None:
            got = out["relay_derived"].get("closed")
            if got is not None and bool(got) != expect_closed:
                problems.append(f"릴레이 파생 closed={got} (기대 {expect_closed})")
            if out["local"]["closed"] != expect_closed:
                problems.append(f"우리 판정 closed={out['local']['closed']} (기대 {expect_closed})")
        if problems:
            raise AgoraError(errors.STORE, "3자 대조 어긋남",
                             {"reason": "triple_check_mismatch", "problems": problems,
                              "invalid": out["invalid"]})
        return out
    rec.step(label, who, check, store=store)


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
            out_path: str | None, workdir: str,
            _finish_participants: tuple[str, ...] | None = None) -> dict[str, Any]:
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
        "참가자": list(_finish_participants or PARTICIPANTS),
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
        f"> 참가자 = {' · '.join(f'`{p}`' for p in summary.get('참가자', PARTICIPANTS))} "
        f"· 방 = `{summary['방']}`",
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
    parser.add_argument("--verify", nargs="+", metavar="ROOM-ID", default=None,
                        help="방 3자 대조만 한다(읽기 전용 · 완주하지 않는다)")
    parser.add_argument("--dir", default=None, help="--verify 가 쓸 설정 폴더(기본 = 설정 기본값)")
    parser.add_argument("--fresh-ids", action="store_true",
                        help="참가자 이름에 꼬리를 붙인다(접두 jarvis-test- 유지 · 실물 재실행용)")
    args = parser.parse_args(argv)
    if args.verify:
        # ⛔완주하지 않는다 — 이 갈래는 **읽기만** 한다.
        return verify(args.verify, directory=args.dir,
                      relay_url=args.relay or (None if not args.live else None))
    out = args.out
    if out is None:
        today = datetime.date.today().isoformat()
        out = os.path.join(_ROOT, "docs", "rehearsal",
                           f"{today}{'-live' if args.live else '-fake'}.md")
    suffix = None
    if args.fresh_ids:
        import secrets
        suffix = secrets.token_hex(3)
    result = run(live=args.live, relay_url=args.relay, out_path=out, suffix=suffix)
    return errors.OK if result["summary"]["실패"] == 0 else errors.STORE


if __name__ == "__main__":
    raise SystemExit(main())
