/**
 * 이벤트 스키마 — kind 9종의 **닫힌** 정의. 파이썬 `agora/schema.py` 를 바꾸지 않고 옮긴 것.
 *
 * ★닫힌 스키마인 이유: 「모르는 칸은 무시」로 두면 언젠가 누가 그 칸에 무엇을 넣고,
 *   서명 대상과 해석 대상이 갈라진다. 그래서 **모르는 칸은 거부**한다.
 *
 * 코드 구분:
 *   · 10(인자 오류) — 모양이 틀렸다(칸 없음·모르는 칸·타입 틀림·값 범위 밖).
 *   · 3(게이트 거부) — 모양은 맞는데 **정책**이 막는다(봉투 결손·집행 금지 표식 부재).
 */
import { ARGUMENT, GATE_REJECT, fail } from "./errors.ts";
import { ID_HEX_LEN, isId } from "./canonical.ts";

export const KINDS = ["genesis", "post", "advance", "resolution", "answer_selected",
  "close", "delegate_chair", "abort", "vote"] as const;
export type Kind = typeof KINDS[number];

export const THREAD_TYPES = ["problem", "knowhow", "debate"] as const;
export const CLOSE_REASONS = ["solved", "unresolved", "superseded", "archived", "aborted", "expired"] as const;
export const ROUNDS = [0, 1, 2, 3];
export const DEADLINE_ROUNDS = ["r0", "r1", "r2", "r3"] as const;
// 계약 확장 9 — 예산 칸 이름(agora/contract_open.py 의 BUDGET_FIELDS 와 같아야 한다).
export const BUDGET_FIELDS = ["posts_per_round", "max_chars_per_round"] as const;

export const GENESIS_PREV = "genesis";
export const GENESIS_EXPECTED_STATE = "";
export const MAX_LOG_EXCERPT_BYTES = 4 * 1024;

const COMMON_REQUIRED = ["v", "kind", "thread_id", "message_id", "prev", "expected_state",
  "from", "roster", "scrub", "ts", "payload"];
const COMMON_OPTIONAL = ["delegate"];

const ENVELOPE_REQUIRED = ["env", "symptom", "repro_steps"];
const ENVELOPE_OPTIONAL = ["log_excerpt", "tried", "questions"];
const ENVELOPE_ENV_REQUIRED = ["os", "app"];
const ENVELOPE_ENV_OPTIONAL = ["version"];

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj =>
  typeof v === "object" && v !== null && !Array.isArray(v);
// ★파이썬은 bool 을 int 로 세지 않는다(`type(True) is int` = False). 같은 경계를 지킨다.
const isInt = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v);

function need<T>(o: Obj, key: string, kind: "string" | "int" | "dict" | "list", where: string): T {
  if (!(key in o)) fail(ARGUMENT, "필수 칸 누락", { where, key });
  const v = o[key];
  const ok = kind === "string" ? typeof v === "string"
    : kind === "int" ? isInt(v)
    : kind === "dict" ? isObj(v)
    : Array.isArray(v);
  if (!ok) {
    fail(ARGUMENT, "칸 타입이 다르다",
      { where, key, want: kind, got: Array.isArray(v) ? "list" : v === null ? "null" : typeof v });
  }
  return v as T;
}

function closed(o: Obj, allowed: string[], where: string): void {
  const extra = Object.keys(o).filter(k => !allowed.includes(k));
  if (extra.length) fail(ARGUMENT, "계약에 없는 칸", { where, extra: extra.sort() });
}

function envelopeMissing(key: string, where: string): never {
  // 봉투 **결손**은 정책 거부(3)다 — 모양 오류(10)와 구별한다.
  return fail(GATE_REJECT, "봉투 필수 칸 누락", { where, key });
}

