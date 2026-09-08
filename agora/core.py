"""코어 — 쓰기 경로 하나(설계 §4 도구 계약의 공통 뼈대).

`propose`·`say`·`advance`… 는 전부 **같은 순서**를 지나야 한다:

    ⑴ 계약(스키마) → ⑵ 스크럽 게이트 → ⑶ **주인 승인** → ⑷ 서명 → ⑸ 저장층 쓰기

★순서가 규칙의 절반이다. 게이트를 서명 **뒤에** 두면 「막혔지만 서명은 남은」 이벤트가 생기고,
  저장층 쓰기 **뒤에** 두면 이미 나간 글을 막는 셈이 된다.
  그래서 이 순서를 한 함수에 못박고, **차단 시 쓰기 호출이 0 인지**를 시험한다
  (code 3 이 났다는 것만으로는 「안 썼다」가 증명되지 않는다 — 쓰고 나서 났을 수도 있다).

★서명기는 이 게이트를 **다시** 검사한다(M-11 · S3-5). 여기의 통과는 발신자의 자기주장이고,
  기록에 남는 판정은 서명기의 것이다.
"""

from __future__ import annotations

from typing import Any

from agora import errors, ledger as ledger_mod, schema, scrub, sign
from agora.contract_open import DEFAULT_HUMAN_APPROVAL, HUMAN_APPROVAL_REQUIRED
from agora.errors import AgoraError
from agora.event import render_post


def approval_gate(*, config: dict[str, Any] | None = None,
                  prompt: Any = None, isatty: Any = None) -> dict[str, Any]:
    """전송 전 주인 승인(설계 §5 H-1 · F-14). **기본은 on 이다.**

    ★기계가 못 잡는 것이 남기 때문에 있는 문이다 — 목록에 없는 실명·주소·자유문 개인정보는
      규칙으로 못 잡는다(§5 잔여 위험). 그 자리를 사람이 메운다.

    ★**띄울 수 없으면 보내지 않는다.** TTY 가 없다고 조용히 통과시키면, 승인 게이트는
      「사람이 볼 때만 작동하는 게이트」가 된다 — 무인 실행에서 정확히 무력해진다.
      그래서 code 3 으로 멈추고 사유 문자열을 못박는다(다른 code 3 과 구별돼야 한다).

    ★끄는 길은 **`config.json` 하나뿐**이다. 환경변수·명령행으로 끌 수 있으면
      「급해서 한 번만」이 생기고, 그 한 번이 기본값이 된다.
    """
    import sys as _sys
    cfg = config or {}
    if cfg.get("human_approval", DEFAULT_HUMAN_APPROVAL) is False:
        return {"required": False, "approved": True, "why": "config.json"}
    tty = (isatty or _sys.stdin.isatty)()
    if not tty:
        raise AgoraError(errors.GATE_REJECT, "승인을 받을 수 없다 — 전송하지 않는다",
                         {"reason": HUMAN_APPROVAL_REQUIRED})
    if not (prompt or (lambda: False))():
        raise AgoraError(errors.GATE_REJECT, "주인이 승인하지 않았다",
                         {"reason": "human_approval_denied"})
    return {"required": True, "approved": True, "why": "prompt"}


