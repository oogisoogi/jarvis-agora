"""codex 0.1.4 사후 1R(2026-09-11 · REVISE 7건) 재현 프로브를 **테스트로 승격**한 것.

★왜 승격하는가(앞선 판본과 같은 이유): codex 는 일곱 결함을 **일회용 프로브**로 재현했다.
  프로브는 판정문에만 남고 저장소에는 안 남는다 ⇒ 같은 자리가 다시 열려도 아무 그물에 안 걸린다.
  「재현했다」와 「다시 나면 붉어진다」는 다른 말이다.

★각 시험은 판정문의 finding 과 **1:1** 이다(이름 뒤 대괄호). 봉합 **전에 전건 적색**을
  실측하고 시작했다 — 적→초 표는 보고에 있다.

★pytest 없이도 돈다: `python3 tests/test_codex_1r_seal.py` 가 같은 것을 재고 같은 판정을 낸다.
  (이 기계의 시스템 python3 는 PEP 668 로 --user 설치가 막혀 있다 — 검사기 부재로 안 재는 것과
   재서 통과한 것을 구별하려고 폴백 러너를 붙인다.)
"""
from __future__ import annotations

import io
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agora import cli, errors, mcp_server, selftest as st, tools   # noqa: E402
from agora.errors import AgoraError                                 # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _NoConfig:
    """설정 폴더가 **없는** 상태를 만든다 — 인자 오류가 설정 오류에 가려지는지 보는 자리."""

    def __enter__(self) -> str:
        self._old = os.environ.get("AGORA_CONFIG_DIR")
        self.dir = os.path.join(tempfile.gettempdir(), "agora-codex1r-no-such-dir")
        os.environ["AGORA_CONFIG_DIR"] = self.dir
        assert not os.path.exists(self.dir), "이 시험은 없는 폴더를 전제한다"
        return self.dir

    def __exit__(self, *exc: object) -> None:
        if self._old is None:
            os.environ.pop("AGORA_CONFIG_DIR", None)
        else:
            os.environ["AGORA_CONFIG_DIR"] = self._old


def _rc(argv: list[str]) -> int:
    """`cli.main` 을 돌려 **종료 코드만** 본다(stderr 의 JSON 은 여기서 안 읽는다)."""
    err = io.StringIO()
    old, sys.stderr = sys.stderr, err
    try:
        return cli.main(argv)
    finally:
        sys.stderr = old


# ── HIGH-1 인자 검증 < 설정 로딩 ─────────────────────────────────────────────

def test_h1_cli_argument_error_is_not_masked_by_config():
    """[HIGH-1] 설정이 없어도 **인자 오류는 인자 오류**(code 10)다.

    네 경로를 다 잰다 — 코어 도구·운영 동작·CLI 전용·자리 인자. 한 경로만 재면
    나머지가 조용히 설정 오류(code 2)로 남는다(실제로 그랬다).
    """
    with _NoConfig():
        for argv, why in (
            (["read", "--threadd", "x"], "코어 도구 · 모르는 인자"),
            (["read"], "코어 도구 · 빠진 필수 인자"),
            (["abort", "--threadd", "x"], "운영 동작 · 모르는 인자"),
            (["reconcile"], "CLI 전용 · 빠진 필수 인자"),
            (["export"], "CLI 전용 · 빠진 필수 인자"),
        ):
            rc = _rc(argv)
            assert rc == errors.ARGUMENT, f"{why}: rc={rc}(기대 {errors.ARGUMENT}) — {argv}"


def test_h1_mcp_invalid_params_is_not_masked_by_config():
    """[HIGH-1] MCP 도 같다 — 설정이 없어도 인자 오류는 `-32602`(우리 code 10)다."""
    with _NoConfig():
        for arguments, why in (({"threadd": "x"}, "모르는 인자"), ({}, "빠진 필수 인자")):
            try:
                mcp_server.handle({"method": "tools/call",
                                   "params": {"name": "agora.read", "arguments": arguments}},
                                  ctx=None)
            except AgoraError as e:
                assert e.code == errors.ARGUMENT, f"{why}: code {e.code}(기대 10)"
            else:
                raise AssertionError(f"{why}: 오류가 안 났다")


# ── HIGH-2 docs=code 축이 실제 파서를 안 탄다 ────────────────────────────────

