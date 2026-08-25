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


# ── 전송 계층 — JSON-RPC 2.0 stdio (master 결정 2026-08-26 (a)안) ───────────
# ★★**왜 이 층이 새로 생겼나**: 그전까지 이 파일은 **우리가 지은 방언**을 말했다
#   (`{"method":…}` → `{"tools":…}`). 도구 표도 맞았고 시험도 초록이었는데,
#   **실제 MCP 클라이언트는 첫 줄(`initialize`)에서 끊겼다.**
#   그 초록이 왜 아무것도 증명하지 못했나 — **그 시험의 클라이언트를 우리가 썼기 때문이다.**
#   서버와 클라이언트가 같은 저자면 둘은 언제나 서로 맞는다.
#   ⇒ ★**외부 계약은 외부 규약으로 재야 하고, 그 규약은 우리가 쓰지 않은 것이어야 한다.**
#     (「구현했다 ≠ 배선됐다」의 한 겹 더: **배선됐다 ≠ 남이 쓸 수 있다**.)
#
# ★`handle()` 은 **코어로 그대로 남긴다** — 이 층은 봉투만 씌운다. 로직을 여기로 옮기면
#   전송 규약이 바뀔 때마다 판정 로직이 함께 흔들린다.

JSONRPC = "2.0"
# 협상 가능한 규약 판본. 클라이언트가 보낸 값을 **되돌려 준다** — 우리가 아는 것일 때만.
SUPPORTED_PROTOCOLS = ("2025-06-18", "2024-11-05")
SERVER_INFO = {"name": "agora", "version": "0.1.0"}

# JSON-RPC 가 정한 오류 코드. ★**우리 code 는 버리지 않고 `data` 에 넣는다** —
#   규약 코드로 좁히면 「어느 계약이 막았는가」가 사라진다.
RPC_PARSE_ERROR = -32700
RPC_INVALID_REQUEST = -32600
RPC_METHOD_NOT_FOUND = -32601
RPC_INTERNAL_ERROR = -32603


def _rpc_error(code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return err


def negotiate(protocol: Any) -> str:
    """규약 판본 협상 — 아는 것이면 **그대로 되돌려 주고**, 모르면 거부한다.

    ★조용히 우리 판본으로 바꿔 답하면 클라이언트는 자기가 요청한 판본으로 말하고
      우리는 다른 판본으로 답하는 상태가 된다 — 그 어긋남은 한참 뒤 엉뚱한 자리에서 터진다.
    """
    if protocol is None:
        return SUPPORTED_PROTOCOLS[0]
    if protocol in SUPPORTED_PROTOCOLS:
        return protocol
    raise AgoraError(errors.ARGUMENT, "모르는 규약 판본",
                     {"got": str(protocol)[:40], "supported": list(SUPPORTED_PROTOCOLS)})


def rpc_dispatch(request: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
    """메서드 → **MCP `result` 본문**. 전송 봉투는 `serve` 가 씌운다."""
    method = request.get("method")
    if method == "initialize":
        params = request.get("params") or {}
        return {"protocolVersion": negotiate(params.get("protocolVersion")),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO}
    if method == "tools/call":
        # `handle` 은 `{"result": <도구 반환>}` 을 준다. MCP 는 **content 배열**을 원한다.
        inner = handle(request, ctx=ctx)["result"]
        return {"content": [{"type": "text",
                             "text": json.dumps(inner, ensure_ascii=False,
                                                sort_keys=True)}]}
    return handle(request, ctx=ctx)          # tools/list · 모르는 메서드는 여기서 거부된다


def serve(stdin: Any = None, stdout: Any = None, *, ctx: Any = None) -> int:
    """JSON-RPC 2.0 stdio 루프.

    ★★**알림(`id` 없는 요청)에는 아무것도 쓰지 않는다** — 성공도 오류도. 규약이 그렇다.
      한 줄이라도 내보내면 클라이언트는 짝 없는 응답을 받고 프레이밍이 어긋난다
      (구판이 `notifications/initialized` 에 **오류를 답해서** 실제로 그랬다).
    """
    src = stdin or sys.stdin
    dst = stdout or sys.stdout
    for line in src:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            _write(dst, {"jsonrpc": JSONRPC, "id": None,
                         "error": _rpc_error(RPC_PARSE_ERROR, "JSON 이 아니다")})
            continue
        if type(request) is not dict:
            _write(dst, {"jsonrpc": JSONRPC, "id": None,
                         "error": _rpc_error(RPC_INVALID_REQUEST, "요청은 객체여야 한다")})
            continue
        # ★`id` 의 **존재**로 가른다(값이 아니라). `id: null` 도 응답을 요구하는 요청이다.
        notification = "id" not in request
        try:
            result = rpc_dispatch(request, ctx=ctx)
        except AgoraError as e:
            if notification:
                continue                     # ⛔알림에는 오류도 안 보낸다
            unknown = (e.code == errors.ARGUMENT
                       and (e.detail or {}).get("supported") is not None)
            _write(dst, {"jsonrpc": JSONRPC, "id": request.get("id"),
                         "error": _rpc_error(
                             RPC_METHOD_NOT_FOUND if unknown else RPC_INTERNAL_ERROR,
                             e.message,
                             {"agora_code": e.code, "name": errors.NAMES.get(e.code),
                              "detail": e.detail})})
            continue
        if notification:
            continue                         # ⛔성공해도 알림에는 응답 없음
        _write(dst, {"jsonrpc": JSONRPC, "id": request.get("id"), "result": result})
    return errors.OK


def _write(dst: Any, payload: dict[str, Any]) -> None:
    dst.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    dst.flush()
