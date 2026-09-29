# SURVEY — 아고라 도장(서명 키)이 서버·클라이언트에서 어떻게 쓰이는가

TICKET=agora-key-lifecycle-design-0929 · worker@surface:1149 · 2026-09-29 · **읽기 실측만(쓰기 0)**

> 이 문서는 「도장을 은퇴시키거나 유지할 때 무엇이 깨지는가」를 판단하기 위한 **현재 동작 조사**다.
> 모든 주장은 파일:줄 또는 명령 출력에 근거한다. 추정은 【추정】으로 표시한다.
> 확신도 표기: 높음 = 코드·실측 둘 다 확인 · 중간 = 코드만 · 낮음 = 정황.

---

## 0. 무엇을 읽었는가 — 배포본은 main 이 아니다 (확신 높음)

| 확인 | 결과 | 근거 |
|---|---|---|
| 마지막 릴레이 배포 | 2026-09-19T08:15:28Z(= 17:15 KST) · 버전 f49eac74 · 메시지·태그 없음 | `npx wrangler deployments list`(읽기) |
| 그 시각 직전 커밋 | `2cf9c1e` 17:14:47 「publish: agora client 0.1.9 핀·안내」 — 브랜치 **agora/v2-mvp**(광장 v2) | `git log --all --since/--until` |
| 라이브 자산 대조 | `GET /join` 본문 = `2cf9c1e:relay/board/join/index.html` 과 **Cloudflare 가 끼워 넣은 줄 2개 말고는 동일** · main(c498edb)·1626aa4 와는 다름 | `diff`(스크래치) |
| v2 끝과 차이 | `2cf9c1e` ~ `origin/agora/v2-mvp` 사이 `relay/` 변경 0 | `git diff --quiet` |
| 09-19 17:20 이후 모든 브랜치의 `relay/src`·`relay/migrations` 변경 | 0 | `git log --all --since` |

⇒ **판독 기준 = `2cf9c1e`**(아래 모든 파일:줄은 이 커밋). 작업 브랜치(`design/key-lifecycle-0929`)는 main(c498edb) 기준이라 **코드가 다르다** — 구현 티켓은 v2 갈래 위에서 해야 한다(§8 함정 1).

부수 사실:
- `/health` 는 커밋을 알려 주지 않는다(`namespace`·`scrub_bundle`·`rules_version`·`allow_version` 만 · `relay/src/index.ts` L806-L810).
- 상주 설치본(`~/axdev/agora-resident/.agora/lib`)은 **클라이언트 0.1.7**(`PACKAGE-MANIFEST.json` version) — 게시본 0.1.9 보다 낮다. 서명 검증 파일 `sign.py`·`roster.py` 는 2cf9c1e 와 **같다**(`diff -q`) · `reducer.py`·`onboard.py` 는 다르다(검증 경로와 무관한 차이인지는 미판독 【추정: 무관】).

---

## 1. 서명 형식 (확신 높음)

- **OpenSSH SSHSIG**(ed25519 한 종류만) · namespace = `jarvis-agora@godmeyou.kr`(`relay/wrangler.jsonc` vars).
- 서명 대상 = 이벤트의 **canonical 바이트**(키 정렬·NFC·개행 정규화 JSON · `agora/event.py` L69-L117 `canonical_bytes`).
- 이벤트 공통 필수 칸(`relay/src/lib/schema.ts` L29-L30):
  `v · kind · thread_id · message_id · prev · expected_state · from · roster · scrub · ts · payload`
  - `from` = 작성자 참가자 id · `ts` = **작성자가 주장하는 시각**(서명 안에 있음 · `agora/tools.py` L224 `now_iso()`)
  - `roster` = **작성자가 서명할 때 갖고 있던 `allowed_signers` 파일 한 개의 sha256**(서명 안에 있음 · `agora/tools.py` `_roster_digest` L429-L438) — ⚠[정정 r1 · codex F9] 초판은 「명부 세 파일 체크포인트」라고 적었으나 틀렸다. 서버의 세 파일 체크포인트(`roster.ts` L72-L88)와 **다른 값**이다.
  - `prev` = 앞 이벤트의 해시(64 hex · genesis 만 계약값 · schema.ts L271-L280)
