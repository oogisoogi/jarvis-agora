# HANDOFF — TICKET=agora-spec-weekly (주간 성찰 우편 · 2026-10-06 · 292 agora-spec)

> 브리프 = master 0829589a(원장 대조 ⑴nonce ⑵surface:1291 ⑶submitted yes ⑷08:11:33 — 성립).
> 가지 `feat/spec-weekly`(off origin/main 8b81a60) · **push 0 · deploy 0 · 게시 0 · 핀 라이브 교체 0**.

## 0. 머리 3줄
- **끝**: 명세 §1-3 신설 + §1-1·§1-2·§2·§4·§10·§13 개정(전부 「10-06 개정」 표기) · 릴레이 `intent="weekly"` 수용(닫힌 검증 · ISO 주 1 버킷) · 클라이언트 같은 규칙 · 데스크 주간 모드(§9 제안 묶음 · §10 비율표) · §1-2 대조 불일치 플래그 · 기계 우편 접수 회신 제외 확인.
- **시험**: 릴레이 vitest 73→**84** · 로컬 하네스 mailway **109/109**(9-c 주간 7줄 신설) · 릴레이 뮤테이션 신설 **8/8 KILLED**(M45~M52) · 클라이언트 케이스 신설 **9** · 클라이언트 뮤테이션 신설 **12/12 KILLED**(M656~M667) + 바뀐 줄을 겨누던 옛 3(M577·M578·M627) 재조준 KILLED · 전체 selftest 결과 = 아래 §4.
- **결정 1 확정(10-06 master 67d60f6c)**: 스킬 메타 서명 = 비공개층(우편)에만 · 공개 글 0(§5 · 명세 §13-2 4.).

## 1. 바뀐 것(파일 · 무엇)
| 파일 | 무엇 |
|---|---|
| `docs/SPEC-mail-1to1-2026-10-05.md` | 머리 「10-06 개정」 1단 · **§1-3 신설**(서식 표 · 빈 값 글자 목록 · 주기 = 핀 `weekly_period_days` · 빈 보고 생략 · 작성 = 그 집 master · 끄기·승인 예외 `mail_weekly`·고지 문안 · 받는 쪽) · §1-1 (4) 예외 목록 넷째 · §1-2 표 `weekly_skipped` 줄 + (4) 대조 규칙 · §2 intent 줄 · §4 표 1줄 · §4-1 1줄 · §10-2 기계 우편 회신 제외 · §10-4 주간 모드 · §10-6 설정 2칸 · §13-0 표 1줄 · §13-2 핀 줄 서식 + 스킬 메타 서명(📌) · §13-5 끄기 범위 |
| `relay/src/lib/mail.ts` | `WEEKLY_*` 상수 · `MACHINE_INTENTS` · `checkWeekly` · `isoWeekOf`·`isoWeekMonday` · `isBlank`(명시 글자 목록) · 일일 `weekly_skipped`(true 만) · 32KB 413/3 |
| `relay/src/lib/limits.ts` | `MailKind` 에 weekly · 버킷 `gmail-weekly-week:<from>`(7일 · `offsetS` 4일 = 월요일 00:00Z 칸) · 노브 `AGORA_RATE_MAIL_WEEKLY_WEEK_MAX` |
| `relay/src/lib/store.ts` | `bumpRate(..., offsetSeconds = 0)` — 기본 0 = 종전 칸 그대로 |
| `relay/src/index.ts` | 연속 규칙·받는 이 축·미읽음 SQL 4곳에서 weekly 제외 · 버킷에 `offsetS` 전달 |
| `relay/tests/unit.test.ts` · `relay/scripts/mailway.py` · `relay/scripts/mutate.py` | 시험 11 · 하네스 9-c · 뮤테이션 M45~M52 |
| `agora/mail.py` | `WEEKLY`·`MACHINE_INTENTS` · `_check_weekly`(릴레이와 같은 규칙) · `is_blank`·`iso_week_of`·`iso_week_monday` · 일일 `weekly_skipped` · 승인 예외 `mail_weekly`(owner_note 빈 통만) · 핀 `weekly_period_days`(7~28 · 기본 7) |
| `agora/core.py` | `APPROVAL_EXEMPT_NAMES` 에 `mail_weekly`(기본값에도 포함) |
| `agora/counsel.py` | 주간 보고 = 회신·긴급 대상 아님 · `signature_mismatch`(2절 「일일 대조」 열) · 주간 모드(`desk.weekly_dow` 기본 월 · `desk.regress_ratio` 기본 0.10) · W 묶음·주간 지시문 1단·`proposals` 칸 · `ratio_table`·`weekly_status`(창 = 핀 주기 · 격주 핀에서 쉬는 주 오판 방지)·9절·10절 · 알림 줄에 주간 수 |
| `agora/selftest.py` | 케이스 9 · 뮤테이션 12 · 옛 3 재조준 · `bloated` 대역 함수가 새 인자를 받게 |
| `docs/RELAY.md` · `docs/TRANSPORT-RELAY.md` | 릴레이 계약 §14 에 payload ⓓ·버킷 줄·`limit` 이름 · §15 대조표 M15 · 계약 해시 갱신 |
| `config/desk-pin.txt` | 주석 1줄(`weekly_period_days` 줄 서식) — **값 줄 없음 = 기본 7** · 라이브 교체 아님 |

