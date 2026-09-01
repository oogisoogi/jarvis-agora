"""NFR-8 정적 검사 — **정본 경로에 남의 본문을 쓰는 코드 경로 0**(03 §8 · 결정 R-11 A안).

★왜 정적 검사인가: 「아고라는 정본을 자동으로 적재하지 않는다」는 약속은 실행 중 관측으로 못 잰다 —
  안 일어난 일은 로그에 없다. **코드에 그런 경로가 없다**는 것만이 증거이고, 그것은 소스를 읽어야 한다.
★두 축으로 잰다(하나만 재면 반대쪽이 뚫려도 초록이다):
  ⑴ **경로 축** — 쓰기 sink(`open(..,"w"/"a")`·`os.replace/rename`·`shutil.copy*/move`·`.write_text/bytes`)의
     대상 경로 식에 정본 마커(`docs/`·`skills/`·`config/`·`participants/`·`.mcp.json`·지침 파일)가 닿으면
     그 sink 는 **허용목록**(`tests/nfr8-allowlist.txt`)에 사유와 함께 적혀 있어야 한다. 경로 식은
     지역변수 → 모듈 상수 → **같은 모듈 함수의 return 식**까지 따라간다(brief.write_all 이 그 형태다).
  ⑵ **본문 축** — 허용된 sink 를 품은 함수는 이벤트 본문 식별자(`body`·`payload`·`events`·`collected`·
     `quarantined`·`stale`)를 이름·속성·첨자 키로 **참조하지 않는다**. 허용은 「렌더 사본을 쓴다」에
     대한 것이지 「남의 글을 쓴다」에 대한 것이 아니다.
★**못 재는 것(숨기지 않는다)**: 본문 축은 이름 기반 휴리스틱이다 — 본문이 다른 이름의 변수로
  옮겨 담긴 뒤 허용 sink 에 닿으면 못 본다. 경로 축도 리터럴이 아예 없는 경로(전부 인자로 받은 경로)는
  마커를 못 본다. 그래서 허용목록은 **짧아야** 하고, 목록 밖 마커 sink 는 예외 없이 적색이다.
★검사기 자신도 뮤테이션 대상이다(M271·M272) — 문서에 위반을 심어 재는 시험은 검사기 코드의 회귀를 못 본다.
"""

from __future__ import annotations

import ast
import os
from typing import Any

DIR_MARKERS = frozenset({"docs", "skills", "config", "participants"})
FILE_MARKERS = frozenset({".mcp.json", "CLAUDE.md", "AGENTS.md"})
BODY_NAMES = frozenset({"body", "payload", "events", "collected", "quarantined", "stale"})
WRITE_MODES = frozenset("wax+")
SCAN_FILES = ("bin/agora", "bin/agora-signer")
SCAN_DIRS = ("agora",)
EXCLUDE = frozenset({"agora/selftest.py"})     # 하네스 자신 — 픽스처에 위반이 들어 있는 것이 정상이다
_DEPTH = 4


def _marked(literal: str) -> list[str]:
    parts = [p for p in literal.replace("\\", "/").split("/") if p]
    hits = [p for p in parts if p in DIR_MARKERS]
    if parts and parts[-1] in FILE_MARKERS:
        hits.append(parts[-1])
    return hits


class _Module:
    def __init__(self, tree: ast.Module) -> None:
        self.consts: dict[str, ast.expr] = {}
        self.funcs: dict[str, ast.FunctionDef] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                self.consts[node.targets[0].id] = node.value
            elif isinstance(node, ast.FunctionDef):
                self.funcs[node.name] = node


def _literals(expr: ast.AST, mod: _Module, local: dict[str, ast.expr],
              depth: int, seen: set[str]) -> list[str]:
    """경로 식에서 닿을 수 있는 문자열 리터럴 전부 — 이름·상수·같은 모듈 함수 반환까지."""
    out: list[str] = []
    if depth < 0:
        return out
    for node in ast.walk(expr):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
        elif isinstance(node, ast.Name):
            key = node.id
            if key in seen:
                continue
            seen.add(key)
            if key in local:
                out += _literals(local[key], mod, local, depth - 1, seen)
            elif key in mod.consts:
                out += _literals(mod.consts[key], mod, {}, depth - 1, seen)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in mod.funcs:
            fkey = "fn:" + node.func.id
            if fkey in seen:
                continue
            seen.add(fkey)
            fn = mod.funcs[node.func.id]
            flocal = _locals_of(fn)
            for ret in ast.walk(fn):
                if isinstance(ret, ast.Return) and ret.value is not None:
                    out += _literals(ret.value, mod, flocal, depth - 1, seen)
    return out


