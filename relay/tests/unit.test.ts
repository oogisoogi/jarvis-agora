/**
 * 단위 시험 — **순수 모듈만** 여기서 잰다(암호·직렬화·스키마·사슬).
 * 서버 왕복·D1·리듀서 3자 대조는 `scripts/run-local.py`(실제 workerd + 실제 D1)가 잰다.
 * ★그렇게 가른 이유: 에뮬레이터가 통과시키는 것을 실물이 거절한 선례가 있다.
 *   실물로 잴 수 있는 것은 실물로 잰다.
 *
 * ★각 축에 **음성 대조**를 붙인다. 통과만 재는 시험은 「검사가 도는지」를 증명하지 못한다.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { canonicalText, eventHash, parseEventJson } from "../src/lib/canonical.ts";
import { AgoraError } from "../src/lib/errors.ts";
import { parsePost, renderPost } from "../src/lib/post.ts";
import * as schema from "../src/lib/schema.ts";
import { checkSignatureBytes, fingerprintOf, parseArmored, b64decode,
         verifyDetail } from "../src/lib/sshsig.ts";
import { apply, order, stateHash, type ValidEntry } from "../src/lib/reducer.ts";
import { checkpointOf } from "../src/lib/roster.ts";
import { loadBundle, check as scrubCheck } from "../src/lib/scrub.ts";
import { bumpRate, eventIdOf, nowIso } from "../src/lib/store.ts";

const REPO = new URL("../../", import.meta.url).pathname;
const GOLDEN = JSON.parse(readFileSync(REPO + "tests/golden/canonical-vectors.json", "utf8"));
const NS = "jarvis-agora@godmeyou.kr";
const enc = new TextEncoder();

function codeOf(fn: () => unknown): number | string {
  try { fn(); return "던지지 않았다"; }
  catch (e) { return e instanceof AgoraError ? e.code : "다른 예외"; }
}

describe("canonical — 파이썬과 바이트가 같아야 한다", () => {
  it("golden 5변형(CR·CRLF·LF × NFC·NFD)이 같은 canonical·해시로 떨어진다", async () => {
    for (const [name, payload] of Object.entries<any>(GOLDEN.variants)) {
      const ev = { ...GOLDEN.base_event, payload };
      expect(canonicalText(ev), name).toBe(GOLDEN.expected_canonical_utf8);
      expect(await eventHash(ev), name).toBe(GOLDEN.expected_hash);
    }
  });

  it("실수·중복 키는 거부한다(음성 대조)", () => {
    expect(codeOf(() => canonicalText({ a: 1.5 }))).toBe(10);
    expect(codeOf(() => parseEventJson('{"a":1,"a":2}'))).toBe(10);
    expect(codeOf(() => parseEventJson('{"a":1.0}'))).toBe(10);
  });

  it("키 정렬이 실제로 일어난다(정렬을 빼면 다른 문자열이 된다)", () => {
    expect(canonicalText({ b: 1, a: 2 })).toBe('{"a":2,"b":1}');
  });
});

describe("post — 게시물 서식 왕복", () => {
  it("render → parse 왕복에서 이벤트가 보존된다", () => {
    const ev = { ...GOLDEN.base_event, payload: GOLDEN.variants["lf-nfc"] };
    const body = renderPost(canonicalText(ev), GOLDEN.signature);
    const parsed = parsePost(body);
    expect(parsed.canonical).toBe(GOLDEN.expected_canonical_utf8);
    expect(parsed.signature).toContain("BEGIN SSH SIGNATURE");
  });

  it("표식이 없으면 거부한다(음성 대조)", () => {
    expect(codeOf(() => parsePost("```json\n{}\n```"))).toBe(10);
  });
});

describe("sshsig — 이 파일이 틀리면 다른 게이트가 전부 무의미하다", () => {
  const message = enc.encode(GOLDEN.expected_canonical_utf8);
  const pubBlob = b64decode(GOLDEN.public_key.split(/\s+/)[1]);

  it("golden 서명이 검증된다", async () => {
    const r = await checkSignatureBytes(message, parseArmored(GOLDEN.signature), NS);
    expect(r.ok).toBe(true);
    expect(r.fingerprint).toBe(await fingerprintOf(pubBlob));
  });

  it("본문을 한 글자 바꾸면 실패한다(BAD)", async () => {
    const tampered = enc.encode(GOLDEN.expected_canonical_utf8.replace("첫 줄", "첫 쥴"));
    const r = await checkSignatureBytes(tampered, parseArmored(GOLDEN.signature), NS);
    expect(r.ok).toBe(false);
    expect(r.why).toBe("signature_does_not_match_bytes");
  });

  it("namespace 가 다르면 받지 않는다", async () => {
    const r = await checkSignatureBytes(message, parseArmored(GOLDEN.signature), "wrong@ns");
    expect(r.ok).toBe(false);
    expect(r.why).toBe("namespace");
  });

  it("3값 판정: 명부 밖·폐기·principal 불일치를 가른다", async () => {
    const fp = await fingerprintOf(pubBlob);
    const base = { message, signature: GOLDEN.signature, namespace: NS };
    const entry = { principal: GOLDEN.principal, keyType: "ssh-ed25519",
                    keyB64: GOLDEN.public_key.split(/\s+/)[1], fingerprint: fp, revoked: false };
    expect((await verifyDetail({ ...base, principal: GOLDEN.principal,
      lookup: () => entry })).verdict).toBe("ok");
    expect((await verifyDetail({ ...base, principal: GOLDEN.principal,
      lookup: () => undefined })).reason).toBe("not_in_roster");
    expect((await verifyDetail({ ...base, principal: GOLDEN.principal,
      lookup: () => ({ ...entry, revoked: true }) })).reason).toBe("revoked");
    expect((await verifyDetail({ ...base, principal: "someone-else",
      lookup: () => entry })).reason).toBe("principal_mismatch");
    expect((await verifyDetail({ ...base, principal: GOLDEN.principal, signature: null,
      lookup: () => entry })).reason).toBe("no_signature");
  });
});

describe("schema — 닫힌 계약", () => {
  // ★golden base_event 에는 `scrub` 칸이 없다(그 파일은 **직렬화** 벡터이지 스키마 벡터가 아니다).
  //   그대로 쓰면 모든 검사가 「필수 칸 누락(10)」으로 끝나, 10 을 기대하는 축이
  //   **엉뚱한 이유로 초록**이 된다(2026-09-05 자기적발 — 시험 3개가 그 상태였다).
  const ok = () => JSON.parse(JSON.stringify({
    ...GOLDEN.base_event,
    // 같은 이유로 prev·expected_state 도 골라 준다 — golden 은 genesis 계약값을 kind=post 에 달고 있다.
    prev: "a".repeat(64), expected_state: "b".repeat(64),
    scrub: { rules: "r".repeat(64), blocked: 0, redacted: 0 },
    payload: { round: 0, body: "본문" },
  }));

  it("정상 이벤트를 통과시킨다(= 뒤 축들이 재는 전제)", () => {
    expect(() => schema.validate(ok())).not.toThrow();
  });

  it("모르는 칸은 거부한다(10)", () => {
    const e = ok(); (e as any).extra = 1;
    expect(codeOf(() => schema.validate(e))).toBe(10);
  });

  it("권고에 집행 금지 표식이 없으면 정책 거부(3)", () => {
    const e = ok();
    e.kind = "resolution";
    e.prev = "a".repeat(64);
    e.expected_state = "b".repeat(64);
    e.payload = { summary: "요약", dissent: [], recommended_actions: [{ text: "하라" }] };
    expect(codeOf(() => schema.validate(e))).toBe(3);
    e.payload.recommended_actions[0].execution = "forbidden";
    expect(() => schema.validate(e)).not.toThrow();
  });

  it("봉투 결손은 정책 거부(3) · 봉투 안 타입 오류는 모양 오류(10)", () => {
    const e = ok();
    e.kind = "genesis";
    e.prev = "genesis"; e.expected_state = "";
    e.payload = { type: "problem", title: "t", body: "b",
      envelope: { env: { os: "mac", app: "a" }, symptom: "s", repro_steps: [] } };
    expect(codeOf(() => schema.validate(e))).toBe(3);
    e.payload.envelope.repro_steps = [1];
    expect(codeOf(() => schema.validate(e))).toBe(10);
  });

  it("bool 은 int 로 세지 않는다(파이썬과 같은 경계)", () => {
    const e = ok();
    (e.payload as any).round = true;
    expect(codeOf(() => schema.validate(e))).toBe(10);
  });
});

// ── 사슬·전이(암호 없이 순수 구조로 잰다) ──────────────────────────────────
function entry(o: Partial<ValidEntry> & { node_id: string; hash: string; prev: string; kind: string; from: string; }): ValidEntry {
  return {
    created_at: "2026-09-06T00:00:00.000Z", message_id: "m".repeat(32),
    canonical: "", fingerprint: null, roster_stale: false, scrub_recheck: false,
    event: { kind: o.kind, from: o.from, payload: {}, expected_state: "" },
    ...o,
  } as ValidEntry;
}

describe("reducer 2단 — 경합은 격리가 아니라 stale 이다", () => {
  it("같은 prev 후보 중 (created_at, node_id) 최소가 이기고 진 쪽은 stale", () => {
    const g = entry({ node_id: "ev_0000000000000001", hash: "h1", prev: "genesis",
      kind: "genesis", from: "a" });
    const w = entry({ node_id: "ev_0000000000000002", hash: "h2", prev: "h1",
      kind: "post", from: "b", created_at: "2026-09-06T00:00:01.000Z" });
    const l = entry({ node_id: "ev_0000000000000003", hash: "h3", prev: "h1",
      kind: "post", from: "c", created_at: "2026-09-06T00:00:02.000Z" });
    const r = order({ thread_id: "t", fetched: 3, valid: [g, w, l], quarantined: [] });
    expect(r.chain.map(x => x.node_id)).toEqual(["ev_0000000000000001", "ev_0000000000000002"]);
    expect(r.stale.map(x => x.reason)).toEqual(["lost_race"]);
  });

  it("동률이면 node_id 사전순이 가른다 — 고정폭이 아니면 뒤집힌다", () => {
    const g = entry({ node_id: "ev_0000000000000001", hash: "h1", prev: "genesis",
      kind: "genesis", from: "a" });
    const same = "2026-09-06T00:00:01.000Z";
    const a = entry({ node_id: "ev_0000000000000002", hash: "h2", prev: "h1", kind: "post", from: "b", created_at: same });
    const b = entry({ node_id: "ev_0000000000000010", hash: "h3", prev: "h1", kind: "post", from: "c", created_at: same });
    const r = order({ thread_id: "t", fetched: 3, valid: [g, b, a], quarantined: [] });
    expect(r.chain[1].node_id).toBe("ev_0000000000000002");
    // 음성 대조: 고정폭을 안 쓰면(2 vs 10) 사전순이 "10" 을 먼저 놓는다.
    expect(["ev_2", "ev_10"].sort()[0]).toBe("ev_10");
  });
});

describe("reducer 3단 — 전이·권한·CAS", () => {
  async function chainOf(kinds: Array<{ kind: string; from: string; payload?: any }>) {
    const entries: ValidEntry[] = [];
    const state: Record<string, any> = {};
    let prev = "genesis";
    let i = 0;
    for (const k of kinds) {
      i++;
      const hash = "h" + i;
      const e = entry({
        node_id: "ev_" + String(i).padStart(16, "0"), hash, prev, kind: k.kind, from: k.from,
        created_at: "2026-09-06T00:00:" + String(i).padStart(2, "0") + ".000Z",
        message_id: String(i).padStart(32, "0"),
      });
      e.event = { kind: k.kind, from: k.from, payload: k.payload ?? {}, expected_state: "" };
      entries.push(e);
      prev = hash;
    }
    void state;
    return entries;
  }

  it("CAS 가 안 맞으면 stale_expected_state 로 격리되고 head 는 전진한다", async () => {
    const es = await chainOf([
      { kind: "genesis", from: "a", payload: { type: "problem", title: "t", body: "b" } },
      { kind: "post", from: "b", payload: { round: 0, body: "x" } },
    ]);
    const r = await apply({ thread_id: "t", chain: es, stale: [], quarantined: [] });
    expect(r.quarantined.map(q => q.reason)).toEqual(["stale_expected_state"]);
    // ★거부돼도 사슬 머리는 전진한다(L-1 교착 봉합) — 안 그러면 다음 사람이 영원히 진다.
    expect(r.head).toBe("h2");
  });

  it("올바른 expected_state 면 받아들이고, 제3자 answer_selected 는 권한으로 막힌다", async () => {
    const es = await chainOf([
      { kind: "genesis", from: "a", payload: { type: "problem", title: "t", body: "b" } },
      { kind: "post", from: "b", payload: { round: 0, body: "x" } },
      { kind: "answer_selected", from: "c", payload: { post_message_id: "2".padStart(32, "0") } },
    ]);
    // 각 이벤트의 expected_state 를 그 시점 상태로 채운다.
    const s0: Record<string, any> = { type: "problem", state: "open", round: null, chair: "a",
      requester: "a", solved_by: null, close_reason: null, head: "h1" };
    es[1].event.expected_state = await stateHash(s0);
    const s1 = { ...s0, head: "h2" };
    es[2].event.expected_state = await stateHash(s1);
    const r = await apply({ thread_id: "t", chain: es, stale: [], quarantined: [] });
    expect(r.events.length).toBe(2);                 // genesis + post
    expect(r.quarantined.map(q => q.reason)).toEqual(["permission"]);
    expect(r.state).toBe("open");
  });
});

describe("roster — 체크포인트 산식", () => {
  it("파일 경계를 해시에 넣는다(경계를 빼면 옮겨도 같은 값이 된다)", async () => {
    const a = await checkpointOf("AB", "", "");
    const b = await checkpointOf("A", "B", "");
    expect(a).not.toBe(b);
  });
});

describe("scrub — 백스톱이 실제로 잡는가", () => {
  const rules = readFileSync(REPO + "config/scrub-rules-v1.json", "utf8");
  const allow = readFileSync(REPO + "config/allowlist-v1.json", "utf8");
  const domains = readFileSync(REPO + "config/allow-domains.txt", "utf8");

  it("이메일·전화 형태를 잡고 정상문은 통과시킨다", async () => {
    const b = await loadBundle(rules, allow, domains);
    expect(scrubCheck({ body: "연락은 someone@example.com" }, b).blocked).toBeGreaterThan(0);
    expect(scrubCheck({ body: "010-1234-5678 로 연락" }, b).blocked).toBeGreaterThan(0);
    expect(scrubCheck({ body: "평범한 한국어 문장이다" }, b).blocked).toBe(0);
  });

  it("허용 밖 도메인 URL 을 잡는다(허용 목록은 통과)", async () => {
    const b = await loadBundle(rules, allow, domains);
    expect(scrubCheck({ body: "https://evil.example/x" }, b).blocked).toBeGreaterThan(0);
    expect(scrubCheck({ body: "https://github.com/x" }, b).blocked).toBe(0);
  });

  it("규칙이 깨지면 전량 차단(fail-closed)", async () => {
    await expect(loadBundle("{", allow, domains)).rejects.toBeInstanceOf(AgoraError);
    await expect(loadBundle(JSON.stringify({ version: "v", rules: [] }), allow, domains))
      .rejects.toBeInstanceOf(AgoraError);
  });

  it("서버는 이름 목록을 갖지 않는다(0 이 정상이고 그 사실이 드러난다)", async () => {
    const b = await loadBundle(rules, allow, domains);
    expect(scrubCheck({ body: "x" }, b).names_loaded).toBe(0);
  });
});

// ── 속도 제한 경계값 ────────────────────────────────────────────────────────
/** 최소 가짜 D1 — `bumpRate` 가 쓰는 두 질의만 흉내 낸다(계수 논리만 잰다). */
function fakeD1() {
  const rows = new Map<string, number>();
  return {
    rows,
    prepare(sql: string) {
      return {
        _binds: [] as unknown[],
        bind(...a: unknown[]) { this._binds = a; return this; },
        async run() { return { success: true }; },
        async first<T>() {
          const k = `${this._binds[0]}|${this._binds[1]}`;
          // 실물과 같게: 증가와 읽기가 **한 문장**이다(INSERT … RETURNING count).
          if (sql.includes("INSERT INTO rate_windows")) rows.set(k, (rows.get(k) ?? 0) + 1);
          return { count: rows.get(k) ?? 0 } as T;
        },
      };
    },
  } as unknown as D1Database;
}

