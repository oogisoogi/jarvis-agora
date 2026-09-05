// room.js — 방 화면 배선.
//
// ★이 화면은 **두 호출**에 걸쳐 있다(상태 머리 · 발언). 한쪽이 죽어도 다른 쪽은 그린다 —
//   한쪽 성공이 다른 쪽 실패를 감추지 않는다(성찰 F-1).
//
// ★★두 구획은 **그리는 동안 `aria-busy` 를 세운다.** 이 화면은 로비·아카이브와 달리
//   「불러오는 중」 문구를 두지 않아서, 그것이 없으면 **아직 아무것도 안 온 화면과 다 온 화면이
//   똑같아 보인다.** 실제로 라이브(왕복 약 0.6초)에서 스크린샷 계기가 도착 전 화면을 찍어
//   「방에 글이 없다」는 거짓 결과를 냈다(2026-09-06 실측). 화면이 스스로 상태를 말해야 계기가 기다린다.
import { getRoom, listEvents, ApiError } from './api.js';
import { currentRoomId } from './urls.js';
import { TYPE, CLOSE_REASON, NOUN, labelOf } from './vocab.js';
import {
  el, clear, field, stateChip, signatureBadge, badgeNode, deadlineText, fmtDateTime,
  flow, resolutionBox, errorLine, emptyLine, partialLine, hiddenSummaryLine,
} from './render.js';
import { verdictBadgesOn } from './flags.js';
import { parsePost } from './parse.js';
import { isHidden } from './render.js';

const titleEl  = document.getElementById('room-title');
const statusEl = document.getElementById('room-status');
const resEl    = document.getElementById('room-resolution');
const flowEl   = document.getElementById('room-flow');

const roomId = currentRoomId();

// ★의장은 방 상태 호출에서 오고, 권고 상자 판정에 필요하다.
//   두 호출은 서로를 기다리지 않으므로(F-1 독립 구획) 약속 하나로 건네준다.
//   상태 호출이 **실패하면 null 이 건너간다** ⇒ 권고 상자는 안 뜬다(모를 때는 안 올린다).
let chairResolved;
const chairPromise = new Promise((resolve) => { chairResolved = resolve; });

function httpText(e, what) {
  if (e instanceof ApiError && e.kind === 'http' && e.status === 404) {
    return `${what}을(를) 찾지 못했습니다. 주소를 확인해 주세요.`;
  }
  if (e instanceof ApiError && e.kind === 'http') return `${what}을(를) 가져오지 못했습니다 (서버 응답 ${e.status}).`;
  return `${what}을(를) 가져오지 못했습니다. 연결을 확인하고 새로 고쳐 주세요.`;
}

/**
 * 제목은 genesis 이벤트의 payload.title 에서 읽는다.
 * ★**가려진 항목은 건너뛴다.** 안 그러면 서버가 격리했거나 경합에 밀어낸 위조 genesis 의 제목이
 *   방 제목과 브라우저 탭 제목이 된다 — 「가린 글의 본문은 꺼내지 않는다」가 제목 칸으로 우회된다.
 *   (이 화면에서 가림 규율이 새는 자리는 본문만이 아니다 · 이종 검토 HIGH 지적 2026-09-06)
 */
function titleFromEvents(items) {
  for (const item of items) {
    if (isHidden(item)) continue;
    const { event } = parsePost(typeof item.body === 'string' ? item.body : '');
    if (event && event.kind === 'genesis') {
      const t = event.payload && event.payload.title;
      if (typeof t === 'string' && t.trim() !== '') return t;
    }
  }
  return null;
}

async function drawStatus() {
  clear(statusEl);
  statusEl.setAttribute('aria-busy', 'true');
  let room;
  try {
    room = await getRoom(roomId);
  } catch (e) {
    chairResolved(null);
    // ★배지는 자동으로 꺼진다 — 서버가 말한 적 없으면 안 그린다(성찰 F-2).
    statusEl.appendChild(errorLine(httpText(e, `${NOUN.room} 상태`)));
    statusEl.removeAttribute('aria-busy');   // 오류도 「다 그린 상태」다 — 안 내리면 계기가 영영 기다린다
    return;
  }
  chairResolved(typeof room.chair === 'string' ? room.chair : null);

  const chips = el('div', { className: 'chips' });
  const typeLabel = labelOf(TYPE, room.type);
  if (typeLabel !== null) chips.appendChild(el('span', { className: 'chip chip-type', text: typeLabel }));
  const st = stateChip(room.state);
  if (st) chips.appendChild(st);
  const badge = badgeNode(signatureBadge(room));
  if (badge) chips.appendChild(badge);
  if (chips.childNodes.length) statusEl.appendChild(chips);

  const fields = el('div', { className: 'fields' });
  const add = (n) => { if (n) fields.appendChild(n); };
  add(field('의장', room.chair));
  add(field('마감', deadlineText(room.deadline), { attrs: { title: room.deadline || null } }));
  add(field('글 수', typeof room.events_counted === 'number' ? `${room.events_counted}건` : null));
  if (fields.childNodes.length) statusEl.appendChild(fields);

  statusEl.removeAttribute('aria-busy');
  if (room.closed === true) {
    const reason = labelOf(CLOSE_REASON, room.close_reason);
    const at = fmtDateTime(room.closed_at);
    const parts = ['이 방은 끝났습니다'];
    if (reason !== null) parts.push(reason);
    if (at !== null) parts.push(at);
    statusEl.appendChild(el('div', { className: 'ribbon', text: parts.join(' · ') }));
  }
}

async function drawFlow() {
  clear(flowEl);
  clear(resEl);
  flowEl.setAttribute('aria-busy', 'true');
  let result;
  try {
    result = await listEvents(roomId);
  } catch (e) {
    flowEl.appendChild(errorLine(httpText(e, '발언')));
    flowEl.removeAttribute('aria-busy');
    return;
  }

  const t = titleFromEvents(result.items);
  if (t !== null) { titleEl.textContent = t; document.title = `아고라 — ${t}`; }

  if (result.items.length === 0) {
    flowEl.appendChild(emptyLine('아직 올라온 글이 없습니다.'));
    flowEl.removeAttribute('aria-busy');
    return;
  }

  const chair = await chairPromise;
  const showVerdict = verdictBadgesOn();
  const { node, resolution, hiddenReasons } = flow(result.items, chair, { showVerdict });
  const box = resolutionBox(resolution);
  if (box) resEl.appendChild(box);
  flowEl.appendChild(node);

  // 판정 배지를 켠 화면에서만 「무엇을 왜 가렸는지」를 세어 알린다(내용은 안 펼친다).
  if (showVerdict) {
    const summary = hiddenSummaryLine(hiddenReasons);
    if (summary) flowEl.appendChild(summary);
  }

  // ★두 미완주는 **서로 다른 문장**이다(성찰 F-3·F-4).
  if (result.truncated) {
    flowEl.appendChild(partialLine('글이 아주 많아 앞부분만 보여 줍니다.'));
  }
  if (result.incomplete) {
    flowEl.appendChild(errorLine('이후 발언을 더 가져오지 못했습니다 — 여기까지가 전부가 아닙니다. 새로 고쳐 주세요.'));
  }
  flowEl.removeAttribute('aria-busy');
}

if (roomId === null) {
  statusEl.appendChild(errorLine('어느 방인지 알 수 없습니다. 로비에서 방을 골라 주세요.'));
} else {
  drawStatus();
  drawFlow();
}
