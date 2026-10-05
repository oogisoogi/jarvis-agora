/**
 * 에이전트 우편(1:1) — 순수 모듈. 계약 = docs/RELAY.md §14 · 명세 = docs/SPEC-mail-1to1-2026-10-05.md §1-1·§2·§3.
 *
 * ★우편은 방이 아니다. 광장 `KINDS` 9종·리듀서·상태기계에 들어가지 않는다(PROTOCOL 무변경).
 *   그래서 스키마도 schema.ts 의 `validate` 가 아니라 여기의 **닫힌 정의**를 쓴다 — 우편 문서를
 *   `POST /events` 에 내면 그쪽 스키마가 거부하고(kind·칸이 다르다), 방 글을 `POST /mail` 에 내면 이쪽이 거부한다.
 * ★이 파일에는 D1·fetch 가 없다. 시험이 직접 부르는 함수만 둔다(검증·쪽 짜기·인증 문서 모양·보존 기한).
 */
import { ARGUMENT, GATE_REJECT, SIGNATURE, fail } from "./errors.ts";
import { canonicalBytes, isId, sha256Hex } from "./canonical.ts";
import { closed, need } from "./schema.ts";
import { b64decode } from "./sshsig.ts";

type Obj = Record<string, unknown>;

export const MAIL_KIND = "mail";
export const MAIL_INTENTS = ["notice", "request", "report"] as const;
export const SIGNAL_INTENT = "signal";
export const SIGNAL_SOURCES = ["master", "worker", "cso", "pack", "update"] as const;
export const DAILY_INTENT = "daily";              // 일일 보고(명세 §1-2 · 증보 8) — 신호와 다른 통
export const DAILY_MAX_BYTES = 32 * 1024;        // 일일 보고 canonical 상한(일반 우편 64KB 보다 작다 · 넘으면 413/3)
export const DAILY_NOTE_MAX_CHARS = 200;         // owner_note = 유일한 자유문 · 코드포인트

export const MAX_SUBJECT_CHARS = 200;          // 코드포인트 수(UTF-16 길이 아님)
export const MAX_BODY_BYTES = 16 * 1024;       // UTF-8
export const MAX_REFS = 5;
export const SIGNAL_ITEMS_MAX = 100;
export const SIGNAL_COUNT_MAX = 100_000;
export const SIGNAL_PAST_MS = 7 * 86_400_000;   // first_seen·last_seen = 지난 7일 안
export const FUTURE_SKEW_MS = 5 * 60_000;       // 서버 시계보다 5분 앞까지는 받는다(시계 어긋남)
export const MAIL_TS_PAST_MS = 86_400_000;      // 우편 ts = 서버 시각 −24시간 ~ +5분
export const AUTH_SKEW_MS = 300_000;            // 수신함·읽음 인증 ts = 서버 시각 ±5분

export const INBOX_PURPOSE = "agora-mail-inbox-v1";
// ★v2(적대 2R R2-1·R2-2): 읽음 대상 = 릴레이가 매긴 `mail_id`(전역 유일 · message_id 는 발신자별로만 유일) ·
//   대화 단위 읽음 = 서명된 `upto`(mail_id) 이하만 — 시각(ts·created_at)을 경계로 쓰지 않는다.
export const ACK_PURPOSE = "agora-mail-ack-v2";
export const INBOX_PAGE_MAX = 50;
export const INBOX_SCAN_MAX = 500;
export const RECEIPTS_MAX = 100;
export const ACK_IDS_MAX = 50;
export const ACK_THREADS_MAX = 20;
export const KEEP_DAYS = 30;
export const KEEP_REPLY_DAYS = 90;

const DOC_REQUIRED = ["v", "kind", "message_id", "thread_id", "from", "to", "prev", "roster",
  "scrub", "ts", "payload"];
const DOC_OPTIONAL = ["reply_to"];
const SIGNAL_ITEM_KEYS = ["signature", "count", "source", "op", "version", "os", "error_code",
  "first_seen", "last_seen"];

