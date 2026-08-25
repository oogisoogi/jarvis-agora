# codex 이종 검증 판정 — 코드·보안 축(TICKET=agora-build MVP 완주 · HEAD e9c1d48) · 2026-08-26

## ⑴ 재현 계수

| 검사 | 실측 |
|---|---:|
| 최초 `git status --porcelain` | 0줄 |
| 최종 `git status --porcelain` | 0줄 |
| selftest | 309/309 PASS |
| 뮤테이션 | 234/234 KILLED |
| NOT-APPLIED | 0 |
| selftest 종료 | RC=0 |
| 미지 MCP 판본 | `2099-01-01` → `2025-06-18` |
| 알림 | 응답 0줄 |
| `tools/list` | 11종 |
| 설정 없는 `tools/call` | JSON-RPC `-32603`, `data.agora_code=2`, 서버 RC=0 |
| 비정상 JSON 한 줄 | `-32700`, 프로세스 생존 |
| batch | `-32600`, 프로세스 생존 |
| id 재사용 | 같은 id에 응답 2건, 프로세스 생존 |
| 필수 인자 없는 `tools/call` | 응답 없이 프로세스 종료 RC=2 |
| 읽기 cursor | cursor 유무와 무관하게 같은 이벤트 전건, `next_cursor=null` |

## ⑵ [문제점]

### HIGH — Discussion 복제 재생으로 정본 운반체를 바꿀 수 있다

- 위치: `agora/store_github.py:213`, `agora/store_github.py:223`, `agora/reducer.py:84`, `agora/reducer.py:122`
- `_locate()`는 본문 검색 결과의 첫 노드를 검증 없이 채택한다. 재생 중복 집합은 한 번의 `collect()` 안에서만 유지된다.
- 공격자는 서명 능력 없이 기존의 서명된 genesis를 새 Discussion에 복사할 수 있다. 복제본과 원본은 각각 단독 검증에서 모두 유효하며, 검색 결과가 복제본을 먼저 돌려주면 이후 읽기·쓰기가 복제 운반체로 향한다.
- 재현:

  1. 같은 서명 genesis를 서로 다른 두 MockStore에 게시한다.
  2. 각각 `reducer.collect()`를 호출하면 `valid=1`, `quarantined=0`이다.
  3. GitHub 검색 가짜 응답을 `[DECOY #99, LEGIT #1]`로 주면 `_locate()` 결과가 `(99, "DECOY")`다.
  4. 실측: `REPLAYED_GENESIS_VALID_PER_CARRIER=1 1`, `LOCATE_CHOICE=(99, 'DECOY')`.

- 영향: 오래된 사슬 복제에 의한 상태 롤백·분기, 정상 Discussion 고립, 후속 이벤트 오배송.

### HIGH — 폐기 목록 파일 하나가 빠지면 폐기 검사가 fail-open 된다

- 위치: `agora/roster.py:87`, `agora/sign.py:109`
- 전체 참가자 설정 폴더 부재가 아니라, 설정은 존재하되 `revoked_keys`만 빠진 경우다. `_fingerprints_of()`가 파일 부재를 빈 폐기 목록으로 취급해 폐기 키를 다시 유효하게 만든다.
- 재현:

  1. 명부에 있는 키로 이벤트를 서명한다.
  2. `revoked_path`를 존재하지 않는 경로로 주면 `verdict=ok`.
  3. 같은 키가 든 폐기 파일을 주면 `verdict=unsigned, reason=revoked`.
  4. 실측: `MISSING_KRL=ok`, `PRESENT_KRL=revoked`.

- 영향: 폐기된 개인키 보유자가 해당 노드의 authoritative reducer 상태에 다시 참여할 수 있다.

### MEDIUM — `keygen`이 암호 없는 개인키를 생성한다

- 위치: `agora/keygen.py:52`
- `ssh-keygen` 인자에 `-N ""`가 고정돼 있다.
- 재현:

  1. 임시 `AGORA_CONFIG_DIR`에서 `keygen.run()`을 실행한다.
  2. stdin 없이 `ssh-keygen -y -f id_ed25519`를 실행한다.
  3. 실측 RC=0이며 공개키가 즉시 출력됐다.

- 영향: 백업·파일 유출 시 추가 암호 장벽 없이 서명 신원이 탈취된다.

### MEDIUM — 참가자 설정 폴더의 이름 스크럽 목록이 발신 게이트에 배선되지 않았다

