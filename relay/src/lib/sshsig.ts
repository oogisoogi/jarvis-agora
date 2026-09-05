/**
 * SSHSIG 검증 — `ssh-keygen -Y verify` 가 하는 일을 순수 TS 로 옮긴 것.
 *
 * Workers 에는 `ssh-keygen` 이 없다. 그래서 이 파일이 아고라 신뢰의 **바닥**이다.
 * ⇒ 여기서 틀리면 다른 어떤 게이트도 의미가 없다. 그래서 시험이 정상만이 아니라
 *   **변조·namespace 위조·명부 밖·폐기** 넷을 전부 적색으로 만드는지 잰다.
 *
 * 실측(2026-09-05 · golden 벡터 + workerd 4.118.0):
 *   정상 = true · 본문 1글자 변조 = false · namespace 위조 = false.
 *
 * 형식(RFC 초안 PROTOCOL.sshsig · golden 벡터로 실측 확인):
 *   armor  = "-----BEGIN SSH SIGNATURE-----" base64 "-----END SSH SIGNATURE-----"
 *   blob   = "SSHSIG" | uint32 version | string publickey | string namespace
 *            | string reserved | string hash_algorithm | string signature
 *   서명 대상 = "SSHSIG" | string namespace | string reserved | string hash_alg | string H(message)
 */
import { SIGNATURE, fail } from "./errors.ts";

const enc = new TextEncoder();
const dec = new TextDecoder();

export const VERDICT_OK = "ok";
export const VERDICT_BAD = "BAD";
export const VERDICT_UNSIGNED = "unsigned";
export type Verdict = typeof VERDICT_OK | typeof VERDICT_BAD | typeof VERDICT_UNSIGNED;

export interface VerifyResult {
  verdict: Verdict;
  reason: string;
  fingerprint: string | null;
}

class Reader {
  constructor(private b: Uint8Array, private i = 0) {}
  bytes(n: number): Uint8Array {
    // ★계약 오류로 던진다. 원시 Error 로 새면 라우터가 그것을 「알 수 없는 실패」로 읽어
    //   401(code 4)이어야 할 응답이 500(code 7)으로 나간다 — 조작된 길이 필드 하나로
    //   실패 계약이 뒤집힌다(agy 지적 1 · 2026-09-05).
    if (n < 0 || this.i + n > this.b.length) fail(SIGNATURE, "서명 블록이 짧다", { want: n });
    const s = this.b.subarray(this.i, this.i + n);
    this.i += n;
    return s;
  }
  u32(): number {
    const s = this.bytes(4);
    return ((s[0] << 24) >>> 0) + (s[1] << 16) + (s[2] << 8) + s[3];
  }
  str(): Uint8Array { return this.bytes(this.u32()); }
  get rest(): number { return this.b.length - this.i; }
}

