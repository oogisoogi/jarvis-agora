#!/bin/sh
# 공개 표현 규약 검사 — 금칙어가 **산문에 새는 것**을 막는다.
#
# ★따로 떼어 둔 이유: 게이트 안에 인라인으로 있으면 **이 검사 자체를 시험할 수단이 없다.**
#   검사기가 고장나면 그 출력은 아무것도 증명하지 않는데, 그때 고장을 알아챌 방법이 없다.
#   ⇒ 파일 목록을 인자로 받게 해서 시험이 임시 파일 둘로 양방향을 잴 수 있게 한다.
#
# 쓰는 법:
#   tests/public_terms.sh              # 저장소 전체(git 이 추적하거나 추적할 파일)
#   tests/public_terms.sh <파일>...     # 준 파일만(시험이 이렇게 부른다)
#
# ★**줄 단위 예외**(master 판정 2026-09-11): 줄 끝에 `public-terms: allow` 표식이 붙은 줄만 뺀다.
#   제품이 **실제로 읽어야 하는 파일 경로**에 그 낱말이 들어 있는 경우가 있고, 바꿔 적으면 못 읽는다.
#   ⛔글자를 쪼개 검사를 피하는 것은 금지다 — 미탐과 구별되지 않는 억제다.
#   ⇒ 그래서 **적어 두고 넘긴다**: 뺀 줄은 파일:줄번호로 **출력한다**(보이는 억제).
#   ★표식 없는 새 등장은 종전대로 실패다 — 이 문은 「적은 만큼만」 열린다.
set -u
cd "$(dirname "$0")/.." || exit 2

TERMS_FILE="tests/forbidden-terms.txt"
EXCLUDED="$TERMS_FILE"
ALLOW_MARK="public-terms: allow"

if [ ! -s "$TERMS_FILE" ]; then
  echo "  FAIL — 금칙어 목록이 비었거나 없다($TERMS_FILE). 검사가 무의미하므로 통과시키지 않는다."
  exit 3
fi
echo "  목록 $(grep -c . "$TERMS_FILE") 개 · 검사 제외 1건: $EXCLUDED"
echo "  줄 예외 표식: ${ALLOW_MARK}(붙은 줄은 아래에 파일:줄번호로 찍는다)"

if [ "$#" -gt 0 ]; then
  list() { for f in "$@"; do echo "$f"; done; }
else
  list() { git ls-files --cached --others --exclude-standard; }
fi

hits=0
allowed=0
for f in $(list "$@"); do
  [ "$f" = "$EXCLUDED" ] && continue
  [ -f "$f" ] || continue
  found=$(grep -n -f "$TERMS_FILE" -- "$f" 2>/dev/null) || continue
  n=0
  for_each_line=$(printf '%s\n' "$found")
  OLDIFS=$IFS; IFS='
'
  for line in $for_each_line; do
    case "$line" in
      *"$ALLOW_MARK"*) echo "  줄 예외 $f:${line%%:*}"; allowed=$((allowed + 1)) ;;
      *) n=$((n + 1)) ;;
    esac
  done
  IFS=$OLDIFS
  if [ "$n" -gt 0 ]; then
    echo "  위반 $f: ${n}건"
    hits=$((hits + n))
  fi
done
echo "  합계 ${hits}건 (줄 예외 ${allowed}건 — 위에 전부 찍었다)"
[ "$hits" -eq 0 ] || exit 1
exit 0
