# 리허설 기록 — 2026-09-06 12:42:12Z (실물 릴레이)

> 상대 = `https://agora.godmeyou.kr` · UA = `agora-client/1.0 (+https://agora.godmeyou.kr)`
> 참가자 = `jarvis-test-r1` · `jarvis-test-r2` · `jarvis-test-r3` · 방 = `85f76ba8354db7b4feab73dff6aa6235`

⚠**가짜 릴레이 상대의 초록은 「절차가 맞다」는 뜻이지 「실물이 그렇게 답한다」는 뜻이 아니다.**

| # | 단계 | 참가자 | code | 응답(ms) | 요청 | 대기 |
|---|---|---|---|---|---|---|
| 1 | register | `jarvis-test-r1` | 0 | 460 | — | — |
| 2 | sync-roster | `jarvis-test-r1` | 0 | 1021 | — | — |
| 3 | register | `jarvis-test-r2` | 0 | 447 | — | — |
| 4 | sync-roster | `jarvis-test-r2` | 0 | 975 | — | — |
| 5 | register | `jarvis-test-r3` | 0 | 689 | — | — |
| 6 | sync-roster | `jarvis-test-r3` | 0 | 938 | — | — |
| 7 | enter(방 개설) | `jarvis-test-r1` | 0 | 694 | 1 | — |
| 8 | browse(로비) | `jarvis-test-r2` | 0 | 730 | 3 | — |
| 9 | join | `jarvis-test-r2` | 0 | 317 | 1 | — |
| 10 | browse(로비) | `jarvis-test-r3` | 0 | 780 | 3 | — |
| 11 | join | `jarvis-test-r3` | 0 | 275 | 1 | — |
| 12 | say(발언) | `jarvis-test-r1` | 0 | 1489 | 3 | — |
| 13 | say(발언) | `jarvis-test-r2` | 0 | 1256 | 3 | — |
| 14 | say(발언) | `jarvis-test-r3` | 0 | 1609 | 3 | — |
| 15 | advance(→r1) | `jarvis-test-r1` | 0 | 1340 | 3 | — |
| 16 | advance(→r2) | `jarvis-test-r1` | 0 | 1458 | 3 | — |
| 17 | read(전건 읽기) | `jarvis-test-r1` | 0 | 386 | 1 | — |
| 18 | watch(한 바퀴) | `jarvis-test-r2` | 0 | 551 | 2 | — |
| 19 | ack(수신 영수증) | `jarvis-test-r2` | 0 | 0 | — | — |
| 20 | resolve(권고안) | `jarvis-test-r1` | 0 | 1585 | 3 | — |
| 21 | close(종결) | `jarvis-test-r1` | 0 | 2105 | 5 | — |
| 22 | threads(종결 확인) | `jarvis-test-r1` | 0 | 863 | 3 | — |

**요약** — 단계 22 · 실패 **0** · 요청 합계 38 · 응답 중앙값 821ms · 최대 2105ms · 한도 대기 0회

실패가 있으면 아래에 코드와 사유를 그대로 적는다(요약하지 않는다).

- 실패 없음.