function sshString(bytes: Uint8Array): Uint8Array {
  const out = new Uint8Array(4 + bytes.length);
  new DataView(out.buffer).setUint32(0, bytes.length);
  out.set(bytes, 4);
  return out;
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((a, p) => a + p.length, 0);
  const out = new Uint8Array(total);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

export function b64decode(s: string): Uint8Array {
  const bin = atob(s.replace(/\s+/g, ""));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function b64encode(b: Uint8Array): string {
  let s = "";
  for (const x of b) s += String.fromCharCode(x);
  return btoa(s);
}

const BEGIN = "-----BEGIN SSH SIGNATURE-----";
const END = "-----END SSH SIGNATURE-----";

export function hasArmor(sig: string | null | undefined): boolean {
  return !!sig && sig.includes("BEGIN SSH SIGNATURE");
}

export interface ParsedSignature {
  version: number;
  publicKeyBlob: Uint8Array;
  namespace: string;
  reserved: Uint8Array;
  hashAlgorithm: string;
  signatureBlob: Uint8Array;
}

export function parseArmored(sig: string): ParsedSignature {
  const b = sig.indexOf(BEGIN);
  const e = sig.indexOf(END);
  if (b < 0 || e < 0 || e < b) fail(SIGNATURE, "서명 블록 서식이 아니다", null);
  const body = sig.slice(b + BEGIN.length, e);
  let raw: Uint8Array;
  try { raw = b64decode(body); }
  catch { return fail(SIGNATURE, "서명 base64 해독 실패", null); }
  const r = new Reader(raw);
  const magic = dec.decode(r.bytes(6));
  if (magic !== "SSHSIG") fail(SIGNATURE, "SSHSIG magic 불일치", { got: magic });
  const version = r.u32();
  const publicKeyBlob = r.str();
  const namespace = dec.decode(r.str());
  const reserved = r.str();
  const hashAlgorithm = dec.decode(r.str());
  const signatureBlob = r.str();
  return { version, publicKeyBlob, namespace, reserved, hashAlgorithm, signatureBlob };
}

/** 공개키 blob → {type, key}. `ssh-ed25519` 만 받는다(v1). */
export function parsePublicKeyBlob(blob: Uint8Array): { type: string; key: Uint8Array } {
  const r = new Reader(blob);
  const type = dec.decode(r.str());
  const key = r.str();
  // ★끝에 남은 바이트는 조용히 넘기지 않는다 — 파서가 「다 읽었다」를 말할 수 있어야 한다.
  if (r.rest !== 0) fail(SIGNATURE, "공개키 blob 뒤에 잉여 바이트가 있다", { rest: r.rest });
  return { type, key };
}

function parseSignatureBlob(blob: Uint8Array): { type: string; sig: Uint8Array } {
  const r = new Reader(blob);
  const type = dec.decode(r.str());
  const sig = r.str();
  if (r.rest !== 0) fail(SIGNATURE, "서명 blob 뒤에 잉여 바이트가 있다", { rest: r.rest });
  return { type, sig };
}

/** OpenSSH 지문 `SHA256:<base64 패딩없음>` — `ssh-keygen -l` 과 같은 값(2026-09-05 실측). */
export async function fingerprintOf(publicKeyBlob: Uint8Array): Promise<string> {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", publicKeyBlob as BufferSource));
  return "SHA256:" + b64encode(d).replace(/=+$/, "");
}

/**
 * 서명 자체가 이 바이트에 대해 유효한가 — **명부와 무관한 질문**이다
 * (`ssh-keygen -Y check-novalidate` 에 해당).
 */
export async function checkSignatureBytes(
  message: Uint8Array, parsed: ParsedSignature, namespace: string,
): Promise<{ ok: boolean; fingerprint: string | null; why: string }> {
  if (parsed.version !== 1) return { ok: false, fingerprint: null, why: "version" };
  if (parsed.namespace !== namespace) {
    // namespace 가 다르면 「다른 용도의 서명」이다. 재사용을 막는 칸이라 반드시 본다.
    return { ok: false, fingerprint: null, why: "namespace" };
  }
  const pk = parsePublicKeyBlob(parsed.publicKeyBlob);
  const sb = parseSignatureBlob(parsed.signatureBlob);
  if (pk.type !== "ssh-ed25519" || sb.type !== "ssh-ed25519") {
    return { ok: false, fingerprint: null, why: "key_type" };
  }
  if (pk.key.length !== 32 || sb.sig.length !== 64) {
    return { ok: false, fingerprint: null, why: "key_or_sig_length" };
  }
  const hashName = parsed.hashAlgorithm === "sha512" ? "SHA-512"
    : parsed.hashAlgorithm === "sha256" ? "SHA-256" : null;
  if (!hashName) return { ok: false, fingerprint: null, why: "hash_algorithm" };

  const H = new Uint8Array(await crypto.subtle.digest(hashName, message as BufferSource));
  const signed = concat(enc.encode("SSHSIG"), sshString(enc.encode(parsed.namespace)),
                        sshString(parsed.reserved), sshString(enc.encode(parsed.hashAlgorithm)),
                        sshString(H));
  const fp = await fingerprintOf(parsed.publicKeyBlob);
  let key: CryptoKey;
  try {
    key = await crypto.subtle.importKey("raw", pk.key as BufferSource, { name: "Ed25519" }, false, ["verify"]);
  } catch {
    return { ok: false, fingerprint: fp, why: "import_key" };
  }
  const ok = await crypto.subtle.verify({ name: "Ed25519" }, key, sb.sig as BufferSource, signed as BufferSource);
  return { ok, fingerprint: fp, why: ok ? "verified" : "signature_does_not_match_bytes" };
}

export interface RosterEntry {
  principal: string;
  keyType: string;
  keyB64: string;
  fingerprint: string;
  revoked: boolean;
}

/**
 * 3값 판정 — `ok` / `BAD` / `unsigned`. 파이썬 `sign.verify_detail` 과 같은 계약.
 * ★셋을 뭉치지 않는다. 「변조됐다」와 「모르는 사람이다」가 구별되지 않으면 조치가 갈린다.
 */
export async function verifyDetail(args: {
  message: Uint8Array;
  signature: string | null | undefined;
  principal: string;
  namespace: string;
  lookup: (fingerprint: string) => RosterEntry | undefined;
}): Promise<VerifyResult> {
  if (!hasArmor(args.signature)) {
    return { verdict: VERDICT_UNSIGNED, reason: "no_signature", fingerprint: null };
  }
  let parsed: ParsedSignature;
  try { parsed = parseArmored(args.signature as string); }
  catch { return { verdict: VERDICT_BAD, reason: "malformed_signature", fingerprint: null }; }

  const checked = await checkSignatureBytes(args.message, parsed, args.namespace);
  if (!checked.ok) {
    // namespace 불일치·형식 문제는 **변조 정황이 아니다**(다른 용도의 유효한 서명일 수 있다).
    // 바이트와 안 맞는 것만 BAD 다.
    const bad = checked.why === "signature_does_not_match_bytes";
    return {
      verdict: bad ? VERDICT_BAD : VERDICT_UNSIGNED,
      reason: checked.why, fingerprint: checked.fingerprint,
    };
  }
  const fp = checked.fingerprint!;
  const entry = args.lookup(fp);
  if (!entry) return { verdict: VERDICT_UNSIGNED, reason: "not_in_roster", fingerprint: fp };
  if (entry.revoked) return { verdict: VERDICT_UNSIGNED, reason: "revoked", fingerprint: fp };
  if (entry.principal !== args.principal) {
    // 서명은 유효하지만 **그 키는 이 참가자의 키가 아니다**(`-I <principal>` 이 하는 일).
    return { verdict: VERDICT_UNSIGNED, reason: "principal_mismatch", fingerprint: fp };
  }
  return { verdict: VERDICT_OK, reason: "verified", fingerprint: fp };
}
