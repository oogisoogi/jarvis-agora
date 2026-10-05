# DISPOSITION-impl-r4 — Fable 표적 r4(impl-r3 R1·R2 반영분) 처분표

TICKET=agora-admission-block-0929 · 2026-09-29 · 대상 = 68aba22(R1·R2 반영) · 검토 = Fable(claude-fable-5-1) 표적 r4 · 원문 = REVIEW-impl-fable-r4.md
판정 = **ACCEPT** — Q1(R1) 닫힘 · Q2(R2) 닫힘(UNIQUE 주장 확인 · r3 제안이 틀렸음을 검토자가 인정) · 새 결함 HIGH·MED 0 · LOW 3(문구·문서)

| # | 요지 | 처분 |
|---|---|---|
| L1 LOW | rc 6 문구가 「쓰기 명령이 실패」만 말한다 — INSERT 성공 + 재조회 실패 경로와 안 맞음 | **수용** — 「쓰기 명령 또는 그 확인 재조회가 실패했다 — 원격에 행이 있는지 모른다」 |
| L2 LOW | RUNBOOK 머리 줄 rc 6 재실행 결과에 3 이 없다 | **수용** — 「3 이면 첫 실행도 쓰지 않았고 그 사이 모양이 바뀌었다 → 경보 · 멈추고 【질문】」 |
| L3 LOW | 하네스 주석이 실제 갈래(대상 id 지문 변경)와 다르다 | **수용** — 주석을 실제 갈래 이름으로 |
| — | registered NOT EXISTS 절은 UNIQUE 때문에 어떤 DB 상태로도 판별 불가 | **기록(설계상 이중 방어 · 검토자도 결함 아님)** |
| — | 【추정】 keygen 같은 이름 두 번 = 같은 키 | **확인** — `relay/scripts/threeway.py:40`(파일이 있으면 새로 만들지 않는다) |

## 수렴 판단
- 표적 r3 에서 agy ACCEPT · 표적 r4 에서 Fable ACCEPT → master d071dd16 ⑤의 4단계 전제 중 「표적 두 검토자 ACCEPT + master 대조」 쪽의 두 검토자 조건이 채워졌다(master 대조는 master 몫).
- LOW 3 은 문구·주석·문서만(동작 변화 0) · 검토자 권고대로 재검증 없이 반영 · 회귀 = 아래 커밋 메시지에 실측.
