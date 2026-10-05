# HANDOFF-impl — TICKET=agora-admission-block-0929 인계

worker-agoraimpl@surface:1155 · 작업트리 `~/axdev/.wt/agora-admission`(갈래 `feat/admission-block-0929` · 기반 `agora/v2-mvp` 53b21a8 + 설계 3커밋) · 갱신 2026-09-29 21:5x · 후임 worker-agoraimpl@surface:1160 갱신 22:1x(Fable r4 · 3단계)
todo 정본 = 워커 todo 경로 도구가 내주는 파일(`WORKER_AGORAIMPL_TODO.md`)

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
| Fable 표적 r4(R1·R2 반영분) = **ACCEPT** · LOW 3 반영 | 이 갱신 커밋 | REVIEW-impl-fable-r4.md · DISPOSITION-impl-r4.md |
| **3단계(시험 릴레이 원격) 3-0b~3-8 전부 기대값 일치** | 0daeb18 · 이 갱신 커밋(운영 기록) | 아래 「3단계 실측」 |

## 3단계 실측(후임 worker-agoraimpl@surface:1160 · 2026-09-29 22:00~22:08 · master 묶음 d071dd16 ③ + 재개 판정 81c7a057)
| # | 결과 |
|---|---|
| 3-0b | migrations list = 0002 대기 · check-schema rc 3(없음 5) · 프롬프트 없음 |
| 3-0 | 백업 `~/.local/state/agora-detect/backup-next-20260929-220026.sql` 34,683 B · sha256 2613cb3a…c42b · 기준선 참가자 4 · 글 17 · 체크포인트 0 · 방 3 |
| 3-1·3-2 | 0002 ✅ · 표 1 + 트리거 4 · check-schema rc 0 |
| 3-3 | adm-t16-probe 차단 rc 0 → ②③④⑤ 직접 쓰기 전부 rc 1 · 원문 `agora:admission_blocked: SQLITE_CONSTRAINT (extended: SQLITE_CONSTRAINT_TRIGGER) [code: 7500]` · 보조 행 삭제 · 잔여 0 |
| 3-4 | 우리 id+지문 차단 rc 0(사전 id 0·지문 0 · 기존 행 그대로) |
| 3-5·3-6 | 1차 켬 Version 3fe136c6 → **3-7 첫 요청 403 으로 멈춤·끔**(4a1df331 · 켜진 창 22:02:02~46) → 원인 = 드라이버 UA 누락(Cloudflare 1010) → master 재개 판정 → 재켬 **1fc95b66** · /health 200 · 시험 /home 우리 id·지문 404 code 7 |
| 3-7 | UA 단 첫 요청 A 등록 201(가설 확정) · genesis·post 201 · A registered 차단 rc 0 · T4 401 code 4 why=retired · 원장 행 불변 · T5 재전송 200 같은 event_id · 같은 message_id 다른 내용 422 · T6⑴ 재등록 403 code 5 · B absent 차단 rc 0 · T18 B 키 다른 이름 403 code 5 · 행 0 = **8/8** |
| 3-7b | 경합 사본(RACE 4줄만 · 스크래치) 배포 **4e0e46f9** → A 새 글 401 why=retired · 원장 불변 · C 키로 adm-t18-b 403 retired · B 키로 adm-t18-x 403 retired · 행 수 불변 = **5/5**(원격 바인딩 오류 모양 = 표식 포함 확인) |
| 3-8 | 원래 코드 + workers_dev false **57134b71** · No targets · /health 404 1042(글·JSON 요청 모두 · 22:07:14 부터 5연속) · 미리보기(4e0e46f9·57134b71·1fc95b66) 404 1042 |
| 사후 D1 | 차단 행 4(adm-t16-probe · jarvis-jk1gn50iw7 · adm-t18-a · adm-t18-b) · 참가자 5(+adm-t18-a) · 글 19(+adm 2) · 체크포인트 0 · 방 4 · 우리 신원 참가자 행 0 · 마이그레이션 적용 대기 0 |

