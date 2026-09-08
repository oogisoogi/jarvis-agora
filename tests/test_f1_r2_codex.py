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
from agora.event import parse_post as reducer_parse         # noqa: E402


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


def _reduce_bodies(bodies: list[str], *, operators: frozenset[str] = frozenset(),
                   now: str | None = None) -> dict[str, object]:
    """**우리 리듀서를 오라클로 세운다** — 같은 본문 묶음을 `order()+apply()` 에 먹인다.

    ★★왜 이것이 필요한가(codex 4R HIGH · 이 파일이 실제로 낸 사고): D4 ⑷ 는 `debate` 방에
      `answer_selected` 를 넣고 「더블이 solved 를 낸다」를 정답으로 적어 뒀다. 실물·우리
      리듀서는 그 kind 를 problem 전용으로 보고 `kind_not_allowed` 로 격리한다 —
      ⇒ 시험이 **잘못된 동작을 정답으로 고정**했고, 옳은 게이트를 넣는 쪽이 붉어졌다.
      **공허한 시험보다 나쁘다.** 원인은 하나다: 기대값을 **내 머리에서** 적고 리듀서에
      물어보지 않았다. 그래서 이제 D 계열은 기대값을 **리듀서에서 받아 온다.**
    ⛔`collect()` 는 지나간다(서명·명부 검증은 이 축의 관심이 아니고, 시험이 그 준비에
      매달리면 정작 전이 축을 못 잰다). 판정 경로는 `order()+apply()` 로 실물과 같다.
    ⚠예산은 넉넉히 준다 — 예산은 더블이 판정 안 한다고 표에 적힌 축이라 대조를 흐린다.
    """
    from agora.contract_open import GENESIS_PREV
    valid = []
    for i, body in enumerate(bodies):
        parsed = reducer_parse(body)
        ev = parsed["event"]
        valid.append({"node_id": f"ev_{i:016d}",
                      "created_at": f"2026-09-09T00:00:{i:02d}.000Z",
                      "event": ev, "canonical": parsed.get("canonical", body),
                      "hash": event_hash(ev), "kind": ev["kind"], "from": ev["from"],
                      "message_id": ev["message_id"], "prev": ev["prev"] or GENESIS_PREV,
                      "fingerprint": None, "roster_stale": False, "scrub_recheck": False})
    ordered = reducer.order({"thread_id": "t1", "valid": valid,
                             "quarantined": [], "stale": []})
    return reducer.apply(ordered, operators=operators, now=now,
                         budget={"posts_per_round": 99, "max_chars_per_round": 99999})


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

    audited = core.audit_verdict(store=Store(), thread_id="t1", message_id=mid)
    assert audited["verdict"] != core.COMMITTED, (
        f"원장에 있다는 이유만으로 {audited['verdict']!r} 로 판정했다 — 릴레이는 valid:false 라고 했다")
    assert audited["verdict"] == core.REJECTED and audited["reason"] == "lost_race"
    # ★근거줄은 **릴레이가 말한 분류**여야 한다(master 승인 2026-09-09).
    assert audited["reducer"] == "stale", audited

    settled = core.settle_unknown(store=Store(), ledger=(led := _Ledger()),
                                  event={"thread_id": "t1", "message_id": mid},
                                  event_hash="h")
    assert settled["verdict"] == core.REJECTED
    assert settled.get("reason") == "lost_race"
    assert settled.get("reducer") == "stale"
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

    assert core.audit_verdict(store=Store(), thread_id="t1", message_id=mid) == {
        "verdict": core.COMMITTED, "reason": None, "reducer": "accepted"}


def test_a3_missing_relay_verdict_is_not_success() -> None:
    """**판정이 없으면 성공이 아니다**(codex 3R CRITICAL).

    첫 판은 `valid is False` 만 거부로 보고 나머지를 committed 로 접었다 — `valid` 칸이
    빠졌거나 null 인 응답이 조용히 성공이 됐다. 「반영됐다」와 「상대가 말하지 않았다」는 다르다.
    """
    mid = new_id()
    row = {"node_id": "ev_0000000000000007", "body": f'{{"message_id":"{mid}"}}',
           "created_at": "2026-09-09T00:00:00.000Z", "is_genesis": False}
    for label, extra in (("칸 부재", {}), ("null", {"valid": None})):
        class Store:
            def fetch(self, *, thread_id: str, **_: object) -> dict[str, object]:
                return {"items": [dict(row)], "next_cursor": None}

            def audit_events(self, *, thread_id: str,
                             limit: int = 200) -> list[dict[str, object]]:
                return [dict(row, **extra)]

        try:
            out = core.audit_verdict(store=Store(), thread_id="t1", message_id=mid)
        except AgoraError as e:
            assert (e.detail or {}).get("reason") == "relay_verdict_missing", (label, e.detail)
            continue
        raise AssertionError(f"{label}: 판정이 없는데 {out!r} 로 접었다")


