# HANDOFF — 119 상담소 BACKLOG 후보 → 티켓 초안 생성기(TICKET=agora-119-autoticket · 2026-10-09)

## 0. 지금 상태(한눈) — 1판 끝(2026-10-09 · 다음 = master 적대 검토 codex 1R → 반영 → 병합·데스크 재배포 = master)
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
- `relay/node_modules` = 심볼릭 링크(이 worktree 에 만들었다 · `git add -A` 금지).

## 4. 남은 것(master)
- 적대 검토(codex 1R) · 병합 · 데스크 재배포 + 라이브 `config.json` `desk.autoticket` = `"~/axdev/master/briefs/auto"` 1줄(라이브 데스크 쓰기).
- 이 가지 밖 기존 적색(이 티켓 변경 0 · 깨끗한 HEAD 에서도 재현): ① 「우편: 일일 보고 예외는 빈 owner_note 만」 — 픽스처 `day` = 2026-10-05 고정 · 받는 쪽 「봉투 ts 날짜 ±1일」 검사가 10-07 이후 거부(code 10) = 날짜 시한폭탄 · killer M577 NOT-APPLIED ② 「상담소자동: 일일 닫힌 칸만」 — `today="2026-10-06"` 고정 · now = 실시계 → 모든 칸이 걸러져 `['day']` 만 = 같은 시한폭탄 · M702·M731 NOT-APPLIED ③ 「상담소자동: 429 그날 포기·code 8 같은 문서」 — 「작성기를 부르면 안 되는 판」 · 픽스처가 now 에서 하루씩 넘긴다 → 【추정】 요일(주간 작성 창) 의존 · 원인 미확정 · M696·M697 NOT-APPLIED ④ 공개 표현 위반 `docs/SPEC-mail-1to1-2026-10-05.md:608`(10-06 T3 정정 줄 · 데몬 이름). 처방 후보 ①② = 픽스처 날짜를 now 기준으로(T3 몫 · 이 티켓 수정 0).
