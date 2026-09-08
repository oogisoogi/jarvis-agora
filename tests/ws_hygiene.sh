#!/usr/bin/env bash
# 공백 위생 검사 — **우리가 건드린 줄만** 본다(작업트리 · staged · merge-base..HEAD).
#
# ★왜 파일로 뺐나: codex 5R LOW 가 이 검사의 **종료 코드 처리**를 짚었다. 게이트 안에 인라인
#   함수로 두면 그 논리를 **따로 재는 수단이 없다** — 「미측정을 통과로 세지 않는다」는 주장이
#   주장으로만 남는다. 독립 스크립트가 되면 시험이 없는 ref 를 넣어 그 주장을 실측할 수 있다.
# ★rc 규약: 0 = 깨끗 · 1 = 위반 또는 **측정 실패**(둘 다 게이트 실패) — 다만 출력은 가른다.
# ⚠`git diff --check` 실측: 0(깨끗) · 2(위반) · 128(ref 없음). 숫자에 기대지 않고
#   **출력이 비었는데 rc 가 0이 아니면 측정 실패**로 가른다 — git 이 코드를 바꿔도 이 판별은 산다.
set -u
cd "$(dirname "$0")/.." || exit 2

rc=0
check() {   # $1 = 사람이 읽는 이름 · 나머지 = git diff 인자
  label="$1"; shift
  # ⚠stderr 를 stdout 에 **합치지 않는다**: 합치면 「위반」과 「측정 실패」가 같은 칸에 들어가
  #   구별이 사라진다. 이 검사가 고치려는 병이 정확히 그것이다.
  err=$(mktemp "${TMPDIR:-/tmp}/agora-ws.XXXXXX")
  out=$(git diff --check "$@" 2>"$err"); grc=$?
  if [ "$grc" -eq 0 ] && [ -z "$out" ]; then
    :
  elif [ -n "$out" ]; then
    echo "  위반 [$label] (git rc $grc):"; echo "$out" | sed 's/^/    /' | head -10
    rc=1
  else
    echo "  FAIL [$label] — git diff 가 rc $grc 로 죽었다(**미측정**·통과 아님):"
    sed 's/^/    /' "$err" | head -5
    rc=1
  fi
  rm -f "$err"
}

if [ "$#" -gt 0 ]; then
  # 시험용 — 인자를 그대로 한 칸 검사한다(「없는 ref 를 넣으면 실패하는가」를 실측하는 문).
  check "인자 지정: $*" "$@"
  exit $rc
fi

check "작업트리"
check "staged" --cached
base=$(git merge-base HEAD main 2>/dev/null)
if [ -n "$base" ]; then
  check "커밋 $base..HEAD" "$base..HEAD"
else
  # ★못 잰 칸은 통과가 아니다 — 주석만 그렇게 적고 rc 를 안 올리면 그 주석이 거짓이다
  #   (codex 5R LOW 가 이 자기모순을 짚었다).
  echo "  FAIL — main 을 못 찾아 커밋 범위 **미측정**(통과 아님 · 작업트리·staged 만 쟀다)"
  rc=1
fi
[ "$rc" -eq 0 ] && echo "  clean"
exit $rc
