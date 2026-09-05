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

const SETTLED = `(() => {
  if (document.readyState !== 'complete') return false;
  if ([...document.images].some(i => !i.complete)) return false;
  if (document.querySelector('[aria-busy="true"]')) return false;
  const loading = [...document.querySelectorAll('.note')].some(n => n.textContent.includes('불러오는 중'));
  return !loading;
})()`;

const page = await targets();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));

await rpc(ws, 'Page.enable');
await rpc(ws, 'Runtime.enable');
await rpc(ws, 'Emulation.setDeviceMetricsOverride',
  { width, height: 900, deviceScaleFactor: 1, mobile: width < 600 });
await rpc(ws, 'Page.navigate', { url: baseUrl + path_ });

// ★상태로 기다린다 — 고정 시간이 아니라(미도착 화면을 찍고 「결함」이라 보고하지 않기 위해).
let settled = false;
for (let i = 0; i < 100; i += 1) {
  await sleep(100);
  const r = await rpc(ws, 'Runtime.evaluate', { expression: SETTLED, returnByValue: true });
  if (r.result.value === true) { settled = true; break; }
}
const measured = await rpc(ws, 'Runtime.evaluate', { expression: MEASURE, returnByValue: true, awaitPromise: false });
const out = { url: baseUrl + path_, width, settled, ...measured.result.value };

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