def publish_event(*, store: Any, event: dict[str, Any], category: str,
                  title: str = "", is_genesis: bool = False,
                  config: dict[str, Any] | None = None,
                  prompt: Any = None, isatty: Any = None,
                  ledger: Any = None,
                  before_write: Any = None,
                  config_dir: str | None = None) -> dict[str, Any]:
    """한 이벤트를 운반층에 올린다 — 위 5단계를 그 순서대로.

    ★code 8(저장 성공 불명)은 **삼키지 않는다.** 그대로 올려 호출자가 재조회로 판정하게 한다
      (`settle_unknown`). 여기서 성공으로 바꿔 주면 그 거짓이 원장에 그대로 박힌다.

    ★★`before_write` = **쓰기 직전의 마지막 관문**(호출자가 준다 · 없으면 안 부른다).
      왜 여기냐면, 이 함수 안에 **사람이 기다리는 구간**이 있기 때문이다(⑶ 승인 게이트).
      호출자가 상태를 읽고 → 승인을 기다리고 → 쓰는 동안 남이 같은 자리에 글을 올릴 수 있고,
      그 창은 **분 단위**다. 호출 **전에** 검사하면 그 창을 못 덮는다.
      던지면 그대로 올라간다 — 여기서 삼키면 CAS 가 있으나 마나가 된다.
    """
    schema.validate(event)                     # ⑴ 계약
    # ★R3-② — 이름 목록의 자리는 **Context 의 설정 폴더**에서 온다(전역 환경이 아니라). 코어에는
    #   경로를 명시하고, 서명기(별도 프로세스)에는 같은 절대경로를 **호출별 env** 로 준다.
    #   두 겹이 같은 폴더를 보게 하는 통로가 하나뿐이면 어느 쪽도 조용히 다른 목록을 못 본다.
    report = scrub.enforce(event, names_path=scrub.names_path(config_dir))   # ⑵ 게이트
    approval = approval_gate(config=config, prompt=prompt, isatty=isatty)   # ⑶ 승인
    signed = sign.sign_event(event, config_dir=config_dir)   # ⑷ 서명(서명기가 게이트를 재검사한다)
    body = render_post(event, signed["signature"])
    if before_write is not None:
        before_write()                         # ⑸ 마지막 관문(CAS 등) — 던지면 안 쓴다
    try:
        result = store.append(thread_id=event["thread_id"], category=category,
                              title=title or event["payload"].get("title", ""),
                              body=body, is_genesis=is_genesis)   # ⑷ 쓰기
    except AgoraError as e:
        if e.code != errors.UNKNOWN_COMMIT:
            raise
        # ★**여전히 삼키지 않는다** — 그대로 올린다. 다만 호출자가 재조회 판정
        #   (`settle_unknown`)을 할 수 있도록 **해시를 실어** 보낸다. 그 값은 발신자의
        #   주장이 아니라 **서명기가 직접 잰 것**이다(M-11) — 판정의 근거는 잰 값이어야 한다.
        raise AgoraError(e.code, e.message,
                         {**(e.detail or {}), "event_hash": signed["hash"]},
                         retryable=e.retryable_override) from None   # 인스턴스 판단을 잃지 않는다(R5-②)
    row = None
    if ledger is not None:
        row = record_sent(ledger=ledger, event=event, event_hash=signed["hash"],
                          node_id=result.get("node_id"))
    return {"message_id": event["message_id"], "hash": signed["hash"],
            "scrub": report, "approval": approval, "ledger_row": row, **result}


# ── 봉투(설계 §3-2 · FR-2) ──────────────────────────────────────────────────
# ★봉투는 **예의**가 아니라 **자격**이다. 재현 정보 없이 올린 질문은 답하는 쪽의 시간을
#   먼저 쓴다 — 그래서 결손은 「형식 미비」가 아니라 게이트 거부(3)다.

def envelope_template() -> dict[str, Any]:
    """빈 봉투 서식 — 사람이 채워 넣을 자리를 보여 준다.

    ★이 값이 **그대로 검사를 통과**해야 한다(S3-3 AC ③). 서식이 자기 검사를 못 지나면
      「서식대로 썼는데 거부당하는」 일이 생기고, 그러면 아무도 서식을 안 믿는다.
      그래서 서식은 문서에 따로 적지 않고 **여기 한 곳**에 두고 문서가 이것을 인용한다.
    """
    return {
        "env": {"os": "운영체제와 판본", "app": "프로그램과 판본", "version": "0.0.0"},
        "symptom": "무엇이 어떻게 잘못되는지 한 줄",
        "repro_steps": ["첫 단계", "둘째 단계", "그때 일어나는 일"],
        "log_excerpt": "관련 로그 몇 줄(개인 정보와 경로는 빼고)",
        "tried": ["이미 해 본 것"],
        "questions": ["묻고 싶은 것"],
    }


def envelope_check(envelope: Any) -> dict[str, Any]:
    """`agora.envelope_check` 코어(§4) — {ok, errors[], scrub_report}.

    ★**던지지 않고 돌려준다.** 이 도구는 「보내도 되나」를 묻는 자리이지 보내는 자리가 아니다.
      사람이 고칠 수 있게 사유마다 **빠진 칸 이름**을 함께 준다(AC ①).
    """
    errs: list[dict[str, Any]] = []
    try:
        schema._check_envelope(envelope if type(envelope) is dict else {})
    except AgoraError as e:
        errs.append({"code": e.code, "message": e.message, "detail": e.detail})
    report: dict[str, Any] | None = None
    try:
        report = scrub.check({"payload": {"envelope": envelope}})
        if report["blocked"]:
            errs.append({"code": errors.GATE_REJECT, "message": "스크럽 게이트 차단",
                         "detail": {"rules": [f["rule"] for f in report["findings"]],
                                    "where": [f["where"] for f in report["findings"]]}})
    except AgoraError as e:
        errs.append({"code": e.code, "message": e.message, "detail": e.detail})
    return {"ok": not errs, "errors": errs, "scrub_report": report}


