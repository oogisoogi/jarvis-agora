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
# ★**깨움이 실패하면 그 방의 상한을 깎지 않는다**(2026-09-11 윈도우 실증 · master 요구 ⑧).
#   그 판은 방 탓이 아니라 **우리 탓**이었다 — 에이전트가 로그인 안 된 채 떠서 rc 1 로 죽었다.
#   그런데 옛 코드는 깨우기 **전에** 세고 되돌리지 않아, 세 판 만에 그 회차를 영영 건너뛰었다.
#   ⇒ 실패한 깨움은 되돌린다. 대신 **비용 천장을 다른 축으로 옮긴다**: 연속 실패에 상한을 둔다.
#   ⛔안 옮기면 「영원히 실패하며 10분마다 깨우는」 판이 생긴다(옛 상한이 막던 것이 그것이다).
WAKE_FAILURES_MAX = 3                  # 연속 깨움 실패가 이만큼이면 멈추고 사람을 부른다
AGENT_MAX_TURNS = 30
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
LOCK_FILE = "lock"
SETTINGS_FILE = "settings.json"
LAST_FILE = "last.json"
ATTEMPTS_FILE = "attempts.json"
FAILURES_FILE = "wake-failures.json"
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
    return {"config_dir": d, "state": state,
            "off": os.path.join(state, OFF_FLAG),
            "lock": os.path.join(state, LOCK_FILE),
            "settings": os.path.join(state, SETTINGS_FILE),
            "last": os.path.join(state, LAST_FILE),
            "failures": os.path.join(state, FAILURES_FILE),
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


# ── 잠금(파일 잠금 · 기다리지 않음) ──────────────────────────────────────────
def _lock_acquire(path: str) -> tuple[Any | None, str]:
    """(손잡이, 잠금 수단). 손잡이가 None 이면 **다른 판이 쥐고 있다.**

    ★mkdir 잠금을 쓰지 않는 이유(agy 1R HIGH · 0.1.6 안에서 바꿨다): 판이 죽으면 디렉터리가 남고,
      그 묵은 잠금을 나이로 회수하면 두 판이 서로의 새 잠금을 치우는 경쟁이 생긴다. 파일 잠금은
      **프로세스가 죽으면 OS 가 푼다** — 묵은 잠금이 없으니 회수할 일도 없다(창구 = `agora._lock`).
    ⚠잠글 수단이 없는 파이썬(fcntl·msvcrt 둘 다 없음)이면 잠그지 못한 채 돌고, 그 사실을 결과에 적는다.
    """
    from agora import _lock
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")
    try:
        got = _lock.try_acquire(fh)
    except OSError:
        fh.close()
        raise
    if got is False:
        fh.close()
        return None, _lock.backend()
    return fh, _lock.backend()


def _lock_release(fh: Any) -> None:
    from agora import _lock
    try:
        _lock.release(fh)
    except OSError:
        pass
    fh.close()


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


def _open_rooms(ctx: Any) -> tuple[list[dict[str, Any]], bool]:
    """(열린 방들, 끝까지 봤는가). ★끝까지 못 봤으면 그 사실을 들고 나간다 —
    못 본 방의 시도 기록을 「이제 없는 방」으로 지우면 그 방의 상한이 풀린다(agy 1R MED)."""
    from agora import tools
    rooms: list[dict[str, Any]] = []
    cursor = None
    for _ in range(BROWSE_PAGES_MAX):
        page = tools.browse(ctx, cursor=cursor)
        rooms.extend(page.get("rooms") or [])
        cursor = page.get("next_cursor")
        if not cursor:
            return rooms, True
    return rooms, False


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
    rooms, complete = _open_rooms(ctx)
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
    return {"scanned": len(rooms), "due": due, "skipped": skipped, "live": sorted(live),
            "complete": complete}


# ── 깨우기 ──────────────────────────────────────────────────────────────────
# ★PATH 에 없을 때 **마지막으로** 들여다볼 자리들(2026-09-11).
#   스케줄러는 사람의 셸 PATH 를 안 물려받는다 — 설치 때 적어 둔 경로가 없거나 죽었고 `which` 도
#   빈손이면, 설치기가 실제로 놓는 자리를 본다. ⛔**실재하는 것만** 돌려준다(없으면 없는 것이다).
#   · `~/.local/bin/claude` = 이 기계에서 **실측**(동봉 설치본 · 2026-09-11).
#   · 나머지는 **추정**이다 — 존재 검사가 막아 주므로 틀려도 값이 0 이고, 맞으면 깨움 하나를 살린다.
#     추정임을 여기 적어 둔다: 맞았다는 증거가 아직 없다.
AGENT_FALLBACKS = (os.path.join("~", ".local", "bin", "claude"),
                   os.path.join("~", ".local", "bin", "claude.exe"),
                   os.path.join("~", ".local", "bin", "claude.cmd"),
                   os.path.join("~", "AppData", "Roaming", "npm", "claude.cmd"),
                   os.path.join("~", "AppData", "Local", "npm", "claude.cmd"))


def agent_fallbacks(exists: Callable[[str], bool] | None = None) -> list[str]:
    """`which` 가 빈손일 때 볼 자리 — **실재하는 것만** 순서대로."""
    exists = exists or os.path.exists
    found = []
    for item in AGENT_FALLBACKS:
        path = os.path.expanduser(item)
        if exists(path):
            found.append(path)
    return found


def find_agent(p: dict[str, str], which: Callable[[str], str | None] | None = None,
               exists: Callable[[str], bool] | None = None) -> str | None:
    """설치 때 적어 둔 경로 → PATH → **설치기가 놓는 자리**(실재하는 것만).

    ★일정은 사람의 셸 PATH 를 물려받지 않는다(맥 launchd 는 최소 PATH) — 그래서 설치 때 경로를 적어 둔다.
    ★세 번째 걸음은 **`which` 가 실패했을 때만** 본다. 먼저 보면 PATH 에 있는 최신본을 두고
      옛 자리를 잡을 수 있다 — 찾는 순서가 곧 어느 것을 쓰느냐다.
    """
    recorded = _load_json(p["settings"]).get("agent_path")
    if isinstance(recorded, str) and recorded and (exists or os.path.exists)(recorded):
        return recorded
    found = (which or shutil.which)(AGENT_NAME)
    if found:
        return found
    candidates = agent_fallbacks(exists)
    return candidates[0] if candidates else None


def shell_command(p: dict[str, str]) -> list[str]:
    """에이전트에게 쥐여 줄 **단 하나의 손** — 초대문 4단계가 만든 실행 껍데기.

    껍데기가 없으면(개발 트리) 이 꾸러미의 `bin/agora` 를 이 파이썬으로 부른다.
    """
    name = "agora.cmd" if os.name == "nt" else "agora"
    shell = os.path.join(p["config_dir"], "bin", name)
    if os.path.exists(shell):
        return [shell]
    return [sys.executable, os.path.join(_package_root(), "bin", "agora")]


def command_text(shell: list[str]) -> str:
    """깨움 글과 허용 규칙에 **똑같이** 들어가는 명령 문자열.

    ★허용 규칙은 명령을 **글자 그대로** 대조한다(실측) — 글에 적힌 모양과 규칙의 모양이 한 글자라도
      다르면 허락해야 할 명령이 거절된다. 그래서 두 자리가 이 함수 하나에서 나온다.
    ★공백이 든 경로(윈도우 `C:\\Users\\홍 길동\\…`)는 따옴표로 감싼다 — 에이전트는 셸에서 따옴표를 붙여 칠 것이고,
      규칙이 따옴표 없는 모양이면 그 명령이 거절된다(agy 1R).
    """
    return " ".join(f'"{part}"' if " " in part else part for part in shell)


def build_prompt(*, due: list[dict[str, Any]], shell: list[str], rules_text: str,
                 rules_path: str) -> str:
    """깨움 글. ★방 제목은 싣지 않는다 — 제목은 남이 쓴 글이고, 깨움 글은 지시 자리다."""
    command = command_text(shell)
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
    command = command_text(shell)
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


# ★깨운 에이전트가 **어느 설정 폴더로 뜨는가**(계약 확장 8 보강 · 2026-09-11).
#   동봉 설치본은 Claude 설정을 **자기 전용 폴더**(아래 상수)에 둔다 — 로그인 표지도 거기 있다.
#   그런데 일정(스케줄러)이 깨운 프로세스는 **사람의 셸 환경을 물려받지 않으므로**
#   `CLAUDE_CONFIG_DIR` 이 없고, 헤드리스 claude 는 기본값 `~/.claude`(미로그인)로 뜬다.
#   ⇒ 깨우기는 제때 됐는데 **에이전트가 로그인 안 된 채** 죽는다(윈도우 실증 2026-09-11 20:08 · rc 1).
#   ⛔없는 폴더를 지어내지 않는다 — **실재할 때만** 넣는다(없으면 종전대로 claude 의 기본값에 맡긴다).
CLAUDE_CONFIG_ENV = "CLAUDE_CONFIG_DIR"
# ⚠아래 한 줄이 이 저장소에서 **그 폴더 이름을 적는 유일한 자리**다(공개 표현 규약 **줄 예외 1건**).
#   경로는 제품이 **실제로 읽어야 하는 자리**라 다른 말로 바꿔 적을 수 없다 — 바꿔 적으면 못 읽는다.
#   ⛔글자를 쪼개 검사를 피하지 않는다 — 그건 미탐과 구별되지 않는 억제다(게이트 자신이 경고하는 것).
#   ⇒ 표식을 달아 **보이게** 넘긴다. 게이트가 이 줄을 파일:줄번호로 찍는다.
#   ★그리고 이 줄은 **마지막 수단**이다: 그 앞에 「설치 때 본 값」이 있고(아래), 그쪽이 더 일반적이다
#     — 어느 실행기가 넣어 주든 받아 적기 때문이다. 이 상수는 그것마저 없을 때만 쓰인다.
VENDOR_CLAUDE_DIR = os.path.join("~", ".cys", "claude")  # public-terms: allow — 제품이 읽는 실제 경로


def claude_config_dir(env: dict[str, str] | None = None,
                      exists: Callable[[str], bool] | None = None,
                      recorded: str | None = None) -> tuple[str | None, str]:
    """깨울 때 쓸 Claude 설정 폴더와 **그것을 고른 이유** — 우선순위가 곧 계약이다.

    ⑴ 이미 환경에 있으면 **그것이 이긴다**(사람이 정한 값을 기계가 덮지 않는다).
    ⑵ 없으면 **설치 때 본 값**을 쓴다 — 사람이 상주를 켠 그 창에는 그 값이 있었다.
       ★이쪽이 더 일반적이다: 어느 실행기가 넣어 주든 **받아 적기** 때문에 이름을 몰라도 된다.
    ⑶ 그것도 없으면 알려진 설치본 폴더가 **실재할 때만** 쓴다(마지막 수단).
    ⑷ 전부 아니면 **아무것도 넣지 않는다** — claude 가 자기 기본값을 쓴다.
    ⛔없는 폴더를 지어내지 않는다 — 지어내면 「있는데 못 읽는다」와 「없다」가 같은 화면이 된다.
    ★반환에 이유를 함께 낸다: 깨움 결과 행에 적혀야 「어느 폴더로 깨웠나」를 나중에 물을 수 있다.
    """
    env = os.environ if env is None else env
    exists = exists or os.path.isdir
    already = env.get(CLAUDE_CONFIG_ENV)
    if already:
        return already, "환경에 이미 있었다"
    if recorded and exists(recorded):
        return recorded, "상주를 켤 때 그 창에 있던 값"
    vendor = os.path.expanduser(VENDOR_CLAUDE_DIR)
    if exists(vendor):
        return vendor, "알려진 설치본 폴더가 실재한다"
    return None, "정하지 않았다 — claude 기본값에 맡긴다"


def _claude_dir_note(p: dict[str, str] | None = None) -> dict[str, str]:
    """깨움 결과에 싣는 한 칸 — **어느 설정 폴더로 깨웠나**(요구 ①).

    ★없으면 나중에 「왜 로그인이 안 됐나」를 물을 수단이 없다. 2026-09-11 윈도우 사고가 정확히
      그 자리였다: 로그는 `rc 1` 만 말했고, **어느 폴더로 떴는지는 아무 데도 없었다.**
    """
    chosen, why = claude_config_dir(recorded=_recorded_claude_dir(p) if p else None)
    return {"자리": chosen or "정하지 않음", "왜": why}


def _agent_env(p: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env["AGORA_CONFIG_DIR"] = p["config_dir"]
    key = os.path.join(p["config_dir"], "id_ed25519")
    if not env.get("AGORA_SIGNING_KEY") and os.path.exists(key):
        env["AGORA_SIGNING_KEY"] = key
    chosen, _why = claude_config_dir(env, recorded=_recorded_claude_dir(p))
    if chosen:
        env[CLAUDE_CONFIG_ENV] = chosen
    return env


def _recorded_claude_dir(p: dict[str, str]) -> str | None:
    value = _load_json(p["settings"]).get("claude_config_dir")
    return value if isinstance(value, str) and value else None


def wake_failures(p: dict[str, str]) -> int:
    value = _load_json(p["failures"]).get("consecutive")
    return value if type(value) is int and value >= 0 else 0


def _set_wake_failures(p: dict[str, str], value: int, *, why: str | None = None) -> None:
    """연속 실패 계수 — **0 이면 파일을 지운다**(빈 상태와 「0회 실패」를 같은 모양으로 둔다)."""
    if value <= 0:
        if os.path.exists(p["failures"]):
            os.remove(p["failures"])
        return
    doc: dict[str, Any] = {"consecutive": value,
                           "at": _now().isoformat().replace("+00:00", "Z")}
    if why:
        doc["why"] = why
    _write_json(p["failures"], doc)


def _write_last(p: dict[str, str], *, started: str, rc: int, woke: int,
                due: int | None = None, why: str | None = None) -> None:
    """마지막 판의 기록 — ★**시작과 끝을 가른다**(2026-09-11 실증이 계기).

    ★왜: 전에는 칸이 `at` 하나였고 그 값은 **판을 시작한 시각**이었는데, `whoami` 는 그것을
      「마지막 **방문**」이라고 읽어 줬다. 윈도우에서 깨움이 rc 1 로 실패한 판에도 시각이 찍혀
      **「20:08 에 방문했다」로 보였다** — 실패를 성공처럼 읽게 만드는 화면이다.
    ⇒ 끝난 시각은 **끝났을 때만** 적고, 실패한 판은 **「마지막 시도 + 이유」**로 적는다.
      「언제 시도했나」와 「언제 다녀왔나」는 다른 사건이다.
    """
    doc: dict[str, Any] = {"started_at": started,
                           "finished_at": _now().isoformat().replace("+00:00", "Z"),
                           "rc": rc, "woke": woke, "ok": rc == RC_OK}
    if due is not None:
        doc["due"] = due
    if why:
        doc["why"] = why
    _write_json(p["last"], doc)


def _verdict(rc: int, meaning: str) -> dict[str, Any]:
    return {"종료코드": rc, "뜻": meaning}


def once(*, directory: str | None = None, dry_run: bool = False, print_agenda: bool = False,
         ctx_factory: Callable[[str], Any] | None = None, runner: Runner | None = None,
         which: Callable[[str], str | None] | None = None,
         exists: Callable[[str], bool] | None = None,
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

    held, lock_backend = _lock_acquire(p["lock"])
    if held is None:
        _log(p, {**row, "rc": RC_LOCKED, "why": "locked"})
        return {"판정": _verdict(RC_LOCKED, "이미 한 판이 돌고 있다 — 이번 판은 물러난다"),
                "잠금": p["lock"]}
    row["lock"] = lock_backend
    try:
        try:
            ctx = (ctx_factory or tools.context_from_config)(p["config_dir"])
            attempts = {k: v for k, v in _load_json(p["attempts"]).items() if type(v) is int}
            found = plan(ctx, attempts=attempts)
        except AgoraError as e:
            _log(p, {**row, "rc": RC_WAKE_FAILED, "why": f"code {e.code}"})
            _write_last(p, started=at, rc=RC_WAKE_FAILED, woke=0,
                        why=f"광장을 읽지 못했다(code {e.code})")
            return {"판정": _verdict(RC_WAKE_FAILED, f"광장을 읽지 못했다 — code {e.code} {e.message}"),
                    "오류": json.loads(e.to_json())}
        due = found["due"]
        agenda = [{"room_id": d["room_id"], "round": d["round"], "attempt": d["attempt"],
                   "purpose": d["purpose"]} for d in due]
        base = {"본_방": found["scanned"], "안건": agenda, "건너뛴_방": found["skipped"]}
        row.update({"scanned": found["scanned"], "due": len(due),
                    "rooms": [d["room_id"][:8] for d in due]})
        rules = visit_rules_path()
        agent = find_agent(p, which, exists)

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
        elif wake_failures(p) >= WAKE_FAILURES_MAX:
            # ★비용 천장이 여기로 옮겨 왔다(요구 ⑧). 방의 상한을 깎는 대신 **연속 실패**를 센다 —
            #   실패는 방 탓이 아니므로 방에서 깎으면 엉뚱한 회차를 건너뛴다.
            result = {**base,
                      "판정": _verdict(RC_WAKE_FAILED,
                                       f"깨움이 잇따라 {wake_failures(p)}번 실패해 멈췄다 — 사람이 봐야 한다"),
                      "깨움": 0, "에이전트_설정폴더": _claude_dir_note(p),
                      "할일": "에이전트가 뜨는지·로그인돼 있는지 본 뒤 `agora resident on` 으로 계수를 지운다"
                              " (안건과 방의 남은 기회는 그대로 있다)."}
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
            if not ok:
                # ★**되돌린다** — 깨움이 실패한 판은 그 방이 기회를 쓴 것이 아니다(요구 ⑧).
                #   실증: 에이전트가 로그인 안 된 채 떠서 rc 1 로 죽었는데 방의 상한만 깎였다.
                for spent in batches[:wakes_per_cycle]:
                    for item in spent:
                        attempts[item["key"]] = max(0, int(attempts.get(item["key"], 1)) - 1)
                _write_json(p["attempts"], attempts)
            _set_wake_failures(p, 0 if ok else wake_failures(p) + 1,
                               why=None if ok else "깨운 에이전트가 rc 0 으로 끝나지 않았다")
            result = {**base, "깨움": woke, "결과": outcomes,
                      "에이전트_설정폴더": _claude_dir_note(p),
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
            #   ★로비를 끝까지 못 본 판에는 줄이지 않는다 — 못 본 방은 「없는 방」이 아니다.
            live = set(found["live"])
            kept = ({k: v for k, v in attempts.items() if k in live} if found["complete"]
                    else dict(attempts))
            if kept != _load_json(p["attempts"]):
                _write_json(p["attempts"], kept)
            _write_last(p, started=at, rc=rc, woke=result.get("깨움", 0), due=len(due),
                        why=None if rc == RC_OK else result["판정"]["뜻"])
        if lock_backend == "none":
            result["잠금_수단"] = "없음 — 이 파이썬에서는 두 판이 겹쳐 돌 수 있다"
        return result
    finally:
        _lock_release(held)


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
    program = (["/bin/sh", shell[0]] if len(shell) == 1 else shell) + ["resident", "once", "--dir", p["config_dir"]]
    # ★패키지 관리자 자리(Homebrew)도 싣는다 — 깨운 에이전트가 셸에서 부르는 도구가 거기 있을 수 있다(agy 1R).
    path_dirs = [os.path.dirname(agent_path), os.path.dirname(sys.executable),
                 "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
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
                                    "AGORA_CONFIG_DIR": p["config_dir"],
                                    "PATH": ":".join(seen)}}
    return plistlib.dumps(doc, sort_keys=True)


def schtasks_xml_document(*, p: dict[str, str], interval_min: int, pythonw: str,
                          agora_bin: str | None = None) -> str:
    """작업 스케줄러 등록용 XML 한 벌 — ★**배터리 조건을 끈다.**

    왜 XML 인가(2026-09-11 · 요구 ⑤): `schtasks /Create` 에는 **배터리 조건을 끄는 스위치가 없다.**
    그 두 값은 작업 정의 **스키마의 `<Settings>`** 에만 있다
    (`DisallowStartIfOnBatteries` · `StopIfGoingOnBatteries` · 둘 다 기본값이 **true** 다).
    ⇒ 한 줄로는 못 하고 `/XML` 로 올려야 한다.
    ⚠**근거의 종류를 정직하게 적는다**: 이것은 **문서·스키마 근거**이고 **윈도우 실기 실측이 아니다**
      (이 기계는 맥이다). 실측은 윈도우 기계에서만 가능하다 — 그래서 설정에 `windows_measured: False`
      가 계속 남는다. 「돌려 봤다」로 올리지 않는다.
    ★왜 이 조건이 중요한가: 노트북이 배터리로 돌아가는 동안 작업이 **아예 안 뜨거나 도중에 멈춘다.**
      상주는 「사람이 없는 동안」이 존재 이유인데, 사람이 없는 시간은 대개 어댑터도 빠져 있다.
    """
    agora_bin = agora_bin or os.path.join(_package_root(), "bin", "agora")
    args = f'"{agora_bin}" resident once --dir "{p["config_dir"]}"'
    every = f"PT{interval_min}M" if interval_min < 1440 else "P1D"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <TimeTrigger>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition><Interval>{every}</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
    </TimeTrigger>
  </Triggers>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{pythonw}</Command>
      <Arguments>{args}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def schtasks_xml_argv(path: str) -> list[str]:
    return ["schtasks", "/Create", "/XML", path, "/TN", task_name(), "/F"]


# ⛔`schtasks /Create /TR "<한 줄>"` 경로는 **없앴다**(2026-09-11). 그 길로는 배터리 조건을 못 끈다.
#   그때 있던 261자 상한 검사도 같이 사라졌다 — **/XML 은 명령 줄로 넘기지 않으므로 그 상한이 없다.**
#   (검사를 「그냥 뺀」 것이 아니라 **그 제약이 있던 경로 자체를 뺀 것**이다.)


def _pythonw() -> str | None:
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else None


def install(*, directory: str | None = None, interval_min: int = DEFAULT_INTERVAL_MIN,
            platform: str | None = None, runner: Callable[[list[str]], dict[str, Any]] | None = None,
            which: Callable[[str], str | None] | None = None,
            pythonw: str | None = None, agora_bin: str | None = None,
            first_visit: bool = True,
            exists: Callable[[str], bool] | None = None) -> dict[str, Any]:
    """일정을 놓는다. ★검사를 **먼저 전부** 한다 — 거부된 설치가 파일을 남기면 안 된다.

    ★`first_visit` = 놓자마자 한 판을 돈다(요구 ④). 끄는 손잡이를 남긴 이유는 **시험** 때문이다 —
      등록·해제만 재는 케이스가 망을 타면 느려지고 흔들린다(흔들리는 그물은 아무것도 증명 못 한다).
    """
    interval_min = _check_interval(interval_min)
    p = paths(directory)
    run = runner or _run
    plat = platform or sys.platform
    agent = find_agent(p, which, exists)
    if agent is None:
        raise AgoraError(errors.PRECONDITION,
                         "깨울 에이전트(claude)가 이 컴퓨터에 없다 — 상주를 놓지 않는다",
                         {"대신": "agora resident once --print-agenda 로 들를 방만 볼 수 있다",
                          "지원": "claude 만 깨운다(codex·gemini 는 아직 없다)"})
    if not os.path.isdir(p["config_dir"]):
        raise AgoraError(errors.PRECONDITION, "설정 폴더가 없다 — 참가 설치(초대문 1~8단계)를 먼저 한다",
                         {"config_dir": p["config_dir"]})
    settings = {"agent_path": agent, "interval_min": interval_min, "platform": plat,
                "installed_at": _now().isoformat().replace("+00:00", "Z")}
    # ★**설치한 창에 있던 값을 받아 적는다.** 사람이 상주를 켜는 창은 대개 제대로 된 창이고,
    #   일정이 깨운 프로세스는 그 창의 환경을 **안 물려받는다** — 그 간극이 2026-09-11 사고였다.
    #   ⇒ 이름을 아는 대신 **그때 본 것**을 적어 둔다(어느 실행기든 통한다).
    seen_home = os.environ.get(CLAUDE_CONFIG_ENV)
    if seen_home:
        settings["claude_config_dir"] = seen_home
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
        # ★XML 로 올린다 — 배터리 조건을 끄는 길이 그것뿐이다(위 주석 참조).
        doc = schtasks_xml_document(p=p, interval_min=interval_min, pythonw=exe, agora_bin=agora_bin)
        xml_path = os.path.join(p["state"], "schtasks.xml")
        os.makedirs(p["state"], mode=0o700, exist_ok=True)
        with open(xml_path, "w", encoding="utf-16") as fh:      # 스키마가 UTF-16 을 요구한다
            fh.write(doc)
        try:
            made = run(schtasks_xml_argv(xml_path))
        finally:
            # ⛔등록에 쓴 파일을 남기지 않는다 — 남으면 「지금 도는 정의」와 헷갈린다(정본은 스케줄러다).
            if os.path.exists(xml_path):
                os.remove(xml_path)
        if made.get("rc") != 0:
            raise AgoraError(errors.PRECONDITION, "작업 스케줄러 등록이 실패했다", {"schtasks": made})
        settings.update({"scheduler": "schtasks", "task": task_name(), "windows_measured": False,
                         # ★「배터리에서도 돈다」는 **우리가 그렇게 적었다**는 뜻이지
                         #   **그렇게 돌더라**는 뜻이 아니다 — 실기 실측 전까지 이 구분을 유지한다.
                         "battery_conditions_off": "등록 XML 에 적음(윈도우 실기 미실측)"})
    else:
        raise AgoraError(errors.PRECONDITION, "이 운영체제의 일정 등록은 아직 없다(맥·윈도우만)",
                         {"platform": plat,
                          "대신": f"cron 에 한 줄: */{interval_min} * * * * agora resident once"})
    _write_json(p["settings"], settings)
    if os.path.exists(p["off"]):
        os.remove(p["off"])
    _set_wake_failures(p, 0)       # 새로 놓은 일정에 옛 실패를 물려주지 않는다
    out: dict[str, Any] = {"상주": "켜짐", "설정": settings,
                           "끄기": "agora resident off", "지우기": "agora resident uninstall"}
    # ★**설치 직후 한 판을 바로 돈다**(요구 ④ · 손 0). 전에는 첫 결과를 보려면 최대 10분을 기다려야
    #   했고, 그 사이에 설치 화면은 「켜짐」만 말했다 — **돌아가는지 아닌지 모르는 채** 사람이 떠났다.
    #   그래서 윈도우 사고도 다음 날에야 드러났다.
    # ⛔첫 판이 실패해도 **설치는 되돌리지 않는다**(일정은 이미 올바르게 놓였다). 결과만 그대로 싣는다.
    if first_visit:
        try:
            out["첫_방문"] = once(directory=directory)
        except AgoraError as e:
            out["첫_방문"] = {"판정": _verdict(e.code, f"첫 판이 실패했다 — {e.message}"),
                              "오류": json.loads(e.to_json())}
    return out


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
    # ★일정이 붙잡던 표준출력(`resident.out`)도 거둔다(agy 1R LOW) — 판 결과가 쌓인 파일이다.
    # ★잠금 파일도 거둔다(agy 2R LOW) — 파일 잠금은 판이 끝나도 빈 파일이 남는다. 도는 판이 쥐고 있어도
    #   지우는 것은 안전하다(잠금은 열린 손잡이에 걸려 있고, 다음 판은 새 파일을 만든다).
    targets = ([p[key] for key in ("settings", "off", "attempts", "last", "out", "lock")]
               + [p["out"] + ".1"])
    for target_path in targets:
        if os.path.exists(target_path):
            os.remove(target_path)
            removed.append(target_path)
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
    # ★다시 켜는 것은 **「사람이 봤다」는 신호**다 — 연속 실패 계수를 여기서 지운다(요구 ⑧).
    #   ⛔방의 남은 기회(attempts)는 **안 건드린다**: 그건 회차마다 스스로 낡아 사라지는 값이고,
    #     여기서 함께 지우면 「말한 적 없는 회차」를 다시 세는 판이 생긴다.
    cleared = wake_failures(p)
    _set_wake_failures(p, 0)
    out = {"상주": summary_line(p["config_dir"]), "끄기": "agora resident off"}
    if cleared:
        out["지운_연속실패"] = cleared
    return out


def status(*, directory: str | None = None, platform: str | None = None,
           runner: Callable[[list[str]], dict[str, Any]] | None = None,
           which: Callable[[str], str | None] | None = None,
           exists: Callable[[str], bool] | None = None) -> dict[str, Any]:
    """지금 무엇이 돌고 있나 — ★일정이 실제로 올라가 있는지를 **물어서** 적는다(파일만 보고 적지 않는다)."""
    p = paths(directory)
    run = runner or _run
    plat = platform or sys.platform
    settings = _load_json(p["settings"])
    agent = find_agent(p, which, exists)
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
    return {"상주": summary_line(p["config_dir"]),
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
    # ★윈도우는 **돌려 본 적이 없다** — 「켜짐」만 적으면 돈다고 읽힌다(agy 1R MED).
    unmeasured = "윈도우 미실측 · " if settings.get("platform") == "win32" else ""
    return (f"상주: 켜짐({unmeasured}{interval}분 · {last_line(p)})"
            " · 끄기 = agora resident off")


def last_line(p: dict[str, str]) -> str:
    """마지막 판을 **있는 그대로** 한 줄로 — 성공이면 「방문」, 아니면 「시도 + 이유」.

    ⚠옛 판본(0.1.6)이 남긴 기록에는 칸이 `at` 하나뿐이고 그것은 **시작 시각**이다.
      끝난 시각을 모르므로 그 경우는 **「마지막 시도」**로 읽는다 — 모르는 것을 방문으로 올리지 않는다.
    """
    doc = _load_json(p["last"])
    if not doc:
        return "마지막 방문 아직 없음"
    stamp = doc.get("finished_at") or doc.get("started_at") or doc.get("at")
    seen = "아직 없음"
    if isinstance(stamp, str):
        try:
            moment = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            seen = moment.astimezone().strftime("%H:%M")
        except ValueError:
            seen = "읽지 못함"
    if doc.get("rc") == RC_OK and doc.get("finished_at"):
        return f"마지막 방문 {seen}"
    why = doc.get("why") or (f"종료코드 {doc['rc']}" if doc.get("rc") is not None else "이유 미상")
    if "finished_at" not in doc:
        why = f"{why} · 끝난 시각을 모른다(옛 판본 기록)" if doc.get("rc") is not None else "옛 판본 기록"
    return f"마지막 시도 {seen} — 실패({why})"


# ── CLI 입구 ────────────────────────────────────────────────────────────────
ACTION_ARGS: dict[str, tuple[str, ...]] = {
    "once": ("dry_run", "print_agenda", "dir"),
    "install": ("interval_min", "dir"),
    "uninstall": ("dir",),
    "status": ("dir",),
    "off": ("dir",),
    "on": ("dir",),
}


def check_action_args(action: str, kw: dict[str, Any]) -> None:
    """동작 이름과 그 동작이 받는 인자만 **검사**한다(실행은 안 한다).

    ★`dispatch` 에서 떼어 낸 것은 **문서 시험이 같은 판정을 쓰기 위해서**다(codex 1R HIGH-2):
      문서에 `agora resident status --interval-min 5` 라고 적히면 그 줄은 실제로 code 10 인데,
      검사가 실행 경로 안에만 있으면 문서를 재는 쪽은 그것을 못 본다.
    """
    if action not in ACTIONS:
        raise AgoraError(errors.ARGUMENT, "resident 의 동작은 once·install·uninstall·status·off·on 중 하나다",
                         {"got": action, "usage": "agora resident <once|install|uninstall|status|off|on>"})
    stray = sorted(k for k in kw if k not in ACTION_ARGS[action])
    if stray:
        raise AgoraError(errors.ARGUMENT, f"resident {action} 는 이 인자를 받지 않는다",
                         {"unknown": stray, "accepted": list(ACTION_ARGS[action])})


def dispatch(action: str, kw: dict[str, Any]) -> dict[str, Any]:
    """★동작마다 받는 인자를 **따로** 잰다 — `status --interval-min 5` 가 조용히 무시되면
    사람은 자기가 준 줄이 먹힌 줄 안다."""
    check_action_args(action, kw)
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
