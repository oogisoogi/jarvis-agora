// render.js — 구조를 화면으로. **innerHTML 을 쓰지 않는다**(본문은 신뢰할 수 없는 콘텐츠다).
//
// 규율 셋(BOARD.md §5·§6 · 성찰 feed-in):
//  ① 서버가 안 준 칸은 **그리지 않는다** — 기본값 문구로 바꾸지 않는다(field() 한 곳을 지난다).
//  ② 신뢰 표시의 재료는 **서버 파생값뿐**이다 — 본문·서명 블록에서 신뢰를 읽지 않는다.
//  ③ 「비었다」·「못 가져왔다」·「일부러 안 가져왔다」는 **서로 다른 문장**이다.

import { TYPE, STATE, CLOSE_REASON, KIND, labelOf, toneOf, euro } from './vocab.js';
import { parsePost, humanBody, roundOf } from './parse.js';
import { roomUrl } from './urls.js';

/* ── 이름표 기본값 — **예외 2건이고 여기 전부 있다** ───────────────────
 * 칸(field)은 없으면 안 그린다. 그러나 **항목의 이름표**는 비면 누를 곳이 사라진다
 * (제목 없는 카드 = 링크 없는 카드 · 발신자 없는 발언 = 누구 말인지 없는 말).
 * 그래서 이 둘만 예외로 두고, 상수로 선언해 검사기가 **전수로 세어 출력**하게 한다.
 * 보이지 않는 예외는 미탐과 구별되지 않는다.
 */
const NAMELESS_ROOM = '(제목 없음)';
const NAMELESS_WHO = '(발신자 없음)';

/* ── 만들기 도구 ─────────────────────────────────────────────────── */

export function el(tag, opts = {}, children = []) {
  const node = document.createElement(tag);
  if (opts.className) node.className = opts.className;
  if (opts.text !== undefined && opts.text !== null) node.textContent = String(opts.text);
  if (opts.attrs) for (const [k, v] of Object.entries(opts.attrs)) {
    if (v !== null && v !== undefined) node.setAttribute(k, String(v));
  }
  for (const c of children) if (c) node.appendChild(c);
  return node;
}

/**
 * ★칸을 그리는 **유일한 경로**. 값이 없으면 아무것도 만들지 않고 null 을 돌려준다.
 *   여기 `?? '알 수 없음'` 같은 기본값을 넣는 순간 「값이 없다」와 「서버가 안 줬다」가 한 칸에 섞인다.
 *   검증(dev/verify.sh)이 그 기본값 패턴을 0건으로 지킨다.
 */
