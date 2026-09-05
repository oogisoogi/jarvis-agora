/**
 * 스크럽 백스톱 — 파이썬 `agora/scrub.py` 의 규칙을 같은 파일에서 읽어 재현한다.
 *
 * ★**fail-closed 가 이 모듈의 유일한 기본값이다.** 규칙이 없거나 깨졌으면
 *   「검사할 수 없으니 통과」가 아니라 **전량 차단**이다. 검사하지 못한 것을 통과시키면
 *   게이트가 있는 것보다 나쁘다 — 있다고 믿게 만들기 때문이다.
 *
 * ★서버는 **이름 목록(scrub-names.txt)을 갖지 않는다.** 그것은 참가자 로컬이고,
 *   서버가 가지면 「무엇을 가리려 하는지」가 한 곳에 모인다.
 *   ⇒ 서버 스크럽은 클라이언트 게이트의 **대체가 아니라 백스톱**이다(docs/RELAY.md §6).
 *
 * ★파이썬 정규식을 그대로 못 쓴다: `(?i)` 인라인 플래그는 JS 에서 **문법 오류**다.
 *   그래서 접두 플래그를 떼어 JS 플래그로 옮긴다. 옮기지 못하는 패턴이 하나라도 있으면
 *   **전량 차단**한다(조용히 빼면 그 규칙만 꺼진 채 초록이 된다).
 */
import { GATE_REJECT, fail } from "./errors.ts";
import { hex } from "./canonical.ts";

const enc = new TextEncoder();

export interface Finding { rule: string; kind: string; where: string; span?: [number, number]; len?: number; max?: number; bytes?: number; }

interface CompiledRule { id: string; kind: string; re: RegExp; }

export interface ScrubBundle {
  rulesDigest: string; rulesVersion: string;
  allowDigest: string; allowVersion: string;
  bundle: string;
  rules: CompiledRule[];
  forbidden: CompiledRule[];
  fields: Record<string, { max_chars?: number; max_bytes?: number }>;
  defaultSpec: { max_chars?: number; max_bytes?: number };
  domains: Set<string>;
}

/** `(?i)` 같은 파이썬 인라인 플래그를 JS 플래그로 옮긴다. 못 옮기면 던진다(전량 차단). */
function compilePattern(id: string, pattern: string): RegExp {
  let flags = "";
  let src = pattern;
  const m = /^\(\?([aiLmsux]+)\)/.exec(src);
  if (m) {
    for (const f of m[1]) {
      if (f === "i") flags += "i";
      else if (f === "s") flags += "s";
      else if (f === "m") flags += "m";
      else throw new Error(`규칙 ${id}: 옮길 수 없는 인라인 플래그 ${f}`);
    }
    src = src.slice(m[0].length);
  }
  if (/\(\?[aiLmsux]+\)/.test(src)) {
    throw new Error(`규칙 ${id}: 중간 인라인 플래그는 옮길 수 없다`);
  }
  return new RegExp(src, flags);
}

async function sha256HexOf(data: Uint8Array): Promise<string> {
  return hex(new Uint8Array(await crypto.subtle.digest("SHA-256", data as BufferSource)));
}

/**
 * 규칙 3파일의 **원문 텍스트**를 받아 묶음을 만든다.
 * ★원문을 받는 이유: digest 는 파일 바이트의 해시이고, 그 값이 곧 수신 측 대조 기준이다.
 *   JSON 으로 파싱한 뒤 다시 만들면 바이트가 달라져 파이썬 쪽과 갈린다.
 */
export async function loadBundle(rulesText: string, allowText: string,
                                 domainsText: string): Promise<ScrubBundle> {
  const rulesDigest = await sha256HexOf(enc.encode(rulesText));
  const domains = new Set<string>();
  for (const line of domainsText.split("\n")) {
    const t = line.trim();
    if (t && !t.startsWith("#")) domains.add(t.toLowerCase());
  }
  // 파이썬: sha256(raw + b"\n" + "\n".join(sorted(domains)))
  const allowDigest = await sha256HexOf(
    enc.encode(allowText + "\n" + [...domains].sort().join("\n")));

  let rules: CompiledRule[], forbidden: CompiledRule[];
  let rulesVersion: string, allowVersion: string;
  let fields: Record<string, any>, defaultSpec: Record<string, any>;
  try {
    const rdoc = JSON.parse(rulesText);
    const adoc = JSON.parse(allowText);
    rules = rdoc.rules.map((r: any) => ({ id: r.id, kind: r.kind, re: compilePattern(r.id, r.pattern) }));
    forbidden = adoc.forbidden.map((r: any) => ({ id: r.id, kind: r.kind, re: compilePattern(r.id, r.pattern) }));
    rulesVersion = rdoc.version;
    allowVersion = adoc.version;
    fields = adoc.fields;
    defaultSpec = adoc.default;
  } catch (e) {
    fail(GATE_REJECT, "스크럽 규칙이 깨졌다 — 전량 차단(fail-closed)", { error: String(e).slice(0, 160) });
  }
  if (!rules!.length) fail(GATE_REJECT, "규칙이 0개다 — 검사가 무의미하므로 전량 차단", { digest: rulesDigest });
  if (!forbidden!.length) fail(GATE_REJECT, "금칙 구조가 0개다 — 전량 차단", { digest: allowDigest });

  const bundle = await sha256HexOf(enc.encode(rulesDigest + allowDigest));
  return {
    rulesDigest, rulesVersion: rulesVersion!, allowDigest, allowVersion: allowVersion!,
    bundle, rules: rules!, forbidden: forbidden!, fields: fields!, defaultSpec: defaultSpec!, domains,
  };
}

