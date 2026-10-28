# HANDOFF — 상담소 긴급 대조에서 신호 봉투 제외 (TICKET=desk-signal-urgent-exclude · 2026-10-29)

## 1. 증상과 원인
- 증상: 참가자 PC 의 자동 오류 신호(`intent=signal` 우편)가 올 때마다 master 인박스에 「상담 긴급 후보 · 갈래 install_update · 일치 낱말 update.…」 한 줄이 울렸다.
- 라이브 원장 실측(읽기만 · `~/.config/agora-desk/counsel/desk/urgent.jsonl` × `intake.jsonl`): 긴급 줄 **4건 전부 signal 우편** — 브리프의 3건에 하나가 더 있다.

  | 날짜 | 보낸이 | 우편 키 | 대화 |
  |---|---|---|---|
  | 10-06 | jarvis-test-weekly0113(시험 키) | ml_…06 | cda5fba2 |
  | 10-26 | jarvis-rdeh73s9fu | ml_…27 | 3e890698 |
  | 10-28 | jarvis-v80i2vlawm(우리 개발 기기) | ml_…32 | 65319aca |
  | 10-29 | jarvis-v80i2vlawm | ml_…33 | 65319aca |

  접수 원장 전체 = 일일 18 · 신호 10 · 주간 3 · 사람 글(notice) 1. 실사용자 긴급 0.
- 원인: `agora/counsel.py` `_mail_texts` 가 신호 우편의 `items[].error_code` 를 코드 목록으로 돌려주고, `desk_cycle` 이 그것을 그대로 `match_urgent` 에 넣었다. 긴급 표(`desk/urgent-v1.json`)의 install_update 갈래 코드 접두 `update.` 가 `update.sig_mismatch` 등에 일치.
  (모듈 머리말 ⑷ 「긴급 규칙도 사람 글만」(10-06 개정)은 문장만 있고 코드는 신호 코드를 대조하고 있었다.)

## 2. 고친 것
- `agora/counsel.py` `desk_cycle` ⑴ 우편 접수: 봉투 payload 의 `intent == "signal"` 이면 긴급 대조를 하지 않는다(`hits = []`). 접수 원장 줄·배치 입력은 그대로(신호는 여전히 접수되고 배치가 묶는다). 긴급 원장(urgent.jsonl)에도 줄이 생기지 않는다 = 배치 보고서의 「긴급 후보(알림 생략)」 수에도 안 섞인다.
- 사람 글(intent ≠ signal)·공개 방 글의 긴급 판정은 손대지 않았다.
- 판정 키 = 봉투 payload 의 intent(=`_mail_texts` 가 본문을 비우는 기준과 같은 값). 사람이 payload intent 를 signal 로 적어 보내면 그 글은 원래부터 본문이 대조에 안 들어갔다(변화 없음).

## 3. 시험
- 새 케이스 「상담소: 신호 봉투는 긴급 0 · 사람 글 1」(`_case_desk_signal_not_urgent`): 같은 판에 신호 봉투(`update.sig_mismatch`) + 사람 글 「업데이트가 안 돼요 급해요」 → 접수 2 · 긴급 알림 1 · 생략 0 · 긴급 원장 = 사람 글 대화 한 줄 · 알림 줄에 「업데이트가 안」.
- 새 뮤턴트 `M777-desk-signal-urgent`(제외 줄을 원래 대조로 되돌림) → 위 케이스가 잡는다(사전 실측: urgent 2 로 실패 = KILLED). 「상담소」 묶음에 등록.
- 기존 「긴급 규칙 양성·음성·상한」·「신호·일일은 회신 없이 접수」 그대로 PASS.
- 게이트 결과 = §6.

## 4. 신호 속 진짜 급한 패턴(여러 기기 같은 오류 폭증)은 어디서 받나 — 확인 결과
- 받는다(배치 경로): 배치 보고서 「## 2. 자동 신호 집계」(`_signal_table` · `_signal_md`)가 서명별 **횟수 합 · 보낸 참가자 수 · 판본/OS 분포 · first~last** 를 표로 낸다. 여러 기기 같은 오류 = 같은 서명 줄의 「참가자」 열이 커지는 것으로 보인다. 일일 보고와의 서명 대조 불일치도 ⚠줄로 붙는다.
- 받지 않는 것(정직 고지): **즉시 알림은 없다** — 폭증 문턱(예: 같은 서명 참가자 N 이상)으로 울리는 장치는 원래 없고 이번에도 만들지 않았다(브리프 범위 밖). 배치 주기(하루/주) 만큼 늦게 보인다. 필요하면 별도 티켓 후보.

