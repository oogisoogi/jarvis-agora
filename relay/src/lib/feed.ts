/**
 * 광장 피드 정렬 — ★**이식**이다. 정본 = `tools/plaza.py` 의 `feed`·`read_plaza`·`valid_votes`·`scores`·`day_of`.
 *
 * 규칙을 여기서 새로 정하지 않는다. plaza.py 를 고치면 **같은 커밋에서** 이 파일을 고친다 —
 * selftest 「광장: 피드 정렬 py↔ts 가 같다」가 같은 입력에 두 구현이 같은 순서·같은 점수를 내는지 맞춰 보고,
 * vitest 가 두 파일의 상수(감쇠·하루 경계·하루 표 수·마커 정규식)가 같은지 대조한다.
 *
 * ★점수 셈은 **정수(1/100 단위)** 로 한다. plaza.py 는 Decimal + 둘째 자리 ROUND_HALF_UP 이다.
 *   (점수×0.5 + 표) 를 둘째 자리 반올림 = 0.01 단위 정수 c 에 대해 floor(c/2 + 0.5) + 표×100 (c ≥ 0) 과 같다.
 */

export const DAY_START_HOUR = 6;          // plaza.DAY_START_HOUR
export const DECAY_HALF = true;           // plaza.DECAY = 0.5 (정수 셈에서는 「반으로」로만 쓴다)
export const VOTES_PER_DAY = 3;           // plaza.VOTES_PER_DAY
export const KST_OFFSET_HOURS = 9;
export const FEED_SORTS = ["new", "hot", "top"] as const;
export type FeedSort = typeof FEED_SORTS[number];
export const REPLY_WHY = "reply";
// plaza.MARKER_RE 와 같은 식(대조는 vitest 가 plaza.py 원문에서 읽어 맞춘다).
export const MARKER_SOURCE =
  "^\\[(?<kind>졸업|보관|유찰)\\]\\s+(?<id>[0-9a-f]{32})" +
  "(?:\\s*→\\s*(?<thread>[0-9a-f]{32}))?" +
  "(?:\\s*·\\s*(?<note>.*))?$";
const MARKER_RE = new RegExp(MARKER_SOURCE, "u");

/** plaza.is_community 의 이식 — 커뮤니티 = debate · deadlines 없음 · budget 있음. */
export function isCommunity(genesisPayload: unknown): boolean {
  if (!genesisPayload || typeof genesisPayload !== "object" || Array.isArray(genesisPayload)) return false;
  const g = genesisPayload as Record<string, unknown>;
  const b = g.budget;
  return g.type === "debate" && !("deadlines" in g)
    && !!b && typeof b === "object" && !Array.isArray(b);
}

export interface FeedEvent { created_at: string; event: Record<string, any> }
export interface FeedItem {
  room: string; id: string; from: string; at: string; body: string;
  score: string; votes: number; replies: FeedItem[];
}

interface Prop { id: string; from: string; t: number; at: string; body: string; order: number; parent: string | null }
interface Vote { from: string; t: number; target: string; value: number }

/** plaza.day_of — 06:00 KST 이전은 어제. 반환 = 그 날의 epoch 일 번호(비교·차이 계산용). */
export function dayOf(ms: number): number {
  return Math.floor((ms + (KST_OFFSET_HOURS - DAY_START_HOUR) * 3600_000) / 86_400_000);
}

export function replyParent(event: Record<string, any>): string | null {
  const refs = event?.payload?.refs;
  if (!Array.isArray(refs) || !refs.length || !refs[0] || typeof refs[0] !== "object" || Array.isArray(refs[0])) return null;
  if (refs[0].why !== REPLY_WHY) return null;
  const parent = refs[0].message_id;
  return typeof parent === "string" && parent ? parent : null;
}

function ts(text: unknown): number | null {
  if (typeof text !== "string" || !text) return null;
  const ms = Date.parse(text);
  return Number.isFinite(ms) ? ms : null;
}

function readPlaza(events: FeedEvent[]) {
  const proposals = new Map<string, Prop>();
  const votes: Vote[] = [];
  events.forEach((row, order) => {
    const event = row.event ?? {};
    const t = ts(row.created_at);
    if (t === null) return;
    const payload = event.payload ?? {};
    if (event.kind === "post") {
      const body = String(payload.body ?? "");
      if (MARKER_RE.test(body.trim())) return;          // 마커는 글이 아니다
      proposals.set(event.message_id, { id: event.message_id, from: event.from, t, at: row.created_at,
        body, order, parent: replyParent(event) });
    } else if (event.kind === "vote") {
      votes.push({ from: event.from, t, target: payload.target, value: Number(payload.value ?? 0) | 0 });
    }
  });
  return { proposals, votes };
}

