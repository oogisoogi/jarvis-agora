# REVIEW-fable-r1 — 원문(수정 없음)

검토자 = claude -p --model claude-fable-5-1 · 도구 Read/Grep/Glob 만 · cwd = 스크래치 review-r1(커밋 f67726e 스냅샷 + 배포본 2cf9c1e 코드) · 2026-09-29 · 프롬프트 = REVIEW-codex-r1.md 의 PROMPT 절 + 도구 규칙 1줄

(1차 호출은 --allowedTools 가 프롬프트를 삼켜 rc=1 빈 출력 — 프롬프트를 stdin 으로 넘겨 재실행한 결과가 아래다)

## 출력

검토 마무리 단계입니다. 근거 대조가 끝나 최종 판정문을 작성합니다.

**1) [문제점]**

- **F1 · HIGH · 서버 사본 어긋남은 클라이언트 쓰기까지 막는다(§8 실패 방식 과소 서술)**. 근거 `relay/src/index.ts:354-359`(POST 응답 `verdict.reason`) → `agora/store_relay.py:439-440`(`relay_verdict`로 실림) → `agora/tools.py:296-323`(사유가 재시도 불가면 code 3, 재시도 사유면 1회 재시도 뒤 `tools.py:261-267` `rejected_but_head_unchanged`로 code 9). 응답 유실 경로도 같다: `agora/core.py:197-205`가 릴레이 `valid`를 판정 근거로 쓴다. 따라서 `retired`가 `revoked`로 합쳐지는 변이(T8)가 실제로 나면 「서버 방 사본만 어긋남」이 아니라, 은퇴 id가 한 번이라도 글을 쓴 모든 방에서 **전원의 새 글이 `stale_expected_state`로 거부**된다. 판정(state_hash)은 안 새지만 가용성이 죽는다. 고칠 방향: §8 행을 「해당 방 전원 쓰기 불능」으로 정정하고, T8을 선택이 아닌 배포 게이트로 승격. 라이브 스모크에 「은퇴 id가 있는 방에 제3자가 post → 201 accepted」를 추가.

- **F2 · HIGH · 이행 3(마이그레이션 → 배포)의 로컬 게이트 근거가 틀렸고 대상 D1이 둘이다**. `relay/scripts/run-local.py:46-56`은 `SELECT 1 FROM events`가 「no such table」일 때만 `migrations apply`를 돌린다. 0001이 이미 먹인 로컬 D1에는 0002가 **적용되지 않는다**. §5-1 #11의 「L57이 번호순 적용」은 새 트리에서만 참이다. 또 `relay/wrangler.next.jsonc:11,21`(agora-relay-next · D1 `4bfe34f0…`)과 `relay/wrangler.jsonc:14`(D1 `cbdfaaef…`)가 같은 코드로 배포된다. 이행표는 어느 config·어느 DB에 0002를 먹이는지 적지 않는다. `next`에만 먹이고 본 릴레이를 배포하면 G2 시나리오(전 경로 500)가 그대로 난다. 고칠 방향: 이행 3에 `--config` 절대경로와 `database_id`를 명기하고, 로컬은 `wrangler d1 migrations apply --local`을 명시 실행한 뒤 `PRAGMA table_info(participants)`로 확인하는 절차로 바꾼다. 두 릴레이 모두에 0002를 먹인 뒤 배포.

- **F3 · MED · 두 번째 받아들이기 면(agora-relay-next)이 설계 밖이다**. `wrangler.next.jsonc:2-3`은 「시험용 먼저 → 실사용 → 본 릴레이 교체」로 오너가 채택한 경로이고, `:31`의 namespace가 본 릴레이와 같다. 새어 나간 키를 가진 자는 그쪽에 `jarvis-jk1gn50iw7`를 먼저 등록할 수 있다(`index.ts:154-183` · 지문 UNIQUE는 D1별). 은퇴 칸은 D1 한 곳의 행이라 그쪽에는 효력이 없다. 고칠 방향: §2 위협 모델에 「릴레이가 둘」을 넣고, `next` D1에도 같은 행을 두거나 그 id를 선점 등록해 둔다. 탐지기도 두 주소를 본다.

- **F4 · MED · 탐지기 명세가 응답 모양과 안 맞고 오탐 하나가 영구적이다**. `index.ts:486-497`의 이벤트 목록 항목에는 `from`·`message_id` 칸이 없다. `body`를 `parse_post`(`relay/src/lib/post.ts:25`)로 풀어야 한다. §5-2는 두 칸이 있는 것처럼 적었다. 원장 `sent` 행은 **확정 쓰기에만** 남는다(`agora/core.py:95-98`, `:248-252`). code 8 뒤 재조회까지 실패하면(`agora/tools.py:345-363`) 릴레이에는 글이 있고 원장에는 없다. 이 오탐은 한 주기 유예로 안 풀린다. 고칠 방향: 파싱 단계 명시, 「원장 없음 + 릴레이 `valid` 불문」을 「미확정 8 잔여」 사유로 따로 분류. 같은 id로 다른 설정 폴더에서 쓰는 프로세스(`tools/rehearsal.py:68,450`이 `AGORA_CONFIG_DIR`을 바꾼다)가 있으면 원장이 갈리므로 「한 id = 원장 폴더 하나」를 탐지기 불변식으로 적는다.

