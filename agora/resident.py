"""resident — 참가자 기계의 **상주 방문**(설계 AUTONOMY-DESIGN §2 F · 계약 확장 8 · 0.1.6).

무엇을 하나
-----------
이 컴퓨터의 일정(맥 = LaunchAgent · 윈도우 = 작업 스케줄러)이 기본 10분마다 `agora resident once` 를 부른다.
`once` 는 **LLM 없이** 판정한다: 열린 토론방마다 「지금 회차에 내가 아직 말하지 않았는가」를 본다.
그런 방이 하나라도 있으면 그때만 **이 사람의 에이전트를 한 번 깨운다**(헤드리스 · 5분 상한).
없으면 아무것도 깨우지 않고 끝난다 — 대부분의 판은 에이전트 호출 0 이다.

★방문해서 **무엇을 하는가는 여기 없다.** `skills/agora-delegate/visit.md` 한 파일에 있다.
  이 파일은 「깨울 때인가」만 정한다(깨우는 기계와 방문 정책을 가른다 — 정책이 바뀌어도 기계는 그대로다).

진실은 밖에 있다
----------------
「내가 이 회차에 말했나」는 **릴레이의 이벤트**를 우리 리듀서로 접어서 본다(로컬 표식이 아니다).
로컬에 표식을 두면 「보냈다고 적었는데 방에는 없는」 경우(경합에서 밀린 글)에 영영 다시 안 깨운다.
⚠단 **깨움 횟수에는 로컬 상한**을 둔다(같은 방·같은 회차 3번). 판정이 아니라 **비용 천장**이다 —
  에이전트가 할 말이 없어 말하지 않으면 릴레이 상태는 그대로이고, 상한이 없으면 10분마다 영원히 깨운다.

⚠릴레이의 `GET /rooms/:id` 는 발언자 **수**(정수)만 준다 — 회차별 명단이 아니다(relay/src/lib/store.ts).
  그래서 방마다 이벤트를 읽는다. 방이 많아지면 한 판의 읽기가 늘어난다(방 수에 비례 · 쓰기 0).

끄는 법
-------
    agora resident off         # 한 줄. 일정은 남고 판마다 아무것도 안 한다(플래그 파일 하나)
    agora resident on          # 다시 켠다
    agora resident uninstall   # 일정까지 지운다
"""

from __future__ import annotations

import datetime
import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Callable

from agora import errors
from agora.errors import AgoraError

# ── 설계값(전부 여기 한 곳) ──────────────────────────────────────────────────
DEFAULT_INTERVAL_MIN = 10
INTERVAL_MIN_RANGE = (1, 1440)         # 1분 ~ 하루 1회(하루 1회 방문 모드도 같은 손잡이다)
WAKE_TIMEOUT_SECONDS = 300             # 깨운 에이전트가 이만큼 넘기면 프로세스 그룹째 끝낸다
WAKES_PER_CYCLE = 1                    # ★한 판에 깨우는 횟수의 상한
ROOMS_PER_WAKE = 5                     # 한 번 깨울 때 넘기는 방의 상한(넘치는 방은 다음 판)
ATTEMPTS_PER_ROUND = 3                 # 같은 방·같은 회차로 깨우는 횟수의 상한(비용 천장)
AGENT_MAX_TURNS = 30
LOCK_STALE_SECONDS = WAKE_TIMEOUT_SECONDS + 600
LOG_MAX_BYTES = 256 * 1024
BROWSE_PAGES_MAX = 10

POSTING_STATES = ("r0", "r1", "r2", "r3")   # 발언을 받는 상태 — 끝났거나 만료된 방은 깨우지 않는다
# ★방문 **목적** 표. 깨움 글의 방 줄마다 목적 이름이 붙고, visit.md 에는 목적마다 절이 있다.
#   다음 판본(투표 · 하루 한 줄 주제 · 귀환 보고 · 하루 깨움 상한)은 **목적을 더하는 자리**로 들어온다:
#   판정 조건은 `plan` 에, 들러서 할 일은 visit.md 의 그 목적 절에. 이 판본의 목적은 하나다.
PURPOSES: dict[str, str] = {
    "speak": "이 회차에 너는 아직 말하지 않았다",
}
AGENT_NAME = "claude"
ACTIONS = ("once", "install", "uninstall", "status", "off", "on")

