/**
 * 아고라 릴레이 — 계약 정본 = docs/RELAY.md
 *
 * 이 파일이 지키는 경계(§1):
 *   · 서버가 거절하는 것 = **이벤트 한 건만 보고 답할 수 있는 것**뿐이다.
 *   · 사슬에 의존하는 판정(CAS·경합·권한·라운드·예산)은 **거절하지 않고 적재**한 뒤
 *     파생과 `verdict` 로 드러낸다(D-R1 · PROTOCOL §3 의 stale 을 보존하기 위해).
 *   · 서버에 **개인키가 없다.** 서명 코드가 이 저장소 어디에도 없어야 한다.
 */
import { AgoraError, ARGUMENT, GATE_REJECT, PERMISSION, SIGNATURE, STATE_CONFLICT, STORE, fail } from "./lib/errors.ts";
import { canonicalBytes, isId } from "./lib/canonical.ts";
import { prefersHtml } from "./lib/accept.ts";
import { parsePost, renderPost } from "./lib/post.ts";
import * as schema from "./lib/schema.ts";
import * as scrub from "./lib/scrub.ts";
import { b64decode, checkSignatureBytes, fingerprintOf, hasArmor, parseArmored,
         parsePublicKeyBlob } from "./lib/sshsig.ts";
import { bumpRate, deriveThread, eventIdOf, nowIso, rosterView, threadEvents,
         upsertRoom, type Env } from "./lib/store.ts";
import { FEED_SORTS, feed, isCommunity, replyParent, type FeedEvent, type FeedSort } from "./lib/feed.ts";
import { communityBuckets, isNewParticipant, limitsFromEnv } from "./lib/limits.ts";

// 저장소의 **정본 규칙 파일**을 원문 그대로 싣는다(wrangler rules: Text).
import rulesText from "../../config/scrub-rules-v1.json";
import allowText from "../../config/allowlist-v1.json";
import domainsText from "../../config/allow-domains.txt";

const REGISTER_PURPOSE = "agora-register-v1";

// ── 속도 상한(docs/RELAY.md §7) ────────────────────────────────────────────
// ★값의 근거는 **실측된 사용 형태**다(2026-09-05). 토론 한 바퀴에서 의장 한 사람이
//   genesis·advance 3회·resolution·close = 6회를 **몇 초 안에** 쓴다. 처음에 둔 분당 10회는
//   그 정상 동작을 429 로 막았다(골든 세트 4 가 중간에서 잘렸다).
//   ⇒ 시험을 위해 상한을 푼 것이 아니라, **상한이 실제 동작과 안 맞았던 것**이다.
// ⚠등록 IP 상한은 워크숍처럼 **여럿이 한 회선(NAT)** 뒤에 있을 때 정상 참가자를 막는다.
//   그 판단은 운영 결정이라 값만 올려 두고 master 게이트로 올린다(RELAY.md §7 각주).
// 등록 전체 상한 = 시간당 300. 근거: 워크숍 한 자리(수십 명)가 한 시간 안에 다 등록해도 여유가 있고,
// 그 위로는 사람 손이 아니라 자동화라고 볼 수 있는 구간이다. 등록 1건에는 키 생성 + 서명이 이미 든다.
const REGISTER_GLOBAL_HOUR = 300;
const EVENTS_PER_PID_MIN = 30;
const EVENTS_PER_ROOM_MIN = 120;

let bundleCache: scrub.ScrubBundle | null = null;
async function scrubBundle(): Promise<scrub.ScrubBundle> {
  if (!bundleCache) {
    bundleCache = await scrub.loadBundle(rulesText as unknown as string,
                                         allowText as unknown as string,
                                         domainsText as unknown as string);
  }
  return bundleCache;
}

// ── 응답 도우미 ────────────────────────────────────────────────────────────
function corsHeaders(req: Request, env: Env): Record<string, string> {
  const origin = req.headers.get("Origin");
  if (!origin) return {};
  const allowed = (env.CORS_ALLOW_ORIGINS || "").split(",").map(s => s.trim()).filter(Boolean);
  const ok = allowed.includes(origin)
    || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  if (!ok) return {};
  // ★읽기 경로에만 붙인다. 쓰기에 열면 보드를 연 브라우저가 쓰기 경로의 발판이 된다.
  return { "Access-Control-Allow-Origin": origin, "Vary": "Origin",
           "Access-Control-Allow-Methods": "GET" };
}

function json(data: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data, null, 2) + "\n",
    { status, headers: { "content-type": "application/json; charset=utf-8", ...headers } });
}

function text(body: string, headers: Record<string, string> = {}): Response {
  return new Response(body, { status: 200,
    headers: { "content-type": "text/plain; charset=utf-8", ...headers } });
}

function errorResponse(e: unknown): Response {
  if (e instanceof AgoraError) {
    return json(e.toBody(), e.status, e.headers);
  }
  const msg = e instanceof Error ? e.message : String(e);
  // 알 수 없는 실패는 저장층 오류(7)로 낸다 — 재시도 가능하다고 말하는 쪽이 정직하다.
  return json({ code: STORE, name: "store", message: "릴레이 내부 실패", detail: { error: msg.slice(0, 200) } }, 500);
}

async function readJson(req: Request): Promise<Record<string, unknown>> {
  let body: unknown;
  try { body = await req.json(); }
  catch { return fail(ARGUMENT, "본문이 JSON 이 아니다", null); }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    fail(ARGUMENT, "본문은 객체여야 한다", null);
  }
  return body as Record<string, unknown>;
}

function needStr(o: Record<string, unknown>, key: string): string {
  const v = o[key];
  if (typeof v !== "string" || !v) fail(ARGUMENT, "필수 칸 누락", { key });
  return v;
}

