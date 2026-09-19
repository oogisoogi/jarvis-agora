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
