"""서명 클라이언트와 검증.

서명은 **여기서 하지 않는다** — `bin/agora-signer` 를 별도 프로세스로 불러 위임한다.
이 모듈에는 개인키를 읽는 코드가 없다(그 사실 자체가 검사 대상이다).

검증은 세 결과를 낸다. 셋을 뭉치면 안 된다:
  · `ok`       — 명부에 있는 키의 서명이고 본문과 맞는다
  · `BAD`      — 서명이 본문과 **안 맞는다**(변조 정황) — 표시만 하고 지우지 않는다
  · `unsigned` — 서명이 없거나, 서명은 유효하지만 **명부 밖 키**다
`BAD` 와 `unsigned` 를 한 칸에 넣으면 「변조됐다」와 「모르는 사람이다」가 구별되지 않는다.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any

from agora import errors
from agora.contract_open import SIGN_NAMESPACE
from agora.errors import AgoraError

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNER_BIN = os.path.join(_ROOT, "bin", "agora-signer")

OK = "ok"
BAD = "BAD"
UNSIGNED = "unsigned"


def sign_event(event: Any, timeout: int = 60,
               config_dir: str | None = None) -> dict[str, Any]:
    """서명기 프로세스에 위임한다. 키 경로는 넘기지 않는다(환경이 정한다).

    ★R3-②(master#238398): 설정 폴더는 **호출별 env** 로 넘긴다 — 절대경로로. 서명기는 저장소 루트
      cwd 로 돌므로 상대경로를 물려주면 코어와 다른 폴더를 본다(codex 라운드 2 재현: 코어는 차단·서명기는 code 0).
      전역 환경을 바꾸지 않는 이유: 한 프로세스의 Context 둘이 서로를 덮었다.
    """
    # ★어느 층이 막았는지 표식(`layer: signer`)은 `_call_signer` 가 단다(R3-②). 코어 스크럽과
    #   서명기 재검사는 같은 code 3 을 내므로, 표식이 없으면 「코어가 안 걸렀는데 서명기가 가려 준」
    #   상태가 초록으로 남는다.
    return _call_signer({"event": event}, timeout=timeout, config_dir=config_dir)


def sign_register(doc: Any, timeout: int = 60,
                  config_dir: str | None = None) -> dict[str, Any]:
    """등록 소유 증명 서명(릴레이 계약 3-1). **같은 서명기 프로세스**에 위임한다.

    ★여기서 직접 `ssh-keygen -Y sign` 을 부르지 않는다 — 이 모듈에 개인키를 읽는 코드가
      없다는 것이 계약이고, 등록이라고 그 계약을 비켜 가면 분리는 그날로 무의미해진다.
    """
    return _call_signer({"register": doc}, timeout=timeout, config_dir=config_dir)


def _call_signer(request: dict[str, Any], *, timeout: int,
                 config_dir: str | None) -> dict[str, Any]:
    env = dict(os.environ)
    if config_dir:
        env["AGORA_CONFIG_DIR"] = os.path.abspath(config_dir)
    proc = subprocess.run(
        [SIGNER_BIN],
        input=json.dumps(request, ensure_ascii=False),
        capture_output=True, text=True, timeout=timeout, cwd=_ROOT, env=env,
    )
    if proc.returncode != 0:
        try:
            payload = json.loads(proc.stderr.strip() or "{}")
        except ValueError:
            payload = {"message": proc.stderr.strip()[:300]}
        detail = payload.get("detail")
        detail = {**detail, "layer": "signer"} if type(detail) is dict else {"layer": "signer"}
        raise AgoraError(
            payload.get("code", errors.SIGNATURE) if payload.get("code") in errors.ALL_CODES
            else errors.SIGNATURE,
            payload.get("message", "서명기 실패"),
            detail,
        )
    return json.loads(proc.stdout)


def _run(cmd: list[str], data: bytes, timeout: int = 30) -> int:
    """rc 만 본다. ★파이프를 거치지 않는다 — 파이프 뒤에서 rc 를 읽으면 남의 rc 를 읽는다."""
    proc = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout)
    return proc.returncode


def _run_capture(cmd: list[str], data: bytes, timeout: int = 30) -> tuple[int, str]:
    proc = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    return proc.returncode, out + err


def _signing_fingerprint(text: str) -> str | None:
    """`check-novalidate` 출력에서 서명 키 지문을 뽑는다.

    실측 출력 예: `Good "ns" signature with ED25519 key SHA256:....`
    """
    for token in text.split():
        if token.startswith("SHA256:"):
            return token.rstrip(",")
    return None


def verify(raw: bytes, signature: str | None, principal: str,
           allowed_signers_path: str, revoked_path: str | None = None) -> str:
    """3값 계약(`ok`/`BAD`/`unsigned`). 사유까지 필요하면 `verify_detail` 을 쓴다."""
    return verify_detail(raw, signature, principal, allowed_signers_path,
                         revoked_path)["verdict"]


def verify_detail(raw: bytes, signature: str | None, principal: str,
                  allowed_signers_path: str,
                  revoked_path: str | None = None) -> dict[str, Any]:
    """세 결과 중 하나를 돌려준다.

    실측 근거(2026-08-25 · 이 기계): `ssh-keygen -Y verify` 는 성공 0 · **실패 255**.
    `-Y check-novalidate` 는 명부 없이 **서명 자체의 유효성**만 본다(정상 0 · 본문 변조 255 ·
    namespace 불일치 255). 이 둘을 겹쳐서 BAD 와 unsigned 를 가른다.
    """
    if not signature or "BEGIN SSH SIGNATURE" not in signature:
        return {"verdict": UNSIGNED, "reason": "no_signature", "fingerprint": None}
    with tempfile.TemporaryDirectory() as tmp:
        sig_path = os.path.join(tmp, "e.sig")
        with open(sig_path, "w", encoding="utf-8") as fh:
            fh.write(signature)

        # ⑴ 서명 자체가 이 바이트에 대해 유효한가? — 명부와 무관한 질문이다.
        rc, out = _run_capture(["ssh-keygen", "-Y", "check-novalidate",
                                "-n", SIGN_NAMESPACE, "-s", sig_path], raw)
        if rc != 0:
            return {"verdict": BAD, "reason": "signature_does_not_match_bytes",
                    "fingerprint": None}
        fingerprint = _signing_fingerprint(out)

        # ⑵ 폐기된 키인가? — 「그때는 유효했다」와 「지금은 무효다」는 다른 사건이다.
        if revoked_path and fingerprint:
            from agora import roster
            if fingerprint in roster._fingerprints_of(revoked_path):
                return {"verdict": UNSIGNED, "reason": "revoked",
                        "fingerprint": fingerprint}

        # ⑶ 이 서명자가 명부에 있는가?
        if not os.path.exists(allowed_signers_path):
            # 명부가 없으면 「모두 ok」가 아니라 「아무도 모른다」다.
            return {"verdict": UNSIGNED, "reason": "no_roster", "fingerprint": fingerprint}
        if _run(["ssh-keygen", "-Y", "verify", "-n", SIGN_NAMESPACE,
                 "-f", allowed_signers_path, "-I", principal, "-s", sig_path], raw) != 0:
            return {"verdict": UNSIGNED, "reason": "not_in_roster",
                    "fingerprint": fingerprint}
        return {"verdict": OK, "reason": "verified", "fingerprint": fingerprint}
