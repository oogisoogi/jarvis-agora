# HANDOFF — TICKET=agora-spec-weekly (주간 성찰 우편 · 2026-10-06 · 292 agora-spec)

> 브리프 = master 0829589a(원장 대조 ⑴nonce ⑵surface:1291 ⑶submitted yes ⑷08:11:33 — 성립).
> 가지 `feat/spec-weekly`(off origin/main 8b81a60) · **push 0 · deploy 0 · 게시 0 · 핀 라이브 교체 0**.
> **2판**(master ca36b166 · codex 적대 1R BLOCK 6·MAJOR 10·MINOR 4 반영 + 게이트 수리 3f1ae4e0·b653203e) — 번호별 처방 = **§11 1R 반영표**.
> **3판**(master 1363219c · 재개 121e6ee0 · codex 적대 2R BLOCK 3·MAJOR 8·MINOR 3 반영) — 번호별 처방 = **§11 2R 반영표**.

## 0. 이어받기(현재 상태 · 13:1x · 라이브 완료)
- ★**라이브 완료 13:1x**(master ddd4fea6) · main = 152e3be · 릴레이 ac6c2e6b · 사이트 5277712e · 라이브 zip sha 3876029b 일치 · 데스크 d0d45e8(호환 실측 PASS = added 2 · quarantined 0 · `docs/DESK-COMPAT-0113.md` 그대로) · 시험 참가자 jarvis-test-weekly0113 보존 · 다음 = T3 팩 수집기(`TICKET=agora-t3-pack-collector` · §6 의무).
- ★**4판 = 집행 끝**(ef54d1f 본체 + 275e264 게이트 수리 + b0ac641 문서 + 이 §4 줄) · 3R(Fable · 마지막) = 수렴 예·BLOCK 0 · 번호별 = **§11-3** · 다음 = master diff 정독 + 스냅샷 게이트 → 머지(4R 없음).
- (3판 기록) 8128ba9 본체 + 95783e4 게이트 수리 + 1c7544a · 번호별 = §11-2.
- ★**3판 지시(10:02 · master 1363219c · 원장 yes) = 후임 첫 집행 대상** — 지시 원문 = master 인박스 발신 `[master#1363219c]`(판정표: BLOCK M7·N1·B5 · MAJOR M3 부분·M4·M6·M8·M10·N2·B2·B4 · MINOR N3·N4·B3 문면 · 기각 유지 B6 · M5 4종 확정 · 직전 7주 창 불변) · codex 2R 원문 = `~/axdev/master/reports/REVIEW-SPEC-WEEKLY-codex-2r.md` · 순서 = 3판 집행 → `bash tests/commit_gate.sh` 전건 PASS 줄 인용 → §11 에 「2R 반영표」 추가 → 【확인요청】 3판(상한 60분 · 중단 2h) · push 0 · deploy 0.
- **상태**: 2판 = 4a7835d(본체) + 7aab475(§4 게이트 줄) · commit_gate @4a7835d PASS · **codex 적대 2R + master 독립 스냅샷 게이트(7aab475) 가동 중** → 결과가 오면 master 가 반영분을 지시한다(새 작업은 그 지시 뒤에만).
- **확정된 결정**: 스킬 메타 서명 = 비공개층만(67d60f6c) · M5 상태 = **4종**(보냄 / 빈 생략 / 주간 없음(일일은 옴) / 일일도 없음 · 2773748b 채택) · gitleaks 역사 1건(56c3ac9 옛 뮤턴트 이름 오탐) = **스쿼시 안 함**(현 트리 0 · 머지 때 master squash-merge 판단) · 09:09·09:16 지시 = 원장 실재 진짜 발신(queued = 제출 관측 지연).
- **이어받는 사람 첫 행동**: ①이 파일 §11(1R 반영표)·§2·§3 ②`git log --oneline 8b81a60..HEAD` ③2R 반영 지시를 받으면 번호별 처방 → 커밋 → `bash tests/commit_gate.sh` PASS 줄 인용 → 【확인요청】 ④릴레이 시험 = `relay/node_modules`(본 저장소 심볼릭 링크 · 커밋 금지) · 하네스 `AGORA_PORT=<빈 포트> python3 scripts/run-local.py`(터미널의 프로세스 그룹 정리 실행으로 감싼다).
- **함정**: 공백 위생은 merge-base..HEAD 끝점 비교 — 커밋된 위반은 수리 커밋 뒤에만 풀린다 · 기계 통(signal·daily·weekly) 무승인 발신은 받는 이 = 핀 데스크일 때만(시험은 `_PinnedDesk`) · selftest·릴레이 뮤테이션이 도는 동안 해당 소스(agora/·relay/src) 편집 금지(제자리 변이).