const ISO_MS = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
const SIG_KEY = /^[0-9a-f]{32}$/;
const PREV_HASH = /^[0-9a-f]{64}$/;
const SCRUB_KEYS = ["rules", "blocked", "redacted"];   // 클라이언트 core.declare_scrub 이 만드는 모양 그대로
const OP_RE = /^[a-z0-9_.-]{1,32}$/;
const VERSION_RE = /^[0-9A-Za-z.+-]{1,32}$/;
const OS_RE = /^(macos|windows|linux)(-[0-9.]{1,16})?$/;
const ERROR_CODE_RE = /^[a-z0-9._-]{1,48}$/;
const MAIL_ID_RE = /^ml_(\d{16})$/;
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;
const ROLE_RE = /^[a-z][a-z0-9-]{0,31}$/;
const CHECK_ID_RE = /^[a-z0-9-]{1,40}$/;
const DAILY_KEYS = ["day", "version", "os", "seats", "doctor", "errors", "updates", "depts", "uptime", "owner_note"];

const enc = new TextEncoder();
const dec = new TextDecoder();

/**
 * UTC 밀리초 고정폭 ISO 인가. ★형식만이 아니라 **되돌려 같은 문자열이 나오는가**까지 본다 —
 * `2026-02-30T…` 처럼 형식은 맞는데 없는 날짜가 조용히 다음 달로 굴러가지 않게.
 */
export function isIsoMs(v: unknown): v is string {
  if (typeof v !== "string" || !ISO_MS.test(v)) return false;
  const t = Date.parse(v);
  return Number.isFinite(t) && new Date(t).toISOString() === v;
}

/** `ml_` + 16자리 고정폭 — 문자열 정렬 = 적재 순서(event_id 와 같은 이유 · D-R5). */
export function mailIdOf(seq: number): string {
  return "ml_" + String(seq).padStart(16, "0");
}

/** `ml_…` → seq. 형식이 아니면 null. */
export function parseMailId(s: string): number | null {
  const m = MAIL_ID_RE.exec(s);
  return m ? parseInt(m[1], 10) : null;
}

/** 적재 시각 → 보존 기한. 답장 = +90일 · 그 밖 = +30일(명세 §3-4 · 판단 ⑥). */
export function keepUntil(createdMs: number, isReply: boolean): string {
  return new Date(createdMs + (isReply ? KEEP_REPLY_DAYS : KEEP_DAYS) * 86_400_000).toISOString();
}

/**
 * 신호 묶기 키 = sha256(canonical({"error_code","op","source","version"(소문자)})) 의 앞 32 hex(명세 §1-1 (2)).
 * ★릴레이가 **다시 계산해 대조**한다 — 해시라서 이 칸으로 문장을 실어 보낼 수 없다는 주장이 여기서 선다.
 */
export async function signalSignature(item: { error_code: string; op: string; source: string;
                                              version: string }): Promise<string> {
  const raw = canonicalBytes({ error_code: item.error_code, op: item.op, source: item.source,
                               version: item.version.toLowerCase() });
  return (await sha256Hex(raw)).slice(0, 32);
}

function findNull(node: unknown, path: string): string | null {
  if (node === null) return path;
  if (Array.isArray(node)) {
    for (let i = 0; i < node.length; i++) { const r = findNull(node[i], `${path}[${i}]`); if (r) return r; }
  } else if (typeof node === "object") {
    for (const [k, v] of Object.entries(node as Obj)) { const r = findNull(v, `${path}.${k}`); if (r) return r; }
  }
  return null;
}

function bad(message: string, detail: Obj): never {
  return fail(ARGUMENT, message, detail);
}

function checkTimeWindow(v: string, where: string, nowMs: number): number {
  const t = Date.parse(v);
  if (t < nowMs - SIGNAL_PAST_MS || t > nowMs + FUTURE_SKEW_MS) {
    bad("신호 시각이 받는 창 밖이다(지난 7일 ~ +5분)", { where, why: "signal_time_window" });
  }
  return t;
}

