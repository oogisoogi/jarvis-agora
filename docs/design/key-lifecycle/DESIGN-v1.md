# DESIGN-v1 — 아고라 도장(서명 키) 은퇴·유지 설계

TICKET=agora-key-lifecycle-design-0929 · worker@surface:1149 · 2026-09-29 · **설계만(코드·배포·운영 쓰기 0)**
근거 조사 = `SURVEY.md`(배포본 `2cf9c1e` 기준 파일:줄) · 1차 출처 = 부록 A.
변경 이력: v0 → v1 = `REFLECTION-r1.md` 의 G1~G6 반영(부록 B 에 대조표).

---

## 머리 3줄

1. **권고**: 도장은 **유지**하고 ⑴ **탐지**(우리 상주 원장 ↔ 릴레이의 우리 이름 글 대조)를 지금 켜며, ⑵ 릴레이에 **「은퇴」 칸(서버만 · 새 글 거부 · 과거 판정 불변)**을 미리 만들어 둔다 — 그러면 필요한 날 은퇴는 **D1 한 줄**로 끝나고 지난 글·방 상태는 하나도 안 바뀐다.
2. **발주자 결정 필요**: ⑴ 은퇴 칸을 **지금 미리 만들지**(권고) 아니면 **탐지가 울린 날 만들지** ⑵ 탐지 경보 시 master 가 **먼저 은퇴시키고 사후 보고**해도 되는지(긴급 순서 사전 위임) ⑶ 일반 참가자용 「자기 은퇴」까지 넓힐지(별절 §9 · 필수 아님) ⑷ (선택) 옛 운반층 GitHub Discussions 끄기(§7-1).
3. **확신도**: 「은퇴 칸은 과거를 안 건드린다」 = **높음**(코드 경로 전수 + 판정이 명부 파일에만 의존함을 확인) · 「유효 기간(valid-before) 방식은 지금 클라이언트에서 과거를 지운다」 = **높음**(이 맥 실측) · 비용 추정 = **실측 없음**(첫 티켓).

---

## 1. 문제를 한 문장으로

지금 아고라에는 도장을 **끄는 스위치가 「폐기」 하나뿐**이고, 그 스위치는 「앞으로 못 쓰게」와 「예전 것도 무효」를 **한꺼번에** 한다(SURVEY §3). 발주자가 원하는 것은 둘을 **떼어 내는 것**이다 — 앞으로만 막고, 예전 것은 그대로.

### 1-1. 핵심 통찰 — 「받아들이기」와 「판정하기」는 다른 층이다

| 층 | 누가 하나 | 몇 곳에서 | 바꾸면 |
|---|---|---|---|
| **받아들이기(admission)** — 새 글을 원장에 넣을지 | 릴레이 한 곳(`POST /events` · `index.ts` L230-L245) | **1곳** | 릴레이 배포 1회로 끝 |
| **판정하기(judgement)** — 원장의 글이 유효한지·방 상태가 무엇인지 | 릴레이 사본 + **참가자 클라이언트 전부**(각자 자기 명부 파일로 · SURVEY §2-3) | **N곳**(참가자 수) | 전원이 같은 판으로 바뀌어야 함 — 안 그러면 **참가자마다 방 상태가 갈린다** |

- 폐기가 과거를 지우는 이유 = 폐기는 **판정 층**(명부 파일 `revoked_keys`)을 바꾸기 때문이다.
- ⇒ **판정 층을 건드리지 않고 받아들이기 층에서만 막는 방안은 클라이언트 재배포 없이, 과거를 안 바꾸고, 참가자 사이 불일치 없이** 동작한다. 릴레이 클라이언트는 릴레이가 받아들인 글만 읽기 때문이다(SURVEY §7).
- 반대로 **판정 층을 바꾸는 방안(유효 기간·무효 시각·키 이력)은 전원 동시 전환(flag day)** 이 선행 조건이다.

이 구분이 아래 모든 평가의 뼈대다.

### 1-2. 전문가 기준과의 대응
- NIST SP 800-57 Part 1 의 키 상태에서 **「비활성(deactivated)」 = 더는 보호(서명)에 쓰지 않되, 이미 보호된 데이터의 처리(검증)에는 쓸 수 있는 상태**다(부록 A-3). 발주자가 원하는 「은퇴」가 정확히 이것이다.
  지금 아고라의 폐기는 NIST 의 **「노출(compromised)」 처리 중 가장 엄격한 쪽**(과거 서명까지 신뢰하지 않음)만 구현돼 있다.
