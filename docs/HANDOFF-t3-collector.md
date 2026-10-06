# HANDOFF — T3 상담소 자동 전달(TICKET=agora-t3-pack-collector · 2026-10-06)

## 0. 지금 상태(한눈) — 4판 끝(2026-10-06 18:4x · 이종 리뷰 1R·2R·3R 반영 · 다음 = master 정독·게이트·Fable 판정 → 머지)
- 아고라 가지 `feat/t3-collector`(main e0f5df5 위) — push 0. 판별 커밋 = 1판 §2 · 2판 `77c5f8c`·`65d9058`·`499d98c`·`d9e0e7d` · 3판 `8d40331`(끄기 = 설정 먼저·잠금 대기 상한·지우기 미룸 표식 · 일일 cutoff = facts 값·낡은 facts 거부)·`9dd0c83`(스킬 문서 칸 이름)·`9aadf40`(이 문서 함정 줄) · commit_gate PASS @9aadf40 = 605/605 · 679/679 KILLED · NOT-APPLIED 0.
- 4판(codex 3R BLOCK1·MAJOR3) = 아고라 `1e89611`(off = `auto=false`+`purge_due` 한 설정 문서 원자 기록 · 지운 뒤에만 표식 뺌 · on = 표식 남으면 run.lock 잡고 지운 뒤에만 켬 · 발신 직전 auto ∧ 표식 없음 · facts nonce 일치 때만 · cutoff 미래 +5분 초과 거부)·`7cd7b04`(CLI 명령 표 `facts_nonce` — 꾸러미 E2E 적발)·`b9c92ab`(M699 앵커 재조준) · commit_gate PASS @b9c92ab = 607/607 · 687/687 KILLED · 팩 `45054930`(tick 판 nonce → facts.json + `--facts-nonce`)·`89512f67`(tick 총 ≤540 = 끝내기 몫 40 선차감 · agora 몫 ≤500 · 실측 499.0초)·`1368c5eb`(windows-health 필수 검체 같은 줄 ok · skipped 0 · awk 자가 시험)·`429c1d6b`·`1b304707`(동봉 재빌드).
- 팩 가지 `t3/collector-118` = **merge 4d0aab95(U1 병합) 위로 rebase** — 머리 `1b304707` · 본 가지 push 0 · CI 전용 미러 `fix/t3-collector-118`(= 1b304707 · master 재승인 f0642410) · 설계 1장 = 그 저장소 `docs/design/T3-COLLECTOR-DESIGN-2026-10-06.md`(§8~§10 = 판정·리뷰 반영).
- 동봉 = 0.1.14 zip sha256 `276b64f55e9de9c6ea92141c000a22e31551acdfe4ef1b006631fc492c892bf6` · 715,390 B · 57 파일 · 빌드 트리 = 아고라 `b9c92ab` · 핀 넷째 칸 = 트리 지문 v2 `c7d9c679b7d0868fc2f8b13c4e39d3b89bc6920da81a2d3fdca08365f8734640` · known(자동 교체 대상) = 0.1.12·0.1.13·0.1.14(산식 v2 · 3판·4판 중간 빌드 줄 = 미배포라 교체 · 다음 판 동봉 때 그 판 줄을 더한다).
- 다음 사람이 먼저 볼 것: ①판을 올리면 known 에 지금 판 줄 추가 + 핀 4칸 재계산(팩 시험 `test_known_file_rows` 가 핀 넷째 칸 = known 동봉 판 줄을 대조) ②아고라 소스를 고쳐 zip 이 바뀌면 팩 b64·핀도 함께(같은 커밋 세트) ③윈 = windows-health 레인의 팩 파이썬 스텝이 교차 잠금·0번 바이트를 잰다.
- 판 = 클라이언트 0.1.14 후보(`__version__` · RELEASES 후보 행) · 동봉 zip = 팩 원본 `install/agora-client-0.1.14.zip.b64` + `install/agora-client.pin`.
- 게시·릴레이 /join 핀·main 병합·팩 발행 = master(1.1.8 발행과 묶음 · 0.1.13 존치).