function checkEnvelope(env: Obj): void {
  closed(env, [...ENVELOPE_REQUIRED, ...ENVELOPE_OPTIONAL], "envelope");
  for (const key of ENVELOPE_REQUIRED) if (!(key in env)) envelopeMissing(key, "envelope");
  const e = need<Obj>(env, "env", "dict", "envelope");
  closed(e, [...ENVELOPE_ENV_REQUIRED, ...ENVELOPE_ENV_OPTIONAL], "envelope.env");
  for (const key of ENVELOPE_ENV_REQUIRED) {
    if (!(key in e)) envelopeMissing(key, "envelope.env");
    need<string>(e, key, "string", "envelope.env");
  }
  need<string>(env, "symptom", "string", "envelope");
  const steps = need<unknown[]>(env, "repro_steps", "list", "envelope");
  if (steps.length === 0) {
    fail(GATE_REJECT, "재현 단계가 비었다", { where: "envelope.repro_steps" });
  }
  steps.forEach((st, i) => {
    if (typeof st !== "string") fail(ARGUMENT, "재현 단계는 문자열이어야 한다", { where: `envelope.repro_steps[${i}]` });
  });
  if ("log_excerpt" in env) {
    const raw = new TextEncoder().encode(need<string>(env, "log_excerpt", "string", "envelope"));
    if (raw.length > MAX_LOG_EXCERPT_BYTES) {
      fail(GATE_REJECT, "로그 발췌 상한 초과",
        { where: "envelope.log_excerpt", bytes: raw.length, max: MAX_LOG_EXCERPT_BYTES });
    }
  }
  for (const key of ["tried", "questions"]) {
    if (key in env) {
      need<unknown[]>(env, key, "list", "envelope").forEach((item, i) => {
        if (typeof item !== "string") fail(ARGUMENT, "문자열 목록이어야 한다", { where: `envelope.${key}[${i}]` });
      });
    }
  }
}

function checkLink(link: Obj, where: string, needWhy: boolean): void {
  const allowed = needWhy ? ["thread_id", "message_id", "why"] : ["thread_id", "message_id"];
  closed(link, allowed, where);
  if (!isId(need<string>(link, "thread_id", "string", where))) {
    fail(ARGUMENT, "id 형식이 아니다", { where: `${where}.thread_id` });
  }
  if ("message_id" in link && !isId(need<string>(link, "message_id", "string", where))) {
    fail(ARGUMENT, "id 형식이 아니다", { where: `${where}.message_id` });
  }
  if (needWhy) need<string>(link, "why", "string", where);
}

function checkGenesis(p: Obj): void {
  closed(p, ["type", "title", "body", "envelope", "deadlines", "chair", "parent",
             "budget"], "genesis");
  const t = need<string>(p, "type", "string", "genesis");
  if (!(THREAD_TYPES as readonly string[]).includes(t)) {
    fail(ARGUMENT, "스레드 유형이 계약 밖", { type: t, allowed: THREAD_TYPES });
  }
  need<string>(p, "title", "string", "genesis");
  need<string>(p, "body", "string", "genesis");
  if (t === "problem" || t === "knowhow") {
    if (!("envelope" in p)) fail(GATE_REJECT, "봉투 없는 problem/knowhow", { type: t });
    checkEnvelope(need<Obj>(p, "envelope", "dict", "genesis"));
  }
  if ("deadlines" in p) {
    const dl = need<Obj>(p, "deadlines", "dict", "genesis");
    closed(dl, [...DEADLINE_ROUNDS], "genesis.deadlines");
    for (const k of Object.keys(dl)) need<string>(dl, k, "string", "genesis.deadlines");
  }
  if ("budget" in p) {
    // 계약 확장 9 — **모양만** 본다(아는 칸인가 · 정수인가 · 음수가 아닌가).
    // 상한(정책)은 리듀서가 격리로 판정한다 — 모양과 정책을 한 코드로 뭉개지 않는다.
    const budget = need<Obj>(p, "budget", "dict", "genesis");
    closed(budget, [...BUDGET_FIELDS], "genesis.budget");
    if (Object.keys(budget).length === 0) fail(ARGUMENT, "빈 예산 칸", { where: "genesis.budget" });
    for (const k of Object.keys(budget)) {
      if (need<number>(budget, k, "int", "genesis.budget") < 0) {
        fail(ARGUMENT, "예산이 음수다", { where: "genesis.budget", key: k });
      }
    }
  }
  if ("parent" in p) checkLink(need<Obj>(p, "parent", "dict", "genesis"), "genesis.parent", false);
  if ("chair" in p) need<string>(p, "chair", "string", "genesis");
}

