// py↔ts 대조 탐침 — **같은 사슬을 두 구현에 먹이고 `head`·`state_hash` 를 맞춰 본다.**
//
// ★왜 필요한가(2026-09-11): `vote` 분기의 head 전진을 **두 구현에서 같은 커밋에** 고쳤다.
//   한쪽만 고치면 상태 해시가 갈라져 3자 대조(클라·릴레이·보드)가 그 자리에서 깨진다
//   (그 경고는 reducer.ts 주석에 2026-09-05 부터 적혀 있었다). 그래서 **기계가 맞춰 본다.**
//
// 쓰기: 표준입력으로 {"entries": [...]} 를 주면 {"head":…, "state_hash":…, "accepted":…} 를 낸다.
//   entries = 파이썬 리듀서가 쓰는 것과 **같은 모양**(node_id·hash·prev·kind·from·created_at·event).
import { build } from "esbuild";
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const raw = readFileSync(0, "utf8");
const input = JSON.parse(raw);
const out = join(tmpdir(), `agora-reducer-${process.pid}.mjs`);
await build({ entryPoints: [new URL("../src/lib/reducer.ts", import.meta.url).pathname],
              bundle: true, format: "esm", platform: "node", outfile: out, logLevel: "silent" });
const { order, apply } = await import(pathToFileURL(out).href);

const ordered = order({ thread_id: input.thread_id ?? "t",
                        fetched: input.entries.length, valid: input.entries, quarantined: [] });
const result = await apply(ordered, {});
process.stdout.write(JSON.stringify({
  head: result.head ?? result.state?.head ?? null,
  state_hash: result.state_hash ?? null,
  accepted: (result.events ?? []).map(e => e.node_id),
  stale: (result.stale ?? []).map(s => s.reason),
  quarantined: (result.quarantined ?? []).map(q => q.reason),
}) + "\n");
