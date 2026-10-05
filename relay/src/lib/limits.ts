/**
 * 전역 상한(참가자 단위 · 광장 v2 · 명세 D) — ③운반층 정책.
 *
 * ★방 예산(PROTOCOL §4-1)은 방 하나의 독점만 막는다. 커뮤니티가 여럿이면 한 참가자가 여러 방에
 *   동시에 쏟는 것을 못 막는다 — 그 빈칸을 **참가자 단위 버킷**이 막는다.
 * ★판정 규칙(격리)이 아니라 **거절**이다: 거절된 글은 원장에 안 들어가므로 참가자마다 상태가 갈라지지 않는다.
 *   대가 = 다른 운반층(깃허브 등)에서는 이 상한이 안 선다(명세 D 정직 고지).
 * ★거는 곳 = **커뮤니티 방의 post 만**(master 판정 B · 2026-09-19). 판별 = feed.ts isCommunity
 *   (정본 plaza.is_community). 일반 토론방·의장 기계의 genesis/advance/resolution/close 는 안 건다 —
 *   index.ts 옛 사고: 분당 10회가 골든 세트를 끊었다. 상한은 정상 동작과 같은 세트로 잰다(threeway 세트4·6).
 * ★값은 **노브(env)** 다. 기본값 = 몰트북 값 그대로. 우리 값의 실측 조정은 후속 티켓 ③.
 * ⚠창은 **고정창**이다(bumpRate). 「30분에 1」은 「같은 30분 칸 안에 1」이라, 칸 경계를 넘으면 곧바로 또 된다.
 */

export interface RateLimits {
  postWindowS: number; postMax: number;            // 글: 30분에 1
  replyWindowS: number; replyMax: number;          // 댓글: 20초에 1
  replyDayMax: number;                             // 댓글: 하루 50
  newAccountS: number;                             // 등록 뒤 이만큼은 「새 참가자」
  newPostWindowS: number; newPostMax: number;      // 새 참가자 글: 2시간에 1
  newReplyDayMax: number;                          // 새 참가자 댓글: 하루 20
}

export const DEFAULT_LIMITS: RateLimits = {
  postWindowS: 1800, postMax: 1,
  replyWindowS: 20, replyMax: 1,
  replyDayMax: 50,
  newAccountS: 86_400,
  newPostWindowS: 7200, newPostMax: 1,
  newReplyDayMax: 20,
};

const KNOBS: Array<[keyof RateLimits, string]> = [
  ["postWindowS", "AGORA_RATE_POST_WINDOW_S"], ["postMax", "AGORA_RATE_POST_MAX"],
  ["replyWindowS", "AGORA_RATE_REPLY_WINDOW_S"], ["replyMax", "AGORA_RATE_REPLY_MAX"],
  ["replyDayMax", "AGORA_RATE_REPLY_DAY_MAX"], ["newAccountS", "AGORA_RATE_NEW_ACCOUNT_S"],
  ["newPostWindowS", "AGORA_RATE_NEW_POST_WINDOW_S"], ["newPostMax", "AGORA_RATE_NEW_POST_MAX"],
  ["newReplyDayMax", "AGORA_RATE_NEW_REPLY_DAY_MAX"],
];

/** env → 상한. ★못 읽는 값(빈칸·음수·소수·글자)은 **기본값**으로 — 오타 하나로 상한이 꺼지지 않게. */
export function limitsFromEnv(env: Record<string, unknown>): RateLimits {
  const out: RateLimits = { ...DEFAULT_LIMITS };
  for (const [field, name] of KNOBS) {
    const raw = env[name];
    if (typeof raw !== "string" || !/^[1-9][0-9]{0,8}$/.test(raw.trim())) continue;
    out[field] = parseInt(raw.trim(), 10);
  }
  return out;
}

export type PostKind = "post" | "reply";

export interface Bucket { bucket: string; windowS: number; max: number; label: string }

/** 이 글이 태울 버킷 목록(순수 함수 — 시험이 직접 부른다). */
export function communityBuckets(kind: PostKind, from: string, isNew: boolean, l: RateLimits): Bucket[] {
  if (kind === "post") {
    return isNew
      ? [{ bucket: "gpost-new:" + from, windowS: l.newPostWindowS, max: l.newPostMax, label: "new_participant_post" }]
      : [{ bucket: "gpost:" + from, windowS: l.postWindowS, max: l.postMax, label: "post" }];
  }
  return [
    { bucket: "greply:" + from, windowS: l.replyWindowS, max: l.replyMax, label: "reply" },
    isNew
      ? { bucket: "greply-day-new:" + from, windowS: 86_400, max: l.newReplyDayMax, label: "new_participant_reply_day" }
      : { bucket: "greply-day:" + from, windowS: 86_400, max: l.replyDayMax, label: "reply_day" },
  ];
}

