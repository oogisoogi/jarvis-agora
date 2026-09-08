"""CLI 진입 — 서브커맨드 등록과 오류 계약 집행만 한다.

★기능은 여기 있지 않다. 이 파일이 하는 일은 셋뿐이다.
  ⑴ 계약(설계 §4)의 서브커맨드를 **전건 등록**한다 — MCP 도구와의 1:1 대조가 이 등록표에서 파생된다.
  ⑵ 파일 인자를 구조체로 바꿔 코어에 넘긴다(MCP 인자에는 파일 경로가 없다).
  ⑶ 어떤 실패든 `AgoraError` 로 받아 **JSON 을 stderr 로 내고 그 code 로 종료**한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable

from agora import errors
from agora.errors import AgoraError

# ── 서브커맨드 등록표 ────────────────────────────────────────────────────────
# core=True  : 코어 함수 = MCP 도구와 1:1 (이름은 하이픈↔밑줄만 다르다)
# core=False : CLI 전용 (MCP 예외 · 정본 = 설계 §4 「(CLI만)」 행 · 계수·목록은 거기에만 — B④-r2 2026-09-02)
# built      : 이 슬라이스까지 실제로 구현됐는가. False 면 계약대로 등록만 되고 실행은 거부된다.
#              ★「등록됐다」와 「동작한다」를 한 칸으로 뭉치지 않으려고 나눠 둔다 —
#                뭉치면 미구현이 --help 에서 구현으로 보인다.
COMMANDS: dict[str, dict[str, Any]] = {
    "threads":        {"core": True,  "built": True,  "slice": "S1-6"},
    "read":           {"core": True,  "built": True,  "slice": "S1-6"},
    "propose":        {"core": True,  "built": True,  "slice": "S2-4"},
    "say":            {"core": True,  "built": True,  "slice": "S2-4"},
    "advance":        {"core": True,  "built": True,  "slice": "S2-5"},
    "resolve":        {"core": True,  "built": True,  "slice": "S3-2"},
    "mark-solved":    {"core": True,  "built": True,  "slice": "S2-4"},
    "close":          {"core": True,  "built": True,  "slice": "S2-4"},
    "vote":           {"core": True,  "built": True,  "slice": "S3-4"},
    "envelope-check": {"core": True,  "built": True,  "slice": "S3-3"},
    "ack":            {"core": True,  "built": True,  "slice": "S5-3"},
    "watch":          {"core": False, "built": True,  "slice": "S6-2"},
    # ★계약 확장(master 결정 2026-08-25 · S5-5 회신) — 수동 대조를 CLI 로 둔다.
    #   설계 §4 의 CLI 전용 4종에 하나가 더해졌다. 조용히 늘리지 않고 여기 근거를 적는다.
    "reconcile":      {"core": False, "built": True,  "slice": "S6-2"},
    "selftest":       {"core": False, "built": True,  "slice": "S1-8"},
    "keygen":         {"core": False, "built": True,  "slice": "S1-4"},
    "export":         {"core": False, "built": True,  "slice": "S6-2"},
    "import":         {"core": False, "built": True,  "slice": "S6-2"},
    # ★계약 확장 2(master 결정 2026-08-26) — **도구 표면을 띄우는 명령**.
    #   S6-2 AC ② 는 「예시 설정 그대로 서버를 띄워 도구 목록 조회」를 요구하는데,
    #   `mcp_server.serve` 를 **부를 방법이 아무 데도 없었다**(`__main__`·CLI·예시 파일 전무).
    #   그래서 시험은 `handle()` 을 직접 부르며 초록이었고, 제품에는 표면이 없었다.
    #   ⇒ 도구가 아니라 **운영 동작**이므로 core=False 이고 MCP 에 노출하지 않는다
    #     (서버를 띄우는 명령을 서버가 노출하면 대리인이 서버를 또 띄운다).
    "mcp-serve":      {"core": False, "built": True,  "slice": "S6-6"},
    # ★계약 확장 4(master 결정 2026-09-05 22:0x · `[master#6657207e]`) — **박람회 여정 3종**.
    #   06 증보 §4 의 J1·J2 가 요구하는 어휘(방을 연다·로비를 돈다·참가한다)를 손에 쥐여 준다.
    #   ⇒ 도구 표면이 11종 → **14종**이 된다. 06 §6 의 「도구 계약 무변경」은 master 문면 과실로
    #     판정됐고 06 에 정오표가 남았다(브리프 21:52 가 정본).
    #   ★새 규칙은 없다 — `enter`=propose · `browse`=threads · `join`=로컬 확인(새 kind 없음).
    "enter":          {"core": True,  "built": True,  "slice": "S8-1"},
    "browse":         {"core": True,  "built": True,  "slice": "S8-1"},
    "join":           {"core": True,  "built": True,  "slice": "S8-1"},
    # ★계약 확장 5(같은 결정) — **가입·명부 운영 3종**. 도구가 아니다:
    #   설치 도우미가 부르는 한 줄이고, MCP 표면에 올리면 대리인 세션 손에 「명부를 갈아라」가 쥐어진다.
    "register":       {"core": False, "built": True,  "slice": "S8-2"},
    "sync-roster":    {"core": False, "built": True,  "slice": "S8-2"},
    "whoami":         {"core": False, "built": True,  "slice": "S8-2"},
    # ★계약 확장 6(master 발주 2026-09-06 r4) — **운영자 체크포인트 발행**.
    #   도구가 아니다: 명부의 정본이 운반층으로 간 뒤 그것을 되돌려 오는 **운영자의 손**이고,
    #   MCP 표면에 올리면 대리인 세션이 「지금 명부가 정본이다」라고 서명해 버린다.
    "checkpoint":     {"core": False, "built": True,  "slice": "S8-3"},
    # ★계약 확장 3(master 결정 2026-08-26 (b)안) — **절차 개입** 2종.
    #   계약 kind 9종 중 `delegate_chair`·`abort` 는 **내보낼 자리가 없었다**(발신자 0).
    #   그래서 만료된 스레드를 되살릴 수도, 운영자가 중단할 수도 없었다 — 받을 준비만 돼 있었다.
    #   도구가 아니라 운영 동작으로 둔다(§4 도구 11종 동결 문면 불변 · MCP 표면 11종 유지).
    "delegate-chair": {"core": False, "built": True,  "slice": "S7-3"},
    "abort":          {"core": False, "built": True,  "slice": "S7-3"},
    # ★계약 확장 7(master 판정 2026-09-09 `[master#696731a8]` B안) — **설치 점검**.
    #   ⚠`selftest` 와 재는 것이 다르다: `selftest` 는 **개발 트리 전용 하네스**다
    #     (케이스·뮤테이션이 `tests/`·`docs/`·`.appbuild/` 를 연다 — 배포 꾸러미에는 그것들이 없다).
    #     그래서 꾸러미 안의 `selftest` 는 **정직하게 거절**하고, 「내 기계의 설치가 성립하는가」는
    #     이 명령이 진다(여섯 축 · 전부 읽기 전용 · 미측정을 통과로 세지 않는다).
    #   도구가 아니다: MCP 표면에 올리지 않는다(대리인이 자기 설치를 점검할 일은 없다).
    "selfcheck":      {"core": False, "built": True,  "slice": "S8-4"},
}

# MCP 에 노출하지 않는 것 — 정본 = 설계 §4 「(CLI만)」 행(예외 계수는 그 한 곳에만 · J-7 2026-09-02).
#   이 집합은 그 행과 같아야 한다(`_case_mcp_names_derive_from_cli`·`_case_local_commands_are_not_tools` 가 잰다).
MCP_EXEMPT = frozenset({"watch", "selftest", "keygen", "export", "import",
                        "reconcile", "mcp-serve", "delegate-chair", "abort",
                        # 계약 확장 5(2026-09-05) — 가입·명부 운영. 설치가 부르고 대리인은 못 부른다.
                        "register", "sync-roster", "whoami",
                        # 계약 확장 6(2026-09-06) — 운영자 체크포인트 발행.
                        "checkpoint",
                        # 계약 확장 7(2026-09-09) — 설치 점검. 대리인이 자기 설치를 볼 일은 없다.
                        "selfcheck"})

# ── 역할별 노출표(설계 §5 「수신 격리」 H-3 · NFR-2) ─────────────────────────
# ★**여기가 「도구 목록」의 단일 출처다.** 대리인 브리프(S6-3 `brief-reader.md`)는 이 표를
#   인용해 렌더한다 — 브리프에 손으로 목록을 적으면 두 곳이 갈라지고, 갈라진 날
#   무도구여야 할 세션에 도구가 하나 들어가 있어도 아무도 모른다.
#
# ★`reader` 가 **공집합**인 것이 이 표의 전부다. 수신 워커는 남이 보낸 글을 읽을 뿐이고,
#   그 글에는 「이것을 실행하라」가 들어 있을 수 있다(§8 주입 픽스처). 도구가 0 이면
#   그 문장은 **읽을 수는 있어도 실행할 손이 없다.**
#   ⇒ `agora.ack` 도 여기에 없다. 영수증을 쓰는 것은 **참가 master 세션**이다(K-2).
ROLE_PARTICIPANT_MASTER = "participant_master"
ROLE_READER = "reader"


def role_tools(role: str) -> tuple[str, ...]:
    """그 역할의 손에 닿는 MCP 도구 이름들."""
    if role == ROLE_READER:
        return ()                      # ★무도구 — 이 공집합이 격리 그 자체다
    if role == ROLE_PARTICIPANT_MASTER:
        return tuple(mcp_tool_name(n) for n in core_command_names())
    raise AgoraError(errors.ARGUMENT, "모르는 역할", {"role": role})


def mcp_tool_name(cli_name: str) -> str:
    """CLI 이름 → MCP 도구 이름. 규칙은 하이픈→밑줄 하나뿐이다."""
    return "agora." + cli_name.replace("-", "_")


def core_command_names() -> tuple[str, ...]:
    return tuple(n for n, m in COMMANDS.items() if m["core"])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agora",
        description="Jarvis Agora — 에이전트 광장 클라이언트",
        add_help=True,
    )
    p.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력한다(기본)")
    sub = p.add_subparsers(dest="command", metavar="<command>")
    for name, meta in COMMANDS.items():
        tag = "" if meta["built"] else f"  [미구현 — {meta['slice']}]"
        sp = sub.add_parser(name, help=name + tag, add_help=True)
        # ★`REMAINDER` 여야 한다 — `nargs="*"` 는 **`--relay` 같은 인자를 「모르는 옵션」으로 보고
        #   서브커맨드를 시작도 하기 전에 거부한다**(argparse 의 기본 동작).
        #   ⚠이것이 실물에서 터졌다(2026-09-05 CLI 실사격): `_kv` 는 `--key value` 를 읽을 줄 아는데
        #   그 값이 **거기까지 오지 못했다** — 시험이 `_kv` 를 직접 불러 재고 있어서 초록이었다.
        #   ⇒ 「등록됐다」와 「동작한다」의 그 자리다. 이제 케이스가 **`bin/agora` 를 실제로 부른다.**
        sp.add_argument("rest", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return p


# 정수로 읽는 칸 — **계약이 정한다**(§4 도구 인자 표). 여기 없으면 문자열이다.
# ★왜 목록인가: 「숫자처럼 보이면 정수」로 하면 **제목 「2026」이 정수가 된다.**
#   그러면 스키마가 「title 은 문자열이어야 한다」로 거절하고, 사용자는 자기가 문자열을 줬다고
#   믿는다 — 틀린 곳과 탓하는 곳이 어긋난다. 처음 쓴 파서가 실제로 그랬다.
INT_ARGS = frozenset({"round", "to_round", "value", "limit", "interval"})
BOOL_ARGS = frozenset({"audit", "answered", "once", "unattended", "yes"})
# 값 **없이** 올 수 있는 플래그(`--unattended`). 목록 밖의 `--키`는 값을 요구한다 —
# ★아무 `--키`나 값 없이 참으로 읽으면 `--body --relay x` 가 조용히 `body=True` 가 된다.
FLAG_ARGS = frozenset({"unattended", "yes", "once", "audit"})
# JSON 으로 읽는 칸 — **여기 없으면 문자열이다.**
# ★「`{`·`[` 로 시작하면 JSON」으로 하면 **우리 규약이 요구하는 제목이 깨진다**:
#   시험 글 제목은 `[selftest] …` 로 시작해야 하는데(04-tasks S7-2), 그 값이 JSON 으로 해석되어
#   `code 10` 이 난다. S7-1 실물 절차에서 실제로 막혔다 — **값의 모양으로 추측하면
#   언제나 이런 충돌이 생긴다.** 칸 이름은 계약이 정하고, 계약은 충돌하지 않는다.
JSON_ARGS = frozenset({"envelope", "deadlines", "counter", "refs", "parent",
                       "dissent", "recommended_actions", "arguments"})


def _run_onboard(name: str, rest: list[str]) -> Any:
    """가입·명부 운영 3종 — **도구가 아니라 설치·운영 동작**이다(계약 확장 5).

    ★`context_from_config` 를 거치지 않는다. 그 함수는 **운반층을 세우는 것부터** 하는데,
      `register` 는 바로 그 운반층 주소를 **설정에 적으러** 온 명령이다 — 거치면
      「설정이 없어서 설정을 못 적는」 닭·달걀이 된다(첫 설치가 정확히 그 상태다).
    """
    from agora import onboard
    # ★맨 앞의 맨몸 토큰을 **동작 이름**으로 읽는 것은 `checkpoint` 에서만이다
    #   (`agora checkpoint issue`). 다른 명령에서 그런 토큰이 오면 예전처럼 `_kv` 가 code 10 을
    #   낸다 — 규칙을 넓히면 `agora whoami 오타` 가 조용히 통과한다.
    action = ""
    if name == "checkpoint" and rest and not rest[0].startswith("--") and "=" not in rest[0]:
        action, rest = rest[0], rest[1:]
    kw = _kv(rest)
    directory = kw.get("dir")
    if name == "register":
        relay_url = kw.get("relay") or kw.get("relay_url")
        if not relay_url:
            raise AgoraError(errors.ARGUMENT, "register 는 --relay <url> 이 필요하다",
                             {"usage": "agora register --relay <url> [--unattended]"})
        return onboard.register(directory=directory, relay_url=relay_url,
                                unattended=bool(kw.get("unattended", False)))
    if name == "sync-roster":
        return onboard.sync_roster(directory=directory,
                                   relay_url=kw.get("relay") or kw.get("relay_url"),
                                   yes=bool(kw.get("yes", False)))
    if name == "checkpoint":
        # ★동작을 **하나만** 둔다(`issue`). 「발행」과 「조회」를 한 명령에 넣으면 조회하려다
        #   서명이 나가는 오타가 생긴다 — 조회는 `sync-roster`·`whoami` 가 이미 한다.
        if action != "issue":
            raise AgoraError(errors.ARGUMENT, "checkpoint 의 동작은 issue 하나다",
                             {"got": action, "usage": "agora checkpoint issue [--relay <url>]"})
        return onboard.issue_checkpoint(directory=directory,
                                        relay_url=kw.get("relay") or kw.get("relay_url"),
                                        signer=kw.get("signer"))
    return onboard.whoami(directory=directory)


def _run_operator(name: str, rest: list[str]) -> Any:
    """운영 동작 2종 — 도구가 아니라 **절차 개입**이다(§4 아래 절 · master 결정 2026-08-26).

    ★도구 표(`tools.CORE_TOOLS`)를 거치지 않는다. 거기 넣으면 계약이 13종이 되고
      MCP 표면에 올라간다 — 대리인 세션 손에 「의장을 갈아치워라」가 쥐어진다.
    """
    from agora import tools
    kw = _kv(rest)
    ctx = tools.context_from_config(kw.pop("dir", None))
    if name == "delegate-chair":
        return tools.delegate_chair(ctx, thread_id=kw["thread_id"],
                                    new_chair=kw["new_chair"])
    return tools.abort(ctx, thread_id=kw["thread_id"], reason=kw["reason"])


def _run_local(name: str, rest: list[str]) -> Any:
    """MCP 에 없는 CLI 전용 명령들(§4 예외). 이것들은 **도구가 아니라 운영 동작**이다.

    ★그래서 도구 표에 넣지 않는다. 넣으면 대리인 세션의 손에 「감시를 멈춰라」·「원장을 들여라」가
      쥐어지고, 그것은 참가자가 아니라 **운영자가 할 일**이다.
    """
    from agora import tools
    kw = _kv(rest)
    d = kw.pop("dir", None)
    ctx = tools.context_from_config(d)
    if name == "watch":
        from agora.watch import Cursor, run
        # ★명부 경로를 **실어 준다**(M-e). 안 실으면 검증이 자료 없이 돌고, 모든 글이
        #   미검증으로 떨어져 알림이 통째로 조용해진다 — 인자를 만든 것으로 배선이 되지 않는다.
        return run(store=ctx.store, spool=ctx.spool, cursor=Cursor(_config_dir(d)),
                   ledger=ctx.ledger,
                   interval=int(kw.get("interval", 60)),
                   once=bool(kw.get("once", False)),
                   allowed_signers_path=ctx.allowed_signers_path,
                   revoked_path=ctx.revoked_path)
    if name == "reconcile":
        from agora import reconcile as rec
        thread_id = kw.get("thread_id")
        if not thread_id:
            raise AgoraError(errors.ARGUMENT, "reconcile 은 thread_id 가 필요하다", None)
        return rec.reconcile(store=ctx.store, ledger=ctx.ledger, thread_id=thread_id,
                             spool=ctx.spool)
    from agora import export as export_mod
    if name == "export":
        out_path = kw.get("out")
        if not out_path:
            raise AgoraError(errors.ARGUMENT, "export 는 out=<경로> 가 필요하다", None)
        return export_mod.dump(directory=_config_dir(d), out_path=out_path)
    src = kw.get("file")
    if not src:
        raise AgoraError(errors.ARGUMENT, "import 는 file=<경로> 가 필요하다", None)
    with open(src, encoding="utf-8") as fh:
        doc = json.load(fh)
    return export_mod.load(doc=doc, directory=_config_dir(d))


def _config_dir(explicit: str | None) -> str:
    from agora.participant import config_dir
    return explicit or config_dir()


def _kv(rest: list[str]) -> dict[str, Any]:
    """`key=value` 인자를 구조체로. **파일 인자(`--body-file`)는 S6-2 의 몫이다.**

    ★값의 타입을 **추측하지 않는다.** 정수·불리언은 위 목록의 칸에서만 그렇게 읽고,
      JSON 은 `{`·`[` 로 시작할 때만, 나머지는 **문자열 그대로** 둔다.
    ⚠**제약(의도한 것 · agy 적대검증 2026-09-05 논쟁점)**: 값이 `--` 로 시작하면 `--key value`
      서식으로 못 준다 — 그 토큰을 **다음 플래그**로 보기 때문이다(그래야 `--body --relay x` 같은
      오타에서 플래그가 값으로 조용히 삼켜지지 않는다). 그런 값은 `--key=--value` 나 `key=--value`
      로 준다. **오염을 막는 쪽**을 골랐고, 그 대가를 여기 적어 둔다.
    """
    out: dict[str, Any] = {}
    index = 0
    while index < len(rest):
        token = rest[index]
        index += 1
        # ★`--key value` · `--key=value` 도 받는다(06 §4·브리프가 그 모양으로 적혀 있다).
        #   기존 `key=value` 는 그대로다 — 두 서식이 같은 자리에서 같은 뜻이 되게만 한다.
        if token.startswith("--") and len(token) > 2:
            flag = token[2:]
            if "=" not in flag:
                name = flag.replace("-", "_")
                nxt = rest[index] if index < len(rest) else None
                if nxt is None or nxt.startswith("--"):
                    if name not in FLAG_ARGS:
                        raise AgoraError(errors.ARGUMENT, "이 인자는 값이 필요하다",
                                         {"key": name})
                    out[name] = True          # 값 없는 플래그
                    continue
                out[name] = _value(name, nxt)
                index += 1
                continue
            token = flag
        if "=" not in token:
            raise AgoraError(errors.ARGUMENT, "인자는 key=value 형식이다",
                             {"token_len": len(token)})
        key, _, raw = token.partition("=")
        out[key.replace("-", "_")] = _value(key.replace("-", "_"), raw)
    return out


def _value(key: str, raw: str) -> Any:
    if key in BOOL_ARGS and raw in ("true", "false"):
        return raw == "true"
    if key in INT_ARGS:
        if not raw.lstrip("-").isdigit():
            raise AgoraError(errors.ARGUMENT, "이 칸은 정수여야 한다",
                             {"key": key, "len": len(raw)})
        return int(raw)
    if key in JSON_ARGS:
        try:
            return json.loads(raw)
        except ValueError:
            raise AgoraError(errors.ARGUMENT, "JSON 인자를 읽지 못했다",
                             {"key": key}) from None
    if raw == "null":
        return None
    return raw


# `selftest` 가 개발 트리에서만 도는 근거가 되는 두 자리. ★한 자리로 판정하지 않는다 —
# 하나만 보면 그 하나가 사라지는 날 검사가 조용히 「꾸러미다」로 넘어간다.
DEV_TREE_MARKERS = ("tests/fake_relay.py", ".appbuild")


def _require_dev_tree(root: str | None = None) -> None:
    """`selftest` 는 **개발 트리 전용**이다(master 판정 2026-09-09 `[master#696731a8]` ①).

    ★왜 이 문이 필요한가: `selftest` 의 케이스와 뮤테이션은 `tests/`·`docs/`·`.appbuild/`
      까지 연다. 배포 꾸러미에는 그것들이 없으므로 **없는 파일을 열다 죽었다**(실측 rc=2 ·
      추적정보만 나왔다). 죽는 것과 「여기서는 안 돈다」를 말하는 것은 다르다.
    ★판정은 **두 표지가 모두 없을 때만** 「꾸러미」다. 하나만 없으면 그것은 꾸러미가 아니라
      **망가진 개발 트리**이고, 그때는 통과시켜 원래대로 시끄럽게 죽게 둔다 —
      반쪽 트리를 조용히 「꾸러미니까 넘어감」으로 처리하면 그 순간 이 문이 검사를 끄는 손잡이가 된다.
    """
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    present = [m for m in DEV_TREE_MARKERS if os.path.exists(os.path.join(root, m))]
    if present:
        return
    raise AgoraError(
        errors.PRECONDITION,
        "이 꾸러미에는 개발 트리가 없어 selftest 는 여기서 돌지 않는다."
        " 설치 점검은 agora selfcheck 로 한다.",
        {"reason": "not_a_dev_tree", "설치_점검": "agora selfcheck"},
    )


def dispatch(name: str, args: argparse.Namespace) -> Any:
    meta = COMMANDS.get(name)
    if meta is None:
        raise AgoraError(errors.ARGUMENT, "알 수 없는 서브커맨드", {"command": name})
    if not meta["built"]:
        # ★코드 2(전제 미비)를 쓰되 detail 로 이유를 못박는다.
        #   「무엇이 없어서 못 하는가」가 detail 에 없으면 이 실패는 다른 전제 미비와 구별되지 않는다.
        raise AgoraError(
            errors.PRECONDITION,
            "이 서브커맨드는 아직 구현되지 않았다",
            {"reason": "slice_not_built", "command": name, "slice": meta["slice"]},
        )
    if name == "selfcheck":
        from agora import selfcheck as sc
        return sc.main(list(args.rest) if hasattr(args, "rest") else [])
    if name == "selftest":
        _require_dev_tree()
        from agora import selftest as st
        return st.run()
    if name == "keygen":
        from agora import keygen as kg
        return kg.run(args.rest if hasattr(args, "rest") else [])
    if name == "mcp-serve":
        # ★결과를 **안 돌려준다**(None). 이 명령의 출력은 stdout 의 **프로토콜 줄**이고,
        #   여기서 반환값을 주면 main 이 그 위에 JSON 을 한 줄 더 찍어 프로토콜을 깬다.
        from agora import mcp_server
        mcp_server.serve()
        return None
    if name in ("register", "sync-roster", "whoami", "checkpoint"):
        return _run_onboard(name, list(args.rest) if hasattr(args, "rest") else [])
    if name in ("delegate-chair", "abort"):
        return _run_operator(name, list(args.rest) if hasattr(args, "rest") else [])
    if name in ("watch", "reconcile", "export", "import"):
        return _run_local(name, list(args.rest) if hasattr(args, "rest") else [])
    if meta["core"]:
        # ★코어 도구는 **한 줄로** 넘긴다. 도구마다 여기에 분기를 만들면 그 분기가
        #   두 번째 계약이 되고, 언젠가 표와 갈라진다(그때 갈라진 쪽이 조용히 이긴다).
        from agora import tools
        rest = list(args.rest) if hasattr(args, "rest") else []
        return tools.call(name, tools.context_from_config(), _kv(_positional(name, rest)))
    raise AgoraError(errors.PRECONDITION, "실행기 배선 누락", {"command": name})


# 문서가 **자리 인자**로 적어 놓은 명령들(`agora join <room-id>`) — 표는 한 곳에만 둔다.
# ★2026-09-06 실물 릴레이 리허설에서 터진 자리: `agora join <room-id>` 가 code 10 으로 거부됐다.
#   케이스는 `tools.join(ctx, room_id=…)` 를 **직접** 불러 재고 있어 전건 초록이었다 —
#   **등록됐다 ≠ 동작한다**의 세 번째 판(앞의 둘 = M322 · argparse 진입점).
#   ⇒ 문서가 약속한 서식은 **진입점에서** 받아야 한다.
POSITIONAL_ARG = {"join": "room_id"}


def _positional(name: str, rest: list[str]) -> list[str]:
    """맨 앞의 **맨몸 토큰** 하나를 그 명령의 자리 인자로 바꿔 준다.

    ★`key=value`·`--key value` 규율은 그대로 둔다 — 바꾸는 것은 **첫 토큰 하나**뿐이고,
      그것도 표(`POSITIONAL_ARG`)에 적힌 명령에서만이다. 규칙을 넓히면 오타가 값이 된다.
    ⚠**「`=` 가 들어 있어도 자리 값으로 받자」는 제안을 안 받았다**(agy 적대검증 2026-09-06 · 반박):
      ⑴그렇게 하면 지금 도는 `agora join room_id=<id>` 가 **자리 값으로 오독**된다(그 서식도 계약이다).
      ⑵표에 있는 유일한 명령의 값 문법은 **32자 hex** 라 `=` 가 들어갈 수 없다 — 없는 위험을 막으려고
        있는 서식을 깨지 않는다. ⇒ **표에 값이 `=` 를 가질 수 있는 명령을 넣을 때** 그 명령 전용 규칙을
        여기 적는다(그때가 이 판단을 다시 여는 시점이다).
    """
    key = POSITIONAL_ARG.get(name)
    if not key or not rest:
        return rest
    head = rest[0]
    if head.startswith("--") or "=" in head:
        return rest
    return [f"{key}={head}", *rest[1:]]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        if not argv:
            parser.print_help()
            return errors.OK
        # ★★서브커맨드 **뒤는 argparse 에 넘기지 않는다**(2026-09-05 CLI 실사격에서 터진 자리).
        #   argparse 는 `--topic` 같은 토큰을 **모르는 옵션**으로 보고 서브커맨드가 시작되기도 전에
        #   거부한다(`nargs="*"` 도 `REMAINDER` 도 부모 파서가 「unrecognized arguments」로 죽인다 — 실측).
        #   그래서 `_kv` 가 `--key value` 를 읽을 줄 알아도 **그 값이 거기까지 오지 못했다.**
        #   ⇒ 최상위 플래그만 여기서 처리하고, 나머지는 **손대지 않고** 그대로 넘긴다.
        #   ⚠파서는 버리지 않는다 — 도움말과 「모르는 최상위 인자」 판정은 여전히 그쪽 몫이다.
        while argv and argv[0].startswith("-"):
            token = argv.pop(0)
            if token in ("-h", "--help"):
                parser.print_help()
                return errors.OK
            if token != "--json":
                raise AgoraError(errors.ARGUMENT, "모르는 최상위 인자",
                                 {"arg_len": len(token)})
        if not argv:
            parser.print_help()
            return errors.OK
        command, rest = argv[0], argv[1:]
        if "-h" in rest or "--help" in rest:
            parser.parse_args([command, "--help"])      # 서브커맨드 도움말(SystemExit 0)
            return errors.OK
        result = dispatch(command, argparse.Namespace(rest=rest))
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        # selftest 는 계약 오류가 아니라 **검사 실패**를 낸다 — 계약 코드(2~10)를 쓰지 않고
        # 일반 실패 1로 끝낸다. 계약 코드에 두 뜻을 싣지 않는다.
        if isinstance(result, dict) and result.get("ok") is False:
            return 1
        # `selfcheck` 도 계약 오류가 아니라 **점검 결과**를 낸다. 종료 코드를 판정 칸에서 읽는다 —
        # 판정과 종료 코드가 서로 다른 곳에서 정해지면 언젠가 둘이 갈리고, 그때 기계는 종료 코드를 믿는다.
        # ★0(전축 통과) · 1(실패 있음) · 3(실패는 없고 미측정 있음) — 3 을 0 으로 접지 않는다.
        if isinstance(result, dict) and isinstance(result.get("판정"), dict):
            rc = result["판정"].get("종료코드")
            # ★`type(rc) is int` 여야 한다 — `isinstance` 는 **참·거짓도 정수로 받는다**
            #   (파이썬에서 bool 은 int 의 하위형이다). `종료코드: false` 가 0 으로 통과했다.
            if type(rc) is int:
                return rc
            # ★판정 칸은 있는데 종료 코드를 못 읽으면 **실패 쪽으로 넘어진다.**
            #   여기서 0 으로 폴백하면 결과 형태가 깨지는 순간 fail-open 이 된다
            #   (이종 검증 2026-09-09 지적 · agy·codex 둘 다).
            return 1
        return errors.OK
    except AgoraError as e:
        print(e.to_json(), file=sys.stderr)
        return e.code
    except SystemExit as e:
        # argparse 가 인자 오류에 2로 죽는다 — 우리 계약에서 2는 「전제 미비」이므로
        # 인자 오류(10)로 되돌려 놓는다. 같은 숫자에 두 뜻을 두지 않는다.
        code = e.code if isinstance(e.code, int) else 1
        if code == 0:
            return errors.OK
        err = AgoraError(errors.ARGUMENT, "인자 오류", {"argparse_exit": code})
        print(err.to_json(), file=sys.stderr)
        return err.code
    except Exception as e:      # noqa: BLE001 — 최후 방어. 아래 이유로 **넓게** 잡는다.
        # ★**어떤 실패든 JSON 으로 나간다**(이 파일의 계약 ⑶). 예상 못 한 예외가 날것으로 새면
        #   사용자는 오류 계약을 믿고 있다가 **Traceback 을 받는다** — 그 순간
        #   「무엇이 잘못됐나」를 기계가 읽을 방법이 사라진다(S7-1 에서 실제로 났다:
        #   저장소 설정 칸이 계약에 없어 저장층 생성이 TypeError 로 터졌다).
        # ★메시지 원문은 싣지 않는다 — 그 안에 경로·값이 섞여 나갈 수 있다. **타입만** 싣는다.
        # ★`KeyboardInterrupt`·`SystemExit` 는 `Exception` 밖이라 여기 안 걸린다(의도한 것이다).
        err = AgoraError(errors.PRECONDITION, "예상하지 못한 내부 오류",
                         {"exception": type(e).__name__, "reason": "unexpected"})
        print(err.to_json(), file=sys.stderr)
        return err.code