describe("속도 제한 — 경계에서 하나 틀리지 않는가", () => {
  it("상한까지는 통과하고 상한+1 에서 막힌다", async () => {
    const db = fakeD1();
    const at = 1_700_000_000_000;
    const verdicts: boolean[] = [];
    for (let i = 0; i < 4; i++) {
      verdicts.push((await bumpRate(db, "pid:x", 60, 3, at)).ok);
    }
    expect(verdicts).toEqual([true, true, true, false]);   // 3 까지 통과 · 4번째 차단
  });

  it("창이 바뀌면 다시 센다(고정창)", async () => {
    const db = fakeD1();
    const at = 1_700_000_000_000;
    for (let i = 0; i < 3; i++) await bumpRate(db, "pid:y", 60, 3, at);
    expect((await bumpRate(db, "pid:y", 60, 3, at)).ok).toBe(false);
    const next = at + 60_000;
    expect((await bumpRate(db, "pid:y", 60, 3, next)).ok).toBe(true);
  });

  it("Retry-After 는 창의 남은 시간이고 최소 1초다", async () => {
    const db = fakeD1();
    const at = 1_700_000_000_000 + 59_000;   // 창 끝자락
    const r = await bumpRate(db, "pid:z", 60, 1, at);
    expect(r.retryAfter).toBeGreaterThanOrEqual(1);
    expect(r.retryAfter).toBeLessThanOrEqual(60);
  });
});

describe("식별자 — 정렬이 곧 계약이다", () => {
  it("event_id 는 고정폭이라 문자열 정렬 = 도착 순서", () => {
    const ids = [2, 10, 1].map(eventIdOf).sort();
    expect(ids).toEqual([eventIdOf(1), eventIdOf(2), eventIdOf(10)]);
  });

  it("created_at 은 밀리초 고정폭 ISO 다", () => {
    expect(nowIso(new Date(0))).toBe("1970-01-01T00:00:00.000Z");
    expect(nowIso()).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  });
});