// ── POST /register ─────────────────────────────────────────────────────────
async function handleRegister(req: Request, env: Env): Promise<Response> {
  // ★등록에 **IP 축을 두지 않는다**(master 판정 2026-09-05 · 선택지 ⓒ).
  //   IP 상한은 공격자에게 약하고(주소를 바꾸면 그만) 정상 사용자에게만 강하다 —
  //   워크숍처럼 여럿이 한 회선(NAT) 뒤에 있으면 릴레이에는 한 사람으로 보여
  //   n+1 번째부터 **정상 참가자가 막힌다.** 남는 방어는 소유 증명 서명(필수)·전체 상한·폐기·abort 다.
  //   ⇒ 부수 효과: IP 를 아예 안 만지므로 해시용 비밀(RATE_SALT)도 필요 없어졌다.
  const global = await bumpRate(env.DB, "reg:all", 3600, REGISTER_GLOBAL_HOUR);
  if (!global.ok) {
    fail(STORE, "등록 속도 제한(전체)", { limit: "global", per: "hour" },
      { status: 429, headers: { "Retry-After": String(global.retryAfter) } });
  }

  const body = await readJson(req);
  const participantId = needStr(body, "participant_id");
  const displayName = needStr(body, "display_name");
  const publicKey = needStr(body, "public_key");
  const claimedFp = needStr(body, "fingerprint");
  const signature = needStr(body, "signature");

  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$/.test(participantId)) {
    fail(ARGUMENT, "participant_id 형식이 아니다", { want: "영숫자·.-_ 2~64자" });
  }
  const parts = publicKey.trim().split(/\s+/);
  if (parts.length < 2 || parts[0] !== "ssh-ed25519") {
    fail(ARGUMENT, "ssh-ed25519 공개키만 받는다(v1)", { got: parts[0] ?? null });
  }
  let blob: Uint8Array;
  try { blob = b64decode(parts[1]); }
  catch { return fail(ARGUMENT, "공개키 base64 해독 실패", null); }
  const parsedKey = parsePublicKeyBlob(blob);
  if (parsedKey.type !== "ssh-ed25519" || parsedKey.key.length !== 32) {
    fail(ARGUMENT, "공개키 blob 이 ed25519 가 아니다", null);
  }
  const fingerprint = await fingerprintOf(blob);
  if (fingerprint !== claimedFp) {
    // 서버가 스스로 계산한 값이 정본이다.
    fail(ARGUMENT, "지문이 공개키와 맞지 않는다", { computed: fingerprint });
  }

  // ★소유 증명 — 등록하려는 **그 키로** 만든 서명이어야 한다(D-R6 · master 승인).
  //   증명이 없으면 남의 공개키를 내 이름으로 등재할 수 있고, 신원 선점 방어가 무의미해진다.
  if (!hasArmor(signature)) fail(SIGNATURE, "소유 증명 서명이 없다", null);
  const message = canonicalBytes({
    display_name: displayName, fingerprint, participant_id: participantId,
    public_key: publicKey.trim(), purpose: REGISTER_PURPOSE,
  });
  const checked = await checkSignatureBytes(message, parseArmored(signature), env.AGORA_NAMESPACE);
  if (!checked.ok) fail(SIGNATURE, "소유 증명 서명이 유효하지 않다", { why: checked.why });
  if (checked.fingerprint !== fingerprint) {
    fail(SIGNATURE, "소유 증명이 다른 키로 만들어졌다", { signed_by: checked.fingerprint });
  }

  const byId = await env.DB.prepare(
    "SELECT participant_id, fingerprint, revoked_at, created_at FROM participants WHERE participant_id = ?1"
  ).bind(participantId).first<{ participant_id: string; fingerprint: string; revoked_at: string | null; created_at: string }>();
  if (byId) {
    if (byId.revoked_at) fail(PERMISSION, "폐기된 참가자다", { participant_id: participantId }, { status: 403 });
    if (byId.fingerprint === fingerprint) {
      // 멱등 — 설치를 두 번 돌리는 것이 사고가 되지 않게.
      // ★본문은 201 과 **같은 세 칸**이다. 「이미 있음」은 **코드 200 이 말한다**(master 판정 2026-09-05).
      //   계약(§3-1)이 이름을 준 성공 본문이 그 셋뿐이라, 칸을 하나 더 실으면 계약을 읽고 대조하는
      //   설치기 쪽이 「계약 밖 칸」으로 적색을 낸다 — 실제로 라이브에서 그렇게 났다.
      return json({ participant_id: participantId, fingerprint, created_at: byId.created_at }, 200);
    }
    fail(GATE_REJECT, "이미 등록된 이름이다(다른 키)", { participant_id: participantId }, { status: 409 });
  }
  const byFp = await env.DB.prepare(
    "SELECT participant_id FROM participants WHERE fingerprint = ?1"
  ).bind(fingerprint).first<{ participant_id: string }>();
  if (byFp) {
    // 한 키는 한 이름만 가진다 — 보드에서 같은 지문이 두 이름으로 보이지 않게.
    fail(GATE_REJECT, "이 키는 이미 다른 이름으로 등록돼 있다", { existing: byFp.participant_id }, { status: 409 });
  }

  const createdAt = nowIso();
  await env.DB.prepare(
    `INSERT INTO participants (participant_id, display_name, key_type, key_b64, fingerprint, is_operator, revoked_at, created_at)
     VALUES (?1,?2,?3,?4,?5,0,NULL,?6)`
  ).bind(participantId, displayName, parts[0], parts[1], fingerprint, createdAt).run();
  // ★성공 본문은 계약(§3-1)이 명명한 칸만 싣는다 — 「새로 만들었다」는 **코드 201 이 말한다**.
  //   200 만 고치고 여기를 남겨 두어 설치기 대조가 계속 적색이었다(2026-09-05 master 적발 · 스윕 누락).
  return json({ participant_id: participantId, fingerprint, created_at: createdAt }, 201);
}

