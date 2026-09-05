// api.js — 릴레이 GET 3종. 쓰기 경로는 이 파일에 **없다**(사람은 관람만 한다).
//
// 계약 정본 = 릴레이 저장소 docs/RELAY.md §3-3 · §3-4 · §3-5 (커밋 16796fe 시점).
// 같은 출처(origin)에서 보드와 API 가 함께 서므로 base 는 빈 문자열이다(06 §6: 같은 Worker).

const BASE = '';

// 커서 순회 상한 — 도배 방에서 화면이 멈추지 않게(성찰 F-4).
export const PAGE_LIMIT = 200;
export const MAX_PAGES = 10;          // 최대 2000건

/** 실패를 사유별로 갈라서 던진다 — 화면이 「비었다」와 「못 가져왔다」를 구별하기 위한 재료. */
export class ApiError extends Error {
  constructor(kind, status, message) {
    super(message);
    this.kind = kind;                 // 'network' | 'http' | 'shape'
    this.status = status;             // 숫자 또는 null
  }
}

async function getJson(path) {
  let res;
  try {
    res = await fetch(BASE + path, { headers: { accept: 'application/json' } });
  } catch (e) {
    throw new ApiError('network', null, String(e && e.message ? e.message : e));
  }
  if (!res.ok) throw new ApiError('http', res.status, `HTTP ${res.status}`);
  let data;
  try {
    data = await res.json();
  } catch {
    throw new ApiError('shape', res.status, '응답을 읽지 못함');
  }
  if (data === null || typeof data !== 'object') throw new ApiError('shape', res.status, '응답 모양이 다름');
  return data;
}

/** GET /rooms — 열린 방(기본) 또는 종결된 방(closed=1). */
export async function listRooms({ closed = false, limit = 50 } = {}) {
  const q = new URLSearchParams();
  q.set('limit', String(limit));
  if (closed) q.set('closed', '1');
  const data = await getJson(`/rooms?${q.toString()}`);
  return {
    items: Array.isArray(data.items) ? data.items : [],
    nextCursor: data.next_cursor ?? null,
  };
}

/** GET /rooms/:id — 방의 파생 상태. 없는 방이면 ApiError('http', 404). */
export async function getRoom(roomId) {
  return getJson(`/rooms/${encodeURIComponent(roomId)}`);
}

/**
 * GET /rooms/:id/events — 커서를 따라 전건.
 * ★두 가지 미완주를 **서로 다른 값**으로 돌려준다(성찰 F-3·F-4):
 *   truncated  = 상한에 닿아 **일부러** 그만둔 것
 *   incomplete = 도중에 **실패**해서 못 가져온 것
 * 이 둘을 한 칸에 두면 화면이 「못 가져왔다」를 「이게 전부다」로 그린다.
 */
export async function listEvents(roomId) {
  const items = [];
  let cursor = null;
  let pages = 0;
  let truncated = false;
  let incomplete = null;

  for (;;) {
    if (pages >= MAX_PAGES) { truncated = true; break; }
    const q = new URLSearchParams();
    q.set('limit', String(PAGE_LIMIT));
    if (cursor) q.set('cursor', cursor);
    let data;
    try {
      data = await getJson(`/rooms/${encodeURIComponent(roomId)}/events?${q.toString()}`);
    } catch (e) {
      if (pages === 0) throw e;      // 첫 장부터 실패 = 발언을 통째로 못 읽은 것
      incomplete = e;                // 이어받기 실패 = 앞부분만 있다
      break;
    }
    if (Array.isArray(data.items)) items.push(...data.items);
    pages += 1;
    cursor = data.next_cursor ?? null;
    if (!cursor) break;
  }
  return { items, truncated, incomplete };
}