def declare_scrub(event: dict[str, Any], config_dir: str | None = None) -> dict[str, Any]:
    """이벤트의 `scrub` 칸을 **정직하게** 채운다(§2-1).

    ★이 칸은 서명 대상 안에 있으므로 **이벤트를 만들 때** 채워야 한다 — 나중에 덮어쓰면
      해시가 바뀌어 사슬(`prev`)이 끊긴다. 그래서 「보내기 직전에 고쳐 주는」 편의를 두지 않는다.

    ★싣는 값은 **묶음(bundle)** 이다. 한 겹만 실으면 수신 측이 나머지 겹을 대조할 수 없다.
      대신 대가가 있다: 묶음이 바뀌면 수신 측은 **세 겹(denylist·allowlist·도메인) 전부**를
      갖고 있어야 같은 값을 다시 만들 수 있다 — 규칙 배포 경로가 이 선택의 전제다.
    """
    report = scrub.check(event, names_path=scrub.names_path(config_dir))
    event["scrub"] = {"rules": report["bundle"], "blocked": report["blocked"],
                      "redacted": report["redacted"]}
    return event


# ── 저장 성공 불명(code 8 · S4-3) ───────────────────────────────────────────
# ★「보냈는데 응답이 안 왔다」는 **성공도 실패도 아니다.** 둘 중 하나로 단정하는 순간
#   ⑴성공으로 보면 안 올라간 글을 올라갔다고 믿고(대화가 조용히 끊긴다)
#   ⑵실패로 보면 이미 올라간 글을 다시 올린다(같은 말이 두 번 나간다).
#   그래서 **재조회로 판정할 때까지 아무 말도 하지 않는다.**

COMMITTED = "committed"
ABSENT = "absent"
REJECTED = "rejected"


def audit_verdict(*, store: Any, thread_id: str,
                  message_id: str) -> dict[str, Any]:
    """재조회해서 실제로 **반영됐는지** 판정한다.

    ★판정 근거는 **운반층**이다 — 우리 기록(원장)으로 판정하면 「보냈다고 적었으니 갔을
      것」이라는 순환이 된다.
    ★★그러나 **「적혀 있다」는 「반영됐다」가 아니다**(codex 2R CRITICAL · 2026-09-09).
      릴레이 원장은 append-only 라 격리된 글도 그대로 남는다. 그래서 본문에 `message_id`
      가 보인다는 것만으로 `committed` 를 내면, 경합에서 진 글(`lost_race`)이 응답 유실
      뒤에 **성공으로 둔갑한다** — F-1 이 막으려던 바로 그 형태가 다른 문으로 돌아온다.
      재현: POST 적재 → `valid:false` → 응답 유실(code 8) → 재조회 → rc 0.
    ⇒ **대조 전용 읽기**(`audit_events`)로 릴레이의 파생 판정까지 읽고, `valid:false` 면
      `REJECTED` + 사유를 돌려준다. 부르는 쪽이 그 사유로 재시도할지 멈출지 가른다.
    ⚠`audit_events` 가 없는 운반층(GitHub·목)에는 **릴레이 판정이라는 개념 자체가 없다** —
      그때만 예전처럼 존재로 판정한다. 있는데 못 읽으면 그 오류는 그대로 올라간다
      (읽기 실패를 「없음」으로 접지 않는다 — fail-closed).
    ★★돌려주는 것에 **분류(`reducer`)를 함께 싣는다**(master 승인 2026-09-09). 사유만 싣고
      분류를 「stale」로 못박아 두면 **판정은 맞는데 사람이 읽는 근거 줄이 틀린다** — 릴레이가
      「격리했다」고 답한 것을 우리가 「밀렸다」로 옮겨 적게 된다. 재시도 여부는 `reason` 이 지므로
      결과는 옳지만, 근거가 틀린 보고는 사람 감사를 무의미하게 만든다.
      분류 어휘는 실물 POST verdict 와 **같은 것**을 쓴다(`relay/src/index.ts`):
      accepted · quarantined · stale · unknown. 어휘가 갈리면 같은 사건이 경로마다 다른 이름을 얻는다.
    """
    if hasattr(store, "audit_events"):
        for row in store.audit_events(thread_id=thread_id):
            if message_id not in (row.get("body") or ""):
                continue
            if row.get("valid") is True:
                return {"verdict": COMMITTED, "reason": None, "reducer": "accepted"}
            if row.get("valid") is False:
                return {"verdict": REJECTED, "reason": row.get("reason"),
                        "reducer": _reducer_said(row)}
            # ★★**판정이 없으면 성공이 아니다**(codex 3R CRITICAL · 2026-09-09). 첫 판은
            #   `valid is False` 만 거부로 보고 **나머지를 전부 committed 로 접었다** — 그래서
            #   `valid` 칸이 빠졌거나 null 인 응답이 조용히 성공이 됐다. 그것은 「반영됐다」가
            #   아니라 **「상대가 말하지 않았다」**이고, 두 사건을 한 칸에 뭉치면 이 티켓이
            #   고치려던 병이 그 자리에서 되살아난다.
            # ★실물 릴레이는 이 칸을 **언제나 불린으로** 준다(relay/src/index.ts 의 이벤트 목록
            #   `valid: acceptedIds.has(id)`) — 그러므로 부재·null 은 계약 위반이거나 다른 상대다.
            #   어느 쪽이든 **판정 없이 성공으로 접을 근거가 없다.**
            raise AgoraError(errors.STORE,
                             "릴레이가 이 글의 반영 여부를 말하지 않았다 — 판정 없이 성공으로 접지 않는다",
                             {"reason": "relay_verdict_missing", "thread_id": thread_id,
                              "message_id": message_id, "node_id": row.get("node_id"),
                              "how": "릴레이 이벤트 목록이 valid 칸을 주는지 확인하라"})
        return {"verdict": ABSENT, "reason": None, "reducer": None}
    rows = store.fetch(thread_id=thread_id)["items"]
    for row in rows:
        if message_id in (row.get("body") or ""):
            return {"verdict": COMMITTED, "reason": None, "reducer": None}
    return {"verdict": ABSENT, "reason": None, "reducer": None}