// ── POST /events ───────────────────────────────────────────────────────────
async function handleEvents(req: Request, env: Env): Promise<Response> {
  const body = await readJson(req);
  const threadId = needStr(body, "thread_id");
  const category = needStr(body, "category");
  const title = typeof body["title"] === "string" ? body["title"] as string : "";
  const postBody = needStr(body, "body");
  const isGenesis = body["is_genesis"] === true;

  if (!isId(threadId)) fail(ARGUMENT, "thread_id 형식이 아니다", { thread_id: threadId });
  if (!(schema.THREAD_TYPES as readonly string[]).includes(category)) {
    fail(ARGUMENT, "category 가 계약 밖", { category, allowed: schema.THREAD_TYPES });
  }

  // (1)(2) 크기·서식 — parsePost 안에서 canonical 로 다시 만들며 상한도 본다.
  const parsed = parsePost(postBody);
  const event = parsed.event as Record<string, any>;

  // (3) 스키마 9종 닫힌 검증
  schema.validate(event);

  // (4) 스레드 결박 · (5) is_genesis 정합
  if (event.thread_id !== threadId) {
    fail(ARGUMENT, "이벤트의 thread_id 가 인자와 다르다",
      { arg: threadId, event: event.thread_id });
  }
  if ((event.kind === "genesis") !== isGenesis) {
    fail(ARGUMENT, "is_genesis 가 이벤트 kind 와 맞지 않다",
      { is_genesis: isGenesis, kind: event.kind });
  }
  if (isGenesis && event.payload.type !== category) {
    fail(ARGUMENT, "category 가 genesis 의 유형과 다르다",
      { category, type: event.payload.type });
  }
  // ★★래퍼의 `title` 은 **서명 대상이 아니다.** 그대로 저장하면 보드에 뜨는 방 제목을
  //   서명 밖에서 바꿔치기할 수 있다(agy 2라운드 지적 2). 서명된 값과 같을 때만 받는다.
  if (isGenesis && title !== event.payload.title) {
    fail(ARGUMENT, "title 이 서명된 제목과 다르다",
      { arg: title, signed: event.payload.title });
  }

  // (6) 서명·명부·폐기 — ★**스크럽보다 먼저** 한다(agy 2라운드 지적 3).
  //   스크럽은 정규식 다발이라 상대적으로 비싸다. 서명 없는 쓰레기를 그 앞에 통과시키면
  //   **아무나 서버 CPU 를 태울 수 있다.** 서명 검증은 고정 비용이고 자격을 먼저 가른다.
  const roster = await rosterView(env.DB);
  if (!hasArmor(parsed.signature)) fail(SIGNATURE, "서명이 없다", { from: event.from });
  const sig = parseArmored(parsed.signature as string);
  const checked = await checkSignatureBytes(parsed.raw, sig, env.AGORA_NAMESPACE);
  if (!checked.ok) {
    const bad = checked.why === "signature_does_not_match_bytes";
    fail(SIGNATURE, bad ? "서명이 본문과 맞지 않는다(BAD)" : "서명을 받아들일 수 없다",
      { verdict: bad ? "BAD" : "unsigned", why: checked.why });
  }
  const entry = roster.lookup(checked.fingerprint!);
  if (!entry) fail(SIGNATURE, "명부에 없는 키다", { verdict: "unsigned", why: "not_in_roster" });
  if (entry.revoked) fail(SIGNATURE, "폐기된 키다", { verdict: "unsigned", why: "revoked" });
  if (entry.principal !== event.from) {
    fail(SIGNATURE, "그 키는 이 참가자의 키가 아니다",
      { verdict: "unsigned", why: "principal_mismatch" });
  }

  // (7) 봉투·스크럽 백스톱 — fail-closed. 자격을 가른 뒤에 내용을 본다.
  const bundle = await scrubBundle();
  scrub.enforce(event.payload, bundle);

  // (8) 멱등 — 같은 (from, message_id) + 같은 해시는 새 행을 만들지 않는다.
  // ★★속도 제한**보다 먼저** 본다(agy 지적 2 · 2026-09-05). 뒤에 두면 **재시도가 발언 예산을 깎는다** —
  //   응답을 못 받아 다시 보내는 것은 새 발언이 아닌데도 예산이 준다. 그러면 「재시도가 안전하다」는
  //   계약(§3-2 · code 8 을 「재조회로 판정하라」고 말할 자격)이 무너진다.
  //   ⚠받아들인 대가: 같은 요청을 무한 반복하면 쓰기 상한을 안 태운다. 대신 그 요청은
  //   **아무것도 쓰지 않고**(행 0) 유효 서명까지 필요하다 — 남는 비용은 조회뿐이다.
  const existing = await env.DB.prepare(
    "SELECT seq, hash, created_at FROM events WHERE from_id = ?1 AND message_id = ?2"
  ).bind(event.from, event.message_id).first<{ seq: number; hash: string; created_at: string }>();
  const hash = await hashOf(parsed.raw);
  if (existing) {
    if (existing.hash === hash) {
      return json({
        event_id: eventIdOf(existing.seq),
        url: roomUrl(req, threadId, event.message_id),
        created_at: existing.created_at,
      }, 200);
    }
    // 재시도가 아니라 **다른 글**이다. 새 message_id 로 써야 한다.
    fail(GATE_REJECT, "같은 message_id 로 다른 내용을 보냈다",
      { conflict: "message_id_reused", message_id: event.message_id }, { status: 422 });
  }

  // (9) 속도 — 참가자·방. **새 이벤트일 때만** 예산을 쓴다(위 멱등 반환을 지나온 요청).
  const perPid = await bumpRate(env.DB, "pid:" + event.from, 60, EVENTS_PER_PID_MIN);
  if (!perPid.ok) {
    fail(STORE, "발언 속도 제한", { limit: "participant", per: "minute" },
      { status: 429, headers: { "Retry-After": String(perPid.retryAfter) } });
  }
  const perRoom = await bumpRate(env.DB, "room:" + threadId, 60, EVENTS_PER_ROOM_MIN);
  if (!perRoom.ok) {
    fail(STORE, "방 속도 제한", { limit: "room", per: "minute" },
      { status: 429, headers: { "Retry-After": String(perRoom.retryAfter) } });
  }

  // (9b) 전역 상한(광장 v2 · 명세 D) — **커뮤니티 방의 post 만**(판별 = isCommunity · master 판정 B).
  //   ★의장 기계의 genesis·advance·resolution·close 와 일반 토론방 글은 여기 안 걸린다(골든 세트4 가 잰다).
  //   ★거절이지 격리가 아니다 — 원장에 안 들어가므로 참가자마다 상태가 갈라지지 않는다.
  if (event.kind === "post") {
    const g = await env.DB.prepare(
      "SELECT canonical FROM events WHERE thread_id = ?1 AND is_genesis = 1 ORDER BY seq LIMIT 1"
    ).bind(threadId).first<{ canonical: string }>();
    if (g && isCommunity(genesisPayloadOf(g.canonical))) {
      const limits = limitsFromEnv(env as unknown as Record<string, unknown>);
      const me = roster.rows.find(r => r.participant_id === event.from);
      const isNew = isNewParticipant(me?.created_at, Date.now(), limits);
      const kind = replyParent(event) ? "reply" : "post";
      for (const b of communityBuckets(kind, event.from, isNew, limits)) {
        const r = await bumpRate(env.DB, b.bucket, b.windowS, b.max);
        if (!r.ok) {
          fail(STORE, "커뮤니티 속도 제한", { limit: b.label, window_s: b.windowS, max: b.max },
            { status: 429, headers: { "Retry-After": String(r.retryAfter) } });
        }
      }
    }
  }

  // (10) 적재
  const createdAt = nowIso();
  let inserted: { seq: number } | null = null;
  try {
    inserted = await env.DB.prepare(
    `INSERT INTO events (thread_id, message_id, from_id, kind, prev, hash, canonical, signature,
       category, title, is_genesis, created_at)
     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12) RETURNING seq`
    ).bind(threadId, event.message_id, event.from, event.kind, event.prev, hash, parsed.canonical,
           parsed.signature, category, title, isGenesis ? 1 : 0, createdAt)
     .first<{ seq: number }>();
  } catch (e) {
    // ★동시에 **같은** 이벤트가 둘 들어오면 하나는 UNIQUE(from,message_id) 에 걸린다.
    //   그것은 실패가 아니라 **멱등이 뒤늦게 성립한 것**이다 — 500 으로 내보내면
    //   호출자는 재시도해야 할지 말지 알 수 없다(agy 2라운드 논쟁점 3).
    const again = await env.DB.prepare(
      "SELECT seq, hash, created_at FROM events WHERE from_id = ?1 AND message_id = ?2"
    ).bind(event.from, event.message_id).first<{ seq: number; hash: string; created_at: string }>();
    if (again && again.hash === hash) {
      return json({
        event_id: eventIdOf(again.seq),
        url: roomUrl(req, threadId, event.message_id),
        created_at: again.created_at,
      }, 200);
    }
    throw e;
  }
  if (!inserted) fail(STORE, "적재 결과를 읽지 못했다", null);

  // (11) 파생 — 원장은 그대로 두고 **판정만** 드러낸다.
  const { derived, rows } = await deriveThread({
    db: env.DB, threadId, namespace: env.AGORA_NAMESPACE, roster,
    scrubBundle: bundle.bundle, now: createdAt, render: renderPost,
  });
  // ★updated_at 은 적재마다 갱신된다(격리분 포함) — 안 그러면 폴링이 조용히 눈이 먼다.
  await upsertRoom(env.DB, threadId, derived, rows, createdAt);

  const myId = eventIdOf(inserted.seq);
  const accepted = (derived.reduced.events ?? []).some(e => e.node_id === myId);
  const q = (derived.reduced.quarantined ?? []).find(x => x.node_id === myId);
  const st = (derived.reduced.stale ?? []).find(x => x.node_id === myId);
  return json({
    event_id: myId,
    url: roomUrl(req, threadId, event.message_id),
    created_at: createdAt,
    // 참고용 파생 판정. 무시해도 되고, 무시해도 정본은 안 바뀐다.
    verdict: {
      accepted_to_ledger: true,
      reducer: accepted ? "accepted" : q ? "quarantined" : st ? "stale" : "unknown",
      reason: q?.reason ?? st?.reason ?? null,
      state_hash: derived.reduced.state_hash ?? null,
    },
  }, 201);
}