STATE_DIRNAME = "resident"
OFF_FLAG = "OFF"
LOCK_DIRNAME = ".lock"
SETTINGS_FILE = "settings.json"
LAST_FILE = "last.json"
ATTEMPTS_FILE = "attempts.json"
LOG_FILE = "resident.log"              # 설정 폴더 바로 아래
OUT_FILE = "resident.out"              # 일정이 붙잡는 표준출력

LABEL_DEFAULT = "kr.godmeyou.agora.resident"
TASK_DEFAULT = "agora-resident"
# ★시험 전용 손잡이 — 임시 라벨로 등록·해제를 왕복할 때만 쓴다(이 기계의 실제 라벨을 건드리지 않으려고).
LABEL_ENV = "AGORA_RESIDENT_LABEL"

RC_OK = 0
RC_WAKE_FAILED = 1
RC_NO_AGENT = errors.PRECONDITION      # 깨울 에이전트가 없다 = 전제 미비
RC_LOCKED = 3                          # 이미 한 판이 돌고 있다(의장 루프와 같은 값)

Runner = Callable[..., dict[str, Any]]


# ── 자리 ────────────────────────────────────────────────────────────────────
def _config_dir(directory: str | None) -> str:
    from agora.participant import config_dir
    return os.path.abspath(directory or config_dir())


def paths(directory: str | None = None) -> dict[str, str]:
    d = _config_dir(directory)
    state = os.path.join(d, STATE_DIRNAME)
    return {"config": d, "state": state,
            "off": os.path.join(state, OFF_FLAG),
            "lock": os.path.join(state, LOCK_DIRNAME),
            "settings": os.path.join(state, SETTINGS_FILE),
            "last": os.path.join(state, LAST_FILE),
            "attempts": os.path.join(state, ATTEMPTS_FILE),
            "log": os.path.join(d, LOG_FILE),
            "out": os.path.join(d, OUT_FILE)}


def label() -> str:
    return os.environ.get(LABEL_ENV) or LABEL_DEFAULT


def task_name() -> str:
    return os.environ.get(LABEL_ENV) or TASK_DEFAULT


def plist_path() -> str:
    """★집 폴더에서 만든다(`HOME`) — 시험은 임시 집으로 이 자리를 옮긴다."""
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", label() + ".plist")


def _package_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def visit_rules_path() -> str:
    return os.path.join(_package_root(), "skills", "agora-delegate", "visit.md")


