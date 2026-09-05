// Accept 헤더로 「사람의 브라우저」와 「JSON 클라이언트」를 가른다.
//
// ★왜 있는가: 계약 §3-2 의 `url` 이 `/rooms/<id>#<mid>` 인데 그 주소는 JSON 을 돌려준다.
//   사람이 그 링크를 누르면 화면이 아니라 원문이 뜬다(master 판정 2026-09-05 · 후속 티켓).
// ★기본값은 JSON 이다: Accept 가 없거나 `*/*` 뿐이면(curl·스크립트) 그대로 200 이다.
//   `*/*` 를 html 로 세면 **모든 스크립트가 302 로 튄다** — 계약이 조용히 바뀐다.
//   보드의 `api.js` 도 `accept: application/json` 을 명시하므로 되돌이(loop)가 생기지 않는다.
export function prefersHtml(accept: string | null | undefined): boolean {
  if (!accept) return false;
  let html = 0;
  let jsonQ = 0;
  for (const part of accept.split(",")) {
    const [typeRaw, ...params] = part.split(";");
    const type = typeRaw.trim().toLowerCase();
    let q = 1;
    for (const p of params) {
      const m = /^\s*q=([0-9.]+)\s*$/i.exec(p);
      if (m) q = Number(m[1]);
    }
    if (!Number.isFinite(q)) q = 0;
    if (type === "text/html") html = Math.max(html, q);
    else if (type === "application/json") jsonQ = Math.max(jsonQ, q);
  }
  // 동률이면 html 쪽이다 — 브라우저는 둘을 같이 보내는 일이 없고, 같이 보낸다면 화면을 원한 것이다.
  return html > 0 && html >= jsonQ;
}
