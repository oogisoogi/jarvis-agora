"""스크럽 게이트 — 나가기 전에 막는다.

★**fail-closed 가 이 모듈의 유일한 기본값이다.** 규칙 파일이 없거나 깨졌으면
  「검사할 수 없으니 통과」가 아니라 **전량 차단**이다. 검사하지 못한 것을 통과시키면
  게이트가 있는 것보다 나쁘다 — 있다고 믿게 만들기 때문이다.

2단이다(설계 §5): ⑴**allowlist** — 필드별 허용 길이·구조 · 첨부/이미지/HTML/멘션/비허용 URL 금지
                  ⑵**denylist** — 이메일·전화·비밀키·경로·사설 IP 형태.
  ★두 겹의 뜻이 다르다. allowlist 는 **모양이 우리 것인가**를 묻고(모르는 구조는 거부),
    denylist 는 **아는 위험이 들어 있나**를 묻는다(아는 것만 잡는다).
    denylist 만 두면 목록에 없는 위험이 그대로 나가고, allowlist 만 두면 우리 모양 안에 담긴
    이메일·키가 그대로 나간다.

범위(정직 고지): 픽스처 8종 전건 차단·**정상문 오탐 0** 측정은 **S3-2** 가 한다.
  그러므로 지금의 통과는 「두 겹을 통과했다」이지 「안전하다」가 아니다 —
  목록에 없는 실명·주소·자유문 개인정보는 기계가 못 잡는다(설계 §5 잔여 위험 · human_approval).
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
DEFAULT_ALLOW_PATH = os.path.join(_ROOT, "config", "allowlist-v1.json")
DEFAULT_DOMAINS_PATH = os.path.join(_ROOT, "config", "allow-domains.txt")
# ★이름 목록은 **참가자 로컬**이다(설계 §5·§7). 저장소에는 예시만 둔다 —
#   「무엇을 가리려 하는지」 자체가 정보이기 때문이다.
NAMES_FILENAME = "scrub-names.txt"
DEFAULT_NAMES_PATH = os.path.join(_ROOT, NAMES_FILENAME.join(("config/", "")))


def names_path() -> str:
    """이름 목록이 실제로 있는 자리 — **참가자 설정 폴더가 먼저**다(M-f · codex 2026-08-26).

    ★★그전에는 저장소 안의 한 경로로 **고정**돼 있었다. 그런데 이름 목록은 참가자 로컬이라
      `ONBOARDING` 이 시키는 대로 `AGORA_CONFIG_DIR` 에 둔 사람의 목록은 **아무도 안 읽었다.**
      ⇒ 문서대로 한 사람의 스크럽이 **조용히 0건으로** 돌았다. 「안 걸렀다」와
      「걸릴 것이 없었다」가 같아지는 자리다(이 파일이 애초에 막으려던 것).
    ★환경변수로 자리를 정하는 이유: **서명기는 다른 프로세스**다. 인자로 넘기면
      두 겹(코어·서명기)이 서로 다른 목록을 볼 수 있고, 그러면 재검사가 재검사가 아니다.
      같은 규칙으로 **같은 자리를** 찾게 두는 것이 두 겹을 진짜 두 겹으로 만든다.
    """
    from agora.participant import config_dir
    local = os.path.join(config_dir(), NAMES_FILENAME)
    return local if os.path.exists(local) else DEFAULT_NAMES_PATH

# URL 은 호스트만 본다. 경로·질의는 denylist 와 필드 길이가 따로 본다.
_URL = re.compile(r"(?i)\bhttps?://([^\s/?#\\)\]>'\"]+)")


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


class AllowRules:
    def __init__(self, version: str, default: dict[str, Any], fields: dict[str, Any],
                 forbidden: list[tuple[str, str, re.Pattern[str]]],
                 domains: frozenset[str], digest: str) -> None:
        self.version = version
        self.default = default
        self.fields = fields
        self.forbidden = forbidden
        self.domains = domains
        self.digest = digest


def _load_domains(path: str) -> frozenset[str]:
    """허용 도메인 목록. **없거나 비면 공집합** — 그러면 모든 URL 이 막힌다(fail-closed)."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return frozenset()
    return frozenset(
        line.strip().lower() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def load_allow(path: str | None = None, domains_path: str | None = None) -> AllowRules:
    """allowlist 규칙 — 규칙 파일이 없거나 깨졌으면 여기서도 **전량 차단**이다."""
    path = path or DEFAULT_ALLOW_PATH
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        raise AgoraError(errors.GATE_REJECT,
                         "allowlist 파일을 읽을 수 없다 — 전량 차단(fail-closed)",
                         {"path": os.path.basename(path), "error": e.strerror}) from None
    domains = _load_domains(domains_path or DEFAULT_DOMAINS_PATH)
    digest = hashlib.sha256(
        raw + b"\n" + "\n".join(sorted(domains)).encode("utf-8")).hexdigest()
    try:
        doc = json.loads(raw.decode("utf-8"))
        forbidden = [(r["id"], r["kind"], re.compile(r["pattern"]))
                     for r in doc["forbidden"]]
        version, default, fields = doc["version"], doc["default"], doc["fields"]
    except (ValueError, KeyError, TypeError, re.error) as e:
        raise AgoraError(errors.GATE_REJECT,
                         "allowlist 파일이 깨졌다 — 전량 차단(fail-closed)",
                         {"error": str(e)}) from None
    if not forbidden:
        raise AgoraError(errors.GATE_REJECT,
                         "금칙 구조가 0개다 — 검사가 무의미하므로 전량 차단",
                         {"digest": digest})
    return AllowRules(version, default, fields, forbidden, domains, digest)


def _host_allowed(host: str, domains: frozenset[str]) -> bool:
    """호스트가 허용 목록에 있는가. 앞에 `.` 이 붙은 항목은 하위 도메인을 포함한다."""
    host = host.lower().rsplit("@", 1)[-1].split(":", 1)[0]
    if host in domains:
        return True
    return any(d.startswith(".") and (host.endswith(d) or host == d[1:])
               for d in domains)


def _field_key(path: str) -> str:
    """`$.payload.body[2]` → `payload.body` — 배열 첨자와 뿌리 표시를 떼어 규칙과 맞춘다."""
    return re.sub(r"\[[0-9]+\]", "", path).removeprefix("$.")


def check_allow(payload: Any, allow: AllowRules | None = None) -> list[dict[str, Any]]:
    """모양이 우리 것인가 — 길이·금칙 구조·URL 호스트를 본다."""
    allow = allow or load_allow()
    findings: list[dict[str, Any]] = []
    for where, text in _walk_strings(payload):
        key = _field_key(where)
        spec = allow.fields.get(key, allow.default)
        if "max_chars" in spec and len(text) > spec["max_chars"]:
            findings.append({"rule": "max_chars", "kind": "길이 상한", "where": where,
                             "len": len(text), "max": spec["max_chars"]})
        if "max_bytes" in spec:
            size = len(text.encode("utf-8"))
            if size > spec["max_bytes"]:
                findings.append({"rule": "max_bytes", "kind": "바이트 상한",
                                 "where": where, "bytes": size,
                                 "max": spec["max_bytes"]})
        for rid, kind, pattern in allow.forbidden:
            m = pattern.search(text)
            if m:
                findings.append({"rule": rid, "kind": kind, "where": where,
                                 "span": [m.start(), m.end()]})
        for m in _URL.finditer(text):
            if not _host_allowed(m.group(1), allow.domains):
                # ★적발된 호스트는 담지 않는다 — 보고서가 유출 경로가 되면 안 된다.
                findings.append({"rule": "url-domain", "kind": "허용 밖 도메인",
                                 "where": where, "span": [m.start(), m.end()]})
    return findings


def _walk_strings(node: Any, path: str = "$"):
    if type(node) is str:
        yield path, node
    elif type(node) is list:
        for i, v in enumerate(node):
            yield from _walk_strings(v, f"{path}[{i}]")
    elif type(node) is dict:
        for k, v in node.items():
            yield from _walk_strings(v, f"{path}.{k}")


def load_names(path: str | None = None) -> frozenset[str]:
    """이름 목록. **없으면 공집합**이고 그것은 정상이다.

    ★규칙 파일 부재(전량 차단)와 다르다. 규칙 파일은 「검사기가 고장났다」이고,
      이름 목록 부재는 「이 참가자가 가릴 이름을 아직 안 적었다」다.
      다만 **조용히 다르면 안 되므로** 보고서에 몇 개를 실었는지 적는다 —
      0 이 보이면 「안 걸렀다」와 「걸릴 것이 없었다」를 사람이 구별할 수 있다.
    """
    path = path or names_path()
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return frozenset()
    return frozenset(
        line.strip().lower() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def check_names(payload: Any, names: frozenset[str]) -> list[dict[str, Any]]:
    for where, text in _walk_strings(payload):
        low = text.lower()
        for name in names:
            if name in low:
                # ★이름 자체는 담지 않는다 — 보고서가 유출 경로가 되면 안 된다.
                yield_ = {"rule": "name-list", "kind": "이름 목록", "where": where,
                          "span": [low.index(name), low.index(name) + len(name)]}
                yield yield_


def check(payload: Any, rules: Rules | None = None,
          allow: AllowRules | None = None,
          names: frozenset[str] | None = None) -> dict[str, Any]:
    """구조 전체의 문자열을 훑어 차단 사유를 모은다.

    반환은 **보고서**이지 판정 집행이 아니다 — 집행(전송 중단)은 호출자가 한다.
    보고서에 `rules` digest 를 넣는 이유: 수신 측이 「어떤 규칙으로 걸렀다는 주장인지」를
    대조할 수 있어야 하기 때문이다(설계 M-11).
    """
    rules = rules or load_rules()
    allow = allow or load_allow()
    names = load_names() if names is None else names
    findings: list[dict[str, Any]] = list(check_allow(payload, allow))
    findings.extend(check_names(payload, names))
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
        # ★수신 측이 「어떤 규칙으로 걸렀다는 주장인지」를 대조하려면 **두 겹 다** 필요하다.
        "allow_rules": allow.digest,
        "allow_version": allow.version,
        "bundle": hashlib.sha256(
            (rules.digest + allow.digest).encode("utf-8")).hexdigest(),
        # ★0 이 보이면 「안 걸렀다」와 「걸릴 것이 없었다」를 사람이 구별할 수 있다.
        "names_loaded": len(names),
        "blocked": len(findings),
        "redacted": 0,
        "findings": findings,
    }


def current_bundle() -> str:
    """지금 이 노드가 쓰는 **규칙 묶음 해시**.

    ★이 값이 필요한 이유: 받은 이벤트가 「어떤 규칙으로 걸렀다」고 주장하는지를 **지금 규칙과
      대조**해야 `scrub_recheck` 를 켤 수 있다. 대조할 값을 못 구하면 그 칸은 영원히 False 다
      — 즉 「규칙이 바뀐 뒤에 온 옛 글」을 아무도 못 알아본다(2026-08-26 실측: 그 상태였다).
    """
    return check({"payload": {}})["bundle"]


def enforce(payload: Any, rules: Rules | None = None,
            allow: AllowRules | None = None,
            names: frozenset[str] | None = None) -> dict[str, Any]:
    """차단이 1건이라도 있으면 code 3 으로 멈춘다. 통과하면 보고서를 돌려준다."""
    report = check(payload, rules, allow, names)
    if report["blocked"]:
        raise AgoraError(errors.GATE_REJECT, "스크럽 게이트 차단",
                         {"blocked": report["blocked"],
                          "rules": [f["rule"] for f in report["findings"]],
                          "where": [f["where"] for f in report["findings"]]})
    return report
