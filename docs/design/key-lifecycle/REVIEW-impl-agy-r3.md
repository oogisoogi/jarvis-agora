ACCEPT

- **C1: 닫힘.** 근거(`ops/admission-block.py:275-285`, `relay/scripts/admission.py:324-331`) — 조건부 `INSERT`의 `cond` 구문이 `registered`와 `absent` 모양에 대해 사전 확인과 완벽히 동일한 논리를 구사합니다. D1(SQLite)에서 `INSERT INTO ... SELECT ... WHERE ...`는 단일 문장이므로 원자성을 보장하며, 재조회 시 결과가 없으면 성공하지 않은 것(0행)으로 정확히 판정(결과 불명이 아닌 쓰지 않음으로 처리)합니다. 시험 훅 `--test-interpose-sql`은 독립적인 D1 CLI 호출을 통해 경쟁 창을 실제로 재현해 냅니다.
- **C2: 닫힘.** 근거(`ops/admission-block.py:307-310`, `relay/scripts/admission.py:333-340`) — 동시 등록(`new_rows > 0`)이 발생해 명부 파일 바이트가 달라졌을 때 성공(rc 0)으로 덮지 않고, 대조 미완(rc 5)으로 반환하여 작업자(사람)가 원인을 직접 판정하도록 누수를 막았습니다.
- **C3: 닫힘.** 근거(`docs/design/key-lifecycle/RUNBOOK-admission.md:32`) — RUNBOOK 3-7b 절차를 "등록되지 않은 차단 대상(새 키 혹은 다른 이름)"을 등록하는 것으로 변경하여, 조기 200 반환 분기를 피하고 의도했던 catch 블록의 바인딩 오류(403) 통로를 정상적으로 검증하게 되었습니다.
- **C4: 닫힘.** 근거(`tools/detect_ours.py:203-207`, `tests/test_detect_ours.py:211-226`) — 응답에서 `next_cursor` 칸 누락 시 마지막 페이지로 치부하지 않고, `cursor_missing` 사유와 함께 탐색 불완전 상태로 처리해 글 누락 가능성을 닫았습니다.
- **C5: 닫힘.** 근거(`tools/detect_ours.py:86-94`, `tests/test_detect_ours.py:227-243`) — 본문 읽기 실패(IncompleteRead 등 `HTTPException`) 시 예외로 죽지 않고 `None, reason`을 반환하도록 감싸, 이전에 수집된 발견 경보들을 버리지 않고 함께 보고하도록 수정되었습니다.

새 결함은 없습니다.
- 시험 전용 훅(`--test-interpose-sql`)은 `--local` 모드가 아니면 실행 초기에 차단되므로 원격 운영 환경에서 악용되거나 실수로 트리거될 수 없습니다.
- 종료 코드 변경(이미 차단 11, 대조 미완 5)은 호출자인 `admission.py` 하네스의 기댓값과 정확히 호환됩니다. 또한 운영자가 대조 실패 이후 재실행했을 때 성공(0)으로 착각해 파일 대조를 건너뛰는 인지적 오류를 차단하므로 안전한 설계입니다.
- 탐지기 변경(`HTTPException` 포집)은 기존의 `status is None` 통로를 재활용해 불완전 사유만 덧붙이므로, 정상 응답이나 기타 흐름을 불완전으로 훼손하지 않습니다.