function* walkStrings(node: unknown, path = "$"): Generator<[string, string]> {
  if (typeof node === "string") { yield [path, node]; return; }
  if (Array.isArray(node)) {
    for (let i = 0; i < node.length; i++) yield* walkStrings(node[i], `${path}[${i}]`);
    return;
  }
  if (node && typeof node === "object") {
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      yield* walkStrings(v, `${path}.${k}`);
    }
  }
}

const fieldKey = (path: string) => path.replace(/\[[0-9]+\]/g, "").replace(/^\$\./, "");

const URL_RE = /\bhttps?:\/\/([^\s/?#\\)\]>'"]+)/gi;

function hostAllowed(host: string, domains: Set<string>): boolean {
  const h = host.toLowerCase().split("@").pop()!.split(":")[0];
  if (domains.has(h)) return true;
  for (const d of domains) {
    if (d.startsWith(".") && (h.endsWith(d) || h === d.slice(1))) return true;
  }
  return false;
}

/** 구조 전체의 문자열을 훑어 차단 사유를 모은다. 반환은 **보고서**이지 집행이 아니다. */
export function check(payload: unknown, b: ScrubBundle) {
  const findings: Finding[] = [];
  for (const [where, text] of walkStrings(payload)) {
    const key = fieldKey(where);
    const spec = b.fields[key] ?? b.defaultSpec;
    if (spec?.max_chars != null && Array.from(text).length > spec.max_chars) {
      findings.push({ rule: "max_chars", kind: "길이 상한", where, len: Array.from(text).length, max: spec.max_chars });
    }
    if (spec?.max_bytes != null) {
      const size = enc.encode(text).length;
      if (size > spec.max_bytes) {
        findings.push({ rule: "max_bytes", kind: "바이트 상한", where, bytes: size, max: spec.max_bytes });
      }
    }
    for (const f of b.forbidden) {
      f.re.lastIndex = 0;
      const m = f.re.exec(text);
      // ★적발된 값 자체는 담지 않는다 — 보고서가 유출 경로가 되면 안 된다.
      if (m) findings.push({ rule: f.id, kind: f.kind, where, span: [m.index, m.index + m[0].length] });
    }
    URL_RE.lastIndex = 0;
    let um: RegExpExecArray | null;
    while ((um = URL_RE.exec(text)) !== null) {
      if (!hostAllowed(um[1], b.domains)) {
        findings.push({ rule: "url-domain", kind: "허용 밖 도메인", where, span: [um.index, um.index + um[0].length] });
      }
    }
    for (const r of b.rules) {
      r.re.lastIndex = 0;
      const m = r.re.exec(text);
      if (m) findings.push({ rule: r.id, kind: r.kind, where, span: [m.index, m.index + m[0].length] });
    }
  }
  return {
    rules: b.rulesDigest, rules_version: b.rulesVersion,
    allow_rules: b.allowDigest, allow_version: b.allowVersion,
    bundle: b.bundle,
    names_loaded: 0,   // ★서버는 이름 목록을 갖지 않는다(0 이 정상이고, 그 사실을 드러낸다).
    blocked: findings.length, redacted: 0, findings,
  };
}

/** 차단이 1건이라도 있으면 code 3 으로 멈춘다. */
export function enforce(payload: unknown, b: ScrubBundle) {
  const report = check(payload, b);
  if (report.blocked) {
    fail(GATE_REJECT, "스크럽 게이트 차단", {
      blocked: report.blocked,
      rules: report.findings.map(f => f.rule),
      where: report.findings.map(f => f.where),
    });
  }
  return report;
}