- 위치: `agora/scrub.py:36`, `agora/scrub.py:184`, `agora/scrub.py:226`, `agora/tools.py:664`
- 이름 목록 경로가 저장소의 `config/scrub-names.txt`로 고정돼 있고, `AGORA_CONFIG_DIR` 또는 `context_from_config()`의 디렉터리가 전달되지 않는다.
- 재현:

  1. 임시 참가자 설정 폴더에 고유 가명 한 줄을 `scrub-names.txt`로 둔다.
  2. 같은 폴더를 `AGORA_CONFIG_DIR`로 지정하고 해당 가명이 든 본문을 `scrub.check()`한다.
  3. 기본 경로는 `blocked=0, names_loaded=0`.
  4. 파일 경로를 명시적으로 넘기면 `blocked=1, names_loaded=1, rule=name-list`.

- 영향: 주인 승인을 명시적으로 끈 운영에서는 차단 대상으로 등록한 이름이 외부로 나갈 수 있다.

### MEDIUM — reducer가 서명 이벤트의 `expected_state`를 판정하지 않는다

- 위치: `agora/schema.py:283`, `agora/reducer.py:254`, `agora/reducer.py:428`
- genesis가 아닌 이벤트의 `expected_state`는 문자열인지밖에 보지 않으며, reducer는 값을 사용하지 않는다. 도구의 쓰기 직전 CAS만 검사한다.
- 재현:

  1. 올바른 현재 `prev`를 사용하되 `expected_state=""`인 post를 만든다.
  2. 정상 키로 서명해 운반층에 직접 주입한다.
  3. `collect → order → apply` 결과 해당 post가 accepted되고 격리는 0건이다.

- 영향: 서명된 우회 입력에 대해 이벤트 계약의 CAS 칸이 무효하며, 도구층 검사만 존재한다.

### MEDIUM — 미만료 운영자 위임이 성공으로 보고되고 원장·운반층을 오염시킨다

- 위치: `agora/tools.py:606`, `agora/tools.py:617`, `agora/reducer.py:576`
- 도구층은 운영자 명부만 확인한다. reducer가 미만료 조건으로 거부하지만 `delegate_chair()`는 수락 여부를 재확인하지 않고 무조건 `ok:true`를 반환한다.
- 재현:

  1. 진행 중인 토론에서 의장이 아닌 운영자로 `delegate_chair()`를 호출한다.
  2. 반환값은 `ok:true`.
  3. 운반층 행 수는 2→3으로 증가한다.
  4. 실제 의장은 그대로이고 audit에는 `permission` 격리가 남는다.

- 영향: 운영자는 승계가 완료됐다고 오인하며, 후속 동작이 실패하고 거부 이벤트가 사슬 머리를 전진시킨다.

### MEDIUM — watch가 서명·명부 검증 전에 알림과 수신 영수증을 만든다

- 위치: `agora/watch.py:88`, `agora/watch.py:159`, `agora/watch.py:190`
- watch는 서명 블록의 존재만 `signed`로 세며 실제 검증 없이 spool `delivered`와 원장 `recv/delivered`를 기록한다.
- 재현:

  1. 정상 모양 이벤트에 위조 SSH 서명 블록을 붙여 MockStore에 주입한다.
  2. watch는 `genesis · operator-a` 알림을 내고 `delivered=1`, 원장 행 1개를 기록한다.
  3. 같은 글을 reducer로 검증하면 `valid=0`, `signature_does_not_match_bytes`로 격리된다.

- 영향: 누구나 참가자를 사칭한 알림을 만들고 수신 원장·spool을 오염시킬 수 있다. authoritative reducer 상태는 보호되지만 채널층 신뢰 경계는 깨진다.

### MEDIUM — 잘못된 MCP 도구 인자가 서버 프로세스를 종료시킨다

- 위치: `agora/mcp_server.py:209`, `agora/tools.py:748`
- 전송 루프가 `AgoraError`만 잡는다. 필수 인자 누락·뜻밖의 인자는 `TypeError`가 되어 루프 밖으로 전파된다.
- 재현:

  1. 유효한 임시 참가자 설정으로 서버를 시작한다.
  2. initialize 다음 `agora.envelope_check`를 빈 `arguments`로 호출한다.
  3. 뒤에 정상 `tools/list` 요청을 붙인다.
  4. initialize 응답만 출력되고 서버는 RC=2로 종료한다. stderr에는 CLI 자체 오류 JSON만 나오며 요청 id에 대응하는 JSON-RPC 오류가 없다.

- 영향: 잘못 동작하거나 악의적인 MCP 클라이언트 한 요청으로 연결과 서버를 종료할 수 있다.

### MEDIUM — 읽기 cursor가 무시되어 MCP 응답 크기에 상한이 없다