## 0-1. 머리 3줄(1판 기록)
- **끝**: 명세 §1-3 신설 + §1-1·§1-2·§2·§4·§10·§13 개정(전부 「10-06 개정」 표기) · 릴레이 `intent="weekly"` 수용(닫힌 검증 · ISO 주 1 버킷) · 클라이언트 같은 규칙 · 데스크 주간 모드(§9 제안 묶음 · §10 비율표) · §1-2 대조 불일치 플래그 · 기계 우편 접수 회신 제외 확인.
- **시험**: 릴레이 vitest 73→**84** · 로컬 하네스 mailway **109/109**(9-c 주간 7줄 신설) · 릴레이 뮤테이션 신설 **8/8 KILLED**(M45~M52) · 클라이언트 케이스 신설 **9** · 클라이언트 뮤테이션 신설 **12/12 KILLED**(M656~M667) + 바뀐 줄을 겨누던 옛 3(M577·M578·M627) 재조준 KILLED · 전체 selftest 결과 = 아래 §4.
- **결정 1 확정(10-06 master 67d60f6c)**: 스킬 메타 서명 = 비공개층(우편)에만 · 공개 글 0(§5 · 명세 §13-2 4.).

## 1. 바뀐 것(파일 · 무엇)
| 파일 | 무엇 |
|---|---|
| `docs/SPEC-mail-1to1-2026-10-05.md` | 머리 「10-06 개정」 1단 · **§1-3 신설**(서식 표 · 빈 값 글자 목록 · 주기 = 핀 `weekly_period_days` · 빈 보고 생략 · 작성 = 그 집 master · 끄기·승인 예외 `mail_weekly`·고지 문안 · 받는 쪽) · §1-1 (4) 예외 목록 넷째 · §1-2 표 `weekly_skipped` 줄 + (4) 대조 규칙 · §2 intent 줄 · §4 표 1줄 · §4-1 1줄 · §10-2 기계 우편 회신 제외 · §10-4 주간 모드 · §10-6 설정 2칸 · §13-0 표 1줄 · §13-2 핀 줄 서식 + 스킬 메타 서명(📌) · §13-5 끄기 범위 |
| `relay/src/lib/mail.ts` | `WEEKLY_*` 상수 · `MACHINE_INTENTS` · `checkWeekly` · `isoWeekOf`·`isoWeekMonday` · `isBlank`(명시 글자 목록) · 일일 `weekly_skipped`(true 만) · 32KB 413/3 · **3판**: `evidence_ref` 형식 검사(`evidence_kind`·`evidence_id`) |
| `relay/src/lib/limits.ts` | `MailKind` 에 weekly · 버킷 `gmail-weekly-week:<from>`(7일 · 칸 경계 = 월요일 06:00 KST · `CYCLE_OFFSET_S` 3일 21시간) · 노브 `AGORA_RATE_MAIL_WEEKLY_WEEK_MAX` |
| `relay/src/lib/store.ts` | `bumpRate(..., offsetSeconds = 0)` — 기본 0 = 종전 칸 그대로 |
| `relay/src/index.ts` | 연속 규칙·받는 이 축·미읽음 SQL 4곳에서 weekly 제외 · 버킷에 `offsetS` 전달 |
| `relay/tests/unit.test.ts` · `relay/scripts/mailway.py` · `relay/scripts/mutate.py` | 시험 11 · 하네스 9-c · 뮤테이션 M45~M52 |
| `agora/mail.py` | `WEEKLY`·`MACHINE_INTENTS` · `_check_weekly`(릴레이와 같은 규칙) · `is_blank`·`iso_week_of`·`iso_week_monday` · 일일 `weekly_skipped` · 승인 예외 `mail_weekly`(owner_note 빈 통만) · 핀 `weekly_period_days`(7~28 · 기본 7) · **3판**: `evidence_ref` 검사 · `evidence_sources`·`verify_evidence`(허용 원장 대조) · 공개 `send_weekly` → 비공개 `_send_weekly`(pending `weekly_pending.json` · `rejected`·`superseded`) · `weekly_policy` = epoch ∧ effective_at · 세대 id |
| `agora/core.py` | `APPROVAL_EXEMPT_NAMES` 에 `mail_weekly`(기본값에도 포함) |
| `agora/counsel.py` | 주간 보고 = 회신·긴급 대상 아님 · `signature_mismatch`(2절 「일일 대조」 열) · 주간 모드(`desk.weekly_dow` 기본 월) · W 묶음·주간 지시문 1단·`proposals` 칸 · `ratio_table`·`weekly_status`(창 = 핀 주기 · 격주 핀에서 쉬는 주 오판 방지)·9절·10절 · 알림 줄에 주간 수 · **3판**: owner_note 만 든 주간 보고 분석(N1) · `policy_history`·`policy_at`·주기 원장 `type=policy` · 비율표 `outside` · `_weekly_retry_due` · 표본 = 고유 (세대, 주기) · BACKLOG `cycles` |
| `agora/selftest.py` | 케이스 9 · 뮤테이션 12 · 옛 3 재조준 · `bloated` 대역 함수가 새 인자를 받게 · **3판**: 케이스 5 신설 + 기존 7 갱신 · 뮤테이션 M676~M691 · 재조준 M623·M627·M663·M673·M674 |
| `docs/RELAY.md` · `docs/TRANSPORT-RELAY.md` | 릴레이 계약 §14 에 payload ⓓ·버킷 줄·`limit` 이름 · §15 대조표 M15 · 계약 해시 갱신 |
| `config/desk-pin.txt` | 주석 1줄(`weekly_period_days` 줄 서식) — **값 줄 없음 = 기본 7** · 라이브 교체 아님 |

