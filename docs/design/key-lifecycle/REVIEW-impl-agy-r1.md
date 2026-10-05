판정: BLOCK

[문제점] 1 · HIGH · docs/design/key-lifecycle/DESIGN-v3.md:158 및 relay/src/index.ts:155 부근 · 설계 자체의 결함: `/register` 의 전역 등록 속도 버킷 소모 뒤에 차단 검사가 위치함
- 무엇이 어떻게 틀리는지: 설계가 `POST /register` 의 차단 검사 위치를 "서명 검증 뒤 · byId 조회 앞"으로 명시했습니다. 통상적으로 서비스 거부(DoS)를 막기 위해 전역 속도 제한(버킷 소모)은 서명 검증 직후와 같이 가장 앞단에 위치합니다. 이 설계대로 구현하면 차단된 사용자가 유효한 서명으로 `/register` 를 반복 호출할 때 앱 층 차단 검사에 도달하기도 전에 전역 속도 버킷 예산을 소모하게 됩니다. 이는 차단된 은퇴 사용자가 신규 사용자의 합법적 가입을 막을 수 있는 전역 DoS 취약점입니다(프롬프트가 암시한 "전역 등록 버킷 예산 소모" 경로).
- 고치는 법: 설계와 구현 모두 `/register` 의 차단 검사를 전역 속도 제한 버킷을 소모하기 **전**으로 옮기거나, 차단 검사를 통과한 뒤에만 등록 버킷을 소모하도록 수정해야 합니다.

[문제점] 2 · HIGH · ops/admission-block.py:102 · `--remote` 실행 시 Cloudflare CDN 캐시로 인한 사후 대조의 거짓 초록(False Positive)
- 무엇이 어떻게 틀리는지: `relay_files` 함수가 원격(`--remote`) 릴레이 주소의 `/participants/*` 파일들을 단순 GET 으로 가져와 차단 전후 바이트가 동일한지 대조합니다. 그러나 Cloudflare Workers(또는 CDN)는 이 공개 GET 경로를 강하게 캐시합니다. 운영자가 D1 에 차단 행을 쓴 직후 스크립트가 해당 URL을 호출하면 에지 캐시에 남은 '차단 전'의 정상 명부 파일을 받아오게 되며, 실제 D1 로직 결함으로 명부가 망가졌어도 "세 파일 바이트 동일"이라는 거짓 초록(거짓 동일)을 보고합니다.
- 고치는 법: `urllib.request.Request` 호출 시 URL 끝에 무작위 타임스탬프 쿼리 파라미터를 붙이거나(`?nonce=...`), `Cache-Control: no-cache` 헤더를 추가하여 에지 캐시를 우회하고 항상 최신 D1 상태가 반영된 결과를 가져오도록 해야 합니다.

[문제점] 3 · MED · relay/scripts/run-admission.py:59 및 relay/src/index.ts:155 · 동치 변이(Equivalent Mutant) A8 로 인한 변이 시험 필연적 실패
- 무엇이 어떻게 틀리는지: 앱 층 변이 `A8`은 `/register` 의 앱 층 검사에서 지문(`fingerprint`) 조건을 고의로 누락시킵니다. 하지만 이 검사를 뚫더라도 바로 이어지는 `INSERT` 에서 DB 트리거(`participants_admission_block`)가 완벽하게 막아주며, `catch` 블록이 이를 잡아 결국 동일한 403 오류로 반환합니다. 앱 층 검사가 있든 없든 관측 가능한 부작용 차이(예산 소모 등)가 전혀 없으므로 테스트 하네스 입장에서는 변이가 붉은 불(`rc != 0`)을 켜지 못하고 '초록(생존)'으로 판정됩니다. 이로 인해 `run-admission.py` 는 `FAIL(rc 1)` 로 종료되어 배포(배포 게이트)를 항상 가로막게 됩니다.
- 고치는 법: `A8`은 하네스가 블랙박스 검사로 잡을 수 없는 동치 변이이므로 `APP_MUTATIONS` 목록에서 제거해야 합니다. 부득이하게 시험하려면 트리거 발화 시와 앱 층 차단 시의 오류 메시지를 미세하게 다르게 두어 하네스가 이를 구분할 수 있도록 해야 합니다.

[문제점] 4 · MED · relay/src/lib/admission.ts:33 · Cloudflare Workers 직렬화로 인한 `isAdmissionBlockedError` 판정 누수
- 무엇이 어떻게 틀리는지: `cur instanceof Error` 를 통해 오류 사슬을 순회합니다. 그러나 Cloudflare Workers 환경에서 D1 바인딩이 던지는 내부 오류나 RPC 경계를 넘은 오류는 구조적 복제(structured cloning) 과정에서 `Error` 프로토타입을 잃고 순수 객체(plain object)나 `DOMException` 으로 변형되는 경우가 잦습니다. 이 경우 `instanceof Error` 가 `false` 로 평가되어 메시지를 확인하지 못하고 `String(cur)`(예: `[object Object]`)로 평가되면서 판정이 누수됩니다. 결과적으로 401/403 이 아닌 500 오류가 떨어져, 롤백 창 동안 차단된 사용자의 요청이 계속 버킷 예산을 태울 수 있습니다.
- 고치는 법: 프로토타입에 의존하지 않는 덕 타이핑(Duck Typing) 검사로 변경해야 합니다. 예: `const msg = (typeof cur === "object" && cur !== null && "message" in cur) ? String((cur as any).message) : String(cur);`

[논쟁점] (확신도: 중간) tools/detect_ours.py 의 시험 릴레이 `off` 상태 오판
- 내용: `trial_state` 검사에서 `workers_dev: true` (실제 가동 중) 인데 운영 기록이 `off` 로 기재된 불일치가 발생할 경우, `scan_trial` 은 `trial_log_config_mismatch` 를 `incomplete` 에 추가하지만 이후 `if state == "off": return` 에 걸려 시험 릴레이로 GET 쿼리를 보내지 않고 통과해 버립니다. 시험 릴레이가 의도치 않게 탈취되어 실제 가동 중일 경우, 가장 시급한 즉각적 도용 글 경보(`ALARM`)를 띄우지 못하고 2시간 뒤에나 단순 불완전(설정 불일치) 경보만 울리게 될 여지가 있습니다. 불일치 시에도 `workers_dev: true` 라면 강제로 GET을 쏘도록 예외 처리가 필요해 보입니다.

[다음 단계 조언] 원격 적용(시험 릴레이 → 본 릴레이) 전에 반드시 재야 할 것
1. **원격 D1 트리거 마이그레이션 적용 안전성**: `BEGIN ... END;` 블록 안의 세미콜론(`;`)이 포함된 0002_admission_blocks 마이그레이션이 로컬 `sqlite3.executescript` 에서는 잘 돌지만, 실제 원격의 `wrangler d1 migrations apply` 파서에서는 구문 오류나 분리 오작동을 일으키지 않는지 T16 이행 과정에서 반드시 실측해야 합니다.
2. **원격 CDN 전파 지연시간 (Cache Invalidation)**: 사후 대조 스크립트에서 캐시 우회(Cache-busting) 로직을 적용하더라도 원격 워커 노드들 사이에 DB 반영이 지연될 가능성이 있습니다. 운영 스크립트가 실행 직후 즉시 0초 내에 대조를 수행할 때 발생하는 미세한 타이밍 레이스를 시험 릴레이에서 확인해야 합니다.