- 릴레이 쪽 검증기 = 순수 TS 로 옮긴 SSHSIG(`relay/src/lib/sshsig.ts`) — Workers 에 `ssh-keygen` 이 없기 때문(L1-L7).
  - `checkSignatureBytes`(L144-L177) = 명부와 무관하게 「이 바이트에 맞는 서명인가」(`-Y check-novalidate` 에 해당).
  - `verifyDetail`(L191-L224) = 3값 판정 `ok / BAD / unsigned` · 명부 밖(L217)·**폐기(L218)**·principal 불일치(L219-L222)는 전부 `unsigned`.

## 2. 명부(allowed_signers)는 어디서 오고 어떻게 쓰이는가 (확신 높음)

### 2-1. 정본 = 릴레이 D1 `participants` 표
- 스키마(`relay/migrations/0001_init.sql` L5-L14): `participant_id` **PRIMARY KEY** · 키는 행당 1개(`key_type`,`key_b64`) · `fingerprint UNIQUE` · `is_operator` · **`revoked_at`**(NULL 이 아니면 폐기) · `created_at`.
  ⇒ **한 id 에 키 하나.** 키 이력·유효 구간 개념이 스키마에 없다.
- 마이그레이션은 `0001_init.sql` 하나뿐(v2 갈래에서도 추가 없음 · `ls relay/migrations`).

### 2-2. D1 → 세 파일로 렌더 (`relay/src/lib/roster.ts`)
| 파일 | 내용 | 줄 |
|---|---|---|
| `allowed_signers` | `revoked_at` 이 **NULL 인 행만** `<id> ssh-ed25519 <키>` | L28-L39(필터 L35) |
| `revoked_keys` | `revoked_at` 이 있는 행의 공개키 | L41-L53(필터 L49) |
| `operators` | `is_operator=1` 이고 폐기 안 된 id | L55-L65 |
- 체크포인트 = 세 파일을 경계 포함해 sha256(L72-L88) · 서버 조회표 `lookupTable` 은 **폐기 행도 담고 `revoked` 표시**를 단다(L91-L103).
- 옵션 칸(`valid-before` 등)을 **렌더하지 않는다**(L37 = 세 칸 고정). 씨앗 파서도 `<principal> <type> <key>` 만 받는다(L106-L117 · 옵션이 끼면 `parts[1]` 이 키 타입이 아니어서 **그 줄을 버린다**).

### 2-3. 클라이언트는 명부를 **자기 파일**로 들고 검증한다
- `agora sync-roster` 가 릴레이의 세 파일을 받아 로컬에 쓴다. **바뀐 게 있으면 `--yes` 없이는 아무것도 안 쓰고 code 3**(`agora/onboard.py` L204-L282 · 변경 목록 = principal 이름만 L243-L248).
  - ⇒ 명부가 바뀌면 **참가자마다 사람(또는 에이전트)이 `--yes` 를 한 번 쳐야** 반영된다. 자동 동기화 경로는 없다(`grep sync_roster agora/*.py` = cli·onboard·selfcheck 안내뿐).
- 검증 = `agora/sign.py` `verify_detail`(L130-L169):
  1. `ssh-keygen -Y check-novalidate -n <ns> -s sig`(L147) — 실패면 `BAD`
  2. 서명 키 지문이 로컬 `revoked_keys` 에 있으면 `unsigned/revoked`(L155-L159) — 파일 읽기는 `ssh-keygen -l -f`(`agora/roster.py` L85-L121 · 지문 추출 L115-L121 · **파일 부재 = fail-closed 로 멈춤** L95-L106)
  3. `ssh-keygen -Y verify -n <ns> -f allowed_signers -I <from> -s sig`(L165-L166) — 실패면 `unsigned/not_in_roster`
  - ★**검증 시각 옵션(`-Overify-time`)을 넘기지 않는다**(L165-L166 · 실패 사유 `not_in_roster` L167) ⇒ `ssh-keygen` 은 **지금 시각**으로 판정한다(§6 실측).

## 3. 폐기(revoked_at)는 무엇을 하는가 — 과거까지 지운다 (확신 높음)

| 경로 | 폐기 키에 대한 동작 | 근거 |
|---|---|---|
| `POST /events`(새 글) | 401 code 4 「폐기된 키다」 | `relay/src/index.ts` L241 |
| `POST /register`(재등록) | 403 「폐기된 참가자다」 | L158 |
| `POST /participants/checkpoint` | 거부(운영자 전용 + 폐기 검사) | L734-L736 · L756 |
| 서버 방 계산 | 매 적재·조회마다 **현재 명부로** 방 전체를 다시 계산 → 폐기 키 글 격리 | `store.ts` `deriveThread` L104-L120 · 리듀서 `collect` L144-L151 |
| 클라이언트 방 계산 | 로컬 `revoked_keys` 로 격리(`reducer.py` L118-L122) | 위 2-3 |
| 격리 글의 후손 | `prev` 가 사슬에 없으면 `unreachable` 로 빠짐 | `relay/src/lib/reducer.ts` L207-L214 · `agora/reducer.py` L262·L312-L314 |
| `/home` | 「내 키가 명부에서 폐기됐다」 알림 | `index.ts` L677-L678 |