## 2. 작성자 판단(지시 없이 내린 것 — master 검수 대상)
1. **`week` 창 = 봉투 ts 의 ISO 주 ±1주**(브리프 「봉투 ts ±7일」을 「두 주의 월요일이 7일 이내」로 읽었다 = 같은 주·앞 주·다음 주). ISO 주는 **UTC** 기준.
2. **릴레이도 빈 보고를 거부**(`weekly_empty` · 보내는 쪽 「빈 보고 생략」의 서버 쪽 짝 — 버킷을 빈 통이 태우지 않게).
3. **「빈 값」 = 명시 글자 목록**(JS `trim()` ↔ 파이썬 `strip()` 공백 집합 차이 실측 — U+FEFF ↔ `\x1c-\x1f`·U+0085). 양쪽 같은 시험 벡터.
4. 버킷 칸 경계 = **월요일 00:00Z**(`week` 검증과 같은 주 · KST 월요일 09:00). 
5. `weekly_period_days` 범위 = **7~28**(7 미만 = 릴레이 주 1 에 걸림 · 28 = 4주) · 못 읽으면 7.
6. 회귀 문턱 = **10% + 직전 판 2배**(설계 ⑦ 에 숫자 없음 · 「실측 없음 · 4주 실측으로 교정」 표기). 창 = **배치 날 포함 7일**(월요일 첫 판 신호가 그날 것으로 들어오게).
7. 비율표 분자 = (참가자, 날, `source`) 수 · 한 (참가자, 날) 몫 ≤ 그날 좌석 수 / 분모 = 그 판본(host·pack 중 하나)인 일일 보고의 `seats.count` 합(좌석 칸 없는 보고는 분모 밖).
8. 주간 보고는 **긴급 규칙 대상 아님**(가설 재료).
9. 대조 「같은 날」 = 두 우편 **봉투 ts 의 `day_of`**(06:00 KST).
10. 보내는 쪽 「빈 보고 생략」 판정 함수는 **두지 않았다** — 배선 게이트(「안 불리는 정의 0」 · 허용목록 규칙 ⑵ 「나중에 쓸 것은 사유가 아니다」)가 막아서다. 판정 규칙 = 명세 §1-3 (1) 「빈 보고 거부」와 같다 · 구현 = T3 작성기(1차 전체 selftest 에서 이 게이트가 적색 1을 냈고 함수를 지워 해소).

