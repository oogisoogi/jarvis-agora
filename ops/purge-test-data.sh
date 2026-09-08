#!/usr/bin/env bash
# purge-test-data.sh — 시험 등재를 원장에서 걷어낸다. **기본은 세기만 한다(dry-run).**
#
# ⛔실제 삭제(`--execute`)는 **운영 담당만** 실행한다. 이 저장소의 워커는 dry-run 까지다.
#   지우는 것은 되돌릴 수 없고, 원장은 append-only 라 「지운다」 자체가 예외 조치다.
#   그래서 기본값이 안전한 쪽이고, 위험한 쪽에 플래그를 붙였다(반대로 두면 손이 미끄러진다).
#
# 무엇을 대상으로 삼나
#   ⑴ 대상 참가자 = participants.participant_id LIKE <패턴>   (기본 'jarvis-test-%')
#   ⑵ 대상 이벤트 = 대상 참가자가 쓴 이벤트 중 **순수 시험 방**에 있는 것
#   ⑶ 대상 방     = 그 방의 이벤트가 **전부** 대상 참가자 것인 방(파생 캐시 rooms 행)
#
# ★섞인 방(시험 참가자 + 실 참가자가 같이 쓴 방)은 **건드리지 않는다.**
#   사슬은 prev 로 이어져 있어서 중간 글을 빼면 그 뒤 글이 `unreachable` 이 된다 —
#   지우는 쪽이 원장을 조용히 망가뜨리는 경우다. 세어서 보여만 주고, 판단은 사람이 한다.
#
# 쓰는 법
#   ops/purge-test-data.sh                # 원격 D1 에 COUNT 만 던진다(읽기 전용)
#   ops/purge-test-data.sh --local        # 로컬 D1 로 같은 것을 한다(연습용)
#   ops/purge-test-data.sh --pattern 'demo-%'
#   ops/purge-test-data.sh --execute      # ⛔실제 삭제 — 운영 담당 전용
#   ops/purge-test-data.sh --include-operators   # ⚠운영자까지 대상에 넣는다(기본은 뺀다)
#   ops/purge-test-data.sh --execute --confirm agora-relay   # 대화형이 아닐 때의 확인 방법
#   ops/purge-test-data.sh --before 2026-09-06T00:00:00+09:00 --no-events
#                                          # 패턴에 더해 「그 시각 앞 등록 ∧ 글 0건 ∧ 운영자 아님」도 대상에 넣는다
#
# ★두 번째 대상 무리가 있는 이유(운영 판정 2026-09-06): 설치기 왕복 시험이 만든 등재는
#   **실 참가자와 id 모양이 같다**(jarvis-<무작위>). 이름으로는 못 가르므로 **행동으로** 가른다 —
#   「글을 한 줄도 안 썼고, 그 시각 이전에 등록했고, 운영자가 아니다.」
#   ⚠--before 와 --no-events 는 **함께** 써야 한다. 하나만 주면 대상이 조용히 넓어진다(그래서 거부한다).
set -u
cd "$(dirname "$0")/.." || exit 2

DB="agora-relay"
WRANGLER="relay/node_modules/.bin/wrangler"
PATTERN="jarvis-test-%"
TARGET="--remote"
EXECUTE=0
INCLUDE_OPS=0
CONFIRM=""
BEFORE_RAW=""
NO_EVENTS=0
LOG="ops/purge-log.md"

usage() { sed -n '2,26p' "$0"; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --execute) EXECUTE=1 ;;
    --local)   TARGET="--local" ;;
    --remote)  TARGET="--remote" ;;
    --pattern) shift; PATTERN="${1:-}" ;;
    --include-operators) INCLUDE_OPS=1 ;;
    --confirm) shift; CONFIRM="${1:-}" ;;
    --before) shift; BEFORE_RAW="${1:-}" ;;
    --no-events) NO_EVENTS=1 ;;
    -h|--help) usage ;;
    *) echo "모르는 인자: $1 (--help)"; exit 2 ;;
  esac
  shift
done

[ -x "$WRANGLER" ] || { echo "wrangler 가 없다: $WRANGLER — relay/ 에서 npm install 먼저"; exit 2; }