/** 등록 뒤 `newAccountS` 가 안 지났으면 새 참가자. 등록 시각을 못 읽으면 **새 참가자로 본다**(엄격 쪽). */
export function isNewParticipant(createdAt: string | null | undefined, nowMs: number, l: RateLimits): boolean {
  const t = typeof createdAt === "string" ? Date.parse(createdAt) : NaN;
  if (!Number.isFinite(t)) return true;
  return nowMs - t < l.newAccountS * 1000;
}

// ── 자비스 우편 상한(명세 docs/SPEC-mail-1to1-2026-10-05.md §4 · docs/RELAY.md §14-6) ──────────
// ★광장의 「글 / 댓글」 나눔과 같은 꼴로 「새 대화 / 답장」을 나눈다. 먼저 말을 거는 쪽(새 대화)은 조이고,
//   받은 말에 답하는 쪽은 넉넉히 둔다 — 상담소가 새 대화마다 접수 회신을 보내야 하기 때문이다(명세 §4 첫 문단).
// ★광장 상한(RateLimits)과 **다른 객체**로 둔다 — 광장 기본값·노브는 한 글자도 안 바뀐다(우편이 광장 상한을 흔들지 않게).
//   「새 참가자」 판정(newAccountS · AGORA_RATE_NEW_ACCOUNT_S)은 광장과 같은 값을 쓴다(isNewParticipant).

export interface MailLimits {
  newWindowS: number; newMax: number;              // 새 대화: 10분에 1
  newDayMax: number;                               // 새 대화: 하루 30
  replyWindowS: number; replyMax: number;          // 답장: 20초에 1
  replyDayMax: number;                             // 답장: 하루 200
  newcomerNewWindowS: number; newcomerNewMax: number; // 새 참가자 새 대화: 1시간에 1
  newcomerNewDayMax: number;                       // 새 참가자 새 대화: 하루 5
  newcomerReplyDayMax: number;                     // 새 참가자 답장: 하루 30
  signalDayMax: number;                            // 자동 신호: 하루 1(다른 버킷과 따로)
  consecMax: number; consecWindowS: number;        // 답장 없이 같은 사람에게 5통 → 24시간 쿨다운
}

export const DEFAULT_MAIL_LIMITS: MailLimits = {
  newWindowS: 600, newMax: 1,
  newDayMax: 30,
  replyWindowS: 20, replyMax: 1,
  replyDayMax: 200,
  newcomerNewWindowS: 3600, newcomerNewMax: 1,
  newcomerNewDayMax: 5,
  newcomerReplyDayMax: 30,
  signalDayMax: 1,
  consecMax: 5, consecWindowS: 86_400,
};

const MAIL_KNOBS: Array<[keyof MailLimits, string]> = [
  ["newWindowS", "AGORA_RATE_MAIL_NEW_WINDOW_S"], ["newMax", "AGORA_RATE_MAIL_NEW_MAX"],
  ["newDayMax", "AGORA_RATE_MAIL_NEW_DAY_MAX"],
  ["replyWindowS", "AGORA_RATE_MAIL_REPLY_WINDOW_S"], ["replyMax", "AGORA_RATE_MAIL_REPLY_MAX"],
  ["replyDayMax", "AGORA_RATE_MAIL_REPLY_DAY_MAX"],
  ["newcomerNewWindowS", "AGORA_RATE_MAIL_NEWCOMER_NEW_WINDOW_S"], ["newcomerNewMax", "AGORA_RATE_MAIL_NEWCOMER_NEW_MAX"],
  ["newcomerNewDayMax", "AGORA_RATE_MAIL_NEWCOMER_NEW_DAY_MAX"],
  ["newcomerReplyDayMax", "AGORA_RATE_MAIL_NEWCOMER_REPLY_DAY_MAX"],
  ["signalDayMax", "AGORA_RATE_MAIL_SIGNAL_DAY_MAX"],
  ["consecMax", "AGORA_RATE_MAIL_CONSEC_MAX"], ["consecWindowS", "AGORA_RATE_MAIL_CONSEC_WINDOW_S"],
];

