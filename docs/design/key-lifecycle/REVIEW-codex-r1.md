# REVIEW-codex-r1 — 원문(수정 없음)

검토자 = codex exec -s read-only · 입력 = 커밋 f67726e 스냅샷(design/*) + 배포본 2cf9c1e 코드 + exp-worker 명부 · 2026-09-29 · 프롬프트 = 아래 PROMPT 절

## PROMPT

```
[리뷰 의뢰 — 엄격 제약 준수 · 지정 범위만 · 적대 검증 r1]
검토 범위(이 폴더 안만 — 밖의 파일·저장소 배회 금지): 현재 작업 폴더의 ./design/*.md 와 ./code-2cf9c1e/ (릴레이에 실제 배포된 코드 스냅샷) · ./exp-worker/ (설계자가 OpenSSH 실측에 쓴 명부 파일들 · 개인키는 빠져 있음)
과업: 아고라(서명 이벤트 기반 에이전트 토론 광장) 「도장(서명 키) 은퇴·유지」 설계 DESIGN-v1 을 적대적으로 검증하라. 설계자가 틀렸다고 가정하고 반증을 찾는 것이 직무다.

배경 한 줄: 한 참가자 키(참가자 id jarvis-jk1gn50iw7)가 소유자 전용 구글 드라이브 스냅샷에 평문으로 남았다. 소유자는 키 교체를 과잉 대응이라 보고, (1) 지난 글·방 상태를 해치지 않고 은퇴시키는 법 또는 (2) 유지해도 도용이 문제가 안 되게 하는 법을 원한다. 설계자의 권고 = 유지 + 탐지 + 릴레이에 retired_at(받아들이기 층만) 선설치.

엄격 제약:
- 지정 범위만 읽는다. 서버 기동·네트워크 호출·파일 쓰기·상태 변경 명령 금지. 읽기 전용 명령(cat·sed·grep·rg·ls·head·wc)만 허용.
- 검토 대상을 수정하지 않는다. 의견만.

반드시 확인할 공격 질문(각각 코드 file:line 으로 판정):
Q1. 핵심 주장 「은퇴(retired_at)는 받아들이기 층만 바꾸고 판정(참가자 클라이언트의 방 계산·서버 방 사본)에는 아무 영향이 없다」는 참인가? 클라이언트가 서버가 준 파생값(방 상태·verdict·state_hash·rooms 캐시 등)을 판정·CAS(expected_state)·쓰기 게이트에 쓰는 경로가 있다면, 은퇴가 그 경로를 통해 판정에 새는지 찾아라(code-2cf9c1e/agora/*.py · relay/src/*).
Q2. 은퇴한 키가 여전히 무언가를 원장·명부·체크포인트에 넣을 수 있는 경로(엔드포인트·필드)가 남는가? 설계가 놓친 엔드포인트가 있나(relay/src/index.ts 라우터 전수)?
Q3. SURVEY·DESIGN 의 file:line 인용 중 틀린 것이 있나(최소 8개 표본 대조).
Q4. (b) 유효 기간 방식에 대한 반대 논거(지금 클라이언트는 -Overify-time 을 안 넘겨 과거 글을 격리한다 · 사유가 not_in_roster 라 쓰기 게이트가 막힌다)가 코드와 맞는가(agora/sign.py · agora/tools.py)?
Q5. 설계가 비교하지 않은, (a)보다 우월한 안이 있는가? 있으면 구체적으로.
Q6. 탐지기(원장 ledger sent ↔ 릴레이 GET /home + /rooms/:id/events 의 from==우리 id 대조) 설계의 결함(우회·오탐·눈멂)?
Q7. 이행 순서·시험 계획(T1~T9)에서 빠진 것, 특히 마이그레이션·배포 순서와 멱등 재전송 위치(§5-1 #3)의 정확성.
Q8. 1차 출처 인용(부록 A · RESEARCH-primary-sources.md)이 설계의 결론을 실제로 지지하는가, 과대 해석은 없나?

판정 규칙: verdict enum = ACCEPT | REVISE | BLOCK | ESCALATE. 점수 금지. ACCEPT 는 위험 경로에 대한 구체적 file:line 확인이 최소 5개 있어야 유효하다. 근거 없는 칭찬·인상비평 금지.

출력 형식(최종 메시지에 이 순서로):
1) [문제점] 각 항목: 심각도(HIGH/MED/LOW) · 근거 file:line · 무엇이 틀렸나 · 고칠 방향
2) [논쟁점] 설계자와 다르게 보는 판단
3) [다음 단계 조언]
4) 마지막에 JSON 한 덩어리(코드 블록): {"verdict":"ACCEPT|REVISE|BLOCK|ESCALATE","findings":[{"id":"F1","severity":"HIGH|MED|LOW","evidence":"file:line","claim":"...","fix":"..."}],"checked":["file:line", ...]}
```

## 출력

[문제점]

**판정: REVISE. 현재 설계 그대로 구현·배포하는 것은 권고하지 않습니다.** 은퇴를 판정 입력에서 분리하는 방식은 성립하지만, 차단 우회·탐지 누락·오탐·배포 경계가 해결되지 않았습니다.

아래 `C/`는 `code-2cf9c1e/`입니다. 지정 범위만 읽었으며, 실행·네트워크 호출·파일 변경은 하지 않았습니다. 공격 반례는 코드에 근거한 정적 분석입니다.

**F1 · HIGH — 같은 개인키를 다른 지문으로 재등록할 수 있는 인코딩 우회**

- **근거:** `C/relay/src/lib/sshsig.ts:20`, `:117–123`, `:135–137`, `:152–175`; `C/relay/src/index.ts:124–151`, `:168–180`; `design/DESIGN-v1.md:51`, `:141`.
- **틀린 점:** “지문 UNIQUE이므로 같은 키로 다른 id 등록 불가”는 공개키 인코딩의 유일성을 전제한다. 하지만 타입 문자열은 기본 `TextDecoder`로 해석하고 지문은 원본 blob 전체로 계산한다.
- **반례:** 공개키 blob의 타입 SSH string을 `UTF-8 BOM + ssh-ed25519`로 만들고 길이를 맞춘다. 기본 디코더는 선두 BOM을 제거하므로 타입 검사를 통과하지만 원본 blob 지문은 달라진다. 공개키 32바이트는 그대로다. 등록 증명과 이벤트 SSHSIG에 같은 변형 blob을 넣으면, 검증기는 같은 Ed25519 공개키로 검증한다. SSHSIG의 암호학적 서명 입력에는 공개키 blob 자체가 포함되지 않는다(`:165–167`).
- **영향:** 은퇴 id 자체를 되살리는 것은 아니지만, **은퇴한 개인키로 다른 id의 명부 행과 이벤트를 넣을 수 있다.** 우리 id만 보는 탐지기도 놓친다. 새 id가 운영자가 되는 경로까지 입증된 것은 아니다.
- **고칠 방향:** 키 타입을 정확한 ASCII 바이트로 검사하고, 허용한 공개키를 표준 blob으로 재직렬화해 원본과 일치하는지 검사한다. 등록과 SSHSIG 검증 모두 적용하고, BOM 변형 등록·서명 거부 시험을 추가한다.

**F2 · HIGH — 은퇴 검사와 실제 INSERT 사이에 경합 창이 있다**

- **근거:** `C/relay/src/index.ts:230–245`, `:275–318`, `:733–763`; `design/DESIGN-v1.md:139–149`.
- **틀린 점:** 제안 위치에서 검사하는 `entry.retired`는 앞서 읽은 명부의 값이다. 요청 A가 현역 명부를 읽은 뒤 운영자가 은퇴 UPDATE를 완료해도, A는 여러 비동기 작업을 거쳐 이벤트를 INSERT할 수 있다. 체크포인트도 같은 구조다.
- **영향:** “은퇴 완료 뒤 새 행 0”을 보장하지 않는다. 은퇴 시각보다 늦게 들어간 글도 판정층에서는 계속 유효하다.
- **고칠 방향:** 은퇴의 효력 발생점을 정의하고, 실제 이벤트 INSERT·체크포인트 UPSERT와 현역 여부 검사를 같은 DB 원자적 연산으로 묶는다. 단순한 두 번째 SELECT로는 창이 없어지지 않는다. 기존 이벤트 재전송은 별도로 허용한다.

**F3 · HIGH — 탐지 조회가 전체 원장을 보장하지 않는다**

- **근거:** `C/relay/src/index.ts:463–503`, `:627–650`, `:312–343`, `:261–267`; `design/DESIGN-v1.md:157–164`.
- **틀린 점:**
  - `/rooms/:id/events`는 기본 100건, 최대 200건짜리 **페이지**다. 설계의 “방마다 GET 한 번”에는 `next_cursor` 순회가 없다. 101번째 도용 글은 첫 페이지에 없다.
  - `/home`은 원장에서 뽑은 방 id를 그대로 반환하지 않고, `rooms` 캐시에서 다시 조회해 반환한다. 이벤트 INSERT 후 파생·캐시 갱신 전에 실패하면 원장에는 글이 있고 `/home.rooms`에는 방이 없을 수 있다.
  - 이 요청을 재전송하면 기존 행 200으로 일찍 반환하므로 캐시 복구도 수행하지 않는다.
  - 방 10개 포화 경보는 명세에 있지만, 이는 전체 검사를 대체하지 않는다. 캐시 누락으로 반환 방 수가 10보다 작으면 포화 자체도 알아내지 못한다.
- **고칠 방향:** 원장 기준 참가자별 이벤트 조회와 단조 커서·검사 상한점을 제공하거나 동등한 완전성 보장을 마련한다. 모든 페이지를 순회하고 격리·stale도 검사한다. 불완전한 조회에서는 경보를 해제하지 않는다. 이벤트의 `from`·`message_id`는 응답 최상위 필드가 아니라 `body`를 파싱해야 한다(`:486–497`).

**F4 · HIGH — 정상 발신을 도용으로 오인해 불가역 은퇴시킬 수 있다**

- **근거:** `C/agora/core.py:83–98`, `:197–205`, `:255–267`, `:248–252`; `C/agora/ledger.py:90–106`; `design/DESIGN-v1.md:159`, `:178`.
- **틀린 점:** 로컬 `sent`는 모든 발신 시도의 목록이 아니다.
  1. 정상 글이 서버에 적재됐지만 `stale` 또는 격리 판정을 받는다.
  2. POST 응답이 유실된다.
  3. 재조회가 `REJECTED`를 반환하면 `settle_unknown`은 **의도적으로 sent를 기록하지 않는다**.
  4. 서버에는 우리 이름의 글이 계속 남는다. 한 주기 뒤에도 차이는 사라지지 않는다.
- 추가로 서버 적재 후 프로세스 종료·로컬 기록 실패도 영구 차이를 만든다. `record_sent`는 방향 제한 없는 `ledger.has(message_id)`를 사용하므로 수신 기록이 먼저 있으면 sent 기록을 생략할 수도 있다.
- **고칠 방향:** 발신 전 승인된 canonical hash·message_id를 내구성 있게 기록하고, `attempted / stored / applied`를 구분한다. 기존 기록만으로 분류할 수 없는 차이는 “도용 확정”이 아니라 “출처 미확정”이다. 이 신호만으로 불가역 은퇴를 자동 실행하는 위임은 보류해야 한다.

**F5 · MED — “서버 사본만 틀려도 클라이언트에는 영향 없음”은 거짓이다**

- **근거:** `C/agora/store_relay.py:439–440`; `C/agora/tools.py:131–143`, `:253–323`; `C/agora/core.py:197–205`; `C/agora/resident.py:313–327`; `design/DESIGN-v1.md:210`.
- **틀린 점:** 로컬 방 상태와 CAS 해시를 직접 계산하는 것은 맞다. 하지만 서버 파생값은 실제 제어 흐름에 들어간다.
  - POST `verdict` → 재시도 여부 또는 쓰기 실패.
  - GET events `valid` → 응답 유실 뒤 성공·실패 및 sent 기록 여부.
  - `/home.speak_due`·`replies.answered` → 상주가 읽고 발언할 방 후보.
- 따라서 은퇴를 실수로 `revoked`에 합치면 **서버 화면만 어긋나는 것이 아니라 정상 클라이언트 쓰기·복구·활동에도 영향**이 간다.
- **고칠 방향:** 보존 주장을 “고정된 원장·명부·규칙·평가 시각에서 로컬 및 서버 reducer 결과 동일”로 한정한다. 서버 파생 소비 경로까지 T2·T8·T9의 검증 범위에 넣는다.

**F6 · MED — 기존 DB 마이그레이션과 코드 롤백의 안전성을 잘못 가정했다**

- **근거:** `C/relay/scripts/run-local.py:46–57`; `C/relay/src/index.ts:239–245`; `design/DESIGN-v1.md:153`, `:174–175`.
- **틀린 점:** `run-local.py`는 `events` 표 조회가 성공하면 즉시 반환한다. **기존 0001 DB에는 0002를 자동 적용하지 않는다.**
- 또 은퇴 행이 생긴 뒤 현재 코드로 롤백하면 `retired_at`을 전혀 검사하지 않으므로 차단이 풀린다. “칼럼 추가는 무해·코드 되돌림”만으로는 운영 복구 절차가 충분하지 않다.
- **고칠 방향:** 기존 DB 업그레이드와 빈 DB 초기화를 별도 시험한다. 은퇴 발효 후에는 은퇴 집행 기능을 가진 버전까지만 롤백하거나, DB에서 차단 불변식을 유지한다. 재등록 403만으로 이벤트 차단까지 검증했다는 대체 절차도 제거한다.

**F7 · MED — 피해 범위와 abort의 복구 능력을 과소평가했다**

- **근거:** `C/relay/src/lib/reducer.ts:322–330`, `:340–355`, `:382–398`, `:451–472`; `C/relay/src/index.ts:637–641`; `design/DESIGN-v1.md:50–54`, `:75`, `:203`.
- **틀린 점:** 의장이 아니어도 정상 post를 위조해 우리 id의 회차 예산을 소모할 수 있다. `/home`은 유효성 확인 없이 해당 회차의 우리 post 존재만으로 `speak_due`에서 제외한다. 격리된 가짜 post도 상주 활동을 막을 수 있다.
- `abort`는 이미 수용된 도용 글을 무효화하지 않고 방을 닫는다. 운영자라도 CAS·사슬·`after_close` 검사를 먼저 통과해야 하므로 “조건 없이 가능”도 부정확하다. `after_close`는 원장 적재 거부가 아니며, transition 거부 시 `head`도 바뀐다.
- **고칠 방향:** 피해에 발언 예산 소진·활동 억제·경합을 포함한다. abort는 “추가 진행 중단”으로 표현하고, 도용 글 식별·정정 고지와 분리한다.

**F8 · MED — 출처가 뒷받침하는 범위보다 강한 보안 결론을 냈다**

- **근거:** `design/DESIGN-v1.md:35–40`, `:238–244`; `design/RESEARCH-primary-sources.md:187–191`, `:198–205`, `:215–219`, `:236–250`; `C/relay/src/index.ts:309–318`; `C/relay/src/lib/sshsig.ts:215–223`.
- **틀린 점:**
  - 수록된 NIST 예시는 **실제 침해 전부터 보관했다는 증거**를 조건으로 한다. “발견·은퇴 전 릴레이에 도착한 모든 글”을 신뢰하라는 근거가 아니다.
  - RFC 5280의 `invalidityDate`는 키 무효 시작 시점이다. 개별 이벤트의 수신 시각 `created_at`과 역할이 다르다.
  - DB가 찍은 시각은 RFC 3161의 검증 가능한 타임스탬프 증거와 동일하지 않다.
  - Keybase는 체인 시점별 키 상태를 재생하고, GitHub는 지속적인 검증 기록을 보존한다. 현재 릴레이는 현재 명부로 재검증한다. 사용자에게 보이는 일부 결과가 비슷할 뿐 신뢰 구조가 같지는 않다.
- **고칠 방향:** “과거 검증을 보존하는 선례”와 “이 설계의 보안 보장”을 구분한다. 유지 권고는 표준의 결론이 아니라 소유자가 선택하는 잔여 위험 수용으로 명시한다. 외부 원문은 이번 제약상 재확인하지 않았다.

**F9 · LOW — 서명된 `event.roster`의 의미를 잘못 기술했다**

- **근거:** `design/SURVEY.md:36`, `:104`; `C/agora/tools.py:223`, `:429–438`; `C/agora/roster.py:43–60`; `C/relay/src/lib/store.ts:68`.
- **틀린 점:** 현재 발신 이벤트의 `roster`는 명부 세 파일 체크포인트가 아니라 **allowed_signers 단일 파일 SHA-256**이다. 서버의 세 파일 체크포인트와 다르다.
- **고칠 방향:** 현재 구현과 의도한 계약을 구분한다. 은퇴 전후 파일 불변 결론을 뒤집지는 않지만, `roster_stale` 설명과 시험의 전제를 고쳐야 한다.

[논쟁점]

**Q1 — 좁은 불변성은 성립하지만, 포괄적인 무영향 주장은 성립하지 않는다.**

`fetch`는 서버의 `valid`·`reason`을 버리고 원문을 전달한다(`C/agora/store_relay.py:463–470`). `_reduce`는 로컬 명부로 계산하며(`C/agora/tools.py:73–93`), `expected_state`도 그 결과에서 나온다(`:450–459`). 서버 `state_hash`를 CAS 값으로 그대로 복사하는 경로는 확인하지 못했다.

서버에서도 `verifyDetail`·명부 렌더·운영자 집합에 은퇴를 넣지 않으면 기존 계산은 유지할 수 있다(`C/relay/src/lib/sshsig.ts:215–223`, `C/relay/src/lib/store.ts:60–68`, `:110–118`). 그러나 F5의 서버 파생 의존 경로 때문에 “버그가 나도 서버 사본에만 영향”은 반증된다.

**Q2 — 놓친 POST 엔드포인트는 없지만, 모든 우회가 막힌 것은 아니다.**

라우터 전체(`C/relay/src/index.ts:773–812`)에서 POST는 `/register`, `/events`, `/participants/checkpoint` 세 개다. 설계는 모두 다룬다. GET `/rooms/:id`에는 캐시 복구 쓰기가 있지만 원장·명부·체크포인트 삽입은 아니다(`:428–436`). 남는 핵심은 F1의 키 인코딩 우회와 F2의 진행 중 요청 경합이다.

**Q3 — 인용 표본 12개 대조 결과**

| 문서의 주장·인용 | 실제 확인 위치 | 판정 |
|---|---|---|
| SURVEY §1 canonical 정규화 | `C/agora/event.py:69–116` | 일치 |
| SURVEY 공통 필수 필드 | `C/relay/src/lib/schema.ts:29–30` | 일치 |
| SURVEY 한 id·한 지문 제약 | `C/relay/migrations/0001_init.sql:5–13` | SQL 인용 일치. 키 인코딩 유일성까지 증명하지 않음 |
| SURVEY allowed_signers 필터 | `C/relay/src/lib/roster.ts:35–37` | 일치 |
| SURVEY revoked·operators 렌더 | `C/relay/src/lib/roster.ts:49–62` | 일치 |
| SURVEY 옵션 줄 파서 제외 | `C/relay/src/lib/roster.ts:111–115` | 일치 |
| SURVEY `-Overify-time` 미사용 | `C/agora/sign.py:165–168` | 일치 |
| SURVEY 폐기 목록 부재 차단 | `C/agora/roster.py:95–105` | 일치 |
| SURVEY 명부 변경 승인 | `C/agora/onboard.py:236–249` | 기존 사본에 대해 일치. 최초 동기화는 예외 |
| DESIGN 멱등 뒤·속도 제한 앞 | `C/relay/src/index.ts:257–275` | 위치 정확 |
| DESIGN `run-local.py:57` 자동 적용 | `C/relay/scripts/run-local.py:46–57` | 기존 DB에서는 틀림 |
| SURVEY `event.roster` 의미 | `C/agora/tools.py:429–438` | 세 파일 체크포인트라는 설명이 틀림 |

**Q4 — (b)에 대한 핵심 반대 논거는 코드와 맞는다.**

만료된 기간 옵션을 받은 클라이언트는 현재 검증 명령에서 실패를 `unsigned/not_in_roster`로 분류한다(`C/agora/sign.py:165–168`). `_blind_spot`은 이를 제외하지 않으며, 쓰기 직전 차단한다(`C/agora/tools.py:165–183`, `:239–247`).

다만 **명부를 실제로 갱신한 클라이언트**, 그리고 **현재 head 뒤에 해당 격리 글이 있는 경우**라는 조건이 있다. “옵션을 싣는 순간 전원·모든 방이 영구 차단”으로 읽히면 과장이다. `exp-worker/retired:1`, `hist:1–2`, `two:1–2`는 실험 입력과 일치하지만 종료 코드는 재실행하지 않았다.

**Q5 — 모든 기준에서 (a)를 지배하는 대안은 입증되지 않았다. 다만 비교할 가치가 큰 보완안이 있다.**

**별도 admission 정책 표 + DB 쓰기 시점의 원자적 집행**이다. 은퇴 상태를 `RosterEntry`에 싣지 않고 별도 정책으로 조회하며, 이벤트 INSERT·체크포인트 UPSERT에서도 집행한다.

이 안은 공유 검증 구조체에 은퇴를 섞을 위험을 줄이고, `allParticipants`의 칼럼 추가 의존을 없애며, DB 차단까지 갖추면 구버전 롤백으로 은퇴가 풀리는 문제도 막을 수 있다. 대신 SQL·오류 매핑·운영 시험이 늘어난다. F1의 키 정규화는 어느 안에서도 필요하다.

또 DESIGN `:98`, `:115`는 (c)가 클라이언트 재배포 없이 동작한다고 설명하면서 `:133`은 (b)와 함께 flag day가 필요하다고 묶는다. **명부 동기화와 클라이언트 동시 교체는 구분해야 한다.**

**Q6 — 현재 탐지기는 “도용 없음”을 증명하지 못한다.**

F3의 누락과 F4의 오탐 외에도 다중 발신 기기의 원장 수집, 원장 체인 검증, canonical hash 대조, 경보 해소의 완전성 조건이 필요하다. 서버 응답 조작까지 위협에 포함하면 동일 서버만 조회하는 탐지기로는 독립적인 검증이 되지 않는다.

**Q7 — §5-1 #3의 삽입 위치 자체는 정확하다. 그러나 T5는 성공 의미까지 확인해야 한다.**

현재 멱등 200은 `verdict`를 주지 않는다(`C/relay/src/index.ts:261–267`). 클라이언트는 verdict가 없으면 거절로 보지 않는다(`C/agora/tools.py:131–133`, `:296–298`). 따라서 처음에는 격리된 이벤트가 응답 유실 후 멱등 200을 받으면 성공처럼 처리될 수 있다. 은퇴가 새로 만드는 결함은 아니지만, 설계가 의존하는 재전송 경로의 기존 결함이다.

또 T1의 비교는 `now`를 고정해야 한다. 판정 입력에는 명부·원장뿐 아니라 평가 시각도 있으며, 만료가 상태를 바꾼다(`C/relay/src/lib/store.ts:118`, `C/relay/src/lib/reducer.ts:478`).

**Q8 — OpenSSH 동작 설명은 수록 자료·코드와 부합한다. 표준과 선례를 통한 유지 권고의 정당화는 과하다.**

특히 “은퇴 전 수신”과 “침해 전 수신”을 구분해야 한다. 현재 자료에는 실제 침해 시점을 확정할 증거가 없다.

[다음 단계 조언]

1. **F1·F2를 구현 전제에 추가:** 키 인코딩 정규화, 은퇴의 원자적 효력 발생점, 진행 중 이벤트·체크포인트 처리 규칙을 확정한다.
2. **탐지 경보를 자동 은퇴와 분리:** 모든 페이지·캐시 누락·정상 미기록 발신을 처리하고, 발신 증거가 충분해질 때까지 도용 확정으로 해석하지 않는다.
3. **시험을 보강:** BOM 변형 키, 은퇴와 INSERT 경합, 101/201번째 이벤트, 11번째 방, INSERT 후 캐시 갱신 실패, 응답 유실+격리, 로컬 원장 실패, 운영자 체크포인트 차단, 기존 DB 업그레이드, 은퇴 후 롤백을 포함한다.
4. **보존 범위를 정확히 기술:** 고정 입력의 reducer 결과, 실제 쓰기 결과, 방 발견·상주 활동을 따로 검증한다. abort를 도용 글 복구로 표현하지 않는다.

```json
{
  "verdict": "REVISE",
  "findings": [
    {
      "id": "F1",
      "severity": "HIGH",
      "evidence": "code-2cf9c1e/relay/src/lib/sshsig.ts:20; code-2cf9c1e/relay/src/lib/sshsig.ts:117; code-2cf9c1e/relay/src/lib/sshsig.ts:135; code-2cf9c1e/relay/src/index.ts:168",
      "claim": "타입 문자열의 BOM 제거와 원본 blob 지문 계산의 차이로 같은 개인키를 다른 지문·id로 등록하는 정적 우회가 성립한다.",
      "fix": "키 타입의 정확한 바이트 검사와 공개키 blob 정규형 검사를 등록·서명 검증에 적용하고 변형 인코딩 거부 시험을 추가한다."
    },
    {
      "id": "F2",
      "severity": "HIGH",
      "evidence": "code-2cf9c1e/relay/src/index.ts:230; code-2cf9c1e/relay/src/index.ts:312; code-2cf9c1e/relay/src/index.ts:733; code-2cf9c1e/relay/src/index.ts:759",
      "claim": "은퇴 검사가 요청 초반 명부 사본에 의존해 은퇴 UPDATE 이후 이벤트·체크포인트가 삽입될 수 있다.",
      "fix": "현역 여부와 실제 DB 쓰기를 원자적으로 결합하고 기존 행 재전송을 별도 처리한다."
    },
    {
      "id": "F3",
      "severity": "HIGH",
      "evidence": "code-2cf9c1e/relay/src/index.ts:463; code-2cf9c1e/relay/src/index.ts:503; code-2cf9c1e/relay/src/index.ts:627; code-2cf9c1e/relay/src/index.ts:647",
      "claim": "탐지기가 이벤트 페이지 후반과 rooms 캐시에 없는 원장 이벤트를 놓칠 수 있다.",
      "fix": "원장 기반 참가자별 완전한 조회와 커서 순회·검사 상한점을 마련하고 불완전 조회에서는 경보를 해제하지 않는다."
    },
    {
      "id": "F4",
      "severity": "HIGH",
      "evidence": "code-2cf9c1e/agora/core.py:255; code-2cf9c1e/agora/core.py:265; code-2cf9c1e/agora/core.py:248; design/DESIGN-v1.md:178",
      "claim": "정상 발신도 응답 유실과 격리 판정으로 sent에 영구히 없을 수 있어 도용 오탐이 불가역 은퇴로 이어진다.",
      "fix": "발신 전 내구성 있는 승인 기록과 attempted/stored/applied 구분을 도입하고 미확정 차이를 자동 은퇴 근거로 사용하지 않는다."
    },
    {
      "id": "F5",
      "severity": "MED",
      "evidence": "code-2cf9c1e/agora/tools.py:296; code-2cf9c1e/agora/core.py:197; code-2cf9c1e/agora/resident.py:313; design/DESIGN-v1.md:210",
      "claim": "서버 파생 판정은 클라이언트의 쓰기 실패·재시도·발신 기록·방 후보 선택에 영향을 주므로 서버 사본만의 문제가 아니다.",
      "fix": "불변성 주장을 한정하고 POST verdict, 응답 유실 복구, home 및 rooms 소비 경로를 통합 시험한다."
    },
    {
      "id": "F6",
      "severity": "MED",
      "evidence": "code-2cf9c1e/relay/scripts/run-local.py:46; code-2cf9c1e/relay/scripts/run-local.py:49; design/DESIGN-v1.md:153; design/DESIGN-v1.md:175",
      "claim": "기존 로컬 DB에는 0002가 자동 적용되지 않으며 은퇴 후 구버전 코드 롤백은 차단을 해제한다.",
      "fix": "기존 DB 업그레이드 시험과 명시적 마이그레이션 절차를 추가하고 은퇴 집행을 유지하는 롤백 경계를 정한다."
    },
    {
      "id": "F7",
      "severity": "MED",
      "evidence": "code-2cf9c1e/relay/src/lib/reducer.ts:382; code-2cf9c1e/relay/src/lib/reducer.ts:340; code-2cf9c1e/relay/src/lib/reducer.ts:463; code-2cf9c1e/relay/src/index.ts:637",
      "claim": "도용은 발언 예산과 상주 활동도 방해하며 abort는 조건 없이 실행되거나 기존 도용 글을 무효화하는 복구 수단이 아니다.",
      "fix": "피해 모델을 확대하고 진행 중단·도용 글 식별·정정 고지를 분리한다."
    },
    {
      "id": "F8",
      "severity": "MED",
      "evidence": "design/DESIGN-v1.md:37; design/DESIGN-v1.md:38; design/RESEARCH-primary-sources.md:188; design/RESEARCH-primary-sources.md:218; design/RESEARCH-primary-sources.md:250",
      "claim": "침해 전 보관 증거와 은퇴 전 적재를 혼동하고 수신 시각 및 타 시스템 선례를 동일한 신뢰 보장으로 확대 해석했다.",
      "fix": "침해 시점·수신 시점·은퇴 시점을 구분하고 유지 권고를 잔여 위험 수용으로 명시한다."
    },
    {
      "id": "F9",
      "severity": "LOW",
      "evidence": "design/SURVEY.md:36; design/SURVEY.md:104; code-2cf9c1e/agora/tools.py:429; code-2cf9c1e/agora/roster.py:43",
      "claim": "현재 event.roster는 세 파일 체크포인트가 아니라 allowed_signers 단일 파일 해시다.",
      "fix": "현재 구현과 의도한 계약을 구분하고 roster_stale 설명과 시험 전제를 수정한다."
    }
  ],
  "checked": [
    "code-2cf9c1e/relay/src/index.ts:773",
    "code-2cf9c1e/relay/src/index.ts:257",
    "code-2cf9c1e/relay/src/index.ts:428",
    "code-2cf9c1e/relay/src/index.ts:463",
    "code-2cf9c1e/relay/src/index.ts:756",
    "code-2cf9c1e/relay/src/lib/sshsig.ts:117",
    "code-2cf9c1e/relay/src/lib/sshsig.ts:215",
    "code-2cf9c1e/relay/src/lib/roster.ts:35",
    "code-2cf9c1e/relay/src/lib/roster.ts:111",
    "code-2cf9c1e/relay/src/lib/store.ts:60",
    "code-2cf9c1e/relay/src/lib/store.ts:110",
    "code-2cf9c1e/relay/src/lib/reducer.ts:340",
    "code-2cf9c1e/relay/src/lib/reducer.ts:478",
    "code-2cf9c1e/relay/migrations/0001_init.sql:5",
    "code-2cf9c1e/relay/scripts/run-local.py:46",
    "code-2cf9c1e/agora/store_relay.py:463",
    "code-2cf9c1e/agora/sign.py:165",
    "code-2cf9c1e/agora/tools.py:165",
    "code-2cf9c1e/agora/tools.py:239",
    "code-2cf9c1e/agora/tools.py:450",
    "code-2cf9c1e/agora/core.py:255",
    "code-2cf9c1e/agora/resident.py:313",
    "code-2cf9c1e/agora/onboard.py:236",
    "code-2cf9c1e/agora/event.py:69",
    "exp-worker/retired:1",
    "exp-worker/hist:1",
    "exp-worker/two:1",
    "design/RESEARCH-primary-sources.md:188"
  ]
}
```

(종료 rc=0)