# ── 질의 도우미 ──────────────────────────────────────────────────────────────
# ★한 값을 받는 질의만 쓴다. 표를 파싱하기 시작하면 이 스크립트가 도구가 아니라 프로그램이 된다.
q1() {
  local sql="$1" out
  out=$(cd relay && unset NODE_OPTIONS && ./node_modules/.bin/wrangler d1 execute "$DB" \
        "$TARGET" --json --command "$sql" 2>&1) || { echo "ERR"; printf '%s\n' "$out" >&2; return 1; }
  printf '%s' "$out" | python3 -c '
import json, sys
# ★실패를 0 으로 읽지 않는다(agy 1R 지적 2). 「지울 것이 없다」와 「못 물어봤다」는 다른 사건이고,
#   둘을 같은 값으로 만들면 이 스크립트의 출력 전체가 믿을 수 없는 것이 된다.
raw = sys.stdin.read()
i, j = raw.find("["), raw.rfind("]")
if i < 0 or j < 0:
    print("ERR"); sys.exit(0)
try:
    doc = json.loads(raw[i:j + 1])
except Exception:
    print("ERR"); sys.exit(0)
if not isinstance(doc, list) or not doc:
    print("ERR"); sys.exit(0)
rows = []
for part in doc:
    if not isinstance(part, dict) or part.get("success") is False or "results" not in part:
        print("ERR"); sys.exit(0)          # 통신은 됐어도 질의가 실패한 모양이다
    rows.extend(part.get("results") or [])
if len(rows) != 1:
    print("ERR"); sys.exit(0)              # COUNT 질의는 언제나 한 줄이다. 아니면 뭔가 틀렸다.
print(list(rows[0].values())[0])
'
}

# ★계수 하나라도 ERR 이면 그 자리에서 멈춘다 — 반쪽 숫자로 사람이 판단하게 두지 않는다.
die_on_err() {
  case "$*" in
    *ERR*) echo "  ✗ 질의 실패 — 자격 증명·네트워크·SQL 을 확인하라(위 stderr). 아무것도 하지 않았다."; exit 3 ;;
  esac
}

esc() { printf '%s' "$1" | sed "s/'/''/g"; }
P=$(esc "$PATTERN")

# ★LIKE 의 `_` 는 「아무 글자 하나」다. 패턴에 밑줄이 있으면 의도보다 넓게 잡히므로
#   ESCAPE 를 붙여 리터럴로 읽게 한다(같은 함정을 이 저장소는 한 번 밟았다).
LIKE="LIKE '$P' ESCAPE '\\'"

# ★운영자는 기본적으로 대상에서 뺀다. 실측(2026-09-06)에서 라이브의 운영자 id 가 시험 패턴과
#   **같은 모양**이었다(`jarvis-test-operator`) — 패턴만 믿었으면 운영자를 지울 뻔했다.
#   운영자를 지우면 체크포인트를 올릴 사람이 사라지고, 그 복구는 등록·표시·재발행 전 과정이다.
OP_GUARD="AND is_operator = 0"
[ "$INCLUDE_OPS" -eq 1 ] && OP_GUARD=""
# ── 두 번째 대상 무리(행동으로 가른다) ──────────────────────────────────────
EXTRA_WHERE=""
if [ -n "$BEFORE_RAW" ] || [ "$NO_EVENTS" -eq 1 ]; then
  if [ -z "$BEFORE_RAW" ] || [ "$NO_EVENTS" -ne 1 ]; then
    echo "  ✗ --before 와 --no-events 는 함께 써야 한다(하나만 주면 대상이 넓어진다). 멈춘다."; exit 2
  fi
  # ★경계 시각을 **우리가 저장하는 서식**(UTC 밀리초 고정폭)으로 정규화한다.
  #   created_at 비교는 문자열 비교라, +09:00 을 그대로 넣으면 9시간 어긋난 채로 조용히 돈다.
  BEFORE=$(python3 -c '
import datetime, sys
raw = sys.argv[1].strip()
if raw.endswith("Z"):
    raw = raw[:-1] + "+00:00"
try:
    dt = datetime.datetime.fromisoformat(raw)
except ValueError:
    print("ERR"); sys.exit(0)
if dt.tzinfo is None:
    print("ERR"); sys.exit(0)     # 무엇 기준인지 모르는 시각은 받지 않는다
dt = dt.astimezone(datetime.timezone.utc)
print(dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000))
' "$BEFORE_RAW")
  [ "$BEFORE" = "ERR" ] && { echo "  ✗ --before 를 못 읽었다('$BEFORE_RAW'). 예: 2026-09-06T00:00:00+09:00"; exit 2; }
  EXTRA_WHERE="OR (created_at < '$BEFORE' AND is_operator = 0
                   AND participant_id NOT IN (SELECT DISTINCT from_id FROM events))"
fi

TEST_PIDS="SELECT participant_id FROM participants
           WHERE ((participant_id $LIKE $OP_GUARD) $EXTRA_WHERE)"
PURE_ROOMS="SELECT thread_id FROM events GROUP BY thread_id
            HAVING SUM(CASE WHEN from_id IN ($TEST_PIDS) THEN 0 ELSE 1 END) = 0"
