# REVIEW-impl-fable-r4 — 원문(수정 없음)

검토자 = claude -p --model claude-fable-5-1 · 도구 Read/Grep/Glob 만 · cwd = 스크래치 review-r4(커밋 35eb4c7 스냅샷 git archive + 68aba22 diff) · 2026-09-29 22:06 끝 · 프롬프트 = 아래 PROMPT 절(표적 = impl-r3 Fable [문제점 1·2] 반영분만) · stderr 0 B · rc 0

## PROMPT

```
[리뷰 의뢰 — 표적 재검증 r4 · TICKET=agora-admission-block-0929]

당신은 적대적 코드 검토자입니다. 이 폴더(현재 작업 디렉터리)는 커밋 35eb4c7 의 읽기 전용 스냅샷입니다. 도구는 Read/Grep/Glob 만 쓰고, 파일 쓰기·명령 실행·네트워크는 하지 마십시오. 아래 지정 범위 밖을 배회하지 마십시오.

## 배경
직전 라운드(r3)에서 당신(같은 모델)은 REVISE 를 냈고, 그 원문이 docs/design/key-lifecycle/REVIEW-impl-fable-r3.md 입니다. 작성자는 그중 [문제점 1](MED) · [문제점 2](MED) 를 커밋 68aba22 로 반영했습니다(처분표 = docs/design/key-lifecycle/DISPOSITION-impl-r3.md 의 R1·R2 행). 그 커밋의 전체 diff 는 ./COMMIT-68aba22.diff 에 있습니다.

## 질문 — 이것만 답하십시오
Q1. [문제점 1] 「조건부 INSERT 가 0행으로 성공한 뒤 재조회가 실패하면 『차단 행은 썼다』(rc 5)로 거짓 보고」 — 68aba22 의 반영(ops/admission-block.py 약 285~345행: written 을 재조회로 행을 확인한 뒤에 세움 · 그 사이 실패는 attempted 로 rc 6)이 이 지적을 닫았습니까? written/attempted 두 플래그가 모든 경로(INSERT 실패 · INSERT 성공+재조회 실패 · 재조회 0행 · 재조회 성공 뒤 rows_of 실패 · relay_files 실패 · 정상)에서 올바른 종료 코드(0/3/4/5/6)로 떨어지는지 경로별로 표로 보여 주십시오.
Q2. [문제점 2] 「registered 조건과 absent id 선점 갈래에 끼어들기 시험이 없다」 — relay/scripts/admission.py 에 추가된 3갈래(registered + 대상 id 지문 변경 · registered + 대상 폐기 · absent + 같은 id 선점)가 이 지적을 닫았습니까? 특히:
  - 당신이 r3 에서 제안한 「registered + 같은 지문의 다른 이름 등록」 대신 「대상 id 의 지문 변경」 갈래를 쓴 이유로 작성자는 participants.fingerprint 가 UNIQUE 라 그 상태가 DB 에 존재할 수 없다고 주장합니다(relay/migrations/0001_init.sql). 이 주장이 맞는지, 그리고 그렇다면 대체 갈래가 registered 조건의 어느 절(EXISTS 절 / NOT EXISTS 절)을 판별하는지, 판별하지 못하는 절이 남는지 답하십시오.
  - 각 갈래가 해당 조건절을 빼거나 오타 내면 실제로 적색이 되는지(판별력) 코드 판독으로 확인하십시오.
Q3. 이 반영이 새 결함을 만들었습니까? (반영된 줄과 그것이 닿는 경로에 한정 · RUNBOOK-admission.md 의 종료 코드 머리 줄과 3-7 의 --participant adm-t18-b 추가 포함)

## 지정 범위(이 파일들만)
- ./COMMIT-68aba22.diff
- ops/admission-block.py
- relay/scripts/admission.py
- relay/migrations/0001_init.sql · relay/migrations/0002_admission_blocks.sql
- docs/design/key-lifecycle/REVIEW-impl-fable-r3.md · docs/design/key-lifecycle/DISPOSITION-impl-r3.md · docs/design/key-lifecycle/RUNBOOK-admission.md(머리 줄 · 3-3~3-8 행)
- (필요 시 참조만) relay/src/index.ts 의 /register · /events 처리부

## 출력 형식
첫 줄 = 판정 하나만: ACCEPT | REVISE | BLOCK
이어서 Q1 · Q2 · Q3 순서로, 모든 주장에 파일:줄 근거. 결함은 [문제점 N] 심각도(HIGH/MED/LOW) · 위치 · 시나리오(구체 입력 → 잘못된 결과) · 고치는 법. 추정은 【추정】으로 표시. 한국어로 답하십시오.
```