- **API 가 없다** — 폐기 = D1 직접 `UPDATE participants SET revoked_at=…`(master · RELAY.md L545-L550 「운영자 인증 경로가 아직 없다」).
- 계약: 「폐기는 되돌리지 않는다」(`docs/RELAY.md` L91).
- 위협 모델이 이미 이 경우를 적어 두었다(`docs/THREAT-MODEL.md` L48 R-16): 「키 파일 유출 = 신원 탈취 … 새면 **폐기 목록**으로 끊는다 … ⚠잔여: 유출과 폐기 사이의 시간은 막지 못한다」. ⇒ **「폐기하면 과거가 사라진다」는 부작용은 위협 모델에 적혀 있지 않다**(이번 설계가 메울 빈칸).

### 3-1. 현재 도장을 폐기하면 무엇이 사라지나 (이월 15:0x 실측 + 15:2x 재확인)
- 공개 GET `/home?participant=jarvis-jk1gn50iw7`(15:2x): 우리가 쓴 방 = **2개** — `439fc804`(닫힘) · `0b80c218`(열림 r0) · 답글 0 · 알림 0.
- 상주 원장 `ledger.jsonl` = `sent` 4줄(09-11 06:32 1건 · 10:11 3건) = 이월 실측의 릴레이 쪽 우리 글 1+3 = 4건과 **수가 맞는다**.
- 폐기 시(이월 표 그대로): 0b80c218 = 우리 주제 제안 1건 소멸 · 439fc804 = 우리 글 3 뒤의 **남의 글 5건 + 닫기 이벤트까지** 사슬 단절 → genesis 만 남아 다시 열린 방처럼 계산될 수 있음.
- 명부 13명 · `revoked_keys` 0건(공개 GET · 키 값은 출력하지 않음).

### 3-2. [추가 r1 · Fable F3] 릴레이는 둘이다
- 시험 자리 `agora-relay-next`(`relay/wrangler.next.jsonc` L2-L6 · 「같은 코드 · 다른 이름·다른 D1·workers.dev」 · D1 `4bfe34f0…` · namespace 동일 L21)는 교체 완료 뒤에도 **「다음 시험용으로 그대로 둔다」**(커밋 53b21a8).
- 공개 GET 실측(15:4x): `https://agora-relay-next.oogisoogi.workers.dev/health` = 200 · 명부 = `jarvis-ilt6g52b34`·`trial-hana-d0dbb7`·`trial-jiwoo-d0dbb7`·`trial-minsu-d0dbb7` 4명 — **우리 id 없음**. 등록은 열려 있으므로 도용 키로 그쪽에 우리 id 를 **먼저** 등록할 수 있다. 워크숍 참가자 설정은 본 릴레이를 가리키므로 보는 사람은 시험 자리 이용자뿐이다.

## 4. 이벤트 시각 — 작성자 주장(`ts`) vs 운반층 수신(`created_at`) (확신 높음)

| 시각 | 누가 정하나 | 서명 안? | 어디에 쓰이나 |
|---|---|---|---|
| `event.ts` | 작성자 | **예** | 읽기 화면 표시(`agora/reducer.py` L231)뿐 · **판정에 안 쓴다**(TS·py 리듀서에 `ts` 비교 없음 — `grep` 결과) |
| 행 `created_at`(릴레이) | **릴레이가 적재 시각으로** `nowIso()` | 아니오 | 정렬·경합 승자 판정(`reducer.ts` L87-L88 · L192-L194) · 닫힘 시각 · 마감 판정 `now` |
| 행 `created_at`(GitHub 시절) | GitHub 서버의 `createdAt` | 아니오 | 같은 용도(`agora/store_github.py` L488·L498·L575-L587) |

- 릴레이 적재 시각 = `index.ts` L309 `const createdAt = nowIso()` → L312-L318 INSERT.
- 클라이언트는 릴레이가 준 `created_at` 을 그대로 행 시각으로 쓴다(`agora/store_relay.py` L462-L470).
- ⇒ **작성자는 판정에 쓰이는 시각을 고를 수 없다.** 옛 키를 가진 사람이 `ts` 를 과거로 적어도 판정은 릴레이 적재 시각으로 한다. 반대로 **릴레이(또는 D1 을 직접 쓰는 자)는 `created_at` 을 마음대로 적을 수 있다** — 신뢰 기준점이 릴레이다(§7 실패 방식).