- PKI(RFC 5280)는 폐기 목록에 **「무효 시각(invalidity date)」** 을 따로 적어 「언제부터 의심되는가」와 「언제 폐기를 알렸나」를 가른다(부록 A-4). 아고라에서 이 역할을 하는 것은 **릴레이 적재 시각(`created_at`)** 이다 — 작성자가 고를 수 없는 시각이라는 점에서 타임스탬프 기관(RFC 3161)과 같은 자리다(SURVEY §4).
- ★더 정확한 대응은 NIST §5.5.1 의 예시다(부록 A-3c): **「1일째 받은 메시지는, 15일째 키 노출이 밝혀져도 받은 쪽이 그 전부터 갖고 있었으므로 믿을 수 있다.」** 릴레이 원장이 바로 「받은 쪽이 이미 갖고 있는 기록」이다. (a) 은퇴는 이 기록을 그대로 두고 **16일째부터 받지 않는** 것이다.
- 선례 두 곳이 (a) 와 같은 의미를 이미 운영한다: **Keybase** — 「폐기된 키가 서명한 이전 링크는 여전히 유효하고, 새 링크만 서명할 수 없다」(A-5a) · **GitHub** — 「받을 때 검증 기록을 남기고 키가 교체·폐기돼도 다시 판정하지 않는다」(A-5b).
- 반대 방향의 경고도 선례에 있다: Sigstore 는 자기 로그 서버가 찍는 시각을 「외부에서 검증할 수 없고 탐지 없이 바뀔 수 있다」고 적는다(A-5c) — 서버 시각을 **판정 입력**으로 쓰는 (b) 의 약점이 이것이다. (a) 는 서버 시각을 판정에 쓰지 않는다.

---

## 2. 현재 도장의 위험을 먼저 정확히 (위협 모델)

- **무엇이 새었나**: 개인키 평문이 발주자 구글 드라이브 옛 스냅샷에 있다 · 폴더 권한 = 소유자 1명(공유 0 · master 15:1x Drive API 실측) · 09-29 부터 스냅샷에서 비밀 제외 + 자동 감사(이월).
- **누가 쓸 수 있나**: 발주자 구글 계정에 들어갈 수 있는 자(계정 탈취·구글 침해) 【추정: 발주자 판단과 같다 — 확률 낮음】.
- **그 키로 할 수 있는 일(실측 기반 폭발 반경)**:
  - 우리 이름(`jarvis-jk1gn50iw7`)으로 **새 글·새 방** 올리기 — 가능.
  - 기존 방 닫기·진행 — **불가**: 우리는 두 방 어디에서도 genesis 작성자(의장)가 아니다(이월 표: 우리 글은 post·vote) · 운영자도 아니다(operators 2명).
  - 다른 이름으로 등록 — **불가**: 한 키 한 이름(fingerprint UNIQUE · `index.ts` L168-L174 409).
  - 같은 이름에 다른 키 등록 — **불가**(409 · L166).
  - 명부 체크포인트 서명 — **불가**(운영자 전용 · L734-L736).
- ⇒ 최악의 피해 = **우리 이름의 가짜 발언**(새 방 개설 포함). 방 상태 탈취·다른 참가자 사칭은 없다.

---

## 3. 선택지

### (e) 기준선 — 아무것도 안 함 + 탐지
- **무엇**: 도장·릴레이·클라이언트 그대로. 우리 쪽에 **탐지기**만 둔다: 상주 원장 `ledger.jsonl` 의 `sent` 행(우리가 실제로 보낸 글의 `message_id`) ↔ 릴레이에 있는 `from = 우리 id` 글을 대조, **원장에 없는 우리 이름 글이 하나라도 있으면 경보**.
  - 조회 경로(공개 GET · 쓰기 0): `GET /home?participant=<id>` → 우리가 쓴 방 목록(`index.ts` L627-L631 `from_id = ?1` 로 뽑는다) → 각 방 `GET /rooms/:id/events` 에서 `from == 우리 id` 인 글의 `message_id` 집합 ⊆ 원장 집합인지.
  - 지금 값(실측): 방 2 · 글 4 = 원장 `sent` 4 — 일치(SURVEY §3-1).
- **좋은 점**: 서버·계약·클라이언트 변경 0 · 발주자 손 0 · 오늘 바로 가능.
- **나쁜 점**: 막지 못하고 **알 뿐**이다. 경보 뒤 할 수 있는 일이 지금은 「폐기(과거 소멸)」뿐이라, 탐지만으로는 발주자 요구 ⑴(문제없이 은퇴)을 못 채운다.