- 되돌리기: 코드 = 지금 배포(57134b71)가 정상 코드 · 경합 사본 흔적 없음. D1 = 0002 표·트리거·차단 행 4 는 남긴다(시험 릴레이 · 옛 코드와 무관) · 전체 되돌림이 필요하면 백업 SQL(위)로 새 D1 복원 — 권하지 않음.
- 드라이버 = 스크래치 `drive.py`(저장소 밖 · 키도 거기) · 저장소 코드 변경 0.

## 4단계 실측(본 릴레이 agora-relay · TICKET=agora-admission-stage4 · worker@surface:1264 · 2026-10-05 12:07~12:2x KST)
발주자 10-05 09:3x 「본 릴레이 적용」 승인 → master 판정 nonce f4683cd1(범위 = RUNBOOK §4 그대로 · **우리 id 차단 = 밖**(상주가 지금도 jarvis-jk1gn50iw7 로 가동 · §7 단계 7) · 본 릴레이 T16 탐침 = 하지 않음). 한 줄마다 master 【실행】: 4-0 9cffe972 · 4-1 6cab7f86 · 4-4 c60aa7ee.

| # | 결과 |
|---|---|
| 사전 읽기(09:11) | name agora-relay · database_id cbdfaaef 일치 · migrations list = 0002 대기 1 · check-schema rc 3(없음 5) · 배포 = f49eac74(09-19 이후 변화 없음) |
| 4-0 | 백업 `~/.local/state/agora-detect/backup-main-20261005-120735.sql` 64,185 B · sha256 67e2fd32…f233 · CREATE TABLE 6 · INSERT participants 13 = 원격 COUNT 13 · events 29 = 29 · 체크포인트 4 · 방 5 |
| 4-1·4-2 | 0002 ✅(12:08:22~24) · 재 list = 적용 대기 0 · check-schema rc 0 · 표 1 + 트리거 4 · 행 수 불변 · 차단 행 0 |
| 4-3 | 사전 사진 `~/.local/state/agora-detect/stage4-pre-20261005-120834/`(명부 3 · 체크포인트 · 방 439fc804·0b80c218 · /home 우리 id · /health) |
| 4-4 | check-schema rc 0 → name 게이트 → deploy rc 0(12:09:36~43) · **Version 4abb01b9-2eaa-4c04-ba6d-6d01effba024** · 「No updated asset files to upload」(자산 변경 0 · dry-run 의 「27 files」 = 파일 23 + 하위 폴더 4 로 보임) · 배포 후보 = f2f74c6(배포본 대비 relay 차이 3파일 = 0002 · index.ts · lib/admission.ts) · 사전 tsc 0 · vitest 39 |
| 4-5 | `stage4-post-20261005-120954/` · 명부 3·체크포인트·/home 우리 id·/health **바이트 동일** · 두 방 = state_hash 동일 · 바이트 차이는 `derived_at`(요청 시각) 한 칸뿐 · /home(지문) 200 notify [] · /rooms 200 · 탐지기 수동 scan OK match=4 rc 0(12:10:11) · 상주 배포 후 2회차 12:14:05·12:24:07 KST rc 0(launchd last exit 0 · runs 412) — ⚠두 회차 모두 due 0·woke 0(들를 방 없음) = 상주의 **쓰기 경로는 이번에 실행되지 않았다**(새 코드에서 우리 id 쓰기 실측 = 다음 실제 발언 때) |

- 되돌리기: 코드 = `wrangler rollback f49eac74-6ac6-4874-b614-f1dbdb7b6e31`(표·트리거는 남아도 옛 코드와 무관 · 차단 행 0 이라 롤백 버킷 위험 없음) · D1 전체 = 위 백업 SQL 로 새 D1 복원(권하지 않음).

