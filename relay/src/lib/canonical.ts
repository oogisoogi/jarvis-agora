/**
 * canonical JSON — 서명 대상 바이트를 만드는 유일한 자리.
 *
 * 파이썬 `agora/event.py` 의 규칙을 **바꾸지 않고 옮긴 것**이다:
 *   UTF-8 · NFC 정규화(키와 문자열 값 모두) · 문자열 안 CR·CRLF → LF ·
 *   키 정렬 · 구분자에 공백 없음 · 개행 없음 · 중복 키 거부 · 실수 거부 · 최대 64KB
 *
 * ★직렬화를 손으로 쓴 이유(자바스크립트 고유 함정 2가지):
 *   ⑴ JS 객체는 **정수처럼 생긴 키를 숫자 순서로 먼저** 늘어놓는다. 객체 순서에 기대면
 *      키 정렬이 조용히 다른 값을 낸다.
 *   ⑵ `Array.sort()` 기본 비교는 **UTF-16 코드 단위** 순서라 BMP 밖 문자에서 파이썬의
 *      **코드포인트** 순서와 갈린다. 그래서 비교기를 직접 준다.
 *   둘 다 지금 우리 스키마에서는 안 터지지만, 터지면 **서명이 갈라지고 아무 오류도 안 난다.**
 */
import { ARGUMENT, GATE_REJECT, fail } from "./errors.ts";

export const MAX_EVENT_BYTES = 64 * 1024;
export const ID_HEX_LEN = 32;

const enc = new TextEncoder();

export function isId(v: unknown): boolean {
  return typeof v === "string" && v.length === ID_HEX_LEN && /^[0-9a-f]+$/.test(v);
}

function nfc(s: string): string {
  return s.normalize("NFC");
}

function normalizeNewlines(s: string): string {
  return s.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function normKey(s: string): string {
  return nfc(normalizeNewlines(s));
}

/** 코드포인트 순서 비교(파이썬 `sorted()` 와 같은 순서). */
function byCodePoint(a: string, b: string): number {
  const ai = Array.from(a), bi = Array.from(b);
  const n = Math.min(ai.length, bi.length);
  for (let i = 0; i < n; i++) {
    const x = ai[i].codePointAt(0)!, y = bi[i].codePointAt(0)!;
    if (x !== y) return x < y ? -1 : 1;
  }
  return ai.length === bi.length ? 0 : (ai.length < bi.length ? -1 : 1);
}

function serialize(node: unknown, path = "$"): string {
  if (node === null) return "null";
  const t = typeof node;
  if (t === "boolean") return node ? "true" : "false";
  if (t === "number") {
    if (!Number.isInteger(node as number)) {
      fail(ARGUMENT, "이벤트에 실수를 담을 수 없다", { path });
    }
    if (!Number.isSafeInteger(node as number)) {
      // 안전 범위 밖 정수는 파이썬과 표현이 갈린다 — 들어올 길을 막는다.
      fail(ARGUMENT, "정수 범위 밖", { path });
    }
    return String(node);
  }
  if (t === "string") return JSON.stringify(nfc(normalizeNewlines(node as string)));
  if (Array.isArray(node)) {
    return "[" + node.map((v, i) => serialize(v, `${path}[${i}]`)).join(",") + "]";
  }
  if (t === "object") {
    const src = node as Record<string, unknown>;
    const seen = new Map<string, unknown>();
    for (const k of Object.keys(src)) {
      const nk = normKey(k);
      if (seen.has(nk)) fail(ARGUMENT, "정규화 후 키 충돌", { path, key: nk });
      seen.set(nk, src[k]);
    }
    const keys = Array.from(seen.keys()).sort(byCodePoint);
    return "{" + keys.map(k => `${JSON.stringify(k)}:${serialize(seen.get(k), `${path}.${k}`)}`).join(",") + "}";
  }
  fail(ARGUMENT, "직렬화할 수 없는 타입", { path, type: t });
}

/** 이벤트 → 서명 입력 바이트. 이 함수의 출력이 곧 서명 대상이다. */
export function canonicalText(event: unknown): string {
  const text = serialize(event);
  if (text.includes("\n") || text.includes("\r")) {
    fail(ARGUMENT, "canonical 에 개행이 있다", null);
  }
  return text;
}

export function canonicalBytes(event: unknown): Uint8Array {
  const text = canonicalText(event);
  const raw = enc.encode(text);
  if (raw.length > MAX_EVENT_BYTES) {
    fail(GATE_REJECT, "이벤트 크기 상한 초과",
         { bytes: raw.length, limit: MAX_EVENT_BYTES }, { status: 413 });
  }
  return raw;
}

export async function sha256Hex(data: Uint8Array): Promise<string> {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", data as BufferSource));
  return hex(d);
}

export function hex(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += b.toString(16).padStart(2, "0");
  return s;
}

export async function eventHash(event: unknown): Promise<string> {
  return sha256Hex(canonicalBytes(event));
}

/**
 * 운반층에서 온 JSON 을 읽는다. **중복 키를 조용히 삼키지 않는다.**
 * `JSON.parse` 는 중복 키에서 마지막 값을 채택한다 — 그러면 서명 대상과 해석 대상이 갈라지고,
 * 그 틈으로 「서명은 맞는데 내용이 다른」 이벤트가 들어온다.
 */
export function parseEventJson(text: string): Record<string, unknown> {
  if (enc.encode(text).length > MAX_EVENT_BYTES) {
    fail(GATE_REJECT, "이벤트 크기 상한 초과", { limit: MAX_EVENT_BYTES }, { status: 413 });
  }
  const stack: Array<Set<string>> = [];
  let obj: unknown;
  try {
    obj = JSON.parse(text, function (this: any, key, value) {
      return value;
    });
  } catch (e) {
    fail(ARGUMENT, "JSON 파싱 실패", { error: String(e).slice(0, 120) });
  }
  // 중복 키·실수는 파서가 감춘다 → 원문을 훑어 직접 잡는다.
  rejectDuplicateKeysAndFloats(text);
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) {
    fail(ARGUMENT, "이벤트는 객체여야 한다", { type: Array.isArray(obj) ? "array" : typeof obj });
  }
  void stack;
  return obj as Record<string, unknown>;
}

