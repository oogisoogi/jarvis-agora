// render.js — 구조를 화면으로. **innerHTML 을 쓰지 않는다**(본문은 신뢰할 수 없는 콘텐츠다).
//
// 규율 셋(BOARD.md §5·§6 · 성찰 feed-in):
//  ① 서버가 안 준 칸은 **그리지 않는다** — 기본값 문구로 바꾸지 않는다(field() 한 곳을 지난다).
//  ② 신뢰 표시의 재료는 **서버 파생값뿐**이다 — 본문·서명 블록에서 신뢰를 읽지 않는다.
//  ③ 「비었다」·「못 가져왔다」·「일부러 안 가져왔다」는 **서로 다른 문장**이다.

import { TYPE, STATE, CLOSE_REASON, KIND, VERDICT, VERDICT_REASON, labelOf, toneOf, euro } from './vocab.js';
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
 * 기본 화면에서 **빼는** 항목. 재료는 서버 파생 판정뿐이다(브라우저는 서명을 검증하지 못한다).
 * 계약 = RELAY.md §3-5 — `valid`(받아들였다) · `quarantined`(자격 없음) · `stale`(경합에 밀렸거나 안 닿는다).
 * ★셋을 다 본다: §10 이 「격리·진 글은 기본 화면에서 뺀다」이므로 **밀린 글도 뺀다.**
 *   칸이 하나도 없으면(옛 서버) 아무것도 빼지 않는다 — 없는 값으로 글을 지우지 않는다.
 */
export function isHidden(item) {
  const v = verdictOf(item);
  return v !== null && v.state !== 'valid';
}

/**
 * 서버가 이 항목을 어떻게 판정했나. 서버가 말하지 않았으면 **null**(배지를 그리지 않는다).
 * ★`isHidden` 이 이 함수에서 파생된다 ⇒ 「가려졌는데 판정이 없다」는 **구조적으로 생길 수 없다.**
 *   (두 곳에 따로 조건을 적으면 둘이 갈리고, 그 틈을 메우려고 자리 메움 문구를 넣게 된다.)
 * @returns {{state:'valid'|'quarantined'|'stale', label:string, tone:string, reason:string|null}|null}
 */
export function verdictOf(item) {
  if (!item || typeof item !== 'object') return null;
  const reason = typeof item.reason === 'string' && item.reason !== '' ? item.reason : null;
  let state = null;
  if (item.quarantined === true) state = 'quarantined';
  else if (item.stale === true) state = 'stale';
  else if (item.valid === true) state = 'valid';
  else if (item.valid === false) state = 'quarantined';
  if (state === null) return null;
  return { state, label: VERDICT[state].label, tone: VERDICT[state].tone, reason };
}

