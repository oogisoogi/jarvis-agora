"""가입·명부 동기화·자기 확인 — **운영 동작 3종**(도구가 아니다).

★도구 표(`tools.CORE_TOOLS`)에 넣지 않는다. 넣으면 MCP 표면에 올라가고, 대리인 세션 손에
  「명부를 갈아라」·「등록을 다시 해라」가 쥐어진다 — 그건 참가자가 아니라 **설치·운영**이 할 일이다.
  (`mcp-serve`·`delegate-chair`·`abort` 를 CLI 전용으로 둔 것과 같은 이유.)

★설치 도우미 [11/11] 이 부르는 한 줄(06 §4 J4):
      agora keygen <id> && agora register --relay <url> --unattended && agora sync-roster --yes
  ⚠`--unattended` 를 **일부러 손으로 쓰게** 했다. 그 플래그가 하는 일은
  **사람 승인 겹을 끄는 것**(`human_approval:false`)이고, 그런 결정이 기본값에 숨으면 안 된다.
  끈 사실은 `whoami` 첫 줄에 **상시 표시**된다(master 결정 2026-09-05 · RC-2).
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from agora import errors, roster
from agora.contract_open import REGISTER_PURPOSE
from agora.errors import AgoraError
from agora.keygen import KEY_NAME
from agora.participant import FILENAME as PARTICIPANT_FILENAME
from agora.participant import config_dir, load

CONFIG_FILENAME = "config.json"
ROSTER_FILES = ("allowed_signers", "revoked_keys", "operators")
CHECKPOINT_FILENAME = "roster-checkpoint.json"


def _relay(url: str) -> Any:
    from agora.store_relay import RelayStore
    return RelayStore(url)


def _config_path(directory: str) -> str:
    return os.path.join(directory, CONFIG_FILENAME)


def _write_json(path: str, doc: Any, *, mode: int = 0o600) -> None:
    """임시 파일 → `os.replace`. 중간에 죽어도 **반쪽 파일이 남지 않는다.**"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, sort_keys=True, indent=2)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _load_config(directory: str) -> dict[str, Any]:
    from agora.tools import load_config
    return load_config(directory)


def _sha256_file(path: str) -> str | None:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def _lines(text: str) -> list[str]:
    """주석·빈 줄을 뺀 실제 내용 줄. 명부 차이는 **이 단위**로 말한다."""
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


# ── register ────────────────────────────────────────────────────────────────

def register(*, directory: str | None = None, relay_url: str,
             unattended: bool = False) -> dict[str, Any]:
    """공개키를 릴레이에 등록하고 설정에 릴레이 주소를 적는다.

    ★**키를 만들지 않는다**(그건 `keygen` 이다). 이미 있는 공개키·지문을 올릴 뿐이다.
    ★소유 증명(릴레이 계약 3-1): 등록하려는 **그 키로** 네 칸을 서명해 함께 보낸다.
      서명은 서명기 프로세스가 한다 — 여기에는 개인키를 읽는 코드가 없다.
    """
    from agora import sign
    directory = os.path.abspath(directory or config_dir())
    doc = load(directory)
    pub_path = os.path.join(directory, KEY_NAME + ".pub")
    if not os.path.exists(pub_path):
        raise AgoraError(errors.PRECONDITION, "공개키 파일이 없다 — 먼저 keygen 을 하라",
                         {"file": KEY_NAME + ".pub"})
    with open(pub_path, encoding="utf-8") as fh:
        public_key = fh.read().strip()
    # ★다섯 칸 — `purpose` 가 **서명 대상 안**이다(릴레이 계약 §3-1 확정본 @b2ca815).
    #   서버는 이 문서를 canonical 로 다시 만들어 그 바이트에 서명을 본다: 칸이 하나 모자라면
    #   서명은 유효한데 **다른 문서의 서명**이 되어 401 이 난다.
    claim = {"display_name": doc["display_name"], "fingerprint": doc["key_fingerprint"],
             "participant_id": doc["id"], "public_key": public_key,
             "purpose": REGISTER_PURPOSE}
    signed = sign.sign_register(claim, config_dir=directory)
    out = _relay(relay_url).register(
        participant_id=claim["participant_id"], display_name=claim["display_name"],
        public_key=claim["public_key"], fingerprint=claim["fingerprint"],
        signature=signed["signature"])

    cfg = _load_config(directory)
    cfg["transport"] = "relay"
    relay_cfg = dict(cfg.get("relay") or {})
    relay_cfg["url"] = relay_url
    cfg["relay"] = relay_cfg
    if unattended:
        # ★사람 승인 겹을 끈다. **숨기지 않는다** — whoami 첫 줄에 상시 표시된다.
        cfg["human_approval"] = False
    _write_json(_config_path(directory), cfg)
    return {"participant_id": claim["participant_id"], "relay": relay_url,
            "transport": "relay", "registered": bool(out.get("registered", True)),
            "proof_hash": signed["hash"],
            "human_approval": cfg.get("human_approval", True),
            "config_file": CONFIG_FILENAME,
            "다음": ["agora sync-roster 로 명부 3종 사본을 받는다",
                   "agora whoami 로 확인한다"]}