## 2. 작성자 판단(지시 없이 내린 것 — master 검수 대상)
> ※**2판에서 바뀐 것**: 1(week ±1 → `cycle` 미래 금지·직전 7주) · 4(월 00:00Z → 월 06:00 KST) · 5(7~28 → {7,14,28}+epoch+effective_at) · 6(회귀 문턱 → 판정 0) · 10(빈 보고 함수 삭제 → 공개 API 복원) — 정본 = §11.
1. **주기 칸 = `cycle`**(옛 `week` 폐지) · 주는 **월요일 06:00 KST 경계**(+3시간 UTC 날짜의 ISO 주) · **미래 금지 · 직전 7주까지**(주기 최대 28일 → 직전 주기 시작은 7주 전까지 · master 결정 「직전 7주 창 불변」) · 기준 = 봉투 ts(릴레이는 서버 시각도).
2. **릴레이도 빈 보고를 거부**(`weekly_empty` · 보내는 쪽 「빈 보고 생략」의 서버 쪽 짝 — 버킷을 빈 통이 태우지 않게).
3. **「빈 값」 = 명시 글자 목록**(JS `trim()` ↔ 파이썬 `strip()` 공백 집합 차이 실측 — U+FEFF ↔ `\x1c-\x1f`·U+0085). 양쪽 같은 시험 벡터.
4. 버킷 칸 경계 = **월요일 06:00 KST**(= 일요일 21:00Z · 고정창 7일을 3일 21시간 옮김 · `cycle` 검증·데스크와 같은 선 하나).
5. 주기 = **닫힌 집합 {7, 14, 28}** · 14·28 = `weekly_epoch` ∧ `weekly_effective_at` **둘 다** 있고 그 시각이 지났을 때만(3판 M4) · 그 밖·못 읽음 = 7 · 정책 세대 id = `<주기>/<위상>/<효력 시각>`.
6. 비율표 = **원자료만 · 판정 0**(회귀 문턱·`desk.regress_ratio` 삭제 · 문턱은 4주 실측 뒤 master) · 분자 = 분모에 든 (참가자, 날)만 · 분모 밖이 있으면 비율 없음(3판 M6). 창 = **배치 날 포함 7일**(월요일 첫 판 신호가 그날 것으로 들어오게).
7. 비율표 분자 = (참가자, 날, `source`) 수 · 한 (참가자, 날) 몫 ≤ 그날 좌석 수 / 분모 = 그 판본(host·pack 중 하나)인 일일 보고의 `seats.count` 합(좌석 칸 없는 보고는 분모 밖).
8. 주간 보고는 **긴급 규칙 대상 아님**(가설 재료).
9. 대조 「같은 날」 = 두 우편 **봉투 ts 의 `day_of`**(06:00 KST).
10. 보내는 쪽 「빈 보고 생략」 판정 = 공개 함수 `mail.weekly_is_empty`(2판 복원 · `send_weekly` 가 부른다 = 배선됨) · 공개 발신 `send_weekly` 만 허용목록(티켓 결박 · §6).

