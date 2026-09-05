/**
 * reducer 이식 — 파이썬 `agora/reducer.py` 1~3단을 **바꾸지 않고** 옮긴 것.
 *
 * ★규칙 하나라도 다르면 3자 대조(docs/RELAY.md §9)가 그 자리에서 적색이 된다.
 *   그것이 이 이식이 정직한지를 재는 유일한 방법이다. 갈리면 **이쪽이 틀린 것**이다.
 *
 * 층 구분(파이썬과 같다):
 *   1단 collect — 무엇을 상태 계산에 넣어도 되는가(격리 6사유)
 *   2단 order   — 사슬·경합(진 것 = stale, 격리가 아니다)
 *   3단 apply   — 유형별 전이·권한·라운드·예산·CAS·만료(격리 9사유)
 */
import { canonicalBytes, hex } from "./canonical.ts";
import { AgoraError } from "./errors.ts";
import { parsePost } from "./post.ts";
import * as schema from "./schema.ts";
import { VERDICT_OK, verifyDetail, type RosterEntry } from "./sshsig.ts";

// 1단 격리 사유
export const UNPARSEABLE = "unparseable";
export const OVERSIZE = "oversize";
export const SCHEMA = "schema";
export const THREAD_MISMATCH = "thread_mismatch";
export const SIGNATURE = "signature";
export const REPLAY = "replay";
// 3단 격리 사유
export const OUT_OF_ROUND = "out_of_round";
export const COUNTER_REQUIRED = "counter_required";
export const PERMISSION = "permission";
export const KIND_NOT_ALLOWED = "kind_not_allowed";
export const BAD_TRANSITION = "bad_transition";
export const UNKNOWN_TARGET = "unknown_target";
export const BUDGET_EXCEEDED = "budget_exceeded";
export const AFTER_CLOSE = "after_close";
export const STALE_EXPECTED = "stale_expected_state";
// 2단 stale 사유
export const LOST_RACE = "lost_race";
export const UNREACHABLE = "unreachable";

export const EXPIRED = "expired";
export const DEBATE_ROUNDS = ["r0", "r1", "r2", "r3"];
export const EXPIRED_GRACE_SECONDS = 300;
export const DEFAULT_BUDGET = { posts_per_round: 2, max_chars_per_round: 6000 };

export const ALLOWED_KINDS: Record<string, Set<string>> = {
  problem: new Set(["post", "answer_selected", "close", "vote", "abort"]),
  knowhow: new Set(["post", "close", "vote", "abort"]),
  debate: new Set(["post", "advance", "resolution", "close", "delegate_chair", "vote", "abort"]),
};
const KNOWHOW_CLOSE_REASONS = new Set(["superseded", "archived"]);

/** 파이썬 len(str) 은 **코드포인트** 수다. JS .length 는 UTF-16 단위라 이모지에서 갈린다. */
export const charLen = (s: string): number => Array.from(s).length;

export interface Row { node_id: string; created_at: string; body: string; }

export interface ValidEntry {
  node_id: string; created_at: string; event: Record<string, any>;
  canonical: string; hash: string; kind: string; from: string;
  message_id: string; prev: string; fingerprint: string | null;
  roster_stale: boolean; scrub_recheck: boolean;
}

export interface Quarantined {
  node_id: string; created_at: string; reason: string; stage?: string; detail?: unknown;
}
export interface Stale {
  node_id: string; message_id: string; from: string; kind: string; reason: string;
  winner_node_id?: string; prev?: string;
}

function orderKey(r: { created_at?: string; node_id?: string }): [string, string] {
  return [String(r.created_at ?? ""), String(r.node_id ?? "")];
}
function cmpKey(a: [string, string], b: [string, string]): number {
  if (a[0] !== b[0]) return a[0] < b[0] ? -1 : 1;
  if (a[1] !== b[1]) return a[1] < b[1] ? -1 : 1;
  return 0;
}