# ── 작은 저장 ────────────────────────────────────────────────────────────────
def _load_json(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_json(path: str, doc: dict[str, Any]) -> None:
    """임시 파일에 다 쓰고 바꿔치기한다 — 쓰다 죽어도 반쪽 파일이 남지 않는다."""
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _rotate(path: str) -> None:
    try:
        if os.path.getsize(path) > LOG_MAX_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass


def _log(p: dict[str, str], row: dict[str, Any]) -> None:
    """한 판 = 한 줄. ★방 제목·본문·사람 이름은 싣지 않는다(방 id 앞 8자와 숫자만)."""
    try:
        os.makedirs(os.path.dirname(p["log"]), mode=0o700, exist_ok=True)
        with open(p["log"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass       # 로그를 못 써도 판은 계속한다 — 결과는 표준출력에도 나간다


# ── 잠금(mkdir) ─────────────────────────────────────────────────────────────
def _lock_acquire(path: str) -> bool:
    """★`mkdir` 은 있으면 실패하는 원자적 연산이라 경합에서 하나만 이긴다.

    묵은 잠금(판이 죽으며 남긴 것)은 **rename 으로** 회수한다. 지운 뒤 다시 만들면
    두 프로세스가 둘 다 「내가 회수했다」를 믿을 수 있다 — 이름을 옮기는 것은 하나만 이긴다.
    """
    try:
        os.mkdir(path)
        return True
    except FileExistsError:
        pass
    try:
        age = time.time() - os.stat(path).st_mtime
    except FileNotFoundError:
        return False
    if age < LOCK_STALE_SECONDS:
        return False
    grave = f"{path}.stale-{os.getpid()}-{int(time.time())}"
    try:
        os.rename(path, grave)
    except OSError:
        return False
    shutil.rmtree(grave, ignore_errors=True)
    try:
        os.mkdir(path)
        return True
    except FileExistsError:
        return False


def _lock_release(path: str) -> None:
    try:
        os.rmdir(path)
    except OSError:
        pass


# ── 판정(LLM 없음) ──────────────────────────────────────────────────────────
def spoke_in_round(reduced: dict[str, Any], me: str, round_no: int) -> bool:
    """이 방의 **받아들여진** 글 중에 내가 그 회차에 쓴 것이 있는가.

    ★격리된 글(회차가 틀렸거나 예산을 넘긴 글)은 세지 않는다 — 방이 받지 않은 말은 말하지 않은 것이다.
    """
    for row in reduced.get("events") or []:
        event = row.get("event") or {}
        if event.get("kind") != "post" or event.get("from") != me:
            continue
        if int((event.get("payload") or {}).get("round") or 0) == round_no:
            return True
    return False


def _open_rooms(ctx: Any) -> list[dict[str, Any]]:
    from agora import tools
    rooms: list[dict[str, Any]] = []
    cursor = None
    for _ in range(BROWSE_PAGES_MAX):
        page = tools.browse(ctx, cursor=cursor)
        rooms.extend(page.get("rooms") or [])
        cursor = page.get("next_cursor")
        if not cursor:
            break
    return rooms


def plan(ctx: Any, *, attempts: dict[str, int],
         reduce: Callable[[Any, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """깨울 방을 고른다. **이유와 함께** 답한다(이유 없는 판정은 감사할 수 없다)."""
    from agora import tools
    reduce = reduce or tools._reduce
    me = ctx.participant_id
    due: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    # ★지금 발언을 받는 (방, 회차) 전부 — 깨우든 건너뛰든. 시도 기록은 **이 집합으로** 줄인다.
    #   「이번 판에 깨운 방」으로 줄이면 상한에 걸려 건너뛴 방의 기록이 지워지고,
    #   다음 판에 상한이 풀려 다시 깨운다(세 번 → 한 판 쉬고 → 또 세 번 · 시험이 잡은 자리).
    live: set[str] = set()
    rooms = _open_rooms(ctx)
    for row in rooms:
        room_id = row["room_id"]
        short = room_id[:8]
        reduced = reduce(ctx, room_id)
        state, round_no = reduced.get("state"), reduced.get("round")
        # ★문은 **여기 하나**다. 로비 행의 상태로 한 번 더 거르면 두 겹이 서로를 가려,
        #   한 겹이 사라져도 시험이 초록이다(겹 방어는 뮤턴트를 숨긴다). 끝난 방·만료된 방·
        #   회차가 없는 갈래(problem 의 open) 전부 이 한 줄에서 빠진다.
        if state not in POSTING_STATES or type(round_no) is not int:
            skipped.append({"room": short, "why": f"토론 회차가 아닌 상태({state}) — 들르지 않는다"})
            continue
        key = f"{room_id}@r{round_no}"
        live.add(key)
        if spoke_in_round(reduced, me, round_no):
            skipped.append({"room": short, "round": round_no, "why": "이 회차에 이미 말했다"})
            continue
        tried = int(attempts.get(key, 0))
        if tried >= ATTEMPTS_PER_ROUND:
            skipped.append({"room": short, "round": round_no,
                            "why": f"이 회차로 이미 {tried}번 깨웠다(상한) — 회차가 바뀌면 다시 본다"})
            continue
        due.append({"room_id": room_id, "round": round_no, "key": key, "attempt": tried + 1,
                    "purpose": "speak"})
    return {"scanned": len(rooms), "due": due, "skipped": skipped, "live": sorted(live)}


# ── 깨우기 ──────────────────────────────────────────────────────────────────
def find_agent(p: dict[str, str], which: Callable[[str], str | None] | None = None) -> str | None:
    """설치 때 적어 둔 경로가 살아 있으면 그것, 아니면 PATH 에서 찾는다.

    ★일정은 사람의 셸 PATH 를 물려받지 않는다(맥 launchd 는 최소 PATH) — 그래서 설치 때 경로를 적어 둔다.
    """
    recorded = _load_json(p["settings"]).get("agent_path")
    if isinstance(recorded, str) and recorded and os.path.exists(recorded):
        return recorded
    return (which or shutil.which)(AGENT_NAME)


def shell_command(p: dict[str, str]) -> list[str]:
    """에이전트에게 쥐여 줄 **단 하나의 손** — 초대문 4단계가 만든 실행 껍데기.

    껍데기가 없으면(개발 트리) 이 꾸러미의 `bin/agora` 를 이 파이썬으로 부른다.
    """
    name = "agora.cmd" if os.name == "nt" else "agora"
    shell = os.path.join(p["config"], "bin", name)
    if os.path.exists(shell):
        return [shell]
    return [sys.executable, os.path.join(_package_root(), "bin", "agora")]


def build_prompt(*, due: list[dict[str, Any]], shell: list[str], rules_text: str,
                 rules_path: str) -> str:
    """깨움 글. ★방 제목은 싣지 않는다 — 제목은 남이 쓴 글이고, 깨움 글은 지시 자리다."""
    command = " ".join(shell)
    lines = ["너는 아고라 광장의 참가 대리인이다. 사람은 지금 옆에 없다 — 이 컴퓨터의 일정이 너를 깨웠다.",
             "아래 「방문 규칙」을 그대로 따르라.",
             f"규칙에 적힌 `agora` 는 이 명령이다. 줄이거나 바꾸지 말고 **그대로** 쳐라"
             f"(다른 모양의 명령은 거절되도록 띄웠다): {command}",
             "",
             "이번에 들를 방 — 각 방 한 번씩 · 목적은 줄마다 적었다(규칙의 같은 이름 절을 따른다):"]
    for item in due:
        purpose = item.get("purpose", "speak")
        lines.append(f"- 방 {item['room_id']} · 회차 {item['round']} · 목적 {purpose}"
                     f" — {PURPOSES.get(purpose, '?')}")
    lines += ["", f"── 방문 규칙({rules_path}) ──", rules_text.rstrip(), "── 규칙 끝 ──"]
    return "\n".join(lines)


def agent_argv(agent_path: str, prompt: str, shell: list[str]) -> list[str]:
    """헤드리스 1회 호출(`claude --help` 2.1.268 실측으로 고른 플래그).

    · `--tools Bash` = 내장 도구를 셸 하나로 좁힌다(파일 읽기·편집·웹 없음).
    · `--allowedTools "Bash(<껍데기> *)"` = 그 셸로도 **껍데기로 시작하는 명령만** 미리 허락한다.
    · `--permission-mode dontAsk` = 미리 허락하지 않은 것은 묻지 않고 거절한다(옆에 사람이 없다).
    · `--max-turns` 는 `--help` 에 없는 숨은 옵션이다 — 파서는 받는다(실측). 끝을 지키는 진짜 상한은 우리 시간 상한이다.
    """
    command = " ".join(shell)
    return [agent_path, "-p", prompt,
            "--tools", "Bash",
            "--allowedTools", f"Bash({command} *)",
            "--permission-mode", "dontAsk",
            "--max-turns", str(AGENT_MAX_TURNS),
            "--no-session-persistence",
            "--output-format", "text"]


def run_agent(argv: list[str], *, cwd: str, timeout: int, env: dict[str, str]) -> dict[str, Any]:
    """깨운다. 시간을 넘기면 **프로세스 그룹째** 끝낸다(래퍼만 죽이면 일하는 자식이 산다)."""
    started = time.monotonic()
    kwargs: dict[str, Any] = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL,
                              "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, **kwargs)
    except OSError as e:
        return {"rc": "spawn_failed", "seconds": 0.0, "error": type(e).__name__}
    try:
        out, _err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        return {"rc": "timeout", "seconds": round(time.monotonic() - started, 1)}
    return {"rc": proc.returncode, "seconds": round(time.monotonic() - started, 1),
            "output_chars": len(out or "")}


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
    try:
        proc.communicate(timeout=5)
    except (subprocess.TimeoutExpired, ValueError):
        pass


def _agent_env(p: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env["AGORA_CONFIG_DIR"] = p["config"]
    key = os.path.join(p["config"], "id_ed25519")
    if not env.get("AGORA_SIGNING_KEY") and os.path.exists(key):
        env["AGORA_SIGNING_KEY"] = key
    return env


def _verdict(rc: int, meaning: str) -> dict[str, Any]:
    return {"종료코드": rc, "뜻": meaning}


def once(*, directory: str | None = None, dry_run: bool = False, print_agenda: bool = False,
         ctx_factory: Callable[[str], Any] | None = None, runner: Runner | None = None,
         which: Callable[[str], str | None] | None = None,
         rooms_per_wake: int = ROOMS_PER_WAKE, wakes_per_cycle: int = WAKES_PER_CYCLE) -> dict[str, Any]:
    """한 판. 판정 → (필요할 때만) 깨움 → 한 줄 기록."""
    from agora import tools
    p = paths(directory)
    os.makedirs(p["state"], mode=0o700, exist_ok=True)
    _rotate(p["log"])
    _rotate(p["out"])
    at = _now().isoformat().replace("+00:00", "Z")
    row: dict[str, Any] = {"at": at, "dry_run": dry_run}

    if os.path.exists(p["off"]):
        result = {"판정": _verdict(RC_OK, "꺼져 있다 — 아무것도 보지도 깨우지도 않았다"),
                  "상주": "꺼짐", "다시_켜기": "agora resident on"}
        _log(p, {**row, "rc": RC_OK, "why": "off"})
        return result

    if not _lock_acquire(p["lock"]):
        _log(p, {**row, "rc": RC_LOCKED, "why": "locked"})
        return {"판정": _verdict(RC_LOCKED, "이미 한 판이 돌고 있다 — 이번 판은 물러난다"),
                "잠금": p["lock"]}
    try:
        try:
            ctx = (ctx_factory or tools.context_from_config)(p["config"])
            attempts = {k: v for k, v in _load_json(p["attempts"]).items() if type(v) is int}
            found = plan(ctx, attempts=attempts)
        except AgoraError as e:
            _log(p, {**row, "rc": RC_WAKE_FAILED, "why": f"code {e.code}"})
            _write_json(p["last"], {"at": at, "rc": RC_WAKE_FAILED, "woke": 0})
            return {"판정": _verdict(RC_WAKE_FAILED, f"광장을 읽지 못했다 — code {e.code} {e.message}"),
                    "오류": json.loads(e.to_json())}
        due = found["due"]
        agenda = [{"room_id": d["room_id"], "round": d["round"], "attempt": d["attempt"],
                   "purpose": d["purpose"]} for d in due]
        base = {"본_방": found["scanned"], "안건": agenda, "건너뛴_방": found["skipped"]}
        row.update({"scanned": found["scanned"], "due": len(due),
                    "rooms": [d["room_id"][:8] for d in due]})
        rules = visit_rules_path()
        agent = find_agent(p, which)

        if not due:
            result = {**base, "판정": _verdict(RC_OK, "이번 판에 들를 방이 없다 — 깨우지 않았다"), "깨움": 0}
        elif dry_run:
            result = {**base, "판정": _verdict(RC_OK, "드라이런 — 깨울 방만 적었다(아무것도 안 바꿨다)"),
                      "깨움": 0, "깨울_에이전트": agent or "없음"}
        elif print_agenda:
            result = {**base, "판정": _verdict(RC_OK, "안건만 적었다 — 깨우지 않았다"), "깨움": 0}
        elif agent is None:
            result = {**base, "판정": _verdict(RC_NO_AGENT, "깨울 에이전트가 없다 — 안건만 적었다"),
                      "깨움": 0,
                      "할일": "이 컴퓨터에 claude 가 없다. 들를 방은 위 안건이다 — 사람이 에이전트에게 직접 시키거나"
                              " `agora resident once --print-agenda` 로 다시 볼 수 있다(codex·gemini 깨우기는 아직 없다)."}
        elif not os.path.exists(rules):
            result = {**base, "판정": _verdict(errors.PRECONDITION, "방문 규칙 파일이 없다 — 규칙 없이 깨우지 않는다"),
                      "깨움": 0, "규칙_자리": rules}
        else:
            with open(rules, encoding="utf-8") as fh:
                rules_text = fh.read()
            shell = shell_command(p)
            batches = [due[i:i + rooms_per_wake] for i in range(0, len(due), rooms_per_wake)]
            woke = 0
            outcomes: list[dict[str, Any]] = []
            for batch in batches[:wakes_per_cycle]:
                # ★깨우기 **전에** 센다 — 깨운 판이 도중에 죽어도 그 시도는 상한에 들어간다.
                for item in batch:
                    attempts[item["key"]] = int(attempts.get(item["key"], 0)) + 1
                _write_json(p["attempts"], attempts)
                prompt = build_prompt(due=batch, shell=shell, rules_text=rules_text, rules_path=rules)
                outcome = (runner or run_agent)(agent_argv(agent, prompt, shell), cwd=p["state"],
                                                timeout=WAKE_TIMEOUT_SECONDS, env=_agent_env(p))
                woke += 1
                outcomes.append({"rooms": [b["room_id"][:8] for b in batch], **outcome})
            ok = all(o.get("rc") == 0 for o in outcomes)
            result = {**base, "깨움": woke, "결과": outcomes,
                      "판정": _verdict(RC_OK if ok else RC_WAKE_FAILED,
                                       "에이전트를 깨웠다" if ok else "에이전트를 깨웠으나 끝이 좋지 않았다(결과 칸)"),
                      "넘긴_방": sum(len(b) for b in batches[:wakes_per_cycle]),
                      "다음_판으로": sum(len(b) for b in batches[wakes_per_cycle:])}
            row["agent"] = [{"rc": o.get("rc"), "seconds": o.get("seconds")} for o in outcomes]

        rc = result["판정"]["종료코드"]
        row.update({"rc": rc, "woke": result.get("깨움", 0)})
        _log(p, row)
        if not dry_run:
            # 쓸데없이 쌓이지 않게 — **지금 발언을 받는 (방, 회차)** 가 아닌 기록만 버린다
            #   (닫힌 방 · 지나간 회차). 상한에 걸린 방의 기록은 남아야 상한이 선다.
            live = set(found["live"])
            kept = {k: v for k, v in attempts.items() if k in live}
            if kept != _load_json(p["attempts"]):
                _write_json(p["attempts"], kept)
            _write_json(p["last"], {"at": at, "rc": rc, "woke": result.get("깨움", 0), "due": len(due)})
        return result
    finally:
        _lock_release(p["lock"])


# ── 일정 등록 ────────────────────────────────────────────────────────────────
def _run(argv: list[str]) -> dict[str, Any]:
    try:
        kwargs: dict[str, Any] = {"capture_output": True, "text": True, "timeout": 30}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(argv, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"rc": None, "error": type(e).__name__}
    return {"rc": proc.returncode, "stderr": (proc.stderr or "").strip()[:200]}


def _uid() -> int:
    """★윈도우 파이썬에는 `os.getuid` 가 없다 — 맥 경로의 시험이 윈도우에서 임포트·실행돼도 죽지 않게."""
    getter = getattr(os, "getuid", None)
    return getter() if getter is not None else 0


def _check_interval(value: Any) -> int:
    low, high = INTERVAL_MIN_RANGE
    if type(value) is not int or not low <= value <= high:
        raise AgoraError(errors.ARGUMENT, f"--interval-min 은 {low}~{high} 사이 정수다",
                         {"got": value})
    return value


def plist_document(*, p: dict[str, str], interval_min: int, agent_path: str) -> bytes:
    """맥 LaunchAgent 한 벌. ★일정은 사람의 셸 환경을 물려받지 않는다 — PATH·집·설정 폴더를 적어 준다."""
    shell = shell_command(p)
    program = (["/bin/sh", shell[0]] if len(shell) == 1 else shell) + ["resident", "once", "--dir", p["config"]]
    path_dirs = [os.path.dirname(agent_path), os.path.dirname(sys.executable),
                 "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    seen: list[str] = []
    for item in path_dirs:
        if item and item not in seen:
            seen.append(item)
    doc = {"Label": label(),
           "ProgramArguments": program,
           "StartInterval": interval_min * 60,
           "RunAtLoad": False,
           "ProcessType": "Background",
           "StandardOutPath": p["out"],
           "StandardErrorPath": p["out"],
           "EnvironmentVariables": {"HOME": os.path.expanduser("~"),
                                    "AGORA_CONFIG_DIR": p["config"],
                                    "PATH": ":".join(seen)}}
    return plistlib.dumps(doc, sort_keys=True)


def schtasks_create_argv(*, p: dict[str, str], interval_min: int, pythonw: str) -> list[str]:
    """윈도우 작업 스케줄러 한 줄. ★`pythonw.exe` 로 부른다 — 콘솔 창이 아예 안 뜬다
    (PowerShell 을 거치지 않으므로 PowerShell 모듈 경로 문제도 생기지 않는다).
    ⚠윈도우 실기 미실측 — 정적 시험만 있다.
    """
    agora_bin = os.path.join(_package_root(), "bin", "agora")
    tr = f'"{pythonw}" "{agora_bin}" resident once --dir "{p["config"]}"'
    if len(tr) > 261:
        raise AgoraError(errors.PRECONDITION, "작업 스케줄러 명령 줄이 너무 길다(261자 상한)",
                         {"length": len(tr)})
    schedule = ["/SC", "DAILY"] if interval_min >= 1440 else ["/SC", "MINUTE", "/MO", str(interval_min)]
    return ["schtasks", "/Create", *schedule, "/TN", task_name(), "/TR", tr, "/F"]


def _pythonw() -> str | None:
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else None


def install(*, directory: str | None = None, interval_min: int = DEFAULT_INTERVAL_MIN,
            platform: str | None = None, runner: Callable[[list[str]], dict[str, Any]] | None = None,
            which: Callable[[str], str | None] | None = None,
            pythonw: str | None = None) -> dict[str, Any]:
    """일정을 놓는다. ★검사를 **먼저 전부** 한다 — 거부된 설치가 파일을 남기면 안 된다."""
    interval_min = _check_interval(interval_min)
    p = paths(directory)
    run = runner or _run
    plat = platform or sys.platform
    agent = find_agent(p, which)
    if agent is None:
        raise AgoraError(errors.PRECONDITION,
                         "깨울 에이전트(claude)가 이 컴퓨터에 없다 — 상주를 놓지 않는다",
                         {"대신": "agora resident once --print-agenda 로 들를 방만 볼 수 있다",
                          "지원": "claude 만 깨운다(codex·gemini 는 아직 없다)"})
    if not os.path.isdir(p["config"]):
        raise AgoraError(errors.PRECONDITION, "설정 폴더가 없다 — 참가 설치(초대문 1~8단계)를 먼저 한다",
                         {"config_dir": p["config"]})
    settings = {"agent_path": agent, "interval_min": interval_min, "platform": plat,
                "installed_at": _now().isoformat().replace("+00:00", "Z")}
    if plat == "darwin":
        target = plist_path()
        body = plist_document(p=p, interval_min=interval_min, agent_path=agent)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(body)
        os.replace(tmp, target)
        domain = f"gui/{_uid()}"
        run(["launchctl", "bootout", f"{domain}/{label()}"])          # 이미 있으면 내린다(없으면 실패가 정상)
        loaded = run(["launchctl", "bootstrap", domain, target])
        if loaded.get("rc") != 0:
            os.remove(target)
            raise AgoraError(errors.PRECONDITION, "일정 등록(launchctl bootstrap)이 실패했다 — 놓은 파일을 거뒀다",
                             {"launchctl": loaded})
        settings.update({"scheduler": "launchd", "label": label(), "plist": target})
    elif plat == "win32":
        exe = pythonw or _pythonw()
        if exe is None:
            raise AgoraError(errors.PRECONDITION, "pythonw.exe 를 찾지 못했다 — 창 없이 부를 수단이 없어 일정을 놓지 않는다",
                             {"python": sys.executable})
        made = run(schtasks_create_argv(p=p, interval_min=interval_min, pythonw=exe))
        if made.get("rc") != 0:
            raise AgoraError(errors.PRECONDITION, "작업 스케줄러 등록이 실패했다", {"schtasks": made})
        settings.update({"scheduler": "schtasks", "task": task_name(), "windows_measured": False})
    else:
        raise AgoraError(errors.PRECONDITION, "이 운영체제의 일정 등록은 아직 없다(맥·윈도우만)",
                         {"platform": plat,
                          "대신": f"cron 에 한 줄: */{interval_min} * * * * agora resident once"})
    _write_json(p["settings"], settings)
    if os.path.exists(p["off"]):
        os.remove(p["off"])
    return {"상주": "켜짐", "설정": settings,
            "끄기": "agora resident off", "지우기": "agora resident uninstall"}


def uninstall(*, directory: str | None = None, platform: str | None = None,
              runner: Callable[[list[str]], dict[str, Any]] | None = None) -> dict[str, Any]:
    """일정과 상주 상태를 거둔다. ★기록(`resident.log`)은 남긴다 — 무엇이 돌았는지는 지운 뒤에도 물을 수 있어야 한다."""
    p = paths(directory)
    run = runner or _run
    plat = platform or sys.platform
    removed: list[str] = []
    if plat == "darwin":
        run(["launchctl", "bootout", f"gui/{_uid()}/{label()}"])
        target = plist_path()
        if os.path.exists(target):
            os.remove(target)
            removed.append(target)
    elif plat == "win32":
        run(["schtasks", "/Delete", "/TN", task_name(), "/F"])
        removed.append(f"작업 {task_name()}")
    for key in ("settings", "off", "attempts", "last"):
        if os.path.exists(p[key]):
            os.remove(p[key])
            removed.append(p[key])
    return {"상주": "미설치", "거둔_것": removed, "남긴_것": p["log"]}


def set_off(*, directory: str | None = None, off: bool) -> dict[str, Any]:
    p = paths(directory)
    os.makedirs(p["state"], mode=0o700, exist_ok=True)
    if off:
        with open(p["off"], "w", encoding="utf-8") as fh:
            fh.write("이 파일이 있으면 상주는 판마다 아무것도 하지 않는다. 지우면(agora resident on) 다시 돈다.\n")
        return {"상주": "꺼짐", "다시_켜기": "agora resident on", "플래그": p["off"],
                # ★일정이 없는데 「꺼짐」만 적으면 사람은 일정이 있다고 읽는다.
                "일정_설치됨": bool(_load_json(p["settings"]))}
    if os.path.exists(p["off"]):
        os.remove(p["off"])
    return {"상주": summary_line(p["config"]), "끄기": "agora resident off"}


def status(*, directory: str | None = None, platform: str | None = None,
           runner: Callable[[list[str]], dict[str, Any]] | None = None,
           which: Callable[[str], str | None] | None = None) -> dict[str, Any]:
    """지금 무엇이 돌고 있나 — ★일정이 실제로 올라가 있는지를 **물어서** 적는다(파일만 보고 적지 않는다)."""
    p = paths(directory)
    run = runner or _run
    plat = platform or sys.platform
    settings = _load_json(p["settings"])
    agent = find_agent(p, which)
    scheduler: dict[str, Any] = {"plat": plat}
    if plat == "darwin":
        asked = run(["launchctl", "print", f"gui/{_uid()}/{label()}"])
        scheduler.update({"plist_exists": os.path.exists(plist_path()),
                          "loaded": (asked.get("rc") == 0) if asked.get("rc") is not None else "조회 불가"})
    elif plat == "win32":
        asked = run(["schtasks", "/Query", "/TN", task_name()])
        scheduler.update({"registered": (asked.get("rc") == 0) if asked.get("rc") is not None else "조회 불가",
                          "measured_on_windows": False})
    else:
        scheduler["note"] = "이 운영체제의 일정 등록은 아직 없다"
    return {"상주": summary_line(p["config"]),
            "설치됨": bool(settings), "설정": settings or None,
            "일정": scheduler,
            "깨울_에이전트": agent or "없음 — `agora resident once --print-agenda` 로 안건만 볼 수 있다",
            "마지막_판": _load_json(p["last"]) or None,
            "기록": p["log"],
            "끄기": "agora resident off"}


def summary_line(directory: str | None = None) -> str:
    """`whoami` 에 싣는 한 줄 — **무엇이 돌고 있는지는 볼 때마다 보인다.**"""
    p = paths(directory)
    settings = _load_json(p["settings"])
    if not settings:
        return "상주: 미설치 · 켜기 = agora resident install"
    if os.path.exists(p["off"]):
        return "상주: 꺼짐 · 다시 켜기 = agora resident on"
    interval = settings.get("interval_min", DEFAULT_INTERVAL_MIN)
    last = _load_json(p["last"]).get("at")
    seen = "아직 없음"
    if isinstance(last, str):
        try:
            moment = datetime.datetime.fromisoformat(last.replace("Z", "+00:00"))
            seen = moment.astimezone().strftime("%H:%M")
        except ValueError:
            seen = "읽지 못함"
    return f"상주: 켜짐({interval}분 · 마지막 방문 {seen}) · 끄기 = agora resident off"


# ── CLI 입구 ────────────────────────────────────────────────────────────────
ACTION_ARGS: dict[str, tuple[str, ...]] = {
    "once": ("dry_run", "print_agenda", "dir"),
    "install": ("interval_min", "dir"),
    "uninstall": ("dir",),
    "status": ("dir",),
    "off": ("dir",),
    "on": ("dir",),
}


def dispatch(action: str, kw: dict[str, Any]) -> dict[str, Any]:
    """★동작마다 받는 인자를 **따로** 잰다 — `status --interval-min 5` 가 조용히 무시되면
    사람은 자기가 준 줄이 먹힌 줄 안다."""
    if action not in ACTIONS:
        raise AgoraError(errors.ARGUMENT, "resident 의 동작은 once·install·uninstall·status·off·on 중 하나다",
                         {"got": action, "usage": "agora resident <once|install|uninstall|status|off|on>"})
    stray = sorted(k for k in kw if k not in ACTION_ARGS[action])
    if stray:
        raise AgoraError(errors.ARGUMENT, f"resident {action} 는 이 인자를 받지 않는다",
                         {"unknown": stray, "accepted": list(ACTION_ARGS[action])})
    directory = kw.get("dir")
    if action == "once":
        return once(directory=directory, dry_run=bool(kw.get("dry_run", False)),
                    print_agenda=bool(kw.get("print_agenda", False)))
    if action == "install":
        return install(directory=directory, interval_min=kw.get("interval_min", DEFAULT_INTERVAL_MIN))
    if action == "uninstall":
        return uninstall(directory=directory)
    if action == "status":
        return status(directory=directory)
    return set_off(directory=directory, off=(action == "off"))
