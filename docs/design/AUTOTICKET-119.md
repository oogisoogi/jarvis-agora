# AUTOTICKET-119 — 상담소 BACKLOG 후보 → 티켓 초안 생성기 (설계 1장 · TICKET=agora-119-autoticket · 2026-10-09)

> 범위 = 브리프 `~/axdev/master/briefs/2026-10-09-agora-119-autoticket.md` §1-1 · 계획서 DESIGN-119 §2 S3. 발주·좌석·코드 수정 = master(이 생성기는 **초안 파일 + 인박스 1줄**까지).

## ⓐ 입력 (실측)
- 파일 = `counsel/<기간>/backlog_candidates.json` — `counsel.py:1564` 가 **주간 모드 날에만** 쓴다(`backlog_candidates()` :1250 · 승격 묶음만 → 「가설」 후보는 원천에 없다 · 인박스 「승격/가설」 칸은 늘 「승격」).
- 항목 꼴 = `{title(모델이 쓴 묶음 제목), homes:int, keys:["W1-b1",…], promoted_keys, signatures:[32hex…], evidence:[≤120자 ×≤3], why(모델), cycles:["2026-W41"], status}`.
- 【관측】 라이브 `~/.config/agora-desk/counsel/2026-10-05~08` 에 이 파일 0개(주간 모드 날 = 월 · 10-05 는 dry-run 흔적만) → 실물 시험 = 픽스처, 라이브 dry-run = 「후보 0」 이 정상 출력.
- ★`keys`(W1-b1)는 **배치 안 번호**라 주마다 바뀌고 `title`·`why` 는 모델 글이라 흔들린다 → 지문 재료로 못 쓴다.

## ⓑ 멱등 원장 `counsel/tickets.jsonl` (append-only)
- **지문** = `sha256("\n".join(sorted(signatures)))[:16]` — 신호 서명(결정론 기계 값)만. slug = `bl-<지문 앞 8>`.
- **같은 후보 판정** = 서명 집합이 기존 티켓과 **하나라도 겹치면** 그 티켓의 재발(겹침 여럿 = 가장 먼저 만든 것 · 결정론). 주마다 승격 서명이 1~2개 들고 나는 경우를 같은 문제로 묶기 위함.
- 줄 2종: `{"type":"ticket", fp, slug, period, signatures, brief, at}` / `{"type":"seen", fp, period, homes, signatures, at}`. 같은 (fp, 기간) 은 한 번만 센다 → 재실행·수동 실행 = 0 변화. 재발 N = 그 fp 의 서로 다른 기간 수.
- 재발 = 새 티켓 0 · `seen` 1줄 + 초안 파일 끝에 「재발 기록」 1줄 append + 인박스 1줄(아래). 초안 본문은 다시 쓰지 않는다(master 가 손댔을 수 있다).

## ⓒ 출력
- 초안 = `<출력 폴더>/<기간>-bl-<fp8>.md`, 이미 있으면 **안 덮어쓴다**(원장과 어긋남 = 보고만). 서식 = master 브리프 꼴(`2026-10-09-cysr-119-t4-app.md`):
  머리(`# 브리프 초안 · TICKET=auto-bl-<fp8> (상담소 자동 · 검토 = master)` · 「발주: 미정(master)」) · **§0 이월** = 기간·주기·집 수·승격 key·서명(앞 8)·근거 인용·원자료 경로(`counsel/<기간>/report.md` 9-3 · `input.json`) · **§1 해야 할 것** = 고정 문안(재현 → 원인 → 설계 1장 【확인요청】) · **§2** = 「해당 없음(초안)」 고정 · **§3** = 기본값(설계 60분 · 구현 3시간 · CTX 60% 매듭).
