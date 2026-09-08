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
  // ★내장 이름(__proto__·constructor …)이 값으로 오면 표에 없는데도 무언가가 잡힌다.
  //   「표에 있는가」는 **표가 직접 가진 칸인가**로 물어야 한다.
  const hit = Object.prototype.hasOwnProperty.call(table, key) ? table[key] : undefined;
  if (hit === undefined) return String(key);
  return typeof hit === 'string' ? hit : hit.label;
}

export function toneOf(key) {
  const hit = STATE[key];
  return hit ? hit.tone : 'quiet';
}

/* ── 서버 판정(relay verdict) ────────────────────────────────────────
 * ★값 집합은 **발명하지 않는다** — 릴레이 계약(docs/RELAY.md §3-5·§5)과 그 구현
 *   (relay/src/lib/reducer.ts 의 사유 상수)에서 그대로 옮긴 것이다.
 *   1단 수집 격리 6종 · 3단 전이 격리 9종 · 2단 경합 stale 2종 = 17종.
 *   ⚠표에 없는 사유가 오면 **그 값을 그대로** 적는다(labelOf 규칙) — 모르는 것을 번역하지 않는다.
 */
export const VERDICT = {
  valid:       { label: '반영됨', tone: 'live' },
  quarantined: { label: '격리',   tone: 'quiet' },
  stale:       { label: '밀림',   tone: 'quiet' },
};

export const VERDICT_REASON = {
  // 1단 — 수집에서 거른 것
  unparseable:    '읽을 수 없는 형식',
  oversize:       '너무 큼',
  schema:         '서식이 맞지 않음',
  thread_mismatch:'다른 방의 글',
  signature:      '서명 확인 실패',
  replay:         '이미 올라온 글',
  // 3단 — 전이에서 거른 것
  out_of_round:      '라운드 밖 발언',
  counter_required:  '반론 라운드인데 반론이 없음',
  permission:        '그 일을 할 자격이 없음',
  kind_not_allowed:  '이 방에서 쓸 수 없는 종류',
  bad_transition:    '지금 단계에서 올 수 없는 글',
  unknown_target:    '가리키는 글을 찾지 못함',
  budget_exceeded:   '발언 한도를 넘음',
  after_close:       '끝난 뒤에 온 글',
  stale_expected_state: '낡은 상태를 보고 쓴 글',
  // 2단 — 경합에서 밀린 것
  lost_race:   '같은 자리를 두고 겨뤄 밀림',
  unreachable: '사슬에 닿지 않음',
};

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