## 1. 무엇이 어디서 도나
| 부품 | 자리 | 비고 |
|---|---|---|
| 신호 줄 쓰기 | 팩 `bin/javis_counsel.py signal` ← 훅 공용 실패 기록 함수(6곳) · preflight `main()` C 번호 FAIL/WARN · 부서 도구 EXIT trap(rc∉{0,2}) · CLI rotate·pack-update 비0 | 형식 밖 = 버림 · 끔 = 안 씀 · 2MB 넘으면 버림 · 잠금 2초 넘으면 버림 |
| 일일 사실 | 팩 `javis_counsel.py facts` → `<설정>/counsel/facts.json` | 꺼짐·그날 일일 끝 = 수집 0 · 일일 마감 = facts `cutoff`(pending 에 박음 → 성공 시 `daily_ok_at`) · 없음·형식 밖·2시간 넘게 묵음 = 일일 0·표식 0(`no_fresh_facts`) |
| 일정 | 팩 `schedule.json` 잡 `agora-counsel`(30분 · base_only · bulk:false · publish:true) → `javis_counsel.py tick` | tick = 동봉본 첫 설치 → facts → `agora counsel auto` |
| 발신 전부 | 아고라 `agora/collector.py`(`agora counsel auto`) | 순서 = 신호 → 주간 → 일일 · 결과 = `counsel/state.json`·`counsel.log` · 화면 0 |
| 끄기 | `agora counsel off|on` = `config.json` `counsel.auto` 그 키만 · off = 설정 먼저 끔 → `run.lock` 을 `WRITER_TIMEOUT + 30`초까지 기다려 지운다(못 쥐면 꺼진 채 「미룸」 · 표식 `purge.due` → 다음 판이 먼저 지움) | 끄면 모은 줄·신호/일일 pending·주간 문서·pending 주기·`weekly_skipped`·우편함 주간 pending 지움 · 판은 발신 직전마다 다시 본다 |
| 보이기 | `agora whoami` 첫 칸 `advice_autosend`(「상담소 자동 전달: 켜짐/꺼짐」) | 키 정렬 `ad` < `ap` — 둘째 칸 승인 게이트 · 셋째 칸 상주(리뷰 ⑫) |

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
- **터미널 데몬의 동결 1회 잡 재적재가 `bulk`/`publish` 를 떨궜다**: `schedule.rs` `requeue_oneshot_after_frozen_at` 이 Job 구조체를 다시 직렬화하면서 두 칸이 빠졌다 — 리뷰 3R ⑥ 에서 팩 저장소 터미널 데몬 Job 의 두 칸을 `Option<bool>` + `skip_serializing_if` 로 바꿔 해소(TICKET=agora-t3-pack-collector).
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
- BACKLOG(데스크 T2 다음 판 · 구현 0): 데스크의 긴급 후보 분류기가 `intent=signal` 봉투의 `update.*` 코드를 긴급으로 센다(§4 「`urgent: 1`」 실측이 그 자리).
- BACKLOG(터미널 데몬 · 이 티켓 밖): 시간 초과된 command 잡의 자식 프로세스 그룹을 데몬이 끝내지 않는다(작성기는 `resident.run_agent` 가 스스로 그룹째 끝낸다).
- BACKLOG(문서 · 비동봉 · 수정 금지 판정 = 리뷰 4판 ⑤): whoami 칸 순서가 옛 꼴로 남은 문서 3곳 — `.appbuild/05-gate.md`:163 · `docs/skill.md`:41 · `docs/ONBOARDING.md`:34(현행 = 첫 칸 `advice_autosend` · 둘째 `approval_gate` · 셋째 상주). 0.1.14 zip 에는 이 문서들이 없어 발행물 결함 아님 — 다음 문서 정비 판에서 고친다.
- BACKLOG(N1 · Fable 최종 판정 MINOR · 안전 쪽): `on` 이 `run.lock` 을 기다리는 동안 도는 판의 OFF 경로가 표식을 먼저 빼면 `expect_due` 불일치로 「켜지_않음」(「그사이 다른 끄기가 끼어들었다」) 사유가 잘못 나간다 — 두 번째 `on` 에서는 켜진다. 처방: 잠금 안에서 `cur = due_token()` 이 None 이면 이미 지워진 것으로 보고 켜기를 진행 + 사유 문구 교정.
- BACKLOG(N2 · Fable MINOR): 그날 일일이 끝난 날의 tick 은 팩이 facts 를 안 써서(비대상 판) nonce 불일치 → `facts={}` — 같은 판 주간 문서에 `version`·`os` 칸이 빠지고 `counsel.log` 에 `no_nonce_match` 가 판마다 찍힌다(소음). 처방 후보: 비대상 판은 nonce 표식만 갱신하거나, 주간 칸 재료를 일일 facts 와 분리.
- BACKLOG(N3 · Fable MINOR): `_write_json`(임시 → fsync → `os.replace`)이 윈 공유 위반(다른 프로세스가 config.json 을 연 채)의 `OSError` 를 잡지 않는다 — `agora counsel on|off` 가 CLI 오류로 끝나고 설정은 그대로(상태 불변 · 안전 쪽). 처방: 짧은 재시도 + 사유 반환.
