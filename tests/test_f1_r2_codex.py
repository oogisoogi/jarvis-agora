"""codex 적대검증 2R(2026-09-09 · BLOCK) 재현 프로브를 **테스트로 승격**한 것.

★왜 승격하는가: codex 는 여섯 결함을 **일회용 인메모리 프로브**로 재현했다. 프로브는 판정문에만
  남고 저장소에는 남지 않는다 ⇒ 같은 자리가 다시 열려도 아무 그물에 안 걸린다.
  「재현했다」와 「다시 나면 붉어진다」는 다른 말이다.

★각 시험은 판정문의 finding 과 **1:1** 이다. 이름 뒤 대괄호가 그 대응이다.
  봉합 전에는 전건 **적색**이어야 한다 — 그것을 먼저 실측하고 봉합했다(적→초 표는 보고에 있다).

★pytest 없이도 돈다: `python3 tests/test_f1_r2_codex.py` 로 직접 실행하면 같은 것을 재고
  같은 판정을 낸다(이 저장소에는 pytest 가 설치돼 있지 않은 기계가 있다 — 검사기가 없어서
  안 재는 것과 재서 통과한 것을 구별하기 위해 폴백 러너를 붙인다).
"""
from __future__ import annotations

import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agora import core, errors, reducer, tools           # noqa: E402
from agora.errors import AgoraError                       # noqa: E402
from agora.event import event_hash, new_id, render_post    # noqa: E402


# ── 공통 도우미 ─────────────────────────────────────────────────────────────

def _body(**over: object) -> str:
    """계약 §2-1 뼈대 11칸을 갖춘 이벤트 본문. **손으로 적는다**(우리 조립기를 쓰면 자기 대조가 된다)."""
    event = {"v": 1, "kind": "post", "thread_id": "t1", "message_id": new_id(),
             "prev": "", "expected_state": "", "from": "alice", "roster": "r0",
             "scrub": {"rules": "b0", "blocked": False, "redacted": []},
             "ts": "2026-09-09T00:00:00.000Z",
             "payload": {"round": 0, "body": "x"}}
    event.update(over)                      # type: ignore[arg-type]
    return render_post(event)


class _Ledger:
    """원장 더블 — `has`/`append` 두 칸만. 무엇이 적혔는지 세는 것이 목적이다."""

    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def has(self, message_id: str) -> bool:
        return any(r["message_id"] == message_id for r in self.rows)

    def append(self, **row: object) -> dict[str, object]:
        self.rows.append(row)
        return row


# ── [CRITICAL] 응답 유실 뒤 valid:false 를 「존재함 = committed」로 오판 ──────

def test_a_audit_verdict_must_not_call_rejected_row_committed() -> None:
    """재조회는 **적혀 있는가**가 아니라 **반영됐는가**를 물어야 한다.

    codex 재현: POST 가 원장에 적재됐으나 `lost_race`·`valid:false` → 응답 유실(code 8)
    → 재조회 → 본문에 message_id 가 있다는 이유만으로 `committed` → 클라이언트 rc 0.
    """
    mid = new_id()
    row = {"node_id": "ev_0000000000000007", "body": f'{{"message_id":"{mid}"}}',
           "created_at": "2026-09-09T00:00:00.000Z", "is_genesis": False}

    class Store:
        def fetch(self, *, thread_id: str, **_: object) -> dict[str, object]:
            return {"items": [dict(row)], "next_cursor": None}

        def audit_events(self, *, thread_id: str, limit: int = 200) -> list[dict[str, object]]:
            # 대조 전용 읽기 = 릴레이가 준 파생 판정까지 온다(계약 §3-5).
            return [dict(row, valid=False, quarantined=False, stale=True, reason="lost_race")]

    verdict, reason = core.audit_verdict(store=Store(), thread_id="t1", message_id=mid)
    assert verdict != core.COMMITTED, (
        f"원장에 있다는 이유만으로 {verdict!r} 로 판정했다 — 릴레이는 valid:false 라고 했다")
    assert verdict == core.REJECTED and reason == "lost_race"

    settled = core.settle_unknown(store=Store(), ledger=(led := _Ledger()),
                                  event={"thread_id": "t1", "message_id": mid},
                                  event_hash="h")
    assert settled["verdict"] == core.REJECTED
    assert settled.get("reason") == "lost_race"
    assert led.rows == [], "반영 안 된 글을 원장에 「보냈다」고 적었다"


