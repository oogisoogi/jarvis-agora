"""계약 상수 — 설계 문서가 확정한 값을 코드에서 한 곳에 모은다.

이 파일의 유래: 04-tasks §0 의 공백(K-*)을 조율자 회신 전까지 격리하려고 만들었고,
2026-08-25 10:0x 에 **전 항목이 확정**되어 이제는 「미회신 격리」가 아니라
**계약 상수 1곳 모음**이다(성찰 R-5).

★값을 바꾸려면 설계 문서를 먼저 바꾼다. 여기가 정본이 아니라 **정본의 사본**이다.
각 상수에 정본 위치를 주석으로 단다 — 사본이 원본을 못 가리키면 사본은 곧 거짓말이 된다.
"""

from __future__ import annotations

# 설계 §D2 · §2-1a — 서명 namespace. 다른 namespace 로 만든 서명은 무효다.
SIGN_NAMESPACE = "jarvis-agora@godmeyou.kr"

# 릴레이 계약 §3-6b(`docs/RELAY.md@main 993053e`) — 명부 체크포인트 서명 문서의 `purpose` 값.
# ★서명 대상은 네 칸 `{checkpoint, purpose, signed_at, signer}` 이고 규칙은 등록·이벤트와 같다
#   (NFC · 키 이름 오름차순 · 개행 정규화). namespace 도 같은 하나(`SIGN_NAMESPACE`)다.
# ★`signed_at` 이 **서명 대상 안**이라는 것이 이 칸의 핵심이다 — 밖에 두면 「언제의 명부인가」를
#   릴레이가 마음대로 적을 수 있고, 그러면 이 칸이 옮기려던 신뢰가 릴레이에게 되돌아온다.
CHECKPOINT_PURPOSE = "agora-roster-checkpoint-v1"

# 밀리초 고정폭 ISO(계약 §3-0) — 문자열 정렬 = 시간 정렬이 되게 하는 서식이다.
CHECKPOINT_TIME_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"

# 릴레이 계약 §3-1(`docs/RELAY.md@b2ca815`) — 등록 소유 증명이 서명하는 문서의 `purpose` 값.
# ★이 칸이 **서명 대상 안에** 있어야 등록 서명을 다른 자리(이벤트·다른 목적)에 재사용할 수 없다.
#   값이 한 글자라도 다르면 서버의 canonical 바이트와 안 맞아 401 이 난다 — 그래서 상수로 둔다.
REGISTER_PURPOSE = "agora-register-v1"

# 설계 §2-1a(K-4) — genesis 이벤트의 두 값. reducer 는 이 조합만 genesis 로 인정한다.
GENESIS_PREV = "genesis"
GENESIS_EXPECTED_STATE = ""

# 설계 §D4 — canonical JSON 상한.
MAX_EVENT_BYTES = 64 * 1024

# ★읽기 한 쪽의 상한(M-d · codex 2026-08-26). `read` 는 인자에 `cursor` 를 두고도
#   응답을 자르지 않아 **상한이 없었다** — 스레드가 길어지면 한 번의 호출이 얼마든 커진다.
#   ⚠자르는 것은 **화면**뿐이다. 상태는 언제나 전건으로 계산한다(자른 뒤의 상태는 상태가 아니다).
READ_PAGE_EVENTS = 50
READ_PAGE_BYTES = 64 * 1024

# 설계 §3-2 — 봉투 로그 발췌 상한.
MAX_LOG_EXCERPT_BYTES = 4 * 1024

# 설계 §2-1 — message_id·thread_id 는 128비트 hex(32자).
ID_HEX_LEN = 32

# 설계 §2-3 ④(R-3) — 노드 시계 오차 흡수. deadline + 이 값 이전의 advance 는 정시로 본다.
# ★더 중요한 규칙은 값이 아니라 순서다: 유효 advance 가 있으면 언제나 expired 보다 우선한다.
EXPIRED_GRACE_SECONDS = 300

# 설계 §5 — 발언 예산 기본값.
DEFAULT_BUDGET_POSTS_PER_ROUND = 2
DEFAULT_BUDGET_MAX_CHARS = 6000

# 계약 확장 9(2026-09-11 · master 판정 [master#10906357] A) — **방이 자기 예산을 들고 다닌다.**
# ★왜: 예산 칸은 debate 면 회차별(`pid@r<n>`)인데 **광장 방은 회차를 안 올린다**(의장 루프에 안
#   맡기는 것이 규칙) ⇒ 한 사람이 광장에 쓸 수 있는 글이 `posts_per_round` 개로 평생 고정됐다.
#   실측 2026-09-11: 라이브 광장에서 방을 연 참가자에게 남은 글이 **1개**였고, 하루 한 바퀴는
#   마커를 3개 쓸 수 없어 첫날 멈췄다. ⇒ 예산의 출처를 **참가자 설정에서 방 genesis 로** 옮긴다.
# ★덤으로 닫히는 것: 전에는 예산이 **참가자 config.json** 에서 왔다 — 내 설정이 릴레이보다
#   느슨하면 릴레이는 `budget_exceeded` 로 격리하고 나는 받아들여 두 쪽 상태가 갈렸다
#   (`tools.py` 의 「릴레이가 받기는 했지만 반영하지 않았다」가 그 자리다). 방 하나가 예산을
#   들고 다니면 **모두가 같은 숫자를 본다.**
# ★상한이 있는 이유: 무한 예산은 debate 방의 독점 방지 규칙을 조용히 없앤다. 범위 밖은
#   **격리**한다(모양이 아니라 정책이므로 스키마가 아니라 리듀서가 판정한다).
# 예산의 칸 이름 — **여기가 유일한 정의처**다(스키마·프로토콜·리듀서가 전부 이것을 인용한다).
BUDGET_FIELDS = ("posts_per_round", "max_chars_per_round")
MAX_BUDGET_POSTS_PER_ROUND = 1000
MAX_BUDGET_MAX_CHARS = 300000

# 광장은 「제안이 쌓이는 곳」이다 — 토론방 기본값(2)으로는 돌지 않는다.
PLAZA_BUDGET_POSTS_PER_ROUND = 200
PLAZA_BUDGET_MAX_CHARS = 100000

# 설계 §D5 — watch 폴링 간격 기본값(초).
DEFAULT_WATCH_INTERVAL_SECONDS = 60

# 설계 §2-1a(F-14) — 승인 게이트 기본값. 끄는 경로는 config.json 하나뿐이다.
DEFAULT_HUMAN_APPROVAL = True
HUMAN_APPROVAL_REQUIRED = "human_approval_required"

# 설계 §2-1a(K-5) — participant.json 의 칸. 비밀은 담지 않는다(지문만).
PARTICIPANT_FIELDS = ("id", "display_name", "key_fingerprint", "namespace", "operator")

# 설계 §7 · §2-1a(K-3) — 명부 파일들.
ROSTER_ALLOWED_SIGNERS = "participants/allowed_signers"
ROSTER_REVOKED_KEYS = "participants/revoked_keys"
ROSTER_OPERATORS = "participants/operators"

# 설계 §2-2 — 이벤트 kind 9종. §9 가 한때 8종이라 적었으나 표(§2-2)가 정본이다.
KINDS = (
    "genesis", "post", "advance", "resolution", "answer_selected",
    "close", "delegate_chair", "abort", "vote",
)

# 설계 §D1 — 저장층 카테고리 3종. problem 만 answerable 이어야 한다(§8 FR-5).
CATEGORIES = ("problem", "knowhow", "debate")
ANSWERABLE_CATEGORY = "problem"