## 출력

ACCEPT

읽기만 했습니다(Read/Grep). 하네스·시험은 돌리지 않았으므로 아래는 모두 코드 판독 결과이고, 「64/64 PASS」·「O5 적색」은 처분표의 주장일 뿐 제가 재지 않았습니다(`DISPOSITION-impl-r3.md:5`).

## Q1. [문제점 1] — **닫혔습니다**

`written = True` 가 재조회 뒤로 옮겨졌고(`ops/admission-block.py:303`), `attempted` 는 INSERT 앞에 세워집니다(`:294`). 종료 코드는 `except Stop` 에서 written → attempted → 그 밖 순서로 갈립니다(`:320-329`).

| 경로 | 실패 지점 | attempted | written | rc | 판정 |
|---|---|---|---|---|---|
| 끼어들기 훅 실패(로컬 전용) | `:292` | F | F | 3 | 옳음 — 쓰기 시도 전 |
| INSERT 실패 | `:295` | T | F | **6** | 옳음 — 원격 커밋 여부 불명 |
| INSERT 성공 + 재조회 실패 | `:298` | T | F | **6** | 옳음 — r3 시나리오(0행 + 재조회 오류)가 rc 5 에서 rc 6 으로 바뀜 |
| 재조회 0행 | `:300-302` | F | F | **3** | 옳음 — 0행 확정 · 「0행」 사유 출력 |
| 재조회 성공 뒤 `rows_of` 실패 | `:304` | T | T | **5** | 옳음 — 행을 확인한 뒤라 「썼다」가 참 |
| `relay_files` 실패(쓰기 뒤) | `:307` | T | T | **5** | 옳음 |
| 정상 · 기존 행 그대로 · 파일 동일 | `:319` | T | T | **0** | 옳음 |
| 기존 행 그대로 · 파일 다름 · 새 행 있음 | `:315-318` | T | T | **5** | 옳음 |
| 기존 행 바뀜, 또는 파일 다름 + 새 행 0 | `:319` | T | T | **4** | 옳음 |

- 쓰기 **앞**의 `relay_files` 실패(`:273`)는 rc 3 입니다.
- `:301` 의 `written = False` 는 이미 False 라 군더더기이고, `:310` 의 `"★없음"` 갈래는 이제 닿지 않습니다. 둘 다 무해합니다.
- 범위 밖 기존 사항: `Stop` 이 아닌 예외(예: wrangler 실행 파일 없음 → `OSError`)는 트레이스백으로 끝납니다(`:94`).

## Q2. [문제점 2] — **닫혔습니다**

**UNIQUE 주장은 맞습니다.** `fingerprint TEXT NOT NULL UNIQUE`(`relay/migrations/0001_init.sql:10`). 제가 r3 에서 제안한 「registered + 같은 지문의 다른 이름 등록」은 끼어들기 INSERT 자체가 UNIQUE 위반으로 실패해, 0행 경로에 닿지 못하고 `:292` 에서 rc 3 으로 끝납니다. r3 의 제안이 틀렸습니다.

**대체 갈래가 판별하는 절**

| 갈래 | 끼어든 뒤 조건의 값 | 판별하는 절 | 그 절을 빼면 |
|---|---|---|---|
| reg1 지문 변경(`admission.py:342-343`) | EXISTS 거짓 · NOT EXISTS 참 | EXISTS 절의 `fingerprint =`(`:279`) | 행이 써짐 → 기존 행이 바뀌어 rc 4 · 차단 행 1 → 적색 |
| reg2 폐기(`admission.py:344-345`) | EXISTS 거짓 | EXISTS 절의 `revoked_at IS NULL`(`:279`) | 같음 → rc 4 · 차단 행 1 → 적색 |
| ghost5 id 선점(`admission.py:346`) | NOT EXISTS 거짓 | absent 조건의 `participant_id =`(`:283`) | 행이 써짐 → rc 0 또는 5 · 차단 행 1 → 적색 |

- absent 조건의 `fingerprint =` 쪽은 기존 ghost3 시험이 판별합니다(`admission.py:323-332`).
- 세 갈래 모두 `(rc, "0행" in out, 차단 행 수)` 세 값을 봅니다(`admission.py:348-349`). 「0행」은 `:302` 에서만 나오므로, 사전 확인(`classify`)에서 멈춘 rc 3 과 구별됩니다. 거짓 초록은 없습니다.
- 끼어들기 SQL 세 개는 모두 성공할 수 있습니다: 지문 값이 서로 다르고(D·E·C), 등록 트리거는 차단된 id·지문만 막습니다(`0002_admission_blocks.sql:18-21`).

