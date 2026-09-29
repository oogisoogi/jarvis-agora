# REVIEW-codex-r2 — 원문(수정 없음)

검토자 = codex exec -s read-only · 입력 = 커밋 3356b66 스냅샷(design/*) + 배포본 2cf9c1e 코드 + exp-worker · 2026-09-29

## PROMPT

```
[리뷰 의뢰 — 엄격 제약 · 지정 범위만 · 적대 검증 r2(마지막 라운드)]
검토 범위(이 폴더 안만): ./design/*.md · ./code-2cf9c1e/(릴레이 배포본 코드) · ./exp-worker/(OpenSSH 실측 명부 파일)
과업: 아고라 「도장(서명 키) 은퇴·유지」 설계 **DESIGN-v2** 를 적대적으로 검증하라. v2 는 1라운드(REVIEW-codex-r1 · REVIEW-fable-r1 · 둘 다 REVISE)의 지적을 DISPOSITION-r1 처분표대로 반영한 판이다.

엄격 제약: 지정 범위만 읽는다. 서버 기동·네트워크·파일 쓰기·상태 변경 금지. 읽기 전용 명령(cat·sed·grep·rg·ls·head·wc)만. 검토 대상 수정 금지.

반드시 판정할 것(각각 file:line 근거):
R1. DISPOSITION-r1 의 「수용」 항목이 DESIGN-v2 에 실제로 반영됐는가 — 반영 누락·왜곡을 항목 id 로 지적. 「반박」(C-F1 심각도 LOW) 논거가 타당한가.
R2. 새 중심안 (a2) = 별도 admission_blocks 표 + events·roster_checkpoints BEFORE INSERT/UPDATE 트리거 + 앱 층 검사(§5). 이 안이 ⑴ 판정(명부 파일·검증·리듀서·서버 참고 판정 verdict/valid)에 새지 않는가 ⑵ 경합을 실제로 없애는가 ⑶ 코드 롤백에 안전한가 ⑷ 배포본 코드(index.ts 의 INSERT·catch·멱등 경로)와 충돌하는 곳은 없는가(예: 트리거 오류가 catch 에서 재조회 → 500 경로, 멱등 재전송, UNIQUE 충돌과의 순서).
R3. 두 릴레이(본 · agora-relay-next) 처리와 이행 순서(§7)가 빠짐없는가 — 특히 시험 릴레이에 우리 id 가 없을 때 차단 행만 넣는 절차(§5-3 #2)가 등록 선점을 실제로 막는가(index.ts /register 경로 대조).
R4. 탐지기 재설계(§6)가 r1 의 누락·오탐 지적을 해소했는가 · 남은 구멍.
R5. 새로 생긴 결함 — v2 가 새로 도입한 주장·절차 중 틀린 것.
R6. 설계가 여전히 비교하지 않은 우월안.

판정: ACCEPT | REVISE | BLOCK | ESCALATE (점수 금지). ACCEPT 는 위험 경로 file:line 확인 5개 이상이 있어야 유효. 1라운드에서 이미 처분된 사항을 같은 논거로 반복하지 말 것 — 처분이 틀렸다면 그 이유를 새 근거로.

출력(최종 메시지에 이 순서로): 1) [문제점] 심각도(HIGH/MED/LOW)·근거·틀린 점·고칠 방향 2) [논쟁점] 3) [다음 단계 조언] 4) JSON 코드 블록 {"verdict":"…","findings":[{"id":"…","severity":"…","evidence":"file:line","claim":"…","fix":"…"}],"checked":["file:line",…]}
```

## 출력

[문제점]

**판정: REVISE.** 별도 차단 표와 DB 트리거라는 중심 방향은 타당하지만, 미등록 id의 등록 차단과 경합 시 응답 계약이 미완성입니다. 아래는 지정 범위의 정적 검토 결과이며, 실행·네트워크·파일 변경은 하지 않았습니다.

**R2-F1 · HIGH — 시험 릴레이의 “차단 행만 삽입”은 등록 선점을 막지 못한다.**

- **근거:** `design/DESIGN-v2.md:147`, `:154`, `:167`; `code-2cf9c1e/relay/src/index.ts:154`, `:157`, `:168`, `:178`.
- **틀린 점:** `/register` 검사를 `byId` 분기에 넣으면서, 그 분기에 들어가지 않는 **미등록 id**도 차단한다고 주장한다. 명세대로 구현하면 `byId=null` → 지문 검사 → `participants INSERT`로 진행한다. 이벤트 트리거는 이후 발언을 막지만 **이름의 선점 등록과 명부 변경은 이미 발생**한다.
- 검사를 분기 밖으로 옮겨도 검사 이후 등록 INSERT까지의 경합과 구코드 롤백은 남는다. “participants에는 트리거가 필요 없다”는 전제가 §5-3의 예외와 충돌한다.
- **고칠 방향:** 등록 여부와 독립적인 앱 검사 및 `participants BEFORE INSERT` 차단을 추가한다. 미등록 상태·검사 후 차단·구코드 롤백을 모두 시험한다. **X-F3의 수용이 실효적으로 미완료**다.

**R2-F2 · MED — 트리거 오류의 401 변환 순서가 기존 멱등 복구와 충돌한다.**

- **근거:** `design/DESIGN-v2.md:152`, `:153`, `:232`, `:239`; `code-2cf9c1e/relay/src/index.ts:257`, `:319`, `:323`, `:326`.
- **반례:** 동일 이벤트의 요청 A·B가 모두 최초 조회에서 “없음”을 읽는다 → A가 적재된다 → 차단 행이 커밋된다 → B의 INSERT가 차단 트리거에 걸린다. 이때 오류를 즉시 401로 변환하면, **이미 적재된 동일 이벤트를 200으로 확정하는 기존 catch 복구를 건너뛴다.**
- BEFORE INSERT 차단이 발화하면 UNIQUE 오류가 발생할 것이라는 전제에도 기대면 안 된다. 기존 코드 그대로라면 재조회 일치 시 200, 불일치·부재 시 재던지기로 500이다.
- **고칠 방향:** catch 처리 순서를 명시한다. 재조회 동일 해시 → 200, 다른 해시 → 422, 행 없음+차단 오류 → 401, 그 밖의 오류 → 기존 실패 처리. T5·T12를 결합한 경합 시험이 필요하다. 기존의 “멱등 200에 verdict 없음”과는 **별개의 새 충돌**이다.

**R2-F3 · MED — 서명기 기록 부재를 “도용 확정”으로 보는 새 주장은 성립하지 않는다.**

- **근거:** `design/DESIGN-v2.md:187`, `:193`, `:194`; `code-2cf9c1e/agora/signer.py:210`; `code-2cf9c1e/agora/core.py:78`, `:80`, `:83`.
- **틀린 점:** 새 기록을 설치하기 전에 정상 서명한 글에는 기록이 없다. v2가 언급하는 기존 네 글도 새 서명기 기록에는 자동으로 생기지 않는다. 단순 append 명세에는 기록의 영속화 완료, 기록 실패 시 서명 중단, 기록 유실·구버전 실행의 처리도 없다.
- 또한 서명은 `before_write`보다 먼저다. 기록 일치는 **로컬 서명 사실**의 증거이지 게시 완료나 게시 주체의 증거까지는 아니다.
- **고칠 방향:** 증거가 완전한 적용 구간과 초기 대조 기준을 정의하고, 영속 기록 성공 후에만 서명하도록 한다. 구간 밖·기록 손상·구버전 사용은 계속 “출처 미확정”으로 남긴다. C-F4의 오탐 완화는 반영됐지만, 선택 기능에서 확정 판정을 다시 과장했다.

**R2-F4 · MED — 증분 탐지의 커서와 미해소 경보를 함께 보존하는 계약이 없다.**

- **근거:** `design/DESIGN-v2.md:190`, `:199`, `:201`.
- **틀린 점:** 2단계는 마지막 seq 이후만 읽고, 미확정 목록이 비면 경보를 해제한다. 그런데 **이전 주기의 미해소 항목을 다음 주기에 유지하는 상태**가 명세에 없다. seq=100에서 미확정 글을 발견하고 커서를 100으로 전진시킨 뒤, 다음 조회가 빈 결과이면 해당 글을 다시 보지 않는다. 현재 주기 결과만으로 목록을 만들면 미해소 경보가 사라진다.
- **고칠 방향:** 릴레이별 커서와 미해소 사건 목록을 분리해 영속 보존한다. 사건 기록을 완료한 뒤 커서를 전진시키고, 사람의 해소 기록이 있어야 항목을 제거한다. “발견 직후 재시작 → 다음 페이지 비어 있음”을 T17에 추가한다. C-F3의 전체 원장 조회 개선에서 **새로 생긴 증분 처리 공백**이다.

**R2-F5 · MED — 시험 릴레이 종료·탐지·원격 검증의 순서가 서로 맞지 않는다.**

- **근거:** `design/DESIGN-v2.md:182`, `:184`, `:211`, `:213`, `:243`; `code-2cf9c1e/relay/wrangler.next.jsonc:5`, `:15`; `code-2cf9c1e/relay/src/index.ts:624`.
- **틀린 점:** 권고대로 1b에서 공개 주소를 끄면, 탐지기가 정상으로 요구하는 **애플리케이션의 “그런 참가자가 없다” 404**를 확인할 수 없다. 이어지는 단계 3·T16의 원격 HTTP 차단 시험에도 접근 경로가 없다. 다시 켜는 시점·보호 조건·시험 후 종료 절차가 빠져 있다.
- **고칠 방향:** 시험 릴레이를 “공개 운영/의도적 종료/검증 중”으로 구분하고 각각의 탐지 기준을 정한다. 보호된 접근 경로 또는 한시적 재개 절차를 명시하고, 재개 전 차단 설치와 시험 후 종료 확인을 포함한다. 단순 GET 실패를 종료 성공으로 간주해서도 안 된다.

**R2-F6 · MED — 설정값 방식의 “경합 없음”은 잘못된 비교다.**

- **근거:** `design/DESIGN-v2.md:78`, `:80`, `:114`, `:133`; `code-2cf9c1e/relay/src/index.ts:230`, `:275`, `:312`.
- **틀린 점:** 설정이 요청 동안 고정이라는 사실은 **요청 내부의 일관성**만 보장한다. 구설정으로 검사를 통과한 진행 중 요청을 새 배포가 차단한다는 보장은 아니다. 기존 코드에는 검사와 INSERT 사이에 비동기 작업이 있고, 설정값 방식에는 DB에서 최종 차단하는 장치가 없다.
- **고칠 방향:** 배포 전 시작한 요청의 완료를 허용하는 계약인지 명시하거나, 요청 배출·쓰기 중단·DB 차단을 추가한다. 이를 반영해 “우리 한 건이면 더 안전”이라는 권고를 재평가한다. **X-Q5b의 채택 근거가 불완전**하다.

**R2-F7 · LOW — `speak_due=[]`만으로 은퇴 상주의 쓰기 시도가 멈추지 않는다.**

- **근거:** `design/DESIGN-v2.md:156`, `:238`; `code-2cf9c1e/agora/resident.py:316`, `:337`, `:347`.
- **틀린 점:** 상주는 `speak_due`뿐 아니라 **미응답 replies**도 후보에 넣고, 별도 reply 작업을 만든다. `retired` 알림을 읽어 중단하는 경로는 없다. 새 답글이 오면 다시 깨어나 차단된 쓰기를 시도할 수 있다.
- **고칠 방향:** 클라이언트 무변경을 유지하려면 은퇴 id의 자동 발신 후보인 replies도 처리하거나, 운영 절차에서 상주를 정지한다. 미응답 답글이 있는 상태로 T11을 확장한다. **X-F7은 부분 반영**이다.

[논쟁점]

**R1 — 처분표 반영 판정**

| 처분 항목 | 판정 및 반영 근거 |
|---|---|
| C-F2·C-F6·C-Q5 | 이벤트·체크포인트의 DB 집행과 롤백 보호는 반영됨. `design/DESIGN-v2.md:130`, `:136`, `:142`, `:212`, `:242`. 등록 예외와 응답 경합은 R2-F1·F2에 남음. |
| C-F3·C-F4·X-F4 | 페이지 순회·body 파싱·캐시 한계·자동 은퇴 철회·단일 원장 규칙은 반영됨. `design/DESIGN-v2.md:176`, `:181`, `:184`, `:186`, `:190`. 새 확정 판정·증분 상태 문제는 R2-F3·F4. |
| C-F5·X-F1 | 고정 입력의 판정 불변으로 범위 축소, 쓰기 영향과 배포 게이트 반영. `design/DESIGN-v2.md:35`, `:36`, `:235`, `:240`. |
| C-F7 | 예산 소진·상주 억제·abort 한계 반영. `design/DESIGN-v2.md:50`, `:51`, `:57`. |
| C-F8·X-F5 | 위험 수용·세 시각 구분·선례의 한계 반영. `design/DESIGN-v2.md:23`, `:24`, `:25`, `:26`. |
| C-F9·C-Q5b·C-Q7 | 명부 해시 정정, 명부 동기화와 클라이언트 교체 구분, 고정 now·기존 멱등 결함 기록 반영. `design/SURVEY.md:36`, `:108`; `design/DESIGN-v2.md:87`, `:228`, `:264`. |
| X-F2·X-F3 | 두 config·D1 및 마이그레이션 순서는 반영. `design/DESIGN-v2.md:166`, `:212`, `:213`, `:214`. 실제 선점 방지·종료 후 이행은 R2-F1·F5로 미완료. |
| X-F6·X-Q5 | 임시 대응 후보와 미실측 한계 반영. `design/DESIGN-v2.md:94`, `:97`, `:219`. |
| X-F7·X-Q5b | 문구는 반영됐으나 해결·권고 근거가 불충분. R2-F7·F6 참조. |
| X-F8·X-F9 | 정오표와 시험 항목 추가 반영. `design/DESIGN-v2.md:228`, `:232`, `:237`, `:238`, `:329`. 추가 시험이 위의 새 반례까지 포괄하지는 않음. |

**C-F1의 LOW 반박은 이 설계의 보호 목표에 한정하면 타당하다.** BOM 변형은 다른 지문을 만들지만, 기존 우리 id의 PK와 서명자 principal 결박을 우회하지 않는다(`code-2cf9c1e/relay/src/index.ts:166`, `:239`, `:242`). 신규 id 등록은 원래 열려 있다. 따라서 같은 사유로 HIGH를 반복하지 않는다. 인코딩 결함 자체는 남아 있으며, 이는 `code-2cf9c1e/relay/src/lib/sshsig.ts:20`, `:119`, `:135`에서 확인된다.

**R2 — 중심안의 보장 범위**

- **판정 분리:** 명부 렌더·조회표·리듀서 입력을 그대로 유지한다면 성립한다. 확인 경로는 `code-2cf9c1e/relay/src/lib/roster.ts:28`, `:41`, `:55`, `:91`; `code-2cf9c1e/relay/src/lib/store.ts:57`, `:110`; `code-2cf9c1e/relay/src/lib/sshsig.ts:215`다. 다만 “구조적으로 누수 불가능”보다는 “공유 구조체를 통한 누수 경로 제거”가 정확하다.
- **경합 제거:** 같은 D1에서 차단 커밋 뒤 실행되는 이벤트 INSERT·체크포인트 UPSERT의 적재 차단은 타당하다. **응답의 멱등성까지 자동으로 해결되지는 않는다.**
- **롤백:** 기존 코드의 실제 쓰기문이 트리거 대상이므로 이벤트·체크포인트 차단은 유지된다(`code-2cf9c1e/relay/src/index.ts:313`, `:760`). 미등록 참가자 등록에는 적용되지 않는다.
- **UPDATE 범위:** SQL은 이벤트 INSERT와 체크포인트 INSERT/UPDATE, 총 세 트리거다. 배포 코드에 이벤트 UPDATE 경로는 없어 해당 누락을 결함으로 보지는 않는다. 비교표의 “트리거 2”는 정정해야 한다(`design/DESIGN-v2.md:118`, `:136`, `:139`, `:142`).
- **서버 참고 판정:** 저장된 이벤트의 POST verdict·GET valid를 차단 상태로 다시 계산하지 않는 조건이 필요하다(`code-2cf9c1e/relay/src/index.ts:338`, `:354`, `:493`). 신규 요청의 admission 오류와 이 판정을 계약 문장에서 구분해야 한다(`design/DESIGN-v2.md:152`, `:161`).

**R3·R4:** 두 릴레이를 명시한 것은 개선이다. 그러나 차단 효력은 D1별 커밋 시점이며, 두 곳 완료 전에는 전역 차단 완료로 보고하면 안 된다. 탐지기도 페이지·캐시 누락과 정상 발신 오탐을 인정하도록 개선됐지만, R2-F3~F5 때문에 아직 “완전·확정”이라는 표현은 이르다.

**R6 — 모든 기준에서 우월한 대안은 확인하지 못했다.** 다만 “우리 id 한 건 고정” 분기에서는 **고정 id 조건을 둔 DB 트리거 + 앱 오류 처리**도 비교할 가치가 있다. 별도 정책 표 없이 DB 집행·롤백 보호를 유지할 수 있어 설정값 방식의 경합 약점보다 유리하다. 대신 두 D1 마이그레이션과 대상 변경 시 트리거 교체가 필요하므로, 일반화에는 (a2)가 낫다. 현재 비교표는 이 절충안을 비교하지 않는다(`design/DESIGN-v2.md:77`, `:109`, `:136`).

[다음 단계 조언]

1. **등록까지 DB 차단 범위에 포함하고, catch의 재조회 우선순위를 확정**한다.
2. 탐지기의 **미해소 사건 보존·커서 전진·서명 기록 적용 구간**을 명세로 고정한다.
3. 시험 릴레이 종료/재개 절차와 상주 reply 경로를 보완한다.
4. 구현 검증에는 미등록 id 등록 경합·구코드 등록·동일 이벤트 두 요청 사이 차단·탐지기 재시작·기록 도입 전 정상 글을 추가한다. 원격 D1 지원과 오류 형태는 현재 자료만으로 확정할 수 없으므로 기존 원격 게이트를 유지한다.

```json
{
  "verdict": "REVISE",
  "findings": [
    {
      "id": "R2-F1",
      "severity": "HIGH",
      "evidence": "design/DESIGN-v2.md:147; design/DESIGN-v2.md:154; design/DESIGN-v2.md:167; code-2cf9c1e/relay/src/index.ts:157; code-2cf9c1e/relay/src/index.ts:178",
      "claim": "미등록 id는 byId 차단 분기를 우회하며 participants 트리거도 없어 차단 행만으로 등록 선점을 막지 못한다.",
      "fix": "등록 여부와 독립적인 앱 검사와 participants BEFORE INSERT 차단을 추가하고 미등록·경합·롤백을 시험한다."
    },
    {
      "id": "R2-F2",
      "severity": "MED",
      "evidence": "design/DESIGN-v2.md:153; design/DESIGN-v2.md:232; code-2cf9c1e/relay/src/index.ts:319; code-2cf9c1e/relay/src/index.ts:326",
      "claim": "차단 트리거 오류를 즉시 401로 변환하면 다른 요청이 이미 적재한 동일 이벤트의 멱등 200 복구와 충돌한다.",
      "fix": "catch에서 재조회 동일 해시 200, 다른 해시 422, 부재와 차단 오류 401 순서를 명시하고 결합 경합 시험을 추가한다."
    },
    {
      "id": "R2-F3",
      "severity": "MED",
      "evidence": "design/DESIGN-v2.md:187; design/DESIGN-v2.md:194; code-2cf9c1e/agora/signer.py:210; code-2cf9c1e/agora/core.py:78; code-2cf9c1e/agora/core.py:80",
      "claim": "서명 기록 도입 전 정상 글과 기록 유실을 구분하지 않고 기록 부재를 도용 확정으로 판정한다.",
      "fix": "증거 적용 구간과 초기 대조 기준, 영속 기록 후 서명, 기록 불완전 시 미확정 분류를 명시한다."
    },
    {
      "id": "R2-F4",
      "severity": "MED",
      "evidence": "design/DESIGN-v2.md:190; design/DESIGN-v2.md:199; design/DESIGN-v2.md:201",
      "claim": "증분 조회 커서와 별개인 미해소 사건 보존 계약이 없어 다음 빈 조회에서 경보가 사라질 수 있다.",
      "fix": "릴레이별 커서와 미해소 사건을 영속 보존하고 사건 기록 완료 후 커서를 전진시키며 명시적 해소만 허용한다."
    },
    {
      "id": "R2-F5",
      "severity": "MED",
      "evidence": "design/DESIGN-v2.md:182; design/DESIGN-v2.md:211; design/DESIGN-v2.md:213; design/DESIGN-v2.md:243; code-2cf9c1e/relay/wrangler.next.jsonc:15",
      "claim": "시험 주소 종료 권고가 애플리케이션 404를 요구하는 탐지 및 후속 원격 HTTP 시험 절차와 연결되지 않는다.",
      "fix": "운영·의도적 종료·검증 중 상태별 탐지 기준과 보호된 시험 접근 또는 한시적 재개·종료 절차를 정의한다."
    },
    {
      "id": "R2-F6",
      "severity": "MED",
      "evidence": "design/DESIGN-v2.md:78; design/DESIGN-v2.md:80; design/DESIGN-v2.md:114; code-2cf9c1e/relay/src/index.ts:275; code-2cf9c1e/relay/src/index.ts:312",
      "claim": "요청 동안 설정이 고정이라는 이유만으로 배포 전 시작한 요청의 검사와 INSERT 사이 경합이 없다고 판단한다.",
      "fix": "진행 중 요청을 포함한 효력 발생 계약을 정하고 필요하면 요청 배출 또는 DB 집행을 추가한 뒤 비교표와 권고를 수정한다."
    },
    {
      "id": "R2-F7",
      "severity": "LOW",
      "evidence": "design/DESIGN-v2.md:156; design/DESIGN-v2.md:238; code-2cf9c1e/agora/resident.py:316; code-2cf9c1e/agora/resident.py:347",
      "claim": "speak_due를 비워도 미응답 replies가 상주의 reply 작업을 생성하므로 은퇴 뒤 쓰기 시도 소음이 남는다.",
      "fix": "reply 후보도 처리하거나 상주 정지를 운영 절차에 포함하고 미응답 답글을 가진 은퇴 참가자로 시험한다."
    }
  ],
  "checked": [
    "design/DISPOSITION-r1.md:11",
    "design/DISPOSITION-r1.md:12",
    "design/DISPOSITION-r1.md:30",
    "design/DISPOSITION-r1.md:34",
    "design/DESIGN-v2.md:130",
    "design/DESIGN-v2.md:142",
    "design/DESIGN-v2.md:160",
    "design/DESIGN-v2.md:221",
    "design/SURVEY.md:36",
    "code-2cf9c1e/relay/src/index.ts:154",
    "code-2cf9c1e/relay/src/index.ts:178",
    "code-2cf9c1e/relay/src/index.ts:239",
    "code-2cf9c1e/relay/src/index.ts:257",
    "code-2cf9c1e/relay/src/index.ts:313",
    "code-2cf9c1e/relay/src/index.ts:323",
    "code-2cf9c1e/relay/src/index.ts:354",
    "code-2cf9c1e/relay/src/index.ts:493",
    "code-2cf9c1e/relay/src/index.ts:624",
    "code-2cf9c1e/relay/src/index.ts:760",
    "code-2cf9c1e/relay/src/lib/roster.ts:28",
    "code-2cf9c1e/relay/src/lib/roster.ts:91",
    "code-2cf9c1e/relay/src/lib/store.ts:110",
    "code-2cf9c1e/relay/src/lib/sshsig.ts:119",
    "code-2cf9c1e/relay/src/lib/sshsig.ts:215",
    "code-2cf9c1e/relay/migrations/0001_init.sql:30",
    "code-2cf9c1e/relay/scripts/run-local.py:46",
    "code-2cf9c1e/relay/wrangler.jsonc:14",
    "code-2cf9c1e/relay/wrangler.next.jsonc:21",
    "code-2cf9c1e/agora/core.py:248",
    "code-2cf9c1e/agora/core.py:265",
    "code-2cf9c1e/agora/sign.py:165",
    "code-2cf9c1e/agora/resident.py:316",
    "exp-worker/retired:1",
    "exp-worker/hist:1",
    "exp-worker/two:2"
  ]
}
```

(종료 rc=0)
