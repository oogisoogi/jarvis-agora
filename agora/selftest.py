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

import json
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



# ── S1-3 서명 픽스처 ─────────────────────────────────────────────────────────
# ★키는 매 실행마다 새로 만든다. 저장소에 키를 두지 않는다 —
#   픽스처 키라도 파일로 남으면 언젠가 진짜 키가 그 자리에 놓인다.
_FIX: dict[str, Any] = {}


FIXTURE_ENV = "AGORA_SELFTEST_FIXTURES"


def _fixtures() -> dict[str, Any]:
    """픽스처 키 묶음. 한 번 만들고 **자식 프로세스와 공유**한다.

    ★왜: 뮤테이션마다 자식 프로세스가 스위트를 다시 도는데, 매번 키를 새로 만들면
      키 생성이 실행 시간을 지배한다(측정: 22 뮤테이션에서 2분 초과).
      공유해도 검사 대상은 그대로다 — 재는 것은 키 생성이 아니라 서명·검증 로직이다.
    """
    if _FIX:
        return _FIX
    import atexit
    import shutil
    import subprocess as sp
    import tempfile
    shared = os.environ.get(FIXTURE_ENV)
    if shared and os.path.isdir(shared):
        d = shared          # 부모가 만든 것을 쓴다 — 지우지 않는다(부모가 지운다)
    else:
        d = tempfile.mkdtemp(prefix="agora-selftest-")
        atexit.register(shutil.rmtree, d, True)
    for name in ("a", "b"):
        if os.path.exists(os.path.join(d, name)):
            continue
        sp.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "fixture",
                "-f", os.path.join(d, name), "-q"], check=True, capture_output=True)
    roster = os.path.join(d, "allowed_signers")
    with open(os.path.join(d, "a.pub"), encoding="utf-8") as fh:
        pub = fh.read().strip()
    with open(roster, "w", encoding="utf-8") as fh:
        fh.write(f"operator-a {pub}\n")
    # ★2인 명부 — reducer 픽스처용. 기존 1인 명부(`roster`)는 그대로 둔다:
    #   「명부 밖 = unsigned」를 재는 S1 케이스가 그 파일에 기대고 있다.
    roster_ab = os.path.join(d, "allowed_signers_ab")
    with open(os.path.join(d, "b.pub"), encoding="utf-8") as fh:
        pub_b = fh.read().strip()
    with open(roster_ab, "w", encoding="utf-8") as fh:
        fh.write(f"operator-a {pub}\noperator-b {pub_b}\n")
    notkey = os.path.join(d, "not-a-key")
    with open(notkey, "w", encoding="utf-8") as fh:
        fh.write("이건 키가 아니다\n")
    _FIX.update({"dir": d, "key_a": os.path.join(d, "a"), "key_b": os.path.join(d, "b"),
                 "roster": roster, "roster_ab": roster_ab, "notkey": notkey, "empty_roster": os.path.join(d, "none")})
    return _FIX


def _with_key(key_path: str, fn):
    old = os.environ.get("AGORA_SIGNING_KEY")
    os.environ["AGORA_SIGNING_KEY"] = key_path
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("AGORA_SIGNING_KEY", None)
        else:
            os.environ["AGORA_SIGNING_KEY"] = old


_EVENT = {"v": 1, "kind": "post", "from": "operator-a",
          "payload": {"round": 1, "body": "정상 본문 · 한글과 ascii"}}


def _sign_fixture() -> dict[str, Any]:
    from agora.sign import sign_event
    f = _fixtures()
    return _with_key(f["key_a"], lambda: sign_event(_EVENT))


def _case_sign_verify_ok() -> None:
    from agora.event import canonical_bytes
    from agora.sign import OK, verify
    f = _fixtures()
    res = _sign_fixture()
    got = verify(canonical_bytes(_EVENT), res["signature"], "operator-a", f["roster"])
    if got != OK:
        raise AssertionError(f"정상 서명이 {got}")


def _case_sign_verify_tampered_is_BAD() -> None:
    from agora.event import canonical_bytes
    from agora.sign import BAD, verify
    f = _fixtures()
    res = _sign_fixture()
    raw = bytearray(canonical_bytes(_EVENT))
    raw[-2] ^= 0x01  # canonical **안**의 1바이트
    got = verify(bytes(raw), res["signature"], "operator-a", f["roster"])
    if got != BAD:
        raise AssertionError(f"변조가 {got} — BAD 여야 한다")


def _case_sign_verify_unsigned() -> None:
    from agora.event import canonical_bytes
    from agora.sign import UNSIGNED, verify
    f = _fixtures()
    got = verify(canonical_bytes(_EVENT), None, "operator-a", f["roster"])
    if got != UNSIGNED:
        raise AssertionError(f"무서명이 {got}")


def _case_sign_off_roster_is_unsigned_not_BAD() -> None:
    """명부 밖 키의 **유효한** 서명은 BAD 가 아니라 unsigned 다.

    ★둘을 뭉치면 「변조됐다」와 「모르는 사람이다」가 구별되지 않는다.
    """
    from agora.event import canonical_bytes
    from agora.sign import BAD, UNSIGNED, verify
    f = _fixtures()
    res = _with_key(f["key_b"], lambda: __import__("agora.sign", fromlist=["x"]).sign_event(_EVENT))
    got = verify(canonical_bytes(_EVENT), res["signature"], "operator-a", f["roster"])
    if got == BAD:
        raise AssertionError("명부 밖 키를 BAD 로 판정했다(변조와 구별 실패)")
    if got != UNSIGNED:
        raise AssertionError(f"명부 밖 키가 {got}")


def _case_verify_missing_roster_is_unsigned() -> None:
    """명부 파일이 **없으면** 「모두 ok」가 아니라 「아무도 모른다」다.

    ★이 케이스는 뮤테이션 M16 이 살아남아서 생겼다. 살아남은 원인은
      「층 방어」도 「등가 뮤턴트」도 아니고 **그물이 없었던 것**이다 —
      명부 밖 키 케이스는 *존재하는* 명부를 쓰므로 이 분기를 한 번도 지나지 않았다.
      변이가 초록일 때 원인을 구별하지 않았다면 이 구멍은 그대로 남았을 것이다.
    """
    from agora.event import canonical_bytes
    from agora.sign import UNSIGNED, verify
    f = _fixtures()
    res = _sign_fixture()
    got = verify(canonical_bytes(_EVENT), res["signature"], "operator-a", f["empty_roster"])
    if got != UNSIGNED:
        raise AssertionError(f"명부 부재인데 {got} — 없는 명부는 아무도 보증하지 않는다")


def _case_signer_refuses_scrub() -> None:
    from agora.sign import sign_event
    f = _fixtures()
    ev = {**_EVENT, "payload": {"body": "키는 sk-abcdefghijklmnop1234 이다"}}
    _with_key(f["key_a"], lambda: sign_event(ev))


def _case_signer_refuses_bad_kind() -> None:
    from agora.sign import sign_event
    f = _fixtures()
    _with_key(f["key_a"], lambda: sign_event({**_EVENT, "kind": "whatever"}))


def _case_signer_refuses_oversize() -> None:
    from agora.sign import sign_event
    f = _fixtures()
    _with_key(f["key_a"], lambda: sign_event({**_EVENT, "payload": {"body": "x" * 70000}}))


def _case_signer_refuses_caller_key() -> None:
    """호출자가 키를 지목하면 거부한다 — 지목이 가능하면 분리가 무의미해진다."""
    import json as _json
    import subprocess as _sp
    from agora.sign import SIGNER_BIN, _ROOT
    f = _fixtures()

    def go():
        p = _sp.run([SIGNER_BIN], input=_json.dumps({"event": _EVENT, "key": "/etc/passwd"}),
                    capture_output=True, text=True, cwd=_ROOT)
        if p.returncode == 0:
            raise AssertionError("호출자 지정 키로 서명했다")
        raise AgoraError(_json.loads(p.stderr)["code"], "거부됨", None)

    _with_key(f["key_a"], go)


def _case_signer_no_key_is_precondition() -> None:
    from agora.sign import sign_event
    old = os.environ.pop("AGORA_SIGNING_KEY", None)
    try:
        sign_event(_EVENT)
    finally:
        if old is not None:
            os.environ["AGORA_SIGNING_KEY"] = old


def _case_signer_bad_key_is_signature_error() -> None:
    """키 파일이 키가 아니면 서명 실패(code 4)다 — 전제 미비(2)와 다른 자리다."""
    from agora.sign import sign_event
    f = _fixtures()
    _with_key(f["notkey"], lambda: sign_event(_EVENT))


def _case_no_private_key_read_outside_signer() -> None:
    """서명기 밖에서 개인키를 읽거나 ssh-keygen 으로 서명하는 경로가 없어야 한다."""
    import re as _re
    allowed = {"signer.py"}
    offenders: list[str] = []
    sign_call = _re.compile(r'"-Y",\s*"sign"')
    for dirpath, _dirs, files in os.walk(os.path.join(_ROOT, "agora")):
        for fn in files:
            if not fn.endswith(".py") or fn in allowed or fn == "selftest.py":
                continue
            with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                if sign_call.search(fh.read()):
                    offenders.append(fn)
    if offenders:
        raise AssertionError(f"서명기 우회 서명 경로: {offenders}")


def _case_scrub_fail_closed() -> None:
    """규칙 파일이 없으면 통과가 아니라 전량 차단이다."""
    from agora.scrub import load_rules
    load_rules(os.path.join(_ROOT, "config", "no-such-rules.json"))


# ── S1-4 명부·키 수명주기 ────────────────────────────────────────────────────

def _case_revoked_key_is_invalid() -> None:
    """폐기된 키의 **유효한** 서명은 무효다 — 그리고 사유가 `revoked` 로 남아야 한다.

    「그때는 유효했다」와 「지금은 무효다」는 다른 사건이라, 사유를 안 남기면
    나중에 「왜 무효인가」를 되짚을 수 없다.
    """
    import shutil
    from agora.event import canonical_bytes
    from agora.sign import UNSIGNED, verify_detail
    f = _fixtures()
    revoked = os.path.join(f["dir"], "revoked_keys")
    shutil.copyfile(os.path.join(f["dir"], "a.pub"), revoked)
    try:
        res = _sign_fixture()
        d = verify_detail(canonical_bytes(_EVENT), res["signature"], "operator-a",
                          f["roster"], revoked)
        if d["verdict"] != UNSIGNED or d["reason"] != "revoked":
            raise AssertionError(f"폐기 키 판정이 {d}")
        # 대조군 — 폐기 목록을 안 주면 같은 서명이 ok 여야 한다(검사가 대상에 닿았다는 증거)
        d2 = verify_detail(canonical_bytes(_EVENT), res["signature"], "operator-a",
                           f["roster"], None)
        if d2["verdict"] != "ok":
            raise AssertionError(f"대조군이 ok 가 아니다: {d2} — 폐기와 무관한 이유로 죽었다")
    finally:
        os.path.exists(revoked) and os.remove(revoked)


def _case_roster_checkpoint_changes() -> None:
    """명부 파일 하나만 바뀌어도 체크포인트가 바뀌고, **파일 경계**도 해시에 들어간다."""
    import shutil
    import tempfile
    from agora import roster
    from agora.contract_open import (ROSTER_ALLOWED_SIGNERS, ROSTER_OPERATORS,
                                     ROSTER_REVOKED_KEYS)
    base = tempfile.mkdtemp(prefix="agora-roster-")
    try:
        def write(root, allowed, revoked, ops):
            os.makedirs(os.path.join(root, "participants"), exist_ok=True)
            for rel, body in ((ROSTER_ALLOWED_SIGNERS, allowed),
                              (ROSTER_REVOKED_KEYS, revoked),
                              (ROSTER_OPERATORS, ops)):
                with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
                    fh.write(body)

        r1 = os.path.join(base, "r1"); r2 = os.path.join(base, "r2")
        r3 = os.path.join(base, "r3")
        write(r1, "AB", "", "")
        write(r2, "A", "B", "")      # 이어 붙이면 r1 과 같은 바이트열이다
        write(r3, "AB", "", "op-1")  # 한 파일만 다르다
        c1, c2, c3 = roster.checkpoint(r1), roster.checkpoint(r2), roster.checkpoint(r3)
        if c1 == c2:
            raise AssertionError("파일 경계가 해시에 안 들어갔다 — 내용을 옮겨도 같은 값이 나온다")
        if c1 == c3:
            raise AssertionError("한 파일이 바뀌었는데 체크포인트가 그대로다")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _case_namespace_single_source() -> None:
    """서명 namespace 문자열이 상수 정의 밖에 또 적혀 있으면 안 된다."""
    from agora.contract_open import SIGN_NAMESPACE
    offenders: list[str] = []
    for dirpath, _dirs, files in os.walk(os.path.join(_ROOT, "agora")):
        for fn in files:
            if not fn.endswith(".py") or fn in {"contract_open.py", "selftest.py"}:
                continue
            with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                if SIGN_NAMESPACE in fh.read():
                    offenders.append(fn)
    if offenders:
        raise AssertionError(f"namespace 리터럴 재등장: {offenders}")


def _participant_dir(doc_override: dict[str, Any] | None = None,
                     file_mode: int = 0o600, dir_mode: int = 0o700) -> str:
    import json as _json
    import tempfile
    from agora.contract_open import SIGN_NAMESPACE
    d = tempfile.mkdtemp(prefix="agora-part-")
    doc = {"id": "operator-a", "display_name": "Operator A",
           "key_fingerprint": "SHA256:fixture", "namespace": SIGN_NAMESPACE,
           "operator": False}
    if doc_override:
        doc.update(doc_override)
    path = os.path.join(d, "participant.json")
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump(doc, fh)
    os.chmod(path, file_mode)
    os.chmod(d, dir_mode)
    return d


def _case_participant_ok() -> None:
    from agora import participant
    d = _participant_dir()
    if participant.load(d)["id"] != "operator-a":
        raise AssertionError("정상 participant.json 로드 실패")


def _case_participant_loose_file_mode() -> None:
    from agora import participant
    participant.load(_participant_dir(file_mode=0o644))


def _case_participant_loose_dir_mode() -> None:
    from agora import participant
    participant.load(_participant_dir(dir_mode=0o755))


def _case_participant_extra_field() -> None:
    from agora import participant
    participant.load(_participant_dir({"secret": "leaked"}))


def _case_keygen_refuses_overwrite() -> None:
    """키 덮어쓰기를 허용하면 그 키로 서명된 과거 이벤트를 아무도 검증 못 하게 된다."""
    import shutil
    import tempfile
    from agora import keygen
    d = tempfile.mkdtemp(prefix="agora-kg-")
    old = os.environ.get("AGORA_CONFIG_DIR")
    os.environ["AGORA_CONFIG_DIR"] = d
    try:
        first = keygen.run(["operator-x"])
        if not first["key_fingerprint"].startswith("SHA256:"):
            raise AssertionError("지문 형식이 아니다")
        keygen.run(["operator-x"])  # 두 번째 — 거부돼야 한다
    finally:
        if old is None:
            os.environ.pop("AGORA_CONFIG_DIR", None)
        else:
            os.environ["AGORA_CONFIG_DIR"] = old
        shutil.rmtree(d, ignore_errors=True)


# ── S1-5 golden 벡터 ────────────────────────────────────────────────────────
GOLDEN_DIR = os.path.join(_ROOT, "tests", "golden")