MIXED_ROOMS="SELECT thread_id FROM events GROUP BY thread_id
             HAVING SUM(CASE WHEN from_id IN ($TEST_PIDS) THEN 1 ELSE 0 END) > 0
                AND SUM(CASE WHEN from_id IN ($TEST_PIDS) THEN 0 ELSE 1 END) > 0"

echo "== 대상 =="
echo "  D1 $DB $TARGET · 패턴 '$PATTERN' · 모드 $([ "$EXECUTE" -eq 1 ] && echo '실행(--execute)' || echo 'dry-run(세기만)')"
[ -n "$EXTRA_WHERE" ] && echo "  + 행동 기준: $BEFORE 이전 등록 ∧ 글 0건 ∧ 운영자 아님"

before_p=$(q1 "SELECT COUNT(*) FROM participants;")
before_e=$(q1 "SELECT COUNT(*) FROM events;")
before_r=$(q1 "SELECT COUNT(*) FROM rooms;")
die_on_err "$before_p" "$before_e" "$before_r"

hit_p=$(q1 "SELECT COUNT(*) FROM ($TEST_PIDS);")
hit_e=$(q1 "SELECT COUNT(*) FROM events WHERE from_id IN ($TEST_PIDS) AND thread_id IN ($PURE_ROOMS);")
hit_r=$(q1 "SELECT COUNT(*) FROM rooms WHERE thread_id IN ($PURE_ROOMS);")
mixed=$(q1 "SELECT COUNT(*) FROM ($MIXED_ROOMS);")
stray=$(q1 "SELECT COUNT(*) FROM events WHERE from_id IN ($TEST_PIDS) AND thread_id NOT IN ($PURE_ROOMS);")
die_on_err "$hit_p" "$hit_e" "$hit_r" "$mixed" "$stray"

echo "== 지금 원장(전) =="
echo "  participants $before_p · events $before_e · rooms(파생 캐시) $before_r"
echo "== 걷어낼 것 =="
echo "  참가자 $hit_p · 이벤트 $hit_e · 방(캐시) $hit_r"
skipped_ops=$(q1 "SELECT COUNT(*) FROM participants WHERE participant_id $LIKE AND is_operator = 1;")
die_on_err "$skipped_ops"
echo "== 건드리지 않는 것 =="
echo "  섞인 방 $mixed 개 · 그 안의 시험 이벤트 $stray 건"
echo "  패턴에 걸렸지만 **운영자라서 뺀** 참가자 $skipped_ops 명$([ "$INCLUDE_OPS" -eq 1 ] && echo ' (⚠--include-operators 로 이번엔 포함된다)')"
echo "  ★섞인 방에서 글을 빼면 그 뒤 글이 사슬에서 끊긴다(unreachable). 사람이 판단할 일이다."

if [ "$EXECUTE" -ne 1 ]; then
  echo
  echo "== dry-run 끝 — 아무것도 지우지 않았다 =="
  echo "  실제로 지우려면(운영 담당 전용): $0 $TARGET --pattern '$PATTERN'$([ "$INCLUDE_OPS" -eq 1 ] && echo ' --include-operators') --execute"
  exit 0
fi

# ── 여기부터는 되돌릴 수 없다 ────────────────────────────────────────────────
# ★확인 게이트(agy 1R 지적 4): 원격에 파괴적 SQL 을 던지기 전에 **DB 이름을 손으로** 받는다.
#   플래그 하나가 붙었다는 사실만으로 프로덕션을 지우게 두지 않는다.
#   자동 실행(파이프·cron)에서는 `--confirm <DB이름>` 으로 같은 확인을 명시한다.
if [ "$TARGET" = "--remote" ]; then
  if [ -n "$CONFIRM" ]; then
    [ "$CONFIRM" = "$DB" ] || { echo "  ✗ --confirm 값이 DB 이름과 다르다($CONFIRM ≠ $DB). 멈춘다."; exit 6; }
  elif [ -t 0 ]; then
    printf "  ⛔원격 %s 에서 위 계수만큼 지운다. 되돌릴 수 없다. DB 이름을 그대로 입력하라: " "$DB"
    read -r typed
    [ "$typed" = "$DB" ] || { echo "  ✗ 입력이 다르다. 멈춘다."; exit 6; }
  else
    echo "  ✗ 대화형이 아니다. 원격 삭제에는 --confirm $DB 가 필요하다."; exit 6
  fi
fi

