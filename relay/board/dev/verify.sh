#!/usr/bin/env bash
# verify.sh — 박람회장 보드 검증 하네스. **판정은 이 스크립트의 출력만이 사실이다.**
#
# ★왜 스크립트인가: 같은 검사를 손으로 칠 때마다 한 번씩 틀린다. 그리고 손으로 치면
#   「어떤 조합을 안 재고 넘어갔는지」가 남지 않는다. 재는 것과 못 잰 것을 여기서 함께 출력한다.
#
# 쓰는 법:  bash relay/board/dev/verify.sh
set -u
cd "$(dirname "$0")/../../.." || exit 2      # 저장소 뿌리

BOARD=relay/board
DEV=$BOARD/dev
OUT=$DEV/out
SHOTS=$DEV/shots
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
rc=0
mkdir -p "$OUT" "$SHOTS"

fail() { echo "  FAIL — $*"; rc=1; }
pass() { echo "  PASS — $*"; }
skip() { echo "  미측정 — $* (통과 아님)"; rc=1; }

free_port() {
  python3 - <<'PY'
import socket
for p in range(8850, 8950):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", p)); s.close(); print(p); break
    except OSError:
        s.close()
PY
}

start_relay() {   # $1 = port, 나머지 = 추가 인자
  local port="$1"; shift
  python3 "$DEV/fake-relay.py" --port "$port" "$@" >/dev/null 2>&1 &
  echo $!
  for _ in $(seq 1 40); do
    curl -sf -o /dev/null "http://127.0.0.1:$port/rooms" && return 0
    sleep 0.2
  done
  return 1
}

echo "== 1. 공개 표현 규약(금칙어) — 저장소 전 파일 =="
hits=0
while IFS= read -r f; do
  [ "$f" = "tests/forbidden-terms.txt" ] && continue
  [ -f "$f" ] || continue
  n=$(grep -c -f tests/forbidden-terms.txt -- "$f" 2>/dev/null); [ -n "$n" ] || n=0
  if [ "$n" -gt 0 ] 2>/dev/null; then echo "    위반 $f: ${n}건"; hits=$((hits + n)); fi
done < <(git ls-files --cached --others --exclude-standard)
[ "$hits" -eq 0 ] && pass "금칙어 0건" || fail "금칙어 ${hits}건"

echo "== 2. 본문 렌더 규율(정적) =="
# ★검사기부터 실사격한다 — 죽은 검사기의 「0건」은 아무것도 증명하지 않는다.
if python3 "$DEV/scan_source.py" --selftest | sed 's/^/    /' | tail -1 | grep -q "실패 0건"; then
  pass "검사기 자기검사 통과(변이를 심으면 적색이 난다)"
else
  python3 "$DEV/scan_source.py" --selftest | sed 's/^/    /'
  fail "검사기 자기검사 실패 — 이 아래 0건은 못 믿는다"
fi
if python3 "$DEV/scan_source.py" "$BOARD"; then
  pass "innerHTML 0건 · 빈칸 기본값 0건"
else
  fail "정적 규율 위반 — 위 목록"
fi