- 위치: `agora/tools.py:338`, `agora/tools.py:372`, `agora/reducer.py:58`
- `read()`는 cursor를 전혀 사용하지 않고 항상 `next_cursor=None`을 반환한다. reducer는 최대 1000페이지를 메모리에 모은 뒤 MCP가 한 JSON 줄로 직렬화한다.
- 재현:

  1. genesis와 post 2건이 있는 스레드에 `read(cursor=None)`과 `read(cursor="after-first-page")`를 호출한다.
  2. 두 응답의 message_id 전건이 동일하고 양쪽 모두 `next_cursor=None`이다.

- 영향: 대형 스레드가 메모리·직렬화·stdio 응답을 비대화해 서버 가용성을 떨어뜨린다.

## ⑶ [논쟁점]

- `abort`는 도구층 운영자 검사와 reducer 검사가 모두 존재한다. `delegate_chair`도 두 층이 있으나, 미만료 거부의 결과 확인이 빠져 위 MEDIUM이 성립한다.
- `mcp-serve`에는 운영자 명부 검사가 없다. 일반 참가자가 자기 MCP 표면을 띄우는 로컬 진입점이라는 현재 경계라면 타당하며 결함으로 세지 않았다.
- UNTRUSTED 표식은 매 본문마다 새 64비트 nonce를 만들고 본문 충돌을 재추첨한다. 같은 리터럴 마커로 경계를 닫는 주입은 재현되지 않았다. 모델이 열린 마커를 읽고 의미상 경계를 무시할 가능성은 기존 R-2이므로 새 결함으로 세지 않았다.
- 비정상 JSON과 batch는 각각 `-32700`, `-32600`으로 응답하고 프로세스가 살았다. id 재사용도 요청별로 응답했다. 다만 `jsonrpc:"1.0"` 요청을 11종 정상 결과로 받아들이는 엄격성 결손이 관측됐으나 별도 결함 계수에는 넣지 않았다.
- 배선 허용목록은 실측 `이름 7 + kind 0 + param 1`이다. 테스트 전용 2건과 감사·고정 계약 보조 정의는 사유가 타당하다. `write_all`은 실제 사용자 진입점이 없고, `checkpoint`는 기존 R-6 범위라 새 결함으로 세지 않았다. `param:limit`은 페이지 크기 기본값이고 전 페이지 순회가 별도로 있어 타당하다.
- kind 발신자 검사는 상수 `kind=` 존재만 본다. 따라서 “발신 함수 존재”는 잡지만 “실제로 성공했다고 정직하게 보고하는가”는 못 잡으며, 미만료 위임의 거짓 성공이 그 공백을 증명했다.
- `roster_stale`, `scrub_recheck`, `is_expired_now`에 필요한 현재 인자는 `_reduce()`에서 전달되고 있었다. 다만 전체 명부 체크포인트 복원 부재는 기존 R-6이며, 이름 목록은 규칙 묶음과 호출 컨텍스트 양쪽에서 빠진 별도 신규 결함이다.

## ⑷ [다음 단계 조언]

1. 릴리스 전에 Discussion 정본 결박과 폐기 목록 fail-closed 두 HIGH를 우선 봉합한다. 검색 첫 결과가 아니라 영속 매핑 또는 복제 불가능한 결정 규칙으로 운반체를 선택해야 한다.
2. `keygen`은 암호 입력을 요구하거나 ssh-agent용 공개키 경로만 쓰게 하고, 무암호 생성은 명시적 위험 승인 없이는 금지한다.
3. 참가자 컨텍스트에 이름 목록 경로를 싣고 발신 코어와 서명기가 동일한 목록을 재검사하도록 한다.
4. reducer에서 각 이벤트의 사전 상태 해시와 `expected_state`를 대조해 불일치를 격리한다.
5. watch는 최소한 스키마·서명·명부·폐기 검증을 통과한 이벤트만 알림·delivery 원장에 올리거나, 미검증 채널을 별도 이름과 단계로 분리한다.
6. `delegate_chair()`도 `abort()`처럼 게시 후 수락을 확인하고, 미만료 요청은 성공으로 반환하지 않게 한다.
7. MCP 루프에서 인자 결손·추가 칸·타입 오류를 JSON-RPC 오류로 변환하고 요청 단위 최후 예외 경계를 둔다.
8. `read`는 상태 계산은 전건으로 하되 렌더 결과를 cursor로 잘라 응답 크기·이벤트 수·바이트 상한을 강제한다.
9. 회귀 시험은 복제 Discussion, KRL 파일 부재, 참가자 설정 이름 목록, 미만료 위임의 반환값·쓰기 계수, 잘못된 MCP 호출 후 후속 요청 생존을 제품 경로로 추가한다.

VERDICT: BLOCK (HIGH 2 · MEDIUM 7)