def _locals_of(fn: ast.FunctionDef) -> dict[str, ast.expr]:
    local: dict[str, ast.expr] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            local[node.targets[0].id] = node.value
    return local


def _sink_target(call: ast.Call) -> tuple[str, ast.AST] | None:
    """이 호출이 쓰기 sink 면 (종류, 대상 경로 식). 아니면 None."""
    f = call.func
    if isinstance(f, ast.Name) and f.id == "open":
        mode = None
        if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
            mode = call.args[1].value
        for kw in call.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
        if isinstance(mode, str) and (set(mode) & WRITE_MODES) and call.args:
            return "open", call.args[0]
        return None
    if isinstance(f, ast.Attribute):
        owner = f.value.id if isinstance(f.value, ast.Name) else None
        if owner == "os" and f.attr in ("replace", "rename") and len(call.args) >= 2:
            return "os." + f.attr, call.args[1]
        if owner == "shutil" and f.attr in ("copy", "copyfile", "copy2", "move") \
                and len(call.args) >= 2:
            return "shutil." + f.attr, call.args[1]
        if f.attr in ("write_text", "write_bytes"):
            return "." + f.attr, f.value
    return None


def _taint(fn: ast.AST) -> list[str]:
    """함수 안에서 본문 식별자를 건드리는 자리(줄 번호·형태)."""
    hits: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id in BODY_NAMES:
            hits.append(f"name:{node.id}@{node.lineno}")
        elif isinstance(node, ast.Attribute) and node.attr in BODY_NAMES:
            hits.append(f"attr:{node.attr}@{node.lineno}")
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and node.slice.value in BODY_NAMES:
            hits.append(f"key:{node.slice.value}@{node.lineno}")
    return hits


def scan_source(source: str, relpath: str) -> list[dict[str, Any]]:
    """한 파일의 쓰기 sink 전부 — 각각 마커·둘러싼 함수·본문 오염 자리를 붙여서."""
    tree = ast.parse(source, filename=relpath)
    mod = _Module(tree)
    rows: list[dict[str, Any]] = []
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    def enclosing(node: ast.AST) -> ast.FunctionDef | None:
        cur: ast.AST | None = node
        while cur is not None:
            if isinstance(cur, ast.FunctionDef):
                return cur
            cur = parents.get(id(cur))
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        sink = _sink_target(node)
        if sink is None:
            continue
        kind, target = sink
        fn = enclosing(node)
        local = _locals_of(fn) if fn is not None else {}
        lits = _literals(target, mod, local, _DEPTH, set())
        markers = sorted({m for lit in lits for m in _marked(lit)})
        rows.append({"file": relpath, "line": node.lineno, "sink": kind,
                     "func": fn.name if fn is not None else "<module>",
                     "markers": markers,
                     "taint": _taint(fn) if fn is not None else []})
    return rows


def scan(root: str, allowlist: dict[str, str]) -> dict[str, Any]:
    """저장소 전체 — 결과에 **검사한 파일 수·sink 수**를 함께 싣는다(0 이 「못 봤다」가 아니게)."""
    files: list[str] = list(SCAN_FILES)
    for d in SCAN_DIRS:
        for name in sorted(os.listdir(os.path.join(root, d))):
            if name.endswith(".py"):
                files.append(f"{d}/{name}")
    files = [f for f in files if f not in EXCLUDE]
    rows: list[dict[str, Any]] = []
    for rel in files:
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            rows += scan_source(fh.read(), rel)
    marked = [r for r in rows if r["markers"]]
    keys = {f"{r['file']}:{r['func']}" for r in marked}
    violations = [r for r in marked if f"{r['file']}:{r['func']}" not in allowlist]
    tainted = [r for r in marked if f"{r['file']}:{r['func']}" in allowlist and r["taint"]]
    stale = sorted(set(allowlist) - keys)
    return {"files": len(files), "sinks": len(rows), "marked": marked,
            "violations": violations, "tainted": tainted, "stale_allowlist": stale,
            "ok": not violations and not tainted and not stale}


def load_allowlist(path: str) -> dict[str, str]:
    """`파일:함수  # 사유` — 사유 없는 줄은 목록에 없는 것으로 친다."""
    out: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, _, why = line.partition("#")
            if name.strip() and why.strip():
                out[name.strip()] = why.strip()
    return out
