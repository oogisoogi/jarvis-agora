// py↔ts 대조 탐침 — **피드 정렬·커뮤니티 판별**을 릴레이 이식(feed.ts)으로 계산해 낸다.
//
// ★정본은 tools/plaza.py 다. selftest 「광장: 피드 정렬 py↔ts 가 같다」가 같은 입력을 plaza.py 에도 먹이고
//   두 출력이 **바이트 단위로 같은 JSON** 인지 맞춰 본다(한쪽만 고치면 그 자리에서 적색).
//
// 쓰기: 표준입력 {"feed": [{"rooms": [[방, 이벤트들]…], "sort": "new|hot|top", "now": ISO}…],
//                  "community": [genesis payload…]}
//   → {"feed": [피드 결과…], "community": [bool…]}
import { build } from "esbuild";
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const input = JSON.parse(readFileSync(0, "utf8"));
const out = join(tmpdir(), `agora-feed-${process.pid}.mjs`);
await build({ entryPoints: [new URL("../src/lib/feed.ts", import.meta.url).pathname],
              bundle: true, format: "esm", platform: "node", outfile: out, logLevel: "silent" });
const { feed, isCommunity } = await import(pathToFileURL(out).href);

process.stdout.write(JSON.stringify({
  feed: (input.feed ?? []).map(c => feed(c.rooms, c.sort, Date.parse(c.now))),
  community: (input.community ?? []).map(g => isCommunity(g)),
}) + "\n");