async function hashOf(raw: Uint8Array): Promise<string> {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", raw as BufferSource));
  let s = "";
  for (const b of d) s += b.toString(16).padStart(2, "0");
  return s;
}

function roomUrl(req: Request, threadId: string, messageId: string): string {
  const u = new URL(req.url);
  return `${u.origin}/rooms/${threadId}#${messageId}`;
}

// ── GET /rooms ─────────────────────────────────────────────────────────────
async function listRooms(req: Request, env: Env): Promise<Response> {
  const u = new URL(req.url);
  const limit = Math.min(Math.max(parseInt(u.searchParams.get("limit") || "50", 10) || 50, 1), 100);
  const updatedSince = u.searchParams.get("updated_since");
  const closed = u.searchParams.get("closed") === "1";
  const cursor = u.searchParams.get("cursor");

  // 질의 1개 — 방 개수에 비례하는 질의를 쓰지 않는다(무료 D1 = 호출당 50개).
  const where: string[] = ["closed = ?1"];
  const binds: unknown[] = [closed ? 1 : 0];
  if (updatedSince) { binds.push(updatedSince); where.push(`updated_at > ?${binds.length}`); }
  if (cursor) { binds.push(cursor); where.push(`updated_at < ?${binds.length}`); }
  binds.push(limit + 1);
  const sql = `SELECT thread_id, title, type, state, round, chair, requester, closed, answered,
      close_reason, closed_at, participants, deadline, state_hash, events_counted, signature_bad,
      updated_at, last_seq
    FROM rooms WHERE ${where.join(" AND ")} ORDER BY updated_at DESC LIMIT ?${binds.length}`;
  const res = await env.DB.prepare(sql).bind(...binds).all<any>();
  const rows = res.results ?? [];
  const page = rows.slice(0, limit);
  return json({
    items: page.map(r => ({
      // 클라이언트 계약 4칸
      room_id: r.thread_id,
      node_id: eventIdOf(r.last_seq),
      updated_at: r.updated_at,
      title: r.title,
      // 보드용 파생 덧칸 — 상태의 근거로 쓰면 안 된다(정본은 서명된 이벤트다).
      type: r.type, chair: r.chair, participants: r.participants,
      state: r.state, round: r.round, deadline: r.deadline,
      closed: !!r.closed, answered: !!r.answered,
      signature_all_ok: r.signature_bad === 0, signature_bad_count: r.signature_bad,
    })),
    next_cursor: rows.length > limit ? page[page.length - 1].updated_at : null,
  }, 200, corsHeaders(req, env));
}