async function checkSignal(p: Obj, nowMs: number): Promise<void> {
  // ★자유문 0 — 제목·본문 칸이 아예 없다(명세 §1-1). 모르는 칸 = 10.
  closed(p, ["intent", "items"], "payload");
  const items = need<unknown[]>(p, "items", "list", "payload");
  if (items.length < 1 || items.length > SIGNAL_ITEMS_MAX) {
    bad("신호 항목 수가 범위 밖", { where: "payload.items", count: items.length, min: 1, max: SIGNAL_ITEMS_MAX });
  }
  const seen = new Set<string>();
  for (let i = 0; i < items.length; i++) {
    const where = `payload.items[${i}]`;
    const it = items[i];
    if (typeof it !== "object" || it === null || Array.isArray(it)) bad("신호 항목은 객체여야 한다", { where });
    const o = it as Obj;
    closed(o, SIGNAL_ITEM_KEYS, where);
    const sig = need<string>(o, "signature", "string", where);
    const count = need<number>(o, "count", "int", where);
    const source = need<string>(o, "source", "string", where);
    const op = need<string>(o, "op", "string", where);
    const version = need<string>(o, "version", "string", where);
    const os = need<string>(o, "os", "string", where);
    const errorCode = need<string>(o, "error_code", "string", where);
    const first = need<string>(o, "first_seen", "string", where);
    const last = need<string>(o, "last_seen", "string", where);
    if (!SIG_KEY.test(sig)) bad("signature 는 소문자 hex 32자", { where: `${where}.signature` });
    if (seen.has(sig)) bad("같은 signature 가 두 번 나왔다", { where: `${where}.signature`, why: "duplicate_signature" });
    seen.add(sig);
    if (count < 1 || count > SIGNAL_COUNT_MAX) bad("count 가 범위 밖", { where: `${where}.count`, min: 1, max: SIGNAL_COUNT_MAX });
    if (!(SIGNAL_SOURCES as readonly string[]).includes(source)) {
      bad("source 가 계약 밖", { where: `${where}.source`, allowed: SIGNAL_SOURCES });
    }
    if (!OP_RE.test(op)) bad("op 형식이 아니다", { where: `${where}.op` });
    if (!VERSION_RE.test(version)) bad("version 형식이 아니다", { where: `${where}.version` });
    if (!OS_RE.test(os)) bad("os 형식이 아니다", { where: `${where}.os` });
    if (!ERROR_CODE_RE.test(errorCode)) bad("error_code 형식이 아니다", { where: `${where}.error_code` });
    if (!isIsoMs(first)) bad("first_seen 은 밀리초 고정폭 ISO", { where: `${where}.first_seen` });
    if (!isIsoMs(last)) bad("last_seen 은 밀리초 고정폭 ISO", { where: `${where}.last_seen` });
    const tf = checkTimeWindow(first, `${where}.first_seen`, nowMs);
    const tl = checkTimeWindow(last, `${where}.last_seen`, nowMs);
    if (tf > tl) bad("first_seen 이 last_seen 보다 늦다", { where });
    const want = await signalSignature({ error_code: errorCode, op, source, version });
    if (want !== sig) {
      // ★값 자체(want)는 돌려준다 — 공개 규칙으로 누구나 계산할 수 있는 값이라 유출이 아니고,
      //   발신 PC 의 정규화가 어디서 갈렸는지 찾는 데 쓴다.
      bad("signature 가 칸 넷의 해시와 다르다", { where: `${where}.signature`, why: "signature_mismatch", want });
    }
  }
}

function intIn(o: Obj, key: string, where: string, min: number, max: number): number {
  const v = need<number>(o, key, "int", where);
  if (v < min || v > max) bad("정수 범위 밖", { where: `${where}.${key}`, min, max });
  return v;
}

