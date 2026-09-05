// vocab.js — 화면에 나가는 **상태·종류 어휘**가 사는 유일한 자리.
//
// ★왜 한 곳인가: 화면 어휘 「방 vs 부스」가 아직 미결이다(06 §10-4).
//   낱말이 파일마다 흩어져 있으면 결정이 왔을 때 「전부 찾았는가」를 아무도 증명 못 한다.
//   ⚠경계: 여기 사는 것은 **값에서 낱말로 옮기는 표**뿐이다.
//     화면의 산문(소개 3문장·하단 고정 문구·오류 문구)은 HTML 에 있다 — 두 자리인 것을 알고 나눈 것이다.
//     (BOARD.md §7 · 성찰 F-7)

export const NOUN = {
  room: '방',            // ← 결정이 「부스」로 오면 이 한 줄
  rooms: '방',
  lobby: '로비',
  archive: '아카이브',
};

// 스레드 종류 — 03-architecture §2-2
export const TYPE = {
  problem: '문제',
  knowhow: '노하우',
  debate: '토론',
};

// 단계 — 03-architecture §6 이 정본. BOARD.md §4-2 표와 같아야 한다.
export const STATE = {
  open:     { label: '열림',            tone: 'live' },
  solved:   { label: '해결됨',          tone: 'live' },
  stale:    { label: '마감 지남',       tone: 'quiet' },
  r0:       { label: '발제',            tone: 'live' },
  r1:       { label: '1차 토론',        tone: 'live' },
  r2:       { label: '반론',            tone: 'live' },
  r3:       { label: '정리',            tone: 'live' },
  resolved: { label: '권고 나옴',       tone: 'live' },
  expired:  { label: '멈춤(마감 지남)', tone: 'quiet' },
  closed:   { label: '종결',            tone: 'quiet' },
};

// 종결 사유 — 03-architecture §2-2 close.reason
export const CLOSE_REASON = {
  solved:     '해결됨',
  unresolved: '결론 없이 종결',
  superseded: '다른 글로 대체됨',
  aborted:    '운영자가 중단',
  expired:    '마감 지나 종결',
};

// 이벤트 종류 — 03-architecture §2-2 kind 9종.
//   flow: 'speech' 발언 카드 · 'divider' 가는 구분 줄 · 'resolution' 권고(위 상자로 올림)
//   'hidden' 기본 화면에서 접는다(v1 범위 밖 — 06 §5 가 투표 표시를 v1.1로 미뤘다)
export const KIND = {
  genesis:         { label: '발제',        flow: 'speech' },
  post:            { label: '발언',        flow: 'speech' },
  advance:         { label: '라운드 넘김', flow: 'divider' },
  resolution:      { label: '권고',        flow: 'resolution' },
  answer_selected: { label: '해결 표시',   flow: 'divider' },
  close:           { label: '종결',        flow: 'divider' },
  delegate_chair:  { label: '의장 넘김',   flow: 'divider' },
  abort:           { label: '운영자 중단', flow: 'divider' },
  vote:            { label: '투표',        flow: 'hidden' },
};

// ★표에 없는 값은 **그 값을 그대로** 적는다. 모르는 것을 아는 것처럼 번역하지 않고,
//   빈칸으로 삼키지도 않는다(BOARD.md §4-1·§4-2 마지막 줄).
export function labelOf(table, key) {
  if (key === null || key === undefined || key === '') return null;
  const hit = table[key];
  if (hit === undefined) return String(key);
  return typeof hit === 'string' ? hit : hit.label;
}

export function toneOf(key) {
  const hit = STATE[key];
  return hit ? hit.tone : 'quiet';
}

/**
 * 한국어 조사 「(으)로」를 낱말에 맞게 고른다.
 * 받침이 없거나 받침이 ㄹ 이면 「로」, 그 밖에는 「으로」.
 * ★「(으)로」처럼 두 형태를 괄호로 얼버무리면 화면이 사람 글이 아니게 된다.
 */
export function euro(word) {
  const s = String(word);
  const tail = s[s.length - 1];
  // ★숫자로 끝나면 **읽는 소리**의 받침을 본다: 0 영·3 삼·6 육 = 받침 있음 → 「으로」.
  //   1 일·7 칠·8 팔 은 받침이 ㄹ 이라 「로」다(ㄹ 받침은 「로」를 쓴다). 나머지는 받침이 없다.
  if (/[0-9]/.test(tail)) return /[036]/.test(tail) ? '으로' : '로';
  const last = s.charCodeAt(s.length - 1);
  if (Number.isNaN(last) || last < 0xac00 || last > 0xd7a3) return '로';   // 한글도 숫자도 아니면 「로」
  const jong = (last - 0xac00) % 28;
  return jong === 0 || jong === 8 ? '로' : '으로';   // 0 = 받침 없음 · 8 = ㄹ
}
