# RUNBOOK-admission — 받아들이기 차단 원격 적용 명령 원고(3단계 시험 릴레이 · 4단계 본 릴레이)

TICKET=agora-admission-block-0929 · worker-agoraimpl@surface:1155 · 2026-09-29 · 설계 = DESIGN-v3 §5-3 · §7 단계 3·4 · §8 T16·T18
⚠**원고다.** 아래 한 줄 한 줄이 원격 쓰기·배포다 — 각 단계마다 워커가 【실행직전확인요청】 → master 재승인(그 1건만) → 실행 → 사후 실측 보고.
⚠wrangler 는 **`--config <절대경로>` 로만** 부른다(cwd 배포 금지) · 부르기 전 `name` 게이트 · `unset NODE_OPTIONS`.
공통: `R=/Users/oogisoogi/axdev/.wt/agora-admission` · `W="$R/relay/node_modules/.bin/wrangler"` · 우리 id = `jarvis-jk1gn50iw7` · 우리 지문 = `SHA256:u9ywSzKEEc1yMrrtWidT/p2UlZYdtkae9EAXCVyWHJI`(공개값 · /home 이 돌려준다).

## 0. 게이트(모든 원격 명령 앞)
```sh
unset NODE_OPTIONS
python3 -c 'import re,sys;print(re.findall(r"^\s*\"(name|database_id)\"\s*:\s*\"([^\"]+)\"",open(sys.argv[1]).read(),re.M))' "$R/relay/wrangler.next.jsonc"
#   → [('name','agora-relay-next'), ('database_id','4bfe34f0-6b43-4b14-b727-89019c94ceb4')] 여야 한다(본 = agora-relay · cbdfaaef-…)
```

## 3단계 — 시험 릴레이(agora-relay-next · 지금 공개 주소 꺼짐)

| # | 무엇 | 명령 | 사후 실측 · 합격 |
|---|---|---|---|
| 3-0 | (권고) 사전 백업 — 저장소 밖 | `$W d1 export agora-relay-next --remote --config "$R/relay/wrangler.next.jsonc" --output ~/.local/state/agora-detect/backup-next-<시각>.sql` | 파일 크기 > 0 · 표 5개 CREATE 포함 |
| 3-1 | 마이그레이션 0002 | `$W d1 migrations apply agora-relay-next --remote --config "$R/relay/wrangler.next.jsonc"` | 출력 표 `0002_admission_blocks.sql ✅` |
| 3-2 | 표 1·트리거 4 확인 | `$W d1 execute agora-relay-next --remote --config "$R/relay/wrangler.next.jsonc" --json --command "SELECT type, name FROM sqlite_master WHERE name LIKE '%admission%' ORDER BY type, name"` | table 1 + trigger 4(`checkpoints_admission_block_ins`·`_upd`·`events_admission_block`·`participants_admission_block`) — **아니면 멈춤·【질문】(대체안 = 조건부 INSERT)** |
| 3-3 | **T16 트리거 실측(원격 · 직접 INSERT 가 실패해야 한다)** — 임시 차단 행 → 그 id·지문으로 직접 INSERT | ① `python3 "$R/ops/admission-block.py" --target trial --remote --shape absent --participant adm-t16-probe --fingerprint SHA256:<버림 키 지문> --execute` ② `$W d1 execute … --command "INSERT INTO participants (participant_id, display_name, key_type, key_b64, fingerprint, is_operator, revoked_at, created_at) VALUES ('adm-t16-probe','p','ssh-ed25519','AAAA','SHA256:<버림 키 지문>',0,NULL,'t')"` ③ 같은 모양으로 `INSERT INTO events (… from_id='adm-t16-probe' …)` | ②③ 이 **실패**하고 오류 문자열에 `agora:admission_blocked` **포함**(원문 그대로 기록 · D1 이 감싸는 모양 = catch 의 포함 비교 근거) · 참가자·이벤트 행 0. 성공해 버리면 = 트리거 미지원 → 그 행을 지우고 멈춤·【질문】 |
| 3-4 | 우리 id+지문 차단 행 | `python3 "$R/ops/admission-block.py" --target trial --remote --participant jarvis-jk1gn50iw7 --fingerprint SHA256:u9ywSzKEEc1yMrrtWidT/p2UlZYdtkae9EAXCVyWHJI`(계획) → `--execute` | 사전 확인 = id 행 0 · 지문 행 0(시험 릴레이 정상) · 「차단 행 있음 · 명부·체크포인트 표 동일」 |
| 3-5 | 켜기 전 준비 | `python3 "$R/tools/build_next_trial.py" --next-url https://agora-relay-next.oogisoogi.workers.dev` · `wrangler.next.jsonc` 의 `"workers_dev": false` → `true`(preview_urls 는 false 유지) · `ops/trial-relay-state.jsonl` 에 `verifying` 한 줄 | — |
| 3-6 | 켜서 배포(검증 중) | `$W deploy --config "$R/relay/wrangler.next.jsonc"` | `/health` 200 ok:true · 탐지기 = 시험 릴레이 id·지문 404(정상) |
| 3-7 | **T16·T18 HTTP 실측** — 버림 키 2개(A·B · 스크래치에서 생성 · 저장소 밖) | A 등록 → A 가 토론방 genesis·post(201) → `admission-block --target trial --remote --shape registered --participant <A> --fingerprint <A 지문> --execute` → A 새 글 = **401 code 4 why=retired** · A 재전송(차단 전 글) = 200 같은 event_id · 같은 message_id 다른 내용 = 422 · A 재등록 = 403 · B 지문을 `--shape absent` 로 차단 → **B 키로 다른 이름 등록 = 403 · 행 0(T18)** | 전부 기대대로 · 원격 D1 에서 `SELECT COUNT(*)` 로 행 0 확인 |
| 3-8 | 끄기 | `"workers_dev": true` → `false` · `$W deploy --config …` · `ops/trial-relay-state.jsonl` 에 `off` 한 줄 | `/health` = 404 error code 1042 · 미리보기 404 · 탐지기 「꺼짐 — 건너뜀」 |

