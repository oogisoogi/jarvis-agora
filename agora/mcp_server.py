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
RPC_INVALID_PARAMS = -32602
RPC_INTERNAL_ERROR = -32603


def _rpc_error(code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return err


def negotiate(protocol: Any) -> str:
    """규약 판본 협상(MCP Lifecycle §Version Negotiation).

    ★규약이 정한 것은 이렇다: 요청 판본을 **지원하면 같은 판본으로 응답** ·
      **지원하지 않으면 서버가 지원하는 판본으로 응답** · 그 판본을 못 쓰겠으면
      **클라이언트가** 연결을 끊는다. ⇒ **거절은 서버의 몫이 아니다.**

    ★★**초판은 이것을 반대로 했다**(2026-08-26 master 의 C-7 실측이 잡았다):
      모르는 판본을 **거부**했다. 그래서 Claude Code 2.1.245 가 보내는 `2025-11-25` 에
      `-32601` 을 냈고, 클라이언트는 **조용히 서버를 버렸다**(도구 0종). 화면에는 오류도 안 뜬다.
      ⇒ 「조용한 강제 변환은 나쁘다」는 내 규율이 옳았지만 **적용할 자리를 틀렸다**:
        규약이 요구하는 것은 「지원 판본으로 **답하기**」이지 「거부」가 아니다.
        그리고 그 답 자체가 협상 결과의 **명시**라서 조용한 변환이 아니다.
    ⚠거부는 **`protocolVersion` 이 아예 없거나 문자열이 아닐 때만** — 그건 협상이 아니라
      깨진 요청이다.
    """
    if type(protocol) is not str or not protocol:
        raise AgoraError(errors.ARGUMENT, "protocolVersion 이 문자열이 아니다",
                         {"got": type(protocol).__name__,
                          "supported": list(SUPPORTED_PROTOCOLS)})
    if protocol in SUPPORTED_PROTOCOLS:
        return protocol
    # 모르는 판본 — **우리가 지원하는 최신 판본으로 답한다.** 이어 갈지는 클라이언트가 정한다.
    return SUPPORTED_PROTOCOLS[0]


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
                             # ★R6 ⓑ(codex 라운드 5) — data 는 to_dict 에서 **파생**한다(손조립 금지). 손으로 세 키만 옮기니
                             #   retryable·message 가 MCP 에 안 나갔다 — 03 §4 「오류 = {code, retryable, message, detail}」
                             #   미달의 선재 공백이었고, retryable 이 인스턴스 판단이 되면서(R5) 그 공백이 실제 의미를 가졌다.
                             {"agora_code": e.code,
                              **{k: v for k, v in e.to_dict().items() if k != "code"}})})
            continue
        except Exception as e:                # noqa: BLE001 — 최후 경계는 넓어야 한다
            # ★★M-c(codex 2026-08-26) — **한 요청이 서버 전체를 죽이던 자리.**
            #   여기는 `AgoraError` 만 잡고 있었다. 그런데 도구 인자가 계약과 다르면
            #   파이썬이 먼저 `TypeError` 를 던진다(우리 오류가 아니다) ⇒ 루프를 뚫고 나가
            #   **프로세스가 끝난다.** 붙어 있던 클라이언트는 이유 없이 연결을 잃는다.
            #   ⇒ 남이 보낸 한 줄로 남의 서버를 끌 수 있다는 뜻이다.
            # ★그래서 최후 경계는 **넓게** 잡는다: 모르는 실패도 **응답으로** 만들고 계속 산다.
            #   ⚠넓게 잡는 대가 = 진짜 결함이 조용해진다. 그래서 **삼키지 않는다** —
            #   예외 종류와 문구를 응답에 실어 보낸다(감춘 것이 아니라 옮긴 것이다).
            if notification:
                continue
            bad_args = isinstance(e, (TypeError, ValueError))
            # ⚠형태를 위 블록과 **일부러 다르게** 쓴다: 뮤테이션 하네스는 (파일·문자열)로
            #   조준하므로 같은 모양이 두 번 나오면 그 조준이 **NOT-APPLIED** 로 죽는다
            #   (여기서 실제로 M233 이 그렇게 됐다 — 고친 것이 아니라 안 재게 된 것이다).
            failure = _rpc_error(RPC_INVALID_PARAMS if bad_args else RPC_INTERNAL_ERROR,
                                 "요청을 처리하지 못했다",
                                 {"exception": type(e).__name__, "why": str(e)[:200]})
            _write(dst, {"jsonrpc": JSONRPC, "id": request.get("id"), "error": failure})
            continue
        if notification:
            continue                         # ⛔성공해도 알림에는 응답 없음
        _write(dst, {"jsonrpc": JSONRPC, "id": request.get("id"), "result": result})
    return errors.OK


def _write(dst: Any, payload: dict[str, Any]) -> None:
    dst.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    dst.flush()
