# REVIEW-fable-r2 — 원문(수정 없음)

검토자 = claude -p --model claude-fable-5-1 · Read/Grep/Glob 만 · cwd = 스크래치 review-r2(커밋 3356b66 스냅샷 + 배포본 2cf9c1e) · 2026-09-29 · 프롬프트 = REVIEW-codex-r2.md 의 PROMPT 절 + 도구 규칙 1줄

## 출력

**판정: REVISE.** 중심안 (a2) 자체는 건전합니다. 판정 누수 없음·경합 제거·events/roster_checkpoints 롤백 안전은 코드로 확인했습니다. 그러나 시험 릴레이 처리(§5-3 #2)가 §5-2 의 검사 위치·§5-1 의 「participants 트리거 불필요」 문장과 서로 모순이라 선점 등록을 실제로 막지 못하고, 1라운드 검토자가 낸 가장 싼 대안(선점 등록) 하나가 처분표에서 소리 없이 빠졌습니다.

**1) [문제점]**

- **F1 · HIGH · 시험 릴레이의 선점 등록 차단이 실제로는 안 걸린다.** §5-2 는 `/register` 검사를 「L154-L167 byId 분기」에 둔다(DESIGN-v2.md:154). 그런데 §5-3 #2 는 시험 D1 에 우리 id 가 없을 때 「차단 행만 넣고 선점은 앱 층 /register 403 으로 막는다」고 한다(:167). index.ts:154-167 의 byId 분기는 행이 있을 때만 들어가므로, 행이 없는 시험 릴레이에서는 그 검사가 한 번도 실행되지 않고 L168-L183 의 신규 등록이 그대로 통과한다. 게다가 §5-1 「participants 에는 트리거가 필요 없다, 차단된 id 는 이미 행이 있어서」(:147)는 §5-3 #2 의 0행 경우와 정면으로 모순이다. 롤백 주장(§3 (a2) ⑵ · :70)도 등록 경로에는 성립하지 않는다. 옛 코드는 admission_blocks 를 안 읽으므로 시험 릴레이에서 우리 id 행이 생긴다(이후 글은 events 트리거가 막으니 실피해는 「명부에 우리 이름이 오르는 것」까지). 고칠 방향: ⑴ /register 검사를 byId 조회와 무관하게(서명 검증 뒤·행 유무 불문) 둔다 ⑵ `participants` 에도 BEFORE INSERT 트리거(`NEW.participant_id` 차단)를 넣어 두 릴레이·롤백 모두 PK 층에서 막는다 ⑶ T6 에 「행 없음 + 차단 id + 새 키 → 403 · 행 0 · 옛 코드에서도 행 0」 추가.

- **F2 · MED · (R1 반영 누락) 처분표가 검토자의 대안 하나를 이유 없이 뺐다.** REVIEW-fable-r1.md:17 과 :51 은 시험 릴레이 대응으로 「next D1 에도 은퇴 행 **또는 그 id 를 선점 등록**」을 제안했다. DISPOSITION-r1.md:30 은 「수용」이라며 ⑴ workers_dev 끄기 ⑵ 차단 행 ⑶ 삭제만 적었고, v2 §3(:102)·§4 비교표(:109-122)에 선점 등록은 없다. 이 안은 새 키(유출 스냅샷에 없는 키·쓰고 버리는 키)로 시험 릴레이에 우리 id 를 등록해 두는 것으로, 코드 0·마이그레이션 0·오늘 가능·PK(0001_init.sql:6) 층이라 코드 롤백에 무관하며, workers_dev 를 켜고 끌 때마다 다시 열리는 창(F9)과 무관하게 지속된다. 외부 쓰기라 master 게이트가 필요하다는 점은 적되, 비교표에서 빠질 이유는 없다.

- **F3 · MED · 시험 릴레이의 위협은 「우리 이름」이 아니라 「우리 키」인데 설계·탐지기 모두 이름만 본다.** 유출 키를 가진 자는 시험 릴레이에 우리 공개키를 **아무 이름으로나** 등록할 수 있다(그 D1 에 우리 지문이 없으니 0001_init.sql:10 의 UNIQUE 가 막지 않는다). §5-3 #2 의 차단 행은 participant_id 기준이라 못 막고, §6-2 탐지기는 `/home?participant=<id>` 404 만 본다(:182). 그런데 index.ts:622 는 `participant_id = ?1 OR fingerprint = ?1` 이라 지문으로도 물을 수 있다. 고칠 방향: 탐지기가 두 릴레이에 `SHA256:<우리 지문>` 으로도 묻고(본 릴레이는 우리 행 = 정상, 시험은 404 여야 정상), F1 의 participants 트리거 조건에 `NEW.fingerprint` 도 넣는다.

