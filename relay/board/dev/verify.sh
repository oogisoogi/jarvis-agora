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

echo "== 7. 판정 배지(플래그) =="
if [ -x "$CHROME" ]; then
  PORT=$(free_port)
  SRV=$(start_relay "$PORT") || fail "가짜 릴레이가 안 떴다"
  if [ -n "${SRV:-}" ]; then
    R2=b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2
    NODE_OPTIONS= node "$DEV/probe.mjs" "http://127.0.0.1:$PORT" "/room?id=$R2" 1440 "$SHOTS/room-verdict-off-1440.png" > "$OUT/verdict-off.json" 2>/dev/null
    NODE_OPTIONS= node "$DEV/probe.mjs" "http://127.0.0.1:$PORT" "/room?id=$R2&verdict=1" 1440 "$SHOTS/room-verdict-on-1440.png" > "$OUT/verdict-on.json" 2>/dev/null
    kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
    if python3 - <<PY
import json, sys
off = json.load(open("$OUT/verdict-off.json"))
on  = json.load(open("$OUT/verdict-on.json"))
ok = True
if off["verdictBadges"]:
    print("      끈 화면에 판정 배지", len(off["verdictBadges"]), "개"); ok = False
if not on["verdictBadges"]:
    print("      켠 화면에 판정 배지 0개 — 플래그가 안 먹는다"); ok = False
# 가린 것 요약은 켠 화면에만
def has(d, frag): return any(frag in n for n in d["notes"])
if has(off, "가린 기록"):
    print("      끈 화면에 가린 기록 요약이 있다"); ok = False
if not has(on, "가린 기록"):
    print("      켠 화면에 가린 기록 요약이 없다"); ok = False
# ⛔가린 글의 **본문**은 어느 쪽에도 없어야 한다(세는 것과 보여 주는 것은 다른 일이다)
for name, d in (("끈", off), ("켠", on)):
    if "기본 화면에 나오면 안 된다" in (d.get("allText") or ""):
        print(f"      {name} 화면에 가린 글의 본문이 새어 나왔다"); ok = False
print("      끈 화면 배지", len(off["verdictBadges"]), "· 켠 화면 배지", len(on["verdictBadges"]))
sys.exit(0 if ok else 1)
PY
    then
      pass "기본 off · ?verdict=1 에서만 배지 · 가린 글 본문은 양쪽 다 0"
    else
      fail "판정 배지 플래그가 계약대로 돌지 않는다"
    fi
  fi
fi

echo "== 8. 판정 칸이 없는 옛 서버 =="
if [ -x "$CHROME" ]; then
  PORT=$(free_port)
  SRV=$(start_relay "$PORT" --omit-verdict-fields) || fail "가짜 릴레이(판정 칸 제외)가 안 떴다"
  if [ -n "${SRV:-}" ]; then
    R2=b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2
    NODE_OPTIONS= node "$DEV/probe.mjs" "http://127.0.0.1:$PORT" "/room?id=$R2&verdict=1" 1440 "" > "$OUT/noverdict.json" 2>/dev/null
    kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
    # 칸이 없으면 ⑴배지 0 ⑵아무것도 가리지 않는다(없는 값으로 글을 지우지 않는다)
    if python3 -c "
import json,sys
d=json.load(open('$OUT/noverdict.json'))
ok = not d['verdictBadges'] and not any('가린 기록' in n for n in d['notes']) and d['speeches'] >= 5
print('      배지', len(d['verdictBadges']), '· 발언', d['speeches'])
sys.exit(0 if ok else 1)"; then
      pass "판정 칸이 없으면 배지 0 · 아무것도 가리지 않는다"
    else
      fail "판정 칸이 없는데 배지를 그렸거나 글을 지웠다"
    fi
  fi
fi

echo "== 9. 느린 서버에서 도착 전 화면을 찍지 않는가 =="
if [ -x "$CHROME" ]; then
  PORT=$(free_port)
  SRV=$(start_relay "$PORT" --slow 0.7) || fail "가짜 릴레이(지연)가 안 떴다"
  if [ -n "${SRV:-}" ]; then
    R3=c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3
    NODE_OPTIONS= node "$DEV/probe.mjs" "http://127.0.0.1:$PORT" "/room?id=$R3" 1440 "" > "$OUT/slow.json" 2>/dev/null
    kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
    if python3 -c "
import json,sys
d=json.load(open('$OUT/slow.json'))
ok = d['settled'] is True and d['speeches'] >= 3 and d['title'] != '아고라 — 방'
print('      정착', d['settled'], '· 발언', d['speeches'], '· 제목', d['title'])
sys.exit(0 if ok else 1)"; then
      pass "왕복이 늦어도 다 그려진 뒤에 찍는다"
    else
      fail "도착 전 화면을 찍었다 — 스크린샷이 거짓 결함을 만든다"
    fi
  fi
fi

echo "== 10. 오류 화면도 「다 그렸다」고 말하는가 =="
if [ -x "$CHROME" ]; then
  PORT=$(free_port)
  SRV=$(start_relay "$PORT") || fail "가짜 릴레이가 안 떴다"
  if [ -n "${SRV:-}" ]; then
    NODE_OPTIONS= node "$DEV/probe.mjs" "http://127.0.0.1:$PORT" "/room?id=ffffffffffffffffffffffffffffffff" 1440 "" > "$OUT/err.json" 2>/dev/null
    kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
    if python3 -c "
import json,sys
d=json.load(open('$OUT/err.json'))
notes=' '.join(d['notes'])
ok = d['settled'] is True and '찾지 못했습니다' in notes
print('      정착', d['settled'], '· 알림', len(d['notes']))
sys.exit(0 if ok else 1)"; then
      pass "없는 방에서도 오류를 말하고 정착 신고를 내린다"
    else
      fail "오류 화면이 「아직 그리는 중」으로 남았거나 오류를 안 말했다"
    fi
  fi
fi

echo "== 결과: $([ $rc -eq 0 ] && echo PASS || echo FAIL) =="
exit $rc