async function sha256Of(raw: Uint8Array): Promise<string> {
  return hex(new Uint8Array(await crypto.subtle.digest("SHA-256", raw as BufferSource)));
}

export interface CollectResult {
  thread_id: string; fetched: number; valid: ValidEntry[]; quarantined: Quarantined[];
}

/** 1단 — 검증 파이프. 유효 목록과 격리 목록을 가른다(상태는 계산하지 않는다). */
export async function collect(args: {
  rows: Row[]; threadId: string; namespace: string;
  lookup: (fp: string) => RosterEntry | undefined;
  rosterCheckpoint?: string | null; scrubBundle?: string | null;
}): Promise<CollectResult> {
  const rows = [...args.rows].sort((a, b) => cmpKey(orderKey(a), orderKey(b)));
  const valid: ValidEntry[] = [];
  const quarantined: Quarantined[] = [];
  const seen = new Set<string>();

  const drop = (row: Row, reason: string, detail?: unknown) =>
    quarantined.push({ node_id: row.node_id, created_at: row.created_at, reason, detail });

  for (const row of rows) {
    // (1) 서식 — 우리 서식이 아니면 여기서 끝난다.
    let parsed;
    try { parsed = parsePost(row.body ?? ""); }
    catch (e) {
      const err = e as AgoraError;
      drop(row, err.code === 3 ? OVERSIZE : UNPARSEABLE, { code: err.code, message: err.message });
      continue;
    }
    const event = parsed.event as Record<string, any>;

    // (2) 계약(모양·정책)
    try { schema.validate(event); }
    catch (e) {
      const err = e as AgoraError;
      drop(row, SCHEMA, { code: err.code, message: err.message, at: err.detail });
      continue;
    }

    // (3) 스레드 결박 — 다른 스레드의 **유효한** 이벤트도 여기서는 무효다.
    if (event.thread_id !== args.threadId) {
      drop(row, THREAD_MISMATCH, { event_thread_id: event.thread_id, asked: args.threadId });
      continue;
    }

    // (4) 서명·명부·폐기
    const verdict = await verifyDetail({
      message: parsed.raw, signature: parsed.signature, principal: event.from,
      namespace: args.namespace, lookup: args.lookup,
    });
    if (verdict.verdict !== VERDICT_OK) {
      drop(row, SIGNATURE, { verdict: verdict.verdict, why: verdict.reason });
      continue;
    }

    // (5) 재게시 — 같은 (from, message_id) 는 한 번만이다.
    const key = event.from + " " + event.message_id;
    if (seen.has(key)) {
      drop(row, REPLAY, { from: event.from, message_id: event.message_id });
      continue;
    }
    seen.add(key);

    valid.push({
      node_id: row.node_id, created_at: row.created_at, event,
      canonical: parsed.canonical, hash: await sha256Of(parsed.raw),
      kind: event.kind, from: event.from, message_id: event.message_id, prev: event.prev,
      fingerprint: verdict.fingerprint,
      roster_stale: args.rosterCheckpoint != null && event.roster !== args.rosterCheckpoint,
      scrub_recheck: args.scrubBundle != null && event.scrub?.rules !== args.scrubBundle,
    });
  }
  return { thread_id: args.threadId, fetched: rows.length, valid, quarantined };
}

export interface OrderResult {
  thread_id: string; chain: ValidEntry[]; stale: Stale[]; quarantined: Quarantined[];
}

