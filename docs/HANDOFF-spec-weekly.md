# HANDOFF — TICKET=agora-spec-weekly (주간 성찰 우편 · 2026-10-06 · 292 agora-spec)

> 브리프 = master 0829589a(원장 대조 ⑴nonce ⑵surface:1291 ⑶submitted yes ⑷08:11:33 — 성립).
> 가지 `feat/spec-weekly`(off origin/main 8b81a60) · **push 0 · deploy 0 · 게시 0 · 핀 라이브 교체 0**.
> **2판**(master ca36b166 · codex 적대 1R BLOCK 6·MAJOR 10·MINOR 4 반영 + 게이트 수리 3f1ae4e0·b653203e) — 번호별 처방 = **§11 1R 반영표**.

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
> ※**2판에서 바뀐 것**: 1(week ±1 → `cycle` 미래 금지·직전 7주) · 4(월 00:00Z → 월 06:00 KST) · 5(7~28 → {7,14,28}+epoch+effective_at) · 6(회귀 문턱 → 판정 0) · 10(빈 보고 함수 삭제 → 공개 API 복원) — 정본 = §11.
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

## 3. 릴레이 deploy 게이트·되돌리기(master 집행용 · 워커 실행 0 · 2판 B5 로 고침)
**게이트 순서(앞 단계 실측 PASS 없이 다음 단계 금지)**
1. **릴레이 deploy** — 병합판 `cd relay && unset NODE_OPTIONS && npx vitest run`(86/86) · `AGORA_PORT=<빈 포트> python3 scripts/run-local.py` rc 0(`== 결과: PASS ==` · 우편 109/109 · 클라이언트 왕복 14/14) → `npx wrangler deploy --config <절대경로>/relay/wrangler.jsonc`. D1 마이그레이션 없음(`git diff --stat origin/main -- relay/migrations` = 빈 줄). 라이브 스모크(쓰기 0 · 버킷 0): 서명된 weekly + 항목 `evidence:""` → 400·10·`evidence_required`(옛 판 = `intent 가 계약 밖`).
2. **데스크 클라이언트 호환 확인** — 상담소 데스크 설정 폴더의 클라이언트를 이 판(0.1.13 후보)으로 올린 뒤, 시험 참가자 키로 `weekly` 1통(빈 owner_note) + `weekly_skipped` 든 daily 1통을 데스크에 보내 데스크 `mail.sync` 결과 `quarantined` 0 · `added` 2 를 실측. ⚠이 단계 전에는 1.1.8 발행 금지 — **옛 데스크 클라이언트는 weekly 와 `weekly_skipped` 든 일일 보고를 격리하고 커서를 넘긴다**(업그레이드 뒤 자동 재수신 안 됨 · codex B5 실측).
3. **1.1.8 팩 발행** — 2 의 PASS 줄을 인용한 뒤에만.

**되돌리기(「데이터 되돌림 불요」 문구 삭제 — 틀렸다)**
- 원칙 = **forward-fix**(릴레이를 옛 판으로 되돌리지 않는다). 옛 릴레이 SQL 은 미읽음·연속 규칙에서 `weekly` 를 빼지 않아, weekly 행이 적재된 뒤 되돌리면 **사람 미읽음으로 센다**(데스크 뱃지·받는 이 미읽음 상한 오염).
- 부득이 되돌리면: ⑴ 되돌리기 전에 `UPDATE mail SET acked_at = <지금> WHERE intent = 'weekly' AND acked_at IS NULL`(weekly 행 격리 = 미읽음·상한 계수에서 빠짐 · 본문은 다음 덤 삭제) — master D1 집행 ⑵ 데스크 쪽 격리분 재생 = 데스크 설정 폴더 `mailbox/quarantine.jsonl` 의 `contract` 사유 weekly·daily 줄의 `mail_id` 최소값으로 `mailbox/cursor.json` 을 되감고 새 판 클라이언트로 `agora mail inbox` 1회(같은 `(from,message_id)` 는 한 번만 적재 = 중복 0).

## 4. 전체 게이트
- **2판(커밋 4a7835d) `bash tests/commit_gate.sh` = `== 결과: PASS ==` rc 0** — 공개 표현 0 · 비밀 누출 0 · selftest **582/582 PASS · 616/616 KILLED** · F-1 재현 25/25 · codex 0.1.4 사후 재현 11/11 · 공백 위생 PASS. 릴레이: vitest **86/86** · 로컬 하네스 rc 0(우편 109/109 · 클라이언트 왕복 14/14 · 「핀 밖 받는 이 신호 = code 3」 신설) · 뮤테이션 M45~M53 **9/9 KILLED**.
- (아래 = 1판 기록)
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
- ⚠사고 1(정직): 착수 때 터미널의 todo 경로 명령이 준 파일(역할 worker-2 상속)을 보관 없이 덮어써 앞 워커(1285 · 1.1.8 W2 팩 티켓 · 이미 종료)의 TODO 를 잃었다 — 원문 회수 불가 · 머리 5줄과 그 티켓 정본 위치(그 저장소 `docs/merge/HANDOFF-118-w2.md`)를 팩 round 폴더의 보관 파일(`archive_WORKER_2_TODO.*.2026-10-06.md`)에 남겼다 · 도구 결함(역할 상속) = master 백로그.

