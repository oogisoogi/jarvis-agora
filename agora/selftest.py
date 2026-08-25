"""selftest — 픽스처 실행 + 뮤테이션 검산 하네스.

★이 하네스가 지키는 규율 넷(전부 실패 경험에서 온 것이다):

 ⑴ **변이 적용을 먼저 단언한다.** 변이가 소스에 안 들어갔는데 스위트가 초록이면
    그것은 「그물이 없다」가 아니라 **「아무것도 안 쟀다」**이고, 둘은 정반대 처방을 부른다.
 ⑵ **미측정(NOT-APPLIED)은 실패와 같은 급으로 위에 보고한다.** 각주로 내리면 라운드를 넘겨 눈을 감는다.
 ⑶ **판정은 종료 코드로 읽는다.** 표준출력 문구를 파싱하면, 실패 배너가 stderr 로 갈 때
    판정기가 「공허」를 보고한다.
 ⑷ **복원은 `finally` 에서 한다.** 하네스가 도중에 죽으면 변이가 소스에 남는다.
    그리고 자식 프로세스는 바이트코드 캐시를 쓰지 않는다 — 같은 길이 수정이 캐시에 가려지기 때문이다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Callable

from agora import contract_open, errors
from agora.cli import COMMANDS, MCP_EXEMPT, core_command_names, mcp_tool_name
from agora.errors import AgoraError

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 픽스처 ─────────────────────────────────────────────────────────────────
# 각 케이스는 「무엇을 하면 어떤 코드가 나와야 하는가」다.
# expect_code=None 이면 성공(예외 없음)을 기대한다.

def _case_unknown_subcommand() -> None:
    from agora.cli import dispatch
    dispatch("no-such-command", None)


def _case_unbuilt_subcommand() -> None:
    """미구현 서브커맨드 거부.

    ★코드(2)만 재면 안 된다 — `dispatch` 안의 **다른 경로**(배선 누락)도 같은 2를 낸다.
      실제로 M3 뮤테이션(가드 삭제)이 그 틈으로 살아남았다.
      그래서 이 분기에만 있는 `detail.reason` 까지 단언한다.
    """
    from agora.cli import dispatch
    try:
        dispatch("threads", None)
    except AgoraError as e:
        reason = (e.detail or {}).get("reason")
        if reason != "slice_not_built":
            raise AssertionError(
                f"코드는 맞지만 분기가 다르다: reason={reason!r}"
            ) from None
        raise


def _case_bad_error_code() -> None:
    AgoraError(99, "계약 밖 코드")


def _case_argparse_reject() -> None:
    import contextlib
    import io as _io
    from agora.cli import build_parser
    # argparse 는 실패 시 usage 를 stderr 로 뱉는다 — 재려는 것이 아니므로 삼킨다.
    with contextlib.redirect_stderr(_io.StringIO()):
        try:
            build_parser().parse_args(["--no-such-flag"])
        except SystemExit as e:
            raise AgoraError(errors.ARGUMENT, "인자 오류", {"argparse_exit": e.code}) from None
    raise AssertionError("argparse 가 거부하지 않았다")


def _case_retryable_contract() -> None:
    """재시도 가능은 저장층 축 둘뿐이어야 한다."""
    actual = {c for c in errors.ALL_CODES if AgoraError(c, "x").retryable}
    expected = {errors.STORE, errors.UNKNOWN_COMMIT}
    if actual != expected:
        raise AssertionError(f"retryable 집합 불일치: {sorted(actual)} != {sorted(expected)}")


def _case_codes_defined_once() -> None:
    """코드 숫자는 errors.py 에만 있어야 한다 — 다른 모듈이 같은 숫자를 다시 적으면 갈라진다."""
    import re
    offenders: list[str] = []
    pattern = re.compile(r"^\s*(PRECONDITION|GATE_REJECT|SIGNATURE|PERMISSION|STORE|"
                         r"UNKNOWN_COMMIT|STATE_CONFLICT|ARGUMENT)\s*=\s*\d+", re.M)
    for dirpath, _dirs, files in os.walk(os.path.join(_ROOT, "agora")):
        for fn in files:
            if not fn.endswith(".py") or fn == "errors.py":
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8") as fh:
                if pattern.search(fh.read()):
                    offenders.append(os.path.relpath(path, _ROOT))
    if offenders:
        raise AssertionError(f"코드 재정의: {offenders}")


def _case_mcp_names_derive_from_cli() -> None:
    """MCP 도구 이름은 CLI 등록표에서 파생돼야 한다 — 손으로 적은 목록이면 갈라진다."""
    core = set(core_command_names())
    exempt_in_core = core & MCP_EXEMPT
    if exempt_in_core:
        raise AssertionError(f"MCP 예외가 core 로 등록됨: {sorted(exempt_in_core)}")
    non_core = {n for n in COMMANDS if n not in core}
    if non_core != set(MCP_EXEMPT):
        raise AssertionError(f"CLI 전용 집합 불일치: {sorted(non_core)} != {sorted(MCP_EXEMPT)}")
    for n in core:
        if mcp_tool_name(n) != "agora." + n.replace("-", "_"):
            raise AssertionError(f"이름 규칙 위반: {n}")


def _case_contract_constants() -> None:
    """설계가 확정한 값이 사본에서 조용히 달라지지 않았는지."""
    c = contract_open
    checks = [
        (len(c.KINDS) == 9, f"kind 계수 {len(c.KINDS)} != 9"),
        (c.GENESIS_PREV == "genesis", "genesis prev 값"),
        (c.GENESIS_EXPECTED_STATE == "", "genesis expected_state 값"),
        (c.EXPIRED_GRACE_SECONDS == 300, "grace window"),
        (c.MAX_EVENT_BYTES == 65536, "이벤트 상한"),
        (c.ID_HEX_LEN == 32, "id 길이(128비트)"),
        (c.DEFAULT_HUMAN_APPROVAL is True, "승인 기본값"),
        (len(c.PARTICIPANT_FIELDS) == 5, "participant.json 칸 수"),
        (c.ANSWERABLE_CATEGORY == "problem", "answerable 카테고리"),
    ]
    bad = [msg for ok, msg in checks if not ok]
    if bad:
        raise AssertionError("; ".join(bad))


# ── S1-2 canonical ──────────────────────────────────────────────────────────

def _case_canonical_key_order() -> None:
    from agora.event import event_hash
    a = {"b": 1, "a": {"y": 2, "x": 3}, "z": [1, {"q": 0, "p": 9}]}
    b = {"z": [1, {"p": 9, "q": 0}], "a": {"x": 3, "y": 2}, "b": 1}
    if event_hash(a) != event_hash(b):
        raise AssertionError("키 순서가 해시를 바꿨다")


def _case_canonical_nfc() -> None:
    import unicodedata
    from agora.event import event_hash
    nfd = unicodedata.normalize("NFD", "한글 제목 · 시험")
    nfc = unicodedata.normalize("NFC", "한글 제목 · 시험")
    if nfd == nfc:
        raise AssertionError("픽스처가 NFD/NFC 를 구분하지 못한다 — 검사가 무의미하다")
    if event_hash({"title": nfd}) != event_hash({"title": nfc}):
        raise AssertionError("NFD 입력이 NFC 로 정규화되지 않았다")


def _case_canonical_duplicate_key() -> None:
    from agora.event import parse_event
    parse_event('{"a":1,"b":2,"a":3}')


def _case_canonical_size_cap() -> None:
    from agora.event import canonical_bytes
    canonical_bytes({"log": "x" * (64 * 1024 + 10)})


def _case_canonical_no_float() -> None:
    from agora.event import canonical_bytes
    canonical_bytes({"n": 1.5})


def _case_canonical_bitflip_detected() -> None:
    """canonical **안**의 1바이트 변조는 전부 해시를 바꿔야 한다(설계 AC).

    ★무작위 100회로 돌린다 — 한 자리만 찔러 보면 「그 자리만 민감한」 해시도 통과한다.
    """
    import hashlib
    import random
    from agora.event import canonical_bytes
    raw = canonical_bytes({
        "v": 1, "kind": "post", "from": "operator-a",
        "payload": {"round": 2, "body": "한 줄 본문 · ascii and 한글"},
    })
    base = hashlib.sha256(raw).hexdigest()
    rng = random.Random(20260825)  # 씨앗 고정 — 실패가 재현돼야 고칠 수 있다
    for _ in range(100):
        i = rng.randrange(len(raw))
        flipped = bytearray(raw)
        flipped[i] ^= 1 << rng.randrange(8)
        if hashlib.sha256(bytes(flipped)).hexdigest() == base:
            raise AssertionError(f"바이트 {i} 변조가 해시를 안 바꿨다")


def _case_canonical_rejects_str_subclass() -> None:
    """str 을 상속한 값은 거부한다 — __str__ 을 덮으면 서명 입력이 바뀔 수 있다."""
    from agora.event import canonical_bytes

    class Sneaky(str):
        pass

    canonical_bytes({"k": Sneaky("x")})


CASES: tuple[tuple[str, Callable[[], None], int | None], ...] = (
    ("unknown-subcommand → 10",   _case_unknown_subcommand,   errors.ARGUMENT),
    ("unbuilt-subcommand → 2",    _case_unbuilt_subcommand,   errors.PRECONDITION),
    ("bad-error-code → 10",       _case_bad_error_code,       errors.ARGUMENT),
    ("argparse-reject → 10",      _case_argparse_reject,      errors.ARGUMENT),
    ("retryable = {7,8}",         _case_retryable_contract,   None),
    ("codes-defined-once",        _case_codes_defined_once,   None),
    ("mcp-names-derive-from-cli", _case_mcp_names_derive_from_cli, None),
    ("contract-constants",        _case_contract_constants,   None),
    ("canonical: 키 순서 무관",    _case_canonical_key_order,  None),
    ("canonical: NFD→NFC",        _case_canonical_nfc,        None),
    ("canonical: 중복 키 → 10",   _case_canonical_duplicate_key, errors.ARGUMENT),
    ("canonical: 64KB 초과 → 3",  _case_canonical_size_cap,   errors.GATE_REJECT),
    ("canonical: 실수 거부 → 10", _case_canonical_no_float,   errors.ARGUMENT),
    ("canonical: 1바이트 변조 100회", _case_canonical_bitflip_detected, None),
    ("canonical: str 서브클래스 → 10", _case_canonical_rejects_str_subclass, errors.ARGUMENT),
)


# ── 뮤테이션 ────────────────────────────────────────────────────────────────
# (id, 파일, 찾을 문자열, 바꿀 문자열, 이 변이를 잡아야 하는 케이스 이름)
MUTATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("M1-retryable-widened", "agora/errors.py",
     "RETRYABLE: frozenset[int] = frozenset({STORE, UNKNOWN_COMMIT})",
     "RETRYABLE: frozenset[int] = frozenset({STORE, UNKNOWN_COMMIT, GATE_REJECT})",
     "retryable = {7,8}"),
    ("M2-unknown-cmd-silent", "agora/cli.py",
     'raise AgoraError(errors.ARGUMENT, "알 수 없는 서브커맨드", {"command": name})',
     'meta = {"core": False, "built": True, "slice": "?"}',
     "unknown-subcommand → 10"),
    ("M3-unbuilt-passes", "agora/cli.py",
     'if not meta["built"]:',
     'if False:',
     "unbuilt-subcommand → 2"),
    ("M4-error-code-guard-off", "agora/errors.py",
     "if code not in ALL_CODES:",
     "if False:",
     "bad-error-code → 10"),
    ("M5-grace-changed", "agora/contract_open.py",
     "EXPIRED_GRACE_SECONDS = 300",
     "EXPIRED_GRACE_SECONDS = 30",
     "contract-constants"),
    ("M6-sort-keys-off", "agora/event.py",
     "        sort_keys=True,",
     "        sort_keys=False,",
     "canonical: 키 순서 무관"),
    ("M7-nfc-off", "agora/event.py",
     'def _nfc(text: str) -> str:\n    return unicodedata.normalize("NFC", text)',
     "def _nfc(text: str) -> str:\n    return text",
     "canonical: NFD→NFC"),
    ("M8-dupkey-allowed", "agora/event.py",
     '        if nk in seen:\n            raise AgoraError(errors.ARGUMENT, "중복 키", {"key": nk})',
     "        if False:\n            pass",
     "canonical: 중복 키 → 10"),
    ("M9-size-cap-off", "agora/event.py",
     "    if len(raw) > MAX_EVENT_BYTES:",
     "    if False:",
     "canonical: 64KB 초과 → 3"),
    ("M10-float-allowed", "agora/event.py",
     '    if type(node) is float:\n        raise AgoraError(errors.ARGUMENT, "이벤트에 실수를 담을 수 없다", {"path": path})',
     "    if type(node) is float:\n        return node",
     "canonical: 실수 거부 → 10"),
    ("M11-isinstance-widened", "agora/event.py",
     "    if type(node) is str:\n        return _nfc(node)",
     "    if isinstance(node, str):\n        return _nfc(node)",
     "canonical: str 서브클래스 → 10"),
)


def _run_cases() -> tuple[list[dict[str, Any]], set[int]]:
    rows: list[dict[str, Any]] = []
    observed: set[int] = set()
    for name, fn, expect in CASES:
        try:
            fn()
        except AgoraError as e:
            observed.add(e.code)
            ok = (e.code == expect)
            rows.append({"case": name, "result": "PASS" if ok else "FAIL",
                         "got": e.code, "want": expect})
        except Exception as e:  # noqa: BLE001 — 픽스처의 assert 실패도 여기로 온다
            rows.append({"case": name, "result": "FAIL", "got": type(e).__name__,
                         "want": expect, "detail": str(e)})
        else:
            ok = expect is None
            rows.append({"case": name, "result": "PASS" if ok else "FAIL",
                         "got": None, "want": expect})
    return rows, observed


def _cases_pass_in_subprocess() -> bool:
    """자식 프로세스에서 케이스만 돌린다.

    -B 로 바이트코드 캐시를 끈다 — 같은 길이 수정이 캐시에 가려져
    「변이했는데 결과가 같다」는 거짓 생존을 만드는 것을 막는다.
    판정은 **종료 코드**로만 읽는다(출력 문구 파싱 금지).
    """
    code = (
        "import sys; sys.path.insert(0, %r);"
        "from agora.selftest import _run_cases;"
        "rows, _ = _run_cases();"
        "sys.exit(0 if all(r['result'] == 'PASS' for r in rows) else 1)"
    ) % _ROOT
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, "-B", "-c", code], env=env,
                          capture_output=True, text=True, cwd=_ROOT)
    return proc.returncode == 0


def _run_mutations() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mid, relpath, old, new, killer in MUTATIONS:
        path = os.path.join(_ROOT, relpath)
        with open(path, encoding="utf-8") as fh:
            original = fh.read()

        # ⑴ 변이 적용 선-단언 — 대상 문자열이 없으면 아무것도 재지 못한다.
        if old not in original:
            rows.append({"mutation": mid, "result": "NOT-APPLIED",
                         "why": "대상 문자열 부재(소스가 옮겨졌을 수 있다)",
                         "file": relpath, "killer": killer})
            continue
        if original.count(old) != 1:
            rows.append({"mutation": mid, "result": "NOT-APPLIED",
                         "why": f"대상 문자열이 {original.count(old)}곳 — 어느 것을 쟀는지 알 수 없다",
                         "file": relpath, "killer": killer})
            continue

        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(original.replace(old, new, 1))
            # ⑵ 변이가 실제로 파일에 있는지 되읽어 확인한다.
            with open(path, encoding="utf-8") as fh:
                if new not in fh.read():
                    rows.append({"mutation": mid, "result": "NOT-APPLIED",
                                 "why": "쓰기 후 재독에서 변이 미발견", "file": relpath,
                                 "killer": killer})
                    continue
            killed = not _cases_pass_in_subprocess()
            rows.append({"mutation": mid, "result": "KILLED" if killed else "SURVIVED",
                         "file": relpath, "killer": killer})
        finally:
            # ⑷ 무슨 일이 있어도 복원한다.
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(original)
    return rows


def run() -> dict[str, Any]:
    case_rows, observed = _run_cases()
    mutation_rows = _run_mutations()

    未 = sorted(set(errors.ALL_CODES) - observed)
    unbuilt = sorted(n for n, m in COMMANDS.items() if not m["built"])

    case_fail = [r for r in case_rows if r["result"] != "PASS"]
    mut_survived = [r for r in mutation_rows if r["result"] == "SURVIVED"]
    mut_notapplied = [r for r in mutation_rows if r["result"] == "NOT-APPLIED"]

    report: dict[str, Any] = {
        # ★미측정을 맨 위에 둔다 — 아래로 내리면 안 읽힌다.
        "미측정": {
            "뮤테이션_NOT_APPLIED": len(mut_notapplied),
            "발생하지_않은_오류코드": 未,
            "note": "발생하지 않은 코드는 그 코드를 내는 경로가 아직 없다는 뜻이다."
                    " 게이트 통과 조건은 0이며, 슬라이스가 진행되며 줄어든다.",
        },
        "cases": case_rows,
        "mutations": mutation_rows,
        "요약": {
            "케이스": f"{len(case_rows) - len(case_fail)}/{len(case_rows)} PASS",
            "뮤테이션": f"{len([r for r in mutation_rows if r['result'] == 'KILLED'])}/"
                        f"{len(mutation_rows)} KILLED",
            "미구현_서브커맨드": unbuilt,
            "슬라이스": "S1-2",
        },
        # ok 는 「이 슬라이스가 자기 몫을 했는가」다.
        # 미발생 오류코드는 다음 슬라이스의 몫이므로 여기서 ok 를 깎지 않는다 —
        # 대신 위 「미측정」 칸에 남아 게이트에서 세어진다.
        "ok": not case_fail and not mut_survived and not mut_notapplied,
    }
    return report
