"""CLI 진입 — 서브커맨드 등록과 오류 계약 집행만 한다.

★기능은 여기 있지 않다. 이 파일이 하는 일은 셋뿐이다.
  ⑴ 계약(설계 §4)의 서브커맨드를 **전건 등록**한다 — MCP 도구와의 1:1 대조가 이 등록표에서 파생된다.
  ⑵ 파일 인자를 구조체로 바꿔 코어에 넘긴다(MCP 인자에는 파일 경로가 없다).
  ⑶ 어떤 실패든 `AgoraError` 로 받아 **JSON 을 stderr 로 내고 그 code 로 종료**한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from agora import errors
from agora.errors import AgoraError

# ── 서브커맨드 등록표 ────────────────────────────────────────────────────────
# core=True  : 코어 함수 = MCP 도구와 1:1 (이름은 하이픈↔밑줄만 다르다)
# core=False : CLI 전용 (설계 §4 가 명시한 MCP 예외 — watch·selftest·keygen·export)
# built      : 이 슬라이스까지 실제로 구현됐는가. False 면 계약대로 등록만 되고 실행은 거부된다.
#              ★「등록됐다」와 「동작한다」를 한 칸으로 뭉치지 않으려고 나눠 둔다 —
#                뭉치면 미구현이 --help 에서 구현으로 보인다.
COMMANDS: dict[str, dict[str, Any]] = {
    "threads":        {"core": True,  "built": False, "slice": "S1-6"},
    "read":           {"core": True,  "built": False, "slice": "S1-6"},
    "propose":        {"core": True,  "built": False, "slice": "S2-4"},
    "say":            {"core": True,  "built": False, "slice": "S2-4"},
    "advance":        {"core": True,  "built": False, "slice": "S2-5"},
    "resolve":        {"core": True,  "built": False, "slice": "S3-2"},
    "mark-solved":    {"core": True,  "built": False, "slice": "S2-4"},
    "close":          {"core": True,  "built": False, "slice": "S2-4"},
    "vote":           {"core": True,  "built": False, "slice": "S3-4"},
    "envelope-check": {"core": True,  "built": False, "slice": "S3-3"},
    "ack":            {"core": True,  "built": True,  "slice": "S5-3"},
    "watch":          {"core": False, "built": False, "slice": "S5-2"},
    "selftest":       {"core": False, "built": True,  "slice": "S1-8"},
    "keygen":         {"core": False, "built": True,  "slice": "S1-4"},
    "export":         {"core": False, "built": False, "slice": "S6-2"},
}

# MCP 에 노출하지 않는 것 — 설계 §4 가 예외로 명시한 4종.
MCP_EXEMPT = frozenset({"watch", "selftest", "keygen", "export"})

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
        sp.add_argument("rest", nargs="*", help=argparse.SUPPRESS)
    return p


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
    if name == "selftest":
        from agora import selftest as st
        return st.run()
    if name == "keygen":
        from agora import keygen as kg
        return kg.run(args.rest if hasattr(args, "rest") else [])
    if name == "ack":
        from agora import ack as ack_mod
        from agora.ledger import Ledger
        from agora.participant import config_dir
        from agora.spool import Spool
        rest = list(args.rest) if hasattr(args, "rest") else []
        if len(rest) != 1:
            raise AgoraError(errors.ARGUMENT, "ack 는 message_id 하나를 받는다",
                             {"given": len(rest)})
        d = config_dir()
        return ack_mod.ack(ledger=Ledger(d), spool=Spool(d), message_id=rest[0])
    raise AgoraError(errors.PRECONDITION, "실행기 배선 누락", {"command": name})


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        if not argv:
            parser.print_help()
            return errors.OK
        ns = parser.parse_args(argv)
        if not ns.command:
            parser.print_help()
            return errors.OK
        result = dispatch(ns.command, ns)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        # selftest 는 계약 오류가 아니라 **검사 실패**를 낸다 — 계약 코드(2~10)를 쓰지 않고
        # 일반 실패 1로 끝낸다. 계약 코드에 두 뜻을 싣지 않는다.
        if isinstance(result, dict) and result.get("ok") is False:
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