function strList(o: Obj, key: string, where: string, max: number, re: RegExp): string[] {
  const v = need<unknown[]>(o, key, "list", where);
  if (v.length > max) bad("목록이 너무 길다", { where: `${where}.${key}`, count: v.length, max });
  v.forEach((x, i) => { if (typeof x !== "string" || !re.test(x)) bad("목록 항목 형식이 아니다", { where: `${where}.${key}[${i}]` }); });
  return v as string[];
}

/**
 * 일일 보고(명세 §1-2) — 닫힌 모양 · `day` 만 필수 · 나머지 칸은 선택(모르면 뺀다) · 칸 안의 하위 칸은 전부 필수
 * (단 `version` 은 host·pack 중 하나 이상). ★자유문은 `owner_note` 1칸(≤200 코드포인트)뿐 — 나머지는 계수·판본·기계 id.
 * 크기 상한 32KB 는 validateMail 이 canonical 전체로 잰다(413/3).
 */
function checkDaily(p: Obj, nowMs: number): void {
  closed(p, ["intent", "daily"], "payload");
  const w = "payload.daily";
  const d = need<Obj>(p, "daily", "dict", "payload");
  closed(d, DAILY_KEYS, w);
  const day = need<string>(d, "day", "string", w);
  // ★Date.parse 는 2026-02-30 을 3월 2일로 고쳐 읽는다 — 되돌려 같은 글자인지 본다(적대 2R R2-4 · 파이썬 date.fromisoformat 과 같은 경계).
  const dayMs = DAY_RE.test(day) ? Date.parse(day + "T00:00:00.000Z") : NaN;
  if (Number.isNaN(dayMs) || new Date(dayMs).toISOString().slice(0, 10) !== day) bad("day 는 실제 날짜 YYYY-MM-DD", { where: `${w}.day` });
  if ("version" in d) {
    const v = need<Obj>(d, "version", "dict", w);
    closed(v, ["host", "pack"], `${w}.version`);
    const keys = Object.keys(v);
    if (!keys.length) bad("version 은 host·pack 중 하나 이상", { where: `${w}.version` });
    for (const k of keys) if (!VERSION_RE.test(need<string>(v, k, "string", `${w}.version`))) bad("version 형식이 아니다", { where: `${w}.version.${k}` });
  }
  if ("os" in d && !OS_RE.test(need<string>(d, "os", "string", w))) bad("os 형식이 아니다", { where: `${w}.os` });
  if ("seats" in d) {
    const o = need<Obj>(d, "seats", "dict", w); const ww = `${w}.seats`;
    closed(o, ["count", "roles"], ww);
    intIn(o, "count", ww, 0, 64);
    const roles = strList(o, "roles", ww, 64, ROLE_RE);
    if (roles.some((r, i) => i > 0 && roles[i - 1] > r)) bad("roles 는 정렬된 목록", { where: `${ww}.roles` });
  }
  if ("doctor" in d) {
    const o = need<Obj>(d, "doctor", "dict", w); const ww = `${w}.doctor`;
    closed(o, ["ok", "warn", "fail", "skip", "warn_ids", "fail_ids"], ww);
    for (const k of ["ok", "warn", "fail", "skip"]) intIn(o, k, ww, 0, 999);
    for (const k of ["warn_ids", "fail_ids"]) strList(o, k, ww, 64, CHECK_ID_RE);
  }
  if ("errors" in d) {
    const o = need<Obj>(d, "errors", "dict", w); const ww = `${w}.errors`;
    closed(o, ["tick_errors", "hook_rc_nonzero", "signatures"], ww);
    for (const k of ["tick_errors", "hook_rc_nonzero"]) intIn(o, k, ww, 0, SIGNAL_COUNT_MAX);
    strList(o, "signatures", ww, SIGNAL_ITEMS_MAX, SIG_KEY);
  }
  if ("updates" in d) {
    const ups = need<unknown[]>(d, "updates", "list", w);
    if (ups.length > 10) bad("updates 는 최대 10개", { where: `${w}.updates`, count: ups.length, max: 10 });
    ups.forEach((u, i) => {
      const ww = `${w}.updates[${i}]`;
      if (typeof u !== "object" || u === null || Array.isArray(u)) bad("updates 항목은 객체여야 한다", { where: ww });
      const o = u as Obj;
      closed(o, ["from", "to", "result", "at"], ww);
      for (const k of ["from", "to"]) if (!VERSION_RE.test(need<string>(o, k, "string", ww))) bad("version 형식이 아니다", { where: `${ww}.${k}` });
      if (!ERROR_CODE_RE.test(need<string>(o, "result", "string", ww))) bad("result 형식이 아니다", { where: `${ww}.result` });
      const at = need<string>(o, "at", "string", ww);
      if (!isIsoMs(at)) bad("at 은 밀리초 고정폭 ISO", { where: `${ww}.at` });
      checkTimeWindow(at, `${ww}.at`, nowMs);
    });
  }
  if ("depts" in d) {
    const o = need<Obj>(d, "depts", "dict", w); const ww = `${w}.depts`;
    closed(o, ["active", "tombstones"], ww);
    for (const k of ["active", "tombstones"]) intIn(o, k, ww, 0, 999);
  }
  if ("uptime" in d) {
    const o = need<Obj>(d, "uptime", "dict", w); const ww = `${w}.uptime`;
    closed(o, ["last_boot", "uptime_s"], ww);
    const lb = need<string>(o, "last_boot", "string", ww);
    if (!isIsoMs(lb) || Date.parse(lb) > nowMs + FUTURE_SKEW_MS) bad("last_boot 은 지나간 밀리초 ISO", { where: `${ww}.last_boot` });
    intIn(o, "uptime_s", ww, 0, 31_536_000);
  }
  if ("owner_note" in d) {
    const n = [...need<string>(d, "owner_note", "string", w)].length;
    if (n > DAILY_NOTE_MAX_CHARS) bad("owner_note 는 200자까지", { where: `${w}.owner_note`, chars: n, max: DAILY_NOTE_MAX_CHARS });
  }
}