def test_h2_docs_scan_catches_all_three_variants():
    """[HIGH-2] 오타 플래그·모르는 명령·self-parsed 잘못된 플래그 **셋 다** 적색이어야 한다.

    codex 가 쓴 그대로다: 문서를 한 글자씩 틀리게 읽히고 그 케이스가 붉어지는지 본다.
    구판은 셋 중 **둘**이 초록이었다(모르는 명령·self-parsed 는 계수조차 안 했다).
    """
    case = "문서=코드: 문서 명령이 파서를 지난다"
    original = st._read_text
    variants = [
        ("오타 플래그", "docs/OPERATOR.md", "--thread_id <방 id>", "--thraed_id <방 id>"),
        ("모르는 명령", "docs/OPERATOR.md", "agora read    --thread_id", "agora readd   --thread_id"),
        ("self-parsed 잘못된 플래그", "docs/INVITE.md", "agora selfcheck", "agora selfcheck --definitely-wrong"),
    ]
    try:
        for label, target, old, new in variants:
            seen = {"hit": False}

            def patched(p: str, t: str = target, o: str = old, n: str = new,
                        seen: dict = seen) -> str:
                text = original(p)
                if p.endswith(t):
                    if o not in text:
                        raise AssertionError(f"변이 앵커가 사라졌다: {t} 의 {o!r}")
                    seen["hit"] = True
                    return text.replace(o, n, 1)
                return text

            st._read_text = patched
            green = st._run_one(case)
            assert seen["hit"], f"{label}: 시험이 그 문서를 아예 안 읽는다({target})"
            assert not green, f"{label}: 문서를 틀리게 고쳤는데 케이스가 초록이다"
    finally:
        st._read_text = original


def test_h2_docs_scan_covers_the_five_claimed_docs():
    """[HIGH-2] 주장한 문서 5종 + 스킬 3종을 **실제로 훑는다**(문서마다 최소 1줄).

    ★「주장한 목록」이 정본이다 — 스캐너가 보는 목록이 그보다 좁으면 주장이 거짓이 된다.
    """
    want = ("README.md", "docs/ONBOARDING.md", "docs/RUN-WINDOWS.md", "docs/OPERATOR.md",
            "docs/INVITE.md", "skills/agora-delegate/SKILL.md",
            "skills/agora-delegate/brief-writer.md", "skills/agora-delegate/brief-reader.md")
    scanned = st.doc_scan_report()
    for rel in want:
        assert rel in scanned, f"이 문서를 안 훑는다: {rel}"
    for rel in want:
        if rel.endswith("brief-reader.md"):
            continue                      # 명령이 한 줄도 없는 문서(그 사실도 표에 남는다)
        assert scanned[rel]["parsed"] > 0, f"{rel}: 파서를 태운 명령이 0줄이다"


def test_h2_skipped_lines_are_counted_not_silent():
    """[HIGH-2] 건너뛴 줄은 **셈해서 말한다** — 조용한 통과 금지."""
    scanned = st.doc_scan_report()
    for rel, row in scanned.items():
        assert "skipped" in row, f"{rel}: 건너뜀 칸이 아예 없다"
        for item in row["skipped"]:
            assert item.get("why"), f"{rel}: 건너뛴 줄에 사유가 없다 — {item}"


# ── HIGH-3 OPERATOR 진행 블록이 실행 불가 ────────────────────────────────────

def test_h3_operator_progression_block_actually_runs():
    """[HIGH-3] 문서의 진행 블록을 **그대로 실행해** 완주한다(r3 에서만 권고).

    구판은 `advance --to_round 1` 직후 `resolve` 라 code 3(bad_transition)에서 멈췄다 —
    인자 이름은 맞았고 **순서가 틀렸다**. 이름만 재는 그물은 그것을 못 본다.
    """
    st.run_operator_progression_block()      # 실패하면 예외가 난다(그것이 판정이다)


# ── MEDIUM-4 반복 플래그·자리+이름 충돌 ──────────────────────────────────────

def test_m4_repeated_and_conflicting_arguments_are_rejected():
    """[MEDIUM-4] 같은 칸을 두 번 주면 **마지막 값이 조용히 이기지 않는다**."""
    a, b = "a" * 32, "b" * 32
    for argv, why in (
        (["--thread", a, "--thread", b], "같은 이름 반복"),
        (["--thread_id", a, "--thread-id", b], "같은 이름 · 붙임표 판본"),
        (cli._positional("join", [a, "--room_id", b]), "자리 인자 + 이름 인자"),
    ):
        try:
            got = cli._kv(argv)
        except AgoraError as e:
            assert e.code == errors.ARGUMENT, f"{why}: code {e.code}(기대 10)"
            detail = json.dumps(e.detail or {}, ensure_ascii=False)
            assert a[:8] in detail and b[:8] in detail, f"{why}: 두 값을 다 안 보여 준다 — {detail}"
        else:
            raise AssertionError(f"{why}: 조용히 통과했다 — {got}")