export function field(label, value, opts = {}) {
  if (value === null || value === undefined || value === '') return null;
  const wrap = el('div', { className: 'field' });
  wrap.appendChild(el('span', { className: 'field-k', text: label }));
  wrap.appendChild(el('span', { className: 'field-v', text: value, attrs: opts.attrs }));
  return wrap;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

/* ── 값 다듬기 ───────────────────────────────────────────────────── */

export function fmtDateTime(iso) {
  if (typeof iso !== 'string' || iso === '') return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString('ko-KR', {
    year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

/**
 * 마감은 **사실로만** 적는다 — 이것으로 단계를 다시 계산하지 않는다(성찰 F-5).
 * ★칸 이름이 이미 「마감」이므로 값에 다시 「마감」을 넣지 않는다(안 그러면 화면에 「마감 마감 지남」).
 */
export function deadlineText(iso) {
  const shown = fmtDateTime(iso);
  if (shown === null) return null;
  return new Date(iso).getTime() < Date.now() ? '지남' : shown;
}

/** 지문을 그린다면 앞 8자만(BOARD.md §6-3). */
export function shortFingerprint(fp) {
  if (typeof fp !== 'string' || fp === '') return null;
  return fp.length <= 8 ? fp : `${fp.slice(0, 8)}…`;
}

/* ── 신뢰 표시 — 서버가 말할 때만 ─────────────────────────────────── */

/**
 * @returns {{label:string, tone:'ok'|'quiet'}|null} null 이면 **배지를 그리지 않는다**.
 * ★두 칸이 없으면 「확인 안 됨」도 쓰지 않는다 — 「서버가 아니라고 했다」와
 *   「서버가 말한 적 없다」는 다른 사건이고, 화면 문구 하나로 합치면 구별이 사라진다.
 */
export function signatureBadge(roomStatus) {
  if (!roomStatus || typeof roomStatus !== 'object') return null;
  const ok = roomStatus.signature_all_ok;
  if (typeof ok !== 'boolean') return null;
  if (ok) return { label: '서명 확인됨', tone: 'ok' };
  const bad = roomStatus.signature_bad_count;
  const n = typeof bad === 'number' && Number.isFinite(bad) ? bad : null;
  // ★n 이 0 이면 수를 적지 않는다 — 「검증 안 됨 0건」은 「실패가 0건이니 안전하다」로 읽힌다.
  //   서버가 all_ok=false 라고 말한 이상 안전하지 않고, 그 모순된 0 을 화면이 대신 설명하지 않는다.
  return { label: n === null || n === 0 ? '검증 안 됨' : `검증 안 됨 ${n}건`, tone: 'quiet' };
}

export function badgeNode(badge) {
  if (!badge) return null;
  return el('span', { className: `badge badge-${badge.tone}`, text: badge.label });
}

export function stateChip(state) {
  const label = labelOf(STATE, state);
  if (label === null) return null;
  return el('span', { className: `chip chip-${toneOf(state)}`, text: label });
}

/* ── 어느 이벤트를 화면에서 빼고 어느 것을 접나 ───────────────────── */

/**
 * ★릴레이가 항목별 유효 칸을 주기 시작하면 **여기 한 곳**이 켜진다
 *   (master 판정 2026-09-05 = A 채택 · 그때까지는 이 두 줄이 언제나 거짓이라 아무것도 안 뺀다).
 */
export function isHidden(item) {
  if (!item || typeof item !== 'object') return false;
  if (item.valid === false) return true;
  if (item.quarantined === true) return true;
  return false;
}

/** 우리가 모르는 종류 · v1 범위 밖 종류(투표)는 지우지 않고 **접는다**. */
export function isFolded(event) {
  const kind = event && typeof event.kind === 'string' ? event.kind : null;
  if (kind === null) return true;
  const spec = KIND[kind];
  if (!spec) return true;
  return spec.flow === 'hidden';
}

/* ── 로비·아카이브 카드 ───────────────────────────────────────────── */

export function roomCard(room) {
  const card = el('article', { className: 'card' });
  const head = el('div', { className: 'card-head' });

  const link = el('a', { className: 'card-title', text: room.title || NAMELESS_ROOM,
                         attrs: { href: roomUrl(room.room_id) } });
  head.appendChild(link);

  const chips = el('div', { className: 'chips' });
  const typeLabel = labelOf(TYPE, room.type);
  if (typeLabel !== null) chips.appendChild(el('span', { className: 'chip chip-type', text: typeLabel }));
  const st = stateChip(room.state);
  if (st) chips.appendChild(st);
  if (chips.childNodes.length) head.appendChild(chips);
  card.appendChild(head);

  const meta = el('div', { className: 'fields' });
  const add = (n) => { if (n) meta.appendChild(n); };
  add(field('의장', room.chair));
  add(field('참가', typeof room.participants === 'number' ? `${room.participants}명` : null));
  add(field('마감', deadlineText(room.deadline), { attrs: { title: room.deadline || null } }));
  add(field('마지막 글', fmtDateTime(room.updated_at), { attrs: { title: room.updated_at || null } }));
  if (meta.childNodes.length) card.appendChild(meta);

  return card;
}

export function archiveRow(room, resolutionFirstLine) {
  const card = roomCard(room);
  const reason = labelOf(CLOSE_REASON, room.close_reason);
  const extra = el('div', { className: 'fields' });
  if (reason !== null) extra.appendChild(field('종결', reason));
  const closedAt = fmtDateTime(room.closed_at);
  if (closedAt !== null) extra.appendChild(field('종결 시각', closedAt, { attrs: { title: room.closed_at } }));
  if (extra.childNodes.length) card.appendChild(extra);
  if (resolutionFirstLine) {
    card.appendChild(el('p', { className: 'archive-resolution', text: resolutionFirstLine }));
  }
  return card;
}

/* ── 방 화면: 발언 흐름 ───────────────────────────────────────────── */

export function rawDetails(raw) {
  const d = el('details', { className: 'raw' });
  d.appendChild(el('summary', { text: '원문 보기' }));
  d.appendChild(el('pre', { className: 'raw-pre', text: raw }));
  return d;
}

function speechCard(event, raw) {
  const card = el('article', { className: 'speech' });
  const head = el('div', { className: 'speech-head' });
  head.appendChild(el('span', { className: 'speech-who', text: event.from || NAMELESS_WHO }));
  const when = fmtDateTime(event.ts);
  if (when !== null) head.appendChild(el('time', { className: 'speech-when', text: when, attrs: { datetime: event.ts } }));
  const kindLabel = labelOf(KIND, event.kind);
  if (kindLabel !== null && event.kind !== 'post') {
    head.appendChild(el('span', { className: 'chip chip-kind', text: kindLabel }));
  }
  card.appendChild(head);

  const body = humanBody(event);
  if (body !== null) {
    card.appendChild(el('p', { className: 'speech-body', text: body }));
  } else {
    card.appendChild(el('p', { className: 'speech-nobody', text: '이 글에서 읽을 본문을 찾지 못했습니다.' }));
  }
  card.appendChild(rawDetails(raw));
  return card;
}

function dividerLine(text) {
  return el('div', { className: 'divider' }, [el('span', { className: 'divider-text', text })]);
}

function foldedLine(raw, why) {
  const d = el('details', { className: 'raw folded' });
  d.appendChild(el('summary', { text: why }));
  d.appendChild(el('pre', { className: 'raw-pre', text: raw }));
  return d;
}

/**
 * 이 권고를 **공식 결론으로 올려도 되는가**.
 * ★kind 가 resolution 이라는 것만으로는 부족하다 — 이벤트 목록은 걸러지지 않은 채 오므로
 *   의장이 아닌 참가자가 낸 resolution 이 섞여 있을 수 있고, 그것을 상자에 올리면
 *   **이 화면이 남의 글을 방의 결론이라고 말하는 것**이 된다. 상태기계상 resolution 은 의장만 낸다.
 * ⛔의장을 모르면(방 상태를 못 읽었으면) **올리지 않는다** — 모를 때는 조용한 쪽이 안전하다.
 */
function isChairResolution(event, chair) {
  if (typeof chair !== 'string' || chair === '') return false;
  return event.kind === 'resolution' && event.from === chair;
}

/**
 * 발언 흐름을 그린다.
 * @param {Array} items 릴레이가 준 이벤트 항목
 * @param {string|null} chair 방의 의장(서버 파생값) — 없으면 권고 상자를 올리지 않는다
 * @returns {{node: DocumentFragment, resolution: {event:object, raw:string}|null}}
 */
export function flow(items, chair = null) {
  const frag = document.createDocumentFragment();
  let resolution = null;
  let lastRound = null;

  for (const item of items) {
    if (isHidden(item)) continue;                       // ← 릴레이가 유효 칸을 주면 여기서 빠진다
    const raw = typeof item.body === 'string' ? item.body : '';
    const { event } = parsePost(raw);

    if (event === null) {
      frag.appendChild(foldedLine(raw, '읽지 못한 기록 1건 — 원문 보기'));
      continue;
    }
    if (isFolded(event)) {
      frag.appendChild(foldedLine(raw, '이 화면에서 보여 주지 않는 기록 1건 — 원문 보기'));
      continue;
    }

    const spec = KIND[event.kind];
    const r = roundOf(event);
    if (r !== null && r !== lastRound && spec.flow === 'speech') {
      frag.appendChild(dividerLine(labelOf(STATE, `r${r}`) ?? `라운드 ${r}`));
      lastRound = r;
    }

    if (spec.flow === 'resolution') {
      if (isChairResolution(event, chair)) {
        if (resolution === null) resolution = { event, raw };
        frag.appendChild(dividerLine('권고 — 위 상자에 있습니다'));
      } else {
        // 의장이 아닌 이가 낸 권고 — 지우지 않고 **접는다**(있었다는 사실은 남긴다).
        frag.appendChild(foldedLine(raw, '의장이 내지 않은 권고 1건 — 원문 보기'));
      }
      continue;
    }
    if (spec.flow === 'divider') {
      let text = spec.label;
      if (event.kind === 'advance' && r !== null) {
        const to = labelOf(STATE, `r${r}`) ?? `라운드 ${r}`;
        text = `${to}${euro(to)} 넘어감`;
      }
      if (event.kind === 'close') {
        const reason = labelOf(CLOSE_REASON, event.payload && event.payload.reason);
        if (reason !== null) text = `종결 — ${reason}`;
      }
      frag.appendChild(dividerLine(text));
      if (event.kind === 'advance' && r !== null) lastRound = r;
      continue;
    }
    frag.appendChild(speechCard(event, raw));
  }
  return { node: frag, resolution };
}

/** 권고 상자 — 언제나 「권고」라고 적는다(집행이 아니다 · 06 §2 불가침). */
export function resolutionBox(resolution) {
  if (!resolution) return null;
  const { event, raw } = resolution;
  const box = el('section', { className: 'resolution', attrs: { 'aria-label': '권고' } });
  box.appendChild(el('h2', { className: 'resolution-title', text: '권고' }));
  box.appendChild(el('p', { className: 'resolution-note', text: '아고라는 집행하지 않습니다. 아래는 각자의 판단에 쓰라고 남긴 권고입니다.' }));

  const summary = humanBody(event);
  if (summary !== null) box.appendChild(el('p', { className: 'resolution-summary', text: summary }));

  const p = event.payload || {};
  const actions = Array.isArray(p.recommended_actions) ? p.recommended_actions : [];
  if (actions.length) {
    box.appendChild(el('h3', { className: 'resolution-sub', text: '권고한 일' }));
    const ul = el('ul', { className: 'resolution-list' });
    for (const a of actions) {
      const t = a && typeof a.text === 'string' ? a.text : null;
      if (t !== null) ul.appendChild(el('li', { text: t }));
    }
    if (ul.childNodes.length) box.appendChild(ul);
  }

  const dissent = Array.isArray(p.dissent) ? p.dissent : [];
  if (dissent.length) {
    box.appendChild(el('h3', { className: 'resolution-sub', text: '다른 의견' }));
    const ul = el('ul', { className: 'resolution-list' });
    for (const d of dissent) {
      const who = d && typeof d.from === 'string' ? d.from : null;
      const quote = d && typeof d.quote === 'string' ? d.quote : null;
      if (quote === null) continue;
      ul.appendChild(el('li', { text: who === null ? quote : `${who} — ${quote}` }));
    }
    if (ul.childNodes.length) box.appendChild(ul);
  }

  box.appendChild(rawDetails(raw));
  return box;
}

/** 권고 첫 줄(아카이브용). 의장이 낸 것만. 없거나 의장을 모르면 null. */
export function resolutionFirstLine(items, chair = null) {
  for (const item of items) {
    if (isHidden(item)) continue;
    const { event } = parsePost(typeof item.body === 'string' ? item.body : '');
    if (event && isChairResolution(event, chair)) {
      const s = humanBody(event);
      if (s === null) return null;
      const line = s.split('\n')[0].trim();
      return line === '' ? null : line;
    }
  }
  return null;
}

/* ── 세 가지 「없음」을 서로 다른 문장으로 ────────────────────────── */

export function emptyLine(text)  { return el('p', { className: 'note note-empty', text }); }
export function errorLine(text)  { return el('p', { className: 'note note-error', text, attrs: { role: 'alert' } }); }
export function partialLine(text){ return el('p', { className: 'note note-partial', text }); }