// ── GET /rooms/:id ─────────────────────────────────────────────────────────
async function roomStatus(req: Request, env: Env, threadId: string): Promise<Response> {
  const rows = await threadEvents(env.DB, threadId);
  if (!rows.length) {
    // ★없는 방 = 404 + code 7. append-only 세계에서 「아직 안 올라온 방」과 구별되지 않는다.
    fail(STORE, "그 방이 아직 없다", { room_id: threadId }, { status: 404 });
  }
  const roster = await rosterView(env.DB);
  const bundle = await scrubBundle();
  const { derived } = await deriveThread({
    db: env.DB, threadId, namespace: env.AGORA_NAMESPACE, roster,
    scrubBundle: bundle.bundle, rows, render: renderPost,
  });
  const r = derived.reduced;

  // ★파생 캐시 자가치유(R-7): 캐시가 지워졌거나 낡았으면 이 조회가 다시 채운다.
  //   ⚠갱신이 **필요할 때만** 쓴다 — 읽을 때마다 쓰면 조회가 쓰기 증폭이 된다.
  const cached = await env.DB.prepare(
    "SELECT state_hash, events_counted FROM rooms WHERE thread_id = ?1"
  ).bind(threadId).first<{ state_hash: string | null; events_counted: number }>();
  if (!cached || cached.state_hash !== (r.state_hash ?? null)
      || cached.events_counted !== rows.length) {
    await upsertRoom(env.DB, threadId, derived, rows,
                     cached ? nowIso() : rows[rows.length - 1].created_at);
  }

  return json({
    // 클라이언트 계약 3칸(+closed_at)
    room_id: threadId,
    closed: r.state === "closed",
    answered: derived.answered,
    closed_at: derived.closedAt,
    // 3자 대조·보드용 덧칸
    state: r.state, close_reason: r.close_reason ?? null, type: r.type ?? null,
    chair: r.chair ?? null, requester: r.requester ?? null, round: r.round ?? null,
    title: rows.find(x => x.is_genesis === 1)?.title ?? "",
    deadline: derived.deadline,
    participants: derived.participants,
    state_hash: r.state_hash ?? null,
    events_counted: rows.length,
    // ★배지의 근거. 전건이 ok 일 때만 참이다 — 「대체로 맞음」에 켜면 배지가 거짓말을 시작한다.
    signature_all_ok: derived.signatureBad === 0,
    signature_bad_count: derived.signatureBad,
    derived_at: nowIso(),
  }, 200, corsHeaders(req, env));
}

// ── GET /rooms/:id/events ──────────────────────────────────────────────────
async function roomEvents(req: Request, env: Env, threadId: string): Promise<Response> {
  const u = new URL(req.url);
  const limit = Math.min(Math.max(parseInt(u.searchParams.get("limit") || "100", 10) || 100, 1), 200);
  const cursorSeq = parseInt(u.searchParams.get("cursor") || "0", 10) || 0;
  const audit = u.searchParams.get("audit") === "1";

  const all = await threadEvents(env.DB, threadId);
  if (!all.length) fail(STORE, "그 방이 아직 없다", { room_id: threadId }, { status: 404 });

  const roster = await rosterView(env.DB);
  const bundle = await scrubBundle();
  const { derived } = await deriveThread({
    db: env.DB, threadId, namespace: env.AGORA_NAMESPACE, roster,
    scrubBundle: bundle.bundle, rows: all, render: renderPost,
  });
  const acceptedIds = new Set((derived.reduced.events ?? []).map(e => e.node_id));
  const qMap = new Map((derived.reduced.quarantined ?? []).map(x => [x.node_id, x]));
  const sMap = new Map((derived.reduced.stale ?? []).map(x => [x.node_id, x]));

  // ★거르지 않는다 — 거르면 클라이언트 리듀서가 prev 를 못 찾아 멀쩡한 글을 「닿지 않음」으로 만든다.
  const page = all.filter(r => r.seq > cursorSeq).slice(0, limit);
  const items = page.map(r => {
    const id = eventIdOf(r.seq);
    const q = qMap.get(id);
    const s = sMap.get(id);
    const item: Record<string, unknown> = {
      event_id: id,
      created_at: r.created_at,
      body: renderPost(r.canonical, r.signature),
      is_genesis: r.is_genesis === 1,
      // 보드가 기본 화면에서 가릴 수 있게 파생 판정을 노출한다(계약 요구 3-①).
      // ⚠클라이언트는 **상태의 근거로 쓰면 안 된다** — 판정은 각자의 리듀서가 한다.
      valid: acceptedIds.has(id),
      quarantined: !!q,
      stale: !!s,
      reason: (q?.reason ?? s?.reason) ?? null,
    };
    if (audit && q) item.detail = q.detail ?? null;
    return item;
  });
  const last = page.length ? page[page.length - 1].seq : cursorSeq;
  const more = all.some(r => r.seq > last);
  return json({ items, next_cursor: more ? String(last) : null },
    200, corsHeaders(req, env));
}

// ── 광장 v2 읽기(명세 A1·A2·G) — ★전부 **캐시**다 ─────────────────────────────
// 응답의 글은 정본이 아니다. 클라이언트는 GET /rooms/:id/events 로 받아 서명·사슬을 **다시 검증**하고,
// 불일치면 버린다(PROTOCOL §0 「서버가 통과시킨 글도 격리할 수 있다」와 같은 원리).
const CACHE_NOTICE = "이 응답은 캐시다 — 글은 GET /rooms/:id/events 로 받아 서명·사슬을 다시 검증하고, 맞지 않으면 버린다.";
const COMMUNITIES_MAX = 50;          // 한 번에 돌려주는 커뮤니티 수
const COMMUNITY_SCAN_MAX = 100;      // 후보(열린 debate 방) 훑기 상한 — json_each 한 번에 넘긴다
const FEED_ROOMS_MAX = 10;           // 피드 한 번에 접는 방 수
const FEED_ITEMS_MAX = 50;
const HOME_ROOMS_MAX = 10;           // /home 이 보는 「내 방」 수
const HOME_ITEMS_MAX = 50;
// ★호출당 D1 질의 상한(무료 D1 = 호출당 50). 넘으면 503 — 무한 스캔을 구조로 막는다.
const COMMUNITIES_D1_QUERIES_MAX = 2;
const FEED_D1_QUERIES_MAX = 2 + 1 + FEED_ROOMS_MAX;
const HOME_D1_QUERIES_MAX = 6;
// 알림 후보 = **원장 사실(kind)** 로만(명세 C · 작성자 판단 채택). 글 본문 문구로는 발동하지 않는다.
const NOTIFY_KINDS: Record<string, string> = {
  resolution: "내가 참가한 방에 권고가 도착했다(집행은 주인 승인)",
};

