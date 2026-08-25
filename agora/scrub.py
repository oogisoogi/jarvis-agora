"""스크럽 게이트 — 나가기 전에 막는다.

★**fail-closed 가 이 모듈의 유일한 기본값이다.** 규칙 파일이 없거나 깨졌으면
  「검사할 수 없으니 통과」가 아니라 **전량 차단**이다. 검사하지 못한 것을 통과시키면
  게이트가 있는 것보다 나쁘다 — 있다고 믿게 만들기 때문이다.

범위(정직 고지): 이 슬라이스(S1-3)가 채운 것은 **denylist** 뿐이다.
  allowlist(필드별 허용 문자·길이·구조 · 첨부/이미지/HTML/멘션/비허용 URL 금지)는 **S3-1** 이 더하고,
  픽스처 8종 전건 차단·정상문 오탐 0 측정은 **S3-2** 가 한다.
  그러므로 **지금의 통과는 「denylist 를 통과했다」이지 「안전하다」가 아니다.**
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from agora import errors
from agora.errors import AgoraError

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RULES_PATH = os.path.join(_ROOT, "config", "scrub-rules-v1.json")


class Rules:
    def __init__(self, version: str, compiled: list[tuple[str, str, re.Pattern[str]]],
                 digest: str) -> None:
        self.version = version
        self.compiled = compiled
        self.digest = digest


def load_rules(path: str | None = None) -> Rules:
    path = path or DEFAULT_RULES_PATH
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        raise AgoraError(errors.GATE_REJECT,
                         "규칙 파일을 읽을 수 없다 — 전량 차단(fail-closed)",
                         {"path": os.path.basename(path), "error": e.strerror}) from None
    digest = hashlib.sha256(raw).hexdigest()
    try:
        doc = json.loads(raw.decode("utf-8"))
        rules = doc["rules"]
        compiled = [(r["id"], r["kind"], re.compile(r["pattern"])) for r in rules]
        version = doc["version"]
    except (ValueError, KeyError, TypeError, re.error) as e:
        raise AgoraError(errors.GATE_REJECT,
                         "규칙 파일이 깨졌다 — 전량 차단(fail-closed)",
                         {"error": str(e)}) from None
    if not compiled:
        raise AgoraError(errors.GATE_REJECT,
                         "규칙이 0개다 — 검사가 무의미하므로 전량 차단",
                         {"digest": digest})
    return Rules(version, compiled, digest)


def _walk_strings(node: Any, path: str = "$"):
    if type(node) is str:
        yield path, node
    elif type(node) is list:
        for i, v in enumerate(node):
            yield from _walk_strings(v, f"{path}[{i}]")
    elif type(node) is dict:
        for k, v in node.items():
            yield from _walk_strings(v, f"{path}.{k}")


def check(payload: Any, rules: Rules | None = None) -> dict[str, Any]:
    """구조 전체의 문자열을 훑어 차단 사유를 모은다.

    반환은 **보고서**이지 판정 집행이 아니다 — 집행(전송 중단)은 호출자가 한다.
    보고서에 `rules` digest 를 넣는 이유: 수신 측이 「어떤 규칙으로 걸렀다는 주장인지」를
    대조할 수 있어야 하기 때문이다(설계 M-11).
    """
    rules = rules or load_rules()
    findings: list[dict[str, Any]] = []
    for where, text in _walk_strings(payload):
        for rid, kind, pattern in rules.compiled:
            m = pattern.search(text)
            if m:
                findings.append({
                    "rule": rid,
                    "kind": kind,
                    "where": where,
                    # ★적발된 값 자체는 담지 않는다 — 보고서가 유출 경로가 되면 안 된다.
                    "span": [m.start(), m.end()],
                })
    return {
        "rules": rules.digest,
        "rules_version": rules.version,
        "blocked": len(findings),
        "redacted": 0,
        "findings": findings,
    }


def enforce(payload: Any, rules: Rules | None = None) -> dict[str, Any]:
    """차단이 1건이라도 있으면 code 3 으로 멈춘다. 통과하면 보고서를 돌려준다."""
    report = check(payload, rules)
    if report["blocked"]:
        raise AgoraError(errors.GATE_REJECT, "스크럽 게이트 차단",
                         {"blocked": report["blocked"],
                          "rules": [f["rule"] for f in report["findings"]],
                          "where": [f["where"] for f in report["findings"]]})
    return report