def test_a2_audit_verdict_stays_committed_when_relay_accepted() -> None:
    """대조군 — 릴레이가 받아들인 글은 그대로 `committed` 여야 한다(과잉 차단 방지)."""
    mid = new_id()
    row = {"node_id": "ev_0000000000000007", "body": f'{{"message_id":"{mid}"}}',
           "created_at": "2026-09-09T00:00:00.000Z", "is_genesis": False}

    class Store:
        def fetch(self, *, thread_id: str, **_: object) -> dict[str, object]:
            return {"items": [dict(row)], "next_cursor": None}

        def audit_events(self, *, thread_id: str, limit: int = 200) -> list[dict[str, object]]:
            return [dict(row, valid=True, quarantined=False, stale=False, reason=None)]

    assert core.audit_verdict(store=Store(), thread_id="t1",
                              message_id=mid) == (core.COMMITTED, None)


# ── [HIGH-1] 정상 응답에서도 relay valid:false 를 rc 0 으로 덮는 분기 ────────

def _ctx_for_publish(tmp: str) -> tools.Context:
    with open(os.path.join(tmp, "allowed_signers"), "w", encoding="utf-8") as fh:
        fh.write("alice ssh-ed25519 AAAA\n")
    return tools.Context(store=object(), ledger=_Ledger(),
                         allowed_signers_path=os.path.join(tmp, "allowed_signers"),
                         participant_id="alice", config={}, config_dir=None)


def test_b_relay_rejection_must_not_be_swallowed_by_local_acceptance(monkeypatch) -> None:
    """릴레이가 `budget_exceeded` 로 격리했는데 **우리 리듀서가 받았다**는 이유로 정상 종료했다.

    codex 재현: 로컬 예산이 릴레이보다 느슨하면 이 창이 상시로 열린다.
    기대: `valid:false` 는 **항상 비영 종료**(성공으로 접으려면 공개 결과에 강제 노출).
    """
    tmp = tempfile.mkdtemp(prefix="agora-t-b-")
    ctx = _ctx_for_publish(tmp)
    seen: dict[str, object] = {}

    def fake_publish_event(**kw: object) -> dict[str, object]:
        seen["message_id"] = kw["event"]["message_id"]           # type: ignore[index]
        return {"message_id": kw["event"]["message_id"],          # type: ignore[index]
                "relay_verdict": {"accepted_to_ledger": True, "reducer": "quarantined",
                                  "reason": "budget_exceeded", "state_hash": "S"}}

    monkeypatch.setattr(core, "publish_event", fake_publish_event)
    # 우리 리듀서는 그 글을 사슬에 넣었다 — 구판은 이것을 근거로 정상 종료했다.
    monkeypatch.setattr(tools, "_reduce", lambda c, t: {
        "state": "r0", "round": 0, "head": "H", "state_hash": "S",
        "events": [{"message_id": seen.get("message_id")}], "quarantined": [], "stale": []})

    try:
        out = tools._publish(ctx, kind="post", thread_id="t1",
                             payload={"round": 0, "body": "x"}, prev="H",
                             expected_state="S", category="debate")
    except AgoraError as e:
        # master 판정 2026-09-09 — 신규 번호 없음: 재시도 불가 사유는 3(GATE_REJECT).
        assert e.code == errors.GATE_REJECT, e.code
        assert (e.detail or {}).get("reason") == "budget_exceeded"
        # ★번호만 보는 스크립트는 「스키마가 막았다」와 「릴레이가 반영을 거부했다」를 못 가른다.
        #   그 한계를 **detail 이 닫는다** — 사유와 다툼을 함께 단언해야 그 닫힘이 증명된다.
        assert (e.detail or {}).get("accepted_by_us") is True
        return
    raise AssertionError(
        f"릴레이가 budget_exceeded 로 반영을 거부했는데 정상 반환했다: {json.dumps(out, default=str)}")


# ── [HIGH-2] --verify 가 릴레이 파생 필드를 버려 거짓 PASS ───────────────────

def test_c1_thread_status_must_preserve_derived_fields() -> None:
    """어댑터가 `state·round·state_hash·close_reason·chair` 를 버리면 대조할 것이 없다."""
    from agora.store_relay import RelayStore
    store = RelayStore("http://127.0.0.1:1/")
    payload = {"room_id": "t1", "closed": False, "answered": False, "closed_at": None,
               "state": "r3", "round": 3, "state_hash": "SERVER",
               "close_reason": None, "chair": "alice", "type": "debate",
               "requester": "alice", "events_counted": 7}
    store._run = lambda method, path, **kw: dict(payload)      # type: ignore[assignment]
    out = store.thread_status(thread_id="t1")
    for field in ("state", "round", "state_hash", "close_reason", "chair"):
        assert field in out, f"릴레이가 준 {field} 를 어댑터가 버렸다: {out}"
    assert out["state"] == "r3" and out["round"] == 3 and out["state_hash"] == "SERVER"


