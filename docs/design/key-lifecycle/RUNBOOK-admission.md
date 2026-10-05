# RUNBOOK-admission — 받아들이기 차단 원격 적용 명령 원고(3단계 시험 릴레이 · 4단계 본 릴레이)

TICKET=agora-admission-block-0929 · worker-agoraimpl@surface:1155 · 2026-09-29 · 설계 = DESIGN-v3 §5-3 · §7 단계 3·4 · §8 T16·T18
⚠**원고다.** 아래 한 줄 한 줄이 원격 쓰기·배포다 — 각 단계마다 워커가 【실행직전확인요청】 → master 재승인(그 1건만) → 실행 → 사후 실측 보고.
⚠`ops/admission-block.py` 종료 코드: **0** = 차단·대조 성공(기대값) · **11** = 이미 차단(쓰지 않음 — 이전 실행이 4·5·6 이었다면 그 대조를 사람이 손으로 끝낸다) · **10** = 계획만 · **3** = 중단(쓰기 0 · 「0행」 사유면 **경보 → 멈추고 【질문】**) · **4** = 쓰기 뒤 기존 행·파일 불일치(멈춤·보고) · **5** = 쓰기 뒤 대조 미완(동시 등록 포함 · 사람 대조) · **6** = 쓰기 결과 불명(같은 명령 재실행 → 11 이면 행 있음 · 0 이면 이번에 씀 · 3 이면 첫 실행도 쓰지 않았고 그 사이 모양이 바뀌었다 → 경보 · 멈추고 【질문】).
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
| 3-0b | (읽기) 적용 기록·비대화 실행 확인 — **첫 원격 호출은 읽기로** | `$W d1 migrations list agora-relay-next --remote --config "$R/relay/wrangler.next.jsonc"` · `python3 "$R/ops/admission-block.py" --target trial --remote --check-schema` | list = 0001 적용됨·0002 대기 · check-schema = rc 3(「없음」 5개) — 프롬프트 없이 끝나고 `--json` 모양이 로컬과 같음 |
| 3-1 | 마이그레이션 0002 | `$W d1 migrations apply agora-relay-next --remote --config "$R/relay/wrangler.next.jsonc"` | 출력 표 `0002_admission_blocks.sql ✅` |
| 3-2 | 표 1·트리거 4 확인 | `python3 "$R/ops/admission-block.py" --target trial --remote --check-schema`(같은 것을 손으로: `$W d1 execute … --json --command "SELECT type, name FROM sqlite_master WHERE name LIKE '%admission%'"`) | table 1 + trigger 4(`checkpoints_admission_block_ins`·`_upd`·`events_admission_block`·`participants_admission_block`) — **아니면 멈춤·【질문】(대체안 = 조건부 INSERT)** |
| 3-3 | **T16 트리거 실측(원격 · 직접 INSERT 가 실패해야 한다)** — 임시 차단 행 → 그 id·지문으로 직접 INSERT | ① `python3 "$R/ops/admission-block.py" --target trial --remote --not-ours --participant adm-t16-probe --fingerprint SHA256:<버림 키 지문> --execute`(기본 모양 absent) ② `$W d1 execute … --command "INSERT INTO participants (participant_id, display_name, key_type, key_b64, fingerprint, is_operator, revoked_at, created_at) VALUES ('adm-t16-probe','p','ssh-ed25519','AAAA','SHA256:<버림 키 지문>',0,NULL,'t')"` ③ `$W d1 execute … --command "INSERT INTO events (thread_id, message_id, from_id, kind, prev, hash, canonical, signature, category, title, is_genesis, created_at) VALUES ('00000000000000000000000000000000','00000000000000000000000000000001','adm-t16-probe','post','p','h','{}','s','debate','',0,'t')"` ④ `… --command "INSERT INTO roster_checkpoints (checkpoint, signer, signature, signed_at) VALUES ('adm-t16-cp','adm-t16-probe','s','t')"`(INSERT 트리거) ⑤ 차단 안 된 이름으로 한 행을 먼저 넣고(`… VALUES ('adm-t16-cp2','adm-t16-free','s','t')`) → `… --command "UPDATE roster_checkpoints SET signer='adm-t16-probe' WHERE checkpoint='adm-t16-cp2'"`(UPDATE 트리거) → 끝나면 `DELETE FROM roster_checkpoints WHERE checkpoint='adm-t16-cp2'` | ②③④⑤ 가 **실패**하고 오류 문자열에 `agora:admission_blocked` **포함**(원문 그대로 기록 — ⚠이것은 **wrangler CLI 통로**의 모양이다 · 워커 런타임 바인딩 오류(catch 가 받는 것)는 3-7b 가 잰다) · 참가자·이벤트 행 0. 성공해 버리면 = 트리거 미지원 → 그 행을 지우고 멈춤·【질문】 |
| 3-4 | 우리 id+지문 차단 행 | `python3 "$R/ops/admission-block.py" --target trial --remote --participant jarvis-jk1gn50iw7 --fingerprint SHA256:u9ywSzKEEc1yMrrtWidT/p2UlZYdtkae9EAXCVyWHJI`(계획) → `--execute` | 사전 확인 = id 행 0 · 지문 행 0(시험 릴레이 정상) · 「차단 행 있음 · 명부·체크포인트 표 동일」 |
| 3-5 | 켜기 전 준비 | `python3 "$R/tools/build_next_trial.py" --next-url https://agora-relay-next.oogisoogi.workers.dev` · `wrangler.next.jsonc` 의 `"workers_dev": false` → `true`(preview_urls 는 false 유지) · `ops/trial-relay-state.jsonl` 에 `verifying` 한 줄 | — |
| 3-6 | 켜서 배포(검증 중) | `$W deploy --config "$R/relay/wrangler.next.jsonc"` | `/health` 200 ok:true · 탐지기 = 시험 릴레이 id·지문 404(정상) |
| 3-7 | **T16·T18 HTTP 실측** — 버림 키 2개(A·B · 스크래치에서 생성 · 저장소 밖) | A 등록 → A 가 토론방 genesis·post(201) → `admission-block --target trial --remote --not-ours --shape registered --participant adm-t18-a… --fingerprint <A 지문> --execute`(registered 는 `adm-t` 머리만) → A 새 글 = **401 code 4 why=retired** · A 재전송(차단 전 글) = 200 같은 event_id · 같은 message_id 다른 내용 = 422 · A 재등록 = 403 · B 지문을 `--not-ours --participant adm-t18-b`(모양 absent)로 차단(3-7b 가 이 이름을 쓴다) → **B 키로 다른 이름 등록 = 403 · 행 0(T18)** | 전부 기대대로 · 원격 D1 에서 `SELECT COUNT(*)` 로 행 0 확인 |
| 3-7b | **(권고 · master 선택) 바인딩 오류 통로 실측** — 앱 검사를 뺀 경합 창 사본(`relay/scripts/run-admission.py` 의 `RACE` 편집)을 시험 릴레이에 한 번 배포 | 사본 폴더에서 `$W deploy --config <사본>/relay/wrangler.next.jsonc`(name 게이트) → 차단된 adm-t18-a 새 글 · **등록은 행이 없는 차단 대상으로**(B 지문으로 막은 `adm-t18-b` 이름에 새 키 C · B 키로 다른 이름 `adm-t18-x` — 이미 등록된 A 의 재등록은 byId 같은 지문 분기에서 200 이라 catch 에 안 닿는다 · impl codex) | 새 글 = **401 why=retired**(= catch 가 원격 바인딩 오류에서 표식을 찾음) · 두 등록 = 403 · 참가자 행 0 · 500 이면 표식 모양이 다르다 → 멈춤·【질문】 · 끝나면 정상 코드로 재배포 · ⚠안 하면 「바인딩 오류 모양 = 원격 미실측」이 잔존한 채 4단계로 간다 |
| 3-8 | 끄기 | `"workers_dev": true` → `false` · `$W deploy --config …` · `ops/trial-relay-state.jsonl` 에 `off` 한 줄 | `/health` = 404 error code 1042 · 미리보기 404 · 탐지기 「꺼짐 — 건너뜀」 |