- **F5 · MED · 1차 출처 과대 해석(Q8)**. 설계 §1-2는 NIST §7.4 「비활성」을 근거로 대지만, 실제 상황은 §7.5/§5.5 「노출 의심」이다. RESEARCH §3.3 인용 원문은 "the compromised key shall be revoked"·"continued use ... limited to processing information already protected"다. day1/day15 예시는 **이미 받은 글을 믿어도 된다**는 뜻이지, 노출 의심 키로 **계속 서명해도 된다**는 뜻이 아니다. 「유지」 권고는 NIST가 지지하는 것이 아니라 오너의 위험 수용이다. Keybase 선례(A-5a)는 공개 Merkle 루트가 있어 성립한다(RESEARCH §5a). 릴레이는 그것이 없으므로 「릴레이가 정직할 때만」이라는 단서가 A-5a 옆에 붙어야 한다. 고칠 방향: §1-2에 「NIST 기준 정답은 폐기, 유지는 위험 수용」을 명시.

- **F6 · MED · 5-긴급의 공백: 은퇴 칸 배포 전에 경보가 울리면 할 수 있는 일이 없다**. 이행 1~3은 며칠이 걸리고, 그 사이 대응 수단은 오늘과 같이 폐기(과거 소멸)와 운영자 abort뿐이다. 설계는 이 창을 적지 않았다. Q5와 연결(아래 논쟁점).

- **F7 · LOW · 은퇴된 상주가 매 주기 401을 낸다**. `agora/resident.py:313-320`은 `/home`의 `speak_due`로 후보를 고르는데, `index.ts:636-642`의 그 질의는 은퇴를 모른다. 상주는 매 주기 쓰기를 시도해 code 4로 실패하고 `tools/daily_loop.py:174-195`가 실패 횟수를 센다. 「무해」는 맞지만 소음이다. 고칠 방향: `/home` 응답에 `retired` 알림을 넣을 때 `speak_due`를 비우거나 상주가 알림을 보고 멈추게 한다.

- **F8 · LOW · 인용 줄 오차(Q3 · 결론에 영향 없음)**. 표본 30여 개 대조 결과 대부분 정확. 어긋난 것: RELAY.md 「L546-L547 되돌림 스크립트 없음」→ 실제 `docs/RELAY.md:547-548`. `index.ts L627-L631` → 질의는 `:628-631`. `roster.py L112-L121` 지문 추출 → `:115-121`. REFLECTION의 `store.ts L102` → `:103`. RESEARCH §7-4는 하한 8.9, DESIGN은 8.7로 서로 다르다(클라이언트는 `sign.py:165`처럼 `-Y verify`만 쓰므로 8.7이 맞고, RESEARCH 쪽을 고친다).

- **F9 · LOW · 시험 계획 빈칸**. #5(은퇴 운영자 체크포인트 거부)·#7(`/home` 알림)에 대응하는 T가 없다. `store.ts:66`의 `operators` 집합이 은퇴 뒤에도 그대로여서 과거 abort가 유효하다는 것(G4)도 T1 골든에 「은퇴 운영자가 abort한 방」이 없으면 안 잰다. T5는 같은 message_id·다른 내용 → 422(`index.ts:270-271`) 불변도 함께.

**2) [논쟁점]**

