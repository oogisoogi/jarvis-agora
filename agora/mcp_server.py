"""MCP 서버 — 도구 11종을 **코어 함수 시그니처에서 파생해** 노출한다(설계 §4 · 04-tasks S6-1).

★**스키마를 손으로 적지 않는다.** 손으로 적으면 코어 함수에 인자를 하나 더한 날
  스키마가 조용히 낡고, 원격 클라이언트는 **없는 인자를 못 보내거나 있는 인자를 잘못 보낸다.**
  ⇒ `inspect` 로 시그니처에서 파생하고, **한쪽만 바뀌면 시험이 적색**을 낸다.

★**MCP 인자에는 파일 경로가 없다**(04-tasks AC ②). 원격 클라이언트는 우리 파일 시스템을
  갖고 있지 않다 — 경로를 받는 도구는 그 클라이언트에서 **반드시 실패한다.**
  파일 인자는 CLI 의 몫이고(`--body-file`), 그 경계를 시험이 지킨다.

⚠**못 잰 것**: 실제 MCP 클라이언트와의 연동(전송 계층 준수)은 여기서 검증하지 않는다.
  이 파일이 재는 것은 **도구 목록과 스키마가 코어와 일치한다**는 것까지다.
"""

from __future__ import annotations

import inspect
import json
import sys
from typing import Any

from agora import cli, errors, tools
from agora.errors import AgoraError

PROTOCOL_HINT = "tools/list · tools/call"

# 경로처럼 보이는 인자 이름 — 이런 칸이 MCP 표면에 있으면 안 된다.
PATH_LIKE = ("path", "file", "dir", "directory", "out", "filename")

_TYPE_MAP = {
    "str": "string", "int": "integer", "bool": "boolean",
    "dict": "object", "list": "array", "Any": "object",
}


def _json_type(annotation: Any) -> str:
    """주석에서 JSON 타입을 고른다. **모르면 추측하지 않고 object 로 둔다.**"""
    text = annotation if type(annotation) is str else getattr(annotation, "__name__", "Any")
    text = text.replace(" | None", "").strip()
    for key, value in _TYPE_MAP.items():
        if text.startswith(key) or text.startswith(f"{key}[") or text == key:
            return value
    return "object"


def tool_schema(name: str) -> dict[str, Any]:
    """코어 함수 하나의 MCP 스키마 — **시그니처가 정본**이다."""
    fn = tools.CORE_TOOLS[name]
    props: dict[str, Any] = {}
    required: list[str] = []
    for param in list(inspect.signature(fn).parameters.values())[1:]:   # ctx 제외
        props[param.name] = {"type": _json_type(param.annotation)}
        if param.default is inspect.Parameter.empty:
            required.append(param.name)
    return {"name": cli.mcp_tool_name(name),
            "description": (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else name,
            "inputSchema": {"type": "object", "properties": props, "required": required}}


def tool_schemas() -> list[dict[str, Any]]:
    """도구 11종 전건. 순서는 계약 표(등록표) 순서를 따른다."""
    return [tool_schema(name) for name in tools.CORE_TOOLS]


def path_like_arguments() -> list[str]:
    """MCP 표면에 남아 있는 **경로형 인자**. 있으면 계약 위반이다(비어 있어야 한다)."""
    found = []
    for schema in tool_schemas():
        for arg in schema["inputSchema"]["properties"]:
            low = arg.lower()
            if any(low == p or low.endswith("_" + p) for p in PATH_LIKE):
                found.append(f"{schema['name']}.{arg}")
    return sorted(found)


def handle(request: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
    """`tools/list` 와 `tools/call` 만 다룬다.

    ★모르는 메서드는 **거부한다.** 조용히 빈 응답을 주면 클라이언트는 「그런 도구가 없다」와
      「우리가 그 요청을 이해 못 했다」를 구별하지 못한다.
    """
    method = request.get("method")
    if method == "tools/list":
        return {"tools": tool_schemas()}
    if method != "tools/call":
        raise AgoraError(errors.ARGUMENT, "모르는 메서드",
                         {"method": method, "supported": PROTOCOL_HINT})
    params = request.get("params") or {}
    full = params.get("name") or ""
    inner = _cli_name(full)
    if inner is None:
        # ★`surface` 로 **이 층임을 표시**한다. 아래 `tools.call` 도 같은 것을 막지만,
        #   표식이 없으면 「어느 층이 막았는가」를 시험이 구별하지 못하고 — 실제로 못 했다 —
        #   이 문을 지워도 아래 문이 대신 답해 **초록이 유지된다**(M187 이 살아남은 자리).
        raise AgoraError(errors.ARGUMENT, "계약에 없는 도구",
                         {"tool": full, "surface": "mcp"})
    context = ctx if ctx is not None else tools.context_from_config()
    return {"result": tools.call(inner, context, dict(params.get("arguments") or {}))}


def _cli_name(mcp_name: str) -> str | None:
    for name in tools.CORE_TOOLS:
        if cli.mcp_tool_name(name) == mcp_name:
            return name
    return None


def serve(stdin: Any = None, stdout: Any = None) -> int:
    """줄 단위 JSON 요청/응답. 오류도 **JSON 으로** 돌려준다(계약 코드 유지)."""
    src = stdin or sys.stdin
    dst = stdout or sys.stdout
    for line in src:
        line = line.strip()
        if not line:
            continue
        try:
            response = handle(json.loads(line))
        except AgoraError as e:
            response = {"error": json.loads(e.to_json())}
        except ValueError:
            response = {"error": {"code": errors.ARGUMENT, "message": "JSON 이 아니다"}}
        dst.write(json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n")
        dst.flush()
    return errors.OK
