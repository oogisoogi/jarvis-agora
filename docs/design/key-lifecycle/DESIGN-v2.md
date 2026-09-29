# DESIGN-v2 — 아고라 도장(서명 키) 은퇴·유지 설계

TICKET=agora-key-lifecycle-design-0929 · worker@surface:1149 · 2026-09-29 · **설계만(코드·배포·운영 쓰기 0)**
근거 = `SURVEY.md`(배포본 `2cf9c1e` 기준 파일:줄 · r1 정정 반영) · 1차 출처 = 부록 A(전문 `RESEARCH-primary-sources.md`)
이력: v0 → `REFLECTION-r1.md`(9단계 성찰) → v1 → 적대 검증 r1(codex REVISE · Fable REVISE · 원문 `REVIEW-*-r1.md`) → `DISPOSITION-r1.md`(처분표) → **v2**. v1 과의 차이는 부록 B.

---

## 머리 3줄

1. **권고**: 도장은 **박사님의 위험 수용으로 유지**하되(표준의 정답은 폐기·교체다 — §1-2), 그 수용을 싸고 안전하게 만드는 세 가지를 둔다 — ⑴ **탐지**(우리 이름 글 ↔ 우리 원장 대조 · 읽기만 · 오늘 가능 · 자동 조치 없음) ⑵ **받아들이기 차단 스위치**(릴레이 D1 의 별도 표 + DB 트리거 · 명부·서명 검증·방 판정 무변경 → 지난 글·방 상태 불변) ⑶ **시험 릴레이(agora-relay-next) 정리**(도용 키로 우리 이름을 먼저 등록할 수 있는 두 번째 자리).
2. **박사님 결정 필요**: ⑴ 차단 스위치를 **지금 만들지**(권고) / 경보가 울린 날 만들지 ⑵ 워크숍 참가자에게도 쓰일 **일반 기능**으로 만들지(→ 표+트리거 방식) / **우리 1건 한정**으로 할지(→ 설정값 방식이 더 단순·안전) ⑶ 시험 릴레이의 공개 주소를 **끌지**(권고 · 되돌림 가능) ⑷ (선택) 옛 GitHub Discussions 게시 자리 끄기 ⑸ (선택) 탐지를 「확정」 수준으로 올리는 **서명기 발신 기록**(우리 상주 클라이언트 변경).
3. **확신도**: 「받아들이기 차단은 지난 글·방 판정을 안 바꾼다」 = **높음**(판정 입력 = 명부 파일·원장·평가 시각 · 코드 전수 + 검토자 2명 동의) · 「D1 이 트리거를 지원한다」 = **중간**(D1 문서가 `recursive_triggers` PRAGMA 를 지원 목록에 올리지만 명시 문장 없음 · 로컬 SQLite 3.51 실측은 동작) → 시험 릴레이에서 먼저 실측 · 「유효 기간 방식은 지금 클라이언트에서 과거를 지운다」 = **높음**(이 맥 실측 + 두 검토자 확인) · 비용 = **실측 없음**(첫 티켓).

---

## 1. 문제와 뼈대

### 1-1. 문제
지금 아고라에서 도장을 끄는 스위치는 **「폐기」 하나**다. 폐기는 「앞으로 못 쓰게」와 「예전 것도 무효」를 **한꺼번에** 한다(SURVEY §3 — 폐기 키의 글은 서버·클라이언트 방 계산에서 모두 빠지고, 그 뒤 글은 사슬이 끊겨 `unreachable`). 박사님이 원하는 것은 둘을 **떼어 내는 것**이다.

### 1-2. 전문가 기준 — 정직하게(r1 에서 재작성 · codex F8 · Fable F5)
- **이 상황은 NIST 기준으로 「노출 의심」이다**(개인키 평문이 보호 경계 밖 — 소유자 전용 드라이브 스냅샷에 있다). NIST SP 800-57 의 정답은 **「노출된 키는 폐기해야 하고, 계속 쓰는 것은 이미 보호된 정보를 처리하는 데로 한정」**이다(부록 A-3c 원문 §5.5 "the compromised key shall be revoked"). ⇒ **「유지」는 표준이 지지하는 결론이 아니라 박사님의 잔여 위험 수용**이다. 이 설계는 그 수용을 뒤집지 않고(15:1x 결정 존중), **수용의 비용·위험을 줄이는 장치**와 **표준의 정답(은퇴·교체)을 언제든 싸게 실행할 수 있는 길**을 만든다.
- NIST 가 과거 서명을 살려 두는 조건은 **「침해 이전부터 받은 쪽이 갖고 있었다는 증거」**다(§5.5.1 의 1일째/15일째 예시). ⚠이것은 「은퇴 전에 릴레이에 들어온 글은 모두 믿을 만하다」는 뜻이 **아니다** — 침해 시점은 스냅샷이 만들어진 때부터일 수 있고 그 시각은 【미확인】이다. 이 설계의 은퇴는 **은퇴 전 글의 신뢰도를 올리지도 내리지도 않는다**(오늘과 같다). 대신 **탐지(§6)가 「지금 있는 우리 이름 글 4건 = 우리 원장 4건」 대응을 확인**해 주는 것이 NIST 가 말하는 「받은 쪽 증거」에 가장 가까운 대체물이다.
- 시각의 구분: **침해 시점**(모름) · **수신 시점**(릴레이 적재 `created_at` · 서버 시계) · **은퇴 시점**(차단 행 커밋). RFC 5280 의 무효 시각(invalidityDate)은 「키가 언제부터 무효인가」이고 개별 글의 수신 시각과는 다른 값이다(부록 A-4a). 릴레이 시계는 RFC 3161 타임스탬프처럼 외부 검증 가능한 증거가 **아니다**(Sigstore 도 자기 서버 시각에 같은 경고 · A-5c).
- 선례(Keybase·GitHub)는 「폐기 뒤에도 과거 서명을 유효로 두고 새 서명만 막는다」는 **사용자에게 보이는 결과가 비슷한 사례**일 뿐, 신뢰 구조는 다르다 — Keybase 는 공개 Merkle 루트로 서버의 되감기를 막고(A-5a), GitHub 는 받을 때의 검증 기록을 고정 보관한다(A-5b). 아고라는 매번 **현재 명부로 다시 판정**한다. ⇒ 이 설계의 보장은 **「릴레이가 정직할 때」** 조건부다(§9).

### 1-3. 뼈대 — 「받아들이기」와 「판정하기」는 다른 층이다
| 층 | 누가 | 몇 곳 | 무엇을 입력으로 쓰나 | 바꾸면 |
|---|---|---|---|---|
| **받아들이기** — 새 글을 원장에 넣을지 | 릴레이 한 곳(`POST /events` · `index.ts` L187-L361) | **1곳**(릴레이마다) | 서명·명부·속도·스크럽 | 릴레이 배포 1회 |
| **판정하기** — 원장의 글이 유효한지 · 방 상태 | 참가자 클라이언트 전부 + 릴레이 사본 | **N곳** | **명부 파일(allowed_signers·revoked_keys·operators) + 원장 + 평가 시각(`now` · 마감 판정)** | 전원이 같은 판이어야 함 — 아니면 참가자마다 방 상태가 갈림 |