def _reducer_said(row: dict[str, Any]) -> str:
    """대조 행의 분류 — 실물 POST verdict 와 **같은 어휘**로 옮긴다(계약 §3-5).

    ★두 사건을 가른다: `quarantined` 는 절차에서 걸린 것(자리를 바꿔도 그대로) ·
      `stale` 은 경합에서 밀린 것(자리를 다시 잡으면 유효해진다). 한 칸에 뭉치면 처방이 갈린다.
    ★둘 다 아닌데 무효면 `unknown` 이다 — 지어내지 않는다(실물도 그 자리에 unknown 을 쓴다).
    """
    if row.get("quarantined"):
        return "quarantined"
    if row.get("stale"):
        return "stale"
    return "unknown"


def record_sent(*, ledger: Any, event: dict[str, Any], event_hash: str,
                node_id: str | None) -> dict[str, Any] | None:
    """원장에 발신 행을 남긴다 — **같은 message_id 는 한 번만**.

    ★재조회로 「저장됨」이 확정되면 같은 이벤트를 다시 기록하려는 흐름이 생긴다.
      원장은 append-only 라 지울 수 없으므로, **쓰기 전에** 중복을 막아야 한다.
    """
    if ledger.has(event["message_id"]):
        return None
    return ledger.append(direction="sent", message_id=event["message_id"],
                         event_hash=event_hash, stage="sent", node_id=node_id,
                         hash_of=ledger_mod.HASH_EVENT_CANONICAL)


def settle_unknown(*, store: Any, ledger: Any, event: dict[str, Any],
                   event_hash: str) -> dict[str, Any]:
    """code 8 을 만난 뒤의 마무리 — 재조회로 판정하고, 저장됐을 때만 원장에 남긴다."""
    audited = audit_verdict(store=store, thread_id=event["thread_id"],
                            message_id=event["message_id"])
    verdict, reason = audited["verdict"], audited["reason"]
    row = None
    if verdict == COMMITTED:
        row = record_sent(ledger=ledger, event=event, event_hash=event_hash,
                          node_id=None)
    # ★`REJECTED` 는 원장에 안 적는다. 「보냈다」고 적으면 그 줄은 **반영된 글과 구별되지
    #   않고**, 다음 사람이 원장을 근거로 「이미 했다」를 읽는다. 릴레이 원장에는 그 글이
    #   남아 있고(append-only) 그 사실은 `reason` 으로 올라간다 — 우리 줄은 안 만든다.
    return {"verdict": verdict, "reason": reason,
            "reducer": audited["reducer"], "ledger_row": row}