/** D1 질의를 세고 상한을 넘으면 거절한다 — 상한이 주석이 아니라 동작이 되게. */
class QueryBudget {
  used = 0;
  constructor(private db: D1Database, readonly max: number) {}
  prepare(sql: string): D1PreparedStatement {
    this.used += 1;
    if (this.used > this.max) {
      fail(STORE, "이 경로의 D1 질의 상한을 넘었다", { max: this.max }, { status: 503 });
    }
    return this.db.prepare(sql);
  }
  get asDb(): D1Database { return this as unknown as D1Database; }
}

function genesisPayloadOf(canonical: string): unknown {
  try { return (JSON.parse(canonical) as Record<string, any>)?.payload ?? null; }
  catch { return null; }
}

function intParam(u: URL, name: string, dflt: number, hi: number): number {
  const v = parseInt(u.searchParams.get(name) || String(dflt), 10);
  return Math.min(Math.max(Number.isFinite(v) ? v : dflt, 1), hi);
}

/** 커뮤니티 방 목록(질의 2개). 판별은 isCommunity 한 곳(정본 plaza.is_community). */
async function communityRooms(qb: QueryBudget, limit: number): Promise<any[]> {
  const cand = (await qb.prepare(
    `SELECT thread_id, title, chair, participants, state, round, updated_at, last_seq
       FROM rooms WHERE type = 'debate' AND closed = 0 ORDER BY updated_at DESC LIMIT ?1`
  ).bind(COMMUNITY_SCAN_MAX).all<any>()).results ?? [];
  if (!cand.length) return [];
  const gen = (await qb.prepare(
    `SELECT thread_id, canonical FROM events
      WHERE is_genesis = 1 AND thread_id IN (SELECT value FROM json_each(?1)) ORDER BY seq`
  ).bind(JSON.stringify(cand.map(r => r.thread_id))).all<{ thread_id: string; canonical: string }>()).results ?? [];
  const first = new Map<string, unknown>();
  for (const g of gen) if (!first.has(g.thread_id)) first.set(g.thread_id, genesisPayloadOf(g.canonical));
  return cand.filter(r => isCommunity(first.get(r.thread_id))).slice(0, limit)
    .map(r => ({ ...r, budget: (first.get(r.thread_id) as any)?.budget ?? null }));
}

async function listCommunities(req: Request, env: Env): Promise<Response> {
  const u = new URL(req.url);
  const qb = new QueryBudget(env.DB, COMMUNITIES_D1_QUERIES_MAX);
  const rows = await communityRooms(qb, intParam(u, "limit", COMMUNITIES_MAX, COMMUNITIES_MAX));
  return json({
    items: rows.map(r => ({
      room_id: r.thread_id, title: r.title, chair: r.chair, participants: r.participants,
      state: r.state, updated_at: r.updated_at, node_id: eventIdOf(r.last_seq), budget: r.budget,
    })),
    rule: "debate · deadlines 없음 · budget 있음",
    cache: true, verify: CACHE_NOTICE,
    limits: { d1_queries_used: qb.used, d1_queries_max: qb.max, scan_max: COMMUNITY_SCAN_MAX },
  }, 200, corsHeaders(req, env));
}

async function getFeed(req: Request, env: Env): Promise<Response> {
  const u = new URL(req.url);
  const sort = u.searchParams.get("sort") || "new";
  if (!(FEED_SORTS as readonly string[]).includes(sort)) {
    fail(ARGUMENT, "sort 는 new·hot·top 중 하나다", { sort, allowed: FEED_SORTS });
  }
  const limit = intParam(u, "limit", 20, FEED_ITEMS_MAX);
  const qb = new QueryBudget(env.DB, FEED_D1_QUERIES_MAX);
  const rooms = await communityRooms(qb, FEED_ROOMS_MAX);
  const roster = await rosterView(qb.asDb);
  const bundle = await scrubBundle();
  const now = nowIso();
  const input: Array<[string, FeedEvent[]]> = [];
  for (const r of rooms) {
    const rows = await threadEvents(qb.asDb, r.thread_id);
    const { derived } = await deriveThread({
      db: qb.asDb, threadId: r.thread_id, namespace: env.AGORA_NAMESPACE, roster,
      scrubBundle: bundle.bundle, rows, now, render: renderPost,
    });
    // ★받아들여진 이벤트만 — 격리·stale 은 피드에 안 오른다(클라이언트 리듀서와 같은 입력).
    input.push([r.thread_id, (derived.reduced.events ?? []).map(e => ({ created_at: e.created_at, event: e.event }))]);
  }
  const items = feed(input, sort as FeedSort, Date.parse(now)).slice(0, limit);
  return json({
    sort, items, rooms: rooms.map(r => r.thread_id),
    rule: "정본 = tools/plaza.py feed · 추천이 많다고 참은 아니다",
    cache: true, verify: CACHE_NOTICE, derived_at: now,
    limits: { d1_queries_used: qb.used, d1_queries_max: qb.max, rooms_max: FEED_ROOMS_MAX, items_max: FEED_ITEMS_MAX },
  }, 200, corsHeaders(req, env));
}