- 3-3·3-7 의 임시 참가자·방·글은 시험 릴레이 원장에 남는다(원장은 append-only) — 이름 머리를 `adm-t16-`·`adm-t18-` 로 가른다.
- T12(경합) 는 원격에서 HTTP 로 재현할 수 없다(검사 통과 뒤 차단 커밋 창) — 3-3 의 직접 INSERT 가 **트리거가 원격에서 발화하고 표식 문자열이 오는지**를 재고, catch 매핑은 로컬 경합 창(run-admission race)이 잰다.

## 4단계 — 본 릴레이(agora-relay · agora.godmeyou.kr) · master/박사님 게이트 · 워커는 원고만

| # | 무엇 | 명령 | 합격 |
|---|---|---|---|
| 4-0 | **사전 D1 백업(필수)** — 저장소 밖 | `$W d1 export agora-relay --remote --config "$R/relay/wrangler.jsonc" --output ~/.local/state/agora-detect/backup-main-<시각>.sql` | 파일 > 0 · `participants`·`events` INSERT 행 수 = 원격 `SELECT COUNT(*)` |
| 4-1 | 마이그레이션 0002 **먼저**(반대 순서 = 새 코드의 차단 조회 「no such table」 · 설계 §7) | `$W d1 migrations apply agora-relay --remote --config "$R/relay/wrangler.jsonc"` | `0002 ✅` · 옛 코드(지금 배포본)는 새 표와 무관하게 돈다 |
| 4-2 | 표 1·트리거 4 확인 | 3-2 와 같은 질의(본 D1) | 5개 |
| 4-3 | 사전 사진 | `GET /participants/{allowed_signers,revoked_keys,operators}` 바이트 · `GET /participants/checkpoint` · 방 2개(439fc804·0b80c218) `GET /rooms/:id` state_hash | 저장 |
| 4-4 | 배포 | name 게이트(`agora-relay`) → `$W deploy --config "$R/relay/wrangler.jsonc"`(자산 = relay/board · routes = 커스텀 도메인) | `/health` 200 |
| 4-5 | 사후 대조 | 4-3 과 같은 GET | 명부 세 파일·체크포인트·두 방 state_hash **동일**(차단 행 0 이므로 당연 — 코드 교체만의 무영향 확인) · 탐지기 OK · 우리 상주 다음 회차 정상 |
| — | **우리 id 차단은 이 티켓 밖**(§7 단계 7 · 새 id 전환 뒤 · 박사님 결정) | `admission-block.py --target main --remote …`(상주 먼저 정지 — 스크립트가 강제) | 두 D1 모두 끝나기 전 「차단 완료」 보고 금지 |

- 되돌림: 코드 = 이전 배포본으로 재배포(`wrangler rollback` 또는 2cf9c1e 빌드) — 트리거·표는 남아도 옛 코드와 무관(롤백 창은 짧게 · §9) · 표·트리거 제거 = 별도 마이그레이션(권하지 않음).
- 계약 문서(RELAY.md 오류표·§8 스키마·「계약 문장」 · THREAT-MODEL R-16) = 초안만(`DRAFT-contract-admission.md`) · 확정 = master(§7 단계 5).