- **F4 · MED · §5-3 #2 사전 확인 질의가 두 사건을 한 값으로 접는다.** `WHERE participant_id=?1 AND fingerprint=?2` (:167) 는 0행이 「id 부재」인지 「다른 키로 이미 선점됨」인지 가르지 못하고, 1행이 「우리」인지 「도용자가 우리 키로 먼저 등록」인지 가르지 못한다. 후자는 탐지 경보 대상인데 스크립트는 「정상 1행」으로 지나간다. 고칠 방향: id 만으로 조회한 뒤 지문 일치·불일치·부재 세 갈래로 보고하고, 불일치는 경보로 올린다.

- **F5 · MED · catch 변환 조건과 대체안(조건부 INSERT)의 실패 경로가 덜 정해졌다.** index.ts:319-334 는 INSERT 예외에서 재조회 후 없으면 `throw e` 로 가고, index.ts:80-82 가 500 code 7 로 낸다. v2 는 「오류 메시지가 `agora:admission_blocked` 면 401」(:153)이라고 하는데, D1 은 SQLite 메시지를 자기 접두·접미로 감싸 전달하므로 **동일 비교가 아니라 포함 비교**여야 하고, T16 이 「메시지 문자열이 D1 을 거쳐도 남는가」를 직접 재야 한다. 대체안 `INSERT … SELECT … WHERE NOT EXISTS`(:72)는 예외를 안 내고 0행을 돌려주므로 index.ts:335 `fail(STORE, "적재 결과를 읽지 못했다")` 가 500 code 7 을 낸다. 새 코드가 null 을 「차단」으로 다시 판정하는 분기가 필요하며, 그 경로는 이미 속도 예산(index.ts:275-284)을 소모한 뒤라는 점도 적어야 한다.

- **F6 · LOW · 롤백 상태에서 차단 id 의 요청이 남의 방 예산을 태운다.** 옛 코드는 pid·room 버킷을 INSERT **앞**에서 올린다(index.ts:275-284). 트리거가 500 을 내면 클라이언트는 `retry:true` 로 4회 재시도한다(store_relay.py:37, :49, :293-297). 요청마다 `room:<thread>` 120/분 버킷(index.ts:41, :280)이 줄어 도용자가 특정 방을 429 로 몰 수 있다. 새 코드는 앱 검사가 속도 앞이라 무관하다. §9 롤백 행에 「롤백 중 방 예산 소모 가능 · 롤백 창은 짧게」를 적으면 된다.

- **F7 · LOW · X-F7 처분이 반만 반영됐다.** `/home` 의 `speak_due: []`(:156)만 비운다. resident.py:316 은 `replies` 중 `answered=false` 도 후보로 쓰므로 은퇴 상주는 답글 목적으로 계속 깨어나 401 을 쌓고, daily_loop.py:174-176·:193-195 가 실패를 센다. 차단 id 에는 `replies: []` 도 함께 비우는 것이 클라이언트 무변경 안이다.

- **F8 · LOW · 신설 경로 이름이 기존 라우터와 충돌한다.** `GET /participants/retired`(:158)는 index.ts:787-788 의 `^\/participants\/([a-z_]+)$` 에 먼저 잡혀 participantsFile 로 가고 404 「그런 명부는 없다」(index.ts:705)가 난다. 라우트 순서를 앞에 두거나 이름을 바꾼다. `/participants/:id/events` 는 id 문자집합(index.ts:121)을 반영한 별도 정규식이 필요하다.

- **F9 · LOW · 이행 순서의 실무 구멍 셋.** ⑴ 1b(workers_dev:false · :211)가 3단계(시험 릴레이 원격 T16 · :213)보다 앞이라 3단계 동안 다시 켜고 끝나면 다시 꺼야 하는데 표에 없다 ⑵ 시험 릴레이 배포는 wrangler.next.jsonc:35-36 대로 `build_next_trial.py` 산출 자산이 없으면 멈춘다 ⑶ run-local.py:75-76 의 초기화는 admission_blocks 를 지우지 않아 T4 뒤 재실행이 그 id 로 계속 막힌다.

