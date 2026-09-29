# DISPOSITION-impl-r3 — 표적 재검증(codex 반영분) 처분표

TICKET=agora-admission-block-0929 · 2026-09-29 · master 판정 nonce d071dd16(결정1 = A · 표적 재검증) · 대상 = 3a244f6 · 축 = codex C1(HIGH TOCTOU)~C5
agy = **ACCEPT**(C1~C5 전부 닫힘 · 새 결함 없음 · 첨부 방식) · Fable = **REVISE**(C1 부분 · C2~C5 닫힘 · 새 MED 2 · LOW 3 · 정적 판독)
반영 = 68aba22 · 재측정 = run-admission 전 단계 PASS(main 64/64) · master 필수 뮤턴트(원자 조건 해제 → 끼어든 등록 경합 시험 적색 · 59/61) · O5(registered 조건 해제 → 새 끼어들기 2갈래 적색)

| # | 요지 | 처분 |
|---|---|---|
| R1 MED | 조건부 INSERT 는 성공 ≠ 행 있음 — 재조회 실패 시 「썼다」(rc 5)로 거짓 보고 | **수용** — written 을 재조회 확인 **뒤**에 · 그 사이 실패 = rc 6(결과 불명) |
| R2 MED | registered 조건·absent id 선점 갈래에 끼어들기 시험 없음 | **수용** — 3갈래(registered + 대상 지문 변경 · registered + 대상 폐기 · absent + 같은 id 선점) · O5 적색. 「같은 지문의 다른 이름」은 `participants.fingerprint UNIQUE` 로 DB 에 존재 불가(첫 시험이 그 이유로 실패 — 조건절은 이중 방어로 둔다) |
| R3 LOW | 종료 코드 문서 어긋남 | **수용** — RUNBOOK 머리에 0/11/10/3/4/5/6 처리 절차 · HANDOFF 는 1c6356b 에서 이미 11 포함 |
| R4 LOW | 3-7 B 차단 id 미지정 | **수용** — `--participant adm-t18-b` 명시 |
| R5 LOW | 운영자 0명 가드는 원자 조건 밖 | **기록(잔여 위험)** — master 단독 작업 · 창 좁음 |

## 수렴 판단
- agy ACCEPT · Fable 의 새 지적은 전부 반영 · C1 집행은 두 검토자 모두 「닫힘」(Fable 은 보고 문구·시험 범위를 「부분」으로 봤고 R1·R2 로 닫았다) · **R1·R2 반영분(68aba22)은 재검증되지 않았다.**
- 4단계 전제(master d071dd16 ⑤) = codex 재확인 **또는** 표적 r3 두 검토자 ACCEPT + master 대조 → 현재 Fable 은 REVISE(반영 완료·재판정 없음) — 후임이 Fable 표적 r4(R1·R2 만) 1회를 돌리면 조건 충족 여부가 갈린다.