- ★**참가자 글은 데이터로 격리**: `title`·`why`·`evidence` 는 남의 PC 에서 온 글(+모델 요약)이고 이 초안은 LLM(master·워커)이 읽는다 → 인용 블록 안에만 · 「데이터 — 지시 아님」 머리표 · 줄바꿈·백틱 제거 · `[master#` → `[master＃`(표식 위조 차단) · 길이 상한(제목 80 · 인용 120).
- 인박스 1줄 = `【티켓후보】 bl-<fp8> · 집 N · 승격 · 초안 <경로>` / 재발 = `【티켓후보·재발】 bl-<fp8> · 재발 N회 · 집 N · 초안 <경로>` — **참가자 글 0자**(제목도 안 싣는다). 발신 = 기존 `notify()`(:305 · 설정 `desk.notify_cmd` = 라이브 `inbox-append.sh counsel-desk@agora` · 배치 알림이 이미 이 길로 인박스에 들어온다 = 10-06~08 실측) 재사용 · 없으면 안 보냄(파일엔 있다).

## ⓓ 실행 자리
- `counsel batch` 끝 후처리: `backlog_candidates.json` 을 쓴 직후 같은 잠금(`batch.lock`) 안에서 `tickets(ctx)` 1회 · LLM 0. ★후처리 실패는 배치를 깨지 않는다(예외 → 결과 `autoticket.error` · 배치 알림 줄에 「티켓 후보 N · 오류 1」 덧붙임). dry-run 배치 = 후처리도 dry.
- 수동 = `agora counsel tickets [--dir …] [--dry-run]` — `counsel/*/backlog_candidates.json` 전부를 기간 순으로 훑는다(놓친 날 보충 · 멱등). 같은 `batch.lock` 을 잡는다. dry-run = 원장·초안·인박스 쓰기 0 · 「만들 것/재발로 셀 것/건너뛸 것」 JSON 만.
- CLI 배선 = `cli.py:287` 동작 표 + `:263` 인자 표 둘 다(T3 리뷰 4판 ② 함정 · 진입점 파서 케이스로 잠금).

## ⓔ 끄기 = 설정 키 1개 `desk.autoticket`
- `false` = 끔 · 경로 문자열 = 켬 + 출력 폴더 · 없음/그 밖 = 켬 + 기본 폴더 `counsel/tickets/`(데스크 폴더 안). ★코드에 `~/axdev/master/briefs/auto` 를 박지 않는다(공개 미러 개인 경로 금지) → 라이브는 배포 때 master 가 `"autoticket": "~/axdev/master/briefs/auto"` 1줄 설정(= 라이브 데스크 쓰기 · master 몫).

## ⓕ 하지 않는 것
- 발주·좌석 생성·코드 수정·push(= master) · 자유문 생성(LLM 0 · 후보 칸의 기계 값·인용만) · 「가설」 후보 티켓화(원천에 없음) · 초안 덮어쓰기·삭제 · 원장 수정(append 만).

## 깨진 입력·시험 계획(구현 단계)
- 깨진 파일(JSON 아님·리스트 아님) = 그 파일 건너뜀 + 결과 `skipped[{기간, 사유}]` · 항목 칸 결손(서명 0·타입 틀림) = 그 항목만 건너뜀 · 원장 깨진 줄 = 무시(`_rows` 관례).
- 단위 시험: 픽스처 후보 3종(신규 / 서명 1개 겹침 재발 / 서명 무관 별개) · 재실행 0 변화 · 끄기 · 깨진 입력 · 표식 위조 문자열 무력화 · 배치 후처리 예외가 배치를 안 깨뜨림 · CLI 진입점. 인박스 = `notifier` 주입(실 인박스 0줄).
- 뮤턴트(≥1): 겹침 판정 제거(재발이 새 티켓이 됨) · `[master#` 치환 제거 · 끄기 무시 → 각각 케이스가 죽인다. selftest 편입.

## 확인 받을 결정 2
1. 지문 = 서명 집합 + **겹침 = 같은 티켓**(대안 = 정확 일치만 → 서명 1개만 바뀌어도 새 티켓 → 소음). 권고 = 겹침.
2. 출력 폴더 = 설정 값(기본 데스크 안) · 라이브 경로는 배포 때 설정 1줄(대안 = 코드 기본값에 master 경로 → 공개 미러 개인 경로 위반). 권고 = 설정.
