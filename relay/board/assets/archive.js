// archive.js — 아카이브 화면 배선.
//
// ★방 목록(GET /rooms)에는 **종결 사유·종결 시각·권고**가 없다(RELAY.md §3-3 실측).
//   그 셋은 방을 하나씩 열어야 나오므로 **앞 몇 개만** 열어 읽고, 나머지는 읽지 않는다 —
//   그리고 **읽지 않았다는 사실을 한 줄로 말한다.** 행마다 빈칸을 두면
//   「권고가 없는 방」과 「아직 안 읽은 방」이 구별되지 않는다(BOARD.md §6-2).
import { listRooms, listEvents, getRoom, ApiError } from './api.js';
import { archiveRow, resolutionEntry, emptyLine, errorLine, el, clear } from './render.js';
import { verdictBadgesOn } from './flags.js';

const PREVIEW_ROOMS = 8;
const mount = document.getElementById('board');

function failText(e) {
  if (e instanceof ApiError && e.kind === 'http') return `끝난 방 목록을 가져오지 못했습니다 (서버 응답 ${e.status}). 잠시 뒤 새로 고쳐 주세요.`;
  return '끝난 방 목록을 가져오지 못했습니다. 연결을 확인하고 새로 고쳐 주세요.';
}

/** 방을 열어 「권고 첫 줄 · 종결 사유 · 종결 시각」을 읽는다. 실패하면 아무것도 지어내지 않는다. */
async function openRoom(roomId) {
  // ★권고 첫 줄 판정에는 **의장**이 필요하다(의장이 낸 권고만 결론으로 친다) ⇒ 방 상태를 먼저 읽는다.
  const status = await getRoom(roomId).catch(() => null);
  const chair = status && typeof status.chair === 'string' ? status.chair : null;
  const found = await listEvents(roomId)
    .then((r) => resolutionEntry(r.items, chair))
    .catch(() => null);
  return { line: found ? found.line : null, verdict: found ? found.item : null, status };
}

async function main() {
  clear(mount);
  mount.appendChild(el('p', { className: 'note note-empty', text: '끝난 방을 불러오는 중입니다…' }));
  let result;
  try {
    result = await listRooms({ closed: true });
  } catch (e) {
    clear(mount);
    mount.appendChild(errorLine(failText(e)));
    return;
  }
  clear(mount);
  if (result.items.length === 0) {
    mount.appendChild(emptyLine('아직 끝난 방이 없습니다.'));
    return;
  }

  const showVerdict = verdictBadgesOn();
  const previewCount = Math.min(PREVIEW_ROOMS, result.items.length);
  const opened = await Promise.all(
    result.items.slice(0, previewCount).map((r) => openRoom(r.room_id)),
  );

  const ul = el('ul', { className: 'list' });
  result.items.forEach((room, i) => {
    const got = i < previewCount ? opened[i] : null;
    // 열어서 읽은 칸만 덧붙인다 — 못 읽었으면 덧붙이지 않는다(빈 값을 지어내지 않는다).
    const merged = got && got.status ? { ...room, ...got.status } : room;
    ul.appendChild(el('li', {}, [archiveRow(merged, got ? got.line : null, showVerdict ? (got ? got.verdict : null) : null)]));
  });
  mount.appendChild(ul);

  if (result.items.length > previewCount) {
    mount.appendChild(el('p', { className: 'note note-partial',
      text: `권고와 종결 사유는 최근 ${previewCount}개 방까지만 미리 보여 드립니다 — 나머지는 방을 열면 보입니다.` }));
  }
}

main();
