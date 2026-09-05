/**
 * 운반 서식 — 게시물 원문 ↔ {이벤트, 서명}.
 * 파이썬 `agora/event.py` 의 `render_post`·`parse_post` 와 같은 계약이다.
 *
 * ★서명은 **펜스 안 글자**가 아니라 canonical 바이트에 걸린다.
 *   그래서 읽는 쪽은 「펜스 글자를 믿는다」가 아니라 **「펜스에서 구조를 읽고 canonical 로 다시 만든다」**.
 *   사람이 예쁘게 고쳐도 검증은 안 흔들리고, **내용**을 고치면 반드시 BAD 로 잡힌다.
 */
import { canonicalBytes, canonicalText, parseEventJson } from "./canonical.ts";
import { ARGUMENT, fail } from "./errors.ts";

export const POST_MARKER = "<!-- agora-event v1 -->";
const FENCE_OPEN = "```json";
const FENCE_CLOSE = "```";
const SIG_BEGIN = "-----BEGIN SSH SIGNATURE-----";
const SIG_END = "-----END SSH SIGNATURE-----";

export interface ParsedPost {
  event: Record<string, unknown>;
  signature: string | null;
  raw: Uint8Array;
  canonical: string;
}

export function parsePost(text: string): ParsedPost {
  if (typeof text !== "string" || !text.includes(POST_MARKER)) {
    fail(ARGUMENT, "이벤트 게시물 서식이 아니다", { want_marker: POST_MARKER });
  }
  const after = text.slice(text.indexOf(POST_MARKER) + POST_MARKER.length);
  const openAt = after.indexOf(FENCE_OPEN);
  if (openAt < 0) fail(ARGUMENT, "코드펜스가 없다", { want: FENCE_OPEN });
  const rest = after.slice(openAt + FENCE_OPEN.length);
  const closeAt = rest.indexOf(FENCE_CLOSE);
  if (closeAt < 0) fail(ARGUMENT, "코드펜스가 닫히지 않았다", { want: FENCE_CLOSE });
  const event = parseEventJson(rest.slice(0, closeAt).trim());

  let signature: string | null = null;
  const tail = rest.slice(closeAt + FENCE_CLOSE.length);
  const begin = tail.indexOf(SIG_BEGIN);
  if (begin >= 0) {
    const end = tail.indexOf(SIG_END, begin);
    if (end < 0) fail(ARGUMENT, "서명 블록이 닫히지 않았다", { want: SIG_END });
    signature = tail.slice(begin, end + SIG_END.length) + "\n";
  }
  // raw = **다시 만든** canonical 바이트. 펜스 안 글자를 그대로 쓰지 않는다.
  return { event, signature, raw: canonicalBytes(event), canonical: canonicalText(event) };
}

/** 저장된 canonical 텍스트 + 서명 → 게시물 원문(클라이언트가 `parse_post` 로 그대로 읽는다). */
export function renderPost(canonical: string, signature: string | null): string {
  const parts = [POST_MARKER, FENCE_OPEN, canonical, FENCE_CLOSE];
  if (signature) parts.push(signature.trim());
  return parts.join("\n") + "\n";
}