## 3. 릴레이 deploy 게이트·되돌리기(master 집행용 · 워커 실행 0 · 2판 B5 로 고침)
**게이트 순서(앞 단계 실측 PASS 없이 다음 단계 금지)**
1. **릴레이 deploy** — 병합판 `cd relay && unset NODE_OPTIONS && npx vitest run`(87/87) · `AGORA_PORT=<빈 포트> python3 scripts/run-local.py` rc 0(`== 결과: PASS ==` · 우편 110/110 · 클라이언트 왕복 14/14) → `npx wrangler deploy --config <절대경로>/relay/wrangler.jsonc`. D1 마이그레이션 없음(`git diff --stat origin/main -- relay/migrations` = 빈 줄). 라이브 스모크(쓰기 0 · 버킷 0): 서명된 weekly + 항목 `evidence_ref.quote:""` → 400·10·`evidence_required`(옛 판 = `intent 가 계약 밖`) · `evidence_ref.kind:"file"` → 400·10·`evidence_kind`.
2. **데스크 클라이언트 호환 확인** — 상담소 데스크 설정 폴더의 클라이언트를 이 판(0.1.13 후보)으로 올린 뒤, 시험 참가자 키로 `weekly` 1통(빈 owner_note) + `weekly_skipped` 든 daily 1통을 데스크에 보내 데스크 `mail.sync` 결과 `quarantined` 0 · `added` 2 를 실측. ⚠이 단계 전에는 1.1.8 발행 금지 — **옛 데스크 클라이언트는 weekly 와 `weekly_skipped` 든 일일 보고를 격리하고 커서를 넘긴다**(업그레이드 뒤 자동 재수신 안 됨 · codex B5 실측).
3. **1.1.8 팩 발행** — 2 의 PASS 줄을 인용한 뒤에만.

**되돌리기(「데이터 되돌림 불요」 문구 삭제 — 틀렸다)**
- 원칙 = **forward-fix**(릴레이를 옛 판으로 되돌리지 않는다). 옛 릴레이 SQL 은 미읽음·연속 규칙에서 `weekly` 를 빼지 않아, weekly 행이 적재된 뒤 되돌리면 **사람 미읽음으로 센다**(데스크 뱃지·받는 이 미읽음 상한 오염).
- ★**옛 릴레이 SQL 실측(3판 B5 · main 8b81a60 `relay/src/index.ts`)** — `acked_at` 격리로는 **부족하다**(2판 ⑴ 폐기):
  · 미읽음 2곳 = `acked_at IS NULL` 을 본다 → acked_at 로 빠진다: 받는 이 미읽음 상한 `:981` · 수신 `UNREAD` `:1096`.
  · ⚠**연속 규칙 `:965~969` = `acked_at` 을 안 본다**(`intent NOT IN ('signal', 'daily')` 만) → weekly 행이 참가자→데스크 「연속」 계수에 들어가 그 참가자의 **사람 우편이 429 `mail_consecutive` 로 막힐 수 있다**.
  · ⚠영수 `:1113`(`acked_at IS NOT NULL`) → acked_at 을 채우면 weekly 보낸 이에게 **거짓 읽음 영수**가 간다 · 덤 삭제 `:1039` = 본문이 지워진다.
