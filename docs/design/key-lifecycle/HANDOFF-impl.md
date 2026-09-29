# HANDOFF-impl — TICKET=agora-admission-block-0929 인계

worker-agoraimpl@surface:1155 · 작업트리 `~/axdev/.wt/agora-admission`(갈래 `feat/admission-block-0929` · 기반 `agora/v2-mvp` 53b21a8 + 설계 3커밋) · 갱신 2026-09-29 21:4x
todo 정본 = `cys todo-path`(`~/.cys/pack/round/WORKER_AGORAIMPL_TODO.md`)

## 끝난 것
| 항목 | 커밋 | 증거 |
|---|---|---|
| 탐지기 1단계 `tools/detect_ours.py` + 시험 20 | e8cc442 · 32f0430 | 20/20 · 표적 변이 7(탐지 4 + 알림 3) 전부 적색 · 라이브 OK match=4 |
| 시험 릴레이 공개 주소 끔(workers_dev·preview_urls false) | 0af110e · 7b5c43f | master 승인 nonce 6ec26264 · 배포 17ba9537 「No targets」 · /health 404 1042 · ops 기록 off |
| launchd 탐지 작업 2개 설치 | 22eec7a | 승인 nonce f72d5e0a · bootstrap rc 0·0 · 첫 실행 exit 0 OK |
| 마이그레이션 0002(표 1 + 트리거 4) + run-local 편입 + DB 층 시험 6 | c408911 | 로컬 apply → sqlite_master 5개 · SQL 변이 3 적색 |
| 앱 층(/events·/register·/checkpoint·/home) | aa04ef6 | tsc 0 · vitest 39 · 3자 대조 PASS |
| 차단 스크립트 `ops/admission-block.py` + 하네스 `relay/scripts/{admission,run-admission}.py` | ef25aac · 3da596a · 2aaedbe | main 54/54 · 누수 변이 3(T8) 적색 · 옛 코드(T6⑷·T15) 6/6 · 경합(T12) 8/8 · 앱 변이 8 중 7 적색 + A8 등가 변이 |
| 원격 원고·계약 초안 | fb8b9e0 | RUNBOOK-admission.md · DRAFT-contract-admission.md |
| 성찰 1단계분 | efd6e93 | REFLECTION-impl-s1.md |

## 미완(다음 사람이 이어서)
1. 적대 검증 r1(agy BLOCK·Fable REVISE)·r2(agy BLOCK·Fable REVISE) 처분 반영 완료 — `DISPOSITION-impl-r1.md`·`-r2.md` · 원문 `REVIEW-impl-*`.
2. codex 최종 코드 1라운드 — **호출 직전 master 인박스 「【순서 요청】 codex 1회」 → 답 받고** `codex exec … </dev/null`(스크래치 detached 스냅숏 · 프롬프트 초안 = 스크래치 `review-prompt-codex.md` · 한도 문구 실패면 재시도 금지·보고).
3. 【확인요청】(머리 3줄 = 성찰·검증·디버깅) → 승인 뒤 3단계 RUNBOOK 3-0b~3-8(단계마다 【실행직전확인요청】 · 3-7b 는 master 선택).
4. 4단계 = 원고만(RUNBOOK §4) — 본 릴레이 적용·배포는 master 판단.

## 함정
- ⚠launchd 탐지 작업이 **이 작업트리의 파일을 직접** 돈다 — `tools/detect_ours.py` 표적 변이는 제자리 수정 금지(사본에서). 갈래 병합·작업트리 삭제 시 경로 옮겨 재설치(master TODO).
- ⚠`ops/trial-relay-state.jsonl` 은 append 전용 · `relay/wrangler.next.jsonc` 의 workers_dev 와 어긋나면 탐지기 「불완전」 — 3단계에서 켜고 끌 때 둘을 함께.
- ⚠로컬 시험은 `relay/.wrangler/state` 한 폴더를 공유 — run-admission 과 run-local 을 **동시에 돌리지 말 것**(같은 포트 8797/8787 은 달라도 D1 파일 공유).
- ⚠워커는 master 표식 모양(대괄호+master#)을 어디에도 쓰지 않는다 — 승인 인용은 「nonce xxxxxxxx」 로.
- A8(등록 앱 검사에서 지문 조건 제거) = 트리거가 같은 403 을 내 바깥에서 구별 불가한 **등가 변이** — 결함 아님.
- T14 = SQL 층 + 서버 층(run-admission `--only upgrade` · 옛 코드+0001+데이터 → 0002 → 새 코드 · 13방 불변).
- 운영 스크립트 종료 코드: 0 성공 · 10 계획만 · 3 중단 · 4 대조 불일치 · 5 대조 미완 · 6 쓰기 결과 불명.
- 탐지기 꺼짐 확인 = 404 + 1042(글 또는 JSON) 만 — Cloudflare 가 Accept 에 따라 모양을 바꾼다(실측).

## 재현
```sh
cd ~/axdev/.wt/agora-admission
python3 tests/test_detect_ours.py && python3 tests/test_admission_sql.py
(cd relay && unset NODE_OPTIONS && npx tsc --noEmit && npx vitest run)
python3 relay/scripts/run-local.py                       # 3자 대조(회귀)
python3 relay/scripts/run-admission.py --workdir <스크래치>   # main·변이 3·old·race
python3 relay/scripts/run-admission.py --workdir <스크래치> --app-mutation "A1 /events 앱 검사 제거(속도 예산 소모)"
```
