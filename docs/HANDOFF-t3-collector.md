# HANDOFF — T3 상담소 자동 전달(TICKET=agora-t3-pack-collector · 2026-10-06)

## 0. 지금 상태(한눈)
- 아고라 가지 `feat/t3-collector`(main e0f5df5 위) — push 0. 커밋 = 아래 §2.
- 팩 가지 `t3/collector-118`(1.1.8 병합 가지 7e7aa5da 위) — push 0 · 설계 1장 = 그 저장소 `docs/design/T3-COLLECTOR-DESIGN-2026-10-06.md`(공개 표현 규약 때문에 이쪽에 둠).
- 판 = 클라이언트 0.1.14 후보(`__version__` · RELEASES 후보 행) · 동봉 zip = 팩 원본 `install/agora-client-0.1.14.zip.b64` + `install/agora-client.pin`.
- 게시·릴레이 /join 핀·main 병합·팩 발행 = master(1.1.8 발행과 묶음 · 0.1.13 존치).

## 1. 무엇이 어디서 도나
| 부품 | 자리 | 비고 |
|---|---|---|
| 신호 줄 쓰기 | 팩 `bin/javis_counsel.py signal` ← 훅 공용 실패 기록 함수(6곳) · preflight `main()` C 번호 FAIL/WARN · 부서 도구 EXIT trap(rc∉{0,2}) · CLI rotate·pack-update 비0 | 형식 밖 = 버림 · 끔 = 안 씀 · 2MB 넘으면 버림 · 잠금 2초 넘으면 버림 |
| 일일 사실 | 팩 `javis_counsel.py facts` → `<설정>/counsel/facts.json` | 꺼짐·그날 일일 끝 = 수집 0 |
| 일정 | 팩 `schedule.json` 잡 `agora-counsel`(30분 · base_only · bulk:false · publish:true) → `javis_counsel.py tick` | tick = 동봉본 첫 설치 → facts → `agora counsel auto` |
| 발신 전부 | 아고라 `agora/collector.py`(`agora counsel auto`) | 순서 = 신호 → 주간 → 일일 · 결과 = `counsel/state.json`·`counsel.log` · 화면 0 |
| 끄기 | `agora counsel off|on` = `config.json` `counsel.auto` 그 키만 | 끄면 모은 줄·신호/일일 pending·주간 pending 지움 |
| 보이기 | `agora whoami` 셋째 칸 `autosend_counsel` | 첫 칸 게이트·둘째 칸 상주 계약 유지(작성자 판단) |

## 2. 커밋
| 저장소 · 가지 | 커밋 | 내용 |
|---|---|---|
| 아고라 `feat/t3-collector` | `d4bac71` | collector.py · CLI auto/off/on · whoami 셋째 칸 · 케이스 10 · M693~M713 · 허용목록 send_weekly 줄 삭제 |
| 〃 | `2d096f7` | 꾸러미 `config/desk-pin.txt` 동봉 + 케이스 + M714 |
| 〃 | `a854fb3` | 판 0.1.14 후보(`__version__` · RELEASES 후보 행) — zip 빌드 트리 |
| 〃 | (이 문서 커밋) | HANDOFF |
| 팩 `t3/collector-118` | `e2a16835` · `a0561a56` · `d5b05199` | javis_counsel.py · 쓰는 자리 4종 · 일정 잡 · Rust 신호 · 시험 |
| 〃 | `5276859e` | tick = 꺼짐·그날 일일 끝이면 사실 수집 0 · 설계 1장 이동 |
| 〃 | `01a509ca` | 동봉 b64 + 핀(0.1.14 · sha256 `64f093b12719594300cd7c9dfb283ea938a8e19c92acbaa3f58f15cde2772235` · 701,355 B · 57 파일) · 윈 실기 문안 |
| 〃 | `e0236ba4` | 건강 검체 H-WIN-16 동결표 등재 |

## 3. 함정·주의(다음 사람)
- **보낸 줄 = 같은 바이트**: `collector.move_sent` 는 원문 줄을 그대로 옮긴다(CR 만 떼어 LF) — 재직렬화하면 주간 근거 훅 id 가 끊긴다(뮤테이션 M695).
- **잠금 = 옆 파일 0번 바이트**: `counsel/signals.lock` 을 `a+` 로 열고 `seek(0)` 뒤 잠근다(윈 `msvcrt.locking` 은 현재 위치부터) — 팩·아고라 양쪽 같다. 윈 실기에서 상호배제를 아직 못 쟀다.
- **주간 작성기**: 부르기 **전에** state 에 `writing` → 죽어도 같은 주기 재호출 0(토큰 1회) · rc≠0·JSON 깨짐 = `gave_up`(빈 보고 아님 · weekly_skipped 안 실음) · 근거 거부 항목 빼고 **다시** verify 뒤 거부 0 일 때만 send.
- **top_features = 그 주기 안 줄의 op 집계**(원장 전체 아님 · 작성자 판단 — 원장 전체로 세면 신호가 한 번이라도 있던 PC 는 영원히 빈 보고가 안 된다).
- **꾸러미 핀 누락(수리)**: 0.1.13 까지 zip 에 `config/desk-pin.txt` 가 없었다 → 0.1.14 MANIFEST 에 추가 + 케이스 「꾸러미: 상담소 핀이 실린다」 + M714.
- **429 와 버킷**: 신호(`gmail-signal-day`)·일일(`gmail-daily-day`) = 발신자당 하루 1 · 주간(`gmail-weekly-week`) = 월요일 06:00 KST 칸 주 1(명세 §1-3 (2)) — 시험 참가자로 같은 날 두 번 보내면 429 가 정상(수집기는 그날·그 주기 포기).
- **selftest·뮤테이션 도는 동안 소스 편집 금지**(전임 함정 그대로) · `relay/node_modules` = 심볼릭 링크(`git add -A` 금지).

## 4. 라이브 실측(시험 참가자 `jarvis-test-weekly0113` · 설정 폴더 격리)
- 14:23:54 KST `agora counsel auto` 1판: 신호 201(message_id `1df4f47c…` · 항목 2) · 일일 429(같은 날 0113 호환 시험이 버킷 사용 = 정상 포기) · 주간 W40 = 빈 보고(`weekly_skipped` 이월).
- 보낸 원장 `signals-sent.jsonl` = 보낸 두 줄과 `cmp` 같은 바이트 · 모은 파일 0 바이트.
- 데스크: 14:27:56 KST 상주 판 `mail: 1` · inbox 에 그 message_id 1건 · 격리 파일 없음 · 데스크가 `urgent: 1` 로 셌다(update.sig_mismatch 줄 = 0113 시험이 남긴 근거 줄).
- 작성기 실호출(발신 0 · 우리 계정 1회): 10.9초 · 항목 4 · 근거 거부 0 · top_features 3.

## 5. 남은 것(이 티켓 밖 · master)
- 명세 §13-6 1줄 정정(팩 PC = 일정이 대신) · AUTO-UPDATE-118 L331 문면 정정 · 게시·핀 · 병합 순서 U1 → U3 → T3(rebase 시점 = master).
- 윈 실기(문안 = 팩 저장소 `docs/design/T3-WIN-HANDS-ON-2026-10-06.md`).
- 적대 라운드(codex 1R·2R → Fable 3R · 발주 = master).
