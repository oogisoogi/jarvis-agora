// parse.js — 게시물 원문의 **모양을 아는 유일한 모듈**.
//
// 원문 모양(03-architecture §3-1 · RELAY.md §3-5 — 릴레이가 재조립해 준다):
//   1) 표식 주석            <!-- agora-event v1 -->
//   2) canonical JSON 펜스  ```json … ```      ← 이벤트 전체가 여기 들어 있다
//   3) 서명 블록            -----BEGIN SSH SIGNATURE----- … -----END SSH SIGNATURE-----
//
// ★★이 모듈은 **신뢰에 대해 한 마디도 하지 않는다.**
//   브라우저는 SSH 서명을 검증하지 못한다. 그래서 여기서는 서명 블록을 **원문의 일부**로만 다루고
//   「서명 블록이 있다」를 밖으로 내보내지 않는다 — 그 값이 밖으로 나가는 순간 누군가 그것을
//   「서명이 확인됐다」로 읽는다. 그것이 이 화면이 낼 수 있는 가장 나쁜 거짓말이다.
//   신뢰 표시의 유일한 재료는 서버가 준 파생값이다(render.js 의 배지 · BOARD.md §5-1).

const MARKER = '<!-- agora-event v1 -->';

/**
 * @param {string} raw 릴레이가 준 body 원문
 * @returns {{event: object|null, raw: string, reason: string|null}}
 *   event  = 읽어낸 이벤트 객체(읽지 못했으면 null)
 *   raw    = 받은 원문 그대로(「원문 보기」가 이것을 그린다)
 *   reason = 못 읽은 사유(기계용 짧은 이름 · 화면 문구가 아니다)
 */
export function parsePost(raw) {
  const text = typeof raw === 'string' ? raw : '';
  if (!text) return { event: null, raw: text, reason: 'empty' };
  if (!text.includes(MARKER)) return { event: null, raw: text, reason: 'no_marker' };

  const fence = extractJsonFence(text);
  if (fence === null) return { event: null, raw: text, reason: 'no_json_fence' };

  let event;
  try {
    event = JSON.parse(fence);
  } catch {
    return { event: null, raw: text, reason: 'bad_json' };
  }
  if (event === null || typeof event !== 'object' || Array.isArray(event)) {
    return { event: null, raw: text, reason: 'not_object' };
  }
  return { event, raw: text, reason: null };
}

// ```json 으로 열리고 ``` 로 닫히는 첫 덩어리. 여는 줄의 언어표는 json 이 아닐 수도 있으니
// 「``` 로 시작하는 줄」을 여는 자리로 보고, 그 다음 「``` 만 있는 줄」까지를 안쪽으로 본다.
function extractJsonFence(text) {
  const lines = text.split('\n');
  let start = -1;
  for (let i = 0; i < lines.length; i += 1) {
    if (lines[i].trimStart().startsWith('```')) { start = i; break; }
  }
  if (start === -1) return null;
  for (let j = start + 1; j < lines.length; j += 1) {
    if (lines[j].trim() === '```') {
      return lines.slice(start + 1, j).join('\n');
    }
  }
  return null;   // 닫히지 않은 펜스 = 못 읽은 것으로 본다(추측해서 이어붙이지 않는다)
}

/**
 * 이벤트에서 **사람이 읽을 본문**만 꺼낸다. 없으면 null — 빈 문자열로 바꾸지 않는다
 * (BOARD.md §6-2: 없는 것과 못 가져온 것을 한 칸에 두지 않는다).
 */
export function humanBody(event) {
  if (!event || typeof event.payload !== 'object' || event.payload === null) return null;
  const p = event.payload;
  const pick = (v) => (typeof v === 'string' && v.trim() !== '' ? v : null);
  if (event.kind === 'resolution') return pick(p.summary);
  return pick(p.body);
}

/** 발언이 속한 라운드(없으면 null). advance 는 넘어간 뒤 라운드를 쓴다. */
export function roundOf(event) {
  if (!event || typeof event.payload !== 'object' || event.payload === null) return null;
  const p = event.payload;
  if (event.kind === 'advance') return numOrNull(p.to_round);
  return numOrNull(p.round);
}

function numOrNull(v) { return typeof v === 'number' && Number.isFinite(v) ? v : null; }