- 3-3·3-7 의 임시 참가자·방·글은 시험 릴레이 원장에 남는다(원장은 append-only) — 이름 머리를 `adm-t16-`·`adm-t18-` 로 가른다.
- T12(경합) 는 원격에서 HTTP 로 재현할 수 없다(검사 통과 뒤 차단 커밋 창) — 3-3 의 직접 INSERT 가 **트리거가 원격에서 발화하고 표식 문자열이 오는지**를 재고, catch 매핑은 로컬 경합 창(run-admission race)이 잰다.

## 4단계 — 본 릴레이(agora-relay · agora.godmeyou.kr) · master/발주자 게이트 · 워커는 원고만

✅**기준 일치 확인 · 2026-09-29 22:2x KST(읽기만 · worker-agoraimpl@surface:1160)** — 본 릴레이 현재 배포 = 버전 `f49eac74`(2026-09-19 17:15:27 KST · `wrangler deployments list` 의 마지막 줄 · 태그·메시지 없음). 그 시각은 2cf9c1e 커밋(17:14:47) 40초 뒤 · 53b21a8(17:25:11)보다 앞이고, 2cf9c1e→53b21a8 은 문서 1커밋(relay 코드·자산·설정 차이 0). 자산 23개(`relay/board` @53b21a8) 대조 = JS·CSS·dev 18개 바이트 동일 · HTML 5개는 Cloudflare 엣지 주입(숨은 `/cdn-cgi/content` 링크 · `__CF$cv$params` 챌린지 스크립트 · Web Analytics 비콘)과 그것이 연 줄바꿈 1개를 걷어내면 바이트 동일. `/health` = ok:true · scrub_bundle 59507587…270e7(시험 릴레이의 같은 값과 동일). ⚠워커 스크립트 본문 자체는 읽는 경로가 없어 바이트 대조하지 않았다(배포 시각·자산·문서뿐인 차이로 추론).