function checkLetter(p: Obj): void {
  closed(p, ["subject", "body", "intent", "refs"], "payload");
  const intent = need<string>(p, "intent", "string", "payload");
  if (!(MAIL_INTENTS as readonly string[]).includes(intent)) {
    bad("intent 가 계약 밖", { where: "payload.intent", intent, allowed: [...MAIL_INTENTS, SIGNAL_INTENT, DAILY_INTENT] });
  }
  const subject = need<string>(p, "subject", "string", "payload");
  const n = [...subject].length;
  if (n < 1 || n > MAX_SUBJECT_CHARS) {
    bad("제목 길이가 범위 밖(코드포인트 1~200)", { where: "payload.subject", chars: n, max: MAX_SUBJECT_CHARS });
  }
  const body = need<string>(p, "body", "string", "payload");
  if (body.length === 0) bad("본문이 비었다", { where: "payload.body" });
  const bytes = enc.encode(body).length;
  if (bytes > MAX_BODY_BYTES) {
    // ★크기는 모양(10)이 아니라 **크기 거부(413/3)** 다 — 명세 §3-1 ①「크기(64KB · body 16KB) → 413/3」.
    fail(GATE_REJECT, "본문 크기 상한 초과", { where: "payload.body", bytes, limit: MAX_BODY_BYTES }, { status: 413 });
  }
  if ("refs" in p) {
    const refs = need<unknown[]>(p, "refs", "list", "payload");
    if (refs.length > MAX_REFS) bad("refs 는 최대 5개", { where: "payload.refs", count: refs.length, max: MAX_REFS });
    refs.forEach((r, i) => {
      if (typeof r !== "string" || r.length === 0) bad("refs 항목은 빈칸이 아닌 문자열", { where: `payload.refs[${i}]` });
    });
    // 링크 허용 규칙(config/allow-domains.txt)은 스크럽 백스톱이 문자열 전체를 훑으며 본다(422/3).
  }
}