echo "== 3. 하단 고정 문구 =="
# ★총합을 보면 안 된다 — 한 장에서 0회, 다른 장에서 2회여도 총합은 맞는다(배치가 다른데 집계가 같다).
#   파일마다 정확히 1회인지를 **각각** 묻는다.
bad3=0
for h in $BOARD/*.html; do
  c=$(grep -c "이 화면은 서버의 계산입니다 — 정본은 서명된 이벤트입니다." "$h"); [ -n "$c" ] || c=0
  if [ "$c" -ne 1 ]; then echo "    $h: ${c}회 (기대 1)"; bad3=$((bad3 + 1)); fi
done
files=$(ls $BOARD/*.html | wc -l | tr -d ' ')
[ "$bad3" -eq 0 ] && pass "HTML ${files}장 전부 정확히 1회" || fail "고정 문구가 1회가 아닌 파일 ${bad3}장"

echo "== 4. 색 대비 계기(토큰 조합) =="
if python3 "$DEV/contrast.py" > "$OUT/contrast.txt" 2>&1; then
  tail -1 "$OUT/contrast.txt" | grep -q "= 0건" && pass "$(tail -1 "$OUT/contrast.txt")" || fail "$(tail -1 "$OUT/contrast.txt")"
else
  skip "대비 계기 실행 실패"
fi

echo "== 5. 실렌더 측정(헤드리스) =="
if [ ! -x "$CHROME" ]; then
  skip "크롬 없음 — 실렌더를 재지 못했다"
else
  PORT=$(free_port)
  SRV=$(start_relay "$PORT") || { fail "가짜 릴레이가 안 떴다"; SRV=""; }
  if [ -n "$SRV" ]; then
    R2=b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2
    R3=c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3
    for w in 1440 390; do
      for spec in "/|lobby" "/room?id=$R3|room-resolved" "/room?id=$R2|room-r2" "/archive|archive"; do
        p="${spec%%|*}"; nm="${spec##*|}"
        NODE_OPTIONS= node "$DEV/probe.mjs" "http://127.0.0.1:$PORT" "$p" "$w" "$SHOTS/$nm-$w.png" > "$OUT/$nm-$w.json" 2>"$OUT/$nm-$w.err" \
          || echo "    probe 실패: $nm-$w ($(head -1 "$OUT/$nm-$w.err"))"
      done
    done
    kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
    python3 "$DEV/judge.py" "$OUT" || rc=1
  fi
fi

echo "== 6. 폴백 두 가지(서버가 덜 줄 때) =="
if [ -x "$CHROME" ]; then
  PORT=$(free_port)
  SRV=$(start_relay "$PORT" --omit-signature-fields) || fail "가짜 릴레이(서명 칸 제외)가 안 떴다"
  if [ -n "${SRV:-}" ]; then
    NODE_OPTIONS= node "$DEV/probe.mjs" "http://127.0.0.1:$PORT" "/room?id=c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3" 1440 "$SHOTS/room-nosig-1440.png" > "$OUT/nosig.json" 2>/dev/null
    kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
    b=$(python3 -c "import json;print(len(json.load(open('$OUT/nosig.json'))['badges']))" 2>/dev/null || echo ERR)
    [ "$b" = "0" ] && pass "서명 파생값이 없으면 배지 0개" || fail "배지가 ${b}개 그려졌다 — 없는 칸으로 신뢰를 말하면 안 된다"
  fi

  PORT=$(free_port)
  SRV=$(start_relay "$PORT" --fail-second-page) || fail "가짜 릴레이(2쪽 실패)가 안 떴다"
  if [ -n "${SRV:-}" ]; then
    NODE_OPTIONS= node "$DEV/probe.mjs" "http://127.0.0.1:$PORT" "/room?id=c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3" 1440 "$SHOTS/room-partial-1440.png" > "$OUT/partial.json" 2>/dev/null
    kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
    if python3 -c "
import json,sys
d=json.load(open('$OUT/partial.json'))
ok=any('더 가져오지 못했습니다' in n for n in d['notes'])
sys.exit(0 if ok else 1)" 2>/dev/null; then
      pass "이어받기 실패 시 「여기까지가 전부가 아니다」를 말한다"
    else
      fail "이어받기가 실패했는데 화면이 조용하다 — 일부를 전건처럼 그린다"
    fi
  fi
fi

  PORT=$(free_port)
  SRV=$(start_relay "$PORT" --omit-chair) || fail "가짜 릴레이(의장 칸 제외)가 안 떴다"
  if [ -n "${SRV:-}" ]; then
    NODE_OPTIONS= node "$DEV/probe.mjs" "http://127.0.0.1:$PORT" "/room?id=c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3" 1440 "" > "$OUT/nochair.json" 2>/dev/null
    kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
    # ★음성 단언(없는 칸을 안 그린다)만 두면 **렌더가 통째로 죽어도** 초록이다.
    #   그래서 같은 화면에서 **서버가 준 칸은 여전히 그려진다**를 함께 못박는다(양성 구조 단언).
    if python3 -c "
import json,sys
d=json.load(open('$OUT/nochair.json'))
fields=d['fields']
has_chair=any('의장' in f for f in fields)
has_count=any('글 수' in f for f in fields)
filler=any(w in (d.get('allText') or '') for w in ('알 수 없음','미상','undefined'))
sys.exit(0 if (not has_chair and not filler and has_count) else 1)" 2>/dev/null; then
      pass "안 준 칸은 안 그리고(자리 메움 0) 준 칸은 그대로 그린다"
    else
      python3 -c "
import json
d=json.load(open('$OUT/nochair.json'))
print('      칸:', d['fields'])" 2>/dev/null
      fail "서버가 안 준 칸을 메웠거나, 준 칸까지 함께 사라졌다(렌더가 죽었을 수 있다)"
    fi
  fi

echo "== 결과: $([ $rc -eq 0 ] && echo PASS || echo FAIL) =="
exit $rc