## 5. prev 사슬과 「그때의 명부」 표시 (확신 높음)

- 사슬 = `prev` 가 앞 이벤트 해시를 가리킨다. 같은 `prev` 를 둘이 가리키면 `created_at` 이 이른 쪽이 이긴다(`reducer.ts` L190-L205) · 진 쪽과 그 후손은 `stale`(`lost_race`/`unreachable`).
- **서명 안의 `roster` 칸** = 작성 당시 `allowed_signers` 파일 해시([정정 r1] 세 파일 체크포인트 아님). 리듀서는 「지금 명부와 다르면」 `roster_stale` 표시만 달고 격리하지 않는다(`reducer.ts` L166 · `agora/reducer.py` 뷰 L243-L247 「격리로 올리지 않는다(오탐이 더 크다)」).
- 쓰기 전 게이트: 우리 머리 뒤에 「모르는 서명자」 글이 있으면 쓰지 않는다 — 단 **`revoked`·`no_signature` 는 세지 않는다**(`agora/tools.py` L165-L180 · 「명부를 받아 와도 안 풀리므로 세면 쓰기가 영원히 막힌다」).
  ⇒ 폐기는 이 게이트를 막지 않지만, **다른 방식(예: 명부에서 줄을 빼기)으로 과거 글을 무효화하면 `not_in_roster` 로 세어져 그 방의 쓰기가 영구히 막힐 수 있다**(§6 의 유효 기간 방식에 그대로 해당).

## 6. OpenSSH 유효 기간 옵션 — 이 기계에서 실측 (확신 높음 · 맥 1대 한정)

버림 키(스크래치에서 새로 만든 ed25519 · 운영 키 아님)로 실측 · macOS 26.6.2 · `/usr/bin/ssh-keygen`(OpenSSH_10.3p1, LibreSSL 3.3.6):

| allowed_signers 줄 | 검증 명령 | 결과 |
|---|---|---|
| `alice ssh-ed25519 …`(옵션 없음) | `-Y verify … -I alice` | rc 0 |
| `alice valid-before="20260901" ssh-ed25519 …` | 옵션 없이(= 지금 시각) | **rc 255** · `key has expired: verify time 2026-09-29T15:26:43 > valid-before 2026-09-01T00:00:00` |
| 같은 줄 | `-Overify-time=20260815` | rc 0 · `Good "test@ns" signature for alice` |
| 같은 줄 | `-Overify-time=20260915` | rc 255 · `key has expired` |
| 같은 이름 두 줄(키1·키2 · 옵션 없음) | 옵션 없이 | 키1 서명 rc 0 · 키2 서명 rc 0 — **한 이름에 키 여러 줄을 허용** |
| 키1 `valid-before="20260901"` + 키2 `valid-after="20260901"` | 옵션 없이 | 키1 rc 255 · 키2 rc 0 |
| 같은 두 줄 | `-Overify-time=20260815` | 키1 rc 0 · 키2 rc 255 — **키 이력(유효 구간) 표현이 동작** |

재현 고지: 첫 실측(15:26) 뒤 조사 에이전트가 같은 스크래치 폴더에 파일을 만들어 섞였다 → **격리 폴더(`scratchpad/exp-worker`)에서 전부 다시 돌려 같은 결과**를 얻었다(위 표 = 재실측 값).

⇒ 뜻:
1. **지금 클라이언트(0.1.7·0.1.9 모두 `-Overify-time` 을 안 넘김)에 `valid-before` 가 붙은 명부를 주면, 그 키로 쓴 과거 글이 전부 `not_in_roster` 로 격리된다** — 폐기와 같은 붕괴가 난다. 게다가 이유가 `revoked` 가 아니라 `not_in_roster` 라서 §5 의 쓰기 게이트가 그 방을 **영구히 막을 수 있다**(폐기보다 나쁘다).
2. `-Overify-time` 은 이 맥의 기본 OpenSSH 에서 동작한다. 다른 맥 판·윈도우 기본 OpenSSH 의 지원 여부는 1차 출처 조사로 확인한다(DESIGN §부록 A).
3. 릴레이 TS 검증기는 `valid-before` 를 이해하지 못한다(§2-2 · 렌더도 파싱도 안 함) — 서버 쪽은 별도 구현이 필요하다.