def test_a4_evidence_line_carries_the_relay_classification() -> None:
    """근거줄은 **릴레이가 말한 분류**여야 한다(master 승인 2026-09-09).

    ★판정(재시도 여부)은 `reason` 이 진다 — 그래서 분류를 "stale" 로 못박아도 **결과는 옳다.**
      그러나 사람이 읽는 근거가 사실과 달라지고, 틀린 근거 위의 감사는 감사가 아니다.
    """
    mid = new_id()
    row = {"node_id": "ev_0000000000000007", "body": f'{{"message_id":"{mid}"}}',
           "created_at": "2026-09-09T00:00:00.000Z", "is_genesis": False}

    class Quarantined:
        def audit_events(self, *, thread_id: str,
                         limit: int = 200) -> list[dict[str, object]]:
            return [dict(row, valid=False, quarantined=True, stale=False,
                         reason="budget_exceeded")]

    audited = core.audit_verdict(store=Quarantined(), thread_id="t1", message_id=mid)
    assert audited["reducer"] == "quarantined", audited
    assert audited["reason"] == "budget_exceeded", audited

    class Neither:
        def audit_events(self, *, thread_id: str,
                         limit: int = 200) -> list[dict[str, object]]:
            return [dict(row, valid=False, quarantined=False, stale=False, reason=None)]

    # 둘 다 아니면 **지어내지 않는다** — 실물도 그 자리에 unknown 을 쓴다.
    assert core.audit_verdict(store=Neither(), thread_id="t1",
                              message_id=mid)["reducer"] == "unknown"


def test_a5_unmeasurable_chain_is_not_a_rejection() -> None:
    """「우리도 거부했다」와 「읽지 못해 모른다」를 한 값으로 뭉치지 않는다(codex 3R LOW)."""
    tmp = tempfile.mkdtemp(prefix="agora-t-a5-")
    ctx = _ctx_for_publish(tmp)
    saved = tools._reduce
    try:
        tools._reduce = lambda c, t: (_ for _ in ()).throw(
            AgoraError(errors.STORE, "못 읽는다", None))
        assert tools._accepted_by_us(ctx, "t1", "m") is None
        tools._reduce = lambda c, t: {"events": []}
        assert tools._accepted_by_us(ctx, "t1", "m") is False
        tools._reduce = lambda c, t: {"events": [{"message_id": "m"}]}
        assert tools._accepted_by_us(ctx, "t1", "m") is True
    finally:
        tools._reduce = saved


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


