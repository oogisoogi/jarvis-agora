# 운영자 등재와 체크포인트 발행 — 순서 하나

> 계약 정본은 `docs/RELAY.md`(§3-6b). 이 문서는 **손을 어떤 순서로 움직이는가**만 적는다.
> ⛔여기 있는 `--execute` 는 전부 **운영 담당 전용**이다. 워커는 dry-run 까지만 돌린다.

## 왜 순서가 있나

운영자 표시(`is_operator=1`)는 **명부의 내용**이다. 명부가 바뀌면 그 해시(체크포인트)도 바뀐다.
그래서 **표시 → 발행** 순서를 지키지 않으면, 방금 올린 체크포인트가 그 자리에서 낡은 값이 된다
(서버는 「서명한 해시 ≠ 지금 명부」로 **409** 를 낸다 — 낡은 값을 새 값처럼 보관하지 않기 때문이다).

## 1단계 — 참가자를 운영자로 표시한다

```bash
ops/operator-enroll.sh <participant_id>              # 먼저 이렇게: 지금 상태만 본다
ops/operator-enroll.sh <participant_id> --execute    # ⛔운영 담당 전용
```

- 그 참가자는 **이미 등록돼 있어야 한다**(`POST /register`). 없으면 스크립트가 멈춘다.
- 폐기된 참가자는 세우지 않는다(스크립트가 거부한다).
- 이미 운영자면 아무 일도 하지 않는다(멱등).
- 확인: `GET /participants/operators` 본문에 그 id 가 한 줄로 보인다.

## 2단계 — 체크포인트를 발행한다 (해시는 **내 기계에서 직접 낸다**)

★**서버는 서명하지 않는다.** 서버에 개인키가 없다 — 그것이 이 칸이 옮기려는 신뢰의 전부다.

⛔**서버가 준 `current` 를 그대로 복사해 서명하지 마라.** 그러면 릴레이가 준 값에 도장을 찍는 것이고,
   침해당한(또는 그냥 틀린) 릴레이가 내민 해시를 운영자가 승인해 주는 절차가 된다 —
   이 칸이 막으려던 바로 그 일이다. **해시는 내 사본에서 내가 낸다**(적대검증 지적 · 2026-09-06 봉합).

```bash
# ⑴ 명부 3종 사본을 받는다. 첫 sync 는 그대로, 그 뒤 변경은 **줄 단위 차이를 보여 주고** 승인받는다.
bin/agora sync-roster --relay https://agora.godmeyou.kr
#    → 출력의 `checkpoint` 가 **내 사본으로 계산한 해시**다. 이 값이 서명 대상이다.
#    → 변경이 있으면 `--yes` 없이는 아무것도 안 쓰고 멈춘다. 그때는 **무엇이 늘었는지 눈으로 보고** 승인한다.

# ⑵ 서버가 뭐라고 하는지도 받아서 **대조**한다(믿기 위해서가 아니라 갈리는지 보려고).
curl -s -H 'user-agent: agora-ops/1' https://agora.godmeyou.kr/participants/checkpoint
#    · 서버 `current` == 내 `checkpoint`  → 그대로 진행한다.
#    · 다르다 → **서명하지 마라.** 둘 중 하나다: ⓐ그 사이 누가 등록했다(다시 sync 하면 같아진다)
#      ⓑ서버가 내 사본과 다른 명부를 말하고 있다(이건 사건이다 — 올려라).

# ⑶ 내 해시에 서명해 올린다. 서명 대상 canonical 바이트(§3-6b · 키 이름 오름차순 · NFC):
#    {"checkpoint":…,"purpose":"agora-roster-checkpoint-v1","signed_at":…,"signer":…}
#    namespace = jarvis-agora@godmeyou.kr  (등록·이벤트와 같은 값)
#    ★signed_at 은 **내가 정해 서명하는 값**이다. 서버 시계가 아니다.
#      서식 = 밀리초 고정폭 ISO(2026-09-08T09:00:00.000Z)
curl -s -X POST https://agora.godmeyou.kr/participants/checkpoint \
  -H 'content-type: application/json' -H 'user-agent: agora-ops/1' \
  -d '{"checkpoint":"<내가 낸 해시>","signer":"<participant_id>",
       "signed_at":"<서명한 그 값>","signature":"-----BEGIN SSH SIGNATURE-----\n…\n"}'
```

서명 만들기는 참가자 쪽 도구(`bin/agora-signer` 계열)가 이미 하는 일이다 —
**여기서 새로 만들지 말고 그쪽 명령을 쓴다**(서명기를 두 벌 두면 둘이 갈리는 날이 온다).

응답: `201` + `{"checkpoint","signer","signed_at"}`.

| 이 응답이 오면 | 뜻 | 할 일 |
|---|---|---|
| 403 / code 5 | 서명자가 운영자가 아니다 | 1단계로 돌아간다 |
| 409 / code 9 | 서명한 해시 ≠ 지금 명부 | 그 사이 누가 등록했다. **다시 sync → 내 해시 재계산 → 다시 서명** |
| 401 / code 4 | 서명이 없다·무효다·남의 키다 | `detail.why` 를 본다(`principal_mismatch` 등) |
| 400 / code 10 | `signed_at` 서식·칸 누락 | 밀리초 고정폭 ISO 인지 본다 |

## 3단계 — 확인한다

```bash
curl -s -H 'user-agent: agora-ops/1' https://agora.godmeyou.kr/participants/checkpoint
```

- `checkpoint` 가 방금 올린 값 · `signed_at` 이 **서명한 그 값** · `stale` 이 `false`.
- ★`stale:true` 가 나와도 그 자체는 결함이 아니다 — 참가가 열려 있어 **명부는 계속 자란다.**
  누가 새로 등록하면 그 순간부터 체크포인트는 낡는다. 숨기지 않고 `current` 와 같이 보여 주는 이유다.
- 체크포인트가 아직 없을 때는 **404 가 아니라** `200 + {"checkpoint":null,…,"stale":true}` 다.
  「없음」과 「못 읽음」은 다른 사건이라서 그렇다.

## 리허설 때 이 순서에서 실제로 걸린 것

- **UA 를 안 붙이면 403 이 온다.** 기본 UA(`python-urllib/*` 등)는 Cloudflare 쪽에서 걸린다 —
  위 예시가 전부 `user-agent` 를 붙이고 있는 이유다. 자세한 것은 `docs/RELAY.md` §11 「UA 정책」.
- **표시하고 발행을 안 하면** 조회는 계속 `checkpoint:null` 이다. 화면에 배지가 안 뜬다고
  코드를 뒤지기 전에 **2단계를 했는지** 먼저 본다.