- 부득이 되돌리면(master D1 집행 · 순서 고정):
  ⑴ **백업** — `npx wrangler d1 execute <우편 DB> --remote --json --command "SELECT * FROM mail WHERE intent = 'weekly'" > weekly-backup-<시각>.json` · ★검증 = 같은 때 `SELECT COUNT(*) FROM mail WHERE intent = 'weekly'` 값 = 백업 파일 행 수 · `shasum -a 256 weekly-backup-<시각>.json` 값을 기록(4판 N10).
  ⑵ **격리 = 삭제** — `DELETE FROM mail WHERE intent = 'weekly'`(옛 SQL 세 곳(연속·미읽음·영수)에서 모두 빠지는 유일한 길 · 새 표식 칸은 옛 SQL 이 모른다) → 옛 판 deploy. ⚠스키마 주석 「행은 지우지 않는다」(`relay/migrations/0003_mail.sql:3`)의 **되돌리기 한정 예외**(master 집행 · 이 절차 밖 삭제 0).
  ⑶ forward-fix 판 재배포 뒤 필요하면 ⑴ 백업으로 재적재 — ★재적재 전 백업 파일의 행 수·sha256 이 ⑴ 기록과 같은지 대조 → 행마다 `INSERT INTO mail (message_id, thread_id, from_id, to_id, prev, reply_to, intent, hash, bytes, canonical, signature, keep_until, created_at, purged_at, acked_at) VALUES (…백업 값…) ON CONFLICT (from_id, message_id) DO NOTHING`(`seq` 는 새로 매긴다 = 옛 mail_id 와 다르다 · 데스크 적재 = `(from,message_id)` 한 번만 = 중복 0).
  ⑷ **데스크 쪽 격리분 재생** — 데스크 설정 폴더 `mailbox/quarantine.jsonl` 의 `contract` 사유 weekly·daily 줄 `mail_id` 중 최소 seq 를 `n` 이라 할 때 `mailbox/cursor.json` 의 `since` = **`ml_<n − 1 을 16자리 0 채움>`**(= `min(mail_id) − 1` · 수신은 `since` **보다 큰** 것만 받는다 — 최소값 그대로면 그 첫 통을 잃는다 · `agora/mail.py` 의 `hold - 1` 커서 관례와 같다) → 새 판 클라이언트로 `agora mail inbox` 1회(중복 0).

## 4. 전체 게이트
- **4판(커밋 b0ac641) `bash tests/commit_gate.sh` = `== 결과: PASS ==` rc 0** — 공개 표현 0 · 비밀 누출 0 · selftest **587/587 PASS · 633/633 KILLED · NOT-APPLIED 0** · F-1 25/25 · codex 0.1.4 사후 11/11 · 공백 위생 clean · 릴레이 vitest **87/87**(relay/ 는 8128ba9 이후 무변경). 1차(ef54d1f) = FAIL 586/587 — M690 앵커 미이동(pending 저장 줄 재구성) → 275e264 수리.
- **3판(커밋 95783e4) `bash tests/commit_gate.sh` = `== 결과: PASS ==` rc 0** — 공개 표현 0 · 비밀 누출 0 · selftest **587/587 PASS · 632/632 KILLED · NOT-APPLIED 0** · 미발생 오류코드 0 · F-1 재현 25/25 · codex 0.1.4 사후 재현 11/11 · 공백 위생 clean · 릴레이(8128ba9 · src 이후 무변경): vitest **87/87** · 로컬 하네스 rc 0(`== 결과: PASS ==` · 우편 **110/110**(「근거 출처 종류 밖 = 400/10 evidence_kind」 신설) · 클라이언트 왕복 14/14) · 뮤테이션 M45~M55 **11/11 KILLED**(M54·M55 신설 · M47 재조준).
  · 1차 commit_gate(8128ba9) = **FAIL**(정직): 케이스 579/587 — 새 픽스처 `_ev` 가 같은 파일의 광장 픽스처 `_ev`(selftest.py:13517)를 덮어 광장·피드 7 케이스 TypeError + M623 앵커 미이동 1 → 그 여파 NOT-APPLIED 21 · 수리 = 95783e4(`_wev` 개명 · M623 재조준) · 대상 케이스 재실행 0 적색.
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
- ★**T3 의무(3판 B2 · `TICKET=agora-t3-pack-collector`)** = `send_weekly`·`weekly_is_empty` 호출자 + 주기 스케줄 + 업데이트 공지 고지 + `weekly_skipped` 생성 + 윈 실기 · 허용목록 `send_weekly` 줄 삭제 조건 = T3 머지(게이트가 호출부 실재로 대체 · 남으면 규칙 ⑶ 적색) · T3 계약 추가 = 신호 원장 보낸 줄은 **같은 바이트**로 옮겨 적기(훅 줄 id = 원문 해시 · 명세 §1-3 (4)) · `send_weekly` 반환 `rejected`·`pending`·`superseded` 처리.
- ★**자동 수리 레인(3판 B4)** = `TICKET=agora-autofix-lane-118`(우리 쪽 도구 · 기본 OFF · 1.1.8 발행 게이트 의존 · 켜기 = master) · 이 티켓 코드 0.
- ★**T3 계약(4판 N6)** = 작성기는 `send_weekly` 전에 `mail.verify_evidence` 를 먼저 부르고 **거부 0 일 때만** 발신한다(부분 발신 뒤 같은 주기 재발신 없음 · 버킷 주 1 · `send_weekly` 의 빼기는 마지막 그물) · pending `expired` 반환(23시간·429 = 새 문서)을 처리한다.
- **BACKLOG(다음 판 · 3R MINOR · master 95aceb00)**: N7 주 단위 재시도가 비정상 종료 경로(호출 원장 `called` ∧ 주기 줄 0)를 못 봄 · N8 인용 최소 의미(토큰 1개 이상 일치) · N9 `rejected` 영속(`mailbox/weekly_rejected.jsonl`) · N11 `policy_at` = 목록 순서가 아니라 효력 시작 최대값 선택. (+ 3R N12 의 `relay/src/lib/limits.ts:54` 주석 「월요일 00:00Z」 = 4판 범위(HANDOFF 두 줄) 밖이라 손대지 않았다 — 다음 판.)
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