/** 2단 — 유효 목록에서 사슬·진 것·닿지 않는 것을 가른다. 상태는 계산하지 않는다. */
export function order(collected: CollectResult): OrderResult {
  const byPrev = new Map<string, ValidEntry[]>();
  for (const e of collected.valid) {
    const list = byPrev.get(e.prev) ?? [];
    list.push(e);
    byPrev.set(e.prev, list);
  }
  const chain: ValidEntry[] = [];
  const stale: Stale[] = [];
  const seenHashes = new Set<string>();
  let key = schema.GENESIS_PREV;
  for (;;) {
    const candidates = byPrev.get(key) ?? [];
    if (!candidates.length) break;
    // 승자 = createdAt 이 이르면 이긴다. 동률이면 node_id 사전순.
    let winner = candidates[0];
    for (const c of candidates) if (cmpKey(orderKey(c), orderKey(winner)) < 0) winner = c;
    for (const loser of candidates) {
      if (loser === winner) continue;
      stale.push({
        node_id: loser.node_id, message_id: loser.message_id, from: loser.from,
        kind: loser.kind, reason: LOST_RACE, winner_node_id: winner.node_id,
      });
    }
    chain.push(winner);
    seenHashes.add(winner.hash);
    if (winner.hash === key) break;   // 자기 자신을 가리키는 사슬 — 무한 순회 차단
    key = winner.hash;
  }
  const lostNodes = new Set(stale.map(s => s.node_id));
  for (const e of collected.valid) {
    if (!seenHashes.has(e.hash) && !lostNodes.has(e.node_id)) {
      stale.push({
        node_id: e.node_id, message_id: e.message_id, from: e.from, kind: e.kind,
        reason: UNREACHABLE, prev: e.prev,
      });
    }
  }
  return { thread_id: collected.thread_id, chain, stale, quarantined: collected.quarantined };
}

function parseTs(value: string): number {
  const t = Date.parse(String(value));
  if (Number.isNaN(t)) {
    throw new AgoraError(10, "시각 형식이 아니다", { value: String(value).slice(0, 40) });
  }
  return t;
}

export function deadlinePassed(deadline: string, now: string,
                               graceSeconds = EXPIRED_GRACE_SECONDS): boolean {
  return parseTs(now) > parseTs(deadline) + graceSeconds * 1000;
}

export function isExpiredNow(gtype: string, stateName: string,
                             deadlines: Record<string, any>, now?: string | null): boolean {
  if (gtype !== "debate" || !now || !DEBATE_ROUNDS.includes(stateName)) return false;
  const due = deadlines ? deadlines[stateName] : null;
  return !!due && deadlinePassed(due, now);
}

const HASH_FIELDS = ["type", "state", "round", "chair", "requester", "solved_by",
  "close_reason", "head"];

/** 상태 해시 — 다음 이벤트의 expected_state 가 가리키는 값. 사슬의 머리를 포함한다. */
export async function stateHash(state: Record<string, any>): Promise<string> {
  const snap: Record<string, unknown> = {};
  for (const k of HASH_FIELDS) snap[k] = state[k] ?? null;
  return sha256Of(canonicalBytes(snap));
}

export interface ApplyResult {
  thread_id: string; state: string | null; reason?: string;
  type?: string; round?: number | null; chair?: string; requester?: string;
  solved_by?: string | null; close_reason?: string | null; head?: string; abort_reason?: string;
  events: ValidEntry[]; deferred: unknown[]; stale: Stale[]; quarantined: Quarantined[];
  usage?: Record<string, { posts: number; chars: number }>;
  budget?: { posts_per_round: number; max_chars_per_round: number };
  state_hash?: string;
}

