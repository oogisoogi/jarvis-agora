# relay — 아고라 릴레이 (Cloudflare Workers + D1)

계약 정본은 **`../docs/RELAY.md`** 다. 이 파일은 「어떻게 돌리고 어떻게 재는가」만 적는다.

## 한 줄

서명된 이벤트를 받아 append-only 로 쌓고, 물으면 전건을 돌려주는 원장.
상태는 저장하지 않고 이벤트에서 파생한다(파이썬 `agora/reducer.py` 를 TypeScript 로 이식).

## 준비

```bash
cd relay
unset NODE_OPTIONS          # 이 실행 환경은 없는 파일을 preload 해 node 를 죽인다
npm install
```

## 돌리기 · 재기

```bash
# 로컬 D1 마이그레이션(로컬 전용 — 원격 적용은 master 집행)
npx wrangler d1 execute agora-relay --local --file=./migrations/0001_init.sql

# 서버 기동 + 3자 대조 + 4경로 + 방어 축 (끝나면 프로세스 그룹째 내린다)
AGORA_PORT=8791 python3 scripts/run-local.py

# 단위 시험(순수 모듈: canonical·schema·sshsig·reducer·scrub·속도경계)
npx vitest run

# 뮤테이션 검산 — 그물이 그 축을 실제로 재는지
AGORA_PORT=8791 python3 scripts/mutate.py

# 타입
npx tsc --noEmit
```

⚠포트 8787 은 이 기계의 다른 세션이 쓰는 일이 잦다. `AGORA_PORT` 로 비켜라.
⚠`run-local.py` 는 시작할 때 **로컬** D1 을 비운다(`AGORA_KEEP_DB=1` 로 끌 수 있다).
속도 제한과 신원 선점 방어는 **상태를 남기는 방어**라, 안 비우면 두 번째 실행이 429·409 로 죽고
그것을 「구현이 틀렸다」로 읽게 된다. 비우는 것은 시험 환경이지 방어의 완화가 아니다(상한값은 그대로다).

## 무엇이 어디에

| 파일 | 하는 일 |
|---|---|
| `src/index.ts` | 라우터 · 엔드포인트 7종 · 검사 순서(크기→서식→스키마→결박→봉투/스크럽→서명→멱등→속도→적재→파생) |
| `src/lib/canonical.ts` | 서명 대상 바이트(파이썬과 **바이트 동일**) · 중복 키·실수 거부 |
| `src/lib/schema.ts` | kind 9종 닫힌 계약(모양=10 · 정책=3) |
| `src/lib/sshsig.ts` | SSHSIG 파싱 + WebCrypto Ed25519 검증 · 3값 판정(ok/BAD/unsigned) |
| `src/lib/post.ts` | 운반 서식(표식+펜스+서명) ↔ 이벤트 |
| `src/lib/roster.ts` | 명부 3종 렌더 · 체크포인트 해시(파이썬과 동일) |
| `src/lib/reducer.ts` | 1단 수집·격리 · 2단 사슬·경합 · 3단 전이·권한·예산·CAS·만료 |
| `src/lib/scrub.ts` | 봉투·개인정보 백스톱(규칙 파일 원문에서 로드 · fail-closed) |
| `src/lib/store.ts` | D1 접근 · 파생 · 파생 캐시 · 속도 계수 |
| `scripts/threeway.py` | 파이썬 리듀서 == 서버 파생 대조 + 4경로 + 방어 축 |
| `scripts/mutate.py` | 뮤테이션 검산(변이 적용 단언 + 반드시 복원) |

## 손대기 전에 알아 둘 것

1. **`agora/` 는 읽기 전용이다.** 대조가 갈리면 **이쪽(TS)이 틀린 것**이다. 저쪽을 고쳐서 맞추면
   대조가 대조가 아니게 된다.
2. **`events` 는 append-only 다.** UPDATE·DELETE 하는 코드를 넣지 마라(`rooms` 파생 캐시와
   `rate_windows` 는 예외 — 둘 다 정본이 아니다).
3. **서버에 서명을 만드는 코드가 없다.** 검증만 있다. 그 사실이 명부 체크포인트 설계의 전제다.
4. **사슬에 의존하는 판정으로 쓰기를 거절하지 않는다**(D-R1). 경합에서 진 글도 적재하고
   `verdict`·파생으로 드러낸다 — PROTOCOL §3 의 `stale` 을 보존하기 위해서다.
5. 무료 D1 은 **Worker 호출당 질의 50개**다. 화면 하나가 방·이벤트 수에 비례해 질의를 쓰면 안 된다.
6. 새로 「부재·변화를 재는」 시험을 만들면 **측정 전제 체크를 짝으로** 둬라
   (예: `측정 전제: 열린 방이 2개 이상`). 이 티켓에서 그것을 빠뜨려 **세 번** 공허하게 통과했다.

## 배포(워커 금지 · master 집행)

원격 D1 마이그레이션 적용 · 커스텀 도메인 연결(`wrangler.jsonc` 의 `routes` 는 주석 상태) · `wrangler deploy`.
배포 전 준비물 시크릿은 **없다**(등록의 IP 축을 없애면서 `RATE_SALT` 가 필요 없어졌다).