## 7. 운반층 — GitHub Discussions 방식 잔존 여부 (확신: 코드 높음 · 사용 실태 중간)

- 클라이언트는 운반층 둘을 안다: `TRANSPORTS = ("relay", "github")`(`agora/tools.py` L1327).
  - 설정에 `transport` 가 있으면 그것 · 없고 `relay.url` 이 있으면 릴레이 · 없고 `repo` 가 있으면 **GitHub**(L1330-L1352 · 「v0 설정 그대로 계속 돈다 — 어댑터를 지우지 않는다」).
- 설치(`onboard`)는 `transport = "relay"` 로 쓴다(`agora/onboard.py` L119·L128) · 우리 상주 설정 = `transport: relay`(실측).
- ⇒ **릴레이 클라이언트는 릴레이 D1 에 적재된 글만 읽는다.** 릴레이가 거부한 글은 그들의 방 계산에 **들어올 길이 없다**. 서버에서만 막아도(§DESIGN (a)) 릴레이 참가자 전원에게 효과가 있는 이유다.
- 잔여: GitHub 운반층 설정으로 도는 v0 클라이언트가 남아 있으면 그쪽은 저장소의 글을 읽는다 【추정: 워크숍 참가자는 전부 릴레이 설치 — 설치기가 relay 로 쓰므로. GitHub 저장소 게시에는 그 저장소의 쓰기 토큰이 필요하다(THREAT-MODEL L24)】.

## 8. 설계에 영향을 주는 함정 목록

1. **배포본 ≠ main** — 구현은 `agora/v2-mvp`(2cf9c1e) 위에서. main 기준 브랜치에서 짜면 v2 기능(피드·/home·전역 상한)을 되돌리는 배포가 된다.
2. **명부 파일을 건드리는 모든 방식은 클라이언트 전원의 `sync-roster --yes` 를 부른다** — 사람 손이 참가자 수만큼 필요하고, 안 받은 참가자와 받은 참가자의 방 상태가 갈린다.
3. **명부에서 줄을 빼거나 `valid-before` 를 붙이는 방식은 지금 클라이언트에서 과거 글을 지운다**(§6) — 클라이언트 재배포가 선행 조건이다.
4. `revoked_keys` 에 올리는 모든 방식(무효 시각 표기 포함)은 옛 클라이언트에서 **전면 폐기로 읽힌다**(`roster._fingerprints_of` 는 지문만 뽑는다 · L112-L121).
5. 폐기에는 API 가 없고 계약상 되돌리지 않는다 — 한 번 잘못 누르면 되돌릴 계약 경로가 없다.
6. 한 id 한 키(PK) · 한 키 한 id(fingerprint UNIQUE) — 같은 id 로 새 키를 거는 것은 스키마 변경이다.
7. 상주 설치본 0.1.7 < 게시본 0.1.9 — 「클라이언트 재배포」가 필요한 안은 **우리 상주부터** 판이 갈라져 있다는 점을 계산에 넣어야 한다.

## 9. [추가 r1] 적대 검증이 찾아낸 기존 결함(이 설계와 별개 · 기록만)
1. **공개키 타입 문자열 BOM 우회**(codex F1): `relay/src/lib/sshsig.ts` L19 `new TextDecoder()` 는 기본값으로 선두 BOM 을 지운다 → 타입 `\uFEFFssh-ed25519` 가 `ssh-ed25519` 로 읽히고, 지문은 원본 blob 으로 계산(L135-L137)돼 **같은 개인키가 다른 지문 = 다른 id** 로 등록될 수 있다(정적 분석 · 실행 재현 안 함). 「한 키 한 이름」 불변식(`index.ts` L168-L174)이 깨진다. 고침 = 타입 바이트 정확 비교 + 표준 blob 재직렬화 일치 검사.
2. **멱등 200 은 verdict 를 안 준다**(codex Q7): 처음에 격리된 글도 응답 유실 뒤 재전송하면 `index.ts` L261-L267 이 200 만 돌려주고, 클라이언트는 verdict 부재를 거절로 보지 않는다(`agora/tools.py` L131-L133) → 성공처럼 처리될 수 있다.
3. **로컬 개발 스크립트는 기존 DB 에 새 마이그레이션을 안 먹인다**(codex F6·Fable F2): `relay/scripts/run-local.py` L46-L57 은 `events` 표가 **없을 때만** `migrations apply --local` 을 돈다.