## 11-2. 2R 반영표(codex 적대 2R · `~/axdev/master/reports/REVIEW-SPEC-WEEKLY-codex-2r.md` · master 판정 1363219c · 3판)
| # | 판정 | 처방(1줄) · 자리 |
|---|---|---|
| M7 | BLOCK 채택 | 자유문 `evidence` 폐지 → 구조화 `evidence_ref{kind hook·sig·cmd, id 종류별 형식, quote ≤120 한 줄}` · 송신 클라이언트 `mail.evidence_sources`(허용 원장 `counsel/signals*.jsonl` 필드에서만 원문 생성)·`verify_evidence`(quote ⊂ 원문) · `send_weekly` = 못 맞춘 항목 빼고 `rejected` 반환(전부 빠지면 발신 0) · `mail_weekly` 예외 = ∧ 전건 통과 · 릴레이 = 형식만(`evidence_kind`·`evidence_id`) · 스크럽 2중 그대로 |
| N1 | BLOCK 채택 | `need_analysis` = 담긴 주간 보고 수(항목 0·owner_note 만이어도) · 지시문 주간 1단 조건 같음 · 보고서 9절 「주간 보고 오너 한 줄」 · 분석 실패 = 처리 완료 0(시험 양·음) |
| B5 | BLOCK 채택 | §3 되감기 = `min(mail_id) − 1`(since 관례 · `hold - 1` 과 같음) · 옛 SQL 실측: 미읽음 2곳(:981·:1096)은 acked_at 을 보나 **연속 규칙(:965~969)은 안 봄**·영수(:1113) 거짓 읽음 → acked_at 격리 폐기 · 백업 → `DELETE … intent='weekly'` → 옛 판 → forward-fix 뒤 재적재 |
| M3 | 부분(창 불변) | 직전 7주 창 = master 결정 불변 · BACKLOG 후보 `cycles` = 항목 **실제** payload 주기 · 항목 신호 창 = 그 보고가 온 시각의 정책 세대 길이(`policy_at`) |
| M4 | 채택 | 14·28 = `weekly_epoch` ∧ `weekly_effective_at` 둘 다 · `weekly_policy` 반환에 `effective_at`·`generation`(`<주기>/<위상>/<효력>`) · 주기 원장 `type=policy` 줄(세대 바뀔 때) + cycle 줄에 세대·효력 · `policy_history`·`policy_at` = 전환 전 자료는 옛 정책 |
| M6 | 채택 | 분자 = 분모 `seats_of` 에 든 (참가자, 날)만 · `outside` 열 · 하나라도 있으면 `ratio=None`(「-(모집단 불일치)」) · 재현 200% 벡터 = 시험 |
| M8 | 채택 | 주기 원장 cycle 줄에 `period`(호출 시도 원장과 같은 키) · `_weekly_retry_due` = 설정 주 단위에서 그 기간 주간 모드 실패·이월 ∧ 못 묶인 주간 보고 → 같은 주 재호출 허용(하루 비용 천장 안) · 성공 뒤 셋째 = 종전 거절 |
| M10 | 채택 | 표본 = 성공 ∧ 주간 ≥1 인 cycle 줄의 **고유 (generation, cycle)** 수 · 자기시험 = 고유 주기 4개 + 같은 주기 중복이 안 세짐 |
| N2 | 채택 | `mailbox/weekly_pending.json` = 발신 **전** 문서 저장 · 같은 주기 = 그 문서만 재전송(새 id 0) · 실패 = `{"pending","doc"}` 반환(예외 대신) · 성공 = 비움 · 다른 주기 = `superseded` |
| B2 | 처리(코드 0) | 허용목록 `send_weekly` 줄 = `TICKET=agora-t3-pack-collector · 삭제 조건 = T3 머지` + 규칙 ⑵ 예외 문장(master 결정) · §6 T3 의무 1줄 · (`weekly_is_empty` 는 2판부터 `send_weekly` 가 불러 배선됨 = 허용목록 줄 없음 — 지시의 「두 줄」 중 실재는 한 줄) |
| B4 | 처리(코드 0) | §6 `TICKET=agora-autofix-lane-118` 1줄 |
| N3 | 채택 | 공개 `send_weekly(ctx, weekly)` = 주입점 0 · 언제나 `_publish` · 시험 주입 = 비공개 `_send_weekly(…, publish=)` · 시험 = 시그니처 대조 |
| N4 | 채택 | 명세 예시 `cycle`·`evidence_ref` · 표 머리 「`cycle` 만 필수」 · §2 작성자 판단 1·4·5·6·10 실제 교체(월요일 06:00 KST · 닫힌 주기 · 판정 0) |
| B3 | 기각 유지 · 문면 통일 | 명세 §1-3 (2) · §13-2 2. · `mail.desk_pin` docstring = 「꾸러미 판올림으로만(= 서명 꾸러미 교체 · T3 자동 교체 포함 · 호스트 터미널 판 불요) · 우편·원격 명령으로는 불가」 같은 문장 |
| B6 · M5 | 기각 유지 · 확정 | 변경 0 |
| 새 뮤테이션 | — | 클라이언트 M676~M691(16) · 바뀐 줄 재조준 M627·M663·M673·M674 · 릴레이 M54·M55 + M47 재조준 · ⚠번호 M690·M691 은 옛 주석의 「690 대역」과 숫자가 겹친다(현 저장소 모든 가지에 M69x 실재 0 — git grep 실측) |