# ── MEDIUM-5 값 검증 없는 필수 인자 ──────────────────────────────────────────

def test_m5_id_arguments_are_validated_by_value():
    """[MEDIUM-5] 빈 문자열·한글·짧은 hex 는 **id 가 아니다**(있기만 하면 통과 금지)."""
    ctx = st._tools_ctx()
    for value in ("", "방번호", "ABCDEF", "a" * 31, None):
        try:
            tools.call("read", ctx, {"thread_id": value})
        except AgoraError as e:
            assert e.code == errors.ARGUMENT, f"{value!r}: code {e.code}(기대 10)"
            assert "thread_id" in str(e.message) + json.dumps(e.detail or {}, ensure_ascii=False), \
                f"{value!r}: 어느 칸인지 안 말한다"
        else:
            raise AssertionError(f"{value!r}: id 가 아닌 값으로 읽기가 성공했다")
    # 대조군 — 제대로 된 id 는 통과해야 한다(검사가 전부를 막으면 그것도 결함이다).
    tools.call("read", ctx, {"thread_id": "0" * 32})


# ── MEDIUM-6 MCP arguments 강제 변환 ─────────────────────────────────────────

def test_m6_mcp_arguments_must_be_an_object():
    """[MEDIUM-6] 스키마가 object 라고 했으면 **배열·문자열은 -32602** 다."""
    for arguments, why in (([["envelope", {}]], "배열"), ("envelope", "문자열"), (5, "정수")):
        try:
            mcp_server.handle({"method": "tools/call",
                               "params": {"name": "agora.envelope_check", "arguments": arguments}},
                              ctx=object())
        except AgoraError as e:
            assert e.code == errors.ARGUMENT, f"{why}: code {e.code}(기대 10 → -32602)"
        else:
            raise AssertionError(f"{why}: 객체가 아닌 arguments 가 정상 호출로 받아들여졌다")


def test_m6_id_arguments_carry_a_pattern_in_the_schema():
    """[MEDIUM-6] `thread_id` 스키마에 32-hex 패턴이 있다(스키마와 런타임이 같은 말을 한다)."""
    schema = mcp_server.tool_schema("read")["inputSchema"]["properties"]["thread_id"]
    assert schema.get("pattern"), f"thread_id 스키마에 패턴이 없다: {schema}"


# ── LOW-7 M243 서술 ─────────────────────────────────────────────────────────

def test_l7_last_resort_boundary_is_really_measured():
    """[LOW-7] 최후 경계(M243)가 **실제로 재지는지**를 잰다 — 서술이 아니라 실행으로.

    ★이 시험이 있는 이유: 「M243 을 제품 코드로 복구했다」는 설명이 사실이 아니었다
      (복구는 테스트 입력 보강이었고, 제품 경계는 기준 커밋에도 있었다).
      ⇒ 서술을 고치는 것으로 끝내지 않고, **그 축이 비어 있지 않다**를 기계가 재게 한다.
    ★판정: 프레임 묶음 중 **우리 오류가 아닌 예외**로 최후 경계까지 가는 것이 최소 하나 있어야 한다.
    """
    out = io.StringIO()
    mcp_server.serve(io.StringIO("\n".join(st.RPC_BAD_ARG_FRAMES) + "\n"), out,
                     ctx=st._tools_ctx())
    lines = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    reached = [x for x in lines
               if x.get("error", {}).get("data", {}).get("exception") not in (None, "AgoraError")]
    assert reached, "최후 경계까지 가는 프레임이 하나도 없다 — 그 축은 지금 비어 있다"
    assert lines[-1].get("result") is not None, "마지막 프레임에 서버가 대답하지 않았다"


def _main() -> int:
    cases = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    bad = 0
    for name, fn in cases:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:                    # noqa: BLE001 — 표를 내는 것이 목적이다
            bad += 1
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(cases) - bad}/{len(cases)} PASS · 실패 {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
