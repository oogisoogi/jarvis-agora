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

# 설계 §5 — 발언 예산 기본값. 참가자 config.json 이 덮어쓸 수 있다(값이 실제로 읽히는지는 검증 대상).
DEFAULT_BUDGET_POSTS_PER_ROUND = 2
DEFAULT_BUDGET_MAX_CHARS = 6000

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
