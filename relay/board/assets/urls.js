// urls.js — 주소를 만드는 유일한 자리.
//
// ★왜 한 곳인가: 최종 주소 모양은 `/rooms/:id` 인데(브리프 §2), 그 주소가 서려면
//   정적 자산 라우팅 설정(`wrangler.jsonc` 의 not_found_handling)이 필요하고 **그 파일은 이 작업의 경계 밖**이다.
//   그래서 v1 은 쿼리 인자로 두고, 설정이 서면 아래 상수 하나를 뒤집는다.
//   (BOARD.md §9 · 성찰 F-7 — 어휘 미결과 주소 미결은 **해소 시점이 달라서** 파일을 나눴다)

export const PRETTY_URLS = false;   // ← 정적 라우팅이 서면 true

export function roomUrl(roomId) {
  return PRETTY_URLS
    ? `/rooms/${encodeURIComponent(roomId)}`
    : `room.html?id=${encodeURIComponent(roomId)}`;
}

export function lobbyUrl()   { return PRETTY_URLS ? '/' : 'index.html'; }
export function archiveUrl() { return PRETTY_URLS ? '/archive' : 'archive.html'; }

// 지금 보고 있는 방의 id — 두 주소 모양 모두에서 읽는다.
export function currentRoomId() {
  const q = new URLSearchParams(location.search).get('id');
  if (q) return q;
  const m = location.pathname.match(/\/rooms\/([^/?#]+)$/);
  return m ? decodeURIComponent(m[1]) : null;
}

// 설치 안내 — 문구는 master 확정(2026-09-05), 주소는 06 §4 J3.
export const INSTALL_URL = 'https://jarvis-install.godmeyou.kr/';