function validVotes(p: ReturnType<typeof readPlaza>): Vote[] {
  const last = new Map<string, Vote>();
  for (const v of [...p.votes].sort((a, b) => a.t - b.t)) {
    const target = p.proposals.get(v.target);
    if (!target) continue;
    if (target.from === v.from) continue;             // ⛔자기 제안
    last.set(JSON.stringify([v.from, v.target]), v);  // 마지막 것만(자리는 처음 넣은 곳 · 파이썬 dict 와 같다)
  }
  const kept = [...last.values()].filter(v => v.value === 1);
  const byDay = new Map<string, Vote[]>();
  for (const v of [...kept].sort((a, b) => a.t - b.t)) {
    const k = JSON.stringify([v.from, dayOf(v.t)]);
    if (!byDay.has(k)) byDay.set(k, []);
    byDay.get(k)!.push(v);
  }
  const out: Vote[] = [];
  for (const same of byDay.values()) out.push(...same.slice(-VOTES_PER_DAY));
  return out.sort((a, b) => a.t - b.t);
}

/** 점수(1/100 단위 정수). */
function scoresCents(p: ReturnType<typeof readPlaza>, through: number): Map<string, number> {
  const perDay = new Map<string, Map<number, number>>();
  for (const v of validVotes(p)) {
    if (!perDay.has(v.target)) perDay.set(v.target, new Map());
    const m = perDay.get(v.target)!;
    const d = dayOf(v.t);
    m.set(d, (m.get(d) ?? 0) + 1);
  }
  const out = new Map<string, number>();
  for (const [pid, prop] of p.proposals) {
    const start = dayOf(prop.t);
    let c = 0;
    for (let d = start; d <= through; d++) {
      c = Math.floor(c / 2 + 0.5) + (perDay.get(pid)?.get(d) ?? 0) * 100;
    }
    out.set(pid, c);
  }
  return out;
}

function fmt(cents: number): string {
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}

interface Work extends FeedItem { _t: number; _order: number; _cents: number; replies: Work[] }

export function feed(rooms: Array<[string, FeedEvent[]]>, sort: FeedSort, nowMs: number): FeedItem[] {
  if (!(FEED_SORTS as readonly string[]).includes(sort)) throw new Error("정렬은 new·hot·top 중 하나다");
  const through = dayOf(nowMs);
  const tops: Work[] = [];
  for (const [room, events] of rooms) {
    const p = readPlaza(events);
    const table = scoresCents(p, through);
    const counts = new Map<string, number>();
    for (const v of validVotes(p)) counts.set(v.target, (counts.get(v.target) ?? 0) + 1);
    const items = new Map<string, Work>();
    for (const [pid, prop] of p.proposals) {
      const c = table.get(pid) ?? 0;
      items.set(pid, { room, id: pid, from: prop.from, at: prop.at, body: prop.body, score: fmt(c),
        votes: counts.get(pid) ?? 0, replies: [], _t: prop.t, _order: prop.order, _cents: c });
    }
    const byOrder = [...p.proposals.values()].sort((a, b) => a.order - b.order);
    for (const prop of byOrder) {
      const parent = prop.parent !== null ? p.proposals.get(prop.parent) : undefined;
      if (parent && parent.order < prop.order) items.get(parent.id)!.replies.push(items.get(prop.id)!);
      else tops.push(items.get(prop.id)!);
    }
  }
  const cmpStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
  // 마지막 동점 깨기 = (방, 글 id) 내림차순 → 그 위에 안정 정렬(plaza.py 와 같은 두 단계).
  tops.sort((a, b) => cmpStr(b.room, a.room) || cmpStr(b.id, a.id));
  tops.sort((a, b) => {
    const first = sort === "hot" ? b._cents - a._cents : sort === "top" ? b.votes - a.votes : 0;
    return first || (b._t - a._t);
  });
  return tops.map(strip);
}

function strip(w: Work): FeedItem {
  return { room: w.room, id: w.id, from: w.from, at: w.at, body: w.body, score: w.score, votes: w.votes,
           replies: [...w.replies].sort((a, b) => a._order - b._order).map(strip) };
}