/**
 * 우편 문서 닫힌 검증(명세 §2 · §1-1). 통과하면 같은 객체를 돌려준다.
 * ★신호·일일 보고의 시각 창(지난 7일 ~ +5분)은 **봉투 ts 기준**이다(적대 2R R2-3 · 받는 쪽과 같은 기준).
 *   `_nowMs` 는 부르는 쪽 계약을 그대로 두려고 남긴다(쓰지 않는다). 우편 자체의 `ts` 창(서버 −24시간 ~ +5분)은
 *   여기서 보지 않는다 — 그것은 모양이 아니라 정책(422/3)이고, 명세의 검사 순서상 대화 결박 **뒤**다.
 */
export async function validateMail(doc: unknown, _nowMs: number): Promise<Obj> {
  if (typeof doc !== "object" || doc === null || Array.isArray(doc)) {
    bad("우편 문서는 객체여야 한다", { got: Array.isArray(doc) ? "list" : doc === null ? "null" : typeof doc });
  }
  const d = doc as Obj;
  closed(d, [...DOC_REQUIRED, ...DOC_OPTIONAL], "mail");
  // ★null 은 어디에도 없다(선택 칸은 「빠짐」으로만 말한다) — scrub 처럼 안을 따로 보지 않는 칸까지 훑는다.
  const nullAt = findNull(d, "mail");
  if (nullAt) bad("null 은 받지 않는다(선택 칸은 빼서 보낸다)", { where: nullAt });
  if (need<number>(d, "v", "int", "mail") !== 1) bad("판본이 다르다", { v: d["v"] });
  if (need<string>(d, "kind", "string", "mail") !== MAIL_KIND) bad("kind 는 mail 이어야 한다", { kind: d["kind"] });
  for (const key of ["message_id", "thread_id"]) {
    if (!isId(need<string>(d, key, "string", "mail"))) bad("id 형식이 아니다", { key, want_hex_len: 32 });
  }
  if ("reply_to" in d && !isId(need<string>(d, "reply_to", "string", "mail"))) {
    bad("id 형식이 아니다", { key: "reply_to", want_hex_len: 32 });
  }
  const from = need<string>(d, "from", "string", "mail");
  const to = need<string>(d, "to", "string", "mail");
  if (!from || !to) bad("from·to 가 비었다", { from, to });
  if (from === to) bad("자기 자신에게는 보낼 수 없다", { from, to });
  const prev = need<string>(d, "prev", "string", "mail");
  if (prev !== "genesis" && !PREV_HASH.test(prev)) {
    bad("prev 는 genesis 또는 소문자 hex 64자", { len: prev.length });
  }
  // ★봉투도 닫는다(적대 1R R1-2) — payload 만 닫으면 `scrub`·`roster` 에 자유문을 실어 신호의 승인 겹 예외
  //   (「자유문 칸이 없는 닫힌 모양」이 예외의 전제)를 그대로 지나간다. 클라이언트 `declare_scrub` 이 만드는 모양만 받는다.
  if (!PREV_HASH.test(need<string>(d, "roster", "string", "mail"))) bad("roster 는 소문자 hex 64자", { where: "mail.roster" });
  const sc = need<Obj>(d, "scrub", "dict", "mail");
  closed(sc, SCRUB_KEYS, "scrub");
  if (!PREV_HASH.test(need<string>(sc, "rules", "string", "scrub"))) bad("scrub.rules 는 소문자 hex 64자", { where: "scrub.rules" });
  for (const key of ["blocked", "redacted"]) {
    if (need<number>(sc, key, "int", "scrub") < 0) bad("scrub 계수는 0 이상", { where: `scrub.${key}` });
  }
  if (!isIsoMs(need<string>(d, "ts", "string", "mail"))) bad("ts 는 밀리초 고정폭 ISO", { ts: d["ts"] });
  const p = need<Obj>(d, "payload", "dict", "mail");
  const intent = need<string>(p, "intent", "string", "payload");
  // ★신호·일일 보고의 시각 창 기준 = **우편 봉투 ts**(적대 2R R2-3) — 받는 쪽 클라이언트도 같은 기준으로 다시 잰다.
  //   서버 시각을 기준으로 두면 릴레이가 받은 문서를 받는 쪽이 계약 위반으로 격리한다. 봉투 ts 자체의 서버 창
  //   (−24시간 ~ +5분)은 handleMailPost (6) 이 따로 본다.
  const basisMs = Date.parse(d["ts"] as string);
  if (intent === SIGNAL_INTENT) await checkSignal(p, basisMs);
  else if (intent === DAILY_INTENT) {
    checkDaily(p, basisMs);
    const bytes = canonicalBytes(d).length;
    if (bytes > DAILY_MAX_BYTES) {
      fail(GATE_REJECT, "일일 보고 크기 상한 초과", { where: "mail", bytes, limit: DAILY_MAX_BYTES }, { status: 413 });
    }
  } else checkLetter(p);
  return d;
}

