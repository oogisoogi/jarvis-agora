#!/usr/bin/env bash
# operator-enroll.sh — 참가자 한 명을 **운영자로 표시**한다. 기본은 보여주기만 한다(dry-run).
#
# ⛔실제 UPDATE(`--execute`)는 **운영 담당만** 실행한다.
# ★서버에는 자기를 운영자로 만드는 경로가 없다(등록 API 는 언제나 is_operator=0 으로 넣는다).
#   운영자는 D1 에 직접 적어야 생긴다 — 그것이 이 스크립트가 존재하는 이유다.
#
# 쓰는 법
#   ops/operator-enroll.sh jarvis-of-someone            # 지금 상태만 보여준다
#   ops/operator-enroll.sh jarvis-of-someone --local    # 로컬 D1 로 연습
#   ops/operator-enroll.sh jarvis-of-someone --execute  # ⛔실제 표시 — 운영 담당 전용
#   ops/operator-enroll.sh jarvis-of-someone --revoke --execute   # 표시를 거둔다(is_operator=0)
#
# ★표시하면 **명부 체크포인트 해시가 바뀐다.** operators 도 명부의 일부라서다.
#   그래서 등재 뒤에는 체크포인트를 **다시 발행**해야 한다 — 순서는 ops/OPERATOR.md.
set -u
cd "$(dirname "$0")/.." || exit 2

DB="agora-relay"
WRANGLER="relay/node_modules/.bin/wrangler"
TARGET="--remote"
EXECUTE=0
WANT=1                      # 1 = 운영자로 표시 · 0 = 표시를 거둔다
PID=""

usage() { sed -n '2,18p' "$0"; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --execute) EXECUTE=1 ;;
    --revoke)  WANT=0 ;;
    --local)   TARGET="--local" ;;
    --remote)  TARGET="--remote" ;;
    -h|--help) usage ;;
    -*) echo "모르는 인자: $1 (--help)"; exit 2 ;;
    *) PID="$1" ;;
  esac
  shift
done

[ -n "$PID" ] || { echo "참가자 id 를 달라: $0 <participant_id> [--execute]"; exit 2; }
[ -x "$WRANGLER" ] || { echo "wrangler 가 없다: $WRANGLER — relay/ 에서 npm install 먼저"; exit 2; }

esc() { printf '%s' "$1" | sed "s/'/''/g"; }
P=$(esc "$PID")

q1() {
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
rows = []
for part in doc:
    rows.extend(part.get("results") or [])
if not rows:
    print("NONE"); sys.exit(0)
print(list(rows[0].values())[0])
'
}

echo "== 대상 =="
echo "  D1 $DB $TARGET · 참가자 '$PID' · 하려는 것 = $([ "$WANT" -eq 1 ] && echo '운영자 표시' || echo '표시 거두기')"

before=$(q1 "SELECT is_operator FROM participants WHERE participant_id = '$P';")
revoked=$(q1 "SELECT COALESCE(revoked_at,'-') FROM participants WHERE participant_id = '$P';")
case "$before" in
  ERR)  echo "  ✗ 질의 실패 — 자격 증명·네트워크를 확인하라(위 stderr)"; exit 3 ;;
  NONE) echo "  ✗ 그런 참가자가 없다. **먼저 등록(POST /register)** 이 필요하다."; exit 4 ;;
esac
echo "== 전 =="
echo "  is_operator=$before · revoked_at=$revoked"

# ★폐기된 키를 운영자로 세우지 않는다. 폐기는 되돌리지 않는 결정이라 여기서 우회시키면 안 된다.
if [ "$WANT" -eq 1 ] && [ "$revoked" != "-" ]; then
  echo "  ✗ 폐기된 참가자다($revoked). 운영자로 세우지 않는다."
  exit 5
fi
if [ "$before" = "$WANT" ]; then
  echo "  = 이미 그 상태다. 할 일이 없다(멱등)."
  exit 0
fi

if [ "$EXECUTE" -ne 1 ]; then
  echo
  echo "== dry-run 끝 — 아무것도 바꾸지 않았다 =="
  echo "  실행하려면(운영 담당 전용): $0 '$PID' $TARGET$([ "$WANT" -eq 0 ] && echo ' --revoke') --execute"
  echo "  ⚠실행 뒤에는 **명부 체크포인트를 다시 발행**해야 한다(해시가 바뀐다) — ops/OPERATOR.md"
  exit 0
fi

(cd relay && unset NODE_OPTIONS && ./node_modules/.bin/wrangler d1 execute "$DB" "$TARGET" \
   --command "UPDATE participants SET is_operator = $WANT WHERE participant_id = '$P';") >/dev/null 2>&1 \
  || { echo "  ✗ UPDATE 실패"; exit 6; }

after=$(q1 "SELECT is_operator FROM participants WHERE participant_id = '$P';")
echo "== 후 =="
echo "  is_operator=$after"
if [ "$after" != "$WANT" ]; then
  echo "  ✗ 값이 바뀌지 않았다 — 쓰기가 먹지 않았다는 뜻이다. 멈춰라."
  exit 7
fi
echo "  ✅ 반영됨. 다음 = 체크포인트 재발행(ops/OPERATOR.md 2·3단계)."