- **핵심 주장(Q1)은 참이다**. 판정 입력은 명부 파일(`roster.ts:28-65`)·원장뿐이고, CAS 값은 클라이언트 리듀서에서 나온다(`tools.py:459,605` · `reducer.py:676`). `fetch`는 서버 판정 칸을 일부러 버린다(`store_relay.py:463-470`). 그러나 「영향 없음」의 범위를 「상태 계산」으로 좁혀 적어야 한다. 쓰기 경로는 서버 판정에 의존한다(F1).
- **Q4 반대 논거는 코드와 맞다**. `sign.py:165-166`은 `-Overify-time`을 안 넘기고, 실패 사유는 `not_in_roster`(`:167`)다. `tools.py:174`는 `revoked`·`no_signature`만 빼므로 이 사유는 세어진다. 격리된 글의 후손은 `reducer.py:311-317`에서 `unreachable`이 되어 머리가 그 앞으로 물러나므로, 격리 글은 반드시 「머리 뒤」(`tools.py:181`)에 걸린다. 쓰기 봉쇄는 조건부가 아니라 사실상 확정이다. 설계자의 결론에 동의한다.
- **Q5, 설계가 비교하지 않은 안**: 「가장자리 차단」. Cloudflare WAF 사용자 규칙으로 `POST /events`·`/register`·`/participants/checkpoint` 본문에 `"from":"jarvis-jk1gn50iw7"`(또는 그 id)가 있으면 차단. 코드 0·마이그레이션 0·되돌리기 즉시·**오늘** 가능. F6의 창을 메우는 유일한 임시 스위치다. 대가: 멱등 재전송도 막힌다(이미 원장에 있는 글이라 손실은 응답 유실 건뿐). 본문 검사가 현재 요금제에서 되는지는 【미확인】. (a)의 대체가 아니라 (a) 배포 전 임시 대응으로 §6에 넣을 가치가 있다.
- **(a′) 설정값 방식이 우리 1건에는 더 낫다는 설계자 자신의 말(§3 (a′))에 동의한다**. 마이그레이션·두 D1 문제(F2)가 통째로 사라진다. 결정 ⑶이 「일반화 안 함」이면 (a′)를 정식 권고로 올리는 편이 위험이 작다.

**3) [다음 단계 조언]**

1. F1·F2·F3을 반영한 v2 작성. §8 실패 행 정정, 이행 3에 config·DB id·`PRAGMA` 확인 명기, `next` 릴레이 포함.
2. 오너 결정 ⑶ 먼저 받고 (a)/(a′) 확정. (a′)면 마이그레이션 절 삭제.
3. §6에 「배포 전 경보 시 임시 대응」 행 추가(가장자리 차단 가능 여부 실측 뒤).
4. 탐지기 명세를 파싱 기반으로 고치고 오탐 분류에 「8 잔여」 추가. 두 릴레이 주소를 본다.
5. §1-2를 「NIST 정답은 폐기 · 유지는 위험 수용」으로 정직하게 고친다.
6. T 계획에 F9 항목과 「제3자 post가 은퇴 id 방에서 201 accepted」 스모크 추가.

