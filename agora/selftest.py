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
    notkey = os.path.join(d, "not-a-key")
    with open(notkey, "w", encoding="utf-8") as fh:
        fh.write("이건 키가 아니다\n")
    _FIX.update({"dir": d, "key_a": os.path.join(d, "a"), "key_b": os.path.join(d, "b"),
                 "roster": roster, "notkey": notkey, "empty_roster": os.path.join(d, "none")})
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
            "슬라이스": "S1-8(S1 완주)"
        },
        # ok 는 「이 슬라이스가 자기 몫을 했는가」다.
        # 미발생 오류코드는 다음 슬라이스의 몫이므로 여기서 ok 를 깎지 않는다 —
        # 대신 위 「미측정」 칸에 남아 게이트에서 세어진다.
        "ok": not case_fail and not mut_survived and not mut_notapplied,
    }
    return report