## 11-3. 3R 반영표(Fable 적대 3R · 마지막 · `~/axdev/master/reports/REVIEW-SPEC-WEEKLY-fable-3r.md` · 수렴 예 · BLOCK 0 · master 판정 95aceb00 · 4판)
| # | 판정 | 처방(1줄) · 자리 |
|---|---|---|
| N5 | MAJOR 채택 | `_send_weekly` = pending `at` 23시간 초과 또는 직전 429(`rate_limited` 표식) → `resend=False` · 새 문서 · 반환 `expired`·`superseded` · 시험 = 24h 경과·429 각각 새 문서 · 뮤테이션 M692 신설 · M679 재조준(`same` 줄) — ef54d1f |
| N6 | 계약 · 코드 0 | `_send_weekly` docstring · 명세 §1-3 (4) = 「빠진 항목은 그 주기 제외 · T3 작성기는 send 전 `verify_evidence` 선행·거부 0 일 때만 발신」 · §6 T3 계약 1줄 |
| N10 | 문서 | §3 ⑴ 백업 검증(COUNT = 행 수 · sha256 기록) · ⑵ 스키마 「행은 지우지 않는다」의 되돌리기 한정 예외 · ⑶ 재적재 전 행 수·sha 대조 + `INSERT … ON CONFLICT (from_id, message_id) DO NOTHING` |
| N12 | 문서 | §1 limits.ts 줄 「offsetS 4일 = 월 00:00Z」 → 월요일 06:00 KST · counsel.py 줄 `desk.regress_ratio` 삭제 (relay `limits.ts:54` 주석은 범위 밖 · §6 BACKLOG) |