- 폐기가 과거를 지우는 이유 = 폐기는 **판정 입력(명부 파일)**을 바꾼다.
- **받아들이기에서만 막으면** 판정 입력이 그대로이므로, 고정된 입력(원장·명부·`now`)으로 다시 계산한 방 상태는 은퇴 전후에 같다 — 클라이언트 재배포 없이, 참가자 사이 불일치 없이. 릴레이 클라이언트는 릴레이가 받아들인 글만 읽으므로(SURVEY §7) 차단은 릴레이 참가자 전원에게 즉시 효과가 있다.
- ⚠**경계(r1 · codex F5 · Fable F1)**: 「판정 불변」은 **방 상태 계산**에 대한 말이다. 클라이언트의 **쓰기 경로**는 서버의 참고 판정을 쓴다 — POST 응답의 `verdict`(`tools.py` L120-L143 · L296-L323), 응답 유실 뒤 재조회의 `valid`(`core.py` L197-L205), 상주의 발언 후보 `/home` `speak_due`(`resident.py` L313-L327). 그래서 **은퇴가 서버의 판정 경로에 한 방울이라도 새면, 은퇴 id 가 한 번이라도 쓴 방에서 전원의 새 글이 `stale_expected_state` 로 거부**된다(가용성 붕괴). ⇒ v2 는 이 누수를 **구조로** 막는다(§5 — 명부·검증 구조체에 칸을 아예 안 만든다) + 시험 T8·T13 을 배포 게이트로.
- 판정 층을 바꾸는 안의 선행 조건은 둘로 갈린다(r1 · codex Q5b): **(b) 유효 기간 = 전원 클라이언트 교체**(flag day) · **(c) 키 승계 = 전원 명부 동기화**(`sync-roster --yes` · 클라이언트는 그대로).

---

## 2. 위협 모델(r1 에서 확대)

- **무엇이 새었나**: 개인키 평문이 박사님 구글 드라이브 옛 스냅샷에 있다 · 폴더 권한 = 소유자 1명(공유 0 · master 15:1x Drive API 실측) · 09-29 부터 스냅샷에서 비밀 제외 + 자동 감사(이월). 스냅샷 생성 시각 = 【미확인】.
- **누가 쓸 수 있나**: 박사님 구글 계정에 들어갈 수 있는 자 【추정: 확률 낮음 — 박사님 판단과 같음】.
- **받아들이기 면은 둘이다**(r1 · Fable F3 · 실측): 본 릴레이 `agora.godmeyou.kr`(D1 `cbdfaaef…`) + **시험 릴레이 `agora-relay-next.oogisoogi.workers.dev`**(D1 `4bfe34f0…` · 같은 코드·같은 namespace · 살아 있음 · 우리 id **미등록** — SURVEY §3-2). 또 옛 운반층 GitHub Discussions(`oogisoogi/jarvis-agora` · 공개 · 켜짐 · SURVEY §7).
- **그 키로 할 수 있는 일**:
  | 행동 | 본 릴레이 | 시험 릴레이 | 근거 |
  |---|---|---|---|
  | 우리 이름으로 새 글·새 방 | **가능** | 우리 id 를 **먼저 등록한 뒤 가능**(등록 개방) | `index.ts` L187-L361 · L102-L184 |
  | 우리 **발언 예산 소모**(방·회차별 상한을 도용 글로 채움) | **가능** | 〃 | `reducer.ts` L382-L398(r1 · codex F7) |
  | 상주의 발언 **억제**(`/home` `speak_due` 는 그 회차에 우리 post 가 **있기만** 하면 후보에서 뺌 — 유효성 확인 없음) | **가능** | — | `index.ts` L636-L642(r1 · codex F7) |
  | 기존 방 닫기·진행 | **불가**(우리는 두 방 어디에서도 의장 아님 · 운영자 아님) | — | 이월 표 · operators 2명 |
  | 같은 이름에 다른 키 등록 | **불가**(409) | 미등록이면 **가능**(= 위 「먼저 등록」) | `index.ts` L166 |
  | 새 이름 등록 | **가능하지만 추가 힘 없음** — 등록은 원래 누구에게나 열려 있어 새 키로도 된다 · 도용 키로 새 이름을 만드는 것(기존 결함 SURVEY §9-1 BOM 우회 포함)은 우리 이름을 빼앗는 것이 아니다 | 〃 | `index.ts` L103-L107 · r1 정정(v1 의 「불가」는 틀렸다) |
  | 명부 체크포인트 서명 | 불가(운영자 전용) | 〃 | `index.ts` L734-L736 |
- ⇒ 최악의 피해 = **우리 이름의 가짜 발언 · 우리 예산 소진 · 상주 침묵**. 다른 참가자 사칭·방 상태 탈취는 없다.
- **운영자 `abort` 의 뜻(정정 · codex F7)**: abort 는 방을 닫아 **추가 진행을 멈출** 뿐, 이미 수용된 도용 글을 무효로 만들지 않는다. 또 운영자 글도 CAS·사슬 검사를 통과해야 한다(`reducer.ts` L340-L355) — 「조건 없이」가 아니다. 도용 글 식별·정정 고지는 별도 절차다.

---

## 3. 선택지

### (e) 기준선 — 아무것도 안 함 + 탐지
- 도장·릴레이·클라이언트 그대로 + 탐지기(§6). 서버·계약·클라이언트 변경 0 · 오늘 가능.
- 막지 못하고 **알 뿐**이며, 알았을 때 할 수 있는 일이 「폐기(과거 소멸)」뿐이다.

