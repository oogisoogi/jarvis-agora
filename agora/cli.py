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
}

# MCP 에 노출하지 않는 것 — 설계 §4 가 예외로 명시한 4종.
MCP_EXEMPT = frozenset({"watch", "selftest", "keygen", "export", "import",
                        "reconcile", "mcp-serve"})

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


# 정수로 읽는 칸 — **계약이 정한다**(§4 도구 인자 표). 여기 없으면 문자열이다.
# ★왜 목록인가: 「숫자처럼 보이면 정수」로 하면 **제목 「2026」이 정수가 된다.**
#   그러면 스키마가 「title 은 문자열이어야 한다」로 거절하고, 사용자는 자기가 문자열을 줬다고
#   믿는다 — 틀린 곳과 탓하는 곳이 어긋난다. 처음 쓴 파서가 실제로 그랬다.
INT_ARGS = frozenset({"round", "to_round", "value", "limit", "interval"})
BOOL_ARGS = frozenset({"audit", "answered", "once"})
# JSON 으로 읽는 칸 — **여기 없으면 문자열이다.**
# ★「`{`·`[` 로 시작하면 JSON」으로 하면 **우리 규약이 요구하는 제목이 깨진다**:
#   시험 글 제목은 `[selftest] …` 로 시작해야 하는데(04-tasks S7-2), 그 값이 JSON 으로 해석되어
#   `code 10` 이 난다. S7-1 실물 절차에서 실제로 막혔다 — **값의 모양으로 추측하면
#   언제나 이런 충돌이 생긴다.** 칸 이름은 계약이 정하고, 계약은 충돌하지 않는다.
JSON_ARGS = frozenset({"envelope", "deadlines", "counter", "refs", "parent",
                       "dissent", "recommended_actions", "arguments"})


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
        return run(store=ctx.store, spool=ctx.spool, cursor=Cursor(_config_dir(d)),
                   ledger=ctx.ledger,
                   interval=int(kw.get("interval", 60)),
                   once=bool(kw.get("once", False)))
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
    """
    out: dict[str, Any] = {}
    for token in rest:
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
    if name == "mcp-serve":
        # ★결과를 **안 돌려준다**(None). 이 명령의 출력은 stdout 의 **프로토콜 줄**이고,
        #   여기서 반환값을 주면 main 이 그 위에 JSON 을 한 줄 더 찍어 프로토콜을 깬다.
        from agora import mcp_server
        mcp_server.serve()
        return None
    if name in ("watch", "reconcile", "export", "import"):
        return _run_local(name, list(args.rest) if hasattr(args, "rest") else [])
    if meta["core"]:
        # ★코어 도구는 **한 줄로** 넘긴다. 도구마다 여기에 분기를 만들면 그 분기가
        #   두 번째 계약이 되고, 언젠가 표와 갈라진다(그때 갈라진 쪽이 조용히 이긴다).
        from agora import tools
        rest = list(args.rest) if hasattr(args, "rest") else []
        return tools.call(name, tools.context_from_config(), _kv(rest))
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
