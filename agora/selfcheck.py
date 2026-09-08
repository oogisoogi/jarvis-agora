"""설치 점검 — **이 기계에서 이 클라이언트가 실제로 도는가**(master 결정 2026-09-09 · B안).

`selftest` 와 무엇이 다른가
---------------------------
`selftest` 는 **개발 트리 전용 하네스**다. 케이스와 뮤테이션이 `tests/`·`docs/`·`.appbuild/`
까지 열기 때문에, 배포 꾸러미 안에서는 돌지 않는다(2026-09-09 실측: 꾸러미에서 실행하면
없는 파일을 열다 죽는다). ⇒ 「코드가 옳은가」는 개발 트리의 CI 가 지고,
**「내 기계의 설치가 성립하는가」는 이 명령이 진다.** 둘은 재는 대상이 다르다.

무엇을 재는가 — 여섯 축
-----------------------
축을 참가자가 **실제로 막히는 자리**에서 골랐다(2026-09-09 재현으로 확인한 것들이다).

  ⑴ 꾸러미 무결성  — 담겨 온 파일이 표(`PACKAGE-MANIFEST.json`)와 같은가
  ⑵ 참가자 신원    — `participant.json` 을 계약대로 읽을 수 있는가
  ⑶ 운반층 해석    — 릴레이 주소가 잡히는가
  ⑷ 명부 3종       — 사본이 와 있는가
  ⑸ 서명 키        — 키가 **실제로 서명하는가**(있다와 된다는 다르다)
  ⑹ 릴레이 도달    — 상대가 응답하는가

★⑹까지 **전부 읽기 전용**이다. 이벤트를 쓰지 않고, 원장에 한 줄도 남기지 않고, 명부를 갈지
  않는다. 점검이 상태를 바꾸면 「점검했더니 달라졌다」가 되어 다음 사람이 무엇을 본 것인지 모른다.

세 값과 종료 코드
-----------------
축마다 **통과 / 실패 / 미측정** 셋 중 하나다. ★「미측정」을 통과로 세지 않는다 — 안 잰 것은
안 잰 것이다(잰 것이 없는데 초록이면 그 초록은 아무것도 뜻하지 않는다).

  0 = 여섯 축 전부 통과
  1 = 실패가 하나라도 있다
  3 = 실패는 없는데 미측정이 있다
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import urllib.error
import urllib.request
from typing import Any

from agora.contract_open import SIGN_NAMESPACE
from agora.errors import AgoraError

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MANIFEST_NAME = "PACKAGE-MANIFEST.json"

PASS = "통과"
FAIL = "실패"
UNMEASURED = "미측정"

RC_OK = 0
RC_FAIL = 1
RC_UNMEASURED = 3

# 축의 순서 = 사람이 막히는 순서다. 앞이 무너지면 뒤는 볼 것도 없다.
AXES = ("꾸러미_무결성", "참가자_신원", "운반층_해석", "명부_3종", "서명_키", "릴레이_도달")


def _row(result: str, detail: dict[str, Any] | None = None,
         how: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"결과": result}
    if detail:
        row["상세"] = detail
    if how:
        # ★실패에는 **다음에 할 일**을 함께 적는다. 사람이 읽는 화면이고,
        #   「무엇이 틀렸다」만 있으면 그 사람은 우리에게 물어야 한다.
        row["할일"] = how
    return row


# ── ⑴ 꾸러미 무결성 ──────────────────────────────────────────────────────────

def check_package(root: str | None = None) -> dict[str, Any]:
    """담겨 온 파일이 표와 같은가.

    ★표가 없으면 **미측정**이다(개발 트리에는 표가 없다). 「표가 없으니 통과」로 두면
      표를 지우는 것이 검사를 끄는 방법이 된다.
    ⚠이 축은 **표 자신의 변조는 못 잡는다** — 표를 고치고 파일을 고치면 둘이 맞는다.
      그 축은 꾸러미 전체 sha256(설치기 핀)이 지고, 여기 적어 둔다.
    """
    root = root or _ROOT
    path = os.path.join(root, MANIFEST_NAME)
    if not os.path.exists(path):
        return _row(UNMEASURED, {"why": "내용물 표가 없다 — 개발 트리이거나 꾸러미가 아니다",
                                 "file": MANIFEST_NAME})
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        files = doc["files"]
        if type(files) is not dict:
            raise ValueError("files 가 객체가 아니다")
    except (OSError, ValueError, KeyError) as e:
        return _row(FAIL, {"why": "내용물 표를 읽지 못했다", "error": str(e)[:200]},
                    "꾸러미를 다시 받아라(설치 한 줄을 다시 돌리면 된다).")

    missing: list[str] = []
    changed: list[str] = []
    for rel, want in sorted(files.items()):
        full = os.path.join(root, rel)
        if not os.path.exists(full):
            missing.append(rel)
            continue
        with open(full, "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != want:
                changed.append(rel)
    detail = {"표에_적힌_파일": len(files), "없는_파일": missing, "달라진_파일": changed,
              "판본": doc.get("version"),
              "note": "표 자신의 변조는 이 축이 못 잡는다 — 그 축은 꾸러미 전체 sha256 이 진다"}
    if missing or changed:
        return _row(FAIL, detail, "꾸러미를 다시 받아라(설치 한 줄을 다시 돌리면 된다).")
    return _row(PASS, detail)


# ── ⑵ 참가자 신원 ────────────────────────────────────────────────────────────

def check_participant(directory: str) -> dict[str, Any]:
    from agora.participant import load
    try:
        doc = load(directory)
    except AgoraError as e:
        return _row(FAIL, {"code": e.code, "message": e.message, "detail": e.detail},
                    "설치 한 줄을 다시 돌려라 — 참가자 신원 파일은 설치가 만든다.")
    return _row(PASS, {"id": doc["id"], "operator": doc["operator"],
                       "key_fingerprint": doc["key_fingerprint"]})


# ── ⑶ 운반층 해석 ────────────────────────────────────────────────────────────

def check_transport(directory: str) -> dict[str, Any]:
    from agora.tools import load_config, transport_of
    cfg = load_config(directory)
    url = (cfg.get("relay") or {}).get("url")
    transport = None
    try:
        transport = transport_of(cfg)
    except AgoraError as e:
        return _row(FAIL, {"code": e.code, "message": e.message},
                    "설정 파일에 릴레이 주소가 없다 — 설치 한 줄을 다시 돌려라.")
    if transport == "relay" and not url:
        return _row(FAIL, {"transport": transport, "relay": None},
                    "설정 파일에 릴레이 주소가 없다 — 설치 한 줄을 다시 돌려라.")
    return _row(PASS, {"transport": transport, "relay": url,
                       # 승인 겹의 상태를 여기에도 적는다 — 꺼진 것은 볼 때마다 보여야 한다.
                       "사람_승인_겹": "켜짐" if cfg.get("human_approval", True) is not False
                       else "꺼짐(설정이 껐다)"})


# ── ⑷ 명부 3종 ───────────────────────────────────────────────────────────────

def check_roster(directory: str) -> dict[str, Any]:
    from agora import roster as roster_mod
    from agora.onboard import ROSTER_FILES
    view: dict[str, Any] = {}
    absent: list[str] = []
    for name in ROSTER_FILES:
        path = os.path.join(directory, name)
        present = os.path.exists(path)
        if not present:
            absent.append(name)
        lines = 0
        if present:
            with open(path, encoding="utf-8") as fh:
                lines = len([ln for ln in fh.read().splitlines()
                             if ln.strip() and not ln.lstrip().startswith("#")])
        view[name] = {"있음": present, "줄": lines}
    digest = roster_mod.checkpoint(paths={
        f"participants/{n}": os.path.join(directory, n) for n in ROSTER_FILES})
    view["체크포인트"] = digest
    if absent:
        return _row(FAIL, {**view, "없는_것": absent},
                    "명부 사본을 받아라: agora sync-roster")
    return _row(PASS, view)


# ── ⑸ 서명 키 — 실제로 서명해 본다 ───────────────────────────────────────────

def check_signing(directory: str) -> dict[str, Any]:
    """**서명을 한 번 해 본다.** 파일이 있는지 보는 것으로는 이 축을 못 잰다.

    ★막히는 자리가 넷이고 모양이 다 다르다: 환경이 키 자리를 안 알려 줬다 · 파일이 없다 ·
      키에 암호가 걸려 있다 · 서명 도구가 `-Y sign` 을 모른다. 넷 다 「서명해 보기」 한 번에 갈린다.
    ★서명하는 바이트는 **계약 문서가 아니다**(고정 접두 + 난수). 그래서 이 점검이
      재사용 가능한 소유 증명을 만들어 내지 않는다.
    """
    from agora import sign as sign_mod
    from agora.signer import KEY_ENV, PROBE_PREFIX
    nonce = secrets.token_hex(16)
    try:
        out = sign_mod._call_signer({"probe": {"nonce": nonce}},
                                    timeout=60, config_dir=directory)
    except AgoraError as e:
        return _row(FAIL, {"code": e.code, "message": e.message, "detail": e.detail,
                           "env": KEY_ENV},
                    "설치 한 줄을 다시 돌려라 — 서명 열쇠와 그 자리를 설치가 마련한다.")
    except OSError as e:
        return _row(FAIL, {"why": "서명기를 실행하지 못했다", "error": str(e)[:200]},
                    "꾸러미를 다시 받아라(설치 한 줄을 다시 돌리면 된다).")
    signature = out.get("signature")
    if type(signature) is not str or "SSH SIGNATURE" not in signature:
        return _row(FAIL, {"why": "서명기가 서명을 돌려주지 않았다"},
                    "꾸러미를 다시 받아라(설치 한 줄을 다시 돌리면 된다).")
    # ★돌려받은 서명을 **실제로 검증까지 한다.** 서명 문자열이 왔다는 것과 그것이 유효하다는
    #   것은 다른 일이고, 여기서 안 재면 그 차이를 아무도 안 잰다.
    verdict = _verify_probe(PROBE_PREFIX + nonce.encode("ascii"), signature)
    if verdict != "ok":
        return _row(FAIL, {"why": "만든 서명이 검증을 통과하지 못했다", "verdict": verdict},
                    "설치 한 줄을 다시 돌려라.")
    return _row(PASS, {"namespace": out.get("namespace"), "검증": "ok",
                       "note": "계약 문서가 아닌 바이트에 서명했다 — 이 서명은 다른 자리에 못 쓴다"})


def _verify_probe(raw: bytes, signature: str) -> str:
    """서명 주체를 묻지 않고 **서명 자체가 유효한지**만 본다(`check-novalidate`).

    ★명부 대조를 여기서 하지 않는 이유: 갓 설치한 참가자는 아직 명부에 없을 수 있고,
      그때 이 축이 붉어지면 사람은 **서명이 안 된다고 읽는다.** 명부 문제는 ⑷ 축이 진다.
    """
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        sig = os.path.join(tmp, "probe.sig")
        with open(sig, "w", encoding="utf-8") as fh:
            fh.write(signature)
        proc = subprocess.run(
            ["ssh-keygen", "-Y", "check-novalidate", "-n", SIGN_NAMESPACE, "-s", sig],
            input=raw, capture_output=True, timeout=30)
        return "ok" if proc.returncode == 0 else (
            (proc.stderr or b"").decode("utf-8", "replace").strip()[:200] or "rc!=0")


# ── ⑹ 릴레이 도달 — 읽기만 한다 ──────────────────────────────────────────────

def check_relay(directory: str, *, timeout: int = 15) -> dict[str, Any]:
    """상대가 응답하는가. **GET 하나만** 쏜다 — 쓰기도 등록도 하지 않는다.

    ★고른 경로가 명부 사본인 이유: 이미 공개된 읽기 자원이고, 설치기도 같은 것을 받는다.
      「상대가 살아 있는가」를 재려고 새 자원을 만들지 않는다.
    """
    from agora.tools import load_config
    cfg = load_config(directory)
    url = (cfg.get("relay") or {}).get("url")
    if not url:
        return _row(UNMEASURED, {"why": "릴레이 주소를 몰라 물어볼 곳이 없다"})
    target = url.rstrip("/") + "/participants/allowed_signers"
    # ★UA 를 **클라이언트 것과 같은 하나에서** 가져온다. 이름을 대지 않으면 라이브 릴레이가
    #   403(Cloudflare 1010)을 준다 — 실측으로 확인한 자리다(`store_relay.USER_AGENT` 주석).
    #   ⚠여기에 문자열을 따로 적으면 언젠가 둘이 갈리고, 그날 이 축은 **상대가 멀쩡한데 실패**를 낸다
    #     (이 코드를 처음 쓸 때 실제로 그랬다: 다른 축은 다 통과인데 릴레이만 403 이었다).
    from agora.store_relay import USER_AGENT
    req = urllib.request.Request(target, method="GET",
                                 headers={"User-Agent": USER_AGENT, "Accept": "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.status
            body = resp.read(64 * 1024)
    except urllib.error.HTTPError as e:
        return _row(FAIL, {"url": target, "http": e.code},
                    "잠시 뒤 다시 해 보고, 계속 같으면 알려 달라.")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        # ★「못 갔다」와 「가서 거절당했다」를 가른다 — 사람이 할 일이 다르다
        #   (앞은 네트워크·차단, 뒤는 우리 쪽 문제다).
        return _row(FAIL, {"url": target, "why": "상대에 닿지 못했다",
                           "error": str(getattr(e, "reason", e))[:200]},
                    "인터넷 연결과 회사·백신의 차단을 확인하고 다시 해 보라.")
    return _row(PASS, {"url": target, "http": code, "bytes": len(body)})


# ── 묶어서 ───────────────────────────────────────────────────────────────────

def run(*, directory: str | None = None, root: str | None = None,
        relay: bool = True) -> dict[str, Any]:
    from agora.participant import config_dir
    directory = os.path.abspath(directory or config_dir())
    root = root or _ROOT

    axes: dict[str, Any] = {}
    axes["꾸러미_무결성"] = check_package(root)
    axes["참가자_신원"] = check_participant(directory)
    # 앞 축이 무너졌으면 뒤 축은 그 무너짐을 다시 보고할 뿐이다 — 그래도 **돌린다.**
    # 건너뛰면 「미측정」이 되는데, 여기서는 무엇이 되고 무엇이 안 되는지를 한 번에 보여야 한다.
    axes["운반층_해석"] = check_transport(directory)
    axes["명부_3종"] = check_roster(directory)
    axes["서명_키"] = check_signing(directory)
    axes["릴레이_도달"] = (check_relay(directory) if relay else
                       _row(UNMEASURED, {"why": "--no-relay 로 껐다 — 상대에 물어보지 않았다"}))

    results = [axes[a]["결과"] for a in AXES]
    failed = [a for a in AXES if axes[a]["결과"] == FAIL]
    unmeasured = [a for a in AXES if axes[a]["결과"] == UNMEASURED]
    if failed:
        rc = RC_FAIL
    elif unmeasured:
        rc = RC_UNMEASURED
    else:
        rc = RC_OK
    return {
        # ★판정을 맨 위에 둔다 — 아래로 내리면 사람은 축 여섯 개를 읽다 지쳐 그냥 초록으로 읽는다.
        "판정": {"종료코드": rc,
               "요약": f"통과 {results.count(PASS)} · 실패 {len(failed)} · 미측정 {len(unmeasured)}",
               "실패한_축": failed, "미측정_축": unmeasured,
               "note": "미측정은 통과가 아니다 — 안 잰 것은 안 잰 것이다"},
        "설정_폴더": directory,
        "축": axes,
    }


def main(argv: list[str] | None = None) -> dict[str, Any]:
    """CLI 진입점. 종료 코드는 `cli` 가 판정 칸에서 읽는다."""
    argv = list(argv or [])
    return run(relay="--no-relay" not in argv)