```json
{"verdict":"REVISE","findings":[
{"id":"F1","severity":"HIGH","evidence":"agora/tools.py:296-323; agora/tools.py:261-267; agora/core.py:197-205; relay/src/index.ts:354-359","claim":"서버 사본이 은퇴를 폐기처럼 판정하면 클라이언트 정본은 불변이나 relay_verdict·audit_verdict 경로로 해당 방 전원의 쓰기가 거부된다. §8 「서버 사본만 어긋남」은 과소 서술","fix":"§8 정정 · T8을 배포 게이트로 승격 · 은퇴 id 방에서 제3자 post 201 accepted 스모크 추가"},
{"id":"F2","severity":"HIGH","evidence":"relay/scripts/run-local.py:46-56; relay/wrangler.jsonc:14; relay/wrangler.next.jsonc:11,21","claim":"run-local.py는 events 표 부재일 때만 마이그레이션을 먹여 기존 로컬 D1에 0002가 안 붙는다. 대상 D1이 둘인데 이행 3이 어느 DB·config인지 안 적었다","fix":"이행 3에 --config 절대경로·database_id 명기 · 로컬은 migrations apply --local 명시 후 PRAGMA table_info 확인 · 두 D1 모두 적용 후 배포"},
{"id":"F3","severity":"MED","evidence":"relay/wrangler.next.jsonc:2-3,31; relay/src/index.ts:154-183","claim":"agora-relay-next는 같은 namespace의 두 번째 받아들이기 면이다. 새어 나간 키로 그쪽에 같은 id를 선점 등록할 수 있고 은퇴 칸은 D1별이라 효력이 없다","fix":"§2 위협 모델에 릴레이 2개 명시 · next D1에도 은퇴 행 또는 선점 등록 · 탐지기가 두 주소를 본다"},
{"id":"F4","severity":"MED","evidence":"relay/src/index.ts:486-497; agora/core.py:95-98,248-252; agora/tools.py:345-363; tools/rehearsal.py:68,450","claim":"이벤트 목록에 from·message_id 칸이 없어 body 파싱이 필요하다. code 8 뒤 재조회 실패 시 릴레이에만 있는 글은 영구 오탐이다. 다른 설정 폴더에서 같은 id로 쓰면 원장이 갈린다","fix":"parse_post 단계 명시 · 「8 잔여」 오탐 사유 분류 · 한 id = 원장 폴더 하나를 탐지기 불변식으로 명기"},
{"id":"F5","severity":"MED","evidence":"design/RESEARCH-primary-sources.md:187-188 (NIST §5.5·§5.5.1 인용); design/DESIGN-v1.md:35-39","claim":"NIST §5.5는 노출 키를 폐기하라고 하며 day1/day15 예시는 수신 글의 신뢰이지 계속 서명의 근거가 아니다. 「유지」는 NIST 지지가 아니라 오너 위험 수용이다. Keybase 선례는 공개 Merkle 루트 전제","fix":"§1-2에 「NIST 정답은 폐기 · 유지는 위험 수용」 명시 · A-5a에 「릴레이 정직 전제」 단서"},
{"id":"F6","severity":"MED","evidence":"design/DESIGN-v1.md:170-178 (이행표)","claim":"이행 1~3 완료 전에 탐지 경보가 울리면 대응 수단이 오늘과 같이 폐기·abort뿐인데 설계가 그 창을 적지 않았다","fix":"§6에 배포 전 임시 대응 행 추가 · 후보 = Cloudflare 가장자리 차단(요금제 가능 여부 실측 필요)"},
{"id":"F7","severity":"LOW","evidence":"agora/resident.py:313-320; relay/src/index.ts:636-642; tools/daily_loop.py:174-195","claim":"/home speak_due가 은퇴를 모르므로 은퇴된 상주가 매 주기 쓰기를 시도해 code 4 실패를 쌓는다","fix":"/home 은퇴 알림 시 speak_due를 비우거나 상주가 알림을 보고 멈추게 한다"},
{"id":"F8","severity":"LOW","evidence":"docs/RELAY.md:547-548; relay/src/index.ts:628-631; agora/roster.py:115-121; relay/src/lib/store.ts:103; agora/sign.py:165","claim":"인용 줄 오차 4건(결론 영향 없음) · RESEARCH §7-4 하한 8.9와 DESIGN 8.7 불일치(클라이언트는 -Y verify만 쓰므로 8.7이 맞다)","fix":"줄 번호 정정 · RESEARCH §7-4를 8.7로 통일"},
{"id":"F9","severity":"LOW","evidence":"relay/src/lib/store.ts:66; relay/src/index.ts:734-736,756; relay/src/index.ts:270-271","claim":"#5 체크포인트 거부·#7 /home 알림·은퇴 운영자의 과거 abort 유효(operators 집합 불변)에 대응하는 시험이 없다. T5에 422 불변도 없다","fix":"T10 은퇴 운영자 체크포인트 403 · T11 /home retired 알림 · T1 골든에 은퇴 운영자 abort 방 포함 · T5에 같은 id 다른 내용 422 추가"}
],"checked":["relay/src/index.ts:154-183","relay/src/index.ts:230-245","relay/src/index.ts:257-272","relay/src/index.ts:275-306","relay/src/index.ts:309-318","relay/src/index.ts:338-359","relay/src/index.ts:486-497","relay/src/index.ts:515","relay/src/index.ts:621-642","relay/src/index.ts:677-678","relay/src/index.ts:698-711","relay/src/index.ts:728-765","relay/src/index.ts:777-812","relay/src/lib/roster.ts:28-65","relay/src/lib/roster.ts:91-117","relay/src/lib/store.ts:40-70","relay/src/lib/store.ts:104-139","relay/src/lib/sshsig.ts:179-224","relay/src/lib/reducer.ts:144-151","relay/src/lib/reducer.ts:190-215","relay/src/lib/reducer.ts:340-355","relay/src/lib/reducer.ts:463-473","relay/migrations/0001_init.sql:5-14","relay/scripts/run-local.py:46-65","relay/wrangler.jsonc:14","relay/wrangler.next.jsonc:2-36","agora/sign.py:130-169","agora/roster.py:85-121","agora/reducer.py:118-123","agora/reducer.py:292-317","agora/reducer.py:676","agora/tools.py:7","agora/tools.py:118-143","agora/tools.py:165-195","agora/tools.py:224","agora/tools.py:239-247","agora/tools.py:261-323","agora/tools.py:345-363","agora/tools.py:459","agora/tools.py:605","agora/tools.py:1327-1353","agora/core.py:72-100","agora/core.py:197-224","agora/core.py:248-269","agora/store_relay.py:426-441","agora/store_relay.py:463-470","agora/store_relay.py:584-586","agora/onboard.py:119-128","agora/onboard.py:204-286","agora/resident.py:269-334","agora/ledger.py:110-143","agora/event.py:69-117","relay/src/lib/schema.ts:29-30","relay/src/lib/schema.ts:271-280","relay/src/lib/post.ts:25-40","docs/RELAY.md:85-92","docs/RELAY.md:542-554","docs/THREAT-MODEL.md:24","docs/THREAT-MODEL.md:48","docs/ONBOARDING.md:7","docs/RUN-WINDOWS.md:84-89","participants/operators:1-3","tools/daily_loop.py:174-195","tools/rehearsal.py:68,450","exp-worker/plain","exp-worker/two","exp-worker/hist","exp-worker/retired"]}
```

(종료 rc=0)