## 3. 릴레이 deploy 체크리스트(master 집행용 · 워커 실행 0)
0. 순서 = **릴레이 deploy → 상담소 데스크 클라이언트를 이 판(0.1.13 후보)으로 → 그 뒤 1.1.8 팩 발행**. ⚠옛 릴레이는 `weekly` 를 400/10 으로, **옛 데스크 클라이언트는 `weekly` 우편과 `weekly_skipped` 칸이 든 일일 보고를 격리**한다(모르는 intent·칸) — 데스크 갱신이 1.1.8 보다 늦으면 그동안 일일 보고까지 격리된다.
1. 병합판에서 `cd relay && unset NODE_OPTIONS && npx vitest run` = 84/84 · `AGORA_PORT=<빈 포트> python3 scripts/run-local.py` = `== 결과: PASS ==`(mailway 109/109).
2. **D1 마이그레이션 없음**(`mail.intent` 는 CHECK 없는 TEXT · `rate_windows` 재사용 · `relay/migrations/` 변경 0 — `git diff --stat origin/main -- relay/migrations` = 빈 줄).
3. `npx wrangler deploy --config <절대경로>/relay/wrangler.jsonc`(master). 노브 추가 불요(기본 1).
4. 라이브 스모크(쓰기 0 · 버킷 0 — 검증 단계에서 끝나는 요청만): 명부 참가자 키로 서명한 `intent="weekly"` + 항목 `evidence:""` → **400 · code 10 · detail.why `evidence_required`**(옛 판이면 `intent 가 계약 밖`). `{"week": …}` 만 → `weekly_empty`.
5. 되돌리기 = 직전 배포판 재배포(스키마 변경 0 이라 데이터 되돌림 불요).

## 4. 전체 게이트
- 클라이언트 전체 `selftest.run()`(커밋 56c3ac9 트리 · 08:52 끝): **케이스 580/580 PASS · 뮤테이션 608/608 KILLED · NOT_APPLIED 0 · 미발생 오류코드 0 · ok=True**.
  · 1차 전체 실행(커밋 전)은 579 중 1 적색 = 「배선: 안 불리는 정의 0」(`weekly_is_empty` · 부르는 곳 없음) + 그 여파 M208 NOT-APPLIED → 함수 삭제로 해소(§2-10) · 2차 = 위 초록.
- 릴레이(커밋 7d28ef1 · src 이후 무변경): vitest **84/84** · 로컬 하네스 기준선 PASS(mailway 109/109 · 클라이언트 왕복 13/13) · 뮤테이션 M45~M52 **8/8 KILLED**(`isBlank` 교체 뒤 재실행).
- 적대 검증 = master 발주(브리프 §4) — 워커 자체 codex 라운드 0.

## 5. ✅ 결정 확정(개인정보 경계 · 브리프 §3 · master 67d60f6c = 권고 채택)
- **스킬 메타 서명의 공개층 동봉** — 기본 층이 공개(§12 ①)라 공개 방 글에 서명 목록을 실으면 그 PC 의 오류 목록이 누구에게나 보인다(서명 = 공개 규칙 해시 → 오류 이름으로 되짚을 수 있다). **권고 = 비공개층(우편)에만 동봉 · 공개 방 글 0.** 단점 = 공개 상담 글은 신호와 서명으로 안 묶인다(문자열로만). 명세 §13-2 4. = 「확정(10-06 master)」으로 고침.

## 6. 이월 · 함정
- 작성기(참가자 master 백그라운드 프롬프트·스킬) · 발신 일정 · `weekly_skipped` 싣기 · 스킬 메타 동봉 = **T3**(이 티켓은 서식·받는 쪽·데스크).
- `relay/node_modules` = 본 저장소 것 심볼릭 링크(커밋 안 함 · `.gitignore` 의 `node_modules/` 는 링크를 안 잡는다 — `git add -A` 금지).
- 데스크 주간 모드의 첫 실전 = 배포 뒤 첫 월요일 배치(07:30) — 입력 0 이면 9·10절만 결정론으로 찍힌다.
- 증류: 메모리 1건 등록 완료 `reference_js-trim-vs-python-strip-blank-set`.
- ⚠사고 1(정직): 착수 때 `cys todo-path`(역할 worker-2 상속) 파일을 보관 없이 덮어써 앞 워커(1285 · cysr-118-w2-pack · 이미 종료)의 TODO 를 잃었다 — 원문 회수 불가 · 머리 5줄과 정본 위치(그 저장소 `docs/merge/HANDOFF-118-w2.md`)를 `~/.cys/pack/round/archive_WORKER_2_TODO.cysr-118-w2-pack.2026-10-06.md` 에 남겼다.