def test_c2_triple_check_must_flag_state_hash_and_list_failure() -> None:
    """상태 해시가 갈렸는데 `mismatch` 가 비면 rc 0 이 난다 — 목록 실패도 mismatch 다(fail-closed)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rehearsal", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "tools", "rehearsal.py"))
    rehearsal = importlib.util.module_from_spec(spec)          # type: ignore[arg-type]
    spec.loader.exec_module(rehearsal)                          # type: ignore[union-attr]

    class Store:
        def audit_events(self, *, thread_id: str, limit: int = 200) -> list[dict[str, object]]:
            return [{"node_id": "ev_0000000000000001", "valid": True, "reason": None}]

        def thread_status(self, *, thread_id: str) -> dict[str, object]:
            return {"closed": False, "answered": False, "closed_at": None,
                    "state": "r3", "round": 3, "state_hash": "SERVER"}

        def list_threads(self, **_: object) -> dict[str, object]:
            raise AgoraError(errors.STORE, "목록을 못 받았다", None)

    import agora.tools as _t
    saved = _t._reduce
    _t._reduce = lambda c, t: {"state": "r3", "round": 3, "state_hash": "CLIENT",
                               "solved_by": None, "close_reason": None, "head": "h",
                               "quarantined": [], "stale": []}
    try:
        out = rehearsal.triple_check(object(), Store(), "t1")
    finally:
        _t._reduce = saved
    joined = " / ".join(out["mismatch"])
    assert any("state_hash" in m for m in out["mismatch"]), \
        f"릴레이 SERVER vs 우리 CLIENT 인데 mismatch 가 그것을 안 적었다: {joined!r}"
    assert any("list_threads" in m or "목록" in m for m in out["mismatch"]), \
        f"파생 축을 못 읽었는데 mismatch 로 안 셌다: {joined!r}"


# ── [HIGH-3] 더블이 F-1 핵심 계약 expected_state 를 판정하지 않음 ───────────

def _fake_relay_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "fake_relay", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_relay.py"))
    mod = importlib.util.module_from_spec(spec)                 # type: ignore[arg-type]
    spec.loader.exec_module(mod)                                # type: ignore[union-attr]
    return mod


def _seed_room(relay) -> tuple[str, str]:
    """genesis 를 심고 (방 id, genesis 해시) 를 돌려준다."""
    gen = {"v": 1, "kind": "genesis", "thread_id": "t1", "message_id": new_id(),
           "prev": "", "expected_state": "", "from": "alice", "roster": "r0",
           "scrub": {"rules": "b0", "blocked": False, "redacted": []},
           "ts": "2026-09-09T00:00:00.000Z",
           "payload": {"type": "debate", "topic": "t", "chair": "alice"}}
    body = render_post(gen)
    relay.append_event(thread_id="t1", category="debate", title="t",
                       body=body, is_genesis=True)
    return "t1", event_hash(gen)


def test_d1_fake_relay_must_reject_wrong_expected_state() -> None:
    """`prev` 는 맞는데 `expected_state` 가 틀린 글 — 실물은 `stale_expected_state` 로 격리한다."""
    mod = _fake_relay_module()
    relay = mod.FakeRelay()
    room, head = _seed_room(relay)
    row = relay.append_event(thread_id=room, category="debate", title="",
                             body=_body(prev=head, expected_state="definitely-wrong"),
                             is_genesis=False)
    assert row["valid"] is False, f"틀린 expected_state 를 유효로 판정했다: {row}"
    assert row["reason"] == "stale_expected_state", row


def test_d2_fake_relay_contract_shapes() -> None:
    """더블의 서식이 계약과 갈리면 시험 상대가 실물보다 **느슨한 다른 것**이 된다."""
    mod = _fake_relay_module()
    relay = mod.FakeRelay()
    room, head = _seed_room(relay)
    first = relay.rooms[room]["events"][0]
    assert first["event_id"].startswith("ev_") and len(first["event_id"]) == 3 + 16, \
        f"event id 서식이 계약(ev_%016d)과 다르다: {first['event_id']}"
    row = relay.append_event(thread_id=room, category="debate", title="",
                             body=_body(prev="nope", expected_state="x"), is_genesis=False)
    assert row["valid"] is False
    # POST verdict 의 상태 해시 칸 이름은 계약상 `state_hash` 다(실물 index.ts).
    verdict = mod.verdict_of_row(row, relay.rooms[room])
    assert "state_hash" in verdict and "state_hash_at_that_point" not in verdict, verdict


def test_d3_fake_relay_declares_what_it_judges() -> None:
    """「무엇을 판정하고 무엇을 안 하는가」가 **표로** 있어야 한다 — 자기고지 한 줄로는 못 센다."""
    mod = _fake_relay_module()
    table = mod.CONTRACT_COVERAGE
    assert isinstance(table, tuple) and len(table) >= 8
    for row in table:
        assert set(row) == {"check", "where", "judged", "why"}, row
        assert isinstance(row["judged"], bool)
    assert any(r["judged"] for r in table) and any(not r["judged"] for r in table), \
        "전부 참이거나 전부 거짓인 표는 아무것도 안 가른다"
    assert any("expected_state" in r["check"] for r in table if r["judged"])


# ── [MEDIUM] roster 동기화 실패 뒤에도 하네스가 쓰기로 진행 ─────────────────

def test_e_rehearsal_stops_when_sync_roster_fails(monkeypatch) -> None:
    """sync 하나라도 실패하면 **POST 0건**으로 끝나야 한다 — 부분 명부로 방을 열면 F-1 이 재생산된다."""
    import importlib.util
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("rehearsal", os.path.join(root, "tools", "rehearsal.py"))
    rehearsal = importlib.util.module_from_spec(spec)            # type: ignore[arg-type]
    spec.loader.exec_module(rehearsal)                            # type: ignore[union-attr]

    from agora import onboard
    calls = {"n": 0}

    def boom(**kw: object) -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise AgoraError(errors.STORE, "명부 교체가 반쪽만 됐다",
                             {"reason": "partial_replacement"})
        return {"ok": True}

    monkeypatch.setattr(rehearsal.onboard, "sync_roster", boom)
    out = rehearsal.run(live=False, out_path=os.devnull)
    steps = [r["step"] for r in out["rows"]]
    assert not any(s.startswith("enter") or s.startswith("say") or s.startswith("advance")
                   for s in steps), f"sync 실패 뒤에도 쓰기로 진행했다: {steps}"


# ── [LOW] 전건 fetch/audit 에 종료 상한이 없음 ──────────────────────────────

class _Sentinel(Exception):
    """상한이 없으면 영원히 도는 자리 — 시험이 매달리지 않게 여기서 끊는다."""


def _endless_run(cap: int):
    state = {"n": 0}

    def run(method: str, path: str, **kw: object) -> dict[str, object]:
        state["n"] += 1
        if state["n"] > cap:
            raise _Sentinel(f"{state['n']} 번 불렀는데 상한이 안 걸렸다")
        return {"items": [{"event_id": f"ev_{state['n']:016d}", "body": "{}",
                           "created_at": "2026-09-09T00:00:00.000Z"}],
                "next_cursor": f"c{state['n']}"}
    return run


def test_f_fetch_and_audit_have_a_termination_cap() -> None:
    """매번 **새** 커서를 주는 상대에게는 「같은 커서 반복」 검사가 안 걸린다 — 상한이 있어야 끝난다."""
    from agora.store_relay import RelayStore
    for name in ("fetch", "audit_events"):
        store = RelayStore("http://127.0.0.1:1/")
        store._run = _endless_run(2000)                          # type: ignore[assignment]
        try:
            getattr(store, name)(thread_id="t1")
        except _Sentinel as e:
            raise AssertionError(f"{name}: {e}") from None
        except AgoraError as e:
            assert e.code in (errors.STORE, errors.STATE_CONFLICT), (name, e.code)
        else:
            raise AssertionError(f"{name}: 끝없이 페이지를 받는데 조용히 성공했다")


# ── pytest 부재 폴백 러너 ───────────────────────────────────────────────────

class _Monkeypatch:
    """`monkeypatch` 최소 대역 — setattr 과 undo 두 가지만."""

    def __init__(self) -> None:
        self._undo: list[tuple[object, str, object]] = []

    def setattr(self, target: object, name: str, value: object) -> None:
        self._undo.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self) -> None:
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)
        self._undo.clear()


def _main() -> int:
    import inspect
    cases = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    bad = 0
    for name, fn in cases:
        mp = _Monkeypatch()
        try:
            if "monkeypatch" in inspect.signature(fn).parameters:
                fn(mp)
            else:
                fn()
            print(f"  PASS  {name}")
        except Exception as e:                    # noqa: BLE001 — 표를 내는 것이 목적이다
            bad += 1
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        finally:
            mp.undo()
    print(f"\n{len(cases) - bad}/{len(cases)} PASS · 실패 {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
