# HANDOFF — 119 상담소 BACKLOG 후보 → 티켓 초안 생성기(TICKET=agora-119-autoticket · 2026-10-09)

## 0. 지금 상태(한눈) — **4판 끝**(2026-10-09 09:26 · codex 1R·2R·3R + master 직접 판정 반영 · 다음 = master diff 정독·종결 → 병합 main + 데스크 재배포 = master) · 1판 기록은 아래 그대로
- 가지 `feat/119-autoticket`(origin/main `e1372db` 위) · push 0 · 라이브 데스크 쓰기 0. 커밋 = 설계 `3da07f0` · 구현 `ebef940` · 문서 정정·이 문서(아래 §2).
- 설계 1장 = `docs/design/AUTOTICKET-119.md`(master 판정 da6c43ce 통과 — ⑴ 겹침 = 같은 티켓 + **둘 이상 겹침 = 모호** ⑵ 출력 폴더 = 설정 값 ⑶ 보안 4 채택 ⑷ 초안 머리 「생성: autoticket <판> · 원장 fp · 기간」).
- 게이트: commit_gate @ebef940 = 결과 FAIL(rc 1) — **이 가지 변경 밖 기존 적색만**: 케이스 612/615 · 뮤테이션 690/695 KILLED · NOT-APPLIED 5 · 공개 표현 위반 2(SPEC-mail §608 기존 1 + 이 설계 문서 1 → 정정 커밋에서 0) · 비밀 누출 0 · F-1 25/25 · codex 0.1.4 11/11 · 공백 clean. 이 티켓 케이스 8/8 PASS · M747~M754 8/8 KILLED. 실패 3·NOT-APPLIED 5 = 깨끗한 `e1372db` 에서도 같은 적색(§4) — selftest 원문 JSON 재실행으로 대조.
- 라이브 dry-run(`./bin/agora counsel tickets --dry-run --dir ~/.config/agora-desk` · 07:18 KST) = rc 0 · 아래 원문 · 라이브 데스크 파일 stat(mtime·크기) 전후 diff = 0.
```
{
  "ambiguous": [],
  "dir": "~/.config/agora-desk/counsel/tickets",
  "dry_run": true,
  "enabled": true,
  "kept_existing": [],
  "new": [],
  "noop": 0,
  "notify": [],
  "recur": [],
  "skipped": []
}
```
- 후보 0 이 정상 — 라이브 `counsel/2026-10-05~08` 에 `backlog_candidates.json` 0개(주간 모드 = 월요일 · 첫 실물 = 10-12(월) 07:30 배치 · 단 라이브 설치본 d0d45e8 은 이 생성기가 없다 = 재배포 뒤부터).
- E2E(실 CLI · 라이브 데스크 **사본**(scratchpad · 끝나고 삭제) + 후보 픽스처 2기간 · 인박스 경로 환경변수 = 시험 파일): 새 1 · 재발 1 · 알림 2(`inbox-append.sh` rc 0 · 헤더 `[counsel-desk@agora → …]` = 기존 배치 알림과 같은 꼴) · 재실행 = 새 0 · 재발 0 · noop 2 · 실 인박스 0줄.

