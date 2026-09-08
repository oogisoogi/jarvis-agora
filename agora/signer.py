"""서명기 — 분리된 프로세스에서만 도는 부분.

★왜 분리하는가(설계 H-15): 대표 워커가 읽는 본문에는 주입 문구가 들어올 수 있다.
  그 워커가 개인키 파일에 닿을 수 있으면, 키를 **복사하지 않아도** 서명 신탁(oracle)으로
  부려 임의의 이벤트에 서명시킬 수 있다. 그래서 서명은 **다른 프로세스**가 하고,
  그 프로세스는 시키는 대로 서명하지 않고 **자기 검사 네 개를 스스로 통과시킨 뒤에만** 서명한다.

★키 위치는 **호출자가 정하지 않는다.** 환경(`AGORA_SIGNING_KEY`)이 정한다 —
  호출자가 경로를 넘길 수 있으면 「아무 키로나 서명해 달라」가 가능해져서 분리가 무의미해진다.

자기 검사 4:
  ⑴ canonical — 받은 이벤트가 canonical 로 떨어지는가(그리고 그 바이트에만 서명한다)
  ⑵ scrub    — denylist 를 통과하는가(차단 1건이면 서명하지 않는다)
  ⑶ kind     — 계약이 정한 9종 안인가
  ⑷ 크기      — 상한 안인가
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Any

from agora import errors, scrub
from agora.contract_open import (
    CHECKPOINT_PURPOSE, CHECKPOINT_TIME_PATTERN, KINDS, MAX_EVENT_BYTES,
    REGISTER_PURPOSE, SIGN_NAMESPACE,
)
from agora.errors import AgoraError
from agora.event import canonical_bytes

KEY_ENV = "AGORA_SIGNING_KEY"

# 설치 점검 서명 프로브가 서명하는 바이트의 고정 접두(`selfcheck`).
# ★계약 문서(canonical JSON)와 **겹치지 않는 모양**이어야 한다 — 겹치면 점검용 서명이
#   진짜 문서의 서명으로 재사용될 수 있다. JSON 은 `{` 로 시작하므로 이 접두와 절대 안 겹친다.
PROBE_PREFIX = b"agora-selfcheck-probe-v1:"


def _signing_key_path() -> str:
    path = os.environ.get(KEY_ENV)
    if not path:
        raise AgoraError(errors.PRECONDITION, "서명 키가 지정되지 않았다",
                         {"env": KEY_ENV})
    if not os.path.exists(path):
        raise AgoraError(errors.PRECONDITION, "서명 키 파일이 없다",
                         {"env": KEY_ENV})
    return path


def self_check(event: Any) -> tuple[bytes, dict[str, Any]]:
    """네 검사. 하나라도 걸리면 서명하지 않는다."""
    if type(event) is not dict:
        raise AgoraError(errors.ARGUMENT, "이벤트는 객체여야 한다", None)

    # ⑶ kind — 계약 밖 kind 는 서명 자체를 거부한다.
    kind = event.get("kind")
    if kind not in KINDS:
        raise AgoraError(errors.GATE_REJECT, "계약에 없는 kind",
                         {"kind": kind, "allowed": list(KINDS)})

    # ⑵ scrub — 차단 1건이면 서명 없음 = 전송 없음(서명 없이는 저장층에 못 쓴다).
    report = scrub.enforce(event)

    # ⑴⑷ canonical + 크기 — canonical_bytes 가 상한을 함께 집행한다.
    raw = canonical_bytes(event)
    if len(raw) > MAX_EVENT_BYTES:  # 방어적 이중 확인(상한 검사를 지우는 변이를 여기서도 잡는다)
        raise AgoraError(errors.GATE_REJECT, "이벤트 크기 상한 초과",
                         {"bytes": len(raw), "limit": MAX_EVENT_BYTES})
    return raw, report


def sign_bytes(raw: bytes, key_path: str) -> str:
    """ssh-keygen 에 서명을 위임한다.

    실측(2026-08-25): `ssh-keygen -Y sign -n <ns> -f <키> <파일>` → `<파일>.sig` 생성 · rc 0.
    `<키>` 에 **공개키**를 주면 ssh-agent 가 대신 서명한다(개인키 파일 없이도 됨 — 실측 확인).
    """
    with tempfile.TemporaryDirectory() as tmp:
        msg = os.path.join(tmp, "event.bin")
        with open(msg, "wb") as fh:
            fh.write(raw)
        proc = subprocess.run(
            ["ssh-keygen", "-Y", "sign", "-n", SIGN_NAMESPACE, "-f", key_path, msg],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise AgoraError(errors.SIGNATURE, "서명 실패",
                             {"rc": proc.returncode,
                              "stderr": proc.stderr.strip()[:300]})
        sig_path = msg + ".sig"
        if not os.path.exists(sig_path):
            raise AgoraError(errors.SIGNATURE, "서명 파일이 생성되지 않았다", None)
        with open(sig_path, encoding="utf-8") as fh:
            return fh.read()


# 등록 소유 증명이 서명하는 **정확한 다섯 칸**(릴레이 계약 §3-1 확정본 `docs/RELAY.md@b2ca815`).
# ★★`purpose` 가 **서명 대상 안에** 있다 — 확정본이 canonical 바이트를 다섯 칸으로 못박았다.
#   구판(master 통지 2026-09-05 `[master#283b2c7e]`)은 네 칸이었고, 그대로 두면 우리가 만든
#   서명이 서버 계산과 **다른 바이트**에 대한 것이 되어 등록이 전건 401 로 거부된다.
# ★집합을 **닫아 둔다.** 열어 두면 이 경로가 「kind 검사를 안 지나는 서명 신탁」이 된다 —
#   이벤트를 이 문으로 들이밀면 계약 밖 kind 도 서명되어 나간다.
REGISTER_FIELDS = ("display_name", "fingerprint", "participant_id", "public_key", "purpose")


def self_check_register(doc: Any) -> tuple[bytes, dict[str, Any]]:
    """등록 요청 자기 검사 — 다섯 칸 정확히 · 전부 비지 않은 문자열 · 스크럽 · canonical·상한.

    ★`self_check`(이벤트용)와 **함수를 나눈 이유**: 이벤트 검사는 kind 를 요구하고 등록 요청에는
      kind 가 없다. 같은 함수에 「kind 가 없으면 통과」를 더하면 **그 조건이 곧 우회로**가 된다.
    ★`purpose` 는 **값까지 고정**한다. 칸만 열어 두면 이 문이 「아무 목적이나 서명해 주는 곳」이 되고,
      그러면 여기서 나온 서명을 다른 자리에 재사용할 수 있다 — 목적을 서명 안에 박는 뜻이 사라진다.
    """
    if type(doc) is not dict:
        raise AgoraError(errors.ARGUMENT, "등록 요청은 객체여야 한다", None)
    if tuple(sorted(doc)) != REGISTER_FIELDS:
        raise AgoraError(errors.ARGUMENT, "등록 요청은 계약된 다섯 칸만 가진다",
                         {"got": sorted(doc), "want": list(REGISTER_FIELDS)})
    if doc.get("purpose") != REGISTER_PURPOSE:
        raise AgoraError(errors.ARGUMENT, "등록 소유 증명의 purpose 가 계약값이 아니다",
                         {"got": doc.get("purpose"), "want": REGISTER_PURPOSE})
    for key in REGISTER_FIELDS:
        if type(doc[key]) is not str or not doc[key].strip():
            raise AgoraError(errors.ARGUMENT, "등록 요청 칸은 비지 않은 문자열이어야 한다",
                             {"key": key})
    report = scrub.enforce(doc)
    raw = canonical_bytes(doc)
    if len(raw) > MAX_EVENT_BYTES:
        raise AgoraError(errors.GATE_REJECT, "등록 요청 크기 상한 초과",
                         {"bytes": len(raw), "limit": MAX_EVENT_BYTES})
    return raw, report


# 명부 체크포인트가 서명하는 **정확한 네 칸**(릴레이 계약 §3-6b · `docs/RELAY.md@main`).
# ★등록과 같은 이유로 **닫아 둔다**: 문이 열려 있으면 이 경로가 「아무 문서나 서명해 주는 신탁」이 된다.
CHECKPOINT_FIELDS = ("checkpoint", "purpose", "signed_at", "signer")


def self_check_checkpoint(doc: Any) -> tuple[bytes, dict[str, Any]]:
    """체크포인트 발행 요청 자기 검사 — 네 칸 정확히 · `purpose` 값 고정 · `signed_at` 서식.

    ★`signed_at` 서식을 **서명기에서도** 본다(검증 쪽에도 같은 검사가 있다). 서명은 한 번 나가면
      되돌릴 수 없고, 서식이 어긋난 값을 서명해 보내면 서버가 400 으로 돌려주는데 그때는 이미
      **그 바이트에 대한 유효한 서명이 세상에 존재한다.** 나가기 전에 막는 편이 싸다.
    """
    import re
    if type(doc) is not dict:
        raise AgoraError(errors.ARGUMENT, "체크포인트 요청은 객체여야 한다", None)
    if tuple(sorted(doc)) != CHECKPOINT_FIELDS:
        raise AgoraError(errors.ARGUMENT, "체크포인트 요청은 계약된 네 칸만 가진다",
                         {"got": sorted(doc), "want": list(CHECKPOINT_FIELDS)})
    if doc.get("purpose") != CHECKPOINT_PURPOSE:
        raise AgoraError(errors.ARGUMENT, "체크포인트의 purpose 가 계약값이 아니다",
                         {"got": doc.get("purpose"), "want": CHECKPOINT_PURPOSE})
    for key in CHECKPOINT_FIELDS:
        if type(doc[key]) is not str or not doc[key].strip():
            raise AgoraError(errors.ARGUMENT, "체크포인트 칸은 비지 않은 문자열이어야 한다",
                             {"key": key})
    if not re.match(CHECKPOINT_TIME_PATTERN, doc["signed_at"]):
        raise AgoraError(errors.ARGUMENT, "signed_at 은 밀리초 고정폭 ISO 여야 한다",
                         {"got": doc["signed_at"]})
    report = scrub.enforce(doc)
    raw = canonical_bytes(doc)
    return raw, report


def handle(request: dict[str, Any]) -> dict[str, Any]:
    if "key" in request or "key_path" in request:
        # 호출자가 키를 지목하려 하면 그 자체가 계약 위반이다.
        raise AgoraError(errors.ARGUMENT,
                         "호출자는 서명 키를 지정할 수 없다",
                         {"hint": KEY_ENV})
    if "probe" in request:
        # ★설치 점검용 서명 프로브(`agora selfcheck`). 재는 것은 **서명이 되는가** 하나다:
        #   환경이 키 자리를 알려 줬는가 · 그 파일이 있는가 · 잠기지 않았는가 · 서명 도구가
        #   `-Y sign` 을 아는가. 이 넷이 참가자가 실제로 막히는 자리다.
        # ★서명 대상을 **계약 문서가 아닌 바이트**로 둔다 — canonical JSON 이 아니라 고정 접두
        #   + 난수다. 그래서 이 서명은 이벤트로도 등록으로도 체크포인트로도 **재사용될 수 없다.**
        #   (계약 문서를 프로브로 쓰면 점검 한 번이 재사용 가능한 소유 증명을 하나 만들어 낸다.)
        nonce = (request.get("probe") or {}).get("nonce")
        if type(nonce) is not str or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            raise AgoraError(errors.ARGUMENT, "probe nonce 는 32자리 hex 여야 한다",
                             {"got": type(nonce).__name__})
        raw = PROBE_PREFIX + nonce.encode("ascii")
        signature = sign_bytes(raw, _signing_key_path())
        return {"signature": signature, "namespace": SIGN_NAMESPACE,
                "kind_of_request": "probe"}
    if "register" in request:
        # ★등록 소유 증명(릴레이 계약 3-1) — 이벤트가 아니라서 kind 검사가 없다. 그 대신
        #   **칸 집합을 닫아** 이벤트가 이 문으로 새지 못하게 한다.
        import hashlib as _hashlib
        raw, report = self_check_register(request.get("register"))
        signature = sign_bytes(raw, _signing_key_path())
        return {"hash": _hashlib.sha256(raw).hexdigest(), "signature": signature,
                "scrub": report, "namespace": SIGN_NAMESPACE, "kind_of_request": "register"}
    if "checkpoint" in request:
        # ★명부 체크포인트(릴레이 계약 §3-6b) — 이벤트가 아니므로 kind 검사가 없다.
        #   같은 처방: **칸 집합을 닫는다**(이벤트도 등록도 이 문으로 못 샌다).
        import hashlib as _hashlib
        raw, report = self_check_checkpoint(request.get("checkpoint"))
        signature = sign_bytes(raw, _signing_key_path())
        return {"hash": _hashlib.sha256(raw).hexdigest(), "signature": signature,
                "scrub": report, "namespace": SIGN_NAMESPACE,
                "kind_of_request": "checkpoint"}
    event = request.get("event")
    raw, report = self_check(event)
    signature = sign_bytes(raw, _signing_key_path())
    import hashlib
    return {
        "hash": hashlib.sha256(raw).hexdigest(),
        "signature": signature,
        # ★영수증에 실리는 것은 **서명기가 직접 잰 값**이다(M-11). 발신자 주장은 옆에 나란히 둔다 —
        #   지우지 않는 이유: 「무엇을 주장했는가」가 사후 판정의 증거이기 때문이다.
        "scrub": report,
        "scrub_claim": _claim_of(event),
        "claim_mismatch": _claim_mismatch(event, report),
        "namespace": SIGN_NAMESPACE,
    }


def _claim_of(event: Any) -> dict[str, Any]:
    claim = (event or {}).get("scrub") if type(event) is dict else None
    return claim if type(claim) is dict else {}


def _claim_mismatch(event: Any, report: dict[str, Any]) -> dict[str, Any] | None:
    """발신자 주장과 서명기 측정이 어긋나는가 — **어긋나도 서명은 막지 않는다.**

    ★막지 않는 이유: 규칙 판본이 다르면 정직한 발신자도 다른 digest 를 낸다.
      진짜 위조(차단 대상을 담고도 blocked:0 이라 주장)는 **재검사 자체**가 이미 막는다
      (self_check 의 enforce 가 code 3 을 낸다) — 여기서 하는 일은 **보이게 하는 것**이다.
      수신 측은 이 표시를 보고 자기 규칙으로 다시 잰다(§8 재검사 플래그).
    """
    claim = _claim_of(event)
    if not claim:
        return {"why": "no_claim"}
    diff: dict[str, Any] = {}
    if claim.get("rules") != report.get("bundle"):
        diff["rules"] = {"claimed": claim.get("rules"), "measured": report.get("bundle")}
    if claim.get("blocked") != report.get("blocked"):
        diff["blocked"] = {"claimed": claim.get("blocked"),
                           "measured": report.get("blocked")}
    return diff or None


def main() -> int:
    try:
        request = json.loads(sys.stdin.read() or "{}")
        if type(request) is not dict:
            raise AgoraError(errors.ARGUMENT, "요청은 객체여야 한다", None)
        print(json.dumps(handle(request), ensure_ascii=False, sort_keys=True))
        return errors.OK
    except AgoraError as e:
        print(e.to_json(), file=sys.stderr)
        return e.code
    except ValueError as e:
        err = AgoraError(errors.ARGUMENT, "요청 JSON 파싱 실패", {"error": str(e)})
        print(err.to_json(), file=sys.stderr)
        return err.code
