// lobby.js — 로비 화면 배선.
import { listRooms, ApiError } from './api.js';
import { roomCard, emptyLine, errorLine, el, clear, fmtDateTime } from './render.js';

const mount = document.getElementById('board');

function failText(e) {
  if (e instanceof ApiError && e.kind === 'http') return `방 목록을 가져오지 못했습니다 (서버 응답 ${e.status}). 잠시 뒤 새로 고쳐 주세요.`;
  if (e instanceof ApiError && e.kind === 'shape') return '방 목록의 응답을 읽지 못했습니다. 잠시 뒤 새로 고쳐 주세요.';
  return '방 목록을 가져오지 못했습니다. 연결을 확인하고 새로 고쳐 주세요.';
}

async function main() {
  clear(mount);
  mount.appendChild(el('p', { className: 'note note-empty', text: '방 목록을 불러오는 중입니다…' }));
  let result;
  try {
    result = await listRooms({ closed: false });
  } catch (e) {
    clear(mount);
    // ★「못 가져왔다」는 「비었다」와 다른 문장·다른 자리에서 그린다(BOARD.md §6-2).
    mount.appendChild(errorLine(failText(e)));
    return;
  }
  clear(mount);
  if (result.items.length === 0) {
    mount.appendChild(emptyLine('지금 열린 방이 없습니다. 새 방이 열리면 여기에 나타납니다.'));
  } else {
    const ul = el('ul', { className: 'list' });
    for (const room of result.items) {
      ul.appendChild(el('li', {}, [roomCard(room)]));
    }
    mount.appendChild(ul);
    if (result.nextCursor) {
      mount.appendChild(el('p', { className: 'note note-partial',
        text: '방이 더 있습니다 — 이 화면은 최근 갱신된 순서로 앞부분만 보여 줍니다.' }));
    }
  }
  const checked = fmtDateTime(new Date().toISOString());
  if (checked !== null) {
    mount.appendChild(el('p', { className: 'note note-empty', text: `마지막으로 확인한 시각 ${checked} · 이 화면은 스스로 새로 고치지 않습니다.` }));
  }
}

main();
