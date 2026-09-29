#!/usr/bin/env python3
"""우리 이름 글 탐지기 — 1단계(설계 docs/design/key-lifecycle/DESIGN-v3.md §6-2).

무엇을 하나
-----------
릴레이에 적재된 **우리 이름(`from == 우리 id`)의 글**을 모두 모아, 우리 상주 원장(`ledger.jsonl` 의
`dir=sent` 행)과 대조한다. 원장에 없는 우리 이름 글이 있으면 **사람에게 알린다.**

    python3 tools/detect_ours.py                       # 기본 = 우리 상주 폴더 · 본 릴레이 · 시험 릴레이
    python3 tools/detect_ours.py --json                # 기계용 보고
    python3 tools/detect_ours.py liveness --max-age-h 3   # 마지막 성공이 오래됐으면 경보

★읽기만 한다 — 공개 GET 만 부르고, 서버·원장·명부에 쓰지 않는다. 쓰는 것은 이 도구의 상태 파일
  (마지막 성공 시각) 하나뿐이다(`--state-dir`).
★**자동 조치가 없다**(설계 §6-1). 정상 글도 원장에 없을 수 있다 — 응답 유실 뒤 재조회 `REJECTED`
  (`core.py` 가 의도적으로 안 적는다) · 재조회까지 실패한 code 8 잔여 · 적재 뒤 프로세스 종료 ·
  같은 id 를 다른 설정 폴더에서 쓴 경우. 그래서 원장에 없는 글은 「도용」이 아니라
  **「원장 미기록 — 출처 미확정」** 이고, 판단은 사람이 상주 로그로 한다(§6-5).
★**1단계는 완전성을 보장하지 않는다(최선 노력).** `/home` 의 방 목록은 rooms **캐시**에서 오고
  상한(10)이 있다. 그래서 「못 본 것」을 「없다」로 세지 않게 — 못 본 사유는 전부 **불완전**으로 올린다
  (fail-closed). 완전한 대조는 2단계(원장 직조회 GET · 설계 §6-3)의 몫이다.

판정(종료 코드)
---------------
    0 = 일치 — 우리 이름 글이 전부 원장과 맞고, 불완전 사유 없음
    1 = 경보 — 원장 미기록 글 · 시험 릴레이에 우리 id/지문 등록 · 본 릴레이에서 우리 지문이 다른 이름에 붙음 등
    2 = 불완전 — 경보는 없지만 끝까지 보지 못했다(GET 실패 · 응답 모양 이상 · 방 상한 도달 · 원장 부재 …)
    (경보와 불완전이 함께 있으면 1 이고, 보고에 둘 다 싣는다.)

시험 릴레이의 상태(설계 §6-2 · r2 D2-8)
--------------------------------------
운영 기록 `ops/trial-relay-state.jsonl`(append 전용 · 마지막 줄이 현재 상태)로 정한다.
    running   = 공개 주소 켜짐 → 우리 id·지문 질의가 **404 「그런 참가자가 없다」여야 정상** · 200 이면 경보
    verifying = 검증 중(차단 행을 먼저 넣고 켠 상태) → running 과 같은 기준으로 잰다
    off       = 의도적 종료 → **탐지를 건너뛰었다고 표시**한다. ⚠GET 실패를 「꺼짐 성공」으로 읽지 않는다 —
                꺼짐은 운영 기록이 말한다. 기록과 `relay/wrangler.next.jsonc` 의 `workers_dev` 가 어긋나면 불완전.

보고에는 **본문을 인용하지 않는다**(릴레이·방·event_id·created_at·분류만 · 설계 §6-5).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agora.errors import AgoraError  # noqa: E402
from agora.event import event_hash, parse_post  # noqa: E402

DEFAULT_CONFIG_DIR = os.path.expanduser("~/axdev/agora-resident/.agora")
DEFAULT_TRIAL_URL = "https://agora-relay-next.oogisoogi.workers.dev"
DEFAULT_TRIAL_LOG = os.path.join(ROOT, "ops", "trial-relay-state.jsonl")
DEFAULT_TRIAL_CONFIG = os.path.join(ROOT, "relay", "wrangler.next.jsonc")
DEFAULT_STATE_DIR = os.path.expanduser("~/.local/state/agora-detect")
USER_AGENT = "agora-detect/1.0 (+https://agora.godmeyou.kr)"

HOME_ROOMS_MAX = 10            # 릴레이 `index.ts` HOME_ROOMS_MAX — 이 수에 닿으면 11번째 방부터는 안 보인다
EVENTS_PAGE = 200              # GET /rooms/:id/events 의 limit 상한
PAGES_MAX = 1000               # 한 방에서 넘길 쪽 수의 안전 상한(커서가 안 움직이는 서버를 끝없이 돌지 않게)
TRIAL_STATES = ("running", "verifying", "off")

Fetch = Callable[[str], "tuple[int | None, Any]"]


# ── HTTP(읽기 전용) ─────────────────────────────────────────────────────────
def http_get(url: str, timeout: float = 20.0) -> tuple[int | None, Any]:
    """GET 한 번. (상태, 본문) — 본문은 JSON 이면 객체, 아니면 문자열. 연결 실패는 (None, 사유)."""
    req = urllib.request.Request(url, method="GET",
                                 headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, "%s: %s" % (type(e).__name__, str(e)[:200])
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


# ── 입력 ────────────────────────────────────────────────────────────────────
def load_identity(config_dir: str) -> tuple[str, str, str]:
    """(우리 id, 우리 지문, 본 릴레이 주소) — 상주 폴더의 participant.json · config.json 에서."""
    with open(os.path.join(config_dir, "participant.json"), encoding="utf-8") as fh:
        p = json.load(fh)
    with open(os.path.join(config_dir, "config.json"), encoding="utf-8") as fh:
        c = json.load(fh)
    pid, fp = p.get("id"), p.get("key_fingerprint")
    url = ((c.get("relay") or {}).get("url") or "").rstrip("/")
    if not (isinstance(pid, str) and pid and isinstance(fp, str) and fp.startswith("SHA256:") and url):
        raise SystemExit("상주 폴더에서 id·지문·릴레이 주소를 읽지 못했다: " + config_dir)
    return pid, fp, url


def load_sent(ledger_path: str) -> tuple[dict[str, set], int, str | None]:
    """원장의 발신 행 → {message_id: {해시…}}, 해시 종류를 모르는 옛 행 수, 실패 사유(없으면 None).

    ★`hash_of` 가 `event_canonical` 인 행만 해시로 대조한다. 옛 행(칸 없음)은 message_id 만 맞춰 보고
      그 수를 따로 보고한다 — 못 잰 것을 잰 것으로 세지 않는다(`agora/ledger.py` HASH_UNKNOWN 과 같은 규율).
    """
    sent: dict[str, set] = {}
    unknown_kind = 0
    if not os.path.exists(ledger_path):
        return sent, 0, "ledger_missing"
    try:
        with open(ledger_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("dir") != "sent":
                    continue
                mid = row.get("message_id")
                if not isinstance(mid, str):
                    return sent, unknown_kind, "ledger_bad_row"
                hashes = sent.setdefault(mid, set())
                if row.get("hash_of") == "event_canonical" and isinstance(row.get("hash"), str):
                    hashes.add(row["hash"])
                else:
                    unknown_kind += 1
                    hashes.add(None)
    except (OSError, ValueError):
        return sent, unknown_kind, "ledger_unreadable"
    return sent, unknown_kind, None


def trial_state(log_path: str, config_path: str) -> tuple[str | None, str | None, dict]:
    """(운영 기록상 상태, 불완전 사유, 근거) — 기록의 마지막 줄 + 설정 파일의 workers_dev 를 맞춰 본다."""
    info: dict[str, Any] = {"log": log_path, "config": config_path}
    last = None
    try:
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    last = json.loads(line)
    except FileNotFoundError:
        return None, "trial_log_missing", info
    except (OSError, ValueError):
        return None, "trial_log_unreadable", info
    if not isinstance(last, dict) or last.get("state") not in TRIAL_STATES:
        return None, "trial_log_bad_state", info
    info["record"] = {k: last.get(k) for k in ("ts", "state", "note")}
    try:
        cfg = open(config_path, encoding="utf-8").read()
    except OSError:
        return last["state"], "trial_config_unreadable", info
    m = re.search(r'^\s*"workers_dev"\s*:\s*(true|false)\s*,?\s*$', cfg, re.M)
    info["workers_dev"] = m.group(1) if m else None
    want = "false" if last["state"] == "off" else "true"
    if info["workers_dev"] != want:
        return last["state"], "trial_log_config_mismatch", info
    return last["state"], None, info


# ── 본 릴레이 ───────────────────────────────────────────────────────────────
def scan_room(fetch: Fetch, base: str, room: str, pid: str, rep: dict) -> list[dict]:
    """한 방의 이벤트를 **next_cursor 가 빌 때까지** 넘겨, 우리 이름 글을 모은다."""
    ours: list[dict] = []
    cursor = "0"
    for _ in range(PAGES_MAX):
        status, body = fetch("%s/rooms/%s/events?limit=%d&cursor=%s" % (base, room, EVENTS_PAGE, quote(cursor)))
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("items"), list):
            rep["incomplete"].append({"reason": "events_get_failed", "relay": base, "room": room,
                                      "status": status})
            return ours
        for it in body["items"]:
            # ★`from`·`message_id` 는 응답 최상위 칸이 아니다 — 본문(`body`)을 파싱해야 나온다(index.ts roomEvents).
            try:
                ev = parse_post(it["body"])["event"]
                who, mid = ev["from"], ev["message_id"]
                h = event_hash(ev)
            except (AgoraError, KeyError, TypeError, ValueError):
                rep["incomplete"].append({"reason": "event_unparsable", "relay": base, "room": room,
                                          "event_id": it.get("event_id") if isinstance(it, dict) else None})
                continue
            if who == pid:
                ours.append({"room": room, "event_id": it.get("event_id"), "created_at": it.get("created_at"),
                             "message_id": mid, "hash": h})
        nxt = body.get("next_cursor")
        if nxt is None:
            return ours
        if not isinstance(nxt, str) or nxt == cursor:
            rep["incomplete"].append({"reason": "cursor_stuck", "relay": base, "room": room, "cursor": nxt})
            return ours
        cursor = nxt
    rep["incomplete"].append({"reason": "pages_max", "relay": base, "room": room})
    return ours


def scan_main(fetch: Fetch, base: str, pid: str, fp: str, sent: dict, rep: dict) -> None:
    rel = {"relay": base, "role": "main"}
    rep["relays"].append(rel)
    # (1) id 로 — 우리 행이 있고 지문이 우리 것이어야 한다
    status, home = fetch("%s/home?participant=%s" % (base, quote(pid, safe="")))
    if status != 200 or not isinstance(home, dict) or not isinstance(home.get("rooms"), list):
        rep["incomplete"].append({"reason": "home_get_failed", "relay": base, "query": "id", "status": status})
        return
    if home.get("participant") != pid or home.get("fingerprint") != fp:
        rep["alarms"].append({"kind": "main_id_fingerprint_mismatch", "relay": base,
                              "detail": "우리 id 의 등록 지문이 우리 지문과 다르다"})
    if any(isinstance(n, dict) and n.get("kind") in ("revoked", "retired") for n in home.get("notify") or []):
        rel["notice"] = [n.get("kind") for n in home.get("notify") if isinstance(n, dict)
                         and n.get("kind") in ("revoked", "retired")]
    # (2) 지문으로 — 우리 지문이 붙은 이름은 우리 id 하나여야 한다
    status, byfp = fetch("%s/home?participant=%s" % (base, quote(fp, safe="")))
    if status == 200 and isinstance(byfp, dict):
        if byfp.get("participant") != pid:
            rep["alarms"].append({"kind": "main_fingerprint_other_name", "relay": base,
                                  "detail": "우리 지문이 다른 이름으로 등록돼 있다"})
    else:
        rep["incomplete"].append({"reason": "home_get_failed", "relay": base, "query": "fingerprint",
                                  "status": status})
    rooms = [r.get("room_id") for r in home["rooms"] if isinstance(r, dict)]
    rel["rooms"] = len(rooms)
    if len(rooms) >= HOME_ROOMS_MAX:
        # 상한에 닿으면 11번째 방부터는 이 경로로 안 보인다 — 「없다」가 아니라 「못 봤다」.
        rep["incomplete"].append({"reason": "home_rooms_max", "relay": base, "rooms": len(rooms)})
    ours: list[dict] = []
    for room in rooms:
        if not isinstance(room, str) or not re.fullmatch(r"[0-9a-f]{32}", room):
            rep["incomplete"].append({"reason": "home_bad_room_id", "relay": base})
            continue
        ours.extend(scan_room(fetch, base, room, pid, rep))
    rel["ours"] = len(ours)
    for o in ours:
        known = sent.get(o["message_id"])
        if known is None:
            cls, why = "unrecorded", "원장 미기록 — 출처 미확정"
        elif o["hash"] in known:
            cls, why = "match", None
        elif None in known:
            cls, why = "match_unverified_hash", "옛 원장 행(해시 종류 모름) — message_id 만 일치"
        else:
            cls, why = "unrecorded", "원장과 내용(해시) 불일치 — 출처 미확정"
        rep["counts"][cls] = rep["counts"].get(cls, 0) + 1
        if cls == "unrecorded":
            rep["alarms"].append({"kind": "unrecorded_our_name", "relay": base, "room": o["room"],
                                  "event_id": o["event_id"], "created_at": o["created_at"],
                                  "message_id": o["message_id"], "detail": why})
    seen = {o["message_id"] for o in ours}
    # 원장에는 있는데 릴레이에서 못 본 글 — 도용 신호가 아니라 「이번 훑기가 다 못 봤다」는 신호다.
    missing = sorted(m for m in sent if m not in seen)
    if missing:
        rep["incomplete"].append({"reason": "ledger_sent_not_seen", "relay": base, "count": len(missing)})


# ── 시험 릴레이 ─────────────────────────────────────────────────────────────
def scan_trial(fetch: Fetch, base: str, pid: str, fp: str, state: str | None, why: str | None,
               info: dict, rep: dict) -> None:
    rel = {"relay": base, "role": "trial", "state": state, "state_basis": info}
    rep["relays"].append(rel)
    if why:
        rep["incomplete"].append({"reason": why, "relay": base})
    if state == "off":
        # ★꺼짐은 운영 기록이 말한다. 여기서 GET 을 부르지 않는다 — 실패를 성공으로 읽을 틈을 만들지 않는다.
        rel["skipped"] = "운영 기록상 의도적 종료 — 이번 탐지에서 건너뜀"
        return
    if state is None:
        return
    for label, who in (("id", pid), ("fingerprint", fp)):
        status, body = fetch("%s/home?participant=%s" % (base, quote(who, safe="")))
        if status == 404 and isinstance(body, dict) and body.get("code") == 7:
            continue                                    # 정상 — 그런 참가자가 없다
        if status == 200:
            rep["alarms"].append({"kind": "trial_registered_" + label, "relay": base,
                                  "detail": "시험 릴레이에 우리 %s 로 등록된 참가자가 있다(%s)"
                                            % ("id" if label == "id" else "지문",
                                               body.get("participant") if isinstance(body, dict) else "?")})
        else:
            rep["incomplete"].append({"reason": "trial_get_failed", "relay": base, "query": label,
                                      "status": status})


# ── 조립 ────────────────────────────────────────────────────────────────────
def run(*, fetch: Fetch, config_dir: str, main_url: str | None, trial_url: str | None,
        trial_log: str, trial_config: str) -> dict:
    pid, fp, cfg_url = load_identity(config_dir)
    rep: dict[str, Any] = {
        "tool": "detect_ours", "stage": "1단계 = 최선 노력(완전성 보장 없음 · 2단계 = 원장 직조회)",
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "participant": pid, "fingerprint": fp,
        "relays": [], "counts": {}, "alarms": [], "incomplete": [],
    }
    sent, unknown_kind, lerr = load_sent(os.path.join(config_dir, "ledger.jsonl"))
    rep["ledger_sent"] = len(sent)
    if unknown_kind:
        rep["ledger_hash_kind_unknown"] = unknown_kind
    if lerr:
        rep["incomplete"].append({"reason": lerr})
    scan_main(fetch, (main_url or cfg_url).rstrip("/"), pid, fp, sent, rep)
    if trial_url:
        state, why, info = trial_state(trial_log, trial_config)
        scan_trial(fetch, trial_url.rstrip("/"), pid, fp, state, why, info, rep)
    rep["verdict"] = "ALARM" if rep["alarms"] else ("INCOMPLETE" if rep["incomplete"] else "OK")
    return rep


def exit_code(rep: dict) -> int:
    return {"OK": 0, "ALARM": 1, "INCOMPLETE": 2}[rep["verdict"]]


def human(rep: dict) -> str:
    out = ["탐지기 %s · %s · %s" % (rep["verdict"], rep["checked_at"], rep["stage"]),
           "  참가자 %s · 원장 발신 %d건" % (rep["participant"], rep.get("ledger_sent", 0))]
    for r in rep["relays"]:
        if r["role"] == "main":
            out.append("  본 릴레이 %s · 방 %s · 우리 이름 글 %s" % (r["relay"], r.get("rooms", "?"), r.get("ours", "?")))
        else:
            out.append("  시험 릴레이 %s · 상태 %s%s" % (r["relay"], r.get("state"),
                                                    " · " + r["skipped"] if r.get("skipped") else ""))
    if rep["counts"]:
        out.append("  분류 " + " · ".join("%s=%d" % kv for kv in sorted(rep["counts"].items())))
    for a in rep["alarms"]:
        out.append("  ★경보 %s %s" % (a["kind"], {k: v for k, v in a.items() if k != "kind"}))
    for i in rep["incomplete"]:
        out.append("  ⚠불완전 %s" % i)
    return "\n".join(out)


def write_success(state_dir: str, rep: dict) -> None:
    """불완전 사유가 없을 때만 「마지막 성공」을 남긴다 — 반쪽 훑기를 성공으로 세지 않는다."""
    if rep["incomplete"]:
        return
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, "last_success.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"checked_at": rep["checked_at"], "verdict": rep["verdict"],
                   "epoch": int(time.time())}, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def liveness(state_dir: str, max_age_h: float, now: float | None = None) -> tuple[int, str]:
    path = os.path.join(state_dir, "last_success.json")
    try:
        with open(path, encoding="utf-8") as fh:
            epoch = int(json.load(fh)["epoch"])
    except (OSError, ValueError, KeyError, TypeError):
        return 1, "★경보 탐지기 생존: 마지막 성공 기록이 없다(%s)" % path
    age_h = ((now if now is not None else time.time()) - epoch) / 3600
    if age_h > max_age_h:
        return 1, "★경보 탐지기 생존: 마지막 성공이 %.1f시간 전(상한 %.1f)" % (age_h, max_age_h)
    return 0, "탐지기 생존 정상: 마지막 성공 %.1f시간 전" % age_h


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="우리 이름 글 ↔ 우리 원장 대조(1단계 · 읽기만)")
    ap.add_argument("mode", nargs="?", default="scan", choices=("scan", "liveness"))
    ap.add_argument("--config-dir", default=DEFAULT_CONFIG_DIR, help="상주 설정 폴더(participant.json·ledger.jsonl)")
    ap.add_argument("--relay", default=None, help="본 릴레이 주소(기본 = 상주 config.json 의 relay.url)")
    ap.add_argument("--trial-relay", default=DEFAULT_TRIAL_URL, help="시험 릴레이 주소('' = 안 봄)")
    ap.add_argument("--trial-log", default=DEFAULT_TRIAL_LOG)
    ap.add_argument("--trial-config", default=DEFAULT_TRIAL_CONFIG)
    ap.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    ap.add_argument("--max-age-h", type=float, default=3.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.mode == "liveness":
        rc, msg = liveness(args.state_dir, args.max_age_h)
        print(msg)
        return rc
    rep = run(fetch=http_get, config_dir=args.config_dir, main_url=args.relay,
              trial_url=args.trial_relay or None, trial_log=args.trial_log, trial_config=args.trial_config)
    write_success(args.state_dir, rep)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else human(rep))
    return exit_code(rep)


if __name__ == "__main__":
    sys.exit(main())
