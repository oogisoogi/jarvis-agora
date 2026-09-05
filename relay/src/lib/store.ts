/**
 * D1 접근 + 파생 계산.
 *
 * ★`events` 는 append-only 다. 이 파일에 UPDATE·DELETE 하는 코드가 있으면 그 자체가 결함이다
 *   (`rate_windows` 정리와 `rooms` 파생 캐시는 예외 — 둘 다 정본이 아니다).
 * ★질의 개수를 센다: 무료 D1 은 **Worker 호출당 50개**다(docs/RELAY.md §8).
 *   그래서 목록 화면은 방 개수에 비례하는 질의를 절대 쓰지 않는다.
 */
import { reduceThread, type ApplyResult, type Row } from "./reducer.ts";
import { lookupTable, renderAllowedSigners, renderOperators, renderRevokedKeys,
         checkpointOf, type ParticipantRow } from "./roster.ts";
import type { RosterEntry } from "./sshsig.ts";

export interface Env {
  DB: D1Database;
  AGORA_NAMESPACE: string;
  CORS_ALLOW_ORIGINS: string;
}

/** 고정폭 단조 식별자 — 리듀서 동률 규칙이 문자열 사전순이라 자릿수가 곧 계약이다. */
export function eventIdOf(seq: number): string {
  return "ev_" + String(seq).padStart(16, "0");
}

/** 밀리초 고정폭 ISO — 문자열 정렬 = 시간 정렬. */
export function nowIso(d: Date = new Date()): string {
  return d.toISOString();
}

export async function allParticipants(db: D1Database): Promise<ParticipantRow[]> {
  const r = await db.prepare(
    "SELECT participant_id, display_name, key_type, key_b64, fingerprint, is_operator, revoked_at, created_at FROM participants"
  ).all<ParticipantRow>();
  return r.results ?? [];
}

export interface RosterView {
  rows: ParticipantRow[];
  lookup: (fp: string) => RosterEntry | undefined;
  operators: Set<string>;
  allowedText: string;
  revokedText: string;
  operatorsText: string;
  checkpoint: string;
}

export async function rosterView(db: D1Database): Promise<RosterView> {
  const rows = await allParticipants(db);
  const table = lookupTable(rows);
  const allowedText = renderAllowedSigners(rows);
  const revokedText = renderRevokedKeys(rows);
  const operatorsText = renderOperators(rows);
  return {
    rows,
    lookup: (fp: string) => table.get(fp),
    operators: new Set(rows.filter(r => r.is_operator === 1 && !r.revoked_at).map(r => r.participant_id)),
    allowedText, revokedText, operatorsText,
    checkpoint: await checkpointOf(allowedText, revokedText, operatorsText),
  };
}

export interface EventRow {
  seq: number; thread_id: string; message_id: string; from_id: string; kind: string;
  prev: string; hash: string; canonical: string; signature: string; category: string;
  title: string; is_genesis: number; created_at: string;
}

export async function threadEvents(db: D1Database, threadId: string): Promise<EventRow[]> {
  const r = await db.prepare(
    "SELECT seq, thread_id, message_id, from_id, kind, prev, hash, canonical, signature, category, title, is_genesis, created_at FROM events WHERE thread_id = ? ORDER BY seq"
  ).bind(threadId).all<EventRow>();
  return r.results ?? [];
}

/** 저장 행 → 리듀서가 먹는 모양(게시물 원문으로 재조립). */
export function toReducerRows(rows: EventRow[], render: (canonical: string, sig: string) => string): Row[] {
  return rows.map(r => ({
    node_id: eventIdOf(r.seq),
    created_at: r.created_at,
    body: render(r.canonical, r.signature),
  }));
}

export interface Derived {
  reduced: ApplyResult;
  signatureBad: number;
  participants: number;
  deadline: string | null;
  answered: boolean;
  closedAt: string | null;
}

