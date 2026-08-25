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
import subprocess
import sys
import tempfile
from typing import Any

from agora import errors, scrub
from agora.contract_open import KINDS, MAX_EVENT_BYTES, SIGN_NAMESPACE
from agora.errors import AgoraError
from agora.event import canonical_bytes

KEY_ENV = "AGORA_SIGNING_KEY"


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


def handle(request: dict[str, Any]) -> dict[str, Any]:
    if "key" in request or "key_path" in request:
        # 호출자가 키를 지목하려 하면 그 자체가 계약 위반이다.
        raise AgoraError(errors.ARGUMENT,
                         "호출자는 서명 키를 지정할 수 없다",
                         {"hint": KEY_ENV})
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