# ── sync-roster ─────────────────────────────────────────────────────────────

def sync_roster(*, directory: str | None = None, relay_url: str | None = None,
                yes: bool = False) -> dict[str, Any]:
    """명부 3종 사본을 릴레이에서 받는다 — **첫 번째는 그대로, 그 뒤 변경은 확인받고.**

    ★TOFU + 변경 승인(master 결정 2026-09-05 · RC-1). 명부의 정본이 운반층으로 옮겨 갔으므로,
      릴레이가 한 줄을 더 넣으면 그 키의 서명이 유효해진다. 첫 sync 는 신뢰의 시작점이라
      대조할 것이 없지만(어떤 방식에서도 그렇다), **그 뒤의 변화는 사람이 봐야 한다.**
    ★차이가 있는데 `--yes` 가 없으면 **아무것도 쓰지 않고** code 3 으로 멈춘다.
      반쪽만 갱신하는 것보다 안 하는 것이 낫다.
    ⚠**진짜 원자성은 없다**(파일이 셋이다 · agy 적대검증 2026-09-05 정정): 임시 파일 3개를 먼저 쓰므로
      받기·쓰기 실패는 실물을 안 건드리지만 **교체 3회 사이의 창**은 남는다. 그 창에서 죽으면
      code 7 에 `wrote`(이미 바뀐 파일)·`failed` 를 실어 올린다 — 숨기지 않는다.
    """
    directory = os.path.abspath(directory or config_dir())
    cfg = _load_config(directory)
    url = relay_url or (cfg.get("relay") or {}).get("url")
    if not url:
        raise AgoraError(errors.PRECONDITION, "릴레이 주소를 모른다",
                         {"missing": ["relay.url"], "how": "agora register --relay <url>"})
    store = _relay(url)
    fetched = store.roster()

    current: dict[str, str] = {}
    existing: list[str] = []
    for name in ROSTER_FILES:
        path = os.path.join(directory, name)
        if os.path.exists(path):
            existing.append(name)
            with open(path, encoding="utf-8") as fh:
                current[name] = fh.read()
        else:
            current[name] = ""
    first_sync = not existing

    changes: dict[str, dict[str, list[str]]] = {}
    for name in ROSTER_FILES:
        before, after = set(_lines(current[name])), set(_lines(fetched[name]))
        added, removed = sorted(after - before), sorted(before - after)
        if added or removed:
            # ★공개키 전문을 결과에 싣지 않는다 — 화면·로그에 남는다. **줄 수와 principal 만.**
            changes[name] = {"added": [ln.split()[0] for ln in added],
                             "removed": [ln.split()[0] for ln in removed]}
    if changes and not first_sync and not yes:
        raise AgoraError(errors.GATE_REJECT,
                         "명부가 바뀌었다 — 확인하고 --yes 로 받아라",
                         {"changes": changes, "wrote": [], "reason": "roster_change_unconfirmed"})

    # ★셋을 **먼저 전부** 임시 파일로 쓴다. 도중에 실패하면 실물은 하나도 안 바뀐다.
    #   ⚠그래도 `os.replace` 3회 사이의 창은 남는다(진짜 원자성은 파일 3개에 없다) —
    #     그래서 무엇이 바뀌었는지 결과에 **파일 단위로** 적는다.
    tmps: list[tuple[str, str]] = []
    for name in ROSTER_FILES:
        path = os.path.join(directory, name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(fetched[name])
        tmps.append((path, tmp))
    wrote: list[str] = []
    for path, tmp in tmps:
        try:
            if os.path.exists(path):
                # 되돌릴 손잡이 — 잘못된 명부를 받았을 때 직전 것이 옆에 있어야 한다.
                with open(path, "rb") as src, open(path + ".prev", "wb") as dst:
                    dst.write(src.read())
            os.replace(tmp, path)
        except OSError as e:
            # ★★교체 도중에 죽으면 **이미 바뀐 파일이 남는다**(agy 적대검증 2026-09-05 지적).
            #   날것 예외로 새면 호출자는 **어디까지 바뀌었는지 모른 채** 실패만 본다 —
            #   그 상태가 곧 「그때의 명부가 갈라진」 상태이므로 **무엇이 바뀌었는지**를 실어 올린다.
            raise AgoraError(errors.STORE, "명부 교체가 중간에 실패했다 — 일부만 바뀌었을 수 있다",
                             {"wrote": wrote, "failed": os.path.basename(path),
                              "error": type(e).__name__,
                              "how": "남은 임시 파일(<파일>.tmp)과 직전 사본(<파일>.prev)이 옆에 있다",
                              "reason": "roster_partial_replace"}) from None
        wrote.append(os.path.basename(path))

    checkpoint = _fetch_checkpoint(store, directory)
    return {"relay": url, "first_sync": first_sync, "changes": changes,
            "wrote": wrote, "confirmed_by": "--yes" if yes else ("tofu" if first_sync else "no_change"),
            "counts": {name: len(_lines(fetched[name])) for name in ROSTER_FILES},
            "digest": {name: _sha256_file(os.path.join(directory, name))
                       for name in ROSTER_FILES},
            "checkpoint": checkpoint}


def _fetch_checkpoint(store: Any, directory: str) -> dict[str, Any]:
    """운영자 서명 체크포인트(릴레이 계약 §3-6b) — **받아서 남기되 아직 검증하지 않는다.**

    ★검증을 흉내내지 않는다: 확정본 `docs/RELAY.md@b2ca815` 는 **누가 서명하는가**(운영자 ·
      §3-6b)와 **무엇을 서명하는가의 뜻**(명부 3종 렌더의 해시)까지만 적었고, 실제로 검증에
      필요한 세 가지가 없다 — ⑴서명 대상 **바이트**의 정의(해시 문자열 그대로인가, 문서를
      canonical 로 만든 바이트인가) ⑵SSHSIG **namespace**(등록은 §3-1 이 명시했는데 여기는 없다)
      ⑶`signed_at` 결박(없으면 옛 서명을 다시 올리는 것을 못 가른다).
      확정 전에 `verified: true` 를 적으면 **검증하지 않은 것을 검증했다고 적는 것**이 된다.
    ★**부재는 200 + `checkpoint: null` 이다**(§3-6b · `revoked_keys` 와 같은 규율). 그때도
      `current`·`stale` 은 온다 — 그 두 칸이 부재의 내용이므로 버리지 않고 함께 적는다.
      404 는 엔드포인트 자체가 아직 없는 상대에서만 나오고, 그 경우는 어댑터가 `None` 을 준다.
    """
    try:
        doc = store.roster_checkpoint()
    except AgoraError as e:
        return {"present": False, "verified": False, "why": f"fetch_failed:{e.code}"}
    if doc is None:
        return {"present": False, "verified": False, "why": "relay_has_no_checkpoint"}
    if doc.get("checkpoint") is None:
        # 서버는 답했고, 답의 내용이 「아직 없다」다. 「못 읽었다」와 같은 칸에 적지 않는다.
        return {"present": False, "verified": False, "why": "relay_has_no_checkpoint",
                "current": doc.get("current"), "stale": doc.get("stale")}
    _write_json(os.path.join(directory, CHECKPOINT_FILENAME), doc)
    return {"present": True, "verified": False,
            "why": ("검증 계약 미확정(RL-6 · 서명 대상 바이트·namespace·signed_at 결박 없음)"
                    " — 받은 것을 파일로 남기기만 했다"),
            "file": CHECKPOINT_FILENAME,
            "stale": doc.get("stale"), "checkpoint": doc.get("checkpoint"),
            "current": doc.get("current")}


# ── whoami ──────────────────────────────────────────────────────────────────

def whoami(*, directory: str | None = None) -> dict[str, Any]:
    """나는 누구이고, 어디에 대고 말하며, **어떤 겹이 꺼져 있는가**.

    ★`approval_gate` 를 **첫 칸**에 오게 이름 지었다(출력은 키 정렬이라 `a` 가 맨 앞이다).
      사람 승인 겹이 꺼진 것은 설치가 내린 결정이고, 그 결정은 **볼 때마다 보여야** 한다.
    """
    directory = os.path.abspath(directory or config_dir())
    doc = load(directory)
    cfg = _load_config(directory)
    from agora.tools import transport_of
    approval_on = cfg.get("human_approval", True) is not False
    roster_view = {}
    for name in ROSTER_FILES:
        path = os.path.join(directory, name)
        text = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        roster_view[name] = {"present": os.path.exists(path), "lines": len(_lines(text)),
                             "sha256": _sha256_file(path)}
    joined = {}
    joined_path = os.path.join(directory, "joined.json")
    if os.path.exists(joined_path):
        try:
            with open(joined_path, encoding="utf-8") as fh:
                joined = json.load(fh)
        except ValueError:
            joined = {}
    transport = transport_of(cfg)
    # ★명부 3종의 **체크포인트 해시**(master 결정 2026-09-05 · RC-1 (b)안의 「whoami 에 명부 해시」).
    #   ⚠이벤트의 `roster` 칸과 **다른 값이다**: 그쪽은 계약상 `allowed_signers` 하나의 해시이고(§2-1a),
    #     이것은 3종 전체다. 두 값을 같은 이름으로 부르지 않는다.
    checkpoint = roster.checkpoint(paths={
        "participants/allowed_signers": os.path.join(directory, "allowed_signers"),
        "participants/revoked_keys": os.path.join(directory, "revoked_keys"),
        "participants/operators": os.path.join(directory, "operators")})
    return {
        "approval_gate": {
            "state": "켜짐" if approval_on else "꺼짐(설치가 껐다)",
            "why": "config.json human_approval" if not approval_on else "기본값 on",
            # ★켜져 있어도 **승인자가 배선돼 있지 않다**(RC-2 실측). 그 사실을 숨기지 않는다 —
            #   숨기면 「켜짐」이 「사람이 본다」로 읽힌다.
            "note": ("켜져 있으면 현재 구현에서는 모든 발신이 code 3 으로 거부된다"
                     " — 승인자 배선은 v1.1(도구가 「승인 대기」 반환)"),
        },
        "config_dir": directory,
        "joined_rooms": {"count": len(joined), "rooms": sorted(joined)},
        "participant": {"id": doc["id"], "display_name": doc["display_name"],
                        "key_fingerprint": doc["key_fingerprint"],
                        "operator": doc["operator"],
                        "in_roster": doc["id"] in roster.principals(
                            path=os.path.join(directory, "allowed_signers")),
                        "file": PARTICIPANT_FILENAME},
        "relay": (cfg.get("relay") or {}).get("url"),
        "roster": roster_view,
        "roster_checkpoint": {"sha256": checkpoint,
                              "covers": list(ROSTER_FILES),
                              "note": "이벤트의 roster 칸(allowed_signers 단독 해시)과 다른 값이다"},
        "transport": transport,
    }
