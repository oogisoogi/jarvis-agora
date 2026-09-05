"""명부와 키 수명주기 — 「이 서명을 누가 했고, 그 사람이 지금도 유효한가」.

세 파일이 한 벌이다(설계 §7·§2-1a):
  · `participants/allowed_signers` — 누가 참가자인가
  · `participants/revoked_keys`    — 어느 키가 폐기됐는가(평문 공개키 목록)
  · `participants/operators`       — 누가 운영자인가(`abort`·체크포인트 서명 권한)

★셋의 **체크포인트 해시**를 이벤트에 실어 보낸다. 그래야 「그때의 명부로는 유효했다」와
  「지금 명부로는 무효다」를 나중에 구별할 수 있다. 명부는 시간에 따라 바뀌는데
  서명은 과거에 일어난 일이기 때문이다.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Any

from agora import errors
from agora.contract_open import (
    CHECKPOINT_PURPOSE, CHECKPOINT_TIME_PATTERN,
    ROSTER_ALLOWED_SIGNERS, ROSTER_OPERATORS, ROSTER_REVOKED_KEYS,
)
from agora.errors import AgoraError

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(root: str, rel: str) -> str:
    return os.path.join(root, rel)


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        # 없는 것도 상태다 — 빈 바이트로 취급하되, 체크포인트에는 그 사실이 반영된다.
        return b""


def checkpoint(root: str | None = None, *, paths: dict[str, str] | None = None) -> str:
    """명부 3종의 내용 해시. 파일 하나만 바뀌어도 값이 바뀐다.

    ★`paths` = 논리 이름(`participants/…`) → **실제 파일 경로**. 참가자 기계의 사본은
      설정 폴더에 **납작한 이름**(`allowed_signers` …)으로 놓이기 때문이다(ONBOARDING §파일).
      ⚠해시에 넣는 **이름표는 논리 이름 그대로** 둔다 — 그래야 저장소 배치와 설정 폴더 배치가
      **같은 내용에 같은 값**을 낸다. 경로를 이름표로 쓰면 기계마다 다른 값이 나와 대조가 불가능해진다.
    """
    root = root or _ROOT
    paths = paths or {}
    h = hashlib.sha256()
    for rel in (ROSTER_ALLOWED_SIGNERS, ROSTER_REVOKED_KEYS, ROSTER_OPERATORS):
        blob = _read(paths.get(rel) or _path(root, rel))
        # 파일 경계를 해시에 넣는다 — 안 넣으면 A의 끝과 B의 시작을 옮겨도 같은 해시가 된다.
        h.update(rel.encode("utf-8"))
        h.update(len(blob).to_bytes(8, "big"))
        h.update(blob)
    return h.hexdigest()


def operators(root: str | None = None, *, path: str | None = None) -> frozenset[str]:
    """운영자 목록(K-3).

    ★`path` 로 **파일을 직접** 줄 수 있다. 참가자는 저장소를 체크아웃한 채 도는 것이 아니라
      설정 폴더에 명부 **사본**을 두고 돌기 때문이다(ONBOARDING §파일). 그 경로를 못 주면
      이 함수는 저장소 루트만 볼 수 있고, 그러면 **실사용에서 운영자가 0명**이 된다 —
      그 상태로도 아무 오류가 안 난다(`abort` 할 수 있는 사람이 없을 뿐이다).
    """
    text = _read(path or _path(root or _ROOT, ROSTER_OPERATORS)).decode("utf-8", "replace")
    return frozenset(
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _has_key_lines(path: str) -> bool:
    """주석·빈 줄 말고 **키가 한 줄이라도** 있는가."""
    text = _read(path).decode("utf-8", "replace")
    return any(line.strip() and not line.lstrip().startswith("#")
               for line in text.splitlines())


def _fingerprints_of(path: str) -> frozenset[str]:
    """공개키 파일의 지문 집합. 파일이 없거나 **키가 한 줄도 없으면** 공집합이다.

    ★★「키가 없는 파일」과 「못 읽는 파일」을 가른다(2026-08-26 실물에서 터졌다).
      `ssh-keygen -l -f` 는 **주석뿐인 파일**에 `is not a public key file` 로 실패한다.
      그런데 이 저장소의 `participants/revoked_keys` 정본이 바로 그 모양이다(설명 주석 3줄) —
      즉 **명부를 문서대로 복사한 참가자는 모든 읽기가 code 2 로 죽었다.**
    ⚠그렇다고 실패를 통째로 삼키면 안 된다. 삼키는 순간 **폐기가 조용히 꺼지고**,
      그것이 이 파일이 막으려는 바로 그 사고다. 그래서 **키 줄이 있을 때의 실패만** 올린다.
    """
    if not os.path.exists(path):
        # ★★H2(codex 2026-08-26 · R-14) — **부재는 「폐기된 키가 없다」가 아니다.**
        #   예전에는 여기서 공집합을 돌려줬다. 그러면 **파일 하나를 지우는 것이 곧
        #   폐기 목록 전체를 끄는 방법**이 된다 — 그리고 아무 표시도 나지 않는다.
        #   이 파일이 막으려는 사고(폐기 키로 서명한 글이 유효로 읽히는 것)가 정확히
        #   그 상태에서 난다. ⇒ **못 읽으면 멈춘다**(fail-closed).
        # ⚠「비어 있다」를 말하고 싶으면 **파일을 만들어라** — 주석만 있어도 된다.
        #   그것이 「없다」와 「비었다」를 가르는 유일한 방법이다.
        raise AgoraError(errors.PRECONDITION, "폐기 목록 파일이 없다 — 비었음은 빈 파일로 말한다",
                         {"file": os.path.basename(path),
                          "how": "빈 파일이나 주석만 있는 파일을 두면 「폐기된 키 0건」으로 읽는다"})
    if os.path.getsize(path) == 0:
        return frozenset()          # 있는데 비었다 = 명시적 0건
    if not _has_key_lines(path):
        return frozenset()          # 주석뿐 = 명시적 0건(위 docstring 의 실사고)
    proc = subprocess.run(["ssh-keygen", "-l", "-f", path],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AgoraError(errors.PRECONDITION, "폐기 목록을 읽을 수 없다",
                         {"stderr": proc.stderr.strip()[:200]})
    out: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        for p in parts:
            if p.startswith("SHA256:"):
                out.add(p)
    return frozenset(out)


def principals(root: str | None = None, *, path: str | None = None) -> frozenset[str]:
    """명부에 이름이 올라 있는 참가자 id 들(`allowed_signers` 첫 칸).

    ★**검증이 아니다.** 서명 검증은 `ssh-keygen -Y verify` 가 하고, 이 함수는 「내 id 가
      명부에 보이는가」를 사람에게 알려 주기 위한 것이다(`join`·`whoami`).
      이 값으로 판정을 내리면 명부를 손으로 고친 사람이 자기를 통과시키게 된다.
    ★`allowed_signers` 는 `<principal> <keytype> <key...>` 형식이고, principal 자리에는
      쉼표로 여럿이 올 수 있다(OpenSSH 문법) — 그래서 쉼표로 한 번 더 가른다.
    """
    text = _read(path or _path(root or _ROOT, ROSTER_ALLOWED_SIGNERS)).decode("utf-8", "replace")
    out: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        first = line.split()[0]
        out.update(p for p in first.split(",") if p)
    return frozenset(out)


def allowed_signers_path(root: str | None = None) -> str:
    return _path(root or _ROOT, ROSTER_ALLOWED_SIGNERS)



# ── 명부 체크포인트 검증 (릴레이 계약 §3-6b · RL-6 · 2026-09-06 확정) ────────

CHECKPOINT_FIELDS = ("checkpoint", "purpose", "signed_at", "signer")

# 미래 쪽 허용 창(시간). 시계 오차·시간대 실수는 이 안에서 흡수하고, 그보다 먼 미래는 사고로 본다.
FUTURE_GRACE_HOURS = 24


def _plus_hours(stamp: str, hours: int) -> str:
    """고정폭 ISO 시각에 시간을 더한다 — 문자열 비교가 시간 비교가 되는 서식을 유지한다."""
    import datetime
    base = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=datetime.timezone.utc)
    later = base + datetime.timedelta(hours=hours)
    return later.strftime("%Y-%m-%dT%H:%M:%S.") + f"{later.microsecond // 1000:03d}Z"


def checkpoint_canonical(doc: Any) -> bytes:
    """체크포인트 서명 대상 바이트 — **네 칸을 우리가 다시 만든다**(계약 §3-6b).

    ★서버가 준 문서를 그대로 서명 대상으로 쓰지 않는다: 받은 것에는 `current`·`stale` 처럼
      **서버가 지어낸 칸**이 섞여 있고, 그것까지 서명 대상에 넣으면 서명이 릴레이의 말에
      의존하게 된다. 서명이 덮는 범위는 **계약이 정한 네 칸**뿐이다.
    ★`purpose` 를 안에 박는 이유는 등록(§3-1)과 같다 — 이 서명을 다른 자리에 재사용할 수 없게.
    """
    from agora.event import canonical_bytes
    return canonical_bytes({
        "checkpoint": doc.get("checkpoint"), "purpose": CHECKPOINT_PURPOSE,
        "signed_at": doc.get("signed_at"), "signer": doc.get("signer")})


def verify_checkpoint(doc: Any, *, allowed_signers_path: str, operators_path: str,
                      revoked_path: str | None = None,
                      local_checkpoint: str | None = None,
                      last_signed_at: str | None = None,
                      now: str | None = None) -> dict[str, Any]:
    """운영자 서명 체크포인트를 **실제로 검증한다**(계약 §3-6b · RL-6 해소).

    판정은 세 관문을 **순서대로** 지난다. 순서가 곧 사유의 정확도다:
      ⑴칸·서식 — 네 칸이 문자열이고 `signed_at` 이 밀리초 고정폭 ISO 인가(계약 §3-0).
      ⑵**principal** — 서명자가 `operators` 명부에 있는가. 없으면 서명이 유효해도 **권한이 없다**
        (참가자 아무나 명부 사진을 찍어 「이게 지금 명부다」라고 말할 수 있으면 이 칸은 무의미하다).
      ⑶서명 — 네 칸 canonical 바이트에 대한 서명이고, 그 키가 `allowed_signers` 의 **그 이름**의
        키이며 폐기되지 않았는가(`ssh-keygen -Y verify -I <signer>`).
    ★**되돌리기(rollback)는 잡는다**(agy 적대검증 2026-09-06 지적 · 부분 수용): 서명이 유효해도
      `signed_at` 이 **내가 이미 본 것보다 과거**면 거부한다(`signed_at_regressed`). 서명은 과거의
      사실이라 옛 문서를 다시 내놓는 것만으로 명부를 되돌릴 수 있고, 그때 `matches_local:false` 는
      「명부가 자랐다」와 구별되지 않는다 — **단조 증가**가 그 둘을 가르는 유일한 축이다.
      ⚠**절대 시각 유예(「최근이어야 한다」)는 두지 않았다**(같은 지적의 나머지 절반 · 반박):
      체크포인트는 운영자가 **가끔** 서명하는 값이라 계약이 「대부분의 시간 stale」이라고 못박았다.
      「며칠 지났으면 무효」 규칙은 정상 운영을 상시 경보로 만들고, 경보는 그날로 무시되기 시작한다.
      되돌리기는 **우리가 본 것과의 비교**로 잡히므로 시계에 기대지 않는다.
    ★`checkpoint` 값이 **내 사본과 다른 것은 실패가 아니다**(`matches_local: false`).
      명부는 새 등록으로 계속 자라므로 체크포인트는 **대부분의 시간 stale 이다**(계약 §3-6b).
      「서명이 유효한가」와 「지금 명부와 같은가」는 다른 질문이고, 섞으면 정상 상태가 경보가 된다.
    """
    import re

    from agora import sign
    if type(doc) is not dict:
        return {"verified": False, "why": "not_a_document", "signer": None}
    signer = doc.get("signer")
    signature = doc.get("signature")
    # ★`signature` 도 **타입부터** 본다(agy 적대검증 2026-09-06 지적 · 수용): 숫자가 오면
    #   `verify_detail` 안의 `in` 검사가 TypeError 로 터진다 — 못 믿을 문서는 **우아하게 거부**해야지
    #   프로그램이 죽는 것으로 답하면 안 된다(죽음은 판정이 아니다).
    for key in ("checkpoint", "signed_at", "signer", "signature"):
        if type(doc.get(key)) is not str or not doc[key].strip():
            return {"verified": False, "why": f"missing_field:{key}", "signer": signer}
    if not re.match(CHECKPOINT_TIME_PATTERN, doc["signed_at"]):
        # ★서식을 여기서 막는 이유: 서명 대상 **안에** 있는 값이라, 서식이 흔들리면
        #   같은 시각이 두 문자열로 서명될 수 있다(대조가 그때부터 운에 맡겨진다).
        return {"verified": False, "why": "signed_at_format", "signer": signer}
    if signer not in operators(path=operators_path):
        return {"verified": False, "why": "signer_not_operator", "signer": signer}
    if now and doc["signed_at"] > _plus_hours(now, FUTURE_GRACE_HOURS):
        # ★★**미래로 너무 멀리 간 값은 기준으로 삼지 않는다**(agy 적대검증 2026-09-06 지적 · 수용).
        #   시계가 틀어진 기계가 「1년 뒤」를 서명해 올리면, 단조 규칙이 그 값을 기준선으로 삼아
        #   **그 뒤의 정상 발행을 영원히 거부**한다(영구 잠금). 그래서 미래 쪽에만 창을 둔다.
        #   ⚠과거 쪽에는 창을 두지 않는다(agy r3 에서 반박한 그 규칙이다): 체크포인트는 계약상
        #   「대부분 stale」이라 「오래됐으면 무효」는 정상 운영을 상시 경보로 만든다.
        #   **두 규칙이 비대칭인 것이 맞다** — 과거는 정상이고, 먼 미래는 시계 사고다.
        return {"verified": False, "why": "signed_at_in_future", "signer": signer,
                "signed_at": doc["signed_at"], "now": now}
    if last_signed_at and doc["signed_at"] < last_signed_at:
        # ★고정폭 ISO 라 문자열 비교가 곧 시간 비교다(계약 §3-0 이 그 서식을 고른 이유).
        return {"verified": False, "why": "signed_at_regressed", "signer": signer,
                "signed_at": doc["signed_at"], "last_signed_at": last_signed_at}
    detail = sign.verify_detail(checkpoint_canonical(doc), signature, signer,
                                allowed_signers_path, revoked_path)
    out: dict[str, Any] = {"verified": detail["verdict"] == sign.OK,
                           "why": detail["reason"], "verdict": detail["verdict"],
                           "signer": signer, "signed_at": doc["signed_at"]}
    if local_checkpoint is not None:
        # 대조는 하되 **판정에 넣지 않는다** — 다르면 「그 뒤에 명부가 자랐다」가 정상 해석이다.
        out["matches_local"] = doc["checkpoint"] == local_checkpoint
    return out