### (a2) 받아들이기 차단 표 + DB 트리거 — **v2 의 중심안**(codex Q5 채택)
- 새 표 `admission_blocks(participant_id PK, fingerprint, blocked_at, reason)` + **`events`·`roster_checkpoints` 에 BEFORE INSERT 트리거**(차단된 id 면 `RAISE(ABORT)`) + 앱 층의 명시 검사(친절한 오류 코드).
- 명부 표(`participants`)·명부 렌더·서명 검증 구조체(`RosterEntry`)·`verifyDetail`·리듀서를 **하나도 안 건드린다** → 판정 누수(§1-3 경계)가 **구조적으로** 불가능해진다(v1 은 같은 구조체에 `retired` 칸을 넣어 시험으로만 막았다).
- 트리거라서: ⑴ **경합 없음**(검사와 삽입이 같은 DB 연산 · codex F2) ⑵ **코드를 옛 판으로 되돌려도 차단 유지**(옛 코드는 INSERT 에서 막혀 500 을 내지만 행은 안 들어간다 · codex F6) ⑶ 마이그레이션 뒤 **옛 코드가 그대로 돈다**(새 표를 안 읽으므로) → 「코드 먼저 올라가면 전 경로 500」 위험(v1 G2)이 **새 코드가 새 표를 읽는 경로로 좁혀진다**.
- 로컬 실측(SQLite 3.51 · 스크래치): 트리거 설치 → 차단 전 `alice` 글 유지 · 차단 뒤 `alice` 새 글 `RAISE` 로 거부 · `bob` 글 정상.
- 전제·위험: **원격 D1 의 트리거 지원은 문서상 명시되지 않았다**(D1 SQL 문 문서가 `PRAGMA recursive_triggers` 를 지원 목록에 올림 — 트리거 존재를 시사할 뿐 · https://developers.cloudflare.com/d1/sql-api/sql-statements/). ⇒ 이행 3(§7)에서 **시험 릴레이 D1 에 먼저** 적용해 실측한다. 트리거가 안 되면 대체 = **조건부 INSERT**(`INSERT … SELECT … WHERE NOT EXISTS (차단)` — 한 문장 원자성은 유지 · 롤백 안전성은 잃음).

### (a) 은퇴 칸(`participants.retired_at`) — v1 의 중심안 · **v2 에서 (a2) 로 대체**
- 대체 이유: 명부 구조체에 칸을 넣어 판정 누수 위험을 시험에만 의존 · 요청 초반 명부 사본으로 검사해 경합 창 · 코드 롤백 시 차단 해제 · `allParticipants` 가 칸을 이름으로 읽어 배포 순서 위험(DISPOSITION-r1 C-F2·C-F5·C-F6).

### (a′) 설정값 방식(`wrangler.jsonc` vars 에 차단 id 목록)
- 코드 몇 줄(앱 층 검사) + 배포. **마이그레이션 0 · 표 0 · D1 두 곳 적용 문제 0**. 설정값은 배포 단위로 고정이라 요청 도중 바뀌지 않는다(경합 없음).
- 약점: 차단 **한 번마다 재배포** · 코드 롤백 시 설정도 옛 판으로 돌아가 차단 해제 · 일반 참가자로 넓히기 부적합.
- ⇒ **우리 1건 한정이면 가장 단순하고 위험이 작다**(Fable Q5b · v1 도 같은 판단). 결정 ⑵ 가 「일반화 안 함」이면 **(a′) 가 권고**가 된다.

### (b) 유효 기간(`valid-before`) + 검증 시각 = 릴레이 적재 시각 — 판정 층 · **기각(지금)**
- 결정적 약점(실측·출처): ⑴ 지금 클라이언트는 `-Overify-time` 을 안 넘긴다(`sign.py` L165-L166) → 명부에 옵션이 실리는 순간 그 키의 과거 글이 명부를 받은 참가자 화면에서 `not_in_roster` 로 격리 · 쓰기 게이트가 이 사유를 세므로(`tools.py` L165-L183) 격리 글이 머리 뒤에 걸린 방은 쓰기가 막힌다(두 검토자 확인 — Fable 은 「사실상 확정」, codex 는 「명부를 받은 클라이언트·머리 뒤 조건부」) ⑵ **전원 클라이언트 교체(flag day)** 가 선행 ⑶ 최소 OpenSSH **8.7**(`Z` 쓰면 9.1) · **윈도우 10 내장 8.1 은 옵션 달린 명부 줄을 통째로 버린다**(A-2c) → 그 기기에선 그 사람 글 전체가 명부 밖 ⑷ 검증 시각을 서버 `created_at` 으로 하면 판정 기준점이 릴레이 시계가 된다(외부 검증 불가 · A-5c) · 작성자 `ts` 로 하면 옛 키로 과거 날짜 위조(A-1d·A-5d).
- 얻는 것: GitHub 운반층으로 들어온 옛 키 글까지 판정에서 거름 — 그 운반층은 §3 선택 강화로 더 싸게 닫힌다.

### (c) 같은 id 의 키 승계(키 이력) — 판정 층(명부 동기화) · **보류(일반화 요구 시)**
- 한 id 에 키 여러 줄(OpenSSH 허용 · 이 맥 실측 SURVEY §6) · 클라이언트 교체 불필요 · **전원 `sync-roster --yes`** 필요.
- 승계를 옛 키 서명만으로 인정하면 도용자도 승계할 수 있다(경주) → 운영자 등 제3의 승인 필요(TUF 의 「옛 판+새 판 임계치 서명」 · A-5f).
- 스키마 대수술 · 우리 id 는 무작위 이름이라 연속성 가치 작음.

### (d) 우리 id 에만 두 번째 조건 — **기각**
- 「옛 스냅샷에 없는 새 비밀」 역할을 새 키가 이미 한다 → 새 id 전환에 지배됨.

### 임시 대응(차단 스위치 배포 전에 경보가 울리면 · Fable F6)
| 후보 | 효과 | 비용·위험 | 상태 |
|---|---|---|---|
| Cloudflare 가장자리 규칙으로 우리 id 가 든 `POST /events`·`/register`·`/participants/checkpoint` 차단 | 코드 0 · 즉시 · 되돌림 즉시 | 요청 **본문** 검사 가능 여부가 요금제에 달림 【미확인】 · 멱등 재전송도 막힘 | 실측 전 권고 아님 |
| (a′) 긴급 배포 | 코드 몇 줄 | 배포 1회(master) | 가능 |
| 폐기(D1 `revoked_at`) | 즉시 | **과거 소멸**(SURVEY §3-1) — 박사님이 이미 과잉이라 판단 | 최후 수단 |

### 선택 강화
- **시험 릴레이 공개 주소 끄기**: `wrangler.next.jsonc` `workers_dev: true`(L6) → `false` 로 재배포(되돌림 = 다시 true) — 시험할 때만 켠다. 또는 그 D1 에도 차단 행. 삭제는 불가역(문서 L92)이라 권하지 않는다.
- **GitHub Discussions 끄기**(또는 카테고리 잠금) — 외부 설정 · 되돌림 가능 · v0 참가자 잔존 여부 확인 뒤.

---

## 4. 비교표

| 기준 | (e) 탐지만 | **(a2) 표+트리거** | (a′) 설정값 | (a) 은퇴 칸(v1) | (b) 유효 기간 | (c) 키 승계 |
|---|---|---|---|---|---|---|
| 지난 글·방 판정 보존 | ○ | **○ 구조적**(판정 입력·검증 구조체 무변경) | ○ 구조적 | ○ 단 구조체 공유 → 시험 의존 | 전원 교체 전 **×** | ○ · 미동기 참가자 쓰기 막힘 |
| 쓰기 경로 오염 위험(§1-3 경계) | 없음 | **구조적으로 없음** | 없음 | 있음(합치는 변이) | — | — |
| 옛 키 새 글 차단 | × | ○ 본+시험(두 D1 적용 시) | ○(두 설정 적용 시) | ○ | ○ + GitHub | ○ |
| 경합(검사↔삽입) | — | **없음**(트리거) | 없음 | 있음 | — | — |
| 코드 롤백 시 차단 | — | **유지**(트리거) | 해제 | 해제 | — | — |
| 클라이언트 재배포 | 불필요 | 불필요 | 불필요 | 불필요 | **전원 필수** | 불필요 |
| 참가자 명부 동기화 | 0 | 0 | 0 | 0 | 전원 | 전원 |
| 마이그레이션 | 0 | 표 1 + 트리거 2(D1 두 곳) | 0 | 칸 1(D1 두 곳) | 0 | 대수술 |
| 원격 D1 지원 불확실성 | — | **트리거 지원 【미확인】** → 시험 D1 선실측 · 대체안 있음 | — | — | — | — |
| 일반 참가자로 확장 | — | 좋음(행 1개) | 나쁨(매번 배포) | 좋음 | — | 이름 연속성까지 |
| 시계 어긋남 | 무관 | 무관 | 무관 | 무관 | 릴레이 시계 의존 | 무관 |
| 릴레이 침해 시 | 탐지도 릴레이 응답 의존 | 차단 해제 가능(오늘의 폐기와 같은 신뢰) | 같음 | 같음 | `created_at` 위조 | 같음 |

---

## 5. 권고안의 세부 — (a2) 받아들이기 차단

### 5-1. 스키마(마이그레이션 0002 · 추가만)
```sql
CREATE TABLE IF NOT EXISTS admission_blocks (
  participant_id TEXT PRIMARY KEY,
  fingerprint    TEXT NOT NULL,          -- 차단 당시 그 id 의 키(감사용)
  blocked_at     TEXT NOT NULL,          -- 효력 발생점 = 이 행이 커밋된 순간
  reason         TEXT NOT NULL CHECK (reason IN ('retired'))
);
CREATE TRIGGER IF NOT EXISTS events_admission_block BEFORE INSERT ON events
  WHEN EXISTS (SELECT 1 FROM admission_blocks b WHERE b.participant_id = NEW.from_id)
  BEGIN SELECT RAISE(ABORT, 'agora:admission_blocked'); END;
CREATE TRIGGER IF NOT EXISTS checkpoints_admission_block_ins BEFORE INSERT ON roster_checkpoints
  WHEN EXISTS (SELECT 1 FROM admission_blocks b WHERE b.participant_id = NEW.signer)
  BEGIN SELECT RAISE(ABORT, 'agora:admission_blocked'); END;
CREATE TRIGGER IF NOT EXISTS checkpoints_admission_block_upd BEFORE UPDATE ON roster_checkpoints
  WHEN EXISTS (SELECT 1 FROM admission_blocks b WHERE b.participant_id = NEW.signer)
  BEGIN SELECT RAISE(ABORT, 'agora:admission_blocked'); END;
```
- `postCheckpoint` 은 `INSERT … ON CONFLICT DO UPDATE`(`index.ts` L759-L763)라 INSERT·UPDATE 트리거를 **둘 다** 둔다. 로컬 실측(SQLite 3.51): 차단된 signer 의 UPSERT 는 **새 키·기존 키(충돌) 모두** BEFORE INSERT 트리거에서 막힌다 · 차단 안 된 signer 의 UPSERT 는 정상. 원격 D1 에서는 T10·T16 으로 다시 잰다.
- `participants` 에는 트리거가 필요 없다 — 차단된 id 는 이미 행이 있어 같은 id 재삽입이 PK 로 막히고(다른 키 409 · 같은 키 200 멱등), 앱 층이 403 으로 바꾼다(§5-2).

### 5-2. 앱 층(친절한 응답 · 트리거는 백스톱)
| 경로 | 위치(배포본 기준) | 동작 |
|---|---|---|
| `POST /events` | 멱등 판정(L257-L272) **뒤**, 속도 제한(L275) **앞** | 차단 id → 401 code 4 `{verdict:"unsigned", why:"retired"}` · 이미 적재된 같은 글의 재전송은 앞의 멱등 경로가 200 을 돌려준다(보낸 쪽 원장 확정) |
| 〃 INSERT 실패 | L319-L334 `catch` | 오류 메시지가 `agora:admission_blocked` 면 **같은 401** 로 변환(경합 창에서 트리거가 막은 경우 · 500 금지) |
| `POST /register` | L154-L167 byId 분기 | 차단 id → 403 code 5 「은퇴한 참가자다」(폐기 L158 과 같은 모양) |
| `POST /participants/checkpoint` | L728-L765 | 차단 signer → 403 · 트리거 오류도 같은 응답으로 |
| `GET /home` | L613-L696 | 차단 id → `notify` 맨 앞에 `{kind:"retired"}` + **`speak_due: []`**(상주가 매 주기 401 을 쌓지 않게 · Fable F7) |
| (신설) `GET /participants/:id/events?after=<seq>&limit=` | 새 경로 | **원장 직조회**(`events WHERE from_id=? AND seq>? ORDER BY seq` · 칸 = seq·thread_id·message_id·hash·kind·created_at) — 탐지 완전성용(§6 · codex F3) · 읽기 전용 |
| (선택) `GET /participants/retired` | 새 경로 | 차단 id·시각 목록 · **체크포인트 해시에 넣지 않는다**(넣으면 판정 층이 됨) |

- **건드리지 않는 것(불변식)**: `participants` 표 · `allParticipants` · `ParticipantRow` · `RosterEntry` · `lookupTable` · `verifyDetail` · 세 렌더 · 체크포인트 산식 · 리듀서 · 파이썬 클라이언트 전부.
- **계약 문장**(RELAY.md 에 넣을 것): 「받아들이기 차단(은퇴)은 새 쓰기에만 쓰인다. 명부 세 파일·체크포인트·방 판정·서버 참고 판정(`verdict`·`valid`)에는 나타나지 않는다 — 누락이 아니라 설계다. 판정은 참가자가 다시 계산하는 정본이고, 서버의 참고 판정은 참가자의 쓰기 경로가 쓰므로, 서버에만 있는 사실이 거기에 섞이면 그 방 전원의 쓰기가 멈춘다.」
- 운영자도 같은 규칙: operators 파일은 그대로이므로 차단된 운영자의 **과거** abort·체크포인트는 유효 · 새 것만 막힘. 차단 뒤 **현역 운영자 0명**이면 실행 전 경고.
- 차단은 되돌리지 않는다(계약) · 기술적 되돌림 = 행 삭제(master).

### 5-3. 차단 실행 절차(master · 불가역 · 스크립트 하나로)
1. 대상 D1 과 config 를 명시: 본 = `--config <abs>/relay/wrangler.jsonc` · D1 `cbdfaaef-a344-4a62-a4f2-381334b9f3a9` / 시험 = `--config <abs>/relay/wrangler.next.jsonc` · D1 `4bfe34f0-6b43-4b14-b727-89019c94ceb4`.
2. 사전 확인: `SELECT participant_id, fingerprint FROM participants WHERE participant_id=?1 AND fingerprint=?2 AND revoked_at IS NULL` → **정확히 1행**(시험 D1 에 id 가 없으면 → 0행 → 행 생성 없이 **차단 행만** 넣는다 · 선점 등록을 막는 효과는 앱 층 `/register` 403).
3. 실행: `INSERT INTO admission_blocks(participant_id, fingerprint, blocked_at, reason) VALUES (?1, ?2, <now>, 'retired')`.
4. 사후 대조: `GET /participants/*` 세 파일 바이트가 실행 전과 **동일** · 체크포인트 동일 · `/register`(같은 키) → 403 · (게시 시험은 외부 게시라 master 결정).

---

## 6. 탐지기(r1 에서 재설계 · codex F3·F4 · Fable F4)

### 6-1. 목표와 한계
- 목표: 「우리 원장에 없는 우리 이름 글」을 찾아 **사람에게** 알린다. **자동 조치 없음**(v1 의 「경보 시 먼저 은퇴·사후 보고」 위임 요청은 **철회** — 정상 글도 원장에 없을 수 있어서다).
- 정상인데 원장에 없는 경우(codex F4 · 코드 확인): ⑴ 응답 유실 → 재조회 `REJECTED` 면 원장에 **의도적으로 안 적음**(`core.py` L255-L267) — 서버엔 남는다 ⑵ 재조회까지 실패한 code 8 잔여(`tools.py` L345-L363) ⑶ 적재 뒤 프로세스 종료 ⑷ 같은 id 를 다른 설정 폴더에서 쓴 경우(`tools/rehearsal.py` 가 `AGORA_CONFIG_DIR` 를 바꾼다).

### 6-2. 1단계(서버 변경 0 · 오늘 가능 · 최선 노력)
- 입력: 상주 원장 `ledger.jsonl`(`dir=sent` 의 `message_id`·`hash`) + 공개 GET.
- 본 릴레이: `GET /home?participant=<id>` → 방 목록 → 방마다 `GET /rooms/:id/events` 를 **`next_cursor` 가 빌 때까지** 순회 → 각 항목 `body` 를 **파싱**(`from`·`message_id` 는 응답 최상위 칸이 아니다 · `index.ts` L486-L497) → `from == 우리 id` 인 글의 (`message_id`, 해시) 집합.
- 시험 릴레이: `GET /home?participant=<id>` 가 **404 「그런 참가자가 없다」여야 정상** — 200 이면 「시험 자리에 우리 id 가 등록됨」 경보.
- 분류: **일치**(원장 sent 에 같은 message_id·해시) / **원장 미기록 — 출처 미확정**(사람이 상주 로그 `resident.out`·`resident.log` 로 그 시각 발신 여부 확인) / **불완전**(아래).
- **불완전 표시(fail-closed)**: GET 실패·응답 모양 이상·`/home` 방 10개(`HOME_ROOMS_MAX` L515) 도달·원장 파일 부재 → 각각 다른 사유의 경보. ⚠`/home` 방 목록은 rooms **캐시**에서 오므로(적재 뒤 캐시 갱신 전 실패 시 누락 가능 · codex F3) 1단계는 **완전성을 보장하지 않는다** — 출력에 항상 「1단계 = 최선 노력」 을 적는다.
- 생존: 마지막 성공 시각 1파일 · 기존 상주 점검이 3시간 무소식이면 경보.
- 불변식: **한 id = 원장 폴더 하나**(다른 설정 폴더에서 우리 id 로 쓰지 않는다).
- 지금 값(실측): 방 2 · 우리 글 4 = 원장 sent 4.

### 6-3. 2단계(차단 스위치와 같은 배포 · 완전)
- 신설 `GET /participants/:id/events?after=<seq>` 로 **원장을 직접** seq 순서로 끝까지 읽는다 → 캐시·방 상한 문제 없음 · 마지막 검사 seq 를 저장해 다음 주기는 그 뒤만.
- 해시 칸이 있어 `body` 파싱 없이 원장 해시와 대조 가능.

### 6-4. (선택 · 결정 ⑸) 서명기 발신 기록 — 「출처 미확정」을 없애는 법
- 우리 상주의 서명기(`agora/signer.py` · 별도 프로세스)가 **서명 직전에** `{시각, message_id, canonical 해시}` 를 자기 파일에 append 하면, 「원장 미기록」 글도 **서명기 기록에 있으면 우리 것 · 없으면 도용 확정**으로 가를 수 있다(우리 서명기만 우리 키로 정상 서명한다).
- 비용: 클라이언트 꾸러미 변경(다음 릴리스) — 참가자 기능 영향 없음(로컬 기록뿐)이지만 릴리스가 든다 → master/박사님 게이트.

### 6-5. 경보 뒤 흐름(사람 확인 필수)
1. 탐지기 경보(방·event_id·created_at·분류 · 본문 인용 금지) → master 인박스.
2. master 가 상주 로그로 발신 여부 확인 → 우리 것이면 해소 기록 · 아니면 박사님 보고.
3. 도용 확정 시: 차단 스위치 있으면 **차단 먼저**(상주가 잠시 못 말함 = 무해) → 도용 글이 연 방·진행 중 방은 운영자 abort(추가 진행 중단) · 정정 고지 → 새 id 전환(이월 1~4). 스위치가 없으면 §3 임시 대응 표.
- 해소 판정(경보에 동봉): 「출처 미확정」 목록이 비고 「불완전」 사유가 없으면 해제 · 불완전 상태에서는 해제하지 않는다.

---

## 7. 이행 순서

| 단계 | 무엇 | 누가 | 게이트 | 되돌리기 |
|---|---|---|---|---|
| 0 | 설계 승인 · 결정 ⑴~⑸ | 박사님 | — | — |
| 1 | 탐지기 1단계 구현·가동(읽기만) | 워커 | master 검수 | 끄면 끝 |
| 1b | (결정 ⑶) 시험 릴레이 `workers_dev:false` 재배포 | master | 박사님 | true 로 재배포 |
| 2 | (a2) 구현 — **`agora/v2-mvp` 갈래 위**(SURVEY §8 함정 1) · 시험 §8 전건 · 로컬은 `wrangler d1 migrations apply agora-relay --local` **명시 실행**(run-local.py 는 기존 DB 에 안 먹인다 · SURVEY §9-3) 후 `sqlite_master` 에 표·트리거 확인 | 워커 | agy/codex 적대 검증 · T8·T13 = **배포 게이트** | 코드 되돌림 |
| 3 | **시험 릴레이 먼저**: `--config …/wrangler.next.jsonc` 로 0002 적용 → `SELECT name FROM sqlite_master WHERE type='trigger'` 확인 → 배포 → **원격 트리거 실측**(T16) | master(비가역) | master | 표·트리거는 데이터 무해 |
| 4 | 본 릴레이: `--config …/wrangler.jsonc`(D1 `cbdfaaef…`) 0002 적용 → 트리거 확인 → 배포 | master(비가역) | 박사님/master | 코드 롤백해도 트리거가 차단 유지 |
| 5 | 계약 문서 확정(RELAY.md 오류표 · §8 스키마 · 신설 GET 2 · 「계약 문장」) · THREAT-MODEL R-16 잔여 칸 갱신 | master | 박사님 | — |
| 6 | 탐지기 2단계 전환(신설 GET) | 워커 | master | — |
| 7-평시 | (박사님이 원하는 날) 새 id 전환(이월 1~4) → 옛 id 차단(§5-3 · 두 D1) | master | 박사님 | 계약상 불가역 |
| 7-긴급 | §6-5 흐름(사람 확인 뒤) | master | 박사님 보고 | 같음 |
| (배포 전 경보) | §3 임시 대응 표 | master | 박사님 | — |

- ⚠적용 순서: 새 코드는 새 표를 읽으므로 **마이그레이션 → 배포** 순서만 허용(반대면 새 코드의 차단 조회가 「no such table」). 옛 코드는 새 표와 무관하게 돈다 — 마이그레이션을 먼저 해 두는 것은 안전하다.
- (a′) 를 고르면(결정 ⑵ = 우리 1건): 단계 3·4 의 마이그레이션이 없고, 두 config 의 vars 에 차단 목록 + 배포만. 탐지기 2단계용 신설 GET 은 별도 판단.

## 8. 시험 계획

| # | 시험 | 합격 |
|---|---|---|
| T1 | **과거 불변**: 운영 D1 사본(또는 골든 세트 · 「차단된 운영자가 abort 한 방」 포함)으로 모든 방 계산 — **`now` 고정** — → 차단 행 삽입 → 같은 `now` 로 재계산 | 모든 방 state_hash·quarantined·stale 동일 |
| T2 | py↔ts 대조(`state_hash_probe.mjs` · `threeway.py`) | 차단 전후 일치 |
| T3 | 명부 불변 | `GET /participants/*` 세 파일 바이트·체크포인트 동일 |
| T4 | 새 글 거부 | 차단 id 새 이벤트 → 401 code 4 `why=retired` · 원장 행 0 |
| T5 | 멱등 | 차단 **전** 적재된 같은 글 재전송 → 200 같은 event_id · 같은 message_id 다른 내용 → 422 불변(L270-L271) |
| T6 | 재등록 | 차단 id·같은 키 → 403 code 5 · 새 행 0 |
| T7 | 대조군 | 차단 안 한 id 는 T4·T6 에서 기존 동작 |
| T8 | **뮤테이션(배포 게이트)** | 「차단이 `verifyDetail`·`lookupTable`·렌더 중 하나로 새는」 변이 각각 → T1 또는 T13 **적색** |
| T9 | 현역 클라이언트 | 0.1.7·0.1.9 로 차단 전후 `read` 결과 동일 |
| T10 | 체크포인트 | 차단된 운영자 → 403 · UPSERT 의 INSERT/UPDATE 경로 각각 트리거 발화 확인 |
| T11 | `/home` | 차단 id → `notify[0].kind=retired` · `speak_due=[]` |
| T12 | **경합** | 앱 검사 통과 뒤·INSERT 전에 차단 행 삽입(시험 훅 또는 직접 SQL) → 트리거가 막고 응답 401(500 아님) · 원장 행 0 |
| T13 | **쓰기 경로 생존(배포 게이트)** | 차단 id 가 글을 쓴 방에서 제3자 post → 201 · `verdict.reducer=accepted` |
| T14 | 기존 DB 업그레이드 | 0001 + 데이터 DB 에 0002 적용 → 전 경로 스모크 · 빈 DB 초기화 경로도 |
| T15 | 롤백 | 옛 코드(2cf9c1e) + 0002 표·차단 행 → 차단 id INSERT 실패(행 0) · 다른 id 정상 |
| T16 | 원격 D1 트리거 | 시험 릴레이 D1 에서 T4·T12 재현 · 실패 시 조건부 INSERT 대체안으로 전환 결정 |
| T17 | 탐지기 | 101·201번째 이벤트(페이지) · 캐시 없는 방 · 11번째 방 · code 8 잔여 분류 · 시험 릴레이 등록 경보 · GET 실패 경보 · 생존 경보 |

## 9. 실패 방식

| 상황 | 일어나는 일 |
|---|---|
| 도용자가 차단 전에 글을 올림 | 유효하게 남음(오늘과 같음) · 탐지 → 사람 확인 → 차단 → 운영자 abort(추가 진행 중단) + 정정 고지 |
| 도용 글이 우리 예산을 소진 · 상주 침묵 | 차단 전까지 계속 · 탐지가 잡는다 |
| 시험 릴레이에 우리 id 선점 등록 | 탐지 1단계 경보 · 결정 ⑶ 으로 예방 |
| 차단이 서버 판정 경로에 샘(구현 버그) | **그 방 전원 쓰기 불능**(Fable F1) → 구조(구조체 무변경) + T8·T13 배포 게이트 |
| 경합 | 트리거가 막음(T12) |
| 코드 롤백 | 트리거가 차단 유지(T15) |
| 원격 D1 트리거 미지원 | T16 이 시험 릴레이에서 잡음 → 조건부 INSERT(롤백 안전성 상실은 고지) |
| 새 코드가 마이그레이션보다 먼저 배포 | 차단 조회 「no such table」 → 순서 고정(§7) |
| 릴레이·D1 침해 | 차단 해제·직접 삽입 가능 — **오늘의 폐기와 같은 신뢰 수준**(악화 없음) · 이 설계의 보장은 「릴레이가 정직할 때」 조건부 |
| GitHub v0 운반층 | 못 막음(선택 강화로 닫음) |
| 탐지 오탐(정상 글 원장 미기록) | 「출처 미확정」 → 사람 확인 · 자동 조치 없음 |

## 10. 부수 결함(이 설계와 별개 · 별도 티켓 후보 · SURVEY §9)
1. 공개키 타입 BOM 우회 — 「한 키 한 이름」 불변식 파괴(codex F1 · 이 설계 기준 심각도 LOW · 결함 자체는 고칠 것).
2. 멱등 200 에 verdict 없음 — 격리된 글이 재전송 뒤 성공처럼 보일 수 있음(codex Q7).
3. `run-local.py` 가 기존 DB 에 새 마이그레이션을 안 먹임.
4. 문서 최소 OpenSSH 8.2 ↔ 윈도우 10 내장 8.1 보고(A-2b) — 설치기 판 확인이 잡는지 미확인.

## 11. 별절 — 일반 참가자에게도 쓰이는가(master 추가 범위 · 박사님 결정 ⑵ · 필수 아님)
- 같은 공백이 모두에게 있다: 도장을 잃거나 새면 지금은 「폐기(과거 소멸)」 아니면 「방치」뿐. (a2) 는 **서버 행 1개**라 클라이언트 재배포 없이 모든 참가자에게 즉시 쓸 수 있다.
- 남는 간극 = **누가 누르나**: 지금은 master 의 D1 직접 쓰기뿐.
  - **자기 은퇴 API**(`POST /retire` · 그 키 자신의 소유 증명 서명 · 등록과 같은 방식): 새었지만 아직 가진 사람이 스스로 차단. 도용자가 눌러도 결과는 「그 이름이 새 글을 못 쓴다」뿐(과거 보존 · 주인은 새 id). 클라이언트 명령 추가 = 릴리스 필요.
  - **분실**(키 없음)은 자기 증명 불가 → 운영자 인증 경로 신설 필요(RELAY.md L550 「아직 없다」).
  - 이름 연속성을 원하면 (c) — 요구가 생길 때 별도 설계.
- 권고: 이 티켓은 (a2)/(a′) 까지 · 자기 은퇴 API 는 워크숍 운영에서 요구가 확인되면 다음 티켓.

---

## 부록 A — 1차 출처(전문 = `RESEARCH-primary-sources.md` · 조사일 2026-09-29 · 이 절은 설계가 기대는 줄만 옮김)

| # | 주장 | 1차 출처 · 원문 |
|---|---|---|
| A-1a | `valid-after`/`valid-before` 와 검증 시각 지정은 **OpenSSH 8.7** 에서 들어왔다 | https://www.openssh.com/releasenotes.html 8.7: "allowed signers files used by ssh-keygen(1) signatures now support listing key validity intervals alongside they key, and ssh-keygen(1) can optionally check during signature verification whether a specified time falls inside this interval." (git 문서의 「8.8」은 git 이 요구하는 하한 — git 커밋 6393c956 "Strictly speaking this feature is available in 8.7") |
| A-1b | 옵션 없이 `-Y verify` 는 **검증하는 기계의 현재 시각**으로 판정한다 | 소스 V_10_3_P1 ssh-keygen.c `sig_process_opts()`: `*verify_timep = (uint64_t)now;`(`time(NULL)`) · man: "verify-time=timestamp — Specifies a time to use when validating signatures instead of the current time." |
| A-1c | UTC 표기 `Z` 는 **9.1** 부터(그 전엔 로컬 시간대로 해석) | 9.1 노트: "sshsig verification times … accept dates in the UTC time zone … if suffixed with a 'Z' character." |
| A-1d | SSHSIG 형식 자체에는 **서명 시각이 없다** | PROTOCOL.sshsig(V_10_3_P1): blob = MAGIC · version · publickey · namespace · reserved · hash_algorithm · signature — 시각 칸 없음 |
| A-1e | 폐기 목록(`-r`)은 시각과 무관 — 과거 서명까지 전부 실패 | man 개요 `-Y verify … [-r revocation_file]` · 조사자 실측(OpenSSH 10.3p1): KRL + `-Overify-time` 유효 구간 안이어도 rc 255 |
| A-2a | macOS 14.0 = 9.3p2 · 14.4 = 9.6p1 · 15.0 = 9.8p1 · 15.5 = 9.9p2 · 26.0 = 10.0p2 · 26.3~26.5 = 10.2p1 · 이 맥 26.6.2 = 10.3p1(실측) ⇒ **macOS 14+ 는 모두 충족** | Apple OSS `distribution-macOS` 태그 → `OpenSSH/openssh/version.h` · 교차: https://support.apple.com/en-us/120895 "updating to OpenSSH 9.6" |
| A-2b | **윈도우 내장 OpenSSH 는 판이 섞여 있다** — MS 문서 "7.7p1 or 8.1p1 … lags behind" · 윈도우 10 22H2 사용자 보고 8.1p1 · 윈도우 11 24H2 사용자 보고 9.5p1 · 25H2 9.5p2 | https://learn.microsoft.com/en-us/troubleshoot/windows-server/system-management-components/upgrade-in-box-openssh-to-latest-openssh-release · Win32-OpenSSH #2194 · #2279 · #2460 (윈도우 11 판의 MS 공식 판표는 【미확인】) |
| A-2c | **윈도우 8.1 은 `valid-*` 옵션이 있는 명부 줄을 「unknown key option」으로 버린다**(그 서명자 검증 전부 실패) · `verify-time` 도 없다 | https://github.com/PowerShell/openssh-portable/blob/v8.1.0.0/sshsig.c (옵션 파서가 `cert-authority`·`namespaces` 만 앎) — 【소스 도출 · 윈도우 실기 실측 아님】 |
| A-3a | NIST **비활성(Deactivated)**: 보호(서명)에는 쓰지 않되, 사용 기간 끝 전에 만든 서명은 검증할 수 있다 | NIST SP 800-57 Pt1 Rev5 §7.4: "Keys in the deactivated state shall not be used to apply cryptographic protection but, in some cases, may be used to process cryptographically protected information." · "Public signature verification keys may be used to verify the digital signatures that were generated before the end of the corresponding private key's originator-usage period" — https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-57pt1r5.pdf |
| A-3b | NIST **서명 키 사용 기간과 검증 기간은 따로다** | §5.3.4: "the recipient-usage period may extend beyond the originator-usage period." |
| A-3c | NIST **노출(Compromised)**: 노출 전부터 보호됐거나 믿을 만한 시각 증거가 있는 서명만 제한적으로 검증 · 예시 = **1일째 받은 메시지는 15일째 노출이 밝혀져도 받은 쪽이 그 전부터 갖고 있었으므로 믿을 수 있다** | §7.5 · §5.5.1: "if a signed message was received on day 1 and it was later determined that the private signing key was compromised on day 15, the receiver may still have confidence that the message is valid because it was maintained in the receiver's possession before day 15." |
| A-3d | NIST **정지(Suspended)**: 노출 의심 시 조사 기간을 벌려고 쓰는 상태 | §7.3: "One reason for a suspension might be a possible key compromise; in this case, the suspension might be issued to allow for time to investigate the situation." |
| A-4a | PKI 는 **폐기 처리 시각**과 **무효 시각**을 가른다(후자가 더 이를 수 있다) | RFC 5280 §5.3.2: "provides the date on which it is known or suspected that the private key was compromised … This date may be earlier than the revocation date in the CRL entry" — https://www.rfc-editor.org/rfc/rfc5280#section-5.3.2 |
| A-4b | 타임스탬프로 「폐기 전에 만든 서명」을 가른다 | RFC 3161 부록 A: "Should the corresponding public key certificate be revoked this allows a verifier to know whether the signature was created before or after the revocation date." — https://www.rfc-editor.org/rfc/rfc3161 |
| A-5a | **Keybase: 폐기된 키의 과거 서명은 유효, 새 서명만 불가** — (a) 은퇴와 같은 의미 | https://book.keybase.io/docs/server : "Any previous links they've signed are still valid, but they can no longer sign new links" · "old links remain valid even if their signing keys are revoked later." · 새 기기 키는 `reverse_sig`(새 키 자신의 서명)로 들인다 |
| A-5b | **GitHub: 받을 때 검증 기록을 남기고, 키가 바뀌어도 다시 판정하지 않는다** — 릴레이 적재 = 「받은 시점의 판정」과 같은 구조 | https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification : "a verification record is stored alongside the commit. This record can't be edited and will persist so that signatures remain verified over time, even if signing keys are rotated, revoked" |
| A-5c | **Sigstore: 검증 시각 = 로그 편입 시각(벽시계 아님)** · 단 그 시각은 서버 내부 시계라 외부에서 검증할 수 없다고 스스로 경고 | https://docs.sigstore.dev/cosign/verifying/timestamps/ : "Sigstore clients can use either the time of inclusion in Rekor or a signed timestamp provided by a trusted timestamping authority." · "this timestamp comes from Rekor's internal clock, which is not externally verifiable … the timestamp is mutable in Rekor without detection." |
| A-5d | **git: 검증 시각 = 커밋 안의 committer 날짜**(= 서명자가 적는 값) | git v2.56.0 `gpg-interface.c`: `"-Overify-time=%s", show_date(sigc->payload_timestamp …)` · 문서: "Git will mark signatures as valid if the signing key was valid at the time of the signature's creation." — 위조 가능성에 대한 공식 경고는 【미확인】 · 노출 키로 날짜를 과거로 적어 통과 가능 = 【추론: A-1d + 위 소스 결합】 |
| A-5e | Matrix: 사용자 마스터 키가 기기 키를 서명한다 · 마스터 키가 바뀌면 상대에게 알려야 한다 | https://spec.matrix.org/latest/client-server-api/ : "re-issuing a new key signed by the user's master signing key" · "that client must notify the user about the change" (기기 키 폐기 후 과거 메시지 재판정 규칙은 【미확인】) |
| A-5f | TUF: 루트 키 교체는 **옛 판과 새 판 양쪽 임계치 서명**으로만 | https://theupdateframework.github.io/specification/latest/ : "Version N+1 of the root metadata file MUST have been signed by: (1) a THRESHOLD of keys … (version N), and (2) a THRESHOLD of keys … (version N+1)." |
| A-6 | allowed_signers 는 `cert-authority`(SSH 인증서)를 지원하고, 인증서 유효 기간도 검증 시각으로 본다 | man ALLOWED SIGNERS "cert-authority …" · sshsig.c `sshkey_cert_check_authority(…, verify_time, …)` |

## 부록 B — v1 → v2 대조

| 항목 | v1 | v2 | 근거 |
|---|---|---|---|
| 중심 메커니즘 | `participants.retired_at` 칸 + `RosterEntry.retired` | **별도 표 `admission_blocks` + DB 트리거** + 앱 층 검사 | codex Q5 · C-F2·F5·F6 |
| 판정 누수 방어 | 시험(T8)에만 의존 | **구조**(명부·검증 구조체 무변경) + T8·T13 배포 게이트 | codex F5 · Fable F1 |
| 「판정 불변」 범위 | 「서버 사본만 어긋남」 | 방 상태 계산에 한정 · 쓰기 경로는 서버 판정 사용 → 누수 = 전원 쓰기 불능 | codex F5 · Fable F1 |
| 경합 | 없음(누락) | 트리거로 제거 · T12 | codex F2 |
| 코드 롤백 | 「코드 되돌림은 재배포」 | 트리거가 차단 유지 · T15 | codex F6 |
| 릴레이 수 | 1 | **2**(시험 릴레이 · 선점 등록 위험 · 결정 ⑶) | Fable F3 · 실측 |
| 마이그레이션 로컬 | 「run-local.py 가 번호순 적용」(틀림) | `migrations apply --local` 명시 · `sqlite_master` 확인 · config·D1 id 명기 | codex F6 · Fable F2 |
| 탐지 | 방마다 GET 1회 · 원장 대조 · 긴급 시 자동 은퇴 위임 요청 | 페이지 끝까지 · `body` 파싱 · 3분류 · 불완전 표시 · 2단계 원장 직조회 GET · **자동 조치 없음** · 선택 서명기 기록 | codex F3·F4 · Fable F4 |
| 결정 목록 | ⑴ 선설치 ⑵ 긴급 위임 ⑶ 일반화 ⑷ GitHub | ⑴ 선설치 ⑵ 일반화(= a2/a′) ⑶ 시험 릴레이 ⑷ GitHub ⑸ 서명기 기록 · **긴급 위임 철회** | 위 |
| 피해 모델 | 가짜 발언·새 방 | + 예산 소진 · 상주 침묵(`speak_due`) · abort 의미 정정 | codex F7 |
| 표준 해석 | NIST 「비활성」 = 은퇴 | **노출 의심 → NIST 정답은 폐기 · 유지는 위험 수용** · 3시점 구분 · 선례는 결과 유사 사례 | codex F8 · Fable F5 |
| 「다른 이름 등록 불가」 | 불가 | 가능하지만 추가 힘 없음(등록 개방) · BOM 결함은 별도 | codex F1(부분 반박) |
| (c) 선행 조건 | (b) 와 함께 flag day | 전원 명부 동기화(클라이언트 교체 아님) | codex Q5b |
| 배포 전 창 | 없음 | 임시 대응 표 | Fable F6 |
| 상주 소음 | 없음 | 차단 id `/home` `speak_due=[]` | Fable F7 |
| 시험 | T1~T9 | T1(`now` 고정·운영자 abort 방)~T17 | codex Q7 · Fable F9 |

## 부록 C — 정오표(원문 보존 문서의 오류)

| 문서 | 적힌 것 | 맞는 것 | 근거 |
|---|---|---|---|
| RESEARCH-primary-sources §7-4 | 버전 게이트 하한 「< 8.9 거부」 | 이 설계의 클라이언트는 `-Y verify` 만 쓰므로(`sign.py` L165) 기간 옵션·검증 시각의 하한은 **8.7**(`Z` 쓰면 9.1). 8.9 는 `find-principals` 수명 검사용이라 무관 | Fable F8 · RESEARCH §1.2 |
| DESIGN-v1 · REFLECTION-r1 | `RELAY.md` L546-L547 · `index.ts` L627-L631 · `roster.py` L112-L121 · `store.ts` L102 | L547-L548 · L628-L631 · L115-L121 · L103 | Fable F8 |
| DESIGN-v1 §5-1 #11 · REFLECTION-r1 G2 | 「`run-local.py` L57 이 번호순 적용」 | `events` 표가 없을 때만 적용(L46-L57) | codex F6 · Fable F2 |
| SURVEY §1·§5(초판) | `event.roster` = 세 파일 체크포인트 | `allowed_signers` 한 파일 sha256 — SURVEY 본문에서 정정함 | codex F9 |