async function getHome(req: Request, env: Env): Promise<Response> {
  const u = new URL(req.url);
  const who = u.searchParams.get("participant") || "";
  if (!who) fail(ARGUMENT, "participant 가 필요하다(참가자 id 또는 공개키 지문 SHA256:…)", null);
  const since = Math.max(parseInt(u.searchParams.get("since") || "0", 10) || 0, 0);
  const qb = new QueryBudget(env.DB, HOME_D1_QUERIES_MAX);

  // (1) 참가자 — id 또는 지문(신원 = 공개키 지문 · 명세 E)
  const me = await qb.prepare(
    "SELECT participant_id, fingerprint, revoked_at FROM participants WHERE participant_id = ?1 OR fingerprint = ?1"
  ).bind(who).first<{ participant_id: string; fingerprint: string; revoked_at: string | null }>();
  if (!me) fail(STORE, "그런 참가자가 없다", { participant: who }, { status: 404 });
  const pid = me.participant_id;

  // (2) 내 방 — 내가 한 번이라도 쓴 방(최근 순 · 상한)
  const mine = (await qb.prepare(
    `SELECT thread_id, MAX(seq) AS last FROM events WHERE from_id = ?1
      GROUP BY thread_id ORDER BY last DESC LIMIT ?2`
  ).bind(pid, HOME_ROOMS_MAX).all<{ thread_id: string; last: number }>()).results ?? [];
  const ids = JSON.stringify(mine.map(r => r.thread_id));

  // (6) 말할 차례인 방 — 열린 토론 회차(r0~r3)인데 **이 회차에 내 post 가 없는** 방(상주 목적 speak 의 후보).
  //   ★「내 방」만이 아니라 열린 방 전체에서 고른다 — 상주는 아직 한 번도 안 쓴 방에서도 깨워야 한다.
  const speakDue = (await qb.prepare(
    `SELECT r.thread_id, r.round, r.state FROM rooms r
      WHERE r.closed = 0 AND r.state IN ('r0','r1','r2','r3')
        AND NOT EXISTS (SELECT 1 FROM events e WHERE e.from_id = ?1 AND e.thread_id = r.thread_id
                          AND e.kind = 'post' AND json_extract(e.canonical, '$.payload.round') = r.round)
      ORDER BY r.updated_at DESC LIMIT ?2`
  ).bind(pid, HOME_ITEMS_MAX).all<{ thread_id: string; round: number; state: string }>()).results ?? [];

  let rooms: any[] = [], replies: any[] = [], notes: any[] = [];
  if (mine.length) {
    // (3) 방 상태(캐시)
    rooms = (await qb.prepare(
      `SELECT thread_id, title, type, state, round, closed, updated_at, last_seq FROM rooms
        WHERE thread_id IN (SELECT value FROM json_each(?1)) ORDER BY updated_at DESC`
    ).bind(ids).all<any>()).results ?? [];
    // (4) 내 글에 달린 새 답글 — 부모가 **같은 방·먼저 적재된 내 post** 일 때만(plaza.feed 와 같은 조건)
    replies = (await qb.prepare(
      `SELECT e.seq, e.thread_id, e.message_id, e.from_id, e.created_at,
              json_extract(e.canonical, '$.payload.refs[0].message_id') AS parent,
              EXISTS (SELECT 1 FROM events m WHERE m.from_id = ?2 AND m.thread_id = e.thread_id
                        AND m.kind = 'post' AND m.seq > e.seq
                        AND json_extract(m.canonical, '$.payload.refs[0].message_id') = e.message_id) AS answered
         FROM events e
        WHERE e.thread_id IN (SELECT value FROM json_each(?1)) AND e.seq > ?3
          AND e.kind = 'post' AND e.from_id != ?2
          AND json_extract(e.canonical, '$.payload.refs[0].why') = 'reply'
          AND EXISTS (SELECT 1 FROM events p WHERE p.from_id = ?2 AND p.thread_id = e.thread_id
                        AND p.kind = 'post' AND p.seq < e.seq
                        AND p.message_id = json_extract(e.canonical, '$.payload.refs[0].message_id'))
        ORDER BY e.seq DESC LIMIT ?4`
    ).bind(ids, pid, since, HOME_ITEMS_MAX).all<any>()).results ?? [];
    // (5) 알림 후보 — kind 로만
    notes = (await qb.prepare(
      `SELECT seq, thread_id, kind, from_id, created_at FROM events
        WHERE thread_id IN (SELECT value FROM json_each(?1)) AND seq > ?2
          AND kind IN (SELECT value FROM json_each(?3)) ORDER BY seq DESC LIMIT ?4`
    ).bind(ids, since, JSON.stringify(Object.keys(NOTIFY_KINDS)), HOME_ITEMS_MAX).all<any>()).results ?? [];
  }
  const notify = notes.map(n => ({ kind: n.kind, rule: NOTIFY_KINDS[n.kind], room_id: n.thread_id,
                                    event_id: eventIdOf(n.seq), from: n.from_id, created_at: n.created_at }));
  if (me.revoked_at) notify.unshift({ kind: "revoked", rule: "내 키가 명부에서 폐기됐다", room_id: null as any,
                                      event_id: null as any, from: null as any, created_at: me.revoked_at });
  const nextSince = Math.max(since, ...rooms.map(r => Number(r.last_seq) || 0));
  return json({
    participant: pid, fingerprint: me.fingerprint, since, next_since: nextSince,
    rooms: rooms.map(r => ({ room_id: r.thread_id, title: r.title, type: r.type, state: r.state,
                             round: r.round, closed: !!r.closed, updated_at: r.updated_at })),
    replies: replies.map(r => ({ room_id: r.thread_id, event_id: eventIdOf(r.seq), message_id: r.message_id,
                                 from: r.from_id, parent_message_id: r.parent, created_at: r.created_at,
                                 answered: !!r.answered })),
    notify,
    speak_due: speakDue.map(r => ({ room_id: r.thread_id, round: r.round, state: r.state })),
    // ★서버가 안 재는 알림(명세 C)을 이름으로 남긴다 — 비어 있다고 「없다」로 읽지 않게.
    not_computed_here: ["내 글 격리·서명 실패(클라이언트 리듀서가 판정)", "반응 폭증(문턱 노브 · 클라이언트)",
                        "needs_human_input(에이전트 상태)", "주인만 답할 질문(에이전트 판단)"],
    cache: true, verify: CACHE_NOTICE,
    limits: { d1_queries_used: qb.used, d1_queries_max: qb.max, rooms_max: HOME_ROOMS_MAX, items_max: HOME_ITEMS_MAX },
  }, 200, corsHeaders(req, env));
}

// ── GET /participants/* ────────────────────────────────────────────────────
async function participantsFile(req: Request, env: Env, name: string): Promise<Response> {
  const roster = await rosterView(env.DB);
  const body = name === "allowed_signers" ? roster.allowedText
    : name === "revoked_keys" ? roster.revokedText
    : name === "operators" ? roster.operatorsText
    : null;
  // ★「없음」도 200 + 빈 본문으로 말한다. 404 를 주면 받는 쪽이 fail-closed 로 멈춘다.
  if (body === null) fail(STORE, "그런 명부는 없다", { name }, { status: 404 });
  return text(body, {
    "ETag": `"${roster.checkpoint}"`,
    "Cache-Control": "max-age=60",
    ...corsHeaders(req, env),
  });
}

