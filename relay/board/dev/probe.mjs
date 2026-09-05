// probe.mjs — 헤드리스 크롬으로 **실제 렌더**를 재는 계기. 값을 손으로 옮겨 적지 않기 위한 도구.
//
// ★왜 CDP 인가: macOS 헤드리스 크롬은 창을 500px 아래로 못 줄인다(실측 기지).
//   Emulation.setDeviceMetricsOverride 는 그 하한을 지나가므로 390 을 **진짜 390 으로** 잰다.
// ★정착 대기는 시간이 아니라 **상태**로 잰다(진행 중인 fetch 0 · 이미지 complete · 대기 표시 없음).
//
// 쓰는 법: node relay/board/dev/probe.mjs <base-url> <path> <width> <out.png>

import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const [baseUrl, path_, widthArg, outPng] = process.argv.slice(2);
const width = Number(widthArg || 1440);

const port = 9222 + (process.pid % 500);
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${port}`, '--no-first-run', '--no-default-browser-check',
  '--disable-gpu', '--hide-scrollbars=false', '--user-data-dir=/tmp/board-probe-' + process.pid,
  'about:blank',
], { stdio: 'ignore' });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function targets() {
  for (let i = 0; i < 60; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/list`);
      const list = await res.json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page;
    } catch { /* 아직 안 떴다 */ }
    await sleep(200);
  }
  throw new Error('크롬 디버깅 포트에 못 붙었다');
}

let id = 0;
function rpc(ws, method, params = {}) {
  const mine = ++id;
  return new Promise((resolve, reject) => {
    const onMsg = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id !== mine) return;
      ws.removeEventListener('message', onMsg);
      if (msg.error) reject(new Error(`${method}: ${msg.error.message}`));
      else resolve(msg.result);
    };
    ws.addEventListener('message', onMsg);
    ws.send(JSON.stringify({ id: mine, method, params }));
  });
}

const MEASURE = `(() => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && (el.textContent || '').trim() !== '';
  };
  const nodes = [...document.body.querySelectorAll('*')].filter(vis);
  let minFont = Infinity, minSel = null;
  for (const el of nodes) {
    if ([...el.children].some(c => (c.textContent||'').trim() === (el.textContent||'').trim())) continue;
    const px = parseFloat(getComputedStyle(el).fontSize);
    if (px < minFont) { minFont = px; minSel = el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ').join('.') : ''); }
  }
  const lum = (c) => { const f = (v) => { v/=255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
    const m = c.match(/\\d+/g).map(Number); return 0.2126*f(m[0]) + 0.7152*f(m[1]) + 0.0722*f(m[2]); };
  const bgOf = (el) => { let n = el; while (n) { const b = getComputedStyle(n).backgroundColor;
    if (b && !/rgba\\(0, 0, 0, 0\\)|transparent/.test(b)) return b; n = n.parentElement; } return 'rgb(255,255,255)'; };
  let worst = null;
  for (const el of nodes) {
    if ([...el.children].some(c => (c.textContent||'').trim() === (el.textContent||'').trim())) continue;
    const s = getComputedStyle(el);
    const r = (Math.max(lum(s.color), lum(bgOf(el))) + 0.05) / (Math.min(lum(s.color), lum(bgOf(el))) + 0.05);
    if (!worst || r < worst.ratio) worst = { ratio: Number(r.toFixed(2)), sel: el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ').join('.') : ''), color: s.color, bg: bgOf(el), text: (el.textContent||'').trim().slice(0, 30) };
  }
  return {
    title: document.title,
    minFontPx: minFont === Infinity ? null : Number(minFont.toFixed(2)),
    minFontSel: minSel,
    worstContrast: worst,
    overflowPx: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
    footerCount: [...document.querySelectorAll('.sitefoot p')].filter(p => p.textContent.includes('이 화면은 서버의 계산입니다')).length,
    badges: [...document.querySelectorAll('.badge')].map(b => b.textContent),
    verdictBadges: [...document.querySelectorAll('.speech .badge, .archive-resolution .badge')].map(b => b.textContent),
    chips: [...document.querySelectorAll('.chip')].map(b => b.textContent),
    notes: [...document.querySelectorAll('.note')].map(n => n.className + ' :: ' + n.textContent),
    fields: [...document.querySelectorAll('.field')].map(f => f.textContent.trim()),
    allText: document.body.innerText,
    links: [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href')),
    cards: document.querySelectorAll('.card').length,
    speeches: document.querySelectorAll('.speech').length,
    dividers: [...document.querySelectorAll('.divider-text')].map(d => d.textContent),
    folded: [...document.querySelectorAll('details.folded summary')].map(s => s.textContent),
    hasResolutionBox: !!document.querySelector('.resolution'),
    resolution: document.querySelector('.resolution-summary') ? document.querySelector('.resolution-summary').textContent : null,
    archiveResolutions: [...document.querySelectorAll('.archive-resolution')].map(n => n.textContent),
  };
})()`;

