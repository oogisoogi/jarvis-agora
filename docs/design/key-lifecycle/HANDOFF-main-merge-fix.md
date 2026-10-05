# HANDOFF — TICKET=agora-admission-main-merge-fix 인계(종결)

worker@surface:1273 · 작업트리 `jarvis-agora/.wt/agora-main-merge`(갈래 `main-merge-1005`) · 2026-10-05 13:1x~13:5x

## 무슨 일이 있었나
- 가지 `feat/admission-block-0929`(54a54b0) 단독 = commit_gate PASS(517/517 · 542/542).
- main(5747a4f)과 `--no-ff` 병합(b3972a4) 뒤 같은 게이트 = **FAIL**(selftest 514/517 · 뮤테이션 533/542 · NOT-APPLIED 9).
- 발주자 쪽에서 main 을 revert(0946e7e)해 되돌림. 배포본은 가지 코드 그대로라 운영 영향 0.

## 원인(확정)
- 코드·문서가 아니라 **환경**: 병합 좌석(새 worktree)에 `relay/node_modules` 가 없었다(커밋 대상이 아니라 새 worktree 엔 원래 없다).
- `relay/tests/feed_probe.mjs`·`state_hash_probe.mjs` 가 `esbuild` 를 import 하지 못해(ERR_MODULE_NOT_FOUND) py↔ts 대조 케이스 3건이 「미측정 = 실패」:
  투표 py↔ts 해시 · 예산 py↔ts · 광장v2 피드 py↔ts.
- 그 3건을 killer 로 쓰는 뮤테이션 9건(M434 · M481 · M482 · M541~M546)이 「killer 가 변이 전부터 실패」로 NOT-APPLIED.
- 기각한 가설 2: ⑴5747a4f 문서가 문서-코드 계약 시험에 걸림 ⑵병합이 detect_ours/시험을 중복 포함 — 가지↔병합본 차이는 `docs/SPEC-v2-conformance-2026-09-23.md` 1개(25줄)뿐.

## 대조군(같은 트리, esbuild 유무만 다름)
| 트리 | esbuild | 게이트 |
|---|---|---|
| b3972a4 | 없음 | selftest 514/517 · 533/542 · NOT-APPLIED 9 (발주자 로그와 일치) |
| b3972a4(별도 worktree · `npm ci`) | 있음 | **PASS** 517/517 · 542/542 · NOT-APPLIED 0 · rc 0 |
| 0ca1c14 = revert 0946e7e 의 되돌림(트리 5eed640f = b3972a4) | 있음 | **PASS** · F-1 25/25 · codex 사후 11/11 · rc 0 |

## 처리
- 재병합 = revert-of-revert 1커밋 0ca1c14(부모 0946e7e · fast-forward). push 는 발주자가 집행(origin/main = 0ca1c14).
- ⚠**가지 쪽에서 main 을 merge 하지 말 것**: 54a54b0 는 이미 main 의 조상이라 main→가지 merge 는 revert 를 가지로 끌고 와 4단계 작업을 지운다. 가지→main 재merge 는 no-op.
- 재발 방지 1(코드): `tests/commit_gate.sh` 머리에 **환경 사전 점검** — git · python3 · node · gitleaks · `relay/node_modules/esbuild` 중 하나라도 없으면
  `ENV-MISSING: <항목> · <조치>` + **rc 2**(시험 실패 rc 1 과 구분)로 시험 0건 실행 상태에서 멈춘다.
  음성 실측: node_modules 이름 변경 → rc 2(0.02초) · gitleaks 뺀 PATH → rc 2 · 원복 뒤 전체 게이트 PASS.
- 재발 방지 2(문서): README 「새 worktree 게이트 전 `cd relay && npm ci`」 1줄.

## 교훈
- **미측정 ≠ 실패.** 못 잰 것을 통과로 세지 않는 규칙은 옳지만, 같은 칸(rc 1)에 넣으면 「코드가 틀렸다」로 읽혀 멀쩡한 병합이 되돌려진다.
- **환경 결손은 rc 로 가른다**: 시험 전에 따로 재고 다른 종료 코드를 낸다 — 읽는 사람이 로그를 열기 전에 종류가 갈린다.
- 게이트가 적색이면 같은 트리를 다른 환경에서 한 번 더 재는 대조군이 원인 분리의 가장 싼 길이다.
