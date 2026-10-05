# HANDOFF — 윈도우 상주 콘솔 창 깜빡임 제거(D20) · 클라이언트 0.1.10

> TICKET=agora-win-no-console-window · 2026-10-05 · 코드 a79d62a · 게시 핀 740ee78(= main)

## 1. 원인(실측)

- 윈도우 작업 스케줄러 `\agora-resident`(10분 주기)가 `pythonw.exe … agora resident once` 를 부른다.
  pythonw 는 콘솔이 없어서, 그 안에서 콘솔 프로그램을 자식으로 띄우면 **자식마다 새 콘솔 창이 할당**된다.
- 한 판(22초)에 자식 17개가 창을 열었다(hwnd≠0): PowerShell `Get-Acl` 2 · `ssh-keygen -Y check-novalidate/verify` 14 등.
- 숨김 인자(`CREATE_NO_WINDOW`)는 `resident.py` 3자리와 `participant.py` 1자리에만 손으로 붙어 있었고,
  서명 확인(`sign.py`)·서명(`signer.py`)·키(`keygen.py`·`roster.py`)·점검(`selfcheck.py`)·저장층(`store_github.py`)
  자리에는 없었다. 개발기(맥)에서는 창이 생기지 않으므로 시험이 영원히 초록이었다.

## 2. 고친 것 — 자식은 한 문으로만

- **`agora/_proc.py`** = `run`·`Popen`·`check_output`. 윈도우(`os.name == "nt"`)면
  `creationflags |= CREATE_NO_WINDOW` + `STARTUPINFO(STARTF_USESHOWWINDOW, SW_HIDE)` 를 넣는다.
  부르는 쪽 `creationflags` 는 OR 로 합치고(예: 상주의 `CREATE_NEW_PROCESS_GROUP` 유지), 부르는 쪽 `startupinfo` 는 그대로 둔다.
  맥·리눅스는 인자를 하나도 바꾸지 않는다.
- 치환 = 운영 코드 13곳 + selftest 하네스 15곳(합 28곳 · 브리프의 「41」은 속성 참조까지 센 값).
  stdin 으로 사람과 주고받는 호출은 0곳이라 보류한 자리 없음.
- `participant._hidden_window_kwargs()` 는 남겼다(문과 겹치지만 무해 · 기존 시험이 직접 잰다).

## 3. 재발 방지(시험)

- 「윈도우: 자식 문은 창을 숨긴다」 — 윈도우 흉내에서 세 입구 모두 숨김 인자 · OR 합성 · 부른 쪽 dict 무변경 · 비윈도우 무변경.
- 「윈도우: 자식은 _proc 으로만 뜬다」 — 구문 나무로 `agora/` 전체 + `bin/agora`·`bin/agora-signer` 를 훑어
  `subprocess` 직접 띄우기(부르기·별칭·from-import)·`os.system`/`os.popen` 0건. 판정기도 표본으로 먼저 잰다.
- 뮤턴트 M601~M605(축 「자식창」) 전부 KILLED. 게이트 = 519/519 · 547/547 · NOT-APPLIED 0.

## 4. 게시 판본

| 무엇 | 값 |
|---|---|
| 꾸러미 | `agora-client-0.1.10.zip` · 575,838 바이트 · 53 파일 · sha256 `82f870822684bce6ee90ad7bcfc256dcf45924c668026e7a890516a90172ee23` · 재빌드 2/2 동일 |
| 올림(설치 사이트) | ai-jarvis e6d5c39(site/hub) · jarvis-site 배포 `dcf15b18` · 라이브 sha 실측 일치 · 0.1.9 존치 |
| 안내(/join) | 릴레이 배포 `64698c22`(자산 1 = join/index.html · 릴레이 코드 무변경) · 0.1.10 ×3 · 지문 ×3 · skill-pin ×2 |
| 핀 | docs/RELEASES.md 0.1.10 게시 줄 · docs/INVITE.md 3곳 · `--publish-check` rc 0 |

⚠판 번호가 처음으로 두 자리(0.1.10)다. 판을 비교하는 자리(`build_join_page.SKILL_PIN_SINCE`·핀 표 정렬)는
정수 튜플 비교라 「0.1.10 > 0.1.9」가 성립한다(문자열 비교였다면 거꾸로다). 다음에 판 비교를 새로 쓰면 같은 함정을 본다.

## 5. 되돌리기 2종

- 설치 사이트: `wrangler rollback 84f97718-8020-4d5b-b9df-8fb57867f8d4 --config <ai-jarvis>/web/wrangler.jsonc`
- 릴레이 안내: `wrangler rollback 4abb01b9-2eaa-4c04-ba6d-6d01effba024 --config <jarvis-agora>/relay/wrangler.jsonc`
- 둘 다 되돌려도 0.1.9 꾸러미는 그 자리에 있으므로 받는 사람이 멈추지 않는다. 핀·안내 문서는 git revert 740ee78.

## 6. 남은 것

- **윈도우 실기에서 창 0 실측**(상주 한 판 동안 새 콘솔 창 hwnd 0) — 아직 안 쟀다. 운영자 노트북이 0.1.10 으로 갱신된 뒤에만 잴 수 있다.
- 우편 1:1 가지(feat/mail-1to1)는 0.1.10 후보 줄을 쓰고 있었다 — 그 가지는 재제출 때 0.1.11 로 올린다.
- 작업 중 사고 1(근접): 기준선 selftest 를 백그라운드로 돌리는 동안 소스를 고쳤다. 수정은 살아 있었고 변이 잔존도 없었지만,
  selftest 는 소스에 변이를 썼다 되돌리므로 **실행 중 편집은 금지**다.