/** 사슬 → 상태. 서버 파생은 **사본**이고, 정본은 참가자가 자기 손으로 다시 계산한다. */
export async function deriveThread(args: {
  db: D1Database; threadId: string; namespace: string; roster: RosterView;
  scrubBundle?: string | null; now?: string | null; rows?: EventRow[];
  render: (canonical: string, sig: string) => string;
}): Promise<{ derived: Derived; rows: EventRow[] }> {
  const rows = args.rows ?? await threadEvents(args.db, args.threadId);
  const reduced = await reduceThread({
    rows: toReducerRows(rows, args.render),
    threadId: args.threadId,
    namespace: args.namespace,
    lookup: args.roster.lookup,
    rosterCheckpoint: args.roster.checkpoint,
    scrubBundle: args.scrubBundle ?? null,
    operators: args.roster.operators,
    now: args.now ?? nowIso(),
  });
  const signatureBad = (reduced.quarantined ?? []).filter(q => q.reason === "signature").length;
  const speakers = new Set<string>();
  for (const e of reduced.events ?? []) speakers.add(e.from);
  const genesisPayload = (reduced.events ?? [])[0]?.event?.payload ?? {};
  const deadlines = genesisPayload.deadlines ?? {};
  const deadline = reduced.state && deadlines[reduced.state] ? String(deadlines[reduced.state]) : null;
  // closed_at = 상태를 닫은 이벤트의 도착 시각(파생값이지 정본이 아니다).
  let closedAt: string | null = null;
  if (reduced.state === "closed") {
    for (const e of reduced.events ?? []) if (e.kind === "close" || e.kind === "abort") closedAt = e.created_at;
  }
  return {
    rows,
    derived: {
      reduced, signatureBad, participants: speakers.size, deadline,
      answered: reduced.state === "solved" || !!reduced.solved_by,
      closedAt,
    },
  };
}

/** 파생 캐시 갱신. ★DROP 해도 events 로 다시 만들어진다(합격 기준 R-7). */
export async function upsertRoom(db: D1Database, threadId: string, d: Derived,
                                 rows: EventRow[], updatedAt: string): Promise<void> {
  const r = d.reduced;
  const genesis = rows.find(x => x.is_genesis === 1);
  const lastSeq = rows.length ? rows[rows.length - 1].seq : 0;
  await db.prepare(
    `INSERT INTO rooms (thread_id, title, type, state, round, chair, requester, closed, answered,
       close_reason, closed_at, participants, deadline, state_hash, events_counted, signature_bad,
       updated_at, last_seq)
     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18)
     ON CONFLICT(thread_id) DO UPDATE SET
       title=excluded.title, type=excluded.type, state=excluded.state, round=excluded.round,
       chair=excluded.chair, requester=excluded.requester, closed=excluded.closed,
       answered=excluded.answered, close_reason=excluded.close_reason, closed_at=excluded.closed_at,
       participants=excluded.participants, deadline=excluded.deadline, state_hash=excluded.state_hash,
       events_counted=excluded.events_counted, signature_bad=excluded.signature_bad,
       updated_at=excluded.updated_at, last_seq=excluded.last_seq`
  ).bind(
    threadId,
    genesis?.title ?? "",
    r.type ?? (genesis?.category ?? ""),
    r.state ?? null,
    r.round ?? null,
    r.chair ?? null,
    r.requester ?? null,
    r.state === "closed" ? 1 : 0,
    d.answered ? 1 : 0,
    r.close_reason ?? null,
    d.closedAt,
    d.participants,
    d.deadline,
    r.state_hash ?? null,
    rows.length,
    d.signatureBad,
    updatedAt,
    lastSeq,
  ).run();
}

/**
 * 고정창 속도 제한. 넘으면 남은 초를 준다.
 * ★IP 는 **원문을 저장하지 않는다** — 남용을 세려고 방문자 목록을 만들면 그 목록이 다음 사고다.
 */
export async function bumpRate(db: D1Database, bucket: string, windowSeconds: number,
                               limit: number, atMs = Date.now()): Promise<{ ok: boolean; retryAfter: number }> {
  const windowStart = Math.floor(atMs / 1000 / windowSeconds) * windowSeconds;
  // ★증가와 읽기를 **한 문장**으로 한다(RETURNING). 두 문장으로 나누면 그 사이에 다른 요청이
  //   끼어들어 같은 값을 읽거나 남의 차례를 자기 것으로 읽는다 — 상한이 조용히 새는 창이다
  //   (agy 지적 3 · 2026-09-05). 부수 효과로 질의가 2개에서 1개로 준다(호출당 50개 예산).
  const row = await db.prepare(
    `INSERT INTO rate_windows (bucket, window_start, count) VALUES (?1, ?2, 1)
     ON CONFLICT(bucket, window_start) DO UPDATE SET count = count + 1
     RETURNING count`
  ).bind(bucket, windowStart).first<{ count: number }>();
  const count = row?.count ?? 1;
  const retryAfter = windowStart + windowSeconds - Math.floor(atMs / 1000);
  return { ok: count <= limit, retryAfter: Math.max(1, retryAfter) };
}