def _golden() -> dict[str, Any]:
    with open(os.path.join(GOLDEN_DIR, "canonical-vectors.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _case_golden_variants_collapse() -> None:
    """LF/CRLF/CR × NFC/NFD 5변형이 **하나의 canonical** 로 떨어져야 한다."""
    from agora.event import event_hash
    g = _golden()
    hashes = {name: event_hash(dict(g["base_event"], payload=payload))
              for name, payload in g["variants"].items()}
    if len(set(hashes.values())) != 1:
        raise AssertionError(f"변형이 갈렸다: {hashes}")
    if next(iter(hashes.values())) != g["expected_hash"]:
        raise AssertionError("기록된 기대 해시와 다르다 — canonical 규칙이 바뀌었다")


def _case_golden_signature_verifies() -> None:
    """저장된 서명이 저장된 공개키로 검증된다 — **다른 기계도 이 파일만으로 재검증할 수 있다.**"""
    from agora.event import canonical_bytes
    from agora.sign import OK, verify
    g = _golden()
    raw = canonical_bytes(dict(g["base_event"], payload=g["variants"]["lf-nfc"]))
    if raw.decode("utf-8") != g["expected_canonical_utf8"]:
        raise AssertionError("canonical 바이트가 기록과 다르다")
    got = verify(raw, g["signature"], g["principal"],
                 os.path.join(GOLDEN_DIR, "allowed_signers"))
    if got != OK:
        raise AssertionError(f"golden 서명 검증이 {got}")


def _case_golden_bitflip_is_BAD() -> None:
    """golden 벡터의 canonical **안** 1바이트를 뒤집으면 BAD 여야 한다."""
    from agora.event import canonical_bytes
    from agora.sign import BAD, verify
    g = _golden()
    raw = bytearray(canonical_bytes(dict(g["base_event"], payload=g["variants"]["lf-nfc"])))
    raw[len(raw) // 2] ^= 0x01
    got = verify(bytes(raw), g["signature"], g["principal"],
                 os.path.join(GOLDEN_DIR, "allowed_signers"))
    if got != BAD:
        raise AssertionError(f"변조가 {got}")


def _case_golden_declares_what_it_did_not_test() -> None:
    """벡터 파일이 **안 잰 것**을 스스로 밝혀야 한다.

    안 밝히면 다음 사람이 「교차 OS 검증을 했다」로 읽는다 — 실제로 한 것은
    「교차 OS 입력이 같은 canonical 로 떨어진다」뿐이다.
    """
    g = _golden()
    made = g.get("생성", {})
    key = next((k for k in made if "미실행" in k), None)
    if key is None:
        raise AssertionError("golden 벡터에 미실행 고지 칸이 없다")
    note = made[key]
    if "Windows" not in note or "하지 않았다" not in note:
        raise AssertionError(f"고지 내용이 무엇을 안 쟀는지 말하지 않는다: {note[:60]}")


# ── S1-6 원장 · S1-7 저장층 ─────────────────────────────────────────────────

def _ledger_with(n: int):
    import tempfile
    from agora.ledger import Ledger
    d = tempfile.mkdtemp(prefix="agora-led-")
    L = Ledger(d)
    for i in range(n):
        L.append(direction="sent", message_id=f"{i:032x}", event_hash="a" * 64, stage="sent")
    return L


def _case_ledger_chain_ok() -> None:
    L = _ledger_with(100)
    r = L.verify()
    if not r["ok"] or r["rows"] != 100:
        raise AssertionError(f"정상 100행 검증 실패: {r}")


def _case_ledger_body_altered() -> None:
    """칸 **하나**만 고쳐도 잡혀야 한다 — 링크만 재는 검사는 여기를 통과시킨다."""
    L = _ledger_with(10)
    lines = open(L.path, encoding="utf-8").read().splitlines()
    row = json.loads(lines[5])
    row["hash"] = "b" * 64                      # 링크(prev_ledger_hash)는 건드리지 않는다
    lines[5] = json.dumps(row, ensure_ascii=False, sort_keys=True)
    with open(L.path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    r = L.verify()
    if r["ok"] or r["reason"] != "row_body_altered":
        raise AssertionError(f"칸 변조를 못 잡았다: {r}")


def _case_ledger_row_deleted() -> None:
    L = _ledger_with(10)
    lines = open(L.path, encoding="utf-8").read().splitlines()
    del lines[5]
    with open(L.path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    r = L.verify()
    if r["ok"] or r["reason"] != "chain_broken":
        raise AssertionError(f"삭제를 못 잡았다: {r}")


def _case_ledger_append_only() -> None:
    """원장 모듈에 **전량 쓰기 경로가 없어야** 한다.

    ★규율로 「append 만 쓰자」고 해 봐야 다음 사람이 `open(path, "w")` 를 쓴다.
      그러니 코드에서 그 형태를 세어 0 인지 본다.
    """
    import re as _re
    src = open(os.path.join(_ROOT, "agora", "ledger.py"), encoding="utf-8").read()
    # 원장 파일(self.path)에 대한 쓰기는 "a" 모드만 허용한다.
    bad = _re.findall(r'open\(self\.path,\s*"w"', src)
    if bad:
        raise AssertionError(f"원장 전량 쓰기 경로 {len(bad)}건")


def _case_ledger_stores_raw_event() -> None:
    L = _ledger_with(0)
    raw = b'{"v":1,"kind":"post"}'
    path = L.store_event("t" * 32, "m" * 32, raw)
    if open(path, "rb").read() != raw:
        raise AssertionError("이벤트 원문이 보존되지 않았다")


def _case_store_mock_satisfies_contract() -> None:
    from agora.store_base import Store
    from agora.store_mock import MockStore
    if not isinstance(MockStore(), Store):
        raise AssertionError("mock 이 저장층 계약을 충족하지 않는다")


def _case_store_unknown_commit() -> None:
    """저장 성공 불명(8) — 성공으로도 실패로도 단정하지 않는다."""
    from agora.store_mock import MockStore
    s = MockStore()
    s.fail_next_append = "unknown"
    s.append(thread_id="t1", category="problem", title="T", body="b", is_genesis=True)


def _case_store_error_is_retryable() -> None:
    from agora.store_mock import MockStore
    s = MockStore()
    s.fail_next_append = "store"
    s.append(thread_id="t1", category="problem", title="T", body="b", is_genesis=True)


def _case_store_pagination_returns_all() -> None:
    """페이지를 끝까지 돌아야 전건이 나온다 — 한 페이지만 보면 조용히 누락된다."""
    from agora.store_mock import MockStore
    s = MockStore()
    for i in range(250):
        s.inject_raw(thread_id="t2", body=f"e{i}")
    seen, cur = 0, None
    for _ in range(100):
        page = s.fetch(thread_id="t2", cursor=cur, limit=100)
        seen += len(page["items"])
        cur = page["next_cursor"]
        if not cur:
            break
    if seen != 250:
        raise AssertionError(f"페이지 순회에서 {seen}/250 만 회수")


def _case_store_answerable_only_problem() -> None:
    from agora.store_mock import MockStore
    cats = MockStore().categories()
    answerable = {k for k, v in cats.items() if v["is_answerable"]}
    if answerable != {"problem"}:
        raise AssertionError(f"answerable 카테고리가 {answerable} — problem 하나여야 한다")


# ── S2-1 kind 9종 스키마 ────────────────────────────────────────────────────
# ★여기서 재는 것은 **모양**뿐이다 — 누가 보냈는지(권한·5)·순서가 맞는지(경합·9)는
#   S2-2~S2-5 의 몫이다. 그래서 이 픽스처의 이벤트는 서명도 순서도 갖지 않는다.
#   경계를 안 그으면 스키마 케이스가 reducer 결함까지 「잡은 척」하게 된다.
#
# ★픽스처는 전부 가짜다(브리프 §2) — 실제 id·이름·경로를 넣지 않는다.

_ID_A = "0123456789abcdef0123456789abcdef"   # 32자 hex
_ID_B = "fedcba9876543210fedcba9876543210"
_PREV = "b" * 64                              # 앞 이벤트 해시 자리


def _fake_envelope() -> dict[str, Any]:
    return {
        "env": {"os": "fake-os", "app": "fake-app", "version": "0.0.0"},
        "symptom": "가짜 증상 한 줄",
        "repro_steps": ["가짜 1단계"],
        "log_excerpt": "가짜 로그 발췌",
        "tried": ["가짜 시도"],
        "questions": ["가짜 질문"],
    }


# kind → (정상 payload, 결손시 뺄 칸, 그때 기대 코드)
# ★칸 하나를 빼는 이유: 「필수」라고 적어 둔 것이 정말로 필수인지는 **빼 봐야** 안다.
def _payload_table() -> dict[str, tuple[dict[str, Any], str, int]]:
    return {
        "genesis": ({"type": "debate", "title": "가짜 제목", "body": "가짜 본문",
                     "chair": "operator-a"}, "title", errors.ARGUMENT),
        "post": ({"round": 1, "body": "가짜 발언"}, "body", errors.ARGUMENT),
        "advance": ({"from_round": 1, "to_round": 2}, "to_round", errors.ARGUMENT),
        "resolution": ({"summary": "가짜 요약", "dissent": [],
                        "recommended_actions": [{"text": "가짜 권고",
                                                 "execution": "forbidden"}]},
                       "summary", errors.ARGUMENT),
        "answer_selected": ({"post_message_id": _ID_B}, "post_message_id",
                            errors.ARGUMENT),
        "close": ({"reason": "solved"}, "reason", errors.ARGUMENT),
        "delegate_chair": ({"new_chair": "operator-b"}, "new_chair", errors.ARGUMENT),
        "abort": ({"reason": "가짜 중단 사유"}, "reason", errors.ARGUMENT),
        "vote": ({"target": _ID_B, "value": 1}, "value", errors.ARGUMENT),
    }


def _fake_event(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    genesis = kind == "genesis"
    return {
        "v": 1, "kind": kind, "thread_id": _ID_A, "message_id": _ID_B,
        "prev": contract_open.GENESIS_PREV if genesis else _PREV,
        "expected_state": contract_open.GENESIS_EXPECTED_STATE if genesis else "c" * 64,
        "from": "operator-a", "roster": "d" * 64,
        "scrub": {"rules": "e" * 64, "blocked": 0, "redacted": 0},
        "ts": "2026-01-01T00:00:00Z", "payload": payload,
    }


def _case_schema_nine_kinds_ok() -> None:
    """9종 각각 정상 1건이 통과한다 — 그리고 픽스처가 표 전건을 덮는다."""
    from agora import schema
    table = _payload_table()
    if set(table) != set(contract_open.KINDS):
        raise AssertionError(
            f"픽스처가 표를 다 안 덮는다: {sorted(set(table) ^ set(contract_open.KINDS))}")
    for kind, (payload, _drop, _code) in table.items():
        try:
            schema.validate(_fake_event(kind, dict(payload)))
        except AgoraError as e:
            raise AssertionError(f"{kind} 정상건이 거부됐다: {e.to_json()}") from None


def _case_schema_missing_field_rejected() -> None:
    """9종 각각 필수 칸 1개를 빼면 계약 코드로 거부된다."""
    from agora import schema
    for kind, (payload, drop, want) in _payload_table().items():
        broken = dict(payload)
        del broken[drop]
        try:
            schema.validate(_fake_event(kind, broken))
        except AgoraError as e:
            if e.code != want:
                raise AssertionError(
                    f"{kind}.{drop} 결손: code {e.code} != {want}") from None
        else:
            raise AssertionError(f"{kind}.{drop} 결손이 통과했다")


def _case_schema_unknown_kind() -> None:
    """표(§2-2)에 없는 kind 는 거부한다. 격리 목록에 남기는 것은 reducer(S2-2)의 몫이다."""
    from agora import schema
    schema.validate(_fake_event("no-such-kind", {"body": "가짜"}))


def _case_schema_closed_rejects_extra() -> None:
    """모르는 칸은 무시가 아니라 거부다 — 이벤트 최상위·payload 양쪽에서."""
    from agora import schema
    probes = [
        ("event", lambda ev: ev.update({"extra_field": "가짜"})),
        ("payload", lambda ev: ev["payload"].update({"extra_field": "가짜"})),
    ]
    for where, poison in probes:
        ev = _fake_event("post", {"round": 1, "body": "가짜 발언"})
        poison(ev)
        try:
            schema.validate(ev)
        except AgoraError as e:
            if e.code != errors.ARGUMENT:
                raise AssertionError(f"{where} 잉여 칸: code {e.code} != 10") from None
        else:
            raise AssertionError(f"{where} 의 계약 밖 칸이 통과했다")


def _case_schema_type_mismatch() -> None:
    """칸 타입이 다르면 거부한다.

    ★두 갈래를 **따로** 잰다. 처음엔 `round: "1"` 하나로 갈음했는데, 그 값은
      타입 검사를 꺼도 **범위 검사**(라운드 표 밖)가 대신 잡아 버려 M33 변이가 살아남았다.
      = 케이스는 초록인데 재려던 그물은 안 쟀다. 그래서 **범위 검사가 없는 칸**(body)을 함께 둔다.
    """
    from agora import schema
    probes = [
        ("body 가 문자열이 아님", {"round": 1, "body": 123}),      # 타입 검사만이 잡는다
        ("round 가 문자열", {"round": "1", "body": "가짜 발언"}),   # 타입·범위 어느 쪽이든
    ]
    for label, payload in probes:
        try:
            schema.validate(_fake_event("post", payload))
        except AgoraError as e:
            if e.code != errors.ARGUMENT:
                raise AssertionError(f"{label}: code {e.code} != 10") from None
        else:
            raise AssertionError(f"{label} 이 통과했다")


def _case_schema_resolution_execution_forbidden() -> None:
    """★NFR-8 — 권고에 집행 금지 표식이 없으면 **정책** 거부(3)다.

    아고라의 결론은 언제나 권고다. 이 한 칸이 「토론 결과가 자동으로 실행되는 길」을 막는다.
    """
    from agora import schema
    schema.validate(_fake_event("resolution", {
        "summary": "가짜 요약", "dissent": [],
        "recommended_actions": [{"text": "가짜 권고"}],   # execution 없음
    }))


def _case_schema_problem_needs_envelope() -> None:
    """봉투 없는 problem 은 모양이 아니라 정책 위반이다 → 3."""
    from agora import schema
    schema.validate(_fake_event("genesis", {
        "type": "problem", "title": "가짜 제목", "body": "가짜 본문"}))


def _case_schema_problem_with_envelope_ok() -> None:
    """봉투를 붙이면 통과한다 — 위 케이스가 「problem 자체를 막는 것」이 아님을 증명한다."""
    from agora import schema
    schema.validate(_fake_event("genesis", {
        "type": "problem", "title": "가짜 제목", "body": "가짜 본문",
        "envelope": _fake_envelope()}))


def _case_schema_genesis_prev_contract() -> None:
    """genesis 만 `prev=genesis`·`expected_state=""` 를 쓴다(K-4) — 양방향으로 잰다."""
    from agora import schema
    probes = [
        ("genesis 가 계약값을 안 씀",
         lambda: schema.validate({**_fake_event("genesis", {
             "type": "debate", "title": "가짜", "body": "가짜"}), "prev": _PREV})),
        ("genesis 가 아닌데 prev=genesis",
         lambda: schema.validate({**_fake_event("close", {"reason": "solved"}),
                                  "prev": contract_open.GENESIS_PREV})),
    ]
    for label, probe in probes:
        try:
            probe()
        except AgoraError as e:
            if e.code != errors.ARGUMENT:
                raise AssertionError(f"{label}: code {e.code} != 10") from None
        else:
            raise AssertionError(f"{label} 이 통과했다")


def _case_schema_table_matches_contract() -> None:
    """스키마 검사기 표와 계약 kind 목록이 같아야 한다 — 갈라지면 그 자체가 결함이다."""
    from agora import schema
    if set(schema._PAYLOAD_CHECKS) != set(contract_open.KINDS):
        raise AssertionError(
            f"불일치: {sorted(set(schema._PAYLOAD_CHECKS) ^ set(contract_open.KINDS))}")


# ── S2-2 reducer 1단 — 검증 파이프·격리 ─────────────────────────────────────
# ★여기서 재는 것은 「무엇을 상태 계산에 넣어도 되는가」 하나다.
#   정렬·경합(S2-3)·전이(S2-4)는 아직 없다 — 그 경계를 케이스 이름에도 남긴다.

_T1 = "1" * 32          # 이 스레드
_T2 = "2" * 32          # 남의 스레드


def _r2_event(kind: str, payload: dict[str, Any], message_id: str, *,
              thread_id: str = _T1, prev: str | None = None,
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    genesis = kind == "genesis"
    ev: dict[str, Any] = {
        "v": 1, "kind": kind, "thread_id": thread_id, "message_id": message_id,
        "prev": contract_open.GENESIS_PREV if genesis else (prev or "b" * 64),
        "expected_state": contract_open.GENESIS_EXPECTED_STATE if genesis else "c" * 64,
        "from": "operator-a", "roster": "d" * 64,
        "scrub": {"rules": "e" * 64, "blocked": 0, "redacted": 0},
        "ts": "2026-01-01T00:00:00Z", "payload": payload,
    }
    if extra:
        ev.update(extra)
    return ev


def _r2_genesis(mid: str = "a" * 32, thread_id: str = _T1) -> dict[str, Any]:
    return _r2_event("genesis", {"type": "debate", "title": "가짜 제목",
                                 "body": "가짜 발제", "chair": "operator-a"},
                     mid, thread_id=thread_id)


def _r2_post(mid: str, body: str = "가짜 발언", thread_id: str = _T1) -> dict[str, Any]:
    return _r2_event("post", {"round": 1, "body": body}, mid, thread_id=thread_id)


def _r2_signed(event: dict[str, Any]) -> str:
    """서명기를 거쳐 운반층 게시물 본문을 만든다(정상 경로 전체를 탄다).

    ★키는 `from` 에 맞춰 고른다. 남의 이름으로 서명하면 명부 검증에서 걸려
      **전이 단계까지 오지도 못한다** — 권한을 재려던 케이스가 서명에서 죽는다(실제로 그랬다).
    """
    from agora.event import render_post
    from agora.sign import sign_event
    f = _fixtures()
    key = f["key_b"] if event["from"] == "operator-b" else f["key_a"]
    res = _with_key(key, lambda: sign_event(event))
    return render_post(event, res["signature"])


def _r2_store(*posts: str, thread_id: str = _T1) -> Any:
    from agora.store_mock import MockStore
    s = MockStore()
    for i, body in enumerate(posts):
        s.inject_raw(thread_id=thread_id, body=body,
                     created_at=f"2026-01-01T00:00:{i:02d}Z")
    return s


def _r2_collect(store: Any, thread_id: str = _T1, **kw: Any) -> dict[str, Any]:
    from agora import reducer
    f = _fixtures()
    return reducer.collect(store=store, thread_id=thread_id,
                           allowed_signers_path=f["roster_ab"], **kw)


def _r2_reasons(out: dict[str, Any]) -> list[str]:
    return [q["reason"] for q in out["quarantined"]]


def _case_reducer_valid_pass_through() -> None:
    """정상 3건은 전건 유효 · 격리 0 — 그물이 정상건을 잡지 않는다는 대조군."""
    out = _r2_collect(_r2_store(
        _r2_signed(_r2_genesis()),
        _r2_signed(_r2_post("b" * 32)),
        _r2_signed(_r2_post("c" * 32, "또 다른 가짜 발언")),
    ))
    if len(out["valid"]) != 3 or out["quarantined"]:
        raise AssertionError(f"정상 3건: valid={len(out['valid'])} "
                             f"quarantined={_r2_reasons(out)}")


def _case_reducer_unsigned_injection() -> None:
    """서명 없는 이벤트를 운반층에 직접 주입 — 상태 무반영 + 격리 1건(AC ①)."""
    from agora.event import render_post
    out = _r2_collect(_r2_store(
        _r2_signed(_r2_genesis()),
        render_post(_r2_post("b" * 32), None),      # 서명 없음 = 웹에서 붙여넣은 글
    ))
    if len(out["valid"]) != 1:
        raise AssertionError(f"무서명이 유효로 셌다: valid={len(out['valid'])}")
    if _r2_reasons(out) != ["signature"]:
        raise AssertionError(f"격리 사유가 다르다: {out['quarantined']}")


def _case_reducer_foreign_thread_event() -> None:
    """다른 thread_id 의 **유효 서명** 이벤트를 이 스레드에 붙여넣기 → 무효(AC ②)."""
    out = _r2_collect(_r2_store(
        _r2_signed(_r2_genesis()),
        _r2_signed(_r2_post("b" * 32, thread_id=_T2)),   # 서명은 멀쩡하다
    ))
    if len(out["valid"]) != 1 or _r2_reasons(out) != ["thread_mismatch"]:
        raise AssertionError(f"남의 스레드 이벤트: valid={len(out['valid'])} "
                             f"quarantined={out['quarantined']}")


def _case_reducer_replay_rejected() -> None:
    """같은 `(from, message_id)` 재게시 → 뒤엣것만 격리(§2-1 replay 방지).

    ★어느 쪽이 남는지도 잰다. 「하나만 남았다」로 만족하면 노드마다 다른 쪽이 남아도 초록이다.
    """
    from agora.store_mock import MockStore
    body = _r2_signed(_r2_post("b" * 32))
    store = MockStore()
    store.inject_raw(thread_id=_T1, body=_r2_signed(_r2_genesis()),
                     created_at="2026-01-01T00:00:00Z")
    # ★운반층이 **넣은 순서와 다른 시각**을 갖게 둔다. 페이지가 오는 순서는 우리가 못 정한다 —
    #   나중에 만들어진 글이 먼저 실려 올 수 있다. 넣은 순서에 기대면 노드마다 다른 쪽이 살아남는다.
    store.inject_raw(thread_id=_T1, body=body, created_at="2026-01-01T00:00:09Z")
    store.inject_raw(thread_id=_T1, body=body, created_at="2026-01-01T00:00:02Z")
    out = _r2_collect(store)
    if len(out["valid"]) != 2 or _r2_reasons(out) != ["replay"]:
        raise AssertionError(f"재게시: valid={len(out['valid'])} "
                             f"quarantined={out['quarantined']}")
    survivor = [v for v in out["valid"] if v["message_id"] == "b" * 32][0]
    if survivor["created_at"] != "2026-01-01T00:00:02Z":
        raise AssertionError(f"먼저 온 것이 아니라 {survivor['created_at']} 이 살아남았다 "
                             "— 운반층이 실어 준 순서를 그대로 믿었다")


def _case_reducer_schema_violation_quarantined() -> None:
    """서명은 유효한데 계약 밖인 이벤트 → 격리(서명기는 payload 스키마를 안 본다)."""
    bad = _r2_event("post", {"round": 1, "body": "가짜 발언"}, "b" * 32,
                    extra={"sneaky": "계약에 없는 칸"})
    out = _r2_collect(_r2_store(_r2_signed(_r2_genesis()), _r2_signed(bad)))
    if len(out["valid"]) != 1 or _r2_reasons(out) != ["schema"]:
        raise AssertionError(f"스키마 위반: valid={len(out['valid'])} "
                             f"quarantined={out['quarantined']}")


def _case_reducer_web_comment_quarantined() -> None:
    """사람이 웹에서 그냥 쓴 댓글 → 격리(unparseable) · 상태 무반영."""
    out = _r2_collect(_r2_store(
        _r2_signed(_r2_genesis()),
        "이건 그냥 사람이 웹에서 남긴 댓글입니다. 서식이 아닙니다.",
    ))
    if len(out["valid"]) != 1 or _r2_reasons(out) != ["unparseable"]:
        raise AssertionError(f"웹 댓글: valid={len(out['valid'])} "
                             f"quarantined={out['quarantined']}")


def _case_reducer_quarantine_hidden_by_default() -> None:
    """격리는 기본 출력에 **안 보이고** audit 에서만 보인다(AC ③ · §3-1)."""
    from agora import reducer
    from agora.event import render_post
    out = _r2_collect(_r2_store(_r2_signed(_r2_genesis()),
                                render_post(_r2_post("b" * 32), None)))
    plain = reducer.read_view(out, state="open")
    audited = reducer.read_view(out, state="open", audit=True)
    if "quarantined" in plain:
        raise AssertionError("기본 출력에 격리가 보인다")
    if len(audited.get("quarantined") or []) != 1:
        raise AssertionError(f"audit 에 격리가 없다: {audited}")
    if len(plain["events"]) != 1:
        raise AssertionError("기본 출력의 이벤트 수가 유효건과 다르다")


def _case_reducer_quarantine_does_not_delete() -> None:
    """격리는 **표시**다 — 운반층 원본도, 수집 결과도 그대로 남는다(삭제 0)."""
    store = _r2_store(_r2_signed(_r2_genesis()),
                      "웹에서 쓴 댓글", "또 다른 웹 댓글")
    before = len(store.fetch(thread_id=_T1, limit=1000)["items"])
    out = _r2_collect(store)
    after = len(store.fetch(thread_id=_T1, limit=1000)["items"])
    if before != 3 or after != 3:
        raise AssertionError(f"운반층 건수가 변했다: {before} → {after}")
    if out["fetched"] != 3 or len(out["quarantined"]) != 2:
        raise AssertionError(f"수집 계수 불일치: {out['fetched']} / "
                             f"{len(out['quarantined'])}")


def _case_reducer_paginates_and_order_independent() -> None:
    """페이지 경계를 넘어 전건을 모으고, 운반층이 순서를 흔들어도 같은 결과를 낸다.

    ★한 페이지만 읽는 결손은 화면상 정상으로 보이고 상태만 틀린다 — 그래서 따로 잰다.
    """
    posts = [_r2_signed(_r2_genesis())] + [
        _r2_signed(_r2_post(f"{i:032x}")) for i in range(1, 6)
    ]
    store = _r2_store(*posts)
    store.shuffle(seed=20260825)
    out = _r2_collect(store, limit=2)      # 6건을 2건씩 = 페이지 3장
    if out["fetched"] != 6 or len(out["valid"]) != 6:
        raise AssertionError(f"전건 수집 실패: fetched={out['fetched']} "
                             f"valid={len(out['valid'])}")
    ids = [v["message_id"] for v in out["valid"]]
    if ids != sorted(ids, key=lambda m: [v["created_at"] for v in out["valid"]
                                         if v["message_id"] == m][0]):
        raise AssertionError("수집 순서가 createdAt 순이 아니다")


# ── S2-3 reducer 2단 — 정렬·경합 ────────────────────────────────────────────
# ★경합에서 **진 것**과 **자격이 없는 것**은 다른 사건이다. 이 절의 케이스는
#   그 둘이 끝까지 다른 목록에 남는지도 함께 잰다.

def _r3_store(items: list[tuple[str, str]]) -> Any:
    """(본문, createdAt) 목록을 그 순서대로 운반층에 넣는다 — 시각과 순서를 따로 준다."""
    from agora.store_mock import MockStore
    s = MockStore()
    for body, created in items:
        s.inject_raw(thread_id=_T1, body=body, created_at=created)
    return s


def _r3_race(n: int, *, same_time: bool = False) -> dict[str, Any]:
    """같은 `prev` 를 가진 post 를 n 건 만들어 넣고 수집·정렬까지 마친다."""
    from agora import reducer
    from agora.event import event_hash
    g = _r2_genesis()
    ghash = event_hash(g)
    items = [(_r2_signed(g), "2026-01-01T00:00:00Z")]
    for i in range(n):
        post = _r2_event("post", {"round": 1, "body": f"경합 발언 {i}"},
                         f"{i + 1:032x}", prev=ghash)
        created = "2026-01-01T00:00:05Z" if same_time else f"2026-01-01T00:00:{i + 5:02d}Z"
        items.append((_r2_signed(post), created))
    return reducer.order(_r2_collect(_r3_store(items)))


def _case_reducer_race_two_one_winner() -> None:
    """같은 prev 2건 → 승자 1(§8 픽스처)."""
    out = _r3_race(2)
    if len(out["chain"]) != 2 or len(out["stale"]) != 1:
        raise AssertionError(f"경합 2건: chain={len(out['chain'])} stale={out['stale']}")
    if out["stale"][0]["reason"] != "lost_race":
        raise AssertionError(f"사유가 다르다: {out['stale'][0]}")
    if out["chain"][1]["created_at"] != "2026-01-01T00:00:05Z":
        raise AssertionError("이르게 온 쪽이 이기지 않았다")


def _case_reducer_race_three_two_stale() -> None:
    """같은 prev 3건 → 승자 1 · stale 2."""
    out = _r3_race(3)
    if len(out["chain"]) != 2 or len(out["stale"]) != 2:
        raise AssertionError(f"경합 3건: chain={len(out['chain'])} stale={len(out['stale'])}")
    winners = {s["winner_node_id"] for s in out["stale"]}
    if winners != {out["chain"][1]["node_id"]}:
        raise AssertionError(f"진 쪽이 가리키는 승자가 사슬의 승자와 다르다: {winners}")


def _case_reducer_race_tie_is_deterministic() -> None:
    """createdAt 동률 → node_id 사전순 · 같은 입력을 100번 섞어도 같은 승자(AC ②).

    ★수집을 100번 다시 하지 않고 **정렬만** 100번 돌린다. 재는 것이 정렬의 결정론이기 때문이다
      (서명 검증을 100번 돌리면 몇 분이 든다 — 느린 하네스는 안전하지도 않다).
    """
    import random
    from agora import reducer
    from agora.event import event_hash
    g = _r2_genesis()
    ghash = event_hash(g)
    items = [(_r2_signed(g), "2026-01-01T00:00:00Z")]
    for i in range(3):
        items.append((_r2_signed(_r2_event("post", {"round": 1, "body": f"동시 발언 {i}"},
                                           f"{i + 1:032x}", prev=ghash)),
                      "2026-01-01T00:00:05Z"))          # ★셋 다 같은 시각
    collected = _r2_collect(_r3_store(items))
    expected = min((v["node_id"] for v in collected["valid"] if v["kind"] == "post"))
    rng = random.Random(20260825)
    for _ in range(100):
        shuffled = dict(collected)
        shuffled["valid"] = list(collected["valid"])
        rng.shuffle(shuffled["valid"])
        out = reducer.order(shuffled)
        if len(out["chain"]) != 2:
            raise AssertionError(f"사슬 길이가 흔들린다: {len(out['chain'])}")
        if out["chain"][1]["node_id"] != expected:
            raise AssertionError(
                f"승자가 바뀐다: {out['chain'][1]['node_id']} != {expected} "
                "— 목록에 담긴 순서가 승패를 정하고 있다")


def _case_reducer_loser_descendant_unreachable() -> None:
    """진 이벤트를 `prev` 로 가리키는 글은 사슬에 못 붙는다 → unreachable.

    ★이것을 안 가르면 진 쪽 가지가 사슬에 조용히 이어붙는다.
    """
    from agora import reducer
    from agora.event import event_hash
    g = _r2_genesis()
    ghash = event_hash(g)
    winner = _r2_event("post", {"round": 1, "body": "이긴 발언"}, "1" * 32, prev=ghash)
    loser = _r2_event("post", {"round": 1, "body": "진 발언"}, "2" * 32, prev=ghash)
    child = _r2_event("post", {"round": 1, "body": "진 쪽에 붙은 발언"}, "3" * 32,
                      prev=event_hash(loser))
    out = reducer.order(_r2_collect(_r3_store([
        (_r2_signed(g), "2026-01-01T00:00:00Z"),
        (_r2_signed(winner), "2026-01-01T00:00:05Z"),
        (_r2_signed(loser), "2026-01-01T00:00:06Z"),
        (_r2_signed(child), "2026-01-01T00:00:07Z"),
    ])))
    if len(out["chain"]) != 2:
        raise AssertionError(f"사슬에 진 쪽 가지가 붙었다: {len(out['chain'])}")
    reasons = sorted(s["reason"] for s in out["stale"])
    if reasons != ["lost_race", "unreachable"]:
        raise AssertionError(f"사유 구성이 다르다: {out['stale']}")


def _case_reducer_stale_is_not_quarantine() -> None:
    """진 것과 자격 없는 것은 **끝까지 다른 목록**이다.

    같은 묶음에 경합 1건과 무서명 1건을 함께 넣고, 서로의 목록에 섞이지 않는지 본다.
    """
    from agora import reducer
    from agora.event import event_hash, render_post
    g = _r2_genesis()
    ghash = event_hash(g)
    out = reducer.order(_r2_collect(_r3_store([
        (_r2_signed(g), "2026-01-01T00:00:00Z"),
        (_r2_signed(_r2_event("post", {"round": 1, "body": "이긴 발언"}, "1" * 32,
                              prev=ghash)), "2026-01-01T00:00:05Z"),
        (_r2_signed(_r2_event("post", {"round": 1, "body": "진 발언"}, "2" * 32,
                              prev=ghash)), "2026-01-01T00:00:06Z"),
        (render_post(_r2_event("post", {"round": 1, "body": "무서명 발언"}, "3" * 32,
                               prev=ghash), None), "2026-01-01T00:00:07Z"),
    ])))
    if [s["reason"] for s in out["stale"]] != ["lost_race"]:
        raise AssertionError(f"경합 목록에 다른 것이 섞였다: {out['stale']}")
    if [q["reason"] for q in out["quarantined"]] != ["signature"]:
        raise AssertionError(f"격리 목록이 변했다: {out['quarantined']}")
    if len(out["chain"]) != 2:
        raise AssertionError(f"사슬 길이: {len(out['chain'])}")


def _case_reducer_no_genesis_no_chain() -> None:
    """genesis 가 없으면 사슬은 비고, 나머지는 전부 닿지 않는 것이 된다.

    ★빈 사슬을 「정상 0건」으로 조용히 넘기면, genesis 가 격리된 스레드가 **깨끗한 빈 스레드**로 보인다.
    """
    from agora import reducer
    from agora.event import event_hash
    g = _r2_genesis()
    ghash = event_hash(g)
    out = reducer.order(_r2_collect(_r3_store([
        (_r2_signed(_r2_event("post", {"round": 1, "body": "홀로 남은 발언"}, "1" * 32,
                              prev=ghash)), "2026-01-01T00:00:05Z"),
    ])))
    if out["chain"]:
        raise AssertionError(f"genesis 없이 사슬이 생겼다: {out['chain']}")
    if [s["reason"] for s in out["stale"]] != ["unreachable"]:
        raise AssertionError(f"사유가 다르다: {out['stale']}")


# ── S2-4 유형별 전이표 ──────────────────────────────────────────────────────
# ★사슬 하나를 만들어 상태까지 계산하는 픽스처를 공용으로 둔다.
#   각 케이스는 「그 사슬에 이 이벤트를 더하면 어떻게 되는가」 하나만 묻는다.

def _r4_chain(gtype: str, steps: list[tuple[str, dict[str, Any], str]], *,
              operators: frozenset[str] = frozenset()) -> dict[str, Any]:
    """(kind, payload, from) 목록을 앞 이벤트에 이어 붙여 사슬을 만들고 상태까지 계산한다.

    ★`prev` 를 실제 해시로 잇는다 — 잇는 시늉만 하면 S2-3 의 사슬 규칙이 이 픽스처를 걸러 버린다.
    """
    from agora import reducer
    from agora.event import event_hash
    payload: dict[str, Any] = {"type": gtype, "title": "가짜 제목", "body": "가짜 발제",
                               "chair": "operator-a"}
    if gtype in ("problem", "knowhow"):
        payload["envelope"] = _fake_envelope()
    g = _r2_event("genesis", payload, "a" * 32)
    items = [(_r2_signed(g), "2026-01-01T00:00:00Z")]
    prev = event_hash(g)
    for i, (kind, pl, who) in enumerate(steps):
        ev = _r2_event(kind, pl, f"{i + 1:032x}", prev=prev)
        ev["from"] = who
        items.append((_r2_signed(ev), f"2026-01-01T00:01:{i:02d}Z"))
        prev = event_hash(ev)
    return reducer.apply(reducer.order(_r2_collect(_r3_store(items))),
                         operators=operators)


def _r4_reasons(out: dict[str, Any]) -> list[str]:
    return [q["reason"] for q in out["quarantined"] if q.get("stage") == "transition"]


def _case_debate_full_course() -> None:
    """debate 정상 완주: r0 → r1 → r2(반론) → r3 → resolved → closed."""
    out = _r4_chain("debate", [
        ("advance", {"from_round": 0, "to_round": 1}, "operator-a"),
        ("post", {"round": 1, "body": "1라운드 발언"}, "operator-a"),
        ("advance", {"from_round": 1, "to_round": 2}, "operator-a"),
        ("post", {"round": 2, "body": "2라운드 반론",
                  "counter": [{"target_message_id": "b" * 32, "point": "가짜 반론"}]},
         "operator-a"),
        ("advance", {"from_round": 2, "to_round": 3}, "operator-a"),
        ("resolution", {"summary": "가짜 요약", "dissent": [],
                        "recommended_actions": [{"text": "가짜 권고",
                                                 "execution": "forbidden"}]},
         "operator-a"),
        ("close", {"reason": "solved"}, "operator-a"),
    ])
    if out["state"] != "closed" or _r4_reasons(out):
        raise AssertionError(f"정상 완주: state={out['state']} 거부={_r4_reasons(out)}")


def _case_debate_non_chair_advance() -> None:
    """비의장의 advance → 무효(사유 permission) · 라운드 불변."""
    out = _r4_chain("debate", [
        ("advance", {"from_round": 0, "to_round": 1}, "operator-b"),   # 의장이 아니다
    ])
    if out["round"] != 0 or _r4_reasons(out) != ["permission"]:
        raise AssertionError(f"비의장 advance: round={out['round']} "
                             f"거부={_r4_reasons(out)}")


def _case_write_path_non_chair_is_code5() -> None:
    """쓰기 경로에서는 같은 규칙이 **code 5** 로 나간다(§4 · §8 FR-4)."""
    from agora import reducer
    reducer.require_chair({"chair": "operator-a"}, "operator-b")


def _case_write_path_non_requester_is_code5() -> None:
    """해결 표시는 요청자만 — 쓰기 경로 code 5(§8 FR-5)."""
    from agora import reducer
    reducer.require_requester({"requester": "operator-a"}, "operator-b")


def _case_write_path_stale_state_is_code9() -> None:
    """내가 본 상태가 지금 상태와 다르면 **code 9**(CAS) — 재시도 전에 read.

    ★코드 9 가 처음으로 실제 발생하는 자리다(그전까지는 「그 코드를 내는 경로가 없다」였다).
    """
    from agora import reducer
    out = _r4_chain("debate", [("advance", {"from_round": 0, "to_round": 1},
                                "operator-a")])
    reducer.require_state(out, "0" * 64)      # 낡은 상태 해시를 들고 왔다


def _case_debate_out_of_round_post() -> None:
    """라운드 밖 발언 → 격리(§6) · 지금 라운드의 발언만 사슬에 남는다."""
    out = _r4_chain("debate", [
        ("advance", {"from_round": 0, "to_round": 1}, "operator-a"),
        ("post", {"round": 0, "body": "지난 라운드 발언"}, "operator-a"),
    ])
    if _r4_reasons(out) != ["out_of_round"]:
        raise AssertionError(f"라운드 밖 발언: {out['quarantined']}")


def _case_debate_r2_requires_counter() -> None:
    """R2 발언에 counter[] 가 없으면 무효 — R2 는 반론 라운드다."""
    out = _r4_chain("debate", [
        ("advance", {"from_round": 0, "to_round": 1}, "operator-a"),
        ("advance", {"from_round": 1, "to_round": 2}, "operator-a"),
        ("post", {"round": 2, "body": "반론 대상 없는 발언"}, "operator-a"),
    ])
    if _r4_reasons(out) != ["counter_required"]:
        raise AssertionError(f"R2 counter: {out['quarantined']}")


def _case_advance_monotonic_only() -> None:
    """advance 는 한 칸씩만 — r1→r1 · r2→r1 · r1→r3 전건 무효(AC ①).

    ★셋 다 **모양**에서 걸린다(스키마 code 10). 「어디서 걸리든 무효면 됐다」가 아니라
      어디서 걸리는지를 적어 둔다 — 나중에 그 검사를 옮기면 이 케이스가 알려 준다.
    """
    from agora import schema
    for a, b in ((1, 1), (2, 1), (1, 3)):
        try:
            schema.validate(_fake_event("advance", {"from_round": a, "to_round": b}))
        except AgoraError as e:
            if e.code != errors.ARGUMENT:
                raise AssertionError(f"advance {a}→{b}: code {e.code} != 10") from None
        else:
            raise AssertionError(f"advance {a}→{b} 가 통과했다")


def _case_advance_from_round_must_match_now() -> None:
    """모양이 맞아도 **지금 라운드**에서 출발하지 않으면 무효(bad_transition)."""
    out = _r4_chain("debate", [
        ("advance", {"from_round": 1, "to_round": 2}, "operator-a"),   # 지금은 r0
    ])
    if out["round"] != 0 or _r4_reasons(out) != ["bad_transition"]:
        raise AssertionError(f"출발 라운드 불일치: round={out['round']} "
                             f"거부={_r4_reasons(out)}")


def _case_debate_rejects_answer_selected() -> None:
    """debate 에 answer_selected → 유형 경계 위반(AC ③)."""
    out = _r4_chain("debate", [("answer_selected", {"post_message_id": "b" * 32},
                                "operator-a")])
    if _r4_reasons(out) != ["kind_not_allowed"]:
        raise AssertionError(f"debate answer_selected: {out['quarantined']}")


def _case_knowhow_rejects_advance() -> None:
    """knowhow 에 advance → 유형 경계 위반(AC ④)."""
    out = _r4_chain("knowhow", [("advance", {"from_round": 0, "to_round": 1},
                                 "operator-a")])
    if _r4_reasons(out) != ["kind_not_allowed"]:
        raise AssertionError(f"knowhow advance: {out['quarantined']}")


def _case_problem_only_requester_solves() -> None:
    """타인의 해결 표시 → 상태 무반영 · 요청자의 것만 solved(§8 FR-5)."""
    post_id = f"{1:032x}"
    out = _r4_chain("problem", [
        ("post", {"round": 0, "body": "가짜 답변"}, "operator-b"),
        ("answer_selected", {"post_message_id": post_id}, "operator-b"),   # 타인
    ])
    if out["state"] != "open" or _r4_reasons(out) != ["permission"]:
        raise AssertionError(f"타인 해결 표시: state={out['state']} "
                             f"거부={_r4_reasons(out)}")

    out2 = _r4_chain("problem", [
        ("post", {"round": 0, "body": "가짜 답변"}, "operator-b"),
        ("answer_selected", {"post_message_id": post_id}, "operator-a"),   # 요청자
    ])
    if out2["state"] != "solved" or out2["solved_by"] != post_id:
        raise AssertionError(f"요청자 해결 표시: state={out2['state']} "
                             f"solved_by={out2['solved_by']}")


def _case_answer_target_must_exist() -> None:
    """사슬에 없는 글을 답으로 고르면 무효 — 「없는 답으로 해결됨」을 막는다."""
    out = _r4_chain("problem", [
        ("answer_selected", {"post_message_id": "f" * 32}, "operator-a"),
    ])
    if out["state"] != "open" or _r4_reasons(out) != ["unknown_target"]:
        raise AssertionError(f"없는 대상: state={out['state']} 거부={_r4_reasons(out)}")


def _case_knowhow_close_reason_limited() -> None:
    """knowhow 의 종결 사유는 superseded/archived 뿐(§6)."""
    bad = _r4_chain("knowhow", [("close", {"reason": "solved"}, "operator-a")])
    if bad["state"] != "open" or _r4_reasons(bad) != ["bad_transition"]:
        raise AssertionError(f"knowhow close(solved): {bad['quarantined']}")
    ok = _r4_chain("knowhow", [("close", {"reason": "superseded"}, "operator-a")])
    if ok["state"] != "closed":
        raise AssertionError(f"knowhow close(superseded): {ok['state']}")


def _case_events_after_close_rejected() -> None:
    """닫힌 뒤에 온 이벤트는 상태를 못 바꾼다."""
    out = _r4_chain("problem", [
        ("close", {"reason": "unresolved"}, "operator-a"),
        ("post", {"round": 0, "body": "닫힌 뒤 발언"}, "operator-a"),
    ])
    if out["state"] != "closed" or _r4_reasons(out) != ["after_close"]:
        raise AssertionError(f"종결 후 이벤트: state={out['state']} "
                             f"거부={_r4_reasons(out)}")


def _case_no_silent_deferrals() -> None:
    """받는 kind 는 전부 **실제 전이**를 갖는다 — 보류 목록은 비어 있어야 한다.

    ★S2-4 에서 이 케이스는 정반대를 쟀다(delegate_chair 가 보류 목록에 이름을 남기는지).
      S2-5 가 그 둘에 전이를 줬으므로 이제 비어 있는 것이 정상이다.
      **케이스를 지우지 않고 방향을 뒤집어 둔다** — 다음에 또 「받되 계산 안 하는」 kind 가
      생기면 여기서 걸린다. 지워 버리면 그 자리를 지키던 눈이 함께 사라진다.
    """
    out = _r4_chain("debate", [("delegate_chair", {"new_chair": "operator-b"},
                                "operator-a")])
    if out["deferred"]:
        raise AssertionError(f"조용히 보류된 kind 가 있다: {out['deferred']}")
    if out["chair"] != "operator-b":
        raise AssertionError(f"승계가 상태에 반영되지 않았다: chair={out['chair']}")


def _case_state_hash_is_deterministic_and_sensitive() -> None:
    """같은 사슬 → 같은 상태 해시 · 한 걸음 더 가면 달라진다(CAS 의 전제)."""
    steps = [("advance", {"from_round": 0, "to_round": 1}, "operator-a")]
    a = _r4_chain("debate", steps)
    b = _r4_chain("debate", steps)
    if a["state_hash"] != b["state_hash"]:
        raise AssertionError("같은 사슬이 다른 상태 해시를 냈다")
    c = _r4_chain("debate", steps + [("post", {"round": 1, "body": "한 걸음 더"},
                                      "operator-a")])
    if c["state_hash"] == a["state_hash"]:
        raise AssertionError("사슬이 자랐는데 상태 해시가 그대로다")


# ── S2-5 마감·만료·의장 승계 ────────────────────────────────────────────────
# ★시각은 픽스처가 **주입**한다. 프로세스 현재 시각을 읽는 판정은 재현할 수 없고,
#   재현할 수 없는 판정은 노드마다 다른 사실을 만든다.

_DUE = "2026-02-01T00:00:00Z"
_BEFORE = "2026-02-01T00:04:59Z"    # 마감 + 299초 — 유예 안
_AFTER = "2026-02-01T00:05:01Z"     # 마감 + 301초 — 유예 밖


def _r5_debate(steps: list[tuple[str, dict[str, Any], str]], *,
               now: str | None = None, deadlines: dict[str, str] | None = None,
               operators: frozenset[str] = frozenset()) -> dict[str, Any]:
    from agora import reducer
    from agora.event import event_hash
    payload: dict[str, Any] = {"type": "debate", "title": "가짜 제목",
                               "body": "가짜 발제", "chair": "operator-a",
                               "deadlines": deadlines or {"r0": _DUE, "r1": _DUE}}
    g = _r2_event("genesis", payload, "a" * 32)
    items = [(_r2_signed(g), "2026-01-01T00:00:00Z")]
    prev = event_hash(g)
    for i, (kind, pl, who) in enumerate(steps):
        ev = _r2_event(kind, pl, f"{i + 1:032x}", prev=prev)
        ev["from"] = who
        items.append((_r2_signed(ev), f"2026-01-01T00:01:{i:02d}Z"))
        prev = event_hash(ev)
    return reducer.apply(reducer.order(_r2_collect(_r3_store(items))),
                         operators=operators, now=now)


def _case_deadline_expires_without_advance() -> None:
    """마감 경과 + advance 부재 → expired(자동 · 이벤트 없이 시간으로)."""
    out = _r5_debate([], now=_AFTER)
    if out["state"] != "expired":
        raise AssertionError(f"만료되지 않았다: {out['state']}")


def _case_deadline_grace_window() -> None:
    """유예(300초) 안에서는 만료가 아니다 — 시계가 몇 초 빠른 노드가 혼자 앞서 선언하지 못하게."""
    out = _r5_debate([], now=_BEFORE)
    if out["state"] != "r0":
        raise AssertionError(f"유예 안인데 만료됐다: {out['state']}")


def _case_event_beats_time() -> None:
    """유효 advance 가 있으면 그 라운드의 만료 판정보다 **언제나** 우선한다(R-3).

    ★advance 가 마감보다 늦게 왔어도 그렇다. 시간 전이는 이벤트가 **없을 때만** 발동하는 보조 규칙이다.
    """
    out = _r5_debate([("advance", {"from_round": 0, "to_round": 1}, "operator-a")],
                     now=_AFTER, deadlines={"r0": _DUE, "r1": "2026-03-01T00:00:00Z"})
    if out["state"] != "r1" or out["round"] != 1:
        raise AssertionError(f"이벤트가 시간에 졌다: {out['state']}")


def _case_expired_verdict_is_deterministic() -> None:
    """같은 이벤트 묶음 + 같은 시각 → 언제 몇 번을 돌려도 같은 판정(AC ①)."""
    seen = {_r5_debate([], now=_AFTER)["state"] for _ in range(5)}
    if seen != {"expired"}:
        raise AssertionError(f"판정이 흔들린다: {seen}")
    seen2 = {_r5_debate([], now=_BEFORE)["state"] for _ in range(5)}
    if seen2 != {"r0"}:
        raise AssertionError(f"판정이 흔들린다: {seen2}")


def _case_chair_is_latest_delegate() -> None:
    """의장 = genesis.chair 또는 **최신 유효** delegate_chair(AC ③).

    ★두 번 넘기면 마지막 사람이 의장이다. 첫 위임을 붙잡으면 승계가 한 번밖에 못 일어난다.
    """
    out = _r5_debate([
        ("delegate_chair", {"new_chair": "operator-b"}, "operator-a"),
        ("delegate_chair", {"new_chair": "operator-a"}, "operator-b"),
    ])
    if out["chair"] != "operator-a":
        raise AssertionError(f"최신 위임이 반영되지 않았다: chair={out['chair']}")


def _case_non_chair_cannot_delegate() -> None:
    """의장이 아닌 사람의 위임 → 무효(사유 permission) · 의장 불변."""
    out = _r5_debate([("delegate_chair", {"new_chair": "operator-b"}, "operator-b")])
    if out["chair"] != "operator-a" or _r4_reasons(out) != ["permission"]:
        raise AssertionError(f"비의장 위임: chair={out['chair']} 거부={_r4_reasons(out)}")


def _case_expired_resumes_by_advance_not_by_delegate() -> None:
    """만료 재개는 **advance** 가 한다 — 위임만으로는 풀리지 않는다(§8 마감 경과 → 재개).

    ★둘을 뭉치면 「새 의장이 왔으니 됐다」로 끝나고, 라운드는 그대로 멈춰 있는다.
    """
    only_delegate = _r5_debate(
        [("delegate_chair", {"new_chair": "operator-b"}, "operator-a")], now=_AFTER)
    if only_delegate["state"] != "expired" or only_delegate["chair"] != "operator-b":
        raise AssertionError(f"위임만: state={only_delegate['state']} "
                             f"chair={only_delegate['chair']}")

    resumed = _r5_debate([
        ("delegate_chair", {"new_chair": "operator-b"}, "operator-a"),
        ("advance", {"from_round": 0, "to_round": 1}, "operator-b"),   # 새 의장이 재개
    ], now=_AFTER, deadlines={"r0": _DUE, "r1": "2026-03-01T00:00:00Z"})
    if resumed["state"] != "r1" or resumed["chair"] != "operator-b":
        raise AssertionError(f"재개 실패: state={resumed['state']} "
                             f"chair={resumed['chair']}")


def _case_abort_requires_operator() -> None:
    """운영자 명부에 없는 키의 abort → 무효(AC ②) · 명부에 있으면 aborted 로 닫힌다.

    ★명부에서 그 이름을 지우면 같은 키의 abort 가 죽는지도 함께 본다 —
      「운영자가 누구인가」가 코드가 아니라 **명부**에서 온다는 뜻이다.
    """
    out = _r5_debate([("abort", {"reason": "가짜 중단 사유"}, "operator-b")],
                     operators=frozenset({"operator-a"}))      # b 는 운영자가 아니다
    if out["state"] == "closed" or _r4_reasons(out) != ["permission"]:
        raise AssertionError(f"비운영자 abort: state={out['state']} "
                             f"거부={_r4_reasons(out)}")

    ok = _r5_debate([("abort", {"reason": "가짜 중단 사유"}, "operator-b")],
                    operators=frozenset({"operator-a", "operator-b"}))
    if ok["state"] != "closed" or ok["close_reason"] != "aborted":
        raise AssertionError(f"운영자 abort: state={ok['state']} "
                             f"reason={ok.get('close_reason')}")


def _case_deadlines_schema_closed() -> None:
    """마감 표의 키는 라운드 이름뿐이다 — 없는 라운드에 건 마감은 아무도 안 보는 약속이다."""
    from agora import schema
    bad = _fake_event("genesis", {"type": "debate", "title": "가짜", "body": "가짜",
                                  "deadlines": {"r4": _DUE}})
    try:
        schema.validate(bad)
    except AgoraError as e:
        if e.code != errors.ARGUMENT:
            raise AssertionError(f"code {e.code} != 10") from None
    else:
        raise AssertionError("없는 라운드의 마감이 통과했다")


# ── S2-5 후속: 운영자 위임(만료 한정) ───────────────────────────────────────

def _case_operator_delegate_only_when_expired() -> None:
    """운영자는 **만료된 동안만** 의장을 대신 넘길 수 있다(운영자 결정 2026-08-25).

    ★조건이 규칙의 절반이다. 조건이 없으면 운영자가 아무 때나 의장을 갈아치울 수 있어
      의장 권한이 형해화된다.
    """
    ops = frozenset({"operator-b"})
    expired_case = _r5_debate(
        [("delegate_chair", {"new_chair": "operator-b"}, "operator-b")],
        now=_AFTER, operators=ops)
    if expired_case["chair"] != "operator-b":
        raise AssertionError(f"만료 중 운영자 위임이 막혔다: {expired_case['chair']} "
                             f"거부={_r4_reasons(expired_case)}")

    live_case = _r5_debate(
        [("delegate_chair", {"new_chair": "operator-b"}, "operator-b")],
        now=_BEFORE, operators=ops)          # 아직 만료 아님
    if live_case["chair"] != "operator-a" or _r4_reasons(live_case) != ["permission"]:
        raise AssertionError(f"만료 아닌데 운영자 위임이 통과했다: "
                             f"chair={live_case['chair']} 거부={_r4_reasons(live_case)}")


# ── S2-6 프로토콜 예산 ──────────────────────────────────────────────────────
# ★AC ① 이 요구하는 것은 「**로컬 검사를 끄고**」 재는 것이다. 그래서 이 절의 픽스처는
#   사전 검사를 아예 부르지 않고 저장층에 직접 넣는다 — reducer 만으로 막히는지 본다.

def _case_budget_local_precheck_is_code3() -> None:
    """로컬 사전 검사 — 보내기 전에 code 3 으로 막는다(§8 FR-10)."""
    from agora import protocol
    protocol.precheck(body="가짜 발언", used={"posts": 2, "chars": 0},
                      budget={"posts_per_round": 2, "max_chars_per_round": 6000})


def _case_budget_reducer_rejects_without_precheck() -> None:
    """사전 검사를 **끄고** 3번째 발언을 저장층에 직접 주입 → reducer 가 무효 처리(AC ①).

    ★로컬 검사에 의존하지 않는다는 증명이다. 저장층은 비신뢰다 —
      검사를 지운 클라이언트가 언제든 있을 수 있다.
    """
    out = _r5_debate([
        ("post", {"round": 0, "body": "첫 발언"}, "operator-a"),
        ("post", {"round": 0, "body": "둘째 발언"}, "operator-a"),
        ("post", {"round": 0, "body": "셋째 발언"}, "operator-a"),
    ], deadlines={})
    if _r4_reasons(out) != ["budget_exceeded"]:
        raise AssertionError(f"3번째 발언: 거부={_r4_reasons(out)}")
    if out["usage"]["operator-a@r0"]["posts"] != 2:
        raise AssertionError(f"계수가 다르다: {out['usage']}")


def _case_budget_comes_from_settings() -> None:
    """상한은 설정에서 온다 — 값을 바꾸면 결과가 바뀐다(AC ② · 하드코딩 아님)."""
    from agora import reducer
    from agora.event import event_hash
    payload = {"type": "debate", "title": "가짜 제목", "body": "가짜 발제",
               "chair": "operator-a"}
    g = _r2_event("genesis", payload, "a" * 32)
    items = [(_r2_signed(g), "2026-01-01T00:00:00Z")]
    prev = event_hash(g)
    for i in range(2):
        ev = _r2_event("post", {"round": 0, "body": f"발언 {i}"}, f"{i + 1:032x}",
                       prev=prev)
        items.append((_r2_signed(ev), f"2026-01-01T00:01:{i:02d}Z"))
        prev = event_hash(ev)
    collected = _r2_collect(_r3_store(items))
    ordered = reducer.order(collected)

    two = reducer.apply(ordered, budget={"posts_per_round": 2,
                                         "max_chars_per_round": 6000})
    one = reducer.apply(ordered, budget={"posts_per_round": 1,
                                         "max_chars_per_round": 6000})
    if [q["reason"] for q in two["quarantined"] if q.get("stage") == "transition"]:
        raise AssertionError("상한 2 인데 2건이 거부됐다")
    if [q["reason"] for q in one["quarantined"] if q.get("stage") == "transition"] \
            != ["budget_exceeded"]:
        raise AssertionError("상한 1 로 낮췄는데 결과가 그대로다 — 설정을 안 읽는다")


def _case_budget_counts_chars_too() -> None:
    """글자 수 상한도 같은 규칙으로 막힌다."""
    out = _r5_debate([("post", {"round": 0, "body": "가" * 50}, "operator-a")],
                     deadlines={})
    if _r4_reasons(out):
        raise AssertionError(f"기본 상한 안인데 막혔다: {_r4_reasons(out)}")
    from agora import reducer
    from agora.event import event_hash
    g = _r2_event("genesis", {"type": "debate", "title": "가짜", "body": "가짜",
                              "chair": "operator-a"}, "a" * 32)
    ev = _r2_event("post", {"round": 0, "body": "가" * 50}, "1" * 32,
                   prev=event_hash(g))
    ordered = reducer.order(_r2_collect(_r3_store([
        (_r2_signed(g), "2026-01-01T00:00:00Z"),
        (_r2_signed(ev), "2026-01-01T00:01:00Z")])))
    tight = reducer.apply(ordered, budget={"posts_per_round": 9,
                                           "max_chars_per_round": 10})
    over = [q for q in tight["quarantined"] if q.get("stage") == "transition"]
    if [q["reason"] for q in over] != ["budget_exceeded"]:
        raise AssertionError(f"글자 상한이 안 걸린다: {tight['quarantined']}")
    if over[0]["detail"]["limit"] != "max_chars_per_round":
        raise AssertionError(f"걸린 축이 다르다: {over[0]['detail']}")


def _case_budget_not_spent_by_losers() -> None:
    """경합에서 진 글은 예산을 쓰지 않는다(R-2).

    ★안 그러면 남이 경합을 걸어 **내 예산을 태울** 수 있다.
    """
    from agora import reducer
    from agora.event import event_hash
    g = _r2_genesis()
    ghash = event_hash(g)
    winner = _r2_event("post", {"round": 0, "body": "이긴 발언"}, "1" * 32, prev=ghash)
    loser = _r2_event("post", {"round": 0, "body": "진 발언"}, "2" * 32, prev=ghash)
    second = _r2_event("post", {"round": 0, "body": "둘째 발언"}, "3" * 32,
                       prev=event_hash(winner))
    out = reducer.apply(reducer.order(_r2_collect(_r3_store([
        (_r2_signed(g), "2026-01-01T00:00:00Z"),
        (_r2_signed(winner), "2026-01-01T00:00:05Z"),
        (_r2_signed(loser), "2026-01-01T00:00:06Z"),
        (_r2_signed(second), "2026-01-01T00:00:07Z"),
    ]))), budget={"posts_per_round": 2, "max_chars_per_round": 6000})
    if _r4_reasons(out):
        raise AssertionError(f"진 글이 예산을 태웠다: {out['quarantined']}")
    if out["usage"]["operator-a@r0"]["posts"] != 2:
        raise AssertionError(f"계수: {out['usage']}")


def _case_budget_is_per_participant_and_round() -> None:
    """예산은 참가자별·라운드별이다 — 남의 발언이 내 몫을 깎지 않는다."""
    out = _r5_debate([
        ("post", {"round": 0, "body": "a 의 첫 발언"}, "operator-a"),
        ("post", {"round": 0, "body": "a 의 둘째 발언"}, "operator-a"),
        ("post", {"round": 0, "body": "b 의 첫 발언"}, "operator-b"),
    ], deadlines={})
    if _r4_reasons(out):
        raise AssertionError(f"남의 예산을 깎았다: {out['quarantined']}")
    if sorted(out["usage"]) != ["operator-a@r0", "operator-b@r0"]:
        raise AssertionError(f"계수 칸: {sorted(out['usage'])}")


def _case_budget_value_must_be_sane() -> None:
    """설정의 예산 값이 0 이상의 정수가 아니면 인자 오류(10)."""
    from agora import protocol
    protocol.load_budget({"budget": {"posts_per_round": "둘"}})


def _case_usage_field_exists(): 
    """NFR-7(K-6) — 사용량 수집 칸이 결과에 **실재**한다.

    ★토큰 단위 사용량은 코어가 잴 수 없다(토크나이저가 없다) — 도구 경계(S6-1)에서 붙는다.
      여기서 재는 것은 프로토콜이 실제로 셀 수 있는 것(발언 수·글자 수)이 남는가다.
    """
    out = _r5_debate([("post", {"round": 0, "body": "가짜 발언"}, "operator-a")],
                     deadlines={})
    if "usage" not in out or "budget" not in out:
        raise AssertionError(f"사용량·예산 칸이 없다: {sorted(out)}")
    row = out["usage"].get("operator-a@r0")
    if not row or sorted(row) != ["chars", "posts"]:
        raise AssertionError(f"사용량 칸 구성: {row}")


# ── S2-7 스레드 관계 필드(§2-1b) ────────────────────────────────────────────
# ★관계는 **연결**이지 **절차**가 아니다. 이 절의 케이스는 그 경계가 지켜지는지를 잰다.

_OTHER_THREAD = "9" * 32


def _case_relations_three_fields_ok() -> None:
    """parent · refs[] · spawn 각각 정상 1건이 통과한다(AC ①)."""
    from agora import schema
    ok = [
        ("parent", _fake_event("genesis", {
            "type": "knowhow", "title": "가짜", "body": "가짜",
            "envelope": _fake_envelope(),
            "parent": {"thread_id": _OTHER_THREAD, "message_id": "b" * 32}})),
        ("refs", _fake_event("post", {
            "round": 1, "body": "가짜 발언",
            "refs": [{"thread_id": _OTHER_THREAD, "why": "가짜 인용 사유"}]})),
        ("spawn", _fake_event("resolution", {
            "summary": "가짜 요약", "dissent": [],
            "recommended_actions": [{"text": "가짜 권고", "execution": "forbidden",
                                     "spawn": {"type": "problem",
                                               "title": "가짜 후속 제목"}}]})),
    ]
    for name, ev in ok:
        try:
            schema.validate(ev)
        except AgoraError as e:
            raise AssertionError(f"{name} 정상건이 거부됐다: {e.to_json()}") from None


def _case_relations_schema_violations() -> None:
    """세 필드 각각 스키마 위반 1건 → code 10(AC ①)."""
    from agora import schema
    bad = [
        ("parent 에 없는 칸", _fake_event("genesis", {
            "type": "knowhow", "title": "가짜", "body": "가짜",
            "envelope": _fake_envelope(),
            "parent": {"thread_id": _OTHER_THREAD, "note": "계약에 없는 칸"}})),
        ("refs 에 why 없음", _fake_event("post", {
            "round": 1, "body": "가짜 발언",
            "refs": [{"thread_id": _OTHER_THREAD}]})),
        ("spawn 유형이 debate", _fake_event("resolution", {
            "summary": "가짜 요약", "dissent": [],
            "recommended_actions": [{"text": "가짜 권고", "execution": "forbidden",
                                     "spawn": {"type": "debate", "title": "가짜"}}]})),
    ]
    for name, ev in bad:
        try:
            schema.validate(ev)
        except AgoraError as e:
            if e.code != errors.ARGUMENT:
                raise AssertionError(f"{name}: code {e.code} != 10") from None
        else:
            raise AssertionError(f"{name} 이 통과했다")


def _case_relations_do_not_change_procedure() -> None:
    """관계 필드를 더해도 **절차 상태**는 그대로다(AC ②).

    ★`state_hash` 는 달라진다 — 그 안에 사슬의 머리가 들어 있고, 관계를 더하면
      이벤트 바이트가 달라지기 때문이다(S2-4 의 CAS 결정). 그래서 재는 축은 **절차 칸**이다.
      한 값으로 두 질문에 답하려 하면 둘 중 하나는 반드시 거짓말이 된다.
      대신 머리를 뺀 나머지가 같은지까지 확인해 「달라진 것은 머리뿐」임을 못박는다.
    """
    from agora import reducer

    def build(with_relations: bool) -> dict[str, Any]:
        from agora.event import event_hash
        gp: dict[str, Any] = {"type": "debate", "title": "가짜 제목",
                              "body": "가짜 발제", "chair": "operator-a"}
        pp: dict[str, Any] = {"round": 0, "body": "가짜 발언"}
        if with_relations:
            gp["parent"] = {"thread_id": _OTHER_THREAD}
            pp["refs"] = [{"thread_id": _OTHER_THREAD, "why": "가짜 인용 사유"}]
        g = _r2_event("genesis", gp, "a" * 32)
        post = _r2_event("post", pp, "1" * 32, prev=event_hash(g))
        return reducer.apply(reducer.order(_r2_collect(_r3_store([
            (_r2_signed(g), "2026-01-01T00:00:00Z"),
            (_r2_signed(post), "2026-01-01T00:01:00Z")]))))

    plain, linked = build(False), build(True)
    if reducer.procedure_snapshot(plain) != reducer.procedure_snapshot(linked):
        raise AssertionError(f"관계가 절차를 바꿨다: "
                             f"{reducer.procedure_snapshot(plain)} != "
                             f"{reducer.procedure_snapshot(linked)}")
    if len(plain["events"]) != len(linked["events"]) or linked["quarantined"]:
        raise AssertionError("관계가 사슬·격리를 바꿨다")
    if plain["state_hash"] == linked["state_hash"]:
        raise AssertionError("사슬 바이트가 달라졌는데 상태 해시가 그대로다 — CAS 가 눈먼다")


def _case_relations_may_point_nowhere() -> None:
    """없는 스레드를 가리켜도 **거부하지 않는다** — 대신 미해소 링크로 표시한다(AC ④).

    ★거부하면 「먼저 열고 나중에 잇는다」가 불가능해진다.
    """
    from agora import reducer
    from agora.event import event_hash
    g = _r2_event("genesis", {"type": "debate", "title": "가짜", "body": "가짜",
                              "chair": "operator-a",
                              "parent": {"thread_id": _OTHER_THREAD}}, "a" * 32)
    post = _r2_event("post", {"round": 0, "body": "가짜 발언",
                              "refs": [{"thread_id": _OTHER_THREAD,
                                        "why": "가짜 인용 사유"}]},
                     "1" * 32, prev=event_hash(g))
    out = reducer.apply(reducer.order(_r2_collect(_r3_store([
        (_r2_signed(g), "2026-01-01T00:00:00Z"),
        (_r2_signed(post), "2026-01-01T00:01:00Z")]))))
    if out["quarantined"]:
        raise AssertionError(f"없는 스레드를 가리켰다고 거부했다: {out['quarantined']}")
    links = reducer.links_of(out)
    if sorted(l["role"] for l in links) != ["parent", "ref"]:
        raise AssertionError(f"링크 목록: {links}")
    if any(l["resolved"] for l in links):
        raise AssertionError("아무것도 모르는데 해소됐다고 표시했다")
    known = reducer.links_of(out, known_threads=frozenset({_OTHER_THREAD}))
    if not all(l["resolved"] for l in known):
        raise AssertionError("아는 스레드인데 미해소로 남았다")


def _case_spawn_is_proposal_only() -> None:
    """spawn 은 **제안일 뿐** — 스레드를 자동으로 여는 코드 경로가 0건이어야 한다(AC ③).

    ★부재를 증명하는 축이라 변이 대상이 없다(없는 코드는 바꿀 수 없다). 그래서 정적 검사로 잰다:
      **spawn 값을 읽는 코드가 검증기 말고는 없어야 한다.** 아무도 안 읽으면 아무도 못 움직인다.

    ★처음엔 「spawn 을 언급하는 파일에 `.append(` 가 있으면 적색」으로 짰는데,
      리스트의 `.append` 와 주석의 단어까지 걸려 **깨끗한 파일이 위반으로 떴다**.
      검사기가 고장나면 그 출력은 아무것도 증명하지 않는다 — 읽는 행위 자체를 좁혀서 잡는다.
      나중에 렌더러(S6-5)가 spawn 을 읽어야 하면 이 목록에 이름을 **일부러** 더하게 된다.
    """
    import re
    allowed = {"schema.py", "selftest.py"}      # 검증기와 이 파일만
    reads_spawn = re.compile(r"""\[\s*["']spawn["']\s*\]|\.get\(\s*["']spawn["']""")
    offenders: list[str] = []
    for dirpath, _dirs, files in os.walk(os.path.join(_ROOT, "agora")):
        for fn in files:
            if not fn.endswith(".py") or fn in allowed:
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8") as fh:
                if reads_spawn.search(fh.read()):
                    offenders.append(os.path.relpath(path, _ROOT))
    if offenders:
        raise AssertionError(f"spawn 값을 읽는 코드: {offenders}")



# ── S3-1 allowlist ──────────────────────────────────────────────────────────
# ★두 겹의 뜻이 다르다: allowlist 는 「모양이 우리 것인가」, denylist 는 「아는 위험이 있나」.
#   그래서 위반 픽스처도 **구조**로 만든다(개인정보가 아니라 첨부·이미지·HTML·멘션·URL).

_ALLOW_VIOLATIONS = (
    ("이미지", "image", "본문입니다 ![그림](x.png) 끝"),
    ("HTML", "html", "본문입니다 <div>가짜</div> 끝"),
    ("멘션", "mention", "본문입니다 @someone 보세요"),
    ("첨부", "attachment", "본문입니다 file:///어딘가/가짜.txt"),
    ("비허용 도메인", "url-domain", "본문입니다 https://not-allowed.example/a 참고"),
)


def _case_allowlist_blocks_five_kinds() -> None:
    """allowlist 위반 5종이 전건 차단된다(§8 · AC) — 그리고 **어느 규칙이** 잡았는지까지 본다.

    ★사유를 안 보면 「무엇이든 걸리기만 하면 초록」이 된다. 실제로 denylist 가 대신 잡아도
      계수는 같아지므로, 규칙 이름을 단언해야 그 그물을 쟀다고 말할 수 있다.
    """
    from agora import scrub
    for name, rule, body in _ALLOW_VIOLATIONS:
        report = scrub.check({"payload": {"body": body}})
        rules = [f["rule"] for f in report["findings"]]
        if rule not in rules:
            raise AssertionError(f"{name}: {rule} 이 안 잡혔다 — 잡힌 것={rules}")


def _case_allowlist_enforce_is_code3() -> None:
    """집행 경로에서는 code 3 으로 멈춘다(§8 첨부/@멘션/비허용 URL code 3)."""
    from agora import scrub
    scrub.enforce({"payload": {"body": "본문 @someone https://not-allowed.example/a"}})


def _case_allowlist_allows_listed_domain() -> None:
    """허용 목록에 있는 도메인은 통과한다 — 그리고 평범한 본문에 오탐이 없다(대조군).

    ★차단만 재면 「전부 차단」도 초록이다. 통과 축이 없으면 게이트가 죽었는지 알 수 없다.
    """
    from agora import scrub
    clean = [
        "평범한 한글 발언입니다. 숫자 12 와 기호 · 도 있습니다.",
        "ascii sentence with punctuation, and a dash - here.",
        "허용된 문서 링크입니다 https://docs.python.org/3/library/json.html 참고하세요.",
        "코드 이야기: 함수 이름은 canonical_bytes 이고 인자는 event 입니다.",
    ]
    for body in clean:
        report = scrub.check({"payload": {"body": body}})
        if report["blocked"]:
            raise AssertionError(f"정상문 오탐: {body[:20]}… → {report['findings']}")


def _case_allowlist_empty_domains_blocks_all_urls() -> None:
    """허용 도메인 목록을 비우면 **모든 URL 이 차단**된다(AC ① · fail-closed)."""
    import tempfile
    from agora import scrub
    with tempfile.TemporaryDirectory() as d:
        empty = os.path.join(d, "none.txt")
        with open(empty, "w", encoding="utf-8") as fh:
            fh.write("# 비어 있다\n")
        allow = scrub.load_allow(domains_path=empty)
        if allow.domains:
            raise AssertionError(f"목록이 비지 않았다: {allow.domains}")
        found = scrub.check_allow({"payload": {"body": "https://github.com/a 문서"}},
                                  allow)
        if [f["rule"] for f in found] != ["url-domain"]:
            raise AssertionError(f"빈 목록인데 URL 이 통과했다: {found}")


def _case_allowlist_missing_file_is_fail_closed() -> None:
    """allowlist 규칙 파일이 없으면 전량 차단(3) — denylist 와 같은 방향이다."""
    from agora import scrub
    scrub.load_allow(path=os.path.join(_ROOT, "config", "no-such-allowlist.json"))


def _case_allowlist_field_limits() -> None:
    """필드별 상한 — 제목은 글자 수, 로그 발췌는 **바이트**로 잰다.

    ★로그 발췌를 글자 수로 재면 한글이 3배로 들어가 4KB 약속이 깨진다.
    """
    from agora import scrub
    long_title = scrub.check({"payload": {"title": "가" * 201}})
    if [f["rule"] for f in long_title["findings"]] != ["max_chars"]:
        raise AssertionError(f"제목 상한: {long_title['findings']}")
    ok_title = scrub.check({"payload": {"title": "가" * 200}})
    if ok_title["blocked"]:
        raise AssertionError(f"상한 안 제목이 막혔다: {ok_title['findings']}")

    # 한글 1자 = UTF-8 3바이트 → 1400자면 4200바이트로 4KB 를 넘는다.
    big_log = scrub.check({"payload": {"envelope": {"log_excerpt": "가" * 1400}}})
    if [f["rule"] for f in big_log["findings"]] != ["max_bytes"]:
        raise AssertionError(f"로그 발췌 상한: {big_log['findings']}")


def _case_scrub_report_carries_both_digests() -> None:
    """보고서가 **두 겹의 digest** 를 함께 싣는다(M-11 · 수신 측 대조용)."""
    from agora import scrub
    report = scrub.check({"payload": {"body": "평범한 본문"}})
    for key in ("rules", "allow_rules", "bundle"):
        if not report.get(key) or len(report[key]) != 64:
            raise AssertionError(f"digest 칸 {key}: {report.get(key)!r}")
    if report["bundle"] in (report["rules"], report["allow_rules"]):
        raise AssertionError("묶음 digest 가 한쪽과 같다 — 두 겹을 안 묶었다")


def _case_signer_refuses_allowlist_violation() -> None:
    """서명기가 allowlist 위반을 거부한다 → 서명 없음 = 전송 없음(3)."""
    from agora.sign import sign_event
    f = _fixtures()
    ev = _r2_post("1" * 32, "본문 @someone 멘션이 들어 있다")
    _with_key(f["key_a"], lambda: sign_event(ev))

# ── S3-2 denylist v1 · rule digest ──────────────────────────────────────────
# ★픽스처 값은 **그 자리에서 난수로 짓는다**(AC ①). 이유가 둘이다:
#   ⑴ 유명 문서 예제(4111-1111-…)는 도구 기본 허용목록에 걸려 시험이 무효가 된다.
#   ⑵ 진짜처럼 생긴 값이 **저장소에 글자로 남지 않는다** — 커밋 게이트의 누출 스캔과 다투지 않는다.

def _rng():
    import random
    return random.Random(20260825)      # 씨앗 고정 — 실패가 재현돼야 고칠 수 있다


def _denylist_fixtures() -> list[tuple[str, str, str]]:
    """(범주, 기대 규칙 id, 본문) — 설계 §5 의 8범주를 덮는다."""
    import string
    rng = _rng()

    def alnum(n: int) -> str:
        return "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(n))

    def digits(n: int) -> str:
        return "".join(rng.choice(string.digits) for _ in range(n))

    return [
        ("이메일", "email", f"연락은 {alnum(7).lower()}@{alnum(6).lower()}.example 로"),
        ("국제 전화", "phone-intl", f"번호는 +{digits(2)} {digits(3)}-{digits(4)}-{digits(4)} 입니다"),
        ("국내 전화", "phone-kr", f"번호는 01{digits(1)}-{digits(4)}-{digits(4)} 입니다"),
        ("주민등록번호형", "national-id", f"식별자 {digits(6)}-{rng.choice('1234')}{digits(6)}"),
        ("계좌형", "account", f"계좌 {digits(3)}-{digits(4)}-{digits(6)} 로 보내세요"),
        ("카드형", "card", f"카드 {digits(4)}-{digits(4)}-{digits(4)}-{digits(4)}"),
        ("비밀키형", "key-openai", f"키는 sk-{alnum(24)} 입니다"),
        ("비밀키형(gh)", "key-github", f"토큰 ghp_{alnum(30)}"),
        ("비밀키형(AWS)", "key-aws", f"자격 AKIA{''.join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(16))}"),
        ("개인키 블록", "key-private", "-----BEGIN OPENSSH PRIVATE KEY-----"),
        ("절대 경로", "path-posix", f"로그는 /Users/{alnum(6).lower()}/log 에"),
        ("홈 경로", "path-home", f"설정은 ~/{alnum(5).lower()}/conf 에"),
        ("사설 IP", "ip-private", f"서버 192.168.{digits(1)}.{digits(2)} 에서"),
        ("루프백 IP", "ip-loopback", f"로컬 127.0.0.{digits(1)} 에서"),
    ]


def _case_denylist_blocks_all_fixtures() -> None:
    """denylist 픽스처 전건 차단 — 그리고 **어느 규칙이** 잡았는지까지 단언한다(§8)."""
    from agora import scrub
    for label, rule, body in _denylist_fixtures():
        report = scrub.check({"payload": {"body": body}})
        rules = [f["rule"] for f in report["findings"]]
        if rule not in rules:
            raise AssertionError(f"{label}: {rule} 이 안 잡혔다 — 잡힌 것={rules}")


def _case_denylist_covers_eight_categories() -> None:
    """설계 §5 의 8범주가 규칙 파일에 **전부** 있다 — 규칙을 지우면 여기서 걸린다."""
    from agora import scrub
    want = {"email", "phone-intl", "phone-kr", "national-id", "account", "card",
            "key-openai", "key-github", "key-aws", "key-slack", "key-jwt",
            "key-private", "path-posix", "path-windows", "path-home",
            "ip-private", "ip-loopback"}
    have = {rid for rid, _kind, _p in scrub.load_rules().compiled}
    missing = want - have
    if missing:
        raise AssertionError(f"규칙이 사라졌다: {sorted(missing)}")


def _case_denylist_no_false_positive() -> None:
    """정상문 오탐 0(§8) — 우리가 실제로 쓸 법한 문장들로 잰다.

    ★차단 축만 재면 「전부 차단」도 초록이다. 이 축이 없으면 게이트를 조여도 아무도 모른다.
    """
    from agora import scrub
    clean = [
        "재현 절차는 세 단계입니다. 먼저 설정을 열고, 값을 바꾸고, 다시 실행합니다.",
        "판본 1.2.3 에서 같은 증상이 났고 1.2.4 에서는 안 났습니다.",
        "오류 코드 10 은 인자 오류이고 3 은 게이트 거부입니다.",
        "The build failed after 42 seconds with exit status 2.",
        "포트 8080 과 3000 을 함께 열어 두었습니다.",
        "2026-08-25 15:00 에 시작해 15:30 에 끝났습니다.",
        "비율은 10.5 대 89.5 였고 표본은 1200 개였습니다.",
        "문서는 https://docs.python.org/3/library/re.html 에 있습니다.",
    ]
    for body in clean:
        report = scrub.check({"payload": {"body": body}})
        if report["blocked"]:
            raise AssertionError(f"오탐: {body[:24]}… → {report['findings']}")


def _case_denylist_broken_rules_file_is_fail_closed() -> None:
    """규칙 파일이 **깨졌으면** 전량 차단(AC ② · 부재와 같은 방향)."""
    import tempfile
    from agora import scrub
    with tempfile.TemporaryDirectory() as d:
        broken = os.path.join(d, "broken.json")
        with open(broken, "w", encoding="utf-8") as fh:
            fh.write('{"version": "v1", "rules": [{"id": "x", "kind": "y", '
                     '"pattern": "[unclosed"}]}')
        scrub.load_rules(broken)


def _case_names_absence_is_visible() -> None:
    """이름 목록 부재는 **정상**이되 조용하지 않다 — 보고서에 몇 개를 실었는지 남는다.

    ★규칙 파일 부재(전량 차단)와 다르다. 「검사기가 고장났다」와
      「가릴 이름을 아직 안 적었다」는 다른 사건이고, 0 이 보여야 사람이 그것을 구별한다.
    """
    from agora import scrub
    report = scrub.check({"payload": {"body": "평범한 본문"}}, names=frozenset())
    if report["names_loaded"] != 0:
        raise AssertionError(f"이름 계수: {report['names_loaded']}")
    hit = scrub.check({"payload": {"body": "가나다 님이 그렇게 말했습니다"}},
                      names=frozenset({"가나다"}))
    if [f["rule"] for f in hit["findings"]] != ["name-list"]:
        raise AssertionError(f"이름 목록이 안 걸린다: {hit['findings']}")
    if hit["names_loaded"] != 1:
        raise AssertionError(f"이름 계수: {hit['names_loaded']}")


def _case_blocked_means_zero_writes() -> None:
    """차단 1건이면 **저장층 쓰기 호출이 0**이다(AC ③).

    ★code 3 이 났다는 것만으로는 「안 썼다」가 증명되지 않는다 — 쓰고 나서 났을 수도 있다.
      그래서 운반층의 호출 계수를 직접 본다.

    ★그리고 code 3 **자체**로는 이 경로를 잴 수 없다는 것을 실측으로 배웠다:
      publish 의 게이트를 지워도 **서명기가 다시 막아** 똑같이 code 3 이 난다(M-11 이중 방어).
      그래서 재는 축은 코드가 아니라 **쓰기 계수와 순서**다.
    """
    from agora import core
    from agora.store_mock import MockStore
    store = MockStore()
    ev = _r2_post("1" * 32, "본문에 sk-" + "A" * 24 + " 가 들어 있다")
    try:
        core.publish_event(store=store, event=ev, category="debate")
    except AgoraError as e:
        if e.code != errors.GATE_REJECT:
            raise AssertionError(f"code {e.code} != 3") from None
    else:
        raise AssertionError("차단됐어야 할 이벤트가 올라갔다")
    if store.append_calls != 0:
        raise AssertionError(f"막혔는데 저장층을 {store.append_calls}회 호출했다")
    if store.fetch(thread_id=_T1, limit=10)["items"]:
        raise AssertionError("막혔는데 운반층에 글이 남았다")


def _case_clean_event_reaches_store() -> None:
    """대조군 — 깨끗한 이벤트는 같은 경로로 **실제로** 올라간다.

    ★이 축이 없으면 「전부 차단」하는 고장이 초록으로 통과한다.
    """
    from agora import core, reducer
    from agora.store_mock import MockStore
    store = MockStore()
    ev = _r2_genesis()
    f = _fixtures()
    # ★S3-4 가 쓰기 경로에 **승인 게이트**를 넣었다. 이 케이스가 재는 것은 게이트가 아니라
    #   「깨끗하면 끝까지 간다」이므로 승인을 명시로 통과시킨다 —
    #   승인 축은 승인 케이스가 따로 잰다. 안 그러면 이 케이스가 두 가지를 뭉쳐 재게 된다.
    out = _with_key(f["key_a"], lambda: core.publish_event(
        store=store, event=ev, category="debate", is_genesis=True,
        isatty=lambda: True, prompt=lambda: True))
    if store.append_calls != 1 or not out.get("node_id"):
        raise AssertionError(f"쓰기 계수 {store.append_calls} · 결과 {out}")
    collected = _r2_collect(store)
    if len(collected["valid"]) != 1 or collected["quarantined"]:
        raise AssertionError(f"올라간 글이 다시 읽히지 않는다: {collected['quarantined']}")

# ── S3-3 봉투 스키마 · envelope_check ───────────────────────────────────────
# ★봉투는 예의가 아니라 **자격**이다. 재현 정보 없이 올린 질문은 답하는 쪽의 시간을 먼저 쓴다.

def _case_envelope_missing_three_kinds() -> None:
    """봉투 결손 3종 → code 3, 그리고 **빠진 칸 이름**이 사유에 나온다(§8 · AC ①)."""
    from agora import core
    template = core.envelope_template()
    for key in ("env", "symptom", "repro_steps"):
        broken = {k: v for k, v in template.items() if k != key}
        out = core.envelope_check(broken)
        if out["ok"]:
            raise AssertionError(f"{key} 결손이 통과했다")
        first = out["errors"][0]
        if first["code"] != errors.GATE_REJECT:
            raise AssertionError(f"{key} 결손: code {first['code']} != 3")
        if (first.get("detail") or {}).get("key") != key:
            raise AssertionError(f"{key} 결손인데 사유에 칸 이름이 없다: {first}")


def _case_envelope_empty_steps_is_gate() -> None:
    """재현 단계가 **빈 배열**인 것도 결손과 같은 자격 문제다(3)."""
    from agora import core
    env = core.envelope_template()
    env["repro_steps"] = []
    out = core.envelope_check(env)
    if out["ok"] or out["errors"][0]["code"] != errors.GATE_REJECT:
        raise AssertionError(f"빈 재현 단계: {out['errors']}")


def _case_envelope_shape_error_is_ten() -> None:
    """봉투 **안의 타입 오류**는 모양이므로 10 이다 — 자격(3)과 구별한다.

    ★둘을 뭉치면 「고치면 되는 것」과 「올릴 자격이 없는 것」이 같은 코드로 나가고,
      호출자는 어느 쪽인지 몰라 둘 다 못 고친다.
    """
    from agora import core
    env = core.envelope_template()
    env["repro_steps"] = ["첫 단계", 2, "셋째"]
    out = core.envelope_check(env)
    if out["ok"] or out["errors"][0]["code"] != errors.ARGUMENT:
        raise AssertionError(f"타입 오류: {out['errors']}")


def _case_envelope_log_excerpt_cap() -> None:
    """`log_excerpt` 4KB 초과 → code 3(AC ②) · **바이트**로 잰다."""
    from agora import core
    from agora.contract_open import MAX_LOG_EXCERPT_BYTES
    env = core.envelope_template()
    env["log_excerpt"] = "가" * ((MAX_LOG_EXCERPT_BYTES // 3) + 10)   # 한글 1자 = 3바이트
    out = core.envelope_check(env)
    if out["ok"]:
        raise AssertionError("상한을 넘겼는데 통과했다")
    # ★두 겹이 각각 잡는지 **따로** 본다. 계수만 보면 한 겹을 지워도 다른 겹이 대신 잡아
    #   초록이 유지된다(M80 이 처음에 그렇게 살아남았다 — 오늘 여섯 번째 같은 계보).
    schema_hit = [e for e in out["errors"]
                  if (e.get("detail") or {}).get("where") == "envelope.log_excerpt"]
    if not schema_hit or schema_hit[0]["code"] != errors.GATE_REJECT:
        raise AssertionError(f"계약 층이 상한을 안 잡는다: {out['errors']}")
    scrub_hit = [f for f in (out["scrub_report"] or {}).get("findings", [])
                 if f["rule"] == "max_bytes"]
    if not scrub_hit:
        raise AssertionError(f"게이트 층이 상한을 안 잡는다: {out['scrub_report']}")

    ok_env = core.envelope_template()
    ok_env["log_excerpt"] = "가" * ((MAX_LOG_EXCERPT_BYTES // 3) - 10)
    if not core.envelope_check(ok_env)["ok"]:
        raise AssertionError("상한 안인데 막혔다")


def _case_envelope_template_round_trips() -> None:
    """**서식이 그대로 검사를 통과한다**(AC ③).

    ★서식이 자기 검사를 못 지나면 「서식대로 썼는데 거부당하는」 일이 생기고,
      그러면 아무도 서식을 안 믿는다. 그래서 서식은 문서가 아니라 코드에 한 곳으로 둔다.
    """
    from agora import core, schema
    template = core.envelope_template()
    out = core.envelope_check(template)
    if not out["ok"]:
        raise AssertionError(f"서식이 자기 검사를 못 지난다: {out['errors']}")
    if out["scrub_report"]["blocked"]:
        raise AssertionError(f"서식이 스크럽에 걸린다: {out['scrub_report']['findings']}")
    # 서식을 그대로 담은 genesis 도 통과해야 한다 — 왕복의 나머지 반쪽.
    schema.validate(_fake_event("genesis", {
        "type": "problem", "title": "가짜 제목", "body": "가짜 본문",
        "envelope": template}))


def _case_envelope_check_returns_not_raises() -> None:
    """`envelope_check` 는 **던지지 않고 돌려준다** — 보내도 되나를 묻는 자리다.

    ★던지면 호출자가 사유를 하나밖에 못 본다. 사람이 한 번에 다 고칠 수 있어야 한다.
    """
    from agora import core
    env = core.envelope_template()
    del env["symptom"]
    env["log_excerpt"] = "연락처는 010-1234-5678 입니다"      # 스크럽도 함께 걸리게
    out = core.envelope_check(env)          # 예외가 나면 이 줄에서 케이스가 실패한다
    if out["ok"] or len(out["errors"]) < 2:
        raise AssertionError(f"사유를 모아서 주지 않는다: {out['errors']}")
    if out["scrub_report"] is None:
        raise AssertionError("스크럽 보고서가 비었다")

# ── S3-4 human_approval(기본 on) ────────────────────────────────────────────
# ★기계가 못 잡는 것이 남기 때문에 있는 문이다. 그래서 「띄울 수 없으면 보내지 않는다」가
#   이 문의 전부다 — 조용한 자동 승인은 문이 없는 것보다 나쁘다(있다고 믿게 만든다).

def _case_approval_default_is_on() -> None:
    """설정이 **없을 때** 기본값이 on 임을 단언한다(AC ①).

    ★기본값은 「적혀 있는 값」이 아니라 「아무도 안 적었을 때 일어나는 일」이다.
    """
    from agora import contract_open, core
    if contract_open.DEFAULT_HUMAN_APPROVAL is not True:
        raise AssertionError("계약 기본값이 on 이 아니다")
    try:
        core.approval_gate(config=None, isatty=lambda: False)
    except AgoraError as e:
        if (e.detail or {}).get("reason") != contract_open.HUMAN_APPROVAL_REQUIRED:
            raise AssertionError(f"사유가 다르다: {e.detail}") from None
    else:
        raise AssertionError("설정 부재인데 승인 없이 통과했다")


def _case_approval_no_tty_is_code3_with_reason() -> None:
    """TTY 부재 → code 3 **+ 사유 문자열까지** 단언(AC ③).

    ★코드만 보면 스크럽 차단과 구별되지 않는다. 사유 문자열이 그 둘을 가른다.
    """
    from agora.contract_open import HUMAN_APPROVAL_REQUIRED
    from agora import core
    try:
        core.approval_gate(config={}, isatty=lambda: False)
    except AgoraError as e:
        if e.code != errors.GATE_REJECT:
            raise AssertionError(f"code {e.code} != 3") from None
        if (e.detail or {}).get("reason") != HUMAN_APPROVAL_REQUIRED:
            raise AssertionError(f"사유 문자열: {e.detail}") from None
        return
    raise AssertionError("TTY 없이 통과했다")


def _case_approval_denied_writes_nothing() -> None:
    """승인 거부 → 저장층 쓰기 **0**(AC ②) · 사유는 거부로 구별된다."""
    from agora import core
    from agora.store_mock import MockStore
    f = _fixtures()
    store = MockStore()
    ev = _r2_genesis()
    try:
        _with_key(f["key_a"], lambda: core.publish_event(
            store=store, event=ev, category="debate", is_genesis=True,
            isatty=lambda: True, prompt=lambda: False))
    except AgoraError as e:
        if (e.detail or {}).get("reason") != "human_approval_denied":
            raise AssertionError(f"사유: {e.detail}") from None
    else:
        raise AssertionError("거부했는데 올라갔다")
    if store.append_calls != 0:
        raise AssertionError(f"거부했는데 저장층을 {store.append_calls}회 호출했다")


def _case_approval_granted_writes_once() -> None:
    """대조군 — 승인하면 같은 경로로 실제로 올라간다."""
    from agora import core
    from agora.store_mock import MockStore
    f = _fixtures()
    store = MockStore()
    out = _with_key(f["key_a"], lambda: core.publish_event(
        store=store, event=_r2_genesis(), category="debate", is_genesis=True,
        isatty=lambda: True, prompt=lambda: True))
    if store.append_calls != 1 or out["approval"]["approved"] is not True:
        raise AssertionError(f"승인했는데 안 올라갔다: {store.append_calls} {out.get('approval')}")


def _case_approval_off_only_via_config() -> None:
    """끄는 길은 `config.json` 하나뿐 — 환경변수·인자로 끄는 경로가 0건이어야 한다(AC ④).

    ★「급해서 한 번만」 끄는 길을 열어 두면 그 한 번이 기본값이 된다.
      정적으로 잰다: 승인 코드가 환경변수를 읽지 않는다.
    """
    from agora import core
    with open(os.path.join(_ROOT, "agora", "core.py"), encoding="utf-8") as fh:
        src = fh.read()
    for needle in ("environ", "getenv", "argv"):
        if needle in src:
            raise AssertionError(f"승인 경로가 {needle} 를 읽는다 — 끄는 길이 둘이 된다")
    off = core.approval_gate(config={"human_approval": False}, isatty=lambda: False)
    if off["approved"] is not True or off["why"] != "config.json":
        raise AssertionError(f"config 로 끄는 길이 막혔다: {off}")


def _case_approval_no_silent_auto_pass() -> None:
    """조용한 자동 승인 경로 0건(AC ③ 후단) — 승인 없이 True 를 돌려주는 자리가 없다.

    ★기본 인자로 「승인됨」을 넣어 두는 실수가 가장 흔하다. 그래서 프롬프트가 없으면
      **거부**로 떨어지는지 직접 본다.
    """
    from agora import core
    try:
        core.approval_gate(config={}, isatty=lambda: True, prompt=None)
    except AgoraError as e:
        if (e.detail or {}).get("reason") != "human_approval_denied":
            raise AssertionError(f"사유: {e.detail}") from None
        return
    raise AssertionError("프롬프트가 없는데 승인으로 통과했다")

# ── S3-5 서명기 재검사(M-11) ────────────────────────────────────────────────
# ★스크럽 결과는 **발신자의 자기주장**이다. 기록에 남는 판정은 서명기의 것이다.
#   그리고 수신 측은 그 판정을 자기 규칙으로 **다시 잰다** — 세 자리가 각각 자기 눈을 갖는다.

def _case_signer_records_its_own_measurement() -> None:
    """서명기 영수증의 scrub 은 **서명기가 직접 잰 값**이다 — 주장은 옆에 나란히 남는다(AC ①)."""
    from agora import scrub
    from agora.sign import sign_event
    f = _fixtures()
    ev = _r2_post("1" * 32, "깨끗한 본문입니다")
    ev["scrub"] = {"rules": "f" * 64, "blocked": 0, "redacted": 0}   # 거짓 digest 주장
    res = _with_key(f["key_a"], lambda: sign_event(ev))
    measured = scrub.check(ev)
    if res["scrub"]["bundle"] != measured["bundle"]:
        raise AssertionError("영수증이 발신자 주장을 그대로 실었다")
    if res["scrub_claim"]["rules"] != "f" * 64:
        raise AssertionError("주장을 지웠다 — 사후 판정의 증거가 사라진다")
    if not res["claim_mismatch"] or "rules" not in res["claim_mismatch"]:
        raise AssertionError(f"어긋남이 안 보인다: {res['claim_mismatch']}")


def _case_signer_refuses_forged_clean_claim() -> None:
    """차단 대상을 담고도 `blocked: 0` 이라 주장하면 **서명이 안 나온다**(AC ① 위조 픽스처).

    ★위조를 막는 것은 주장 대조가 아니라 **재검사 자체**다. 주장은 얼마든지 예쁘게 쓸 수 있다.
    """
    from agora.sign import sign_event
    f = _fixtures()
    ev = _r2_post("1" * 32, "본문에 sk-" + "B" * 24 + " 가 들어 있다")
    ev["scrub"] = {"rules": "0" * 64, "blocked": 0, "redacted": 0}
    _with_key(f["key_a"], lambda: sign_event(ev))


def _case_honest_declaration_matches() -> None:
    """정직하게 채우면 주장과 측정이 **일치**한다 — 어긋남 표시가 없다(대조군)."""
    from agora import core
    from agora.sign import sign_event
    f = _fixtures()
    ev = core.declare_scrub(_r2_post("1" * 32, "깨끗한 본문입니다"))
    res = _with_key(f["key_a"], lambda: sign_event(ev))
    if res["claim_mismatch"]:
        raise AssertionError(f"정직한 주장인데 어긋남이 떴다: {res['claim_mismatch']}")
    if ev["scrub"]["rules"] != res["scrub"]["bundle"]:
        raise AssertionError("주장이 묶음(bundle)이 아니다")


def _case_declaration_carries_bundle_not_one_layer() -> None:
    """싣는 값은 **묶음**이다 — 한 겹만 실으면 수신 측이 나머지 겹을 대조할 수 없다.

    ★그리고 그 대가를 함께 못박는다: 묶음을 다시 만들려면 수신 측이 **세 겹 전부**
      (denylist 규칙 · allowlist 규칙 · 허용 도메인)를 갖고 있어야 한다.
      한 겹이라도 다르면 묶음이 달라지고, 그 사실이 재검사 플래그로 드러나야 한다.
    """
    import tempfile
    from agora import core, scrub
    ev = core.declare_scrub(_r2_post("1" * 32, "깨끗한 본문입니다"))
    report = scrub.check(ev)
    claimed = ev["scrub"]["rules"]
    if claimed in (report["rules"], report["allow_rules"]):
        raise AssertionError("한 겹만 실었다 — 나머지 겹은 대조할 수 없다")
    # 세 겹 중 **도메인 목록 한 겹만** 달라져도 묶음이 달라진다.
    with tempfile.TemporaryDirectory() as d:
        other = os.path.join(d, "domains.txt")
        with open(other, "w", encoding="utf-8") as fh:
            fh.write("example.test\n")
        alt = scrub.check(ev, allow=scrub.load_allow(domains_path=other))
        if alt["bundle"] == claimed:
            raise AssertionError("도메인 목록이 달라졌는데 묶음이 그대로다")


def _case_receiver_flags_digest_mismatch() -> None:
    """수신 측이 자기 규칙으로 대조해 **재검사 플래그**를 세운다(§8) — 거부가 아니다."""
    from agora import scrub
    g = _r2_genesis()          # 픽스처의 주장은 가짜 digest 다
    out = _r2_collect(_r3_store([(_r2_signed(g), "2026-01-01T00:00:00Z")]),
                      scrub_bundle=scrub.check(g)["bundle"])
    if out["quarantined"]:
        raise AssertionError("digest 가 다르다고 격리했다 — 판본 차이는 거부 사유가 아니다")
    if not out["valid"][0]["scrub_recheck"]:
        raise AssertionError("어긋나는데 재검사 플래그가 없다")


def _case_receiver_no_flag_when_matching() -> None:
    """대조군 — 같은 규칙 묶음이면 플래그가 서지 않는다.

    ★플래그만 재면 「항상 플래그」도 초록이다.
    """
    from agora import core, scrub
    from agora.event import event_hash
    g = core.declare_scrub(_r2_genesis())
    out = _r2_collect(_r3_store([(_r2_signed(g), "2026-01-01T00:00:00Z")]),
                      scrub_bundle=scrub.check(g)["bundle"])
    if not out["valid"]:
        raise AssertionError(f"정직한 이벤트가 격리됐다: {out['quarantined']}")
    if out["valid"][0]["scrub_recheck"]:
        raise AssertionError("일치하는데 플래그가 섰다")
    if out["valid"][0]["hash"] != event_hash(g):
        raise AssertionError("주장을 채운 뒤의 해시가 사슬 값과 다르다")

# ── S2-8 슬라이스 마감 — 그물 대장 ─────────────────────────────────────────

# S2 가 지켜야 할 4축(04-tasks S2-8) → 그 축을 재는 뮤테이션.
# ★이 표가 없으면 「4축을 쟀다」가 사람의 기억에 남는다. 표로 두면 **뮤테이션을 지우는 순간**
#   이 케이스가 적색이 된다 — 그물을 걷어 낸 것이 조용히 지나가지 않는다.
S2_AXES: dict[str, tuple[str, ...]] = {
    "경합": ("M41-reducer-order-unstable", "M42-race-winner-inverted",
             "M43-race-tiebreak-dropped", "M44-unreachable-not-detected",
             "M45-stale-merged-into-quarantine"),
    "권한": ("M46-chair-check-off", "M50-requester-check-off",
             "M57-delegate-chair-check-off", "M58-abort-operator-check-off",
             "M61-operator-delegate-unconditional"),
    "라운드": ("M47-out-of-round-allowed", "M48-counter-not-required",
               "M56-time-beats-event", "M59-expired-never-fires"),
    "예산": ("M62-budget-not-enforced", "M63-budget-hardcoded",
             "M64-budget-chars-ignored", "M65-budget-config-unvalidated"),
}


def _case_s2_axes_have_nets() -> None:
    """S2 의 4축이 각각 실제 뮤테이션으로 덮여 있고, 그 뮤테이션이 표에 실재한다."""
    ids = {m[0] for m in MUTATIONS}
    missing = {axis: sorted(set(want) - ids) for axis, want in S2_AXES.items()}
    missing = {a: v for a, v in missing.items() if v}
    if missing:
        raise AssertionError(f"그물이 사라진 축: {missing}")
    for axis, want in S2_AXES.items():
        if not want:
            raise AssertionError(f"축에 뮤테이션이 하나도 없다: {axis}")


def _case_quarantine_reasons_are_named() -> None:
    """격리 사유는 **이름을 먼저 받는다** — 목록에 없는 사유가 코드에서 나오면 적색.

    ★사유가 목록 밖에서 늘어나면 「왜 안 보이나」에 답하는 어휘가 사람마다 달라진다.
    """
    import re
    from agora import reducer
    src_path = os.path.join(_ROOT, "agora", "reducer.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    used = set(re.findall(r"reject\(entry, ([A-Z_]+)", src))
    used |= set(re.findall(r"drop\(row, ([A-Z_]+)", src))
    named = {n for n in dir(reducer)
             if n.isupper() and isinstance(getattr(reducer, n), str)}
    unknown = used - named
    if unknown:
        raise AssertionError(f"이름 없는 사유: {sorted(unknown)}")
    values = {getattr(reducer, n) for n in used if n in named}
    if not values <= set(reducer.REASONS):
        raise AssertionError(f"REASONS 에 없는 사유: {sorted(values - set(reducer.REASONS))}")



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
    ("sign: 정상 → ok",            _case_sign_verify_ok,        None),
    ("sign: 변조 → BAD",           _case_sign_verify_tampered_is_BAD, None),
    ("sign: 무서명 → unsigned",    _case_sign_verify_unsigned,  None),
    ("sign: 명부밖 → unsigned",    _case_sign_off_roster_is_unsigned_not_BAD, None),
    ("sign: 명부 부재 → unsigned",  _case_verify_missing_roster_is_unsigned, None),
    ("signer: scrub 거부 → 3",     _case_signer_refuses_scrub,  errors.GATE_REJECT),
    ("signer: kind 거부 → 3",      _case_signer_refuses_bad_kind, errors.GATE_REJECT),
    ("signer: 크기 거부 → 3",      _case_signer_refuses_oversize, errors.GATE_REJECT),
    ("signer: 호출자 키 거부 → 10", _case_signer_refuses_caller_key, errors.ARGUMENT),
    ("signer: 키 미지정 → 2",      _case_signer_no_key_is_precondition, errors.PRECONDITION),
    ("signer: 잘못된 키 → 4",      _case_signer_bad_key_is_signature_error, errors.SIGNATURE),
    ("서명기 우회 경로 0건",        _case_no_private_key_read_outside_signer, None),
    ("scrub: 규칙 부재 → 3(fail-closed)", _case_scrub_fail_closed, errors.GATE_REJECT),
    ("명부: 폐기 키 → 무효(사유 revoked)", _case_revoked_key_is_invalid, None),
    ("명부: 체크포인트·파일 경계",   _case_roster_checkpoint_changes, None),
    ("명부: namespace 단일 정의",    _case_namespace_single_source, None),
    ("participant: 정상 로드",       _case_participant_ok,        None),
    ("participant: 파일 644 → 2",    _case_participant_loose_file_mode, errors.PRECONDITION),
    ("participant: 폴더 755 → 2",    _case_participant_loose_dir_mode, errors.PRECONDITION),
    ("participant: 계약 밖 칸 → 2",  _case_participant_extra_field, errors.PRECONDITION),
    ("keygen: 덮어쓰기 거부 → 10",   _case_keygen_refuses_overwrite, errors.ARGUMENT),
    ("golden: 5변형 → canonical 1종", _case_golden_variants_collapse, None),
    ("golden: 서명 재검증 ok",        _case_golden_signature_verifies, None),
    ("golden: 1바이트 변조 → BAD",    _case_golden_bitflip_is_BAD, None),
    ("golden: 미실행 고지 존재",      _case_golden_declares_what_it_did_not_test, None),
    ("원장: 정상 100행 통과",        _case_ledger_chain_ok,       None),
    ("원장: 칸 1개 변조 → 실패",     _case_ledger_body_altered,   None),
    ("원장: 1행 삭제 → 실패",        _case_ledger_row_deleted,    None),
    ("원장: 전량 쓰기 경로 0건",      _case_ledger_append_only,    None),
    ("원장: 이벤트 원문 보존",        _case_ledger_stores_raw_event, None),
    ("저장층: mock 계약 충족",        _case_store_mock_satisfies_contract, None),
    ("저장층: 저장 불명 → 8",         _case_store_unknown_commit,  errors.UNKNOWN_COMMIT),
    ("저장층: 오류 → 7(retryable)",   _case_store_error_is_retryable, errors.STORE),
    ("저장층: 페이지 전건 회수",       _case_store_pagination_returns_all, None),
    ("저장층: problem 만 answerable", _case_store_answerable_only_problem, None),

    ("스키마: 9종 정상 전건 통과",   _case_schema_nine_kinds_ok,  None),
    ("스키마: 9종 필수칸 결손 → 10", _case_schema_missing_field_rejected, None),
    ("스키마: 표 밖 kind → 10",      _case_schema_unknown_kind,   errors.ARGUMENT),
    ("스키마: 계약 밖 칸 → 10",      _case_schema_closed_rejects_extra, None),
    ("스키마: 칸 타입 불일치 → 10",  _case_schema_type_mismatch,  None),
    ("스키마: 권고 집행금지 표식 없음 → 3", _case_schema_resolution_execution_forbidden, errors.GATE_REJECT),
    ("스키마: 봉투 없는 problem → 3", _case_schema_problem_needs_envelope, errors.GATE_REJECT),
    ("스키마: 봉투 붙인 problem → 통과", _case_schema_problem_with_envelope_ok, None),
    ("스키마: genesis prev 계약값",   _case_schema_genesis_prev_contract, None),
    ("스키마: 표 ↔ 계약 kind 일치",   _case_schema_table_matches_contract, None),

    ("reducer: 정상 3건 전건 유효",   _case_reducer_valid_pass_through, None),
    ("reducer: 무서명 주입 → 격리",   _case_reducer_unsigned_injection, None),
    ("reducer: 남의 스레드 → 격리",   _case_reducer_foreign_thread_event, None),
    ("reducer: 재게시 → 뒤엣것 격리", _case_reducer_replay_rejected, None),
    ("reducer: 스키마 위반 → 격리",   _case_reducer_schema_violation_quarantined, None),
    ("reducer: 웹 댓글 → 격리",       _case_reducer_web_comment_quarantined, None),
    ("reducer: 격리는 audit 에만",    _case_reducer_quarantine_hidden_by_default, None),
    ("reducer: 격리는 삭제가 아니다", _case_reducer_quarantine_does_not_delete, None),
    ("reducer: 페이지 전건·순서 무관", _case_reducer_paginates_and_order_independent, None),
    ("경합: 같은 prev 2건 → 승자 1",  _case_reducer_race_two_one_winner, None),
    ("경합: 같은 prev 3건 → stale 2", _case_reducer_race_three_two_stale, None),
    ("경합: 동률 → node_id(100회)",   _case_reducer_race_tie_is_deterministic, None),
    ("경합: 진 쪽 후손 → unreachable", _case_reducer_loser_descendant_unreachable, None),
    ("경합: stale ≠ 격리",            _case_reducer_stale_is_not_quarantine, None),
    ("경합: genesis 없으면 사슬 없음", _case_reducer_no_genesis_no_chain, None),
    ("전이: debate 정상 완주",        _case_debate_full_course, None),
    ("전이: 비의장 advance → 무효",   _case_debate_non_chair_advance, None),
    ("권한: 비의장 쓰기 → 5",         _case_write_path_non_chair_is_code5, errors.PERMISSION),
    ("권한: 비요청자 쓰기 → 5",       _case_write_path_non_requester_is_code5, errors.PERMISSION),
    ("CAS: 낡은 상태로 쓰기 → 9",     _case_write_path_stale_state_is_code9, errors.STATE_CONFLICT),
    ("전이: 라운드 밖 post → 격리",   _case_debate_out_of_round_post, None),
    ("전이: R2 counter 필수",         _case_debate_r2_requires_counter, None),
    ("전이: advance 단조 증가만",     _case_advance_monotonic_only, None),
    ("전이: 출발 라운드 불일치",      _case_advance_from_round_must_match_now, None),
    ("경계: debate 에 answer → 무효", _case_debate_rejects_answer_selected, None),
    ("경계: knowhow 에 advance → 무효", _case_knowhow_rejects_advance, None),
    ("전이: 요청자만 solved",         _case_problem_only_requester_solves, None),
    ("전이: 없는 답 고르기 → 무효",   _case_answer_target_must_exist, None),
    ("전이: knowhow 종결 사유 제한",  _case_knowhow_close_reason_limited, None),
    ("전이: 종결 후 이벤트 → 무효",   _case_events_after_close_rejected, None),
    ("전이: 조용한 보류 0건",         _case_no_silent_deferrals, None),
    ("상태 해시: 결정론·민감",        _case_state_hash_is_deterministic_and_sensitive, None),
    ("마감: advance 부재 → expired",  _case_deadline_expires_without_advance, None),
    ("마감: 유예 안에서는 진행",      _case_deadline_grace_window, None),
    ("마감: 이벤트가 시간을 이긴다",  _case_event_beats_time, None),
    ("마감: 만료 판정 결정론",        _case_expired_verdict_is_deterministic, None),
    ("승계: 최신 위임이 의장",        _case_chair_is_latest_delegate, None),
    ("승계: 비의장 위임 → 무효",      _case_non_chair_cannot_delegate, None),
    ("승계: 재개는 advance 가 한다",  _case_expired_resumes_by_advance_not_by_delegate, None),
    ("중단: 운영자 명부만 abort",     _case_abort_requires_operator, None),
    ("마감: deadlines 표는 닫혀 있다", _case_deadlines_schema_closed, None),
    ("승계: 운영자는 만료 때만",      _case_operator_delegate_only_when_expired, None),
    ("예산: 로컬 사전 검사 → 3",      _case_budget_local_precheck_is_code3, errors.GATE_REJECT),
    ("예산: 사전 검사 없이도 무효",   _case_budget_reducer_rejects_without_precheck, None),
    ("예산: 설정에서 읽는다",         _case_budget_comes_from_settings, None),
    ("예산: 글자 수 상한",            _case_budget_counts_chars_too, None),
    ("예산: 진 글은 안 쓴다",         _case_budget_not_spent_by_losers, None),
    ("예산: 참가자·라운드별",         _case_budget_is_per_participant_and_round, None),
    ("예산: 설정 값 검증 → 10",       _case_budget_value_must_be_sane, errors.ARGUMENT),
    ("예산: 사용량 칸 실재",          _case_usage_field_exists, None),
    ("관계: 세 필드 정상",            _case_relations_three_fields_ok, None),
    ("관계: 세 필드 위반 → 10",       _case_relations_schema_violations, None),
    ("관계: 절차를 바꾸지 않는다",    _case_relations_do_not_change_procedure, None),
    ("관계: 없는 곳을 가리켜도 된다", _case_relations_may_point_nowhere, None),
    ("관계: spawn 은 제안뿐",         _case_spawn_is_proposal_only, None),
    ("S2: 4축 그물 실재",             _case_s2_axes_have_nets, None),
    ("S2: 격리 사유는 이름을 받는다", _case_quarantine_reasons_are_named, None),
    ("allowlist: 위반 5종 차단",      _case_allowlist_blocks_five_kinds, None),
    ("allowlist: 집행 → 3",           _case_allowlist_enforce_is_code3, errors.GATE_REJECT),
    ("allowlist: 허용 통과·오탐 0",   _case_allowlist_allows_listed_domain, None),
    ("allowlist: 빈 목록 → 전 URL 차단", _case_allowlist_empty_domains_blocks_all_urls, None),
    ("allowlist: 파일 부재 → 3",      _case_allowlist_missing_file_is_fail_closed, errors.GATE_REJECT),
    ("allowlist: 필드 상한(자·바이트)", _case_allowlist_field_limits, None),
    ("scrub: 두 겹 digest 동봉",      _case_scrub_report_carries_both_digests, None),
    ("서명기: allowlist 위반 → 3",    _case_signer_refuses_allowlist_violation, errors.GATE_REJECT),
    ("denylist: 픽스처 전건 차단",    _case_denylist_blocks_all_fixtures, None),
    ("denylist: 8범주 규칙 실재",     _case_denylist_covers_eight_categories, None),
    ("denylist: 정상문 오탐 0",       _case_denylist_no_false_positive, None),
    ("denylist: 규칙 파손 → 3",       _case_denylist_broken_rules_file_is_fail_closed, errors.GATE_REJECT),
    ("scrub: 이름 목록 부재는 보인다", _case_names_absence_is_visible, None),
    ("쓰기: 차단이면 저장 호출 0",    _case_blocked_means_zero_writes, None),
    ("쓰기: 깨끗하면 올라간다",       _case_clean_event_reaches_store, None),
    ("봉투: 결손 3종 → 3(칸 이름)",   _case_envelope_missing_three_kinds, None),
    ("봉투: 빈 재현 단계 → 3",        _case_envelope_empty_steps_is_gate, None),
    ("봉투: 타입 오류 → 10",          _case_envelope_shape_error_is_ten, None),
    ("봉투: 로그 발췌 4KB → 3",       _case_envelope_log_excerpt_cap, None),
    ("봉투: 서식이 그대로 통과",      _case_envelope_template_round_trips, None),
    ("봉투: 사유를 모아서 돌려준다",  _case_envelope_check_returns_not_raises, None),
    ("승인: 기본값 on",               _case_approval_default_is_on, None),
    ("승인: TTY 부재 → 3(사유)",      _case_approval_no_tty_is_code3_with_reason, None),
    ("승인: 거부면 쓰기 0",           _case_approval_denied_writes_nothing, None),
    ("승인: 승인하면 올라간다",       _case_approval_granted_writes_once, None),
    ("승인: 끄는 길은 config 하나",   _case_approval_off_only_via_config, None),
    ("승인: 조용한 자동 통과 0건",    _case_approval_no_silent_auto_pass, None),
    ("서명기: 자기 측정을 기록",      _case_signer_records_its_own_measurement, None),
    ("서명기: 위조 주장 → 3",         _case_signer_refuses_forged_clean_claim, errors.GATE_REJECT),
    ("서명기: 정직한 주장은 일치",    _case_honest_declaration_matches, None),
    ("주장: 한 겹이 아니라 묶음",     _case_declaration_carries_bundle_not_one_layer, None),
    ("수신: digest 불일치 → 플래그",  _case_receiver_flags_digest_mismatch, None),
    ("수신: 일치하면 플래그 없음",    _case_receiver_no_flag_when_matching, None),
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
    ("M12-signer-kind-check-off", "agora/signer.py",
     "    if kind not in KINDS:",
     "    if False:",
     "signer: kind 거부 → 3"),
    ("M13-signer-scrub-not-enforced", "agora/signer.py",
     "    report = scrub.enforce(event)",
     "    report = scrub.check(event)",
     "signer: scrub 거부 → 3"),
    ("M14-signer-caller-key-allowed", "agora/signer.py",
     'if "key" in request or "key_path" in request:',
     "if False:",
     "signer: 호출자 키 거부 → 10"),
    ("M15-verify-skips-novalidate", "agora/sign.py",
     "        if rc != 0:\n            return {\"verdict\": BAD, \"reason\": \"signature_does_not_match_bytes\",\n                    \"fingerprint\": None}",
     "        if False:\n            pass",
     "sign: 변조 → BAD"),
    ("M16-verify-missing-roster-is-ok", "agora/sign.py",
     '            return {"verdict": UNSIGNED, "reason": "no_roster", "fingerprint": fingerprint}',
     '            return {"verdict": OK, "reason": "no_roster", "fingerprint": fingerprint}',
     "sign: 명부 부재 → unsigned"),
    ("M17-scrub-rules-missing-passes", "agora/scrub.py",
     '        raise AgoraError(errors.GATE_REJECT,\n                         "규칙 파일을 읽을 수 없다 — 전량 차단(fail-closed)",\n                         {"path": os.path.basename(path), "error": e.strerror}) from None',
     "        return Rules('empty', [(\"x\", \"x\", re.compile(\"(?!x)x\"))], \"none\")",
     "scrub: 규칙 부재 → 3(fail-closed)"),
    ("M18-revocation-ignored", "agora/sign.py",
     "        if revoked_path and fingerprint:",
     "        if False:",
     "명부: 폐기 키 → 무효(사유 revoked)"),
    ("M19-participant-mode-unchecked", "agora/participant.py",
     "    if mode != want:",
     "    if False:",
     "participant: 파일 644 → 2"),
    ("M20-checkpoint-no-boundary", "agora/roster.py",
     '        h.update(rel.encode("utf-8"))\n        h.update(len(blob).to_bytes(8, "big"))',
     "        pass",
     "명부: 체크포인트·파일 경계"),
    ("M21-keygen-overwrites", "agora/keygen.py",
     "    if os.path.exists(key_path):",
     "    if False:",
     "keygen: 덮어쓰기 거부 → 10"),
    ("M22-participant-extra-allowed", "agora/participant.py",
     "    if extra:",
     "    if False:",
     "participant: 계약 밖 칸 → 2"),
    ("M23-newline-not-normalized", "agora/event.py",
     '    return text.replace("\\r\\n", "\\n").replace("\\r", "\\n")',
     "    return text",
     "golden: 5변형 → canonical 1종"),
    ("M24-ledger-body-not-checked", "agora/ledger.py",
     "            if row_hash(row) != row[_ROW_HASH]:",
     "            if False:",
     "원장: 칸 1개 변조 → 실패"),
    ("M25-ledger-link-not-checked", "agora/ledger.py",
     '            if row.get("prev_ledger_hash") != prev_link:',
     "            if False:",
     "원장: 1행 삭제 → 실패"),
    ("M26-ledger-overwrite-mode", "agora/ledger.py",
     '                with open(self.path, "a", encoding="utf-8") as fh:   # ★append 만',
     '                with open(self.path, "w", encoding="utf-8") as fh:',
     "원장: 정상 100행 통과"),
    ("M27-pagination-stops-early", "agora/store_mock.py",
     '        nxt = str(start + limit) if start + limit < len(rows) else None',
     "        nxt = None",
     "저장층: 페이지 전건 회수"),
    ("M28-all-categories-answerable", "agora/store_mock.py",
     '        return {name: {"id": f"MOCKCAT_{name}", "is_answerable": name in self._answerable}',
     '        return {name: {"id": f"MOCKCAT_{name}", "is_answerable": True}',
     "저장층: problem 만 answerable"),
    ("M11-isinstance-widened", "agora/event.py",
     "    if type(node) is str:\n        return _nfc(_normalize_newlines(node))",
     "    if isinstance(node, str):\n        return _nfc(_normalize_newlines(node))",
     "canonical: str 서브클래스 → 10"),
    ("M29-schema-closed-off", "agora/schema.py",
     "    extra = [k for k in obj if k not in allowed]",
     "    extra = []",
     "스키마: 계약 밖 칸 → 10"),
    ("M30-schema-execution-unchecked", "agora/schema.py",
     '        if a.get("execution") != "forbidden":',
     "        if False:",
     "스키마: 권고 집행금지 표식 없음 → 3"),
    ("M31-schema-unknown-kind-allowed", "agora/schema.py",
     "    if kind not in KINDS:",
     "    if False:",
     "스키마: 표 밖 kind → 10"),
    ("M32-schema-required-unchecked", "agora/schema.py",
     "    if key not in obj:",
     "    if False:",
     "스키마: 9종 필수칸 결손 → 10"),
    ("M33-schema-type-unchecked", "agora/schema.py",
     "    if type(value) is not typ:",
     "    if False:",
     "스키마: 칸 타입 불일치 → 10"),
    ("M34-schema-envelope-optional", "agora/schema.py",
     '        if "envelope" not in p:',
     "        if False:",
     "스키마: 봉투 없는 problem → 3"),
    ("M35-reducer-signature-unchecked", "agora/reducer.py",
     '        if verdict["verdict"] != sign.OK:',
     "        if False:",
     "reducer: 무서명 주입 → 격리"),
    ("M36-reducer-thread-binding-off", "agora/reducer.py",
     '        if event["thread_id"] != thread_id:',
     "        if False:",
     "reducer: 남의 스레드 → 격리"),
    ("M37-reducer-replay-allowed", "agora/reducer.py",
     "        if key in seen:",
     "        if False:",
     "reducer: 재게시 → 뒤엣것 격리"),
    ("M38-reducer-schema-not-applied", "agora/reducer.py",
     "            schema.validate(event)",
     "            pass",
     "reducer: 스키마 위반 → 격리"),
    ("M39-reducer-quarantine-always-shown", "agora/reducer.py",
     "    if audit:",
     "    if True:",
     "reducer: 격리는 audit 에만"),
    ("M40-reducer-first-page-only", "agora/reducer.py",
     "        cursor = page.get(\"next_cursor\")",
     "        cursor = None",
     "reducer: 페이지 전건·순서 무관"),
    ("M41-reducer-order-unstable", "agora/reducer.py",
     "    rows = sorted(fetch_all(store, thread_id, limit=limit), key=_order_key)",
     "    rows = fetch_all(store, thread_id, limit=limit)",
     "reducer: 재게시 → 뒤엣것 격리"),
    ("M42-race-winner-inverted", "agora/reducer.py",
     "        winner = min(candidates, key=_winner_key)",
     "        winner = max(candidates, key=_winner_key)",
     "경합: 같은 prev 2건 → 승자 1"),
    ("M43-race-tiebreak-dropped", "agora/reducer.py",
     '    return (str(entry.get("created_at") or ""), str(entry.get("node_id") or ""))',
     '    return (str(entry.get("created_at") or ""), "")',
     "경합: 동률 → node_id(100회)"),
    ("M44-unreachable-not-detected", "agora/reducer.py",
     '        if e["hash"] not in seen_hashes and e["node_id"] not in lost_nodes',
     "        if False",
     "경합: 진 쪽 후손 → unreachable"),
    ("M45-stale-merged-into-quarantine", "agora/reducer.py",
     '            "quarantined": collected["quarantined"]}',
     '            "quarantined": collected["quarantined"] + stale}',
     "경합: stale ≠ 격리"),
    ("M46-chair-check-off", "agora/reducer.py",
     '            if who != state["chair"]:\n                reject(entry, PERMISSION, {"chair": state["chair"], "from": who})\n                continue\n            if payload["from_round"] != state["round"]:',
     '            if False:\n                pass\n            if payload["from_round"] != state["round"]:',
     "전이: 비의장 advance → 무효"),
    ("M47-out-of-round-allowed", "agora/reducer.py",
     '                if payload.get("round") != state["round"]:',
     "                if False:",
     "전이: 라운드 밖 post → 격리"),
    ("M48-counter-not-required", "agora/reducer.py",
     '                if state["round"] == 2 and not payload.get("counter"):',
     "                if False:",
     "전이: R2 counter 필수"),
    ("M49-kind-boundary-open", "agora/reducer.py",
     "        if kind not in ALLOWED_KINDS[gtype]:",
     "        if False:",
     "경계: knowhow 에 advance → 무효"),
    ("M50-requester-check-off", "agora/reducer.py",
     '            if who != state["requester"]:',
     "            if False:",
     "전이: 요청자만 solved"),
    ("M51-answer-target-unchecked", "agora/reducer.py",
     '            if payload["post_message_id"] not in post_ids:',
     "            if False:",
     "전이: 없는 답 고르기 → 무효"),
    ("M52-after-close-allowed", "agora/reducer.py",
     '        if state["state"] == "closed":',
     "        if False:",
     "전이: 종결 후 이벤트 → 무효"),
    ("M53-cas-gate-off", "agora/reducer.py",
     "    if expected_state != now:",
     "    if False:",
     "CAS: 낡은 상태로 쓰기 → 9"),
    ("M89-signer-records-claim-not-measure", "agora/signer.py",
     '        "scrub": report,\n        "scrub_claim": _claim_of(event),',
     '        "scrub": _claim_of(event),\n        "scrub_claim": _claim_of(event),',
     "서명기: 자기 측정을 기록"),
    ("M90-claim-mismatch-hidden", "agora/signer.py",
     '    if claim.get("rules") != report.get("bundle"):',
     "    if False:",
     "서명기: 자기 측정을 기록"),
    ("M91-receiver-recheck-flag-off", "agora/reducer.py",
     '            "scrub_recheck": (scrub_bundle is not None\n                              and event["scrub"].get("rules") != scrub_bundle),',
     '            "scrub_recheck": False,',
     "수신: digest 불일치 → 플래그"),
    ("M92-declare-one-layer-only", "agora/core.py",
     '    event["scrub"] = {"rules": report["bundle"], "blocked": report["blocked"],',
     '    event["scrub"] = {"rules": report["rules"], "blocked": report["blocked"],',
     "주장: 한 겹이 아니라 묶음"),
    ("M84-approval-default-off", "agora/contract_open.py",
     "DEFAULT_HUMAN_APPROVAL = True",
     "DEFAULT_HUMAN_APPROVAL = False",
     "승인: 기본값 on"),
    ("M85-no-tty-passes-silently", "agora/core.py",
     '    if not tty:\n        raise AgoraError(errors.GATE_REJECT, "승인을 받을 수 없다 — 전송하지 않는다",\n                         {"reason": HUMAN_APPROVAL_REQUIRED})',
     '    if not tty:\n        return {"required": True, "approved": True, "why": "no_tty"}',
     "승인: TTY 부재 → 3(사유)"),
    ("M86-denial-ignored", "agora/core.py",
     '    if not (prompt or (lambda: False))():',
     "    if False:",
     "승인: 거부면 쓰기 0"),
    ("M87-approval-skipped-in-publish", "agora/core.py",
     "    approval = approval_gate(config=config, prompt=prompt, isatty=isatty)   # ⑶ 승인",
     '    approval = {"required": False, "approved": True, "why": "skipped"}',
     "승인: 거부면 쓰기 0"),
    ("M88-prompt-defaults-to-approved", "agora/core.py",
     "    if not (prompt or (lambda: False))():",
     "    if not (prompt or (lambda: True))():",
     "승인: 조용한 자동 통과 0건"),
    ("M83-allow-max-bytes-unchecked", "agora/scrub.py",
     '        if "max_bytes" in spec:',
     "        if False:",
     "allowlist: 필드 상한(자·바이트)"),
    ("M78-envelope-required-unchecked", "agora/schema.py",
     "    for key in ENVELOPE_REQUIRED:\n        if key not in env:",
     "    for key in ENVELOPE_REQUIRED:\n        if False:",
     "봉투: 결손 3종 → 3(칸 이름)"),
    ("M79-envelope-missing-is-shape-error", "agora/schema.py",
     '    _fail("봉투 필수 칸 누락", {"where": where, "key": key}, errors.GATE_REJECT)',
     '    _fail("봉투 필수 칸 누락", {"where": where, "key": key})',
     "봉투: 결손 3종 → 3(칸 이름)"),
    ("M80-log-excerpt-cap-off", "agora/schema.py",
     "        if len(raw) > MAX_LOG_EXCERPT_BYTES:",
     "        if False:",
     "봉투: 로그 발췌 4KB → 3"),
    ("M81-empty-steps-allowed", "agora/schema.py",
     "    if not steps:",
     "    if False:",
     "봉투: 빈 재현 단계 → 3"),
    ("M82-envelope-check-drops-scrub", "agora/core.py",
     '        if report["blocked"]:',
     "        if False:",
     "봉투: 사유를 모아서 돌려준다"),
    ("M74-broken-rules-file-passes", "agora/scrub.py",
     '        raise AgoraError(errors.GATE_REJECT,\n                         "규칙 파일이 깨졌다 — 전량 차단(fail-closed)",\n                         {"error": str(e)}) from None',
     '        return Rules("empty", [("x", "x", re.compile("(?!x)x"))], "none")',
     "denylist: 규칙 파손 → 3"),
    # ★첫 판(enforce → check)은 **살아남았다**: 게이트를 꺼도 서명기가 같은 code 3 을 낸다.
    #   그래서 이 축의 변이는 「쓰기를 게이트보다 앞에 둔다」로 바꿨다 — 그것이 AC 가 재는 결함이다.
    ("M75-publish-writes-before-gate", "agora/core.py",
     "    report = scrub.enforce(event)              # ⑵ 게이트 — 여기서 막히면 아래로 못 간다",
     '    store.append(thread_id=event["thread_id"], category=category, title="",\n                 body="", is_genesis=False)\n    report = scrub.enforce(event)',
     "쓰기: 차단이면 저장 호출 0"),
    ("M76-name-list-ignored", "agora/scrub.py",
     "            if name in low:",
     "            if False:",
     "scrub: 이름 목록 부재는 보인다"),
    ("M77-names-count-hidden", "agora/scrub.py",
     '        "names_loaded": len(names),',
     '        "names_loaded": 0,',
     "scrub: 이름 목록 부재는 보인다"),
    ("M69-allow-length-unchecked", "agora/scrub.py",
     '        if "max_chars" in spec and len(text) > spec["max_chars"]:',
     "        if False:",
     "allowlist: 필드 상한(자·바이트)"),
    ("M70-allow-forbidden-off", "agora/scrub.py",
     "        for rid, kind, pattern in allow.forbidden:\n            m = pattern.search(text)",
     "        for rid, kind, pattern in []:\n            m = pattern.search(text)",
     "allowlist: 위반 5종 차단"),
    ("M71-allow-url-host-unchecked", "agora/scrub.py",
     "            if not _host_allowed(m.group(1), allow.domains):",
     "            if False:",
     "allowlist: 빈 목록 → 전 URL 차단"),
    ("M72-allow-empty-domains-fail-open", "agora/scrub.py",
     '    host = host.lower().rsplit("@", 1)[-1].split(":", 1)[0]',
     '    if not domains:\n        return True\n    host = host.lower().rsplit("@", 1)[-1].split(":", 1)[0]',
     "allowlist: 빈 목록 → 전 URL 차단"),
    ("M73-allow-missing-file-passes", "agora/scrub.py",
     '        raise AgoraError(errors.GATE_REJECT,\n                         "allowlist 파일을 읽을 수 없다 — 전량 차단(fail-closed)",\n                         {"path": os.path.basename(path), "error": e.strerror}) from None',
     '        return AllowRules("empty", {}, {}, [("x", "x", re.compile("(?!x)x"))], frozenset(), "none")',
     "allowlist: 파일 부재 → 3"),
    ("M66-link-schema-open", "agora/schema.py",
     "    _closed(link, allowed, where)",
     "    pass",
     "관계: 세 필드 위반 → 10"),
    ("M67-spawn-type-unchecked", "agora/schema.py",
     '            if t not in ("problem", "knowhow"):',
     "            if False:",
     "관계: 세 필드 위반 → 10"),
    ("M68-links-always-resolved", "agora/reducer.py",
     '                        "resolved": link["thread_id"] in known_threads})',
     '                        "resolved": True})',
     "관계: 없는 곳을 가리켜도 된다"),
    ("M61-operator-delegate-unconditional", "agora/reducer.py",
     '                if not (who in operators\n                        and is_expired_now(gtype, state["state"], deadlines, now)):',
     "                if not (who in operators):",
     "승계: 운영자는 만료 때만"),
    ("M62-budget-not-enforced", "agora/reducer.py",
     "            if over:\n                reject(entry, BUDGET_EXCEEDED, over)\n                continue",
     "            if False:\n                pass",
     "예산: 사전 검사 없이도 무효"),
    ("M63-budget-hardcoded", "agora/reducer.py",
     "    limits = protocol.load_budget() if budget is None else dict(budget)",
     "    limits = protocol.load_budget()",
     "예산: 설정에서 읽는다"),
    ("M64-budget-chars-ignored", "agora/protocol.py",
     '    if used["chars"] + len(body) > budget["max_chars_per_round"]:',
     "    if False:",
     "예산: 글자 수 상한"),
    ("M65-budget-config-unvalidated", "agora/protocol.py",
     "            if type(value) is not int or value < 0:",
     "            if False:",
     "예산: 설정 값 검증 → 10"),
    ("M55-grace-ignored", "agora/reducer.py",
     "    return _parse_ts(now, \"now\") > _parse_ts(deadline, \"deadline\") + timedelta(seconds=grace)",
     "    return _parse_ts(now, \"now\") > _parse_ts(deadline, \"deadline\")",
     "마감: 유예 안에서는 진행"),
    # ★재조준 2026-08-25: S2-6 에서 만료 판정을 is_expired_now 한 곳으로 모으면서
    #   M56·M57·M59 의 대상 문자열이 옮겨갔다(NOT-APPLIED 3건으로 드러났다).
    ("M56-time-beats-event", "agora/reducer.py",
     '    due = deadlines.get(state_name)',
     '    due = deadlines.get("r0")',
     "마감: 이벤트가 시간을 이긴다"),
    ("M57-delegate-chair-check-off", "agora/reducer.py",
     '            if who != state["chair"]:\n                if not (who in operators',
     '            if False:\n                if not (who in operators',
     "승계: 비의장 위임 → 무효"),
    ("M58-abort-operator-check-off", "agora/reducer.py",
     "            if who not in operators:",
     "            if False:",
     "중단: 운영자 명부만 abort"),
    ("M59-expired-never-fires", "agora/reducer.py",
     '    if is_expired_now(gtype, state["state"], deadlines, now):\n        state["state"] = EXPIRED',
     '    if False:\n        state["state"] = EXPIRED',
     "마감: advance 부재 → expired"),
    ("M60-deadline-rounds-open", "agora/schema.py",
     '        _closed(dl, DEADLINE_ROUNDS, "genesis.deadlines")',
     "        pass",
     "마감: deadlines 표는 닫혀 있다"),
    ("M54-state-hash-ignores-head", "agora/reducer.py",
     '                ("type", "state", "round", "chair", "requester", "solved_by",\n                 "close_reason", "head")}',
     '                ("type", "state", "round", "chair", "requester", "solved_by",\n                 "close_reason")}',
     "상태 해시: 결정론·민감"),
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


def _case_passes_in_subprocess(case_name: str) -> bool:
    """자식 프로세스에서 **지정한 케이스 하나만** 돌린다.

    ★왜 하나만인가(두 가지 이유):
      ⑴ **귀속**. 「스위트가 빨개졌다」는 어느 그물이 잡았는지 말해 주지 않는다.
         변이마다 「이것을 잡아야 할 케이스」를 적어 두고 그 하나만 돌리면,
         KILLED 는 곧 **그 그물이 잡았다**는 뜻이 된다.
      ⑵ **시간**. 전 스위트를 22번 도는 구조는 2분을 넘겨 타임아웃에 잘렸고,
         그 강제 종료가 소스에 변이를 남겼다(실제로 났다). 느린 하네스는 안전하지도 않다.

    -B 로 바이트코드 캐시를 끈다 — 같은 길이 수정이 캐시에 가려지는 것을 막는다.
    판정은 **종료 코드**로만 읽는다(출력 문구 파싱 금지).
    """
    code = (
        "import sys; sys.path.insert(0, %r);"
        "from agora.selftest import _run_one;"
        "sys.exit(0 if _run_one(%r) else 1)"
    ) % (_ROOT, case_name)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    # 픽스처를 물려준다 — 자식이 키를 다시 만들지 않게(실행 시간의 대부분이 그것이었다).
    env[FIXTURE_ENV] = _fixtures()["dir"]
    proc = subprocess.run([sys.executable, "-B", "-c", code], env=env,
                          capture_output=True, text=True, cwd=_ROOT, timeout=120)
    return proc.returncode == 0


def _run_one(case_name: str) -> bool:
    """이름으로 케이스 하나를 돌려 PASS 여부만 돌려준다."""
    for name, fn, expect in CASES:
        if name != case_name:
            continue
        try:
            fn()
        except AgoraError as e:
            return e.code == expect
        except Exception:  # noqa: BLE001
            return False
        return expect is None
    raise SystemExit(2)  # 이름이 틀렸다 — 조용히 통과시키지 않는다


_JOURNAL = os.path.join(_ROOT, ".agora-mutation-journal")


def _recover_leftover() -> dict[str, Any] | None:
    """앞선 실행이 **강제 종료**돼 소스에 변이가 남았으면 복원한다.

    ★`finally` 는 SIGKILL 을 못 이긴다. 실제로 타임아웃 강제 종료가 변이를 남긴 적이 있다.
      그러니 규율(finally)에 더해 **디스크에 원본을 적어 두고** 다음 시작에서 되돌린다.
      그리고 되돌린 사실을 **보고에 남긴다** — 조용히 고치면 아무도 이 일이 있었는지 모른다.
    """
    if not os.path.exists(_JOURNAL):
        return None
    try:
        with open(_JOURNAL, encoding="utf-8") as fh:
            entry = json.load(fh)
        path = os.path.join(_ROOT, entry["file"])
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(entry["original"])
        return {"restored": entry["file"], "mutation": entry["mutation"]}
    except (OSError, ValueError, KeyError) as e:
        return {"restore_failed": str(e)}
    finally:
        if os.path.exists(_JOURNAL):
            os.remove(_JOURNAL)


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
            # ★변이를 쓰기 **전에** 원본을 저널에 남긴다. 여기서 죽어도 다음 실행이 되돌린다.
            with open(_JOURNAL, "w", encoding="utf-8") as jf:
                json.dump({"file": relpath, "mutation": mid, "original": original}, jf)
                jf.flush()
                os.fsync(jf.fileno())
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(original.replace(old, new, 1))
            # ⑵ 변이가 실제로 파일에 있는지 되읽어 확인한다.
            with open(path, encoding="utf-8") as fh:
                if new not in fh.read():
                    rows.append({"mutation": mid, "result": "NOT-APPLIED",
                                 "why": "쓰기 후 재독에서 변이 미발견", "file": relpath,
                                 "killer": killer})
                    continue
            try:
                killed = not _case_passes_in_subprocess(killer)
                rows.append({"mutation": mid,
                             "result": "KILLED" if killed else "SURVIVED",
                             "file": relpath, "killer": killer})
            except subprocess.TimeoutExpired:
                rows.append({"mutation": mid, "result": "NOT-APPLIED",
                             "why": "케이스가 시간 안에 끝나지 않았다(측정 실패)",
                             "file": relpath, "killer": killer})
        finally:
            # ⑷ 무슨 일이 있어도 복원한다 — 그리고 저널을 지운다.
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(original)
            if os.path.exists(_JOURNAL):
                os.remove(_JOURNAL)
    return rows


def run() -> dict[str, Any]:
    recovered = _recover_leftover()
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
        "복구": recovered,
        "요약": {
            "케이스": f"{len(case_rows) - len(case_fail)}/{len(case_rows)} PASS",
            "뮤테이션": f"{len([r for r in mutation_rows if r['result'] == 'KILLED'])}/"
                        f"{len(mutation_rows)} KILLED",
            "미구현_서브커맨드": unbuilt,
            "슬라이스": "S3-5(서명기 재검사·M-11)"
        },
        # ok 는 「이 슬라이스가 자기 몫을 했는가」다.
        # 미발생 오류코드는 다음 슬라이스의 몫이므로 여기서 ok 를 깎지 않는다 —
        # 대신 위 「미측정」 칸에 남아 게이트에서 세어진다.
        "ok": not case_fail and not mut_survived and not mut_notapplied,
    }
    return report