## 11. 1R 반영표(codex 적대 1R · `REVIEW-SPEC-WEEKLY-codex-1r.md` · master 판정 ca36b166)
| # | 판정 | 처방(1줄) · 자리 |
|---|---|---|
| B1 | 채택 | 기계 통 예외 셋 = `is_blank(owner_note)` ∧ 받는 이 = 서명 검증된 핀 데스크(명부 키 지문 = 핀 지문) · signal·daily 도 실측상 `to` 를 안 봐서 함께 · `mail._to_is_pinned_desk`·`principal_fingerprint` · clientway 「핀 밖 = code 3」 |
| B2 | 부분 채택 | 공개 API 복원 `mail.weekly_is_empty`(빈 판정 = `is_blank`) + 전용 발신 `send_weekly` · 배선 허용목록에 「T3 호출 예정」 등재 · 작성기·일정·윈 실기 = T3 |
| B3 | 기각(문면) | 「판올림 없이」 → 「호스트 터미널 판 없이 = 아고라 클라이언트 꾸러미 핀 갱신(T3 자동 교체)」 · 원격 정책 경로 0 · 설계 §9-2 수정 = master |
| B4 | 기각 | 저위험 자동 수리 레인 = 이 티켓 범위 밖(우리 쪽 도구 · 별도 티켓) |
| B5 | 채택 | §3 = 「릴레이 → 데스크 클라이언트 호환 확인 → 1.1.8」 게이트 + 되돌리기 = forward-fix·weekly 행 격리·커서 재생 |
| B6 | 해소 | 5a941ae(스킬 메타 서명 = 비공개층만 확정) |
| M1 | 채택 | 승격 묶음 → 결정론 `backlog_candidates`(`backlog_candidates.json` · 9-3) · 반영 = master |
| M2 | 채택 | 주기 경계 = 월요일 06:00 KST 하나(릴레이 버킷 offset 3일 21시간 · `cycle` 검증 · 데스크 `cycle_week_of`) |
| M3 | 채택 | 미래 주기 금지 · 현재 또는 직전 주기(직전 7주까지) · 상태·신호 대조 = payload `cycle` 결박 |
| M4 | 채택 | 핀 `weekly_epoch`·`weekly_effective_at` · 주기 {7,14,28} 닫힘 · 위상 없는 14·28 = 7 |
| M5 | 채택 | `weekly_skipped` = 주기 id · 9-1 = 예상 참가자(최근 28일 기계 우편) 기준 4상태(보냄/빈 생략/주간 없음/일일도 없음) — 지시의 3종에 「주간 없음(일일은 옴)」을 따로 둠(꺼짐과 결함을 가르는 codex 원 요구) |
| M6 | 채택 | 비율표 = 원자료만 · 「회귀 후보」 판정·문턱·`desk.regress_ratio` 삭제 |
| M7 | 채택(문면) | §1-3 (4) 작성기 제약 = 출처 = 훅 오류 줄 id·신호 서명·명령 집계만 · 출처 키 `hook:`·`sig:`·`cmd:` 앞머리(T3 계약 · 받는 쪽 강제는 2R 판정 뒤) |
| M8 | 채택 | 주기 원장 `desk/weekly_cycles.jsonl`(성공 여부) · 밀린 weekly(주간 모드 배치 뒤에도 미처리) = 다음 배치에서 요일 무관·사람 글보다 먼저 |
| M9 | 채택 | `send_weekly` = 데스크별 안정 `thread_id`(`mailbox/weekly_thread.json`) |
| M10 | 채택 | 성공 표본 4장 도달 시 master 알림 1줄 1회(`sample_notified` 원장 줄) |
| m1 | 채택 | 승인 조건 빈 판정 = `is_blank`(`" \u3000"` 벡터) |
| m2 | 채택 | evidence 줄바꿈(CR·LF·U+2028·U+2029) = 10 `evidence_multiline`(릴레이·클라이언트) |
| m3 | 채택 | 대조 = 매 배치 최근 이틀 일일 재대조(처리 완료 무관 · 후착 신호로 해소) · 그날 것 「잠정」 |
| m4 | 채택 | 주기 원장 계수(주간 통·밀린 것·입력 B·이월·가장 오래 기다림·토큰·비용) · 9-4 표 |
| 게이트 | 수리 | 공백 위생 :31 · 공개 표현 4(SPEC :12·:135·:173 · HANDOFF :61) · gitleaks 오탐 뮤턴트 이름(M664 → `…-accept-unlisted`) · 1판 보고의 「게이트 PASS」 = **commit_gate 미실행**(selftest·vitest 만 돌렸다) — 2판부터 commit_gate 결과 줄을 보고에 인용 |