| # | 무엇 | 명령 | 합격 |
|---|---|---|---|
| 4-0 | **사전 D1 백업(필수)** — 저장소 밖 · 내보내기 동안 질의가 잠깐 막힐 수 있다【미확인】 → 조용한 시각에 | `$W d1 export agora-relay --remote --config "$R/relay/wrangler.jsonc" --output ~/.local/state/agora-detect/backup-main-<시각>.sql` | 파일 > 0 · `participants`·`events` INSERT 행 수 = 원격 `SELECT COUNT(*)` |
| 4-1 | 마이그레이션 0002 **먼저**(반대 순서 = 새 코드의 차단 조회 「no such table」 · 설계 §7) | `$W d1 migrations apply agora-relay --remote --config "$R/relay/wrangler.jsonc"` | `0002 ✅` · 옛 코드(지금 배포본)는 새 표와 무관하게 돈다 |
| 4-2 | 표 1·트리거 4 확인 | 3-2 와 같은 질의(본 D1) | 5개 |
| 4-3 | 사전 사진 | `GET /participants/{allowed_signers,revoked_keys,operators}` 바이트 · `GET /participants/checkpoint` · 방 2개(439fc804·0b80c218) `GET /rooms/:id` state_hash | 저장 |
| 4-4 | 배포 | **스키마 게이트** `python3 "$R/ops/admission-block.py" --target main --remote --check-schema` = rc 0(아니면 배포 금지 — 새 코드는 새 표를 읽는다) → name 게이트(`agora-relay`) → `$W deploy --config "$R/relay/wrangler.jsonc"`(자산 = relay/board · routes = 커스텀 도메인) | `/health` 200 |
| 4-5 | 사후 대조 | 4-3 과 같은 GET | 명부 세 파일·체크포인트·두 방 state_hash **동일**(차단 행 0 이므로 당연 — 코드 교체만의 무영향 확인) · 탐지기 OK · 우리 상주 다음 회차 정상 |
| — | **우리 id 차단은 이 티켓 밖**(§7 단계 7 · 새 id 전환 뒤 · 발주자 결정) | `admission-block.py --target main --remote …`(상주 먼저 정지 — 스크립트가 강제) | 두 D1 모두 끝나기 전 「차단 완료」 보고 금지 |

- 되돌림: 코드 = 이전 배포본으로 재배포(`wrangler rollback` 또는 2cf9c1e 빌드) — 트리거·표는 남아도 옛 코드와 무관(롤백 창은 짧게 · §9) · 표·트리거 제거 = 별도 마이그레이션(권하지 않음).
- 계약 문서(RELAY.md 오류표·§8 스키마·「계약 문장」 · THREAT-MODEL R-16) = 초안만(`DRAFT-contract-admission.md`) · 확정 = master(§7 단계 5).