## 5. 남은 것 · 함정
- 📌 같은 모양의 구멍이 하나 더 있다(범위 밖이라 안 고침): **일일 보고(`intent=daily`)의 `updates[].result` 가 ok 가 아니면** 그 값이 코드로 긴급 대조에 들어간다(`_mail_texts` · result 형식 = `^[a-z0-9._-]{1,48}$`). result 가 `update.…` 모양이면 신호와 똑같이 긴급이 울린다. 라이브 일일 18통에서는 아직 0건. 일일 보고의 갱신 실패를 긴급으로 둘지(사람 손이 필요할 수 있음) 뺄지는 master 판단.
  → **2판에서 고침(§7 · master#ec2a27e6 지시)**.
- 배포 = master 게이트(워커 실행 0): 브랜치 → main 병합 → `git -C ~/axdev/jarvis-agora/.wt/desk-stable checkout --detach <병합 커밋>`. launchd 재적재 불요 — `kr.godmeyou.agora.desk` 는 매 판 새 프로세스(`resident once` · 껍데기 `~/.config/agora-desk/bin/agora` → desk-stable). 이 변경은 데스크(받는 쪽)만이라 릴레이·참가자 클라이언트 배포는 필요 없다.

## 6. 게이트
- commit_gate(실 `tests/commit_gate.sh` · 2026-10-29 · 코드 커밋 직전 작업트리) = **결과: PASS(rc 0)** · 공개 표현 합계 0건 · 비밀 누출 no leaks · selftest **637/637 PASS · 717/717 KILLED · NOT-APPLIED 0** · 미발생 오류코드 [] · F-1 25/25 · codex 0.1.4 11/11 · 공백 clean. (main 9529f73 기준 636/716 → 케이스 +1 · 뮤턴트 +1)
- 라이브 원장 무접촉 실측: `urgent.jsonl` mtime 시험 전후 동일(10-29 06:11:18).

## 7. 2판 — 기계 코드 전부 제외(master#ec2a27e6 · 일일 포함)
- 원칙(master): 긴급 낱말 대조는 「사람이 쓴 글」에만. 자동 생성 필드는 대조하지 않는다.
- 고친 것: 1판의 「intent == signal 이면 hits = []」를 걷고, 우편 긴급 대조를 `match_urgent(text, [], urgent_table)` 로 바꿨다 — `_mail_texts` 가 돌려주는 기계 코드(신호 `items[].error_code` · 일일 `updates[].result`)를 **아예 넘기지 않는다**. 기계 우편(signal·daily·weekly = `mail.MACHINE_INTENTS`)은 `text` 가 빈 문자열이라 0, 사람 글(notice·request·report = `mail.INTENTS`)은 제목·본문 대조 그대로(본문에 사람이 적은 `J-NET-01` 같은 코드 모양 낱말도 그대로 잡힌다). 우편 intent 는 이 6개뿐(`mail.py:33·37`) — 다른 갈래 없음.
- 형제 grep 1회(`grep -n "urgent|match_faq|_fold(|긴급" agora/*.py` · selftest 제외): 긴급 대조 호출 = 2곳뿐 — ① `counsel.py` 우편(이번에 고침) ② `counsel.py` 공개 방 글 `p.get("body")`(사람 글 · 코드 인자 `[]` · 그대로). 그 밖의 낱말 대조 = `match_faq(text, faq)`(접수 회신 링크 · HUMAN_INTENTS 만 · 기계 우편은 text 가 비어 무관). `resident.py` 는 데스크 결과 수만 싣고(661·676) 대조 없음 · `autoticket.py` 긴급 대조 없음. ⇒ 자동 필드가 긴급 대조에 들어가는 곳은 이번 1곳뿐이었다.
- 시험: 케이스 이름 「상담소: 기계 봉투 코드는 긴급 0 · 사람 글 1」 — 같은 판에 신호(`update.sig_mismatch`) + 일일(`updates[0].result = update.sig_mismatch`) + 사람 글 「업데이트가 안 돼요 급해요」 → 접수 3 · 알림 1 · 생략 0 · 긴급 원장 = 사람 대화 1줄.
  뮤턴트 2 = `M777-desk-signal-urgent`(신호 코드만 되살림) · `M778-desk-daily-urgent`(일일 코드만 되살림) — 둘 다 KILLED(사전 실측 · M778 KILLED = 고치기 전 일일 봉투가 실제로 긴급을 울렸다는 증거).
- 게이트 = 아래 줄(2판 커밋 직전 작업트리).
- commit_gate(실 `tests/commit_gate.sh` · 2판 코드) = **결과: PASS(rc 0)** · 비밀 누출 no leaks · selftest **637/637 PASS · 718/718 KILLED · NOT-APPLIED 0** · 미발생 오류코드 [] · F-1 25/25 · codex 0.1.4 11/11 · 공백 clean. 이 HANDOFF 는 게이트 도중 고쳐져 따로 재검: `tests/public_terms.sh` 0건 · `tests/ws_hygiene.sh` rc 0.

## 8. The Unarchiver 「압축 풀 폴더 권한」 창(07:29:33 · master#d6018fba 질의) — 이 시험 경로가 아님
- 시험·게이트에 GUI 로 여는 단계 0: `git grep` 으로 `open` 명령·NSWorkspace·osascript·LaunchServices·qlmanage·webbrowser 0건(문서 한 줄뿐). selftest 의 외부 실행 = python·node·git·bash(`tools/publish-check.sh` = python `open()` 으로 바이트만 읽음 · `tests/*.sh`)·SIGNER·icacls 뿐. zip 은 전부 `zipfile` 모듈로 쓰고 읽는다(`_publish_fixture` = agora-pub-* · `_case_package_ships_desk_pin` = agora-zip-desk-*).
- 시각: The Unarchiver 프로세스 시작 = 07:29:33 · 부모 = launchd(1) = LaunchServices 로 열림(누가 열었는지는 통합 로그에 안 남음). 그 때 내 1차 게이트가 돌고 있었으나 agora-zip-desk-* 는 07:30:11 에 생겼다(창보다 뒤). `$TMPDIR` 는 여러 좌석이 같이 쓴다(07:41·07:47 의 agora-zip-desk-* = 다른 실행).
- 창의 목록에 보인 `counsel.bak` = 내가 07:28:06 에 실수로 `$TMPDIR` 에 둔 백업(작업용 폴더에 둘 것이었다) — 원인은 아니고 목록에 보였을 뿐 · 지웠다. The Unarchiver 프로세스는 건드리지 않았다.