// ── 수신함·읽음 인증 ─────────────────────────────────────────────────────────
// ★「수신자가 아닌 자는 inbox 를 못 본다」의 유일한 문이 이 서명이다(명세 §3-2).
// ★서명 대상에 **요청 인자(since·receipts_since·acked…)** 를 다 넣는다 — 빼면 남이 가로챈 헤더로
//   다른 쪽수를 읽거나(재사용) 다른 우편에 읽음을 붙일 수 있다. `purpose` 가 등록·체크포인트·이벤트 서명과
//   같은 namespace 안에서 용도를 가른다(교차 재사용 차단).

export function inboxAuthDoc(forId: string, since: string, receiptsSince: string, ts: string): Obj {
  return { for: forId, purpose: INBOX_PURPOSE, receipts_since: receiptsSince, since, ts };
}

export function ackAuthDoc(forId: string, acked: string[], ackedThreads: string[], upto: string, ts: string): Obj {
  return { acked, acked_threads: ackedThreads, for: forId, purpose: ACK_PURPOSE, ts, upto };
}

/** `X-Agora-Mail-Auth: base64(JSON {"ts","signature"})` → 두 칸. 없거나 못 읽으면 401/4. */
export function parseAuthHeader(h: string | null): { ts: string; signature: string } {
  if (!h) fail(SIGNATURE, "우편 인증 헤더가 없다", { verdict: "unsigned", why: "auth_missing" });
  let o: unknown;
  try { o = JSON.parse(dec.decode(b64decode(h.trim()))); }
  catch { return fail(SIGNATURE, "우편 인증 헤더를 읽지 못했다", { verdict: "unsigned", why: "auth_malformed" }); }
  if (typeof o !== "object" || o === null || Array.isArray(o)) {
    fail(SIGNATURE, "우편 인증 헤더 모양이 아니다", { verdict: "unsigned", why: "auth_malformed" });
  }
  const r = o as Obj;
  const extra = Object.keys(r).filter(k => k !== "ts" && k !== "signature");
  if (typeof r["ts"] !== "string" || typeof r["signature"] !== "string" || extra.length) {
    fail(SIGNATURE, "우편 인증 헤더 모양이 아니다", { verdict: "unsigned", why: "auth_malformed" });
  }
  return { ts: r["ts"] as string, signature: r["signature"] as string };
}

/** 인증 ts 가 서버 시각 ±5분 안인가. 못 읽는 값도 창 밖으로 본다. */
export function authTsOk(ts: string, nowMs: number): boolean {
  if (!isIsoMs(ts)) return false;
  return Math.abs(Date.parse(ts) - nowMs) <= AUTH_SKEW_MS;
}

// ── 수신함 쪽 짜기(순수) ─────────────────────────────────────────────────────

export interface InboxHead {
  seq: number;
  thread_id: string;
  created_at: string;
  acked_at: string | null;
}

