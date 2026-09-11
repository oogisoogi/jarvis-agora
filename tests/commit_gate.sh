#!/usr/bin/env bash
# 커밋 전 게이트 — 공개 표현 규약(금칙어 0) + 비밀 누출 0.
#
# ★왜 스크립트인가: 이 검사를 손으로 칠 때마다 한 번씩 틀렸다.
#   `grep -c` 는 0건일 때 "0" 을 찍고 **종료코드 1** 로 끝난다. `|| echo 0` 을 붙이면
#   출력이 "0\n0" 이 되어 「0이 아니다」가 참이 되고, **깨끗한 파일이 위반으로 보고된다.**
#   검사기가 고장나면 그 출력은 아무것도 증명하지 않는다 — 그래서 도구로 고정한다.
#
# ★금칙어 목록은 tests/forbidden-terms.txt 에 **한 곳에만** 둔다.
#   그 파일은 정의상 금칙어를 담으므로 검사 대상에서 뺀다 — 그리고 **뺐다는 사실을 출력한다.**
#   보이지 않는 억제는 미탐과 구별되지 않는다.
set -u
cd "$(dirname "$0")/.." || exit 2

TERMS_FILE="tests/forbidden-terms.txt"
EXCLUDED_FROM_TERM_SCAN=("$TERMS_FILE")
rc=0

echo "== 공개 표현 규약 =="
if [ ! -s "$TERMS_FILE" ]; then
  echo "  FAIL — 금칙어 목록이 비었거나 없다($TERMS_FILE). 검사가 무의미하므로 통과시키지 않는다."
  exit 3
fi
term_count=$(grep -c . "$TERMS_FILE")
echo "  목록 $term_count 개 · 검사 제외 ${#EXCLUDED_FROM_TERM_SCAN[@]}건: ${EXCLUDED_FROM_TERM_SCAN[*]}"

# 검사 대상 = git 이 추적하거나 추적할 파일(무시 파일 제외). 텍스트만 본다.
hits=0
while IFS= read -r f; do
  case " ${EXCLUDED_FROM_TERM_SCAN[*]} " in *" $f "*) continue ;; esac
  [ -f "$f" ] || continue
  n=$(grep -c -f "$TERMS_FILE" -- "$f" 2>/dev/null); [ -n "$n" ] || n=0
  if [ "$n" -gt 0 ] 2>/dev/null; then
    echo "  위반 $f: ${n}건"
    hits=$((hits + n))
  fi
done < <(git ls-files --cached --others --exclude-standard)
echo "  합계 ${hits}건"
[ "$hits" -eq 0 ] || rc=1

echo "== 비밀 누출 =="
if command -v gitleaks >/dev/null 2>&1; then
  if gitleaks dir . --no-banner >/tmp/agora-gitleaks.$$ 2>&1; then
    echo "  no leaks"
  else
    echo "  FAIL — 아래 출력 확인"; tail -20 /tmp/agora-gitleaks.$$; rc=1
  fi
  rm -f /tmp/agora-gitleaks.$$
else
  # ★없으면 통과가 아니라 실패다. 못 잰 것을 잰 것으로 세지 않는다.
  echo "  FAIL — 스캐너 부재로 **미측정**(통과 아님)"; rc=1
fi

echo "== selftest =="
if ./bin/agora selftest >/tmp/agora-selftest.$$ 2>&1; then
  # ★파싱 실패를 **삼키지 않는다.** rc 0 만 보고 통과시키면, 출력이 오염돼 한 글자도
  #   못 읽은 상태가 「PASS」로 나온다 — 검사기가 고장난 것과 통과한 것이 구별되지 않는다.
  #   (2026-08-25 S5-3 에서 실제로 났다: 케이스 하나가 stderr 로 JSON 을 흘려 `2>&1` 로
  #    합쳐진 출력이 「Extra data」가 됐는데 게이트는 PASS·rc 0 을 냈다.)
  if ! python3 -c "
import json,sys
r=json.load(open('/tmp/agora-selftest.$$'))
s=r['요약']; m=r['미측정']
print('  ', s['케이스'], '·', s['뮤테이션'], '· 슬라이스', s['슬라이스'])
print('   미측정: NOT-APPLIED', m['뮤테이션_NOT_APPLIED'], '· 미발생 오류코드', m['발생하지_않은_오류코드'])
"; then
    echo "  FAIL — selftest 출력을 읽지 못했다(오염 또는 형식 변경). 아래 앞 5줄:"
    head -5 /tmp/agora-selftest.$$
    rc=1
  fi
else
  echo "  FAIL — selftest rc != 0"; tail -20 /tmp/agora-selftest.$$; rc=1
fi
rm -f /tmp/agora-selftest.$$

echo "== F-1 재현 시험(codex 2R·4R·5R·6R 판정문 1:1) =="
# ★**시험을 쓴 것과 시험이 도는 것은 다른 말이다.** 이 저장소가 그 차이로 두 번 다쳤다
#   (미배선 함수 전수조사 2026-08-26 · 「구현했다 ≠ 배선됐다」). 파일만 두면 아무도 안 돌린다.
# ★pytest 없이도 돈다(이 기계의 시스템 python3 는 PEP 668 로 --user 설치가 막혀 있다) —
#   같은 파일이 자체 러너를 갖고 있어 **검사기 부재로 안 재는 일**이 생기지 않는다.
if python3 tests/test_f1_r2_codex.py >/tmp/agora-f1r2.$$ 2>&1; then
  tail -1 /tmp/agora-f1r2.$$ | sed 's/^/  /'
else
  echo "  FAIL — 아래 출력 확인"; grep -E "^  FAIL" /tmp/agora-f1r2.$$ | head -10; rc=1
fi
rm -f /tmp/agora-f1r2.$$

echo "== codex 0.1.4 사후 1R 재현 시험(판정문 7건 1:1) =="
# ★같은 이유로 게이트에 싣는다: **시험을 쓴 것과 시험이 도는 것은 다른 말이다.**
#   파일만 두면 아무도 안 돌린다(이 저장소가 그 차이로 두 번 다쳤다).
if python3 tests/test_codex_1r_seal.py >/tmp/agora-codex1r.$$ 2>&1; then
  tail -1 /tmp/agora-codex1r.$$ | sed 's/^/  /'
else
  echo "  FAIL — 아래 출력 확인"; grep -E "^  FAIL" /tmp/agora-codex1r.$$ | head -10; rc=1
fi
rm -f /tmp/agora-codex1r.$$

echo "== 공백 위생(우리가 건드린 줄만) =="
# ★codex 4R LOW 가 이 자리에서 났다: `git diff --check` 가 exit 2 였는데 **아무 게이트도 안 봤다.**
#   손으로 재는 검사는 안 재게 된다 — 그래서 도구에 싣는다.
# ★검사 논리는 `tests/ws_hygiene.sh` 로 뺐다(codex 5R LOW): 인라인 함수는 **따로 잴 수 없어서**
#   「미측정을 통과로 세지 않는다」가 주장으로만 남는다. 독립 스크립트라야 시험이 그 주장을 실측한다.
bash tests/ws_hygiene.sh || rc=1

echo "== 결과: $([ $rc -eq 0 ] && echo PASS || echo FAIL) =="
exit $rc
