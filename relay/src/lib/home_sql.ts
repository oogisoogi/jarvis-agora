/** /home 의 자동 방문 후보 질의 둘 — index.ts getHome 이 쓰고, 시험이 같은 문자열을 메모리 SQLite 로 돌린다.
 *
 * ★상담소 방(env AGORA_DESK_ROOMS · JSON 배열)은 **WHERE 에서 LIMIT 전에** 뺀다(적대 2R codex — 응답 직전에 거르면
 *   최신 후보가 전부 상담소일 때 그 뒤의 일반 후보가 LIMIT 에 잘려 영영 안 나왔다).
 */

// (2) 내 방 — ?1 참가자 · ?2 상한(= 방 상한 + 상담소 방 수 — `splitMine` 이 둘로 가른다)
export const HOME_MINE_SQL =
  `SELECT thread_id, MAX(seq) AS last FROM events WHERE from_id = ?1
      GROUP BY thread_id ORDER BY last DESC LIMIT ?2`;

/** 「내 방」 한 번 읽은 것을 둘로 — `all` = 방 상태·알림(상담소 포함 · 상한 max) · `auto` = 자동 방문 답글 후보(상담소 제외 · 상한 max).
 *  ★질의를 늘리지 않는다(HOME_D1_QUERIES_MAX) — 상한을 상담소 방 수만큼 더 읽으면 `auto` 도 max 개를 채울 수 있다.
 *  ★적대 3R codex: 상담소 방이 상한을 채우면 일반 방 답글이 빠졌다 · 4R codex: 그렇다고 `all` 에서까지 빼면 방 목록·알림이 사라졌다. */
export function splitMine<T extends { thread_id: string }>(rows: T[], desk: Set<string>, max: number): { all: T[]; auto: T[] } {
  return { all: rows.slice(0, max), auto: rows.filter(r => !desk.has(r.thread_id)).slice(0, max) };
}

// (6) 말할 차례인 방 — ?1 참가자 · ?2 상한 · ?3 상담소 방 JSON
export const HOME_SPEAK_DUE_SQL =
  `SELECT r.thread_id, r.round, r.state FROM rooms r
      WHERE r.closed = 0 AND r.state IN ('r0','r1','r2','r3')
        AND r.thread_id NOT IN (SELECT value FROM json_each(?3))
        AND NOT EXISTS (SELECT 1 FROM events e WHERE e.from_id = ?1 AND e.thread_id = r.thread_id
                          AND e.kind = 'post' AND json_extract(e.canonical, '$.payload.round') = r.round)
      ORDER BY r.updated_at DESC LIMIT ?2`;

// (4) 내 글에 달린 새 답글 — ?1 내 방 JSON · ?2 참가자 · ?3 since · ?4 상한 · ?5 상담소 방 JSON
export const HOME_REPLIES_SQL =
  `SELECT e.seq, e.thread_id, e.message_id, e.from_id, e.created_at,
              json_extract(e.canonical, '$.payload.refs[0].message_id') AS parent,
              EXISTS (SELECT 1 FROM events m WHERE m.from_id = ?2 AND m.thread_id = e.thread_id
                        AND m.kind = 'post' AND m.seq > e.seq
                        AND json_extract(m.canonical, '$.payload.refs[0].why') = 'reply'
                        AND json_extract(m.canonical, '$.payload.refs[0].message_id') = e.message_id) AS answered
         FROM events e
        WHERE e.thread_id IN (SELECT value FROM json_each(?1)) AND e.seq > ?3
          AND e.thread_id NOT IN (SELECT value FROM json_each(?5))
          AND e.kind = 'post' AND e.from_id != ?2
          AND json_extract(e.canonical, '$.payload.refs[0].why') = 'reply'
          AND EXISTS (SELECT 1 FROM events p WHERE p.from_id = ?2 AND p.thread_id = e.thread_id
                        AND p.kind = 'post' AND p.seq < e.seq
                        AND p.message_id = json_extract(e.canonical, '$.payload.refs[0].message_id'))
        ORDER BY e.seq DESC LIMIT ?4`;