/** 3단 — 사슬에서 상태를 만든다. 절차에서 걸린 것은 사유와 함께 격리 목록에 더한다. */
export async function apply(ordered: OrderResult, opts: {
  operators?: Set<string>; now?: string | null;
  budget?: { posts_per_round: number; max_chars_per_round: number };
} = {}): Promise<ApplyResult> {
  const operators = opts.operators ?? new Set<string>();
  const now = opts.now ?? null;
  const quarantined = [...ordered.quarantined];
  const chain = ordered.chain;
  if (!chain.length || chain[0].kind !== "genesis") {
    // genesis 가 없으면 상태가 없다. 빈 스레드와 구별되게 이유를 남긴다.
    return {
      thread_id: ordered.thread_id, state: null, reason: "no_genesis", events: [],
      deferred: [], stale: ordered.stale, quarantined,
    };
  }
  const genesis = chain[0].event;
  const gtype = genesis.payload.type as string;
  const state: Record<string, any> = {
    type: gtype,
    state: gtype === "debate" ? "r0" : "open",
    round: gtype === "debate" ? 0 : null,
    chair: genesis.payload.chair || genesis.from,
    requester: genesis.from,
    solved_by: null,
    close_reason: null,
    head: chain[0].hash,
  };
  const accepted: ValidEntry[] = [chain[0]];
  const deferred: unknown[] = [];
  const postIds = new Set<string>([chain[0].message_id]);
  const limits = opts.budget ? { ...opts.budget } : { ...DEFAULT_BUDGET };
  const deadlines = genesis.payload.deadlines ?? {};
  const usage: Record<string, { posts: number; chars: number }> = {};

  const reject = (entry: ValidEntry, reason: string, detail?: unknown) => {
    quarantined.push({
      node_id: entry.node_id, created_at: entry.created_at, reason,
      stage: "transition", detail,
    });
    // ★거부돼도 사슬은 지나갔다 — head 를 전진시킨다(L-1 교착 봉합).
    //   2단은 거부 여부를 모른 채 prev 만 보고 승자를 골랐으므로, head 를 안 옮기면
    //   다음 사람이 영원히 진다(1명이 이벤트 1건으로 스레드를 영구 동결시킬 수 있었다).
    state.head = entry.hash;
  };

  const usageSlot = (pid: string) =>
    state.type === "debate" ? pid + "@r" + state.round : pid;

  for (const entry of chain.slice(1)) {
    const kind = entry.kind, ev = entry.event, who = entry.from;
    const payload = ev.payload;

    // CAS — 계약 칸은 **받는 쪽이 판정할 때만** 계약이다.
    const seen = ev.expected_state;
    let ok = seen === await stateHash(state);
    if (!ok && isExpiredNow(gtype, state.state, deadlines, now)) {
      // 만료된 스레드를 되살리러 쓰는 사람은 **만료가 반영된 상태**를 보고 쓴다.
      const probe = { ...state, state: EXPIRED };
      ok = seen === await stateHash(probe);
    }
    if (!ok) {
      reject(entry, STALE_EXPECTED, {
        expected_state: seen, at_that_point: await stateHash(state),
      });
      continue;
    }

    if (state.state === "closed") { reject(entry, AFTER_CLOSE, { kind }); continue; }
    if (!ALLOWED_KINDS[gtype].has(kind)) {
      reject(entry, KIND_NOT_ALLOWED, { type: gtype, kind });
      continue;
    }

    if (kind === "vote") {
      // 구속력 없음 — 받아 두되 상태를 바꾸지 않는다.
      accepted.push(entry);
      state.head = entry.hash;
      continue;
    }

    if (kind === "post") {
      if (gtype === "debate") {
        if (payload.round !== state.round) {
          reject(entry, OUT_OF_ROUND, { post_round: payload.round, now: state.round });
          continue;
        }
        if (state.round === 2 && !(payload.counter && payload.counter.length)) {
          // R2 는 반론 라운드다 — 대상 없는 발언은 라운드의 뜻을 비운다.
          reject(entry, COUNTER_REQUIRED, { round: 2 });
          continue;
        }
      }
      const slot = usageSlot(who);
      const used = usage[slot] ?? (usage[slot] = { posts: 0, chars: 0 });
      const body = payload.body ?? "";
      let over: Record<string, unknown> | null = null;
      if (used.posts + 1 > limits.posts_per_round) {
        over = { limit: "posts_per_round", used: used.posts, max: limits.posts_per_round };
      } else if (used.chars + charLen(body) > limits.max_chars_per_round) {
        over = {
          limit: "max_chars_per_round", used: used.chars, adding: charLen(body),
          max: limits.max_chars_per_round,
        };
      }
      if (over) { reject(entry, BUDGET_EXCEEDED, over); continue; }
      used.posts += 1;
      used.chars += charLen(body);
      postIds.add(entry.message_id);
      accepted.push(entry);
    } else if (kind === "advance") {
      if (who !== state.chair) {
        reject(entry, PERMISSION, { chair: state.chair, from: who });
        continue;
      }
      if (payload.from_round !== state.round) {
        reject(entry, BAD_TRANSITION, { from_round: payload.from_round, now: state.round });
        continue;
      }
      state.round = payload.to_round;
      state.state = DEBATE_ROUNDS[payload.to_round];
      accepted.push(entry);
    } else if (kind === "resolution") {
      if (who !== state.chair) {
        reject(entry, PERMISSION, { chair: state.chair, from: who });
        continue;
      }
      if (state.state !== "r3") {
        reject(entry, BAD_TRANSITION, { now: state.state, want: "r3" });
        continue;
      }
      state.state = "resolved";
      accepted.push(entry);
    } else if (kind === "answer_selected") {
      if (who !== state.requester) {
        // 남이 고른 답은 상태를 바꾸지 않는다.
        reject(entry, PERMISSION, { requester: state.requester, from: who });
        continue;
      }
      if (!postIds.has(payload.post_message_id)) {
        reject(entry, UNKNOWN_TARGET, { post_message_id: payload.post_message_id });
        continue;
      }
      state.state = "solved";
      state.solved_by = payload.post_message_id;
      accepted.push(entry);
    } else if (kind === "close") {
      if (who !== state.chair && who !== state.requester && !operators.has(who)) {
        reject(entry, PERMISSION, {
          allowed: [state.chair, state.requester, "operator"], from: who,
        });
        continue;
      }
      if (gtype === "knowhow" && !KNOWHOW_CLOSE_REASONS.has(payload.reason)) {
        reject(entry, BAD_TRANSITION, {
          reason: payload.reason, allowed: [...KNOWHOW_CLOSE_REASONS].sort(),
        });
        continue;
      }
      state.state = "closed";
      state.close_reason = payload.reason;
      accepted.push(entry);
    } else if (kind === "delegate_chair") {
      // 의장은 언제나 넘길 수 있다. 운영자는 **만료된 동안만** 대신 넘길 수 있다.
      if (who !== state.chair) {
        if (!(operators.has(who) && isExpiredNow(gtype, state.state, deadlines, now))) {
          reject(entry, PERMISSION, {
            chair: state.chair, from: who, operator_needs: "expired",
          });
          continue;
        }
      }
      state.chair = payload.new_chair;
      accepted.push(entry);
    } else if (kind === "abort") {
      // 운영자 명부에 있는 사람만. 목록에서 이름이 빠지면 그 키의 abort 는 죽는다.
      if (!operators.has(who)) {
        reject(entry, PERMISSION, { from: who, need: "operator" });
        continue;
      }
      state.state = "closed";
      state.close_reason = "aborted";
      state.abort_reason = payload.reason;
      accepted.push(entry);
    }
    state.head = entry.hash;
  }

  // 만료는 **이벤트가 없을 때만** 발동한다(이벤트가 시간을 이긴다).
  if (isExpiredNow(gtype, state.state, deadlines, now)) state.state = EXPIRED;

  const result = {
    ...state,
    thread_id: ordered.thread_id,
    events: accepted, deferred,
    usage, budget: limits,
    stale: ordered.stale, quarantined,
  } as ApplyResult;
  result.state_hash = await stateHash(state);
  return result;
}

/** 편의 — 세 단을 한 번에. */
export async function reduceThread(args: Parameters<typeof collect>[0] & {
  operators?: Set<string>; now?: string | null;
  budget?: { posts_per_round: number; max_chars_per_round: number };
}): Promise<ApplyResult> {
  const collected = await collect(args);
  return apply(order(collected), {
    operators: args.operators, now: args.now, budget: args.budget,
  });
}