**판별하지 못하는 절이 남습니다 — registered 의 NOT EXISTS 절(`:280`).**
- EXISTS 절이 참이면 UNIQUE 때문에 NOT EXISTS 절은 항상 참입니다. 이 절을 빼거나 느슨하게 바꿔도 동작이 같아, 어떤 DB 상태로도 시험할 수 없습니다.
- 더 엄하게 바뀌는 오타(예: `AND participant_id != …` 누락)는 조건이 항상 거짓이 되어, 기존 정상 차단 시험(alice·op, 기대 rc 0)이 적색이 됩니다(`admission.py:246-249`).
- EXISTS 절의 `participant_id =` 도 단독으로는 판별되지 않습니다. 이것을 빼도 NOT EXISTS 절 + UNIQUE 가 같은 뜻을 지킵니다. 두 절을 **동시에** 빼는 퇴행(대상 id 가 바뀌는 끼어들기)만 미검출로 남습니다.
- 작성자의 「이중 방어」 표현(`admission.py:341`)은 정확하고, 결함으로 보지 않습니다.

## Q3. 새 결함 — HIGH·MED 없음, LOW 3건

**[문제점 1] LOW — rc 6 문구가 새 경로와 맞지 않는다**
- 위치: `ops/admission-block.py:325-326`
- 시나리오: INSERT 는 성공하고 재조회만 실패 → 「쓰기 명령이 실패했지만 원격이 이미 커밋했을 수 있다」가 출력됩니다. 실제로 실패한 것은 읽기입니다.
- 고치는 법: 문구를 「쓰기 명령 또는 그 확인(재조회)이 실패했다 — 행 유무 불명」으로 바꿉니다.

**[문제점 2] LOW — RUNBOOK 의 rc 6 재실행 결과에 3 이 빠졌다**
- 위치: `RUNBOOK-admission.md:5`
- 시나리오: 끼어든 등록으로 0행 + 재조회 실패 → rc 6 → 같은 명령 재실행 → 차단 행이 없어 `:246` 을 지나 `classify` 경보로 rc 3. 머리 줄은 「11 이면 행 있음 · 0 이면 이번에 씀」만 적었고, 이때 사유는 「0행」이 아니라 `classify` 문구(`:165-168`)입니다.
- 고치는 법: 「3 이면 첫 실행도 쓰지 않았다 · 모양이 바뀜 → 경보·【질문】」을 더합니다.

**[문제점 3] LOW — 주석이 실제 갈래와 다르다**
- 위치: `relay/scripts/admission.py:333`
- 시나리오: 주석은 「registered(같은 지문의 다른 이름 · 대상 폐기)」인데 실제 첫 갈래는 「대상 id 의 지문 변경」입니다. `:341` 과 어긋납니다.
- 고치는 법: `:333` 을 실제 갈래 이름으로 바꿉니다.

**결함이 아닌 것으로 확인한 것**
- RUNBOOK 머리 줄의 0/11/10/3/4/5 뜻은 코드와 일치합니다(`ops/admission-block.py:27-28`, `:251`, `:290`, `:315-319`).
- 3-7 의 `--participant adm-t18-b` 는 3-7b 의 전제와 맞습니다(`RUNBOOK-admission.md:28-29`). B 는 등록된 적이 없어 absent 사전 확인을 통과합니다.
- 【추정】 새 갈래가 남기는 흔적(reg1 지문 변조 · reg2 `revoked_at='t'` · ghost5 행)은 최종 사진(`admission.py:359`) **앞**에 생기므로 뒤 단계의 기준에 포함됩니다. `/register` 는 `revoked_at` 을 참/거짓으로만 봅니다(`relay/src/index.ts:166`). 명부 렌더 코드는 범위 밖이라 읽지 않았습니다.
- 【추정】 `keygen` 을 같은 이름으로 두 번 부르는 것(`admission.py:337`, `:339`)은 같은 키를 돌려준다는 전제입니다. 아니라면 사전 확인에서 멈춰 「0행」이 없으므로 적색이 됩니다. `threeway.py` 는 범위 밖이라 읽지 않았습니다.

LOW 3건은 문구·문서 정정이라 재검증 없이 반영해도 됩니다.