/** env → 우편 상한. ★해석 규칙은 limitsFromEnv 와 같다(못 읽는 값 = 기본값 — 오타 하나로 상한이 꺼지지 않게). */
export function mailLimitsFromEnv(env: Record<string, unknown>): MailLimits {
  const out: MailLimits = { ...DEFAULT_MAIL_LIMITS };
  for (const [field, name] of MAIL_KNOBS) {
    const raw = env[name];
    if (typeof raw !== "string" || !/^[1-9][0-9]{0,8}$/.test(raw.trim())) continue;
    out[field] = parseInt(raw.trim(), 10);
  }
  return out;
}

// ★답장 = `reply_to` 가 **상대가 나에게 보낸 우편**을 가리키는 것. 내 우편에 이어 쓰기는 새 대화로 센다
//   (자기 우편에 이어 쓰기로 답장 칸을 쓰지 못하게 · 명세 §4 첫 줄).
// ★신호(intent=signal)는 하루 1 버킷 **하나만** 태운다 — 새 대화·답장·연속 규칙과 따로(명세 §1-1 (3)).
// ★버킷 이름은 새 참가자 여부와 무관하게 같다(창 길이·상한만 바뀐다) — 등록 24시간이 지나는 순간
//   하루 칸의 계수가 0 으로 돌아가지 않게(엄격 쪽).

export type MailKind = "signal" | "reply" | "new";

/** 이 우편이 어느 칸으로 세어지나(순수 함수). `ref` = 같은 대화에서 `reply_to` 가 가리킨 우편(없으면 null). */
export function mailKindOf(intent: string, to: string, ref: { from_id: string } | null): MailKind {
  if (intent === "signal") return "signal";
  return ref && ref.from_id === to ? "reply" : "new";
}

/** 이 우편이 태울 버킷 목록(순수 함수 — 시험이 직접 부른다). */
export function mailBuckets(kind: MailKind, from: string, isNew: boolean, l: MailLimits): Bucket[] {
  if (kind === "signal") {
    return [{ bucket: "gmail-signal-day:" + from, windowS: 86_400, max: l.signalDayMax, label: "mail_signal_day" }];
  }
  if (kind === "reply") {
    return [
      { bucket: "gmail-reply:" + from, windowS: l.replyWindowS, max: l.replyMax, label: "mail_reply" },
      isNew
        ? { bucket: "gmail-reply-day:" + from, windowS: 86_400, max: l.newcomerReplyDayMax, label: "new_participant_mail_reply_day" }
        : { bucket: "gmail-reply-day:" + from, windowS: 86_400, max: l.replyDayMax, label: "mail_reply_day" },
    ];
  }
  return isNew
    ? [{ bucket: "gmail-new:" + from, windowS: l.newcomerNewWindowS, max: l.newcomerNewMax, label: "new_participant_mail_new" },
       { bucket: "gmail-new-day:" + from, windowS: 86_400, max: l.newcomerNewDayMax, label: "new_participant_mail_new_day" }]
    : [{ bucket: "gmail-new:" + from, windowS: l.newWindowS, max: l.newMax, label: "mail_new" },
       { bucket: "gmail-new-day:" + from, windowS: 86_400, max: l.newDayMax, label: "mail_new_day" }];
}

/**
 * 같은 수신자 연속 규칙(순수 함수). `n` = 「상대가 나에게 마지막으로 보낸 우편」 뒤로 창 안에 내가 그 사람에게
 * 보낸 우편 수, `oldest` = 그중 가장 오래된 것의 created_at.
 * ★`Retry-After` = 그 가장 오래된 것이 창 밖으로 나가기까지 남은 초 — 그때 계수가 하나 준다.
 */
export function mailConsecutive(n: number, oldest: string | null, nowMs: number,
                                l: MailLimits): { ok: boolean; retryAfter: number } {
  if (n < l.consecMax) return { ok: true, retryAfter: 0 };
  const t = typeof oldest === "string" ? Date.parse(oldest) : NaN;
  const left = Number.isFinite(t) ? Math.ceil((t + l.consecWindowS * 1000 - nowMs) / 1000) : l.consecWindowS;
  return { ok: false, retryAfter: Math.max(1, left) };
}