// ★정착 판정 = ⑴화면이 스스로 말하는 것(aria-busy · 「불러오는 중」)과
//              ⑵아무도 말해 주지 않을 때를 위한 **화면이 더 안 바뀐다**(지문 안정) 두 겹이다.
//   ⑵가 없으면, 자기 상태를 신고하지 않는 판본(예: 이미 배포된 옛 화면)에서 **도착 전 화면을 찍는다.**
//   실측 2026-09-06: 라이브(왕복 약 0.6초) 방 화면을 그렇게 찍어 「글이 없다」는 거짓 결과가 나왔다.
const DECLARED_SETTLED = `(() => {
  if (document.readyState !== 'complete') return false;
  if ([...document.images].some(i => !i.complete)) return false;
  if (document.querySelector('[aria-busy="true"]')) return false;
  const loading = [...document.querySelectorAll('.note')].some(n => n.textContent.includes('불러오는 중'));
  return !loading;
})()`;

const FINGERPRINT = `(() => document.body.querySelectorAll('*').length + ':' + document.body.innerText.length)()`;

const page = await targets();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));

await rpc(ws, 'Page.enable');
await rpc(ws, 'Runtime.enable');
// ★세 번째 겹 — **아직 답을 기다리는 요청이 있는가**.
//   「화면이 안 바뀐다」만으로는 「다 그렸다」와 「아직 안 왔다」가 구별되지 않는다(둘 다 조용하다).
await rpc(ws, 'Network.enable');
let inflight = 0;
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.method === 'Network.requestWillBeSent') inflight += 1;
  else if (m.method === 'Network.loadingFinished' || m.method === 'Network.loadingFailed') inflight -= 1;
});
await rpc(ws, 'Emulation.setDeviceMetricsOverride',
  { width, height: 900, deviceScaleFactor: 1, mobile: width < 600 });
await rpc(ws, 'Page.navigate', { url: baseUrl + path_ });

// ★상태로 기다린다 — 고정 시간이 아니라(미도착 화면을 찍고 「결함」이라 보고하지 않기 위해).
let settled = false;
let lastPrint = null;
let stable = 0;
// 조용해야 하는 시간: 기다리는 요청이 없으면 0.6초, 있으면 1.5초.
// ★진행 중 요청 수를 **차단 조건이 아니라 창의 길이**로 쓴다 — 캐시·리다이렉트로 이 계수가
//   0으로 안 돌아오는 요청이 실제로 있고(라이브 실측), 차단 조건으로 두면 계기가 영영 안 끝난다.
//   그래도 「아직 안 온 화면」은 창을 못 채운다(도착하면 화면이 바뀌어 창이 초기화된다).
for (let i = 0; i < 80; i += 1) {
  await sleep(150);
  const declared = await rpc(ws, 'Runtime.evaluate', { expression: DECLARED_SETTLED, returnByValue: true });
  const print = await rpc(ws, 'Runtime.evaluate', { expression: FINGERPRINT, returnByValue: true });
  const needed = inflight > 0 ? 10 : 4;
  stable = print.result.value === lastPrint ? stable + 1 : 0;
  lastPrint = print.result.value;
  if (declared.result.value === true && stable >= needed) { settled = true; break; }
}
const measured = await rpc(ws, 'Runtime.evaluate', { expression: MEASURE, returnByValue: true, awaitPromise: false });
const out = { url: baseUrl + path_, width, settled, inflightAtEnd: inflight, ...measured.result.value };

if (outPng) {
  const full = await rpc(ws, 'Page.getLayoutMetrics');
  const h = Math.min(6000, Math.ceil(full.cssContentSize.height));
  await rpc(ws, 'Emulation.setDeviceMetricsOverride', { width, height: h, deviceScaleFactor: 1, mobile: width < 600 });
  await sleep(150);
  const shot = await rpc(ws, 'Page.captureScreenshot', { format: 'png' });
  mkdirSync(dirname(outPng), { recursive: true });
  writeFileSync(outPng, Buffer.from(shot.data, 'base64'));
  out.screenshot = outPng;
  out.screenshotHeight = h;
}

console.log(JSON.stringify(out, null, 2));
ws.close();
chrome.kill('SIGTERM');
process.exit(0);