function checkPost(p: Obj): void {
  closed(p, ["round", "body", "counter", "refs"], "post");
  const r = need<number>(p, "round", "int", "post");
  if (!ROUNDS.includes(r)) fail(ARGUMENT, "라운드가 계약 밖", { round: r, allowed: ROUNDS });
  need<string>(p, "body", "string", "post");
  if ("refs" in p) {
    need<unknown[]>(p, "refs", "list", "post").forEach((x, i) => {
      if (!isObj(x)) fail(ARGUMENT, "인용 항목은 객체여야 한다", { where: `post.refs[${i}]` });
      checkLink(x, `post.refs[${i}]`, true);
    });
  }
  if ("counter" in p) {
    need<unknown[]>(p, "counter", "list", "post").forEach((c, i) => {
      if (!isObj(c)) fail(ARGUMENT, "counter 항목은 객체여야 한다", { where: `post.counter[${i}]` });
      closed(c, ["target_message_id", "point"], `post.counter[${i}]`);
      const tid = need<string>(c, "target_message_id", "string", `post.counter[${i}]`);
      if (!isId(tid)) fail(ARGUMENT, "counter 대상 id 형식이 아니다", { where: `post.counter[${i}]` });
      need<string>(c, "point", "string", `post.counter[${i}]`);
    });
  }
}

function checkAdvance(p: Obj): void {
  closed(p, ["from_round", "to_round"], "advance");
  const a = need<number>(p, "from_round", "int", "advance");
  const b = need<number>(p, "to_round", "int", "advance");
  if (!ROUNDS.includes(a) || !ROUNDS.includes(b)) {
    fail(ARGUMENT, "라운드가 계약 밖", { from_round: a, to_round: b });
  }
  if (b !== a + 1) fail(ARGUMENT, "라운드는 한 칸씩만 전진한다", { from_round: a, to_round: b });
}

function checkResolution(p: Obj): void {
  closed(p, ["summary", "dissent", "recommended_actions"], "resolution");
  need<string>(p, "summary", "string", "resolution");
  need<unknown[]>(p, "dissent", "list", "resolution").forEach((d, i) => {
    if (!isObj(d)) fail(ARGUMENT, "이견 항목은 객체여야 한다", { where: `resolution.dissent[${i}]` });
    closed(d, ["from", "message_id", "quote"], `resolution.dissent[${i}]`);
    need<string>(d, "from", "string", `resolution.dissent[${i}]`);
    need<string>(d, "quote", "string", `resolution.dissent[${i}]`);
  });
  need<unknown[]>(p, "recommended_actions", "list", "resolution").forEach((a, i) => {
    const where = `resolution.recommended_actions[${i}]`;
    if (!isObj(a)) fail(ARGUMENT, "권고 항목은 객체여야 한다", { where });
    closed(a, ["text", "execution", "spawn"], where);
    need<string>(a, "text", "string", where);
    if ("spawn" in a) {
      const sw = `${where}.spawn`;
      const sp = need<Obj>(a, "spawn", "dict", where);
      closed(sp, ["type", "title"], sw);
      const t = need<string>(sp, "type", "string", sw);
      // ★열 수 있는 것은 problem·knowhow 뿐이다. debate 를 자동 제안하면 수렴이 또 수렴을 낳는다.
      if (t !== "problem" && t !== "knowhow") {
        fail(ARGUMENT, "spawn 유형이 계약 밖", { where: sw, type: t, allowed: ["problem", "knowhow"] });
      }
      need<string>(sp, "title", "string", sw);
    }
    // ★NFR-8 — 아고라의 결론은 언제나 권고다. 집행 금지 표식이 없으면 정책 위반(3).
    if (a["execution"] !== "forbidden") {
      fail(GATE_REJECT, "권고에 집행 금지 표식이 없다",
        { where, want: "forbidden", got: a["execution"] ?? null });
    }
  });
}

