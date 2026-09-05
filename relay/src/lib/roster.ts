/**
 * 명부 — 「이 서명을 누가 했고, 그 사람이 지금도 유효한가」.
 *
 * 릴레이에서는 **D1 이 명부의 정본**이고 저장소의 `participants/*` 는 씨앗이다(D-R4).
 * 이 파일은 D1 행 ↔ OpenSSH 텍스트를 오간다 — 클라이언트가 받아서 파일로 저장해
 * `ssh-keygen -Y verify` 에 그대로 먹일 수 있어야 하기 때문이다.
 */
import { hex } from "./canonical.ts";
import type { RosterEntry } from "./sshsig.ts";

export const REL_ALLOWED = "participants/allowed_signers";
export const REL_REVOKED = "participants/revoked_keys";
export const REL_OPERATORS = "participants/operators";

const enc = new TextEncoder();

export interface ParticipantRow {
  participant_id: string;
  display_name: string;
  key_type: string;
  key_b64: string;
  fingerprint: string;
  is_operator: number;
  revoked_at: string | null;
  created_at: string;
}

export function renderAllowedSigners(rows: ParticipantRow[]): string {
  const head = [
    "# allowed_signers — 참가자 명부 (OpenSSH allowed_signers 형식)",
    "# 한 줄 = <participant-id> <키 타입> <공개키>",
    "# 이 파일은 릴레이가 D1 에서 만들어 낸다 — 손으로 고치지 않는다.",
  ];
  const body = rows
    .filter(r => !r.revoked_at)
    .sort((a, b) => (a.participant_id < b.participant_id ? -1 : a.participant_id > b.participant_id ? 1 : 0))
    .map(r => `${r.participant_id} ${r.key_type} ${r.key_b64}`);
  return head.concat(body).join("\n") + "\n";
}

export function renderRevokedKeys(rows: ParticipantRow[]): string {
  // ★「없음」도 **빈 본문**으로 말한다. 404 를 주면 받는 쪽이 fail-closed 로 멈춘다.
  const head = [
    "# revoked_keys — 폐기된 공개키 목록 (평문 공개키 한 줄에 하나)",
    "# 여기 오른 키의 서명은 유효하더라도 무효로 판정한다.",
    "# 지우지 않고 여기 올린다 — 지우면 「그때는 유효했다」를 재구성할 수 없다.",
  ];
  const body = rows
    .filter(r => !!r.revoked_at)
    .sort((a, b) => (a.fingerprint < b.fingerprint ? -1 : 1))
    .map(r => `${r.key_type} ${r.key_b64}`);
  return head.concat(body).join("\n") + "\n";
}

export function renderOperators(rows: ParticipantRow[]): string {
  const head = [
    "# operators — 운영자 participant-id 목록 (한 줄에 하나)",
    "# 운영자만 abort 와 체크포인트 서명을 할 수 있다.",
  ];
  const body = rows
    .filter(r => r.is_operator === 1 && !r.revoked_at)
    .map(r => r.participant_id)
    .sort();
  return head.concat(body).join("\n") + "\n";
}

/**
 * 명부 체크포인트 — 파이썬 `roster.checkpoint` 와 **같은 산식**이어야 한다.
 * sha256( for each rel: rel bytes | uint64be(len) | blob )
 * ★파일 경계를 해시에 넣는 이유: 안 넣으면 A 의 끝과 B 의 시작을 옮겨도 같은 해시가 된다.
 */
export async function checkpointOf(allowed: string, revoked: string, operators: string): Promise<string> {
  const parts: Uint8Array[] = [];
  const push = (rel: string, text: string) => {
    const blob = enc.encode(text);
    const len = new Uint8Array(8);
    new DataView(len.buffer).setBigUint64(0, BigInt(blob.length));
    parts.push(enc.encode(rel), len, blob);
  };
  push(REL_ALLOWED, allowed);
  push(REL_REVOKED, revoked);
  push(REL_OPERATORS, operators);
  const total = parts.reduce((a, p) => a + p.length, 0);
  const buf = new Uint8Array(total);
  let o = 0;
  for (const p of parts) { buf.set(p, o); o += p.length; }
  return hex(new Uint8Array(await crypto.subtle.digest("SHA-256", buf as BufferSource)));
}

/** D1 행 → 지문 조회표(서명 검증기가 쓰는 모양). */
export function lookupTable(rows: ParticipantRow[]): Map<string, RosterEntry> {
  const m = new Map<string, RosterEntry>();
  for (const r of rows) {
    m.set(r.fingerprint, {
      principal: r.participant_id,
      keyType: r.key_type,
      keyB64: r.key_b64,
      fingerprint: r.fingerprint,
      revoked: !!r.revoked_at,
    });
  }
  return m;
}

/** 씨앗 파일 파싱 — 우리가 만드는 부분집합만 받는다(모르는 서식은 세어서 드러낸다). */
export function parseAllowedSigners(text: string): Array<{ principal: string; keyType: string; keyB64: string }> {
  const out: Array<{ principal: string; keyType: string; keyB64: string }> = [];
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const parts = t.split(/\s+/);
    if (parts.length < 3) continue;
    const [principal, keyType, keyB64] = parts;
    if (keyType !== "ssh-ed25519") continue;
    out.push({ principal, keyType, keyB64 });
  }
  return out;
}
