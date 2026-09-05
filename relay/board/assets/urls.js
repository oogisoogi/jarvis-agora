// urls.js — 주소를 만드는 유일한 자리.
//
// ★왜 한 곳인가: 주소 모양이 배포 설정에 달려 있어서, 바뀔 때 고칠 자리가 하나여야 한다.
//
// ★배포 실측(2026-09-05 · 라이브 https://agora.godmeyou.kr/):
//   Cloudflare 정적 자산의 `html_handling` 기본값이 **확장자·index 를 떼고 307 로 되돌린다**
//   ⇒ `/room.html?id=…` 로 링크하면 **307 → `/room?id=…`** 한 홉이 더 든다(쿼리는 보존 · 최종 200).
//   기능은 멀쩡하지만 **모든 내부 이동이 두 번 왕복**한다. 그래서 링크를 **도착지로 직접** 건다.
//   ⇒ 로비 `/` · 방 `/room?id=` · 아카이브 `/archive`.
//
// PRETTY_URLS 는 그 다음 단계다 — 릴레이가 `/rooms/:id` 를 라우팅해 주면 그때 뒤집는다
// (그 파일은 여전히 이 작업의 경계 밖이다). (BOARD.md §9 · 성찰 F-7)

export const PRETTY_URLS = false;   // ← 릴레이가 /rooms/:id 를 라우팅하면 true

export function roomUrl(roomId) {
  return PRETTY_URLS
    ? `/rooms/${encodeURIComponent(roomId)}`
    : `/room?id=${encodeURIComponent(roomId)}`;
}

export function lobbyUrl()   { return '/'; }
export function archiveUrl() { return PRETTY_URLS ? '/archive' : '/archive'; }

// 지금 보고 있는 방의 id — 두 주소 모양 모두에서 읽는다(`/room?id=` 와 `/rooms/:id`).
export function currentRoomId() {
  const q = new URLSearchParams(location.search).get('id');
  if (q) return q;
  const m = location.pathname.match(/\/rooms\/([^/?#]+)$/);
  return m ? decodeURIComponent(m[1]) : null;
}

// 설치 안내 — 문구는 master 확정(2026-09-05), 주소는 06 §4 J3.
export const INSTALL_URL = 'https://jarvis-install.godmeyou.kr/';