## 미완(다음 사람이 이어서) — 갱신 2026-10-05
1. 4단계 = **끝**(위 표). 차단 스위치는 두 D1 모두 장전됐고 본 릴레이 차단 행 = 0.
2. 우리 id 차단 = §7 단계 7(새 id 전환 뒤 · 발주자 결정) — 두 D1 모두 끝나기 전 「차단 완료」 보고 금지(시험 D1 은 3단계에서 차단 행 있음).
3. 계약 문서 확정(§7 단계 5 · DRAFT-contract-admission.md) · 탐지기 2단계(§7 단계 6) = master.

## 함정
- ⚠launchd 탐지 작업이 **이 작업트리의 파일을 직접** 돈다 — `tools/detect_ours.py` 표적 변이는 제자리 수정 금지(사본에서). 갈래 병합·작업트리 삭제 시 경로 옮겨 재설치(master TODO).
- ⚠`ops/trial-relay-state.jsonl` 은 append 전용 · `relay/wrangler.next.jsonc` 의 workers_dev 와 어긋나면 탐지기 「불완전」 — 3단계에서 켜고 끌 때 둘을 함께.
- ⚠로컬 시험은 `relay/.wrangler/state` 한 폴더를 공유 — run-admission 과 run-local 을 **동시에 돌리지 말 것**(같은 포트 8797/8787 은 달라도 D1 파일 공유).
- ⚠워커는 master 표식 모양(대괄호+master#)을 어디에도 쓰지 않는다 — 승인 인용은 「nonce xxxxxxxx」 로.
- A8(등록 앱 검사에서 지문 조건 제거) = 트리거가 같은 403 을 내 바깥에서 구별 불가한 **등가 변이** — 결함 아님.
- T14 = SQL 층 + 서버 층(run-admission `--only upgrade` · 옛 코드+0001+데이터 → 0002 → 새 코드 · 13방 불변).
- 운영 스크립트 종료 코드: 0 성공 · 11 이미 차단(대조 없음) · 10 계획만 · 3 중단 · 4 대조 불일치 · 5 대조 미완(동시 등록 포함) · 6 쓰기 결과 불명.
- 차단 INSERT 는 원자적 조건부(`INSERT … SELECT … WHERE 모양 조건`) — 0행이면 중단.
- 탐지기 꺼짐 확인 = 404 + 1042(글 또는 JSON) 만 — Cloudflare 가 Accept 에 따라 모양을 바꾼다(실측).
- ⚠원격 HTTP 쓰기 드라이버는 **UA `agora-client/…` 필수** — `threeway.http()` 는 UA 를 안 달아 workers.dev 에서 Cloudflare 1010 403(본문 = JSON 아닌 글). 로컬 하네스는 Cloudflare 를 안 거쳐 안 드러난다(docs/TRANSPORT-RELAY.md:297 · 3단계 1차 멈춤 원인).
- ⚠끄는 배포(workers_dev false) 뒤 약 25초는 엣지마다 200·404 가 섞인다(22:06:38 배포 → 22:06:48 200 → 22:07:03 404 → 200 → 22:07:14 부터 안정). 이 창에 탐지기가 돌면 「기록 off 인데 응답」 경보가 날 수 있다 — 끔 확인은 연속 몇 회로.
- 3-7b 경합 사본은 `tsc` 에서 `existing possibly null` 3건이 나지만 wrangler 번들은 형 검사를 안 해 배포·동작에 무관(로컬 race 단계와 같은 코드).

## 재현
```sh
cd ~/axdev/.wt/agora-admission
python3 tests/test_detect_ours.py && python3 tests/test_admission_sql.py
(cd relay && unset NODE_OPTIONS && npx tsc --noEmit && npx vitest run)
python3 relay/scripts/run-local.py                       # 3자 대조(회귀)
python3 relay/scripts/run-admission.py --workdir <스크래치>   # main·변이 3·old·race
python3 relay/scripts/run-admission.py --workdir <스크래치> --app-mutation "A1 /events 앱 검사 제거(속도 예산 소모)"
```