- **F10 · LOW · 계약 문장이 자기 응답과 어긋난다.** :161 은 은퇴가 「서버 참고 판정(verdict·valid)에 나타나지 않는다」고 하는데 :152 의 401 본문은 `verdict:"unsigned", why:"retired"` 를 싣는다. 이것은 index.ts:237-244 의 오류 detail 관례이지 2xx 의 verdict 객체가 아니므로, 문장을 「2xx 응답의 verdict 객체·이벤트 목록의 valid」로 좁히면 된다. 파이썬 쪽 `_blind_spot`(tools.py:165-183)은 POST 오류의 why 를 안 보므로 누수는 아니다.

**2) [논쟁점]**

- **C-F1 반박(HIGH→LOW)은 타당하다.** 등록은 누구에게나 열려 있고(index.ts:103-107) 새 키로 새 id 를 만드는 힘은 원래 있으므로, BOM 변형 키로 새 id 를 만드는 것이 우리 이름(PK · index.ts:154-166)에 닿지 않는다는 논거는 맞다. 다만 잔여를 하나 적어야 한다. BOM 변형은 지문이 달라지므로 F3 의 「지문으로 탐지」도 그 변형은 못 본다. 결함 자체를 별도 티켓으로 고치는 것이 그 잔여의 유일한 봉합이다.
- **「판정 누수 구조적 불가」 주장은 참이다.** admission_blocks 를 읽는 곳이 rosterView(store.ts:57-70)·lookupTable(roster.ts:91-103)·verifyDetail(sshsig.ts:191-224)·deriveThread(store.ts:104-139)·세 렌더(roster.ts:28-65)·체크포인트(roster.ts:72-88) 어디에도 없으므로 새 표는 판정 입력이 될 수 없다. 이 점은 v1 대비 분명한 개선이다.
- **경합 제거·UPSERT 처리도 맞다.** 트리거는 index.ts:312-318 의 INSERT 문 안에서 실행되고, BEFORE INSERT 는 UNIQUE 검사·ON CONFLICT(index.ts:759-763) 판정보다 앞서 발화하므로 :146 의 로컬 실측과 부합한다. 트리거가 먼저 막은 뒤 catch 재조회가 기존 행을 찾으면 200 이 되는 순서도 멱등 의미를 해치지 않는다.
- **(a′) 설정값 방식이 우리 1건에는 여전히 더 작다**는 v2 자신의 판단에 동의한다. F1·F3·F4·F9 는 모두 「두 D1 에 표·트리거·행을 맞추는」 비용에서 나온 결함이고, (a′)+선점 등록(F2) 조합은 그 비용 대부분을 없앤다. 다만 롤백 시 차단 해제라는 대가는 v2 가 적은 그대로다.

**3) [다음 단계 조언]**

1. v3 에서 F1 을 먼저 닫는다. /register 검사 위치를 행 유무와 독립으로 옮기고 participants 트리거(id + 지문)를 0002 에 넣는다. §5-1 :147 문장과 §3 :70 롤백 주장을 그에 맞게 고친다.
2. §3 선택 강화·§4 비교표에 「시험 릴레이 선점 등록(버리는 키)」을 넣고, 결정 ⑶ 의 선택지로 박사님께 올린다.
3. §5-3 스크립트를 id 단독 조회 + 세 갈래 보고로 바꾸고, 탐지기 1단계에 지문 질의를 추가한다(F3·F4).
4. §5-2 catch 조건을 「포함 비교」로 명시하고 대체안의 0행 처리·예산 소모를 적는다. T16 합격 기준에 「D1 을 거친 오류 메시지 문자열」을 넣는다(F5).
5. 나머지 LOW(F6~F10)는 문장·라우트·이행표 수정으로 끝난다. 중심 메커니즘은 바꾸지 않아도 된다.