/**
 * 원문 토큰을 훑어 ⑴같은 객체 안 중복 키 ⑵실수 리터럴을 잡는다.
 * ★`JSON.parse` 뒤에 값으로 검사하면 **둘 다 이미 사라진 뒤**다 —
 *   중복 키는 마지막 것만 남고, `1.0` 은 `1` 과 구별되지 않는다.
 */
function rejectDuplicateKeysAndFloats(text: string): void {
  const frames: Array<Set<string>> = [];
  let i = 0;
  const n = text.length;
  let pendingKey: string | null = null;
  while (i < n) {
    const c = text[i];
    if (c === '"') {
      const start = i;
      i++;
      while (i < n) {
        if (text[i] === "\\") { i += 2; continue; }
        if (text[i] === '"') break;
        i++;
      }
      const rawTok = text.slice(start, i + 1);
      i++;
      // 뒤에 오는 첫 비공백이 ':' 이면 이 문자열은 키다.
      let j = i;
      while (j < n && /\s/.test(text[j])) j++;
      if (text[j] === ":" && frames.length) {
        const key = normKey(JSON.parse(rawTok) as string);
        const top = frames[frames.length - 1];
        if (top.has(key)) fail(ARGUMENT, "중복 키", { key });
        top.add(key);
      }
      pendingKey = null;
      continue;
    }
    if (c === "{") { frames.push(new Set()); i++; continue; }
    if (c === "}") { frames.pop(); i++; continue; }
    if (/[-0-9]/.test(c)) {
      let j = i;
      if (text[j] === "-") j++;
      while (j < n && /[0-9]/.test(text[j])) j++;
      if (text[j] === "." || text[j] === "e" || text[j] === "E") {
        fail(ARGUMENT, "이벤트에 실수를 담을 수 없다", { at: text.slice(i, j + 6) });
      }
      i = j;
      continue;
    }
    i++;
    void pendingKey;
  }
}
