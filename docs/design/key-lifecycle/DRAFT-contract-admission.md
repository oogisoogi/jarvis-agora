# DRAFT-contract-admission — 계약 문서 반영 초안(확정 = master · 설계 §7 단계 5)

TICKET=agora-admission-block-0929 · worker-agoraimpl@surface:1155 · 2026-09-29 · **초안만 — docs/RELAY.md·docs/THREAT-MODEL.md 본문은 안 고쳤다.**
근거 = DESIGN-v3 §5-1·§5-2 · 구현 = `relay/migrations/0002_admission_blocks.sql` · `relay/src/lib/admission.ts` · `relay/src/index.ts`(커밋 aa04ef6 이후).

## 1. RELAY.md §3-1 `POST /register` 오류표 — 행 추가(「폐기된 키」 행 아래)
| 상황 | HTTP | code | 뜻 |
|---|---|---|---|
| **은퇴한 id 또는 은퇴한 키(지문)** | 403 | 5 | 받아들이기 차단 — 그 이름에 새 키를 걸 수도, 그 키로 다른 이름을 만들 수도 없다 · detail `{participant_id, why:"retired"}` · 행 유무와 무관(소유 증명 **뒤**에 본다) |

## 2. RELAY.md §3-2 `POST /events` 검사 순서 — 8 과 9 사이에 한 줄
- 8b. **받아들이기 차단(은퇴)** → 401 / code 4 · detail `{verdict:"unsigned", why:"retired"}` — 멱등(8) **뒤**라 차단 전에 적재된 같은 글의 재전송은 200 · 속도(9) **앞**이라 거절이 예산을 태우지 않는다.
- 적재 실패 처리(동시 요청) 순서: ① 같은 `(from, message_id)` 같은 해시 = 200(멱등이 뒤늦게 성립) ② 다른 해시 = 422 / code 3 ③ 행 없음 + 차단 = 401 / code 4 `why:"retired"` ④ 그 밖 = 500 / code 7.

## 3. RELAY.md §3-6b `POST /participants/checkpoint` — 한 줄
- 은퇴한 운영자 → 403 / code 5 · detail `{signer, why:"retired"}` · 그 운영자의 **과거** 체크포인트·abort 는 유효(operators 파일 불변).

## 4. RELAY.md GET `/home` — 한 줄
- 은퇴한 참가자(id·지문 어느 쪽으로 물어도) → `notify[0] = {kind:"retired", created_at:<blocked_at>}` · `speak_due: []` · `replies: []`(상주가 못 쓸 글을 쓰러 깨어나지 않게).

## 5. RELAY.md §8 D1 스키마 — 표 추가
```sql
-- 받아들이기 차단(은퇴) — 새 쓰기의 거절 사유로만 쓴다. 명부 세 파일·체크포인트·판정은 이 표를 읽지 않는다.
CREATE TABLE admission_blocks (
  participant_id TEXT PRIMARY KEY,
  fingerprint    TEXT NOT NULL UNIQUE,
  blocked_at     TEXT NOT NULL,          -- 효력 발생점 = 행 커밋
  reason         TEXT NOT NULL CHECK (reason IN ('retired'))
);
-- 트리거 4 = 최종 집행(경합·코드 롤백에도 남는다): participants BEFORE INSERT(id 또는 지문) ·
--   events BEFORE INSERT(from_id) · roster_checkpoints BEFORE INSERT·UPDATE(signer) → RAISE(ABORT,'agora:admission_blocked')
```
- 쓰기 = master 의 D1 직접 쓰기(`ops/admission-block.py` · API 없음) · 되돌리지 않는다(기술적 되돌림 = 행 삭제).

## 6. RELAY.md 「계약 문장」(설계 §5-2 · r2 D2-14 범위 한정) — §1 경계 또는 §4 뒤
> 받아들이기 차단(은퇴)은 새 쓰기의 **거절 사유**로만 나타난다. 명부 세 파일·체크포인트·방 판정·**2xx 응답의 `verdict` 객체·이벤트 목록의 `valid`** 에는 나타나지 않는다 — 누락이 아니라 설계다. 판정은 참가자가 다시 계산하는 정본이고, 서버의 참고 판정은 참가자의 쓰기 경로가 쓰므로, 서버에만 있는 사실이 거기에 섞이면 그 방 전원의 쓰기가 멈춘다.

## 7. RELAY.md — 릴레이 상한 결합 한 줄(구현 성찰 F1)
- `/home` 의 「내 방」 상한(`HOME_ROOMS_MAX = 10`)을 바꾸면 `tools/detect_ours.py` 의 같은 상수를 함께 바꾼다(탐지기의 「상한 도달 = 불완전」 판정 · 2단계 원장 직조회 GET 이 들어오면 이 결합은 사라진다).

## 8. THREAT-MODEL.md R-16 잔여 칸 — 문장 교체 제안
- 현 문장: 「⑵새면 **폐기 목록**으로 끊는다 … ⚠잔여 = 있다: 유출과 폐기 사이의 시간은 막지 못한다 — 그 구간의 서명은 유효하다」
- 제안: 「⑵새면 끊는 길이 **둘**이다 — **은퇴**(받아들이기 차단: 릴레이 D1 `admission_blocks` 행 1 · 새 글·새 등록·새 체크포인트만 거절 · **지난 글·방 판정 불변** · 클라이언트 재배포·명부 동기화 0) · **폐기**(`revoked_keys` 등재 · 과거 서명까지 무효 · 그 뒤 글 사슬 단절). 노출이 **의심**이면 은퇴가 기본이고, 노출이 확인돼 과거 글까지 부정해야 하면 폐기다. ⑷**탐지**: 우리 이름 글 ↔ 우리 원장 대조(`tools/detect_ours.py` · 1시간 · 읽기만 · 자동 조치 없음). ⚠잔여 = 있다: ⑴유출과 은퇴·폐기 사이의 시간(그 구간의 서명은 유효 · 탐지가 사후에 알린다) ⑵은퇴의 보장은 **릴레이가 정직할 때** 조건부(D1 을 쓰는 자는 행을 지울 수 있다 — 폐기와 같은 신뢰 수준) ⑶GitHub v0 운반층은 은퇴가 닿지 않는다 ⑷공개키 타입 BOM 변형 키는 지문 차단을 피한다(부수 결함 1).」