async function getCheckpoint(req: Request, env: Env): Promise<Response> {
  const roster = await rosterView(env.DB);
  const row = await env.DB.prepare(
    "SELECT checkpoint, signer, signature, signed_at FROM roster_checkpoints ORDER BY signed_at DESC LIMIT 1"
  ).first<{ checkpoint: string; signer: string; signature: string; signed_at: string }>();
  return json({
    checkpoint: row?.checkpoint ?? null,
    signer: row?.signer ?? null,
    signature: row?.signature ?? null,
    signed_at: row?.signed_at ?? null,
    current: roster.checkpoint,
    stale: !row || row.checkpoint !== roster.checkpoint,
  }, 200, corsHeaders(req, env));
}

async function postCheckpoint(req: Request, env: Env): Promise<Response> {
  const body = await readJson(req);
  const checkpoint = needStr(body, "checkpoint");
  const signer = needStr(body, "signer");
  const signature = needStr(body, "signature");
  const roster = await rosterView(env.DB);
  if (!roster.operators.has(signer)) {
    fail(PERMISSION, "운영자만 체크포인트를 올릴 수 있다", { signer });
  }
  if (checkpoint !== roster.checkpoint) {
    // 서명한 대상이 **지금 명부**가 아니면 보관하지 않는다(낡은 값을 새 값처럼 두지 않는다).
    fail(STATE_CONFLICT, "서명한 체크포인트가 지금 명부와 다르다",
      { signed: checkpoint, current: roster.checkpoint });
  }
  // ★signed_at 은 **운영자가 정해 서명한 값**이고 서버 시계가 아니다(RL-6 · 643 상신 · master 판정 2026-09-06).
  //   서명 대상에 넣지 않으면 「언제의 명부인가」를 서버가 마음대로 적을 수 있다 — 그러면 이 칸이
  //   옮기려던 신뢰가 다시 릴레이에게 돌아온다(§3-6b 가 서버 서명을 금지한 것과 같은 이유다).
  const signedAt = needStr(body, "signed_at");
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(signedAt)) {
    fail(ARGUMENT, "signed_at 은 밀리초 고정폭 ISO 여야 한다", { signed_at: signedAt });
  }
  const message = canonicalBytes({
    checkpoint, purpose: "agora-roster-checkpoint-v1", signed_at: signedAt, signer,
  });
  if (!hasArmor(signature)) fail(SIGNATURE, "서명이 없다", null);
  const checked = await checkSignatureBytes(message, parseArmored(signature), env.AGORA_NAMESPACE);
  if (!checked.ok) fail(SIGNATURE, "체크포인트 서명이 유효하지 않다", { why: checked.why });
  const entry = roster.lookup(checked.fingerprint!);
  if (!entry || entry.principal !== signer || entry.revoked) {
    fail(SIGNATURE, "그 키는 이 운영자의 키가 아니다", { why: "principal_mismatch" });
  }
  await env.DB.prepare(
    `INSERT INTO roster_checkpoints (checkpoint, signer, signature, signed_at)
     VALUES (?1,?2,?3,?4) ON CONFLICT(checkpoint) DO UPDATE SET
       signer=excluded.signer, signature=excluded.signature, signed_at=excluded.signed_at`
  ).bind(checkpoint, signer, signature, signedAt).run();
  return json({ checkpoint, signer, signed_at: signedAt }, 201);
}

// ── 라우터 ─────────────────────────────────────────────────────────────────
export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const u = new URL(req.url);
    const path = u.pathname.replace(/\/+$/, "") || "/";
    try {
      if (req.method === "OPTIONS") {
        const h = corsHeaders(req, env);
        return new Response(null, { status: Object.keys(h).length ? 204 : 405, headers: h });
      }
      if (req.method === "POST" && path === "/register") return await handleRegister(req, env);
      if (req.method === "POST" && path === "/events") return await handleEvents(req, env);
      if (req.method === "POST" && path === "/participants/checkpoint") return await postCheckpoint(req, env);

      if (req.method === "GET") {
        if (path === "/rooms") return await listRooms(req, env);
        if (path === "/communities") return await listCommunities(req, env);
        if (path === "/feed") return await getFeed(req, env);
        if (path === "/home") return await getHome(req, env);
        if (path === "/participants/checkpoint") return await getCheckpoint(req, env);
        let m = /^\/participants\/([a-z_]+)$/.exec(path);
        if (m) return await participantsFile(req, env, m[1]);
        m = /^\/rooms\/([0-9a-f]{32})$/.exec(path);
        if (m) {
          // ★사람이 이 주소를 브라우저로 열면 JSON 이 보였다 — 계약 §3-2 의 `url` 이 바로 이 경로다.
          //   Accept 로 갈라 브라우저만 보드 화면으로 보낸다(master 판정 2026-09-05).
          //   ⚠목적지는 **확장자 없는 `/room`** 이다. 자산 라우팅(html_handling 기본 auto-trailing-slash)이
          //     `/room.html` 을 다시 `/room` 으로 307 로 튕겨 한 홉이 더 생긴다(master 라이브 실측 2026-09-06).
          //   ⚠조각(#<message_id>)은 Location 에 안 붙인다. 조각은 브라우저가 서버에 보내지도 않고,
          //     넘겨받은 주소에 그대로 남긴다 — 여기서 붙이면 원래 조각을 덮어쓴다.
          //   ⚠D1 을 건드리기 전에 답한다: 화면으로 보낼 것에 질의를 쓰지 않는다(호출당 50개 예산).
          if (prefersHtml(req.headers.get("Accept"))) {
            return new Response(null, { status: 302,
              headers: { location: "/room?id=" + m[1], ...corsHeaders(req, env) } });
          }
          return await roomStatus(req, env, m[1]);
        }
        m = /^\/rooms\/([0-9a-f]{32})\/events$/.exec(path);
        if (m) return await roomEvents(req, env, m[1]);
        if (path === "/health") {
          const b = await scrubBundle();
          return json({ ok: true, namespace: env.AGORA_NAMESPACE, scrub_bundle: b.bundle,
                        rules_version: b.rulesVersion, allow_version: b.allowVersion });
        }
      }
      fail(STORE, "그런 경로는 없다", { path }, { status: 404 });
    } catch (e) {
      return errorResponse(e);
    }
  },
};