/** 판정 배지 — 사유는 아는 것만 사람 말로, 모르는 사유는 **그대로** 적는다. */
export function verdictBadge(item) {
  const v = verdictOf(item);
  if (v === null) return null;
  const why = v.reason === null ? null : labelOf(VERDICT_REASON, v.reason);
  const text = why === null ? v.label : `${v.label} — ${why}`;
  return el('span', { className: `badge badge-${v.tone}`, text,
                      attrs: { title: v.reason === null ? null : `사유 코드 ${v.reason}` } });
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

export function archiveRow(room, resolutionFirstLine, verdictItem = null) {
  const card = roomCard(room);
  const reason = labelOf(CLOSE_REASON, room.close_reason);
  const extra = el('div', { className: 'fields' });
  if (reason !== null) extra.appendChild(field('종결', reason));
  const closedAt = fmtDateTime(room.closed_at);
  if (closedAt !== null) extra.appendChild(field('종결 시각', closedAt, { attrs: { title: room.closed_at } }));
  if (extra.childNodes.length) card.appendChild(extra);
  if (resolutionFirstLine) {
    const line = el('p', { className: 'archive-resolution', text: resolutionFirstLine });
    const badge = verdictItem ? verdictBadge(verdictItem) : null;
    if (badge) { line.appendChild(document.createTextNode(' ')); line.appendChild(badge); }
    card.appendChild(line);
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

function speechCard(event, raw, badge = null) {
  const card = el('article', { className: 'speech' });
  const head = el('div', { className: 'speech-head' });
  head.appendChild(el('span', { className: 'speech-who', text: event.from || NAMELESS_WHO }));
  const when = fmtDateTime(event.ts);
  if (when !== null) head.appendChild(el('time', { className: 'speech-when', text: when, attrs: { datetime: event.ts } }));
  const kindLabel = labelOf(KIND, event.kind);
  if (kindLabel !== null && event.kind !== 'post') {
    head.appendChild(el('span', { className: 'chip chip-kind', text: kindLabel }));
  }
  if (badge) head.appendChild(badge);
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
export function flow(items, chair = null, opts = {}) {
  const showVerdict = opts.showVerdict === true;
  const frag = document.createDocumentFragment();
  const hiddenReasons = new Map();                      // 사유 → 건수(내용은 세지 않는다)
  let resolution = null;
  let lastRound = null;

  for (const item of items) {
    if (isHidden(item)) {
      // ★가린 것은 **세기만** 한다 — 사유와 건수는 알려 주되 본문은 여기서 꺼내지 않는다.
      const v = verdictOf(item);   // isHidden 이 참이면 v 는 반드시 있다(위 파생 관계)
      const key = v.reason === null ? v.label : `${v.label}(${labelOf(VERDICT_REASON, v.reason)})`;
      const seen = hiddenReasons.get(key);
      hiddenReasons.set(key, (seen === undefined ? 0 : seen) + 1);
      continue;
    }
    const raw = typeof item.body === 'string' ? item.body : '';
    const badge = showVerdict ? verdictBadge(item) : null;
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
    frag.appendChild(speechCard(event, raw, badge));
  }
  return { node: frag, resolution, hiddenReasons };
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
  return (resolutionEntry(items, chair) || {}).line || null;
}

/** 권고 첫 줄 + 그 글의 서버 판정을 함께 돌려준다(같은 항목을 두 번 찾지 않는다). */
export function resolutionEntry(items, chair = null) {
  for (const item of items) {
    if (isHidden(item)) continue;
    const { event } = parsePost(typeof item.body === 'string' ? item.body : '');
    if (event && isChairResolution(event, chair)) {
      const s = humanBody(event);
      if (s === null) return null;
      const line = s.split('\n')[0].trim();
      return line === '' ? null : { line, item };
    }
  }
  return null;
}

/* ── 세 가지 「없음」을 서로 다른 문장으로 ────────────────────────── */

/**
 * 판정 배지를 켰을 때만 나오는 줄 — **가린 기록이 몇 건이고 왜인지**를 알려 준다.
 * ⛔가린 글의 **본문은 여기서 펼치지 않는다**: 켜는 방법이 주소 한 줄이라 누구나 켤 수 있고,
 *   그러면 「기본 화면에서 뺀다」가 주소 한 줄로 우회된다. 세는 것과 보여 주는 것은 다른 일이다.
 */
export function hiddenSummaryLine(hiddenReasons) {
  if (!hiddenReasons || hiddenReasons.size === 0) return null;
  let total = 0;
  const parts = [];
  for (const [why, n] of hiddenReasons) { total += n; parts.push(`${why} ${n}건`); }
  return el('p', { className: 'note note-partial',
                   text: `이 화면에서 가린 기록 ${total}건 — ${parts.join(' · ')}(내용은 보여 주지 않습니다)` });
}

export function emptyLine(text)  { return el('p', { className: 'note note-empty', text }); }
export function errorLine(text)  { return el('p', { className: 'note note-error', text, attrs: { role: 'alert' } }); }
export function partialLine(text){ return el('p', { className: 'note note-partial', text }); }