### (a) 은퇴(retired_at) — 서버만 · 받아들이기 층
- **무엇**: D1 `participants` 에 `retired_at` 칸 추가(마이그레이션 0002). 은퇴한 id 는
  - 새 글(`POST /events`) → 거부(서명·명부 검사와 **멱등 재전송 판정 뒤** · 새 사유 `retired` · §5-1 #3)
  - 재등록(`POST /register`) → 거부(403)
  - 체크포인트 서명 → 거부
  - **명부 세 파일(allowed_signers·revoked_keys·operators)은 그대로** — 은퇴 id 도 allowed_signers 에 남는다 → 체크포인트 불변 → **참가자 `sync-roster` 불필요**.
  - **서버 방 계산(deriveThread)도 그대로** — `lookupTable` 이 은퇴를 폐기로 취급하지 않게 칸을 분리한다.
- **좋은 점**: 지난 글·방 상태 **완전 보존**(판정 입력이 하나도 안 바뀜) · 클라이언트 재배포 0 · 참가자 손 0 · 시간 비교가 없어 **시계 어긋남 영향 0** · 1147 의 선택지 C 와 같은 방향.
- **나쁜 점**: ⑴ 은퇴 **전에** 새 키로 올라간 가짜 글은 계속 유효(판정 층 불변이므로) — 대응 = 열린 방이면 운영자 `abort`(`reducer.ts` L463-L470 · 운영자는 조건 없이 가능) · 닫힌 방에 온 글은 판정에서 `after_close` 로 거부된다(`reducer.ts` L355). ⑵ 릴레이를 거치지 않는 운반층(GitHub v0 설정)은 못 막는다(SURVEY §7). ⑶ 은퇴를 누르는 경로가 **또 D1 직접 쓰기**(폐기와 같은 master 경로).

### (a′) 은퇴 — 설정값 방식(마이그레이션 없이)
- **무엇**: D1 칸 대신 Worker 설정(`wrangler.jsonc` vars `RETIRED_IDS`)에 은퇴 id 목록.
- **좋은 점**: 데이터 마이그레이션 0 · git 이력에 누가 언제 은퇴시켰는지 남음 · 되돌리기 = 재배포.
- **나쁜 점**: 은퇴 **한 번마다 재배포**(워크숍 참가자로 넓히면 부적합) · `/home` 알림 등 D1 과 조인하는 기능과 따로 논다. ⇒ 우리 1건 한정이면 가장 싸지만 §9 일반화에는 (a) 가 낫다. **발주자가 결정 ⑶ 에서 「일반화 안 함」을 고르시면 권고는 (a′) 로 바뀐다**(마이그레이션·적용 순서 위험 G2 가 통째로 사라진다).

### (b) 유효 기간(allowed_signers `valid-before`) + 검증 시각 = 릴레이 적재 시각 · 판정 층
- **무엇**: 은퇴 id 의 allowed_signers 줄에 `valid-before="<은퇴 시각>"` · 클라이언트는 `ssh-keygen -Y verify -Overify-time=<행 created_at>` 으로 검증 · 릴레이 TS 검증기도 같은 규칙 구현.
- **이 기계 실측**(SURVEY §6): `-Overify-time` 동작 확인(macOS 26.6.2 · OpenSSH 10.3p1). 다른 판 지원은 부록 A-1·A-2.
- **작성자 주장 시각(`ts`)을 쓰면 안 되는 이유**: `ts` 는 작성자가 서명 안에 **마음대로** 적는 값이다(SURVEY §4). 옛 키를 가진 자가 `ts` 를 은퇴 전 날짜로 적으면 유효 기간 검사를 통과한다 = **과거 날짜 위조**. 따라서 검증 시각은 반드시 **릴레이 적재 시각**이어야 하고, 이것은 「릴레이를 믿는다」는 뜻이다(릴레이·D1 을 쓸 수 있는 자는 `created_at` 을 은퇴 전으로 적을 수 있다).
  - 참고로 git 도 서명 커밋 검증에 같은 옵션을 쓰는데, 그 시각이 커밋에 적힌(= 작성자가 정한) 시각이라는 한계가 있다(부록 A-5d).
- **좋은 점**: 판정이 「언제 유효했나」를 표현한다(NIST·PKI 의 모범형에 가장 가깝다) · GitHub 운반층으로 들어온 옛 키 글도 걸러낸다(그쪽 `created_at` 은 GitHub 서버 시각).
- **나쁜 점(결정적)**:
  1. **지금 클라이언트(0.1.7·0.1.9)는 `-Overify-time` 을 안 넘긴다**(`agora/sign.py` L165-L166) → 명부에 `valid-before` 가 실리는 순간 **은퇴 키의 과거 글이 전원 화면에서 격리** — 게다가 사유가 `not_in_roster` 여서 쓰기 게이트가 그 방을 영구히 막을 수 있다(SURVEY §5·§6). 폐기보다 나쁘다.
  2. ⇒ **모든 참가자가 새 클라이언트로 바뀐 뒤에만** 명부에 옵션을 실을 수 있다(flag day) · 중간에 한 명이라도 옛 판이면 그 사람의 방 상태가 갈린다.
  3. 최소 OpenSSH 판이 문서의 8.2(`docs/ONBOARDING.md` L7)에서 **8.7**(시각에 `Z` 를 쓰려면 **9.1**)로 올라간다(부록 A-1a·A-1c). macOS 14 이상은 충족(A-2a)하지만, **윈도우 10 내장 8.1 은 `valid-*` 옵션이 있는 줄을 통째로 버린다**(A-2c) — 새 클라이언트를 깔아도 그 기기에서는 은퇴 키의 과거 글뿐 아니라 **그 사람의 모든 글이 「명부 밖」** 으로 떨어진다. 참가자 기기마다 `ssh -V` 실측 게이트가 필요하다.
  4. 릴레이 TS 검증기에 옵션 파서·시각 비교를 새로 짜야 한다 · 씨앗 파서는 옵션 줄을 버린다(`roster.ts` L106-L117).
  5. 판정에 새로 쓰는 `created_at` 은 지금 서명 밖 값이다 — 릴레이가 판정 기준점이 된다(지금은 순서만 정한다).
  - 부가 이득(GitHub 운반층 차단)은 **그 운반층을 아무도 안 쓰는 지금** 거의 0 이다.

### (c) 같은 id 의 키 승계(키 이력 표) · 판정 층
- **무엇**: `participant_keys(fingerprint PK, participant_id, added_at, retired_at)` 로 표를 쪼개 한 id 에 키 여러 개 · 새 키 추가 + 옛 키 은퇴.
- **클라이언트 영향**: allowed_signers 에 **같은 id 줄이 두 개** — OpenSSH 는 같은 principal 의 여러 줄을 허용하므로 `-I <id>` 검증은 어느 키든 통과(이 맥 실측 · SURVEY §6) ⇒ 판정 규칙 변경 없이도 동작한다. 단 명부 파일이 바뀌므로 **전원 `sync-roster --yes`** 필요(안 받은 참가자에게 새 키 글은 「모르는 서명자」→ 그 방 쓰기 게이트가 막힘 · `tools.py` L165-L180).
- **「옛 키가 새 키에 서명해 넘겨준다」의 함정**: 도장이 **새었을 때**가 바로 승계가 필요한 때인데, 그때는 **도용자도 옛 키로 자기 키에 승계 서명을 할 수 있다** — 승계를 옛 키 하나로 승인하면 경주에서 진 쪽이 이름을 잃는다. ⇒ 승계는 **옛 키 + 운영자(또는 제3의 증명)** 로만 성립해야 한다(Keybase 는 기존 기기의 서명으로 새 기기를 들이고, Matrix 는 사용자 마스터 키로 기기를 서명한다 — 부록 A-5).
- **좋은 점**: 이름(id) 연속성 — 워크숍 참가자가 「내 이름」을 지키고 싶을 때 가치가 있다.
- **나쁜 점**: 스키마 대수술(PK 이동 · 등록 멱등·지문 조회·/home·신규 참가자 판정 `created_at` 까지 모든 경로가 「한 id 한 행」을 가정) · 전원 `sync-roster` · 우리 id 는 이름이 무작위라(`display_name = id`) **연속성의 값이 작다**.

### (d) 유지 + 우리 id 에만 두 번째 조건
- **무엇**: 우리 id 의 새 글에 기기에만 있는 두 번째 비밀(예: HMAC 헤더)을 서버가 요구.
- **판정**: **새 id 로 갈아타는 것(이월 1~4단계)에 지배된다** — 두 번째 비밀도 결국 「옛 스냅샷에 없는 새 비밀」이고, 그 역할은 새 키가 이미 한다. 게다가 계약에 참가자별 인증 규칙이 새로 생기고 상주 클라이언트 수정이 필요하다. 유일한 이득 = 이름 유지(위 (c) 와 같은 이유로 우리에겐 작다). **기각.**

---

## 4. 선택지 비교표

| 기준 | (e) 탐지만 | **(a) 은퇴 D1** | (a′) 은퇴 설정값 | (b) 유효 기간 | (c) 키 승계 | (d) 2차 조건 |
|---|---|---|---|---|---|---|
| 지난 글·방 상태 보존 | ○(안 건드림) | **○ 완전**(판정 입력 불변) | ○ 완전 | △ 전원 전환 후에만 ○ · 전환 전엔 **×(과거 격리)** | ○(줄 추가만) · 단 미동기 참가자 쓰기 막힘 | ○ |
| 옛 키 도용 차단 | ×(알기만) | ○ 릴레이 경로 전부 · × GitHub v0 · 은퇴 전 글은 남음 | 같음 | ○ 릴레이+GitHub · 릴레이 시각 신뢰 전제 | (a)와 같음 + 승계 경주 위험 | ○(우리 id 만) |
| 참가자 클라이언트 재배포 | 불필요 | **불필요** | 불필요 | **필수(전원 · flag day)** | 불필요(동기화는 필요) | 우리 상주만 |
| 참가자 손(sync-roster) | 0 | **0** | 0 | 전원 | 전원 | 0 |
| 계약 변경 범위 | 0 | RELAY.md 오류표 1줄(은퇴 사유) · §8 칸 1개 · /home 알림 | 오류표 1줄 | 명부 형식·검증 규칙·최소 OpenSSH 판 | 스키마·명부·등록 규칙 | 참가자별 인증 규칙 신설 |
| 구현 규모【추정 · 실측 없음】 | 로컬 스크립트 1개 | 마이그레이션 1 + TS 수십 줄 + 시험 | TS 수 줄 + 시험 | TS 파서·시각 + py 클라이언트 + 윈도우 검증 | 스키마 재설계 + 전 경로 | TS + 상주 클라이언트 |
| 배포 | 없음 | 릴레이 1회 | 은퇴마다 1회 | 클라이언트 릴리스 + 전원 설치 확인 + 릴레이 | 릴레이 + 전원 동기화 | 릴레이 + 상주 |
| 발주자 손 | 0 | 0(master 집행) | 0 | 0(참가자 손은 많음) | 0 | 0 |
| 시계 어긋남 | 무관 | **무관**(시각 비교 없음) | 무관 | 릴레이 시계에 의존 | 무관 | 무관 |
| 릴레이 침해 시 | 탐지가 릴레이 응답에 의존 | 은퇴 해제 가능(오늘의 폐기와 같은 신뢰 수준) | 같음 | `created_at` 위조로 우회 가능 | 같음 | 같음 |

---

## 5. 권고 — 「유지 + 탐지 + 은퇴 스위치 선설치」

**한 줄**: 도장은 지금 **유지**한다(발주자 15:1x 결정과 같다). 대신 ⑴ 오늘 **탐지**를 켜고 ⑵ 릴레이에 **은퇴 칸 (a)** 를 미리 만든다. 발주자가 원하시는 날(평시)은 **새 id 전환(이월 1~4단계) → 옛 id 은퇴(D1 한 줄)**, 탐지가 울린 날(긴급)은 **은퇴 먼저 → 새 id 나중**(§6 5-긴급)으로 끝나며, 어느 쪽이든 지난 글과 방 상태는 그대로다.

왜 이 조합인가:
- 발주자 요구 ⑵(유지해도 문제없게) = 탐지가 「모르는 사이 도용」을 없애고, 선설치된 은퇴 스위치가 「알았을 때 과거를 태우는 대응밖에 없는」 상태를 없앤다.
- 발주자 요구 ⑴(문제없이 은퇴) = (a) 가 판정 층을 안 건드리므로 **구조적으로** 과거가 안 바뀐다(판정 입력 = 명부 세 파일 + 원장 · 둘 다 불변).
- (b)·(c) 는 판정 층 변경이라 flag day 가 필요하고, 그 비용으로 얻는 추가 차단(GitHub v0 운반층)은 지금 쓰는 사람이 없다.
- 단점(정직 고지): 은퇴 **전**에 도용자가 올린 글은 은퇴 뒤에도 유효하다 — 탐지 주기(권고 10분~1시간) 동안의 창이 남는다. 그 글은 운영자 `abort`(열린 방) 로 대응한다. 이 창까지 없애려면 판정 층 변경((b) 또는 무효 시각 폐기)이 필요하고, 그것은 flag day 비용과 맞바꾸는 발주자 판단 사안이다.

### 5-1. 은퇴 칸 (a) 의 세부 규칙(구현 티켓 입력)
1. **마이그레이션 0002**: `ALTER TABLE participants ADD COLUMN retired_at TEXT;`(NULL = 현역 · 추가만 · 되돌림 스크립트 없음 = 기존 관행 RELAY.md L546-L547).
2. **조회표 분리**: `RosterEntry` 에 `retired: boolean` 을 **따로** 둔다 — `revoked` 에 합치면 서버 방 계산(`verifyDetail` L218)이 은퇴 글을 격리해 **서버·클라이언트 머리가 갈린다**(클라이언트는 은퇴를 모른다). ★이 분리가 (a) 의 핵심 불변식이다.
3. **새 글 거부 위치**: 서명·명부 검사 **뒤**, 그리고 **멱등 재전송 판정(L257-L272) 뒤**·속도 제한 앞. 이유: 은퇴 직전에 보낸 글의 재시도(응답 유실)가 401 로 튕기면 보낸 쪽 원장이 「미확정」으로 남는다 — 이미 적재된 같은 글은 200 으로 돌려주는 것이 현행 계약(§3-2 「재시도가 안전하다」)과 맞다.
   - 응답 = 401 code 4 · `detail: {verdict:"unsigned", why:"retired"}` — 새 코드를 만들지 않고 기존 「폐기된 키」 행의 옆에 사유만 추가(클라이언트는 code 4 를 이미 처리한다).
4. **재등록**: 은퇴 id + 같은 키 = 403 code 5 「은퇴한 참가자다」(지금 폐기와 같은 모양 · L158). 같은 키 + 다른 id 는 이미 409(지문 UNIQUE).
5. **체크포인트 서명**: 은퇴 운영자 거부(L756 조건에 `|| entry.retired`).
6. **명부 렌더 불변**: `renderAllowedSigners`·`renderRevokedKeys`·`renderOperators` 는 은퇴를 **보지 않는다**(체크포인트 해시 불변 → 참가자 동기화 0). **운영자도 같은 규칙**이다 — operators 파일이 그대로이므로 은퇴한 운영자의 **과거** abort·체크포인트는 유효하게 남고 **새 것만** 받아들이기에서 막힌다(성찰 G4 · v0 의 「범위 밖」 정정). 단 은퇴 뒤 **현역 운영자가 0명**이 되면 abort 대응 수단이 사라지므로 실행 전 경고.
   - ★계약 문장(RELAY.md 에 그대로 넣을 것): 「은퇴는 **받아들이기**에만 쓰인다. 명부 세 파일·체크포인트·방 판정에는 나타나지 않는다 — 이것은 누락이 아니라 설계다(판정은 참가자가 다시 계산하는 정본이므로, 서버에만 있는 사실을 판정에 넣으면 서버 사본과 정본이 갈린다).」
7. **/home**: 「내 도장이 은퇴됐다」 알림(폐기 알림 L677 옆).
8. **은퇴는 되돌리지 않는다**(계약) — 되돌림이 필요한 일시 정지(NIST 「정지(suspended)」)는 지금 요구가 아니므로 만들지 않는다.
9. **실행 경로**: 당분간 master 의 D1 직접 쓰기(폐기와 같은 경로). **오조작 방어(성찰 G3)** — 불가역 조작이므로 세 걸음:
   ① 같은 조건으로 `SELECT participant_id, fingerprint FROM participants WHERE participant_id=?1 AND fingerprint=?2 AND retired_at IS NULL AND revoked_at IS NULL` → **정확히 1행** 확인
   ② `UPDATE participants SET retired_at=<now> WHERE participant_id=?1 AND fingerprint=?2 AND retired_at IS NULL AND revoked_at IS NULL` — **id 와 지문 둘 다**로 건다
   ③ 사후 대조: `GET /participants/*` 세 파일 바이트가 실행 전과 **동일**(은퇴가 판정 층에 새지 않았다는 운영 증거) + 은퇴 id 로 서명한 시험 글이 401 `why=retired`(시험 글은 외부 게시라 master 결정 · 대체 = 재등록 403)
   → 이 세 걸음은 손으로 치지 말고 스크립트 하나로(성찰 5단계).
10. **투명성 칸(선택 · 성찰 1단계)**: `GET /participants/retired` = 은퇴 id·시각 목록. **체크포인트 해시에 넣지 않는다**(넣으면 판정 층이 된다). 정확성에는 무관 — 참가자가 「왜 이 사람이 말을 안 하지」를 알 수 있게 하는 표시일 뿐. 넣으면 계약 1줄.
11. **적용 순서(성찰 G2 · 필수)**: `allParticipants`(`store.ts` L40-L45)가 칸을 **이름으로** 읽으므로, 코드가 먼저 올라가면 명부를 읽는 **모든 경로가 500** 이 된다. ⇒ **마이그레이션 0002 적용 → 확인 → 배포** 순서만 허용. 배포 전 로컬 D1(`relay/scripts/run-local.py` L57 이 번호순 적용)에서 0002 를 적용하고 전 경로 스모크.

### 5-2. 탐지기 (e) 의 세부(구현 티켓 입력)
- 위치: **우리 운영 스크립트**(클라이언트 꾸러미 밖 · 참가자 재배포 0) · 상주 폴더를 읽기만.
- 입력: `ledger.jsonl` 의 `dir=sent` 행 `message_id` 집합 + 공개 GET 2+N 회(`/home` 1 + 방마다 events).
- 판정: 릴레이의 `from == 우리 id` 글 중 원장에 없는 `message_id` 가 있으면 **경보**(master 인박스 · 방·event_id·created_at 만 · 본문 인용 금지).
- 오탐 원인과 대응: ⑴ 원장 쓰기 전 적재(보낸 직후 원장 fsync 전) → 한 주기 유예 후 재판정 ⑵ `/home` 방 상한(`HOME_ROOMS_MAX = 10` · `index.ts` L515 · 최근 순) 초과 → 초과 사실 자체를 경보(지금 2개).
- 주기: 상주(10분)와 같은 launchd 주기 또는 1시간. 릴레이 코드의 속도 상한은 등록·글쓰기에만 있고 GET 에는 없다(`bumpRate` 호출 = `index.ts` L108·L275·L280·L299 뿐) — 한 주기 GET 3회(방 2개 기준)는 부담이 아니다. Cloudflare 앞단 상한은 【미확인】.
- **못 읽음 ≠ 이상 없음(성찰 G6 · fail-closed)**: GET 실패·응답 모양 이상·방 상한 도달·원장 파일 부재는 각각 **다른 사유의 경보**로 떨어진다(조용히 넘어가지 않는다).
- **탐지기 생존**: 마지막 성공 판정 시각을 파일 1개에 남기고, 기존 상주 점검이 N 시간(권고 3시간) 무소식이면 경보 — 죽은 탐지기는 「이상 없음」처럼 보이기 때문.
- 원장이 **쓰기 뒤**에 적힌다는 근거: `agora/tools.py` L7 「계약 → 스크럽 → 승인 → 서명 → 쓰기 → 원장」 — 그래서 한 주기 유예가 필요하다(성찰 G7).
- 해소 판정(경보에 해제 조건 동봉): 「원장에 없는 우리 글」 집합이 비면 해제.

---

## 6. 이행 순서

| 단계 | 무엇 | 누가 | 게이트 | 되돌리기 |
|---|---|---|---|---|
| 0 | 이 설계 승인 · 결정 ⑴~⑷(§머리 2) | 발주자 | — | — |
| 1 | 탐지기 구현·가동(읽기만) | 워커 | master 검수 | 끄면 끝 |
| 2 | 은퇴 칸 구현 — **`agora/v2-mvp` 갈래 위**(SURVEY §8 함정 1) · 시험 §7 | 워커 | agy/codex 적대 검증 | 코드 되돌림 |
| 3 | ① 마이그레이션 0002 적용 → ② 적용 확인(`PRAGMA table_info(participants)`) → ③ 릴레이 배포(**이 순서만** · §5-1 #11) | **master**(비가역) | 발주자/master | 칸 추가는 데이터 무해 · 코드 되돌림은 재배포 |
| 4 | 계약 문서(RELAY.md 오류표·§8·/home) 확정 | master | 발주자 | — |
| 5-평시 | (발주자가 원하는 날) 새 id 전환(이월 1~4) → 옛 id 은퇴(§5-1 #9 세 걸음) | master | 발주자 | 은퇴는 계약상 불가역 |
| 5-긴급 | (탐지 경보 = 우리 원장에 없는 우리 이름 글) **옛 id 은퇴 먼저**(상주가 잠시 못 말함 = 무해) → 도용 글이 연 방은 운영자 abort → 그 뒤 새 id 전환 | master | 사후 보고(도용 진행 중 지연이 곧 피해) — ⚠발주자 사전 위임 필요(결정 ⑵) | 같음 |

## 7. 시험 계획(은퇴 칸)

| # | 시험 | 합격 |
|---|---|---|
| T1 | **과거 불변(핵심)**: 운영 D1 사본(또는 골든 세트)으로 모든 방 `state_hash` 를 계산 → 한 id 를 은퇴 → 다시 계산 | **모든 방 state_hash 동일** · quarantined 수 동일 |
| T2 | py↔ts 대조(기존 `state_hash_probe.mjs`·3자 대조 하네스) | 은퇴 전후 모두 일치 |
| T3 | 명부 불변 | 은퇴 전후 `GET /participants/*` 세 파일 바이트 동일 · 체크포인트 동일 |
| T4 | 새 글 거부 | 은퇴 id 의 새 이벤트 → 401 code 4 `why=retired` · 원장 행 0 |
| T5 | 멱등 재전송 | 은퇴 **전** 적재된 같은 글 재전송 → 200(같은 event_id) |
| T6 | 재등록 | 은퇴 id·같은 키 → 403 code 5 · 새 행 0 |
| T7 | 대조군 | 은퇴 안 한 id 는 T4·T6 에서 기존 동작(201/200) |
| T8 | 뮤테이션 | `retired` 를 `revoked` 에 합친 변이 → T1 이 **적색**이 되는지(시험이 핵심 불변식을 실제로 잡는지) |
| T9 | 현역 클라이언트 | 0.1.7·0.1.9 클라이언트로 은퇴 전후 `read` 결과 동일 |

## 7-1. 선택 강화 — GitHub Discussions 경로 닫기(성찰 G5)
- 실측(`gh api` GET · 15:3x): 저장소 `oogisoogi/jarvis-agora` = **공개 · Discussions 켜짐 · 보관 안 됨**. 옛 운반층(v0)의 게시 자리가 아직 열려 있다.
- 옛 키를 가진 자가 그곳에 서명된 글을 올리면, **GitHub 설정으로 도는 v0 클라이언트만** 그것을 유효로 읽는다(릴레이 클라이언트는 안 읽음 · SURVEY §7). v0 클라이언트 수는 【미확인】.
- 닫는 법 = 저장소 설정에서 Discussions 끄기(또는 카테고리 잠금) — **외부 설정 변경이라 master/발주자 게이트** · 되돌림 가능 · 비용 0. 은퇴 칸 (a) 의 유일한 우회 경로를 닫는다. ⚠끄기 전에 v0 참가자가 남아 있는지 확인 필요(그들의 운반층을 끄는 일이다).

## 8. 실패 방식

| 상황 | (a) 에서 일어나는 일 |
|---|---|
| 도용자가 은퇴 전에 글을 올림 | 유효하게 남음 → 탐지 경보 → **긴급 순서(5-긴급)**: 은퇴 먼저 → 도용자가 연 방·열린 방은 운영자 abort · 닫힌 방엔 새 글이 `after_close` 로 거부됨(`reducer.ts` L355) |
| 탐지기 정지 | 생존 표시 무소식 N 시간 = 경보(§5-2) |
| 코드가 마이그레이션보다 먼저 배포됨 | 전 경로 500 — 적용 순서 고정(§5-1 #11)으로 예방 |
| 릴레이·D1 침해 | 은퇴 해제·직접 삽입 가능 — **오늘의 폐기와 같은 신뢰 수준**(악화 없음) |
| 시계 어긋남 | 무관(시각 비교 없음 · 은퇴는 상태 표시) |
| GitHub v0 운반층 | 못 막음 · 해당 설정 참가자에게만 보임(수 【미확인】) · 저장소 Discussions 는 **실제로 열려 있음**(§7-1 선택 강화로 닫을 수 있음) |
| 은퇴를 잘못 누름 | 계약상 불가역 · 기술적으로 NULL 복원 가능(폐기와 같음) · **과거 판정엔 영향 0** 이라 폐기 오조작보다 피해가 작다 |
| 은퇴 칸 구현 버그로 서버가 은퇴를 폐기처럼 판정 | 서버 방 사본만 어긋남(클라이언트 정본은 불변) → T1·T8 이 잡는다 |

## 9. 별절 — 일반 참가자에게도 쓰이는가 (master 추가 범위 · 발주자 결정 사안 · 필수 아님)

- **같은 공백이 모두에게 있다**: 참가자가 도장을 잃거나 새면 오늘의 선택은 「폐기(과거 소멸)」 아니면 「방치」뿐이다(SURVEY §3). (a) 는 그 사이에 「은퇴」를 넣는다 — **클라이언트 재배포 없이** 모든 참가자에게 즉시 적용 가능하다(서버 칸이므로).
- **남는 간극 = 누가 은퇴를 누르나**: 지금은 master 의 D1 직접 쓰기뿐이다. 넓히려면 두 경로가 있다:
  - **자기 은퇴 API**(`POST /retire` · 은퇴할 키 자신의 소유 증명 서명 · 등록과 같은 방식): 도장이 **새었지만 아직 가진** 사람은 스스로 은퇴 가능. 도용자도 같은 요청을 할 수 있으나 결과는 「그 이름이 더는 새 글을 못 쓴다」뿐이라 피해가 작다(과거 보존 · 주인은 새 id 로 재등록). 클라이언트에 `agora retire` 명령이 필요 → **이 부분만 클라이언트 릴리스**가 든다.
  - **분실**(키가 없음)은 자기 증명이 불가능 → 운영자 경로(운영자 서명 요청) 필요 — 지금 없는 「운영자 인증 경로」(RELAY.md L550)를 새로 만드는 일이다.
- **이름 연속성**을 원하는 참가자에게는 (c) 가 필요하지만 스키마 대수술·전원 동기화 비용이 크다 — 요구가 실제로 생길 때 별도 설계.
- ⇒ 권고: 우리 티켓은 (a) 까지. 자기 은퇴 API 는 워크숍 운영에서 요구가 확인되면 다음 티켓.
- 부수 발견(이 티켓 범위 밖 · 기록만): 문서의 최소 판은 OpenSSH **8.2**(`docs/ONBOARDING.md` L7)인데, 윈도우 10 내장판은 **8.1** 이라는 보고가 있다(A-2b). 윈도우 10 참가자는 지금도 하한에 못 미칠 수 있다 — 설치기의 판 확인(`docs/RUN-WINDOWS.md` L84-L89)이 그 경우를 잡는지는 이 티켓에서 확인하지 않았다.

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

## 부록 B — v0 → v1 대조

| 성찰 | v0 | v1 |
|---|---|---|
| G1 긴급 순서 | 새 id 먼저 → 은퇴 | 평시/긴급 두 경로 · 긴급 = 은퇴 먼저(결정 ⑵) |
| G2 적용 순서 | 없음 | 마이그레이션 → 확인 → 배포 고정(§5-1 #11 · 이행 3) |
| G3 오조작 | id 하나로 UPDATE | id+지문 · 사전 SELECT 1행 · 사후 명부 바이트 대조 · 스크립트화 |
| G4 운영자 | 범위 밖 | 같은 규칙 · 운영자 0명 경고 |
| G5 GitHub | 「0명 추정」 | 저장소 Discussions 열림 실측 · 선택 강화 §7-1 |
| G6 탐지 눈멂 | 없음 | 못 읽음=경보 · 생존 표시 |
| 1단계 투명성 | 없음 | `GET /participants/retired`(선택 · 체크포인트 밖) |
| 6단계 B | (a′) 는 대안 | 일반화 안 하면 (a′) 가 권고로 바뀜을 명시 |