function checkAnswerSelected(p: Obj): void {
  closed(p, ["post_message_id"], "answer_selected");
  const mid = need<string>(p, "post_message_id", "string", "answer_selected");
  if (!isId(mid)) fail(ARGUMENT, "id 형식이 아니다", { where: "answer_selected.post_message_id", len: ID_HEX_LEN });
}

function checkClose(p: Obj): void {
  closed(p, ["reason"], "close");
  const r = need<string>(p, "reason", "string", "close");
  if (!(CLOSE_REASONS as readonly string[]).includes(r)) {
    fail(ARGUMENT, "종결 사유가 계약 밖", { reason: r, allowed: CLOSE_REASONS });
  }
}

function checkDelegateChair(p: Obj): void {
  closed(p, ["new_chair"], "delegate_chair");
  need<string>(p, "new_chair", "string", "delegate_chair");
}

function checkAbort(p: Obj): void {
  closed(p, ["reason"], "abort");
  need<string>(p, "reason", "string", "abort");
}

function checkVote(p: Obj): void {
  closed(p, ["target", "value"], "vote");
  const t = need<string>(p, "target", "string", "vote");
  if (!isId(t)) fail(ARGUMENT, "id 형식이 아니다", { where: "vote.target" });
  const v = need<number>(p, "value", "int", "vote");
  if (v !== 0 && v !== 1) fail(ARGUMENT, "투표 값은 0 또는 1", { value: v });
}

const PAYLOAD_CHECKS: Record<string, (p: Obj) => void> = {
  genesis: checkGenesis, post: checkPost, advance: checkAdvance, resolution: checkResolution,
  answer_selected: checkAnswerSelected, close: checkClose, delegate_chair: checkDelegateChair,
  abort: checkAbort, vote: checkVote,
};

// 계약 표와 이 파일이 어긋나면 그 자체가 결함이다 — 로드 시점에 잡는다.
{
  const a = Object.keys(PAYLOAD_CHECKS).sort().join(",");
  const b = [...KINDS].sort().join(",");
  if (a !== b) throw new Error(`스키마와 계약 kind 목록 불일치: ${a} != ${b}`);
}

export function validate(event: unknown): Obj {
  if (!isObj(event)) fail(ARGUMENT, "이벤트는 객체여야 한다", { got: typeof event });
  closed(event, [...COMMON_REQUIRED, ...COMMON_OPTIONAL], "event");
  if (need<number>(event, "v", "int", "event") !== 1) fail(ARGUMENT, "판본이 다르다", { v: event["v"] });
  const kind = need<string>(event, "kind", "string", "event");
  if (!(KINDS as readonly string[]).includes(kind)) {
    fail(ARGUMENT, "계약에 없는 kind", { kind, allowed: KINDS });
  }
  for (const key of ["thread_id", "message_id"]) {
    if (!isId(need<string>(event, key, "string", "event"))) {
      fail(ARGUMENT, "id 형식이 아니다", { key, want_hex_len: ID_HEX_LEN });
    }
  }
  const prev = need<string>(event, "prev", "string", "event");
  const expected = need<string>(event, "expected_state", "string", "event");
  if (kind === "genesis") {
    if (prev !== GENESIS_PREV || expected !== GENESIS_EXPECTED_STATE) {
      fail(ARGUMENT, "genesis 의 prev·expected_state 가 계약값이 아니다",
        { prev, expected_state: expected, want: [GENESIS_PREV, GENESIS_EXPECTED_STATE] });
    }
  } else {
    if (prev === GENESIS_PREV) fail(ARGUMENT, "genesis 가 아닌데 prev 가 genesis 다", { kind });
    if (prev.length !== 64) fail(ARGUMENT, "prev 는 앞 이벤트 해시여야 한다", { len: prev.length });
  }
  need<string>(event, "from", "string", "event");
  need<string>(event, "roster", "string", "event");
  need<Obj>(event, "scrub", "dict", "event");
  need<string>(event, "ts", "string", "event");
  PAYLOAD_CHECKS[kind](need<Obj>(event, "payload", "dict", "event"));
  return event;
}