```json
{"verdict":"REVISE","findings":[
{"id":"F1","severity":"HIGH","evidence":"design/DESIGN-v2.md:147; design/DESIGN-v2.md:154; design/DESIGN-v2.md:167; code-2cf9c1e/relay/src/index.ts:154-183","claim":"§5-2 는 /register 차단 검사를 byId 분기에 두는데 시험 릴레이(우리 id 행 없음)에서는 그 분기에 들어가지 않아 §5-3 #2 가 기대하는 403 이 발생하지 않고 신규 등록이 통과한다. §5-1 「participants 트리거 불필요」는 §5-3 #2 의 0행 경우와 모순이며 롤백 안전 주장도 등록 경로에는 성립하지 않는다.","fix":"검사를 byId 조회와 무관하게 서명 검증 뒤에 둔다 · participants 에 BEFORE INSERT 트리거(NEW.participant_id · NEW.fingerprint) 추가 · T6 에 행 없음+차단 id+새 키 및 옛 코드 경우 추가"},
{"id":"F2","severity":"MED","evidence":"design/REVIEW-fable-r1.md:17; design/REVIEW-fable-r1.md:51; design/DISPOSITION-r1.md:30; design/DESIGN-v2.md:102","claim":"X-F3 처분이 「수용」이면서 검토자가 제안한 「시험 릴레이에 우리 id 선점 등록」을 이유 없이 뺐다. 버리는 새 키로 등록하면 코드 0·마이그레이션 0·PK 층·롤백 무관·workers_dev 토글과 무관하게 지속된다.","fix":"§3 선택 강화와 §4 비교표에 선점 등록을 넣고 결정 ⑶ 선택지로 제시(외부 쓰기 = master 게이트 명기)"},
{"id":"F3","severity":"MED","evidence":"code-2cf9c1e/relay/migrations/0001_init.sql:10; code-2cf9c1e/relay/src/index.ts:622; design/DESIGN-v2.md:167; design/DESIGN-v2.md:182","claim":"시험 D1 에는 우리 지문이 없어 유출 키를 아무 이름으로나 등록할 수 있는데 차단 행과 탐지기는 participant_id 만 본다.","fix":"탐지기가 두 릴레이에 SHA256:<지문> 으로도 /home 을 묻는다 · participants 트리거 조건에 지문 포함"},
{"id":"F4","severity":"MED","evidence":"design/DESIGN-v2.md:167; code-2cf9c1e/relay/src/index.ts:154-167","claim":"사전 확인 질의(id AND 지문)는 0행이 부재인지 다른 키 선점인지, 1행이 우리인지 도용자의 우리 키 등록인지 가르지 못한다.","fix":"id 단독 조회 후 지문 일치·불일치·부재 세 갈래 보고 · 불일치는 경보"},
{"id":"F5","severity":"MED","evidence":"code-2cf9c1e/relay/src/index.ts:319-335; code-2cf9c1e/relay/src/index.ts:80-82; design/DESIGN-v2.md:72; design/DESIGN-v2.md:153","claim":"catch 변환은 D1 이 감싼 메시지에 대한 포함 비교여야 하며, 조건부 INSERT 대체안은 예외 없이 0행을 돌려 L335 가 500 code 7 을 낸다. 두 경로 모두 명세가 없다.","fix":"포함 비교 명시 · 대체안에서 inserted null → admission_blocks 재조회 → 401 분기 · 예산 소모 사실 기재 · T16 에 오류 메시지 문자열 검증 추가"},
{"id":"F6","severity":"LOW","evidence":"code-2cf9c1e/relay/src/index.ts:275-284; code-2cf9c1e/agora/store_relay.py:37; code-2cf9c1e/agora/store_relay.py:49; code-2cf9c1e/agora/store_relay.py:293-297","claim":"옛 코드로 롤백된 동안 차단 id 의 요청은 속도 버킷을 올린 뒤 500 을 받고 클라이언트가 4회 재시도하므로 공유 방 버킷(120/분)을 소모시킬 수 있다.","fix":"§9 롤백 행에 방 예산 소모 가능성과 롤백 창 최소화를 적는다"},
{"id":"F7","severity":"LOW","evidence":"design/DESIGN-v2.md:156; code-2cf9c1e/agora/resident.py:316; code-2cf9c1e/tools/daily_loop.py:174-176","claim":"speak_due 만 비우면 replies.answered=false 로 상주가 계속 깨어나 401 을 쌓는다.","fix":"차단 id 의 /home 에서 replies 도 빈 배열로 준다"},
{"id":"F8","severity":"LOW","evidence":"code-2cf9c1e/relay/src/index.ts:787-788; code-2cf9c1e/relay/src/index.ts:705; code-2cf9c1e/relay/src/index.ts:121; design/DESIGN-v2.md:157-158","claim":"GET /participants/retired 는 기존 명부 파일 라우트에 먼저 잡혀 404 가 난다 · /participants/:id/events 는 id 문자집합용 별도 정규식이 필요하다.","fix":"라우트 순서를 앞에 두거나 경로명을 바꾼다"},
{"id":"F9","severity":"LOW","evidence":"design/DESIGN-v2.md:211-213; code-2cf9c1e/relay/wrangler.next.jsonc:35-36; code-2cf9c1e/relay/scripts/run-local.py:75-76","claim":"1b(workers_dev:false)가 3단계 원격 T16 보다 앞이라 재활성·재비활성 절차가 빠졌고, 시험 릴레이 배포는 자산 빌드가 선행돼야 하며, 로컬 초기화는 admission_blocks 를 지우지 않는다.","fix":"이행표에 토글 절차·자산 빌드 명기 · 구현 갈래의 reset 에 DELETE FROM admission_blocks 추가"},
{"id":"F10","severity":"LOW","evidence":"design/DESIGN-v2.md:152; design/DESIGN-v2.md:161; code-2cf9c1e/relay/src/index.ts:237-244","claim":"계약 문장은 은퇴가 verdict 에 나타나지 않는다고 하지만 401 본문이 verdict:unsigned·why:retired 를 싣는다.","fix":"문장을 2xx verdict 객체·이벤트 목록 valid 로 한정"}
],"checked":[
"code-2cf9c1e/relay/src/index.ts:80-82",
"code-2cf9c1e/relay/src/index.ts:103-107",
"code-2cf9c1e/relay/src/index.ts:121",
"code-2cf9c1e/relay/src/index.ts:154-183",
"code-2cf9c1e/relay/src/index.ts:230-245",
"code-2cf9c1e/relay/src/index.ts:257-272",
"code-2cf9c1e/relay/src/index.ts:275-284",
"code-2cf9c1e/relay/src/index.ts:309-335",
"code-2cf9c1e/relay/src/index.ts:338-360",
"code-2cf9c1e/relay/src/index.ts:428-437",
"code-2cf9c1e/relay/src/index.ts:463-503",
"code-2cf9c1e/relay/src/index.ts:515",
"code-2cf9c1e/relay/src/index.ts:613-695",
"code-2cf9c1e/relay/src/index.ts:698-711",
"code-2cf9c1e/relay/src/index.ts:728-765",
"code-2cf9c1e/relay/src/index.ts:777-812",
"code-2cf9c1e/relay/src/lib/store.ts:40-70",
"code-2cf9c1e/relay/src/lib/store.ts:104-139",
"code-2cf9c1e/relay/src/lib/store.ts:142-179",
"code-2cf9c1e/relay/src/lib/store.ts:185-199",
"code-2cf9c1e/relay/src/lib/roster.ts:28-65",
"code-2cf9c1e/relay/src/lib/roster.ts:72-103",
"code-2cf9c1e/relay/src/lib/sshsig.ts:179-224",
"code-2cf9c1e/relay/src/lib/reducer.ts:340-398",
"code-2cf9c1e/relay/src/lib/errors.ts:8-42",
"code-2cf9c1e/relay/migrations/0001_init.sql:5-31",
"code-2cf9c1e/relay/migrations/0001_init.sql:64-69",
"code-2cf9c1e/relay/scripts/run-local.py:46-65",
"code-2cf9c1e/relay/scripts/run-local.py:75-76",
"code-2cf9c1e/relay/wrangler.jsonc:14",
"code-2cf9c1e/relay/wrangler.next.jsonc:2-36",
"code-2cf9c1e/agora/tools.py:118-143",
"code-2cf9c1e/agora/tools.py:165-183",
"code-2cf9c1e/agora/tools.py:284-323",
"code-2cf9c1e/agora/tools.py:345-405",
"code-2cf9c1e/agora/core.py:72-100",
"code-2cf9c1e/agora/core.py:197-224",
"code-2cf9c1e/agora/core.py:241-269",
"code-2cf9c1e/agora/store_relay.py:35-37",
"code-2cf9c1e/agora/store_relay.py:49",
"code-2cf9c1e/agora/store_relay.py:188-207",
"code-2cf9c1e/agora/store_relay.py:293-311",
"code-2cf9c1e/agora/store_relay.py:347-356",
"code-2cf9c1e/agora/store_relay.py:426-441",
"code-2cf9c1e/agora/store_relay.py:506-562",
"code-2cf9c1e/agora/resident.py:263-320",
"code-2cf9c1e/agora/errors.py:33",
"code-2cf9c1e/tools/daily_loop.py:174-195",
"code-2cf9c1e/docs/RELAY.md:83-92",
"code-2cf9c1e/docs/RELAY.md:544-550",
"code-2cf9c1e/docs/THREAT-MODEL.md:48",
"exp-worker/plain:1",
"exp-worker/two:1-2",
"exp-worker/hist:1-2",
"exp-worker/retired:1",
"design/DESIGN-v2.md:36",
"design/DESIGN-v2.md:67-72",
"design/DESIGN-v2.md:128-169",
"design/DESIGN-v2.md:179-187",
"design/DESIGN-v2.md:205-222",
"design/DISPOSITION-r1.md:11-38",
"design/REVIEW-fable-r1.md:17",
"design/REVIEW-codex-r1.md:45-58",
"design/SURVEY.md:89-91"
]}
```

(종료 rc=0)
