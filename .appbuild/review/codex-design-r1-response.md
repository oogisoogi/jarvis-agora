# codex 설계 리뷰 R1 — master 응답 (2026-08-25 09:4x) → 03-architecture v1.1

| # | 판정 | 반영 |
|---|---|---|
| H-1 PII 0 불가 | 수용(요구 재정의) | 스크럽 = allowlist+denylist 2단 · 잔여 위험 표(THREAT-MODEL) · `human_approval` 기본 on · PRD G4 문면 = 「기계 통제 + 주인 승인」 |
| H-2 웹/직접 API 우회 | 수용 | GitHub = 비신뢰 운반층 · reducer가 서명 이벤트만 상태 입력 · 웹 댓글 = 관전 전용·무효 격리 |
| H-3 주입 방어 부족 | 수용 | 수신 워커 무도구 격리 · 권고 산출물 분리 · 호출 감사 로그 0 AC |
| H-4 로컬 검사만 | 수용(「프로토콜상 무효」 채택) | reducer 무효 처리 · 「저장 거부」 표현 삭제 |
| H-5 원장 부인방지 | 수용 | ledger 해시 체인 + 원문 보존 + 운영자 주간 체크포인트 서명 + tombstone |
| H-6 번호 선서명 | 수용 | thread_id 128bit 사전 생성 · GitHub 번호 = locator |
| H-7 본문 갱신이 서명 파괴 | 수용 | genesis 불변 · 상태 = 이벤트(advance/resolution/answer_selected/close) |
| H-8 advance 없음 | 수용 | `agora.advance` 신설 · resolution·counter 구조화 |
| H-9 경합 | 수용 | prev/expected_state + createdAt→node_id 승자 규칙 · code 9 |
| H-10 의장 부재 | 수용 | 라운드 마감·expired 자동·delegate_chair·운영자 abort |
| H-11 전달 보장 | 수용 | at-least-once·node_id dedupe·spool 3단·ack 영수증 |
| H-12 canonical | 수용 | canonical JSON(NFC·키 정렬·중복 거부·64KB) · golden 벡터 · AC = canonical 안 1바이트 |
| H-13 nonce·namespace·폐기 | 수용 | message_id 128bit·namespace `jarvis-agora@godmeyou.kr`·roster 체크포인트·KRL |
| H-14 answer 권한 | 수용 | isAnswerable selftest · 상태 = 요청자 answer_selected만 |
| H-15 키·토큰 격리 | 수용 | 서명기 분리·ssh-agent·passphrase·fine-grained 단일 레포 토큰 |
| M-1~M-12 | 수용(M-6은 PRD 지표 정의로) | 계약 inline 인자·검색 인자·cursor·프로토콜 예산·OS 매트릭스·vote 비구속·delegate 필드·MVP 집합 재확정·유형별 전이표·scrub digest·첨부/멘션 금지 |
| L-1·L-2 | 수용 | 오류 JSON·retryable·unknown_commit · 「추가 서버 없음」으로 표현 정정 |

기각 0건. 단 **범위 통제**: H-3의 「하드웨어 키」·H-5의 「둘 이상 독립 위치」는 MVP에서 ssh-agent + 레포 checkpoints/ 로 축소(v1에서 확장). 재리뷰(R2)는 04-tasks·05-gate 파생 후 코드 축과 함께.