# ★대상 id 를 **지우기 전에** 고정한다(agy 1R 지적 1 · 진짜 결함이었다).
#   PURE_ROOMS 는 events 를 보고 방을 고르는 질의다. events 를 먼저 지우면 그 다음 문장에서
#   **같은 질의가 0건을 낸다** ⇒ rooms 캐시가 안 지워지고 로비에 **유령 방**으로 남는다.
#   그래서 목록을 먼저 뽑아 리터럴로 굳힌 뒤, 세 문장을 **한 번의 호출**로 보낸다.
qlist() {
  local sql="$1" out
  out=$(cd relay && unset NODE_OPTIONS && ./node_modules/.bin/wrangler d1 execute "$DB" \
        "$TARGET" --json --command "$sql" 2>&1) || { echo "ERR"; printf '%s\n' "$out" >&2; return 1; }
  printf '%s' "$out" | python3 -c '
import json, sys
raw = sys.stdin.read()
i, j = raw.find("["), raw.rfind("]")
if i < 0 or j < 0:
    print("ERR"); sys.exit(0)
try:
    doc = json.loads(raw[i:j + 1])
except Exception:
    print("ERR"); sys.exit(0)
vals = []
for part in doc:
    if not isinstance(part, dict) or part.get("success") is False or "results" not in part:
        print("ERR"); sys.exit(0)
    for row in part.get("results") or []:
        v = list(row.values())[0]
        q = chr(39)                        # 작은따옴표. 파이썬 소스에 그 글자를 그대로 쓰면
                                           # 셸의 -c 인용이 그 자리에서 닫힌다(실제로 한 번 깨졌다).
        if not isinstance(v, str) or q in v:
            print("ERR"); sys.exit(0)      # 따옴표가 든 값은 리터럴로 굳히지 않는다
        vals.append(q + v + q)
print(",".join(vals))
'
}

PID_LIST=$(qlist "$TEST_PIDS;")
ROOM_LIST=$(qlist "$PURE_ROOMS;")
case "$PID_LIST$ROOM_LIST" in
  *ERR*) echo "  ✗ 대상 목록을 굳히지 못했다. 아무것도 하지 않았다."; exit 3 ;;
esac
[ -n "$PID_LIST" ] || { echo "  = 대상 참가자가 없다. 할 일이 없다."; exit 0; }

echo
echo "== 삭제(순서 = events → rooms → participants · 한 번의 호출) =="
echo "  대상 참가자 $(printf '%s' "$PID_LIST" | awk -F, '{print NF}') 명 · 대상 방 $([ -n "$ROOM_LIST" ] && printf '%s' "$ROOM_LIST" | awk -F, '{print NF}' || echo 0) 개"
# ★순서가 규칙이다: 이벤트를 먼저 지워야 파생 캐시가 「지금은 없는 글」을 가리키지 않는다.
#   참가자를 먼저 지우면 그 사람의 남은 글이 명부 밖 서명으로 보여 판정이 뒤집힌다.
#   ⚠D1 의 질의 API 에는 BEGIN/COMMIT 이 없다. 한 호출에 담는 것이 우리가 가진 가장 원자적인 형태다
#     (그래도 부분 실패가 원리적으로 0 은 아니다 — 그래서 실행 뒤 계수를 다시 재고 로그에 남긴다).
ROOM_CLAUSE=""
[ -n "$ROOM_LIST" ] && ROOM_CLAUSE="DELETE FROM rooms WHERE thread_id IN ($ROOM_LIST);"
EVENT_CLAUSE=""
[ -n "$ROOM_LIST" ] && EVENT_CLAUSE="DELETE FROM events WHERE from_id IN ($PID_LIST) AND thread_id IN ($ROOM_LIST);"
(cd relay && unset NODE_OPTIONS && ./node_modules/.bin/wrangler d1 execute "$DB" "$TARGET" --command \
  "$EVENT_CLAUSE $ROOM_CLAUSE DELETE FROM participants WHERE participant_id IN ($PID_LIST);") \
  >/dev/null 2>&1 || { echo "  ✗ 삭제 호출이 실패했다. 아래 계수로 지금 상태를 확인하라."; }

after_p=$(q1 "SELECT COUNT(*) FROM participants;")
after_e=$(q1 "SELECT COUNT(*) FROM events;")
after_r=$(q1 "SELECT COUNT(*) FROM rooms;")
echo "== 지금 원장(후) =="
echo "  participants $after_p · events $after_e · rooms $after_r"

{
  echo ""
  echo "## $(date -u '+%Y-%m-%dT%H:%M:%S.000Z') · $TARGET · 패턴 \`$PATTERN\`"
  echo ""
  echo "| 표 | 전 | 후 | 걷어낸 것 |"
  echo "|---|---|---|---|"
  echo "| participants | $before_p | $after_p | $hit_p |"
  echo "| events | $before_e | $after_e | $hit_e |"
  echo "| rooms(파생 캐시) | $before_r | $after_r | $hit_r |"
  echo ""
  echo "건드리지 않은 것: 섞인 방 $mixed 개 · 그 안의 시험 이벤트 $stray 건"
} >> "$LOG"
echo "  기록 append: $LOG"