## 0-2. 2판(2026-10-09 08:0x · codex 1R BLOCK 9·MAJOR 1 → master 865269a1 ①~⑩) — 커밋 `00c7a7d`
- 게이트: commit_gate @00c7a7d(08:22 KST · 곁 티켓 831ba05 포함) = **selftest 624/624 PASS · 뮤테이션 705/705 KILLED · NOT-APPLIED 0** · 비밀 누출 0 · F-1 25/25 · codex 0.1.4 11/11 · 공백 clean · 결과 FAIL 사유 = 공개 표현 위반 1건 `docs/SPEC-mail-1to1-2026-10-05.md:608`(이 가지 변경 0 · main 기존 · 데몬 이름 1 · 수정 = 지시 밖)
- 라이브 dry-run(2판 · 08:05 KST) = rc 0 · new/recur/ambiguous/collision/renotify 0 · ledger_errors 0 · skipped 0 · 라이브 데스크 stat 전후 diff 0.
| # | 리뷰 지적 | 2판 처방 | 케이스 · 뮤턴트 |
|---|---|---|---|
| ① | 스크럽이 ASCII 치환뿐(전각 표식·유사 백틱·HTML·링크 통과) | **허용 목록**: NFKC → 제어·서식 문자(C0·DEL·C1·2028/2029·200B~200F·202A~202E·2060~206F·FEFF) 제거 → 공백류 = 공백 → 한글(음절·자모)·ASCII 영숫자·공백·`.,!?:;'"-%+=·×` 밖 = `?` | 유니코드 표식·마크업 탈락(codex 재현 문자열) · M749 |
| ② | 기간 폴더 symlink 로 counsel 밖 입력 | 기간 폴더·후보 파일 `islink` 거부 + realpath 가 counsel 안 | symlink 기간 거부 · M755 |
| ③ | slug 32비트 충돌·기존 파일을 티켓으로 확정 | slug = `bl-<fp 16자>` · 초안 자리에 다른 파일·symlink·폴더 밖 = 확정 0 + 【티켓후보·충돌】(원장 0 · 실행마다 보고) · **같은 바이트** = 앞선 부분 실패의 우리 파일로 보고 확정(초안 본문 = 결정론 · 시각 0) | slug 16자·충돌 확정 0(codex 재현 서명 2개) · M756·M757 |
| ④ | 배열 순서로 모호 우회 | 기간 안 = fp 정렬 + **겹침 그래프**: 기존 티켓 ≥2 = 모호 · 1 = 재발 · 기존 0 끼리 차수 ≥2 = 모호 · 서로만 겹치는 짝 = 작은 fp 가 티켓(큰 쪽 = 같은 기간 0 변화) · 모호 후보와만 겹침 = 새 티켓 | 후보 순서 독립(3 집합 × 전 순열) · M758 |
| ⑤ | 같은 ticket 행 두 줄 = 티켓 둘 | 원장 (type, fp) 축약 · 형식 검증(fp 16 hex · slug = bl-fp · 기간 · 서명 32hex · fp = 서명 지문) · 내용이 다른 중복 = 그 fp 격리 + 그 서명과 겹치는 후보 **보류**(새 티켓으로 새지 않게) | 원장 중복 축약·격리 · M759 |
| ⑥ | 원장 brief 경로 신뢰 | 원장의 경로 값을 읽지 않는다 · 출력 폴더 + `<기간>-<slug>.md` 재계산 · symlink·폴더 밖 = append 0 | 초안 경로 재계산(원장 victim 경로 + symlink) · M760 |
| ⑦ | 재발 append 뒤 원장 실패 = 중복 | 신규 = 임시 파일 → `os.link`(덮어쓰기 0) → 원장 → 알림 · 재발 = 초안에 `- <기간> · 재발 ` 표식 없을 때만 append → 원장 → 알림 | 부분 실패 재실행 한 번(원장 쓰기 장애 주입 2곳) · M761·M764 |
| ⑧ | 끝 LF 없는 원장 뒤 접합 | append 전 마지막 바이트 검사(LF 아니면 LF 선행) · 한 write + fsync · 깨진 줄 = 격리(무시·`ledger_errors` 보고) | 원장 끝 LF · M762 |
| ⑨ | 원장 먼저 확정 = 알림 실패 영구 유실 | 행동 행에 `key`·`line`·`notified:false` · 알림 성공 시 `{"type":"notified","key"}` · 다음 실행 = 성공 행 없는 key 먼저 재알림(`renotify`) | 알림 실패 재알림 · M763 |
| ⑩ | 시험이 ASCII 한 패턴뿐 | 위 9 케이스 = 실제 `tickets()` 경로 · 기존 뮤턴트 M747~M752 앵커 재조준 | 티켓후보 케이스 17 · M747~M764 18 |
- 남은 것(정직): 알림은 「많아야 한 번」 이 아니라 **적어도 한 번** — 알림 성공 뒤 `notified` 행 append 가 실패하면 다음 실행이 같은 줄을 다시 보낸다(inbox-append 쪽 멱등 키 없음 · 리뷰 ⑨ 의 notify 측 키는 master 결정 목록 밖이라 안 넣었다). 충돌 보고는 원장에 안 남아 해소될 때까지 실행마다 1줄. GFM 의 `www.` 자동 링크는 허용 문자(`.`)만으로도 생길 수 있다(클릭 가능해질 뿐 지시 아님 · `/`·`:`/`` ` ``·`[]()<>` 는 탈락).
- 1판 원장 행(slug 8자)은 2판 형식 검증에서 「형식이 틀린 ticket 행」 으로 격리된다 — 라이브엔 원장이 없어(dry-run 실측) 영향 0.

## 0-3. 곁 티켓 — main 날짜 시한폭탄 3 케이스(master 93dc565e) — 커밋 `831ba05` · 제품 코드 0 · 시험 의도 불변
- ①「우편: 일일 보고 예외는 빈 owner_note 만」 day = 지금(UTC) 날짜 ②「상담소자동: 일일 닫힌 칸만」 today·weekly_skipped(직전 주기)·last_boot(now − uptime) = now 기준 ③「상담소자동: 429 그날 포기」 = 【관측】 요일 의존(판이 now~+3일 · 월 06:00 KST 를 넘으면 직전 주기 신호 줄로 주간 작성기가 불림 · 실측 7요일 × 시각) → 지나는 주기들의 직전 주기를 state 에 empty 로 미리 둠(주간 단계 = 이 케이스 밖 · 시계 이동 처방은 미래 시각·7일 신호 창에 걸려 기각 · 실측) · 결과 = 위 게이트 624/624 · NOT-APPLIED 0(전 판 612/615 · NOT-APPLIED 5 해소).

## 0-4. 3판(2026-10-09 08:4x · codex 2R BLOCK 13·MAJOR 2 → master 4d186ae8 채택 7 · 기각 6) — 코드 커밋 `49887ca` · SPEC §608 공개 표현 `6291b23`(400d0710 ①)
- 게이트: commit_gate @49887ca(08:54 KST · 실 `tests/commit_gate.sh`) = **결과: PASS(rc 0)** · 공개 표현 합계 0건 · 비밀 누출 no leaks · selftest **631/631 PASS · 713/713 KILLED · NOT-APPLIED 0** · 미발생 오류코드 [] · F-1 25/25 · codex 0.1.4 11/11 · 공백 clean
- 라이브 dry-run(3판 · 08:41 KST) = rc 0 · 전 칸 0 · 라이브 데스크 stat 전후 diff 0.

### 채택 7
| # | 지적 | 고친 자리(`agora/autoticket.py`) | 케이스 · 뮤턴트 |
|---|---|---|---|
| (a) | 새 행 종류를 스키마 없이 상태에 넣음(`{"type":"ambiguous","fp":[]}` = TypeError 영구 정지) | `_valid_row`(:291) 닫힌 스키마 4종(칸 집합 정확히 · fp 16hex · 기간 · 서명 32hex · key = `<type>:<fp>:<기간>` 재계산 · 줄 = 「【티켓후보」 한 줄 · notified=false) · `_state`(:319) 밖 행 = 격리·보고 | 원장 행 닫힌 스키마 · M765 |
| (b) | 짧은 write 성공 처리 · 한글 중간 절단이 원장 읽기 전체를 막음 | `_write_all`(:219) 남은 바이트 반복 + fsync · `_read_ledger`(:262) binary · LF 단위 · 줄마다 UTF-8·JSON 격리 | 짧은 쓰기·UTF-8 절단 · M766·M767 |
| (c) | 재발 줄 접두 판정 = 부분 행을 완성 안 함 | `_recur_append`(:164) 완전한 예상 행 일치 · 끝 부분 행이 예상의 앞부분이면 나머지 채움 · 같은 기간 다른 완전한 줄 = 덧붙이지 않고 보고 · fsync 뒤 seen | 부분 재발 줄 완성 · M768·M761 |
| (d) | 검사와 열기 사이 symlink 교체 창 · 원장 symlink | `_open_regular`(:204) `O_NOFOLLOW` + 같은 fd fstat 정규 파일 — 원장 append·읽기·후보 파일 읽기·초안 정체 확인·재발 append 전부 이 fd | 원장 symlink 거부 · M769(+M760 재조준) |
| (e) | 잠금 수단 none 인데 잠근 것처럼 실행 | `run_locked`(:470) 쓰기 실행 거절 · `tickets`(:585) backend none = 거절(code 2) | 잠금 수단 없음 거절 · M770 |
| (f) | 같은 기간 fp16 충돌 = 하나를 조용히 폐기 | `_load_period`(:384) 같은 fp·다른 서명 집합 = 둘 다 fingerprint-collision 격리·보고 | 기간 안 fp 충돌 격리 · M771 |
| (g) | 핵심 칸만 비교 = key·line 위조 중복을 축약 | `_state`(:334) (type, fp, 기간) 묶음의 **행 전체 digest** 비교 · 다르면 그 묶음 전부(알림 포함) 격리 · ticket 격리 = 서명 겹침 후보 보류 | 행 digest 충돌 격리 · M772(+M759 재조준) |
- 2판 뮤턴트 중 앵커가 바뀐 6개 재조준(M751·M757·M759·M760·M761·M764) — 티켓후보 뮤턴트 26개 전부 KILLED(M747~M772) · 케이스 24.

### 기각 6(코드 0 · master 판정 원문 요지)
| # | 지적 | 기각 사유 |
|---|---|---|
| ① | 1R #1 GFM 자동 링크(`www.` 토큰) | 초안은 사람·LLM 이 읽는 텍스트 파일 · 인용 블록 안 · 렌더러에 올리지 않음 = 계약 밖 |
| ② | 1R #3 hardlink·inode 결박 | counsel/ 안 hardlink = 우리 호스트 쓰기 권한 = 신뢰 경계 안 · symlink 만 (d) 로 닫는다 · openat 디렉터리 fd 프로토콜도 안 한다(기간 **폴더** 교체 창은 남음 — 같은 신뢰 경계) |
| ③ | 1R #4 기존 티켓 + 후보 단일 그래프 | 현 정책(기존 1 겹침 = 재발 · 2+ = 모호)을 fp 정렬로 결정론 적용 · 차이 = 같은 실행 안 새 티켓과의 사후 겹침뿐 · 다음 실행엔 seen 이라 변화 0 |
| ④ | 1R #9 알림 성공 뒤 notified 행 전 중단 | master 08:26 결정 「적어도 한 번」 · 수신 쪽 멱등 키 = 1.1.10 |
| ⑤ | 2R 신규 BLOCK 2 충돌 알림 실행마다 1줄 | master 08:26 결정(해소까지 실행마다 1줄) = 설계 결정 |
| ⑥ | 1R #10 광역 fault injection | (a)~(g) 각각의 뮤턴트로 한정 |
| ⑦ | 3R (d) 부모 디렉터리 dirfd·openat 결박 | 2R 기각 ② 그대로 — counsel/ = 신뢰 경계 안 · `O_NOFOLLOW` 는 마지막 성분까지(master 0b1712a8) |

### BACKLOG(1.1.10 · master 400d0710 ②)
- 알림 수신 쪽 멱등 키 — 행동 행의 `key`(`<type>:<fp>:<기간>`)를 인박스 줄에 실어 받는 쪽(inbox-append 류)이 같은 key 를 한 번만 적게 한다(지금 = 적어도 한 번 · 성공 뒤 notified 행 append 실패 시 중복 1줄).

## 0-5. 4판(2026-10-09 09:1x · codex 3R BLOCK 5·MAJOR 1 → 라운드 상한 · master 직접 판정 0b1712a8 반영 5 · 기각 1) — 코드 커밋 `82d2a63`
- 게이트: commit_gate @82d2a63(09:26 KST · 실 `tests/commit_gate.sh`) = **결과: PASS(rc 0)** · 공개 표현 합계 0건 · 비밀 누출 no leaks · selftest **636/636 PASS · 716/716 KILLED · NOT-APPLIED 0** · 미발생 오류코드 [] · F-1 25/25 · codex 0.1.4 11/11 · 공백 clean
- 라이브 dry-run(4판 · 09:13 KST) = rc 0 · 전 칸 0(held 포함) · 라이브 데스크 stat 전후 diff 0.
| # | 지적 | 고친 자리 | 케이스 · 뮤턴트 |
|---|---|---|---|
| ① | (a) 보강 — `type` 이 문자열 아니면 해시 전에 죽음 | `autoticket.py:296` `type(t) is not str` 선행 | type 문자열 아닌 행 격리(`{"type":[]}`) · M773 |
| ② | (c) 보강 — 재발 줄 확정 못 해도 seen 기록 | `:569` `_recur_append` 가 예상 행 일치 또는 append+fsync 성공(True)일 때만 seen·알림 · 초안 없음·symlink·같은 기간 다른 줄 = `held` 보고(seen 0 · 알림 0 · 다음 실행이 다시 봄) | 초안 없으면 seen 0 · 초안 경로 재계산(symlink → held) · M774 |
| ③ | 배치 후처리가 dry_run 을 안 넘김 | `counsel.py:1574` `dry_run=dry_run` 전달 · 【관측】 재현 안 됨 — dry-run 배치는 `counsel.py:1521` 에서 후처리 전에 반환한다(이 줄은 dry-run 에서 도달 불가) → 방어로 넣고 계약을 시험으로 고정 · **그 줄 뮤턴트는 도달 불가라 죽일 수 없어 등재 안 함**(공짜 KILLED 금지) | 배치 dry-run 쓰기 0(과거 후보 파일 + `batch --dry-run` → 원장·초안·알림 0) |
| ④ | link 뒤 디렉터리 엔트리 미확정인 채 원장 확정 | `:464` `os.link` 뒤 `_fsync_dir(out)`(디렉터리 fd fsync · 윈 = 건너뜀) → 그 뒤 ticket 행 · 「같은 바이트」 확정도 `:445` 에서 같은 fsync | 디렉터리 fsync 뒤 원장(순서 기록) · M775 |
| ⑤ | 원장 티켓과 fp 같고 서명 다름 | `:521` 쓰기 전 둘 다 fingerprint-collision 격리 · 두 서명 집합 = 보류 · 그 티켓 = 이번 실행 상태에서 뺌 | 원장 fp 충돌 격리 · M776 |
- 뮤턴트 정리: M757·M764 앵커 재조준(초안 정체 확인 줄이 ④로 바뀜) · **M760 삭제** = 등가 변이(재발 경로 `_safe_target` 을 빼도 `O_NOFOLLOW`(M769)가 같은 symlink 를 막아 행동 동일 — 남기면 의미 없는 SURVIVED) · 티켓후보 뮤턴트 29/29 KILLED · 케이스 29.
- 기각 추가: (d) 부모 디렉터리 dirfd·openat 결박 = 2R 기각 ② 그대로(counsel/ = 신뢰 경계 안 · `O_NOFOLLOW` 는 마지막 성분까지만).

## 1. 무엇이 어디서 도나
| 부품 | 자리 | 비고 |
|---|---|---|
| 생성기 | `agora/autoticket.py` | `_plan`(쓰기 0) → `run_locked`(초안 → 원장 → 알림 순) · `tickets()` = 수동 진입점(잠금) |
| 배치 후처리 | `agora/counsel.py` `_batch_locked` — `backlog_candidates.json` 쓴 뒤 · 같은 `batch.lock` 안 | 예외 = 결과 `autoticket.error` + 알림 꼬리 「티켓 후보 오류 1(이름)」 · 배치는 성공 그대로 · dry-run 배치는 그 전에 끝나 후처리 0 |
| 수동 | `agora counsel tickets [--dry-run] [--dir …]` | 모든 기간 훑기(놓친 날 보충) · dry-run = 잠금 파일까지 쓰기 0 |
| 끄기 | `config.json` `desk.autoticket` | `false` = 끔(잠금 파일도 안 만듦) · 경로 문자열 = 그 폴더 · 그 밖 = `counsel/tickets/` |
| 원장 | `counsel/tickets.jsonl` | 줄 = `ticket`·`seen`·`ambiguous` · append 만 · 재발 N = 그 티켓의 서로 다른 기간 수 − 1 |
| 알림 | `counsel.notify` → `desk.notify_cmd`(라이브 = `inbox-append.sh counsel-desk@agora`) | 【티켓후보】·【티켓후보·재발】·【티켓후보·모호】 — 참가자 글 0자 |

## 2. 커밋
| 커밋 | 내용 |
|---|---|
| `3da07f0` | 설계 1장 |
| `ebef940` | autoticket.py · counsel 배선(DEFAULTS·settings·batch 후처리·CLI_ACTION_ARGS·dispatch·usage) · cli 동작 표 · 케이스 8 · M747~M754 · 축 「티켓후보」 |
| (이 문서 커밋) | 설계 문서 금칙어 1(브리프 파일 이름 인용) 정정 + 판정 반영 줄 · 이 HANDOFF |

## 3. 함정·주의(다음 사람)
- **지문 재료 = `signatures` 뿐**: 후보의 `keys`(W1-b1)는 배치 안 번호 · `title`·`why` 는 모델 글 — 주마다 흔들린다.
- **티켓 서명 집합은 만든 때 고정**(재발이 서명을 합치지 않는다) — 합치면 사슬이 자란다(모호 규칙과 같은 이유). 그래서 나중 후보가 **재발 때 새로 붙은 서명만** 가지면 새 티켓이 된다(보수 쪽 · 소음 가능 · 실측 뒤 판단).
- **slug = fp 앞 8 hex** — 서로 다른 fp 의 앞 8자가 같으면(2^-32) 같은 파일 이름 → 둘째는 `kept_existing`(안 덮어씀)로 남고 원장은 첫째 초안을 가리킨다.
- **쓰는 순서 = 초안 → 원장 → 알림**: 원장 뒤 알림 전에 죽으면 그 알림 1줄은 잃는다(많아야 한 번 · 재실행이 다시 안 보냄). 초안 뒤 원장 전에 죽으면 재실행이 파일을 안 덮어쓰고 원장만 맞춘다.
- **참가자 글 격리**: 제목·바꿀 것·근거 = 초안의 `> ` 인용 줄 안에만(제어 문자·줄바꿈 → 공백 · 백틱 제거 · `[master#`(대소문자·공백 무관) → `[master＃` · 제목 80 · 인용 120 · 근거 3). 줄머리 `#` 판정은 줄 단위라 인용 안 `## 1.` 은 제목이 아니다(케이스가 줄 단위로 잰다).
- **꾸러미**: `tools/build_client_zip.py` 가 `agora/` 를 `.py` 규칙으로 통째 담는다 → 다음 zip 빌드부터 autoticket.py 가 참가자 꾸러미에도 실린다(데스크 설정 없으면 안 돈다 · 동봉 0.1.14 zip·핀은 이 가지에서 다시 빌드하지 않았다).
- `relay/node_modules` = 게이트용 심볼릭 링크(본 저장소 node_modules) — `relay/.gitignore` 의 `node_modules/`(끝 슬래시 = 폴더만)에 안 걸려 미추적으로 보였다 · 3판 게이트 뒤 지웠다(400d0710 ④) · 게이트를 다시 돌리려면 다시 만든다.

## 4. 남은 것(master)
- 적대 검토(codex 1R) · 병합 · 데스크 재배포 + 라이브 `config.json` `desk.autoticket` = `"~/axdev/master/briefs/auto"` 1줄(라이브 데스크 쓰기).
- (해소 · §0-3 831ba05) 이 가지 밖 기존 적색이었던 것: ① 「우편: 일일 보고 예외는 빈 owner_note 만」 — 픽스처 `day` = 2026-10-05 고정 · 받는 쪽 「봉투 ts 날짜 ±1일」 검사가 10-07 이후 거부(code 10) = 날짜 시한폭탄 · killer M577 NOT-APPLIED ② 「상담소자동: 일일 닫힌 칸만」 — `today="2026-10-06"` 고정 · now = 실시계 → 모든 칸이 걸러져 `['day']` 만 = 같은 시한폭탄 · M702·M731 NOT-APPLIED ③ 「상담소자동: 429 그날 포기·code 8 같은 문서」 — 「작성기를 부르면 안 되는 판」 · 픽스처가 now 에서 하루씩 넘긴다 → 【추정】 요일(주간 작성 창) 의존 · 원인 미확정 · M696·M697 NOT-APPLIED ④ 공개 표현 위반 `docs/SPEC-mail-1to1-2026-10-05.md:608`(10-06 T3 정정 줄 · 데몬 이름). 처방 후보 ①② = 픽스처 날짜를 now 기준으로(T3 몫 · 이 티켓 수정 0).

## 7. 종결(2026-10-09 09:2x · master 68a6c07b — 4판 82d2a63 diff 직접 판독 녹 · codex 추가 라운드 없음)
- 병합 대상 = **main**(베이스 `e1372db`) · 가지 `feat/119-autoticket` 커밋 11: `3da07f0` 설계 · `ebef940` 1판 · `9c2796b` 설계 판정 반영 · `831ba05` 곁 티켓(날짜 시한폭탄 3) · `00c7a7d` 2판 · `11c5484` HANDOFF §0-2·§0-3 · `6291b23` SPEC §608 공개 표현 · `49887ca` 3판 · `2dcd4af` HANDOFF §0-4 · `82d2a63` 4판 · `8a8d0eb` HANDOFF §0-5 (+ 이 절).
- 마지막 게이트 = commit_gate @82d2a63 **PASS** · 636/636 · 716/716 KILLED · NOT-APPLIED 0 · 공개 표현 0 · 누출 0.
- 데스크 재배포 = master(라이브 설치본 = desk-stable d0d45e8 = 이 생성기 없음) + 라이브 `config.json` `desk.autoticket` = `"~/axdev/master/briefs/auto"` 1줄 = master. 재배포 뒤 첫 실물 = 그 다음 월요일 주간 모드 배치(07:30).
- 남은 것 = **알림 수신 멱등 키(1.1.10 BACKLOG)** — 지금 = 적어도 한 번(§0-4 BACKLOG 줄).
- 기각 7(코드 0):
| # | 지적 | 기각 사유 |
|---|---|---|
| ① | 1R #1 GFM 자동 링크(`www.`) | 초안 = 사람·LLM 이 읽는 텍스트 파일 · 인용 블록 안 · 렌더러에 올리지 않음 = 계약 밖 |
| ② | 1R #3 hardlink·inode 결박 | counsel/ 안 hardlink = 우리 호스트 쓰기 권한 = 신뢰 경계 안 · symlink 만 `O_NOFOLLOW` 로 닫음 |
| ③ | 1R #4 기존 티켓 + 후보 단일 그래프 | 현 정책을 fp 정렬로 결정론 적용 · 차이 = 같은 실행 안 새 티켓과의 사후 겹침뿐 · 다음 실행엔 seen 이라 변화 0 |
| ④ | 1R #9 알림 성공 뒤 notified 행 전 중단 | 「적어도 한 번」(master 08:26) · 수신 멱등 키 = 1.1.10 |
| ⑤ | 2R 충돌 알림 실행마다 1줄 | 해소까지 실행마다 1줄 = 설계 결정(master 08:26) |
| ⑥ | 1R #10 광역 fault injection | (a)~(g)·4판 ①~⑤ 각각의 뮤턴트로 한정 |
| ⑦ | 3R 부모 디렉터리 dirfd·openat 결박 | 기각 ② 그대로 — `O_NOFOLLOW` 는 마지막 성분까지(기간 **폴더** 교체 창 = 신뢰 경계 안) |