def _now_iso() -> str:
    """리듀서에 넣을 **지금** — 실물은 시각을 주입받는다(프로세스 시계를 몰래 읽지 않는다)."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _double_kit(mod: object) -> tuple:
    """더블 방을 세우고 글을 얹는 두 도우미 — **D 계열과 4R 시험이 함께 쓴다.**

    ★D4 안에만 두면 새 시험이 같은 것을 다시 적게 되고, 그때 **유형·마감 같은 인자가 한쪽에만**
      생겨 두 벌이 조용히 갈린다(이 파일이 이미 그 사고를 냈다 — D4 ⑷ 가 debate 방을 썼다).
    """
    def room(gtype: str = "debate", ops: str = "",
             deadlines: dict | None = None) -> tuple:
        relay = mod.FakeRelay()                          # type: ignore[attr-defined]
        relay.roster_text["operators"] = ops
        payload: dict = {"type": gtype, "topic": "t"}
        if gtype == "debate":
            payload["chair"] = "alice"
        if deadlines is not None:
            payload["deadlines"] = deadlines
        gen = {"v": 1, "kind": "genesis", "thread_id": "t1", "message_id": new_id(),
               "prev": "", "expected_state": "", "from": "alice", "roster": "r0",
               "scrub": {"rules": "b0", "blocked": False, "redacted": []},
               "ts": "2026-09-09T00:00:00.000Z", "payload": payload}
        relay.append_event(thread_id="t1", category=gtype, title="t",
                           body=render_post(gen), is_genesis=True)
        return relay, gen, event_hash(gen)

    def put(relay: object, kind: str, prev: str, expected: str, payload: dict,
            frm: str = "alice", gtype: str = "debate") -> dict:
        return relay.append_event(                       # type: ignore[attr-defined]
            thread_id="t1", category=gtype, title="", body=_body(
                kind=kind, prev=prev, expected_state=expected, payload=payload,
                **{"from": frm}), is_genesis=False)

    return room, put


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


# 더블이 판정한다고 **선언한** 축의 정확한 목록. ★`len(table) >= 8` 로 재면 표의 **절반을
# 지워도 통과한다**(codex 3R MEDIUM 재현). 개수가 아니라 **무엇이 있는가**를 못박는다.
# ⚠줄이려면 이 목록을 함께 줄여야 하고, 그때 「무엇을 포기했는지」가 diff 에 남는다.
_JUDGED_AXES = (
    "본문 크기 상한", "봉투 뼈대 11칸", "요청 인자 == 서명된 값", "서명이 이 참가자의 것인가",
    "message_id 재사용", "사슬 경합", "expected_state == stateHash(state)",
    "vote 는 머리를 안 옮긴다", "전이 권한", "사슬 자리 소유",
    "만료 판정", "등록 소유 증명 서명", "체크포인트",
    # ★codex 4R HIGH — 「무엇을 판정하는가」에 유형 경계가 없어서, 시험이 잘못된 동작을 고정했다.
    "유형별 허용 kind", "after_close",
    # ★codex 5R HIGH — 수용 여부만 맞고 **상태**가 갈린 두 축.
    "만료 전이", "knowhow 종결 사유 제한",
)
_UNJUDGED_AXES = (
    "kind 9종 payload 닫힌 스키마", "스크럽 백스톱", "만료 중 운영자 대리 의장 위임",
    "예산",
    # ★codex 6R HIGH — 「예산은 안 잰다」와 「대상 후보는 잰다」는 함께 참일 수 없다.
    #   뒤엣것을 **판정에서 뺐다**(표만 고치는 것은 교정이 아니라 변명이다).
    "answer_selected 대상 검증",
)


def test_d3_fake_relay_declares_what_it_judges() -> None:
    """「무엇을 판정하고 무엇을 안 하는가」가 **표로** 있어야 한다 — 자기고지 한 줄로는 못 센다.

    ★★그리고 표는 **정확히** 단언해야 한다(codex 3R MEDIUM): 개수만 재면 절반을 지워도 통과하고,
      그러면 「무엇을 판정하는가」라는 표의 존재 이유가 사라진다. 축이 사라지면 여기가 붉어진다.
    """
    mod = _fake_relay_module()
    table = mod.CONTRACT_COVERAGE
    assert isinstance(table, tuple)
    for row in table:
        assert set(row) == {"check", "where", "judged", "why"}, row
        assert isinstance(row["judged"], bool)
        assert row["why"].strip(), f"사유 없는 행은 경계 선언이 아니다: {row}"
        assert (row["where"] != "—") == row["judged"], \
            f"판정한다면서 자리가 없거나, 안 하면서 자리가 적혀 있다: {row}"
    judged = [r["check"] for r in table if r["judged"]]
    unjudged = [r["check"] for r in table if not r["judged"]]
    for want in _JUDGED_AXES:
        assert any(want in c for c in judged), f"판정한다고 선언된 축이 사라졌다: {want}"
    for want in _UNJUDGED_AXES:
        assert any(want in c for c in unjudged), f"경계 선언이 사라졌다: {want}"
    assert len(judged) == len(_JUDGED_AXES), (len(judged), judged)
    assert len(unjudged) == len(_UNJUDGED_AXES), (len(unjudged), unjudged)


def test_d4_double_matches_reducer_on_the_transitions_it_claims() -> None:
    """더블이 「판정한다」고 적은 전이 축에서 **실물·우리 리듀서와 같은 답**을 내는가.

    ★codex 3R 이 네 입력에서 갈라짐을 보였다. 그 네 입력을 그대로 시험으로 세운다 —
      「25단계 완주」는 **한 경로의 등가성**만 보이지 전이기 전체를 보이지 않는다.
    """
    mod = _fake_relay_module()

    room, put = _double_kit(mod)

    # ⑴ vote 는 머리를 안 옮기지만 **그 자리는 찼다** — 뒤에 온 같은 prev 는 진다.
    relay, gen, head = room()
    sh = mod._state_hash(relay.rooms["t1"]["state"])
    put(relay, "vote", head, sh, {"choice": "a"})
    row = put(relay, "post", head, sh, {"round": 0, "body": "x"})
    assert (row["valid"], row["reason"]) == (False, "lost_race"), row

    # ⑵ 권한에서 걸린 전이는 **격리**다(상태만 안 바뀌는 것이 아니다).
    relay, gen, head = room()
    sh = mod._state_hash(relay.rooms["t1"]["state"])
    row = put(relay, "advance", head, sh, {"from_round": 0, "to_round": 1}, frm="mallory")
    assert (row["valid"], row["quarantined"], row["reason"]) == (False, True, "permission"), row

    # ⑶ 운영자도 방을 닫는다.
    relay, gen, head = room(ops="op1\n")
    sh = mod._state_hash(relay.rooms["t1"]["state"])
    put(relay, "close", head, sh, {"reason": "solved"}, frm="op1")
    assert relay.rooms["t1"]["state"]["state"] == "closed", relay.rooms["t1"]["state"]

    # ⑷ genesis 는 답 후보다(우리 리듀서가 post_ids 를 그렇게 시드한다).
    # ★★**방을 problem 으로 고쳤다**(codex 4R HIGH · 2026-09-09). 구판은 이 검사를 `debate`
    #   방에서 했는데 `answer_selected` 는 **problem 전용**이다(계약 §6) — 실물·우리 리듀서는
    #   `kind_not_allowed` 로 격리하고, 그 시절 더블은 유형을 안 봐서 `solved` 를 냈다.
    #   ⇒ 이 시험은 **더블만 내는 답을 정답으로 고정**하고 있었다. 기대값을 이제 리듀서에서 받는다.
    # ⚠**대상 검증 자체는 이제 판정 축이 아니다**(codex 6R HIGH · `test_j1`): 후보 집합이 예산
    #   판정에 의존해서다. 여기서 재는 것은 「허용된 유형·권한에서 답 선택이 두 구현에서 같은
    #   상태를 낸다」이고, genesis 는 실물에서 **언제나** 후보이므로 이 입력은 그 경계 밖이다.
    relay, gen, head = room(gtype="problem")
    sh = mod._state_hash(relay.rooms["t1"]["state"])
    ab = put(relay, "answer_selected", head, sh, {"post_message_id": gen["message_id"]},
             gtype="problem")["body"]
    assert relay.rooms["t1"]["state"]["state"] == "solved", relay.rooms["t1"]["state"]
    oracle = _reduce_bodies([render_post(gen), ab])
    assert (oracle["state"], oracle["quarantined"]) == ("solved", []), oracle

    # ⑸ 만료는 **양쪽으로** 잰다 — 아래 test_m4 가 마감 전/후를 같이 댄다.
    #    여기서는 「마감이 없으면 만료 해시가 안 통한다」만 본다(넓게 뚫린 문).
    relay, gen, head = room()
    st = relay.rooms["t1"]["state"]
    row = put(relay, "post", head, mod._state_hash({**st, "state": "expired"}),
              {"round": 0, "body": "x"})
    assert (row["valid"], row["reason"]) == (False, "stale_expected_state"), row


# ── codex 4R(2026-09-09 · REVISE) 재현 프로브 승격 ──────────────────────────
# ★★4R 의 세 HIGH 는 **전부 「봉합이 절반이었다」**의 판본이다: ⑴머리를 하나만 옮겼다
#   ⑵유형 경계를 안 옮겼다 ⑶ 두 문 중 한 문만 fail-closed 로 만들었다.
#   ⇒ 같은 규칙을 두 자리에 적어야 할 때, **한 자리만 적으면 시험은 초록이고 실물은 갈린다.**


def test_h1_double_advances_state_head_after_cas_quarantine() -> None:
    """CAS 격리 뒤 **다음 정상 글이 통해야** 한다(codex 4R HIGH · fake_relay.py 격리 분기).

    ★★구판은 운반 `head` 만 옮기고 `state["head"]` 를 genesis 에 뒀다. 상태 해시 8칸에는
      **머리가 들어 있으므로**, 다음 사람이 실물 기준으로 옳게 계산한 `expected_state` 가
      영원히 어긋나 **정상 글이 연쇄 거부**된다 — 한 사람의 이벤트 하나로 방이 동결된다
      (L-1 교착과 같은 병이고, 실물 `reject()` 는 두 머리를 함께 옮겨 그것을 막는다).
    ★D1·D4 는 **첫 거부만** 봤기 때문에 이 결함을 못 잡았다. 그래서 이 시험은 **거부 다음 글**을 본다.
    """
    mod = _fake_relay_module()
    room, put = _double_kit(mod)
    relay, gen, head = room()
    gb = render_post(gen)

    bad = put(relay, "post", head, "definitely-wrong", {"round": 0, "body": "x"})
    assert (bad["valid"], bad["reason"]) == (False, "stale_expected_state"), bad
    # ★두 머리가 함께 갔는가 — 이것이 다음 글의 `expected_state` 를 결정한다.
    state = relay.rooms["t1"]["state"]
    assert relay.rooms["t1"]["head"] == state["head"] == bad["hash"], \
        f"격리 뒤 머리가 갈렸다(운반 {relay.rooms['t1']['head'][:8]} vs 상태 {state['head'][:8]})"

    # ★기대값은 **우리 리듀서에서 받아 온다** — 격리된 글까지 먹인 뒤의 상태 해시다.
    oracle = _reduce_bodies([gb, bad["body"]])
    assert oracle["state_hash"] == mod._state_hash(state), \
        f"격리 뒤 상태 해시가 두 구현에서 갈렸다: {oracle['state_hash'][:8]} vs {mod._state_hash(state)[:8]}"
    good = put(relay, "post", bad["hash"], oracle["state_hash"], {"round": 0, "body": "y"})
    assert (good["valid"], good["reason"]) == (True, None), \
        f"격리 뒤 정상 글이 연쇄 거부됐다(방이 동결된다): {good}"
    after = _reduce_bodies([gb, bad["body"], good["body"]])
    assert len(after["events"]) == 2 and len(after["quarantined"]) == 1, after


def test_h2_double_enforces_per_type_allowed_kinds() -> None:
    """유형이 안 받는 kind 는 **격리**다 — `debate` 방의 `answer_selected`(codex 4R HIGH).

    ★★이 자리의 구판 시험(D4 ⑷)은 **공허한 것을 넘어 잘못된 동작을 정답으로 고정**했다:
      더블이 유형을 안 봐서 `solved` 를 냈고, 시험은 그것을 기대값으로 적었다 —
      옳은 게이트를 넣은 쪽이 붉어졌다(codex 가 실제로 그 프로브에서 D4 실패를 봤다).
    ★그래서 이 시험은 **두 구현에 같은 입력을 넣고 답을 견준다.** 기대값을 손으로 적지 않는다.
    """
    mod = _fake_relay_module()
    room, put = _double_kit(mod)
    # ★★**표를 통째로 견준다**(codex 6R MEDIUM): 구판은 `answer_selected` 의 `debate`/`problem` 만
    #   재서 **`knowhow` 행을 망가뜨린 변이가 살아남았다**(codex 실측 `TYPE_NET_MUTANT SURVIVED`).
    #   한 유형만 재는 시험은 「표가 맞다」를 증명하지 않는다 — 표는 세 줄이고 셋 다 계약이다.
    assert mod._ALLOWED_KINDS == dict(reducer.ALLOWED_KINDS), \
        f"더블의 유형 표가 계약과 갈렸다: {mod._ALLOWED_KINDS} vs {dict(reducer.ALLOWED_KINDS)}"
    # 유형별로 **그 유형이 안 받는 kind** 를 하나씩 태운다(행마다 그물이 있어야 한다).
    for gtype, kind, want in (("debate", "answer_selected", "kind_not_allowed"),
                              ("knowhow", "answer_selected", "kind_not_allowed"),
                              ("knowhow", "advance", "kind_not_allowed"),
                              ("problem", "advance", "kind_not_allowed"),
                              ("problem", "answer_selected", None)):
        relay, gen, head = room(gtype=gtype)
        sh = mod._state_hash(relay.rooms["t1"]["state"])
        payload = ({"post_message_id": gen["message_id"]} if kind == "answer_selected"
                   else {"from_round": 0, "to_round": 1})
        row = put(relay, "answer_selected" if kind == "answer_selected" else kind,
                  head, sh, payload, gtype=gtype)
        oracle = _reduce_bodies([render_post(gen), row["body"]])
        reasons = [q["reason"] for q in oracle["quarantined"]]
        assert reasons == ([want] if want else []), (gtype, kind, reasons)
        assert row["reason"] == want, f"{gtype}/{kind}: 더블 {row['reason']} · 리듀서 {want}"
        if want:
            assert (row["valid"], row["quarantined"]) == (False, True), row
            # ★거부돼도 자리는 지나갔다 — 두 머리 모두.
            assert relay.rooms["t1"]["head"] == relay.rooms["t1"]["state"]["head"], row
        else:
            assert row["valid"] is True, row

    # ★닫힌 방은 그 앞 문이다(같은 계약 단락) — 하나만 옮기면 그 자리에서 갈린다.
    relay, gen, head = room(ops="op1\n")
    sh = mod._state_hash(relay.rooms["t1"]["state"])
    closed = put(relay, "close", head, sh, {"reason": "solved"}, frm="op1")
    assert closed["valid"] is True, closed
    late = put(relay, "post", closed["hash"],
               mod._state_hash(relay.rooms["t1"]["state"]), {"round": 0, "body": "x"})
    assert (late["valid"], late["reason"]) == (False, "after_close"), late
    oracle = _reduce_bodies([render_post(gen), closed["body"], late["body"]],
                            operators=frozenset({"op1"}))
    assert [q["reason"] for q in oracle["quarantined"]] == ["after_close"], oracle

    # ★★**두 문이 동시에 참인 입력**을 못박는다(codex 5R MEDIUM). 위까지는 「열린 방의 금지 kind」와
    #   「닫힌 방의 허용 kind」만 재서, `_gate_denial` 의 **순서를 뒤집어도 통과**했다 —
    #   순서 자체가 계약인데(실물은 after_close 를 먼저 본다) 그 축이 비어 있었다.
    #   ⇒ 닫힌 `debate` 방의 `answer_selected`(유형 밖 kind)는 반드시 `after_close` 여야 한다.
    both = put(relay, "answer_selected", late["hash"],
               mod._state_hash(relay.rooms["t1"]["state"]),
               {"post_message_id": gen["message_id"]})
    assert (both["valid"], both["reason"]) == (False, "after_close"), \
        f"닫힘·유형 밖이 동시에 참인데 {both['reason']} 를 냈다(계약 순서는 after_close 가 먼저)"
    oracle = _reduce_bodies([render_post(gen), closed["body"], late["body"], both["body"]],
                            operators=frozenset({"op1"}))
    assert [q["reason"] for q in oracle["quarantined"]] == ["after_close", "after_close"], oracle


def test_h3_audit_events_fail_closed_on_repeated_cursor() -> None:
    """반복 cursor 는 `fetch` 와 **같은 문으로** 죽는다 — code 7(codex 4R HIGH).

    ★★구판은 `audit_events` 만 조용히 `break` 해 **부분 결과**를 냈다. 그 값을 받는 자리가
      3자 대조와 응답 유실 재조회인데, 둘 다 **없는 행을 「없음」으로 읽는다** —
      뒤 페이지의 `valid:false` 가 사라지고 대조는 `invalid:0 · mismatch:[]` 로 초록이 된다.
      ⇒ 같은 위험을 두 문 중 한 문에만 막으면, 막지 않은 문이 곧 그 축의 구멍이다.
    """
    from agora.store_relay import RelayStore
    pages = [
        {"items": [{"event_id": "ev_0000000000000001", "body": "a", "valid": True}],
         "next_cursor": "c1"},
        {"items": [{"event_id": "ev_0000000000000002", "body": "b", "valid": True}],
         "next_cursor": "c1"},                      # ★같은 커서 — 서버가 제자리를 돈다
        {"items": [{"event_id": "ev_0000000000000003", "body": "c", "valid": False,
                    "reason": "lost_race"}], "next_cursor": None},
    ]

    def store() -> object:
        st = RelayStore.__new__(RelayStore)
        seen = {"n": 0}

        def run(method: str, path: str, **kw: object) -> dict:
            page = pages[min(seen["n"], len(pages) - 1)]
            seen["n"] += 1
            return page

        st._run = run                                # type: ignore[attr-defined]
        return st

    for name in ("audit_events", "fetch"):
        try:
            getattr(store(), name)(thread_id="t1")
        except AgoraError as e:
            assert e.code == errors.STORE, (name, e.code)
        else:
            raise AssertionError(f"{name}: 반복 커서를 부분 결과로 삼켰다(모른다고 말해야 한다)")


def test_m4_expiry_is_measured_in_both_directions() -> None:
    """만료 판정은 **양쪽으로** 잰다 — 마감 전은 거부 · 마감 후는 수용(codex 4R MEDIUM).

    ★★구판은 「마감 없음 → 만료 해시 거부」라는 **음성 입력만** 재서, `_expired_now` 를
      `return False` 로 무력화한 뮤턴트가 살아남았다. ★음성만 재는 검사는 「그 판정이 있다」를
      증명하지 않는다 — 판정을 통째로 지워도 음성은 그대로 음성이다.
    ★경계는 **유예(300초) 양쪽**에서 잰다: 유예 안이면 아직 만료가 아니고, 유예를 넘으면 만료다.
      한쪽만 재면 유예를 지운 뮤턴트가 산다.
    """
    import datetime
    mod = _fake_relay_module()
    room, put = _double_kit(mod)

    def at(offset: int) -> str:
        t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=offset)
        return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    for offset, expired in ((-3600, True), (-60, False), (3600, False)):
        relay, gen, head = room(deadlines={"r0": at(offset)})
        st = relay.rooms["t1"]["state"]
        assert mod._expired_now(st["_deadlines"], st) is expired, (offset, expired)
        # 만료 상태의 해시를 들고 온 글 — 실제로 만료일 때만 통해야 한다.
        row = put(relay, "post", head, mod._state_hash({**st, "state": "expired"}),
                  {"round": 0, "body": "x"})
        assert row["valid"] is expired, (offset, expired, row)
        if not expired:
            assert row["reason"] == "stale_expected_state", row
        # ★★**수용 여부만 재면 상태는 안 잰다**(codex 5R HIGH): 마감이 지난 방을 더블은
        #   `r0` 에 남겨 뒀는데 리듀서는 `expired` 로 갔고, `valid` 만 보던 이 시험은 통과했다.
        #   ⇒ 보고 상태와 **상태 해시**를 리듀서와 견준다. 그것이 3자 대조가 실제로 대는 값이다.
        seen = relay.derived("t1")
        # ⚠거부된 글도 **오라클에 먹인다**: 실물은 거부해도 사슬은 지나갔다고 보고
        #   `state["head"]` 를 옮긴다(reject()) — 안 먹이면 머리가 갈려 대조가 엉뚱하게 붉어진다.
        oracle = _reduce_bodies([render_post(gen), row["body"]], now=_now_iso())
        assert seen["state"] == oracle["state"] == ("expired" if expired else "r0"), \
            (offset, seen["state"], oracle["state"])
        assert seen["state_hash"] == oracle["state_hash"], \
            (offset, seen["state_hash"][:8], oracle["state_hash"][:8])
        # ★대조군 — 만료든 아니든 **지금 상태의 해시**는 언제나 통한다(과잉 차단 방지).
        relay2, gen2, head2 = room(deadlines={"r0": at(offset)})
        st2 = relay2.rooms["t1"]["state"]
        ok = put(relay2, "post", head2, mod._state_hash(st2), {"round": 0, "body": "x"})
        assert ok["valid"] is True, (offset, ok)


# ── codex 5R(2026-09-09 · REVISE) 재현 프로브 승격 ──────────────────────────
# ★★5R 의 두 HIGH 는 **「수용은 맞고 상태가 갈렸다」**의 판본이다: 더블이 글을 받아들이는지는
#   맞췄는데 **그 뒤의 상태**가 실물과 달랐다. ⇒ 수용 여부만 재는 시험은 상태 축을 안 잰다.


def test_i1_double_keeps_knowhow_close_reasons() -> None:
    """`knowhow` 는 종결 사유가 **둘뿐**이다(계약 §6 · codex 5R HIGH).

    ★구판 더블은 아무 사유나 받아 방을 닫았고 리듀서는 `bad_transition` 으로 격리했다 —
      `solved` 하나로 갈렸다. ★유형별 제약을 한 곳만 옮기면 나머지가 그대로 구멍이고,
      그 구멍은 더블이 **받아 주는** 쪽이라 로컬은 언제나 초록이다.
    """
    mod = _fake_relay_module()
    room, put = _double_kit(mod)
    for reason in ("solved", *sorted(reducer.KNOWHOW_CLOSE_REASONS)):
        allowed = reason in reducer.KNOWHOW_CLOSE_REASONS
        relay, gen, head = room(gtype="knowhow")
        row = put(relay, "close", head, mod._state_hash(relay.rooms["t1"]["state"]),
                  {"reason": reason}, gtype="knowhow")
        oracle = _reduce_bodies([render_post(gen), row["body"]])
        assert row["valid"] is allowed, (reason, row)
        assert (oracle["state"] == "closed") is allowed, (reason, oracle["state"])
        assert [q["reason"] for q in oracle["quarantined"]] == \
            ([] if allowed else ["bad_transition"]), (reason, oracle["quarantined"])
        assert row["reason"] == (None if allowed else "bad_transition"), (reason, row)


def test_i2_transport_head_and_state_head_are_different_things() -> None:
    """`vote` 는 상태 머리를 안 옮기지만 **사슬은 잇는다**(codex 5R MEDIUM).

    ★★실물 `order()` 는 `by_prev` 로 엮으므로 vote 의 해시를 `prev` 로 삼은 글이 사슬에 이어지고,
      `apply()` 는 vote 에서 `continue` 해 `state["head"]` 를 안 옮긴다(계약 §5 규칙 5).
      구판 더블은 이 둘을 **한 칸**으로 써서 vote 뒤의 정상 후속 글을 `lost_race` 로 밀어냈다.
    ★한 칸으로 쓰면 둘 중 하나는 반드시 틀린다 — 3R 은 「자리 소유」쪽을 고쳤고(`claimed_prevs`),
      이 쪽이 남아 있었다. **대조군**으로 그 3R 봉합이 살아 있는지도 함께 잰다.
    """
    mod = _fake_relay_module()
    room, put = _double_kit(mod)
    relay, gen, head = room()
    before = mod._state_hash(relay.rooms["t1"]["state"])
    vote = put(relay, "vote", head, before, {"choice": "a"})
    assert vote["valid"] is True, vote
    assert relay.rooms["t1"]["state"]["head"] == head, "vote 가 상태의 머리를 옮겼다"
    assert relay.rooms["t1"]["head"] == vote["hash"], "vote 가 사슬의 머리를 안 옮겼다"
    after = put(relay, "post", vote["hash"], before, {"round": 0, "body": "x"})
    assert (after["valid"], after["reason"]) == (True, None), \
        f"vote 뒤 정상 후속 글을 밀어냈다: {after}"
    oracle = _reduce_bodies([render_post(gen), vote["body"], after["body"]])
    assert len(oracle["events"]) == 3 and not oracle["stale"] and not oracle["quarantined"], \
        oracle
    # 대조군 — 이미 찬 자리(genesis)를 다시 claim 하면 여전히 진다(3R 봉합).
    relay2, _g2, head2 = room()
    sh2 = mod._state_hash(relay2.rooms["t1"]["state"])
    put(relay2, "vote", head2, sh2, {"choice": "a"})
    dup = put(relay2, "post", head2, sh2, {"round": 0, "body": "x"})
    assert (dup["valid"], dup["reason"]) == (False, "lost_race"), dup


def test_i3_whitespace_gate_treats_unmeasured_as_failure() -> None:
    """공백 검사는 **측정 실패를 통과로 세지 않는다**(codex 5R LOW).

    ★구판은 `git diff --check` 의 종료 코드를 버리고 stdout 유무만 봤다 — 없는 ref(rc 128)는
      **출력이 비어 clean 으로 읽힌다.** 검사기가 고장난 것과 깨끗한 것은 다른 사건이다.
    ★그리고 그 논리를 게이트 안 인라인 함수로 두면 **따로 잴 수 없다** — 그래서
      `tests/ws_hygiene.sh` 로 뺐고, 이 시험이 없는 ref 를 넣어 그 주장을 실측한다.
    """
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tests", "ws_hygiene.sh")
    assert os.access(script, os.X_OK), "검사 스크립트가 실행 가능해야 한다"
    bad = subprocess.run(["bash", script, "definitely-missing-ref"],
                         cwd=root, capture_output=True, text=True)
    assert bad.returncode != 0, f"없는 ref 를 통과시켰다: {bad.stdout!r}"
    assert "미측정" in bad.stdout, f"측정 실패를 위반과 구별해 말하지 않았다: {bad.stdout!r}"
    ok = subprocess.run(["bash", script], cwd=root, capture_output=True, text=True)
    assert ok.returncode == 0, f"깨끗한 트리를 위반으로 봤다: {ok.stdout!r}"


# ── codex 6R(2026-09-09 · REVISE) — master 판정 = 「판정 안 함 + 표 사유 교정」 ─────
# ★★6R 의 두 HIGH 는 **선언의 병**이다: 표에 `judged:False` 로 적어 둔 것이 면제처럼 쓰였다.
#   ⑴「예산은 안 잰다」와 「답 후보는 잰다」는 **함께 참일 수 없다**(후보 집합이 예산 판정의
#     결과다) — 뒤엣것을 판정에서 뺐다. ⑵「만료 중 운영자 위임은 안 잰다」고 적어 놓고
#     코드는 `permission` 을 **냈다** — 안 재는 것이 아니라 **좁게 틀린 것**이고 그것은 거짓 적색이다.
# ★그래서 이 두 시험은 **「더블이 여기서 verdict 를 내지 않는다」**를 단언한다. 무엇을 잰다가
#   아니라 **무엇을 재지 않는다**를 재는 시험이다 — 선언이 코드로 성립하는지 보는 유일한 방법이다.
# ⛔이식(계약 규칙을 더블에 손으로 더 옮기는 것)은 master 가 금했다: 남은 것은 손으로 옮긴
#   더블의 꼬리라 라운드로는 수렴하지 않고, 구조 처방(계약 전수 대조표)은 별도 티켓이다.


def test_j1_double_issues_no_verdict_on_answer_target() -> None:
    """대상 검증은 **판정하지 않는다** — 그것이 코드로 성립하는가(codex 6R HIGH).

    ★재현(6R): `problem` 방에 6,001자 post → 리듀서는 `budget_exceeded` 로 거부해 **후보가 아닌데**,
      더블은 예산을 안 재므로 후보로 세고 그 대상의 `answer_selected` 를 `solved` 로 통과시켰다.
    ★봉합은 「예산 이식」이 아니라 **후보 집합의 제거**다: 오염된 값을 아무도 소비하지 않으면
      그 오염은 판정에 닿지 않는다. 대가는 이 축이 **선언된 공백**이 되는 것이고, 표가 그것을 적는다.
    """
    mod = _fake_relay_module()
    room, put = _double_kit(mod)
    # ⑴ 아무도 낸 적 없는 message_id 를 대상으로 삼아도 더블은 `unknown_target` 을 내지 않는다.
    relay, gen, head = room(gtype="problem")
    row = put(relay, "answer_selected", head, mod._state_hash(relay.rooms["t1"]["state"]),
              {"post_message_id": "f" * 32}, gtype="problem")
    assert row["reason"] != "unknown_target", \
        f"판정하지 않겠다고 선언한 축에서 verdict 를 냈다: {row}"
    # ⑵ 그 축이 표에 **경계로** 적혀 있는가(코드와 표가 함께 참이어야 한다).
    unjudged = [r for r in mod.CONTRACT_COVERAGE if not r["judged"]]
    assert any("대상 검증" in r["check"] for r in unjudged), \
        "코드는 안 재는데 표는 안 적었다 — 보이지 않는 억제는 미탐과 구별되지 않는다"
    # ⑶ 후보 집합 자체가 사라졌는가(오염될 값이 없어야 오염 경로가 닫힌다).
    assert "post_ids" not in relay.rooms["t1"], \
        "예산에 의존하는 후보 집합이 남아 있다 — 다음 사람이 다시 판정에 쓴다"
    # ⑷ 대조군: 리듀서는 여전히 그 축을 **잰다**(우리가 약하게 만든 것은 더블 하나다).
    oracle = _reduce_bodies([render_post(gen), row["body"]])
    assert [q["reason"] for q in oracle["quarantined"]] == ["unknown_target"], oracle


def test_j2_double_does_not_falsely_reject_operator_delegation() -> None:
    """운영자 위임에 **거짓 적색을 내지 않는다**(codex 6R HIGH).

    ★재현(6R): 만료된 debate 에서 운영자 `op1` 의 `delegate_chair` 를 리듀서는 격리 없이 받아
      `chair=bob` 으로 갔는데, 더블은 `permission` 으로 **격리**했다. 표는 그 조합을
      「판정 안 함」이라 적고 있었다 — ★안 재는 것과 **틀리게 좁게 재는 것**은 다른 사건이다.
    ★넓게 틀리면 시험이 비고(표가 그 공백을 적는다), 좁게 틀리면 **옳은 쪽이 붉어진다.**
      선언된 경계는 언제나 넓은 쪽이어야 한다.
    """
    import datetime
    mod = _fake_relay_module()
    room, put = _double_kit(mod)
    past = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for label, deadlines in (("만료", {"r0": past}), ("만료 아님", None)):
        relay, gen, head = room(ops="op1\n", deadlines=deadlines)
        st = relay.rooms["t1"]["state"]
        row = put(relay, "delegate_chair", head, mod._state_hash(st),
                  {"new_chair": "bob"}, frm="op1")
        assert row["reason"] != "permission", \
            f"{label}: 운영자 위임에 거짓 적색을 냈다(실물은 만료 중 이것을 받는다): {row}"
        assert relay.rooms["t1"]["state"]["chair"] == "bob", (label, row)
    # 대조군 — 의장도 운영자도 아닌 사람의 위임은 **여전히** permission 이다(권한 축은 살아 있다).
    relay, gen, head = room(ops="op1\n")
    row = put(relay, "delegate_chair", head, mod._state_hash(relay.rooms["t1"]["state"]),
              {"new_chair": "bob"}, frm="mallory")
    assert (row["valid"], row["reason"]) == (False, "permission"), row
    oracle = _reduce_bodies([render_post(gen), row["body"]], operators=frozenset({"op1"}))
    assert [q["reason"] for q in oracle["quarantined"]] == ["permission"], oracle
    # 그 경계가 표에 적혀 있는가.
    unjudged = [r for r in mod.CONTRACT_COVERAGE if not r["judged"]]
    assert any("운영자 대리 의장 위임" in r["check"] for r in unjudged), \
        "조건을 안 보고 받는다면 그 사실이 표에 있어야 한다"


def test_j3_report_boundary_applies_expiry_everywhere() -> None:
    """만료는 **보고 경계 전부**에 입혀진다 — `derived()` 와 `verdict_of_row()`(codex 6R MEDIUM).

    ★M375 는 `_effective_state()` **자체**만 겨눴다. 그래서 `verdict_of_row()` 쪽 호출을 원상태로
      되돌린 변이가 **살아남았다**(codex 실측 `REPORT_BOUNDARY_MUTANT SURVIVED`).
    ★★한 함수를 고친 것과 **그것을 부르는 모든 자리가 고쳐진 것**은 다른 말이다 —
      이 저장소가 「구현했다 ≠ 배선됐다」로 이미 두 번 다친 자리다. ⇒ 두 문을 각각 잰다.
    """
    import datetime
    mod = _fake_relay_module()
    room, put = _double_kit(mod)
    past = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    relay, gen, head = room(deadlines={"r0": past})
    st = relay.rooms["t1"]["state"]
    expired_hash = mod._state_hash({**st, "state": "expired"})
    row = put(relay, "post", head, expired_hash, {"round": 0, "body": "x"})
    assert row["valid"] is True, row
    seen = relay.derived("t1")
    verdict = mod.verdict_of_row(row, relay.rooms["t1"])
    assert seen["state"] == "expired", seen
    assert verdict["state_hash"] == seen["state_hash"], \
        f"두 보고 문이 서로 다른 상태를 말한다: verdict {verdict['state_hash'][:8]} vs derived {seen['state_hash'][:8]}"
    oracle = _reduce_bodies([render_post(gen), row["body"]], now=_now_iso())
    assert verdict["state_hash"] == oracle["state_hash"], \
        (verdict["state_hash"][:8], oracle["state_hash"][:8])


def test_j4_whitespace_gate_fails_when_base_branch_is_missing() -> None:
    """`main` 이 없으면 **실패**한다 — 실제 그 분기를 지난다(codex 6R LOW).

    ★`test_i3` 는 「없는 ref 를 인자로 준 경우」만 쟀고, **실제 `main` 부재 분기**(`merge-base` 가
      비는 경로)는 지나가지 않았다. 그래서 그 분기의 `rc=1` 을 지운 변이가 살아남았다
      (codex 실측 `nomain_rc=0`). ⇒ `main` 이 없는 임시 저장소에서 스크립트를 실제로 돌린다.
    ★★같은 병의 판본이다: 「그 줄을 썼다」와 「그 줄이 도는 것을 봤다」는 다른 말이다.
    """
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with tempfile.TemporaryDirectory() as tmp:
        run = lambda *a: subprocess.run(a, cwd=tmp, capture_output=True, text=True)
        run("git", "init", "-q", "-b", "other")
        os.makedirs(os.path.join(tmp, "tests"))
        with open(os.path.join(root, "tests", "ws_hygiene.sh"), encoding="utf-8") as fh:
            script = fh.read()
        target = os.path.join(tmp, "tests", "ws_hygiene.sh")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(script)
        with open(os.path.join(tmp, "seed.txt"), "w", encoding="utf-8") as fh:
            fh.write("seed\n")
        run("git", "add", "-A")
        run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed")
        out = subprocess.run(["bash", target], cwd=tmp, capture_output=True, text=True)
    assert out.returncode != 0, f"main 이 없는데 통과했다: {out.stdout!r}"
    assert "미측정" in out.stdout, f"미측정이라고 말하지 않았다: {out.stdout!r}"


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