export interface InboxPage<T extends InboxHead> {
  threads: Array<{ thread_id: string; items: T[] }>;
  next: string | null;
}

/**
 * 후보(나에게 온 우편 · seq 오름차순 · 최대 500) → 한 쪽(최대 50통).
 *   · 대화 안 = seq 오름차순(FIFO).
 *   · 대화 순서 = 가장 오래 기다린 미읽음(acked_at 없음)이 먼저 · 미읽음이 없는 대화는 뒤(가장 오래된 순).
 *   · 쪽은 대화마다 **돌아가며** 채운다(라운드로빈) — 한 상대가 60통 보내도 다른 대화가 첫 쪽에 보인다.
 *   · `next` = 모든 후보를 돌려줬고 후보가 상한보다 적으면 null, 아니면 「안 돌려준 것 중 가장 작은 seq − 1」
 *     (at-least-once — 이미 돌려준 것이 다시 올 수 있고 받는 쪽이 `(from,message_id)` 로 거른다).
 * ★진행 보장: 대화가 쪽 크기(50)보다 많으면 seq 가 가장 작은 후보의 대화가 첫 바퀴에서 잘릴 수 있고,
 *   그러면 `next` 가 `since` 와 같아져 **같은 쪽이 영원히 반복**된다. 그래서 그 대화를 첫 바퀴의
 *   마지막 자리(49번)까지 당겨 넣는다 — 그 대화의 첫 항목이 곧 가장 작은 seq(FIFO)이므로 `next` 가 반드시 전진한다.
 */
export function buildInboxPage<T extends InboxHead>(rows: T[], pageMax = INBOX_PAGE_MAX,
                                                     scanMax = INBOX_SCAN_MAX): InboxPage<T> {
  if (!rows.length) return { threads: [], next: null };
  const sorted = [...rows].sort((a, b) => a.seq - b.seq);
  const groups = new Map<string, T[]>();
  for (const r of sorted) {
    const g = groups.get(r.thread_id);
    if (g) g.push(r); else groups.set(r.thread_id, [r]);
  }
  const order = [...groups.entries()].map(([thread_id, items]) => {
    const firstUnread = items.find(x => !x.acked_at);
    return { thread_id, items, unreadAt: firstUnread ? firstUnread.created_at : null,
             firstAt: items[0].created_at, firstSeq: items[0].seq };
  });
  order.sort((a, b) => {
    if (a.unreadAt && b.unreadAt) {
      return a.unreadAt < b.unreadAt ? -1 : a.unreadAt > b.unreadAt ? 1 : a.firstSeq - b.firstSeq;
    }
    if (a.unreadAt) return -1;
    if (b.unreadAt) return 1;
    return a.firstAt < b.firstAt ? -1 : a.firstAt > b.firstAt ? 1 : a.firstSeq - b.firstSeq;
  });
  const minSeq = sorted[0].seq;
  const at = order.findIndex(t => t.firstSeq === minSeq);
  if (at >= pageMax) {
    const [t] = order.splice(at, 1);
    order.splice(pageMax - 1, 0, t);
  }

  const taken = order.map(() => 0);
  let count = 0;
  let moved = true;
  while (count < pageMax && moved) {
    moved = false;
    for (let i = 0; i < order.length && count < pageMax; i++) {
      if (taken[i] < order[i].items.length) { taken[i] += 1; count += 1; moved = true; }
    }
  }
  const threads = order
    .map((t, i) => ({ thread_id: t.thread_id, items: t.items.slice(0, taken[i]) }))
    .filter(t => t.items.length > 0);
  const returned = new Set<number>();
  for (const t of threads) for (const it of t.items) returned.add(it.seq);
  const unreturned = sorted.filter(r => !returned.has(r.seq));
  let next: string | null;
  if (unreturned.length) next = mailIdOf(unreturned[0].seq - 1);
  else next = sorted.length < scanMax ? null : mailIdOf(sorted[sorted.length - 1].seq);
  return { threads, next };
}
