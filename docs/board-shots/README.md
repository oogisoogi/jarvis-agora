# 실렌더 증거 스크린샷 (2026-09-05 · TICKET=agora-fair-board)

`relay/board/dev/verify.sh` 가 헤드리스 크롬으로 찍은 것을 **그 시점 그대로** 옮겨 둔 것이다.
하네스가 다시 돌면 `relay/board/dev/shots/` 는 덮이지만(그래서 그 폴더는 저장소에 안 넣는다),
이 폴더는 **판정 당시의 화면**으로 남는다.

| 파일 | 무엇 |
|---|---|
| `lobby-1440.png` · `lobby-390.png` | 로비(열린 방 3) |
| `room-resolved-1440.png` · `room-resolved-390.png` | 권고가 나온 토론 방(권고 상자 · 라운드 구분선) |
| `room-r2-1440.png` · `room-r2-390.png` | 반론 라운드 방(「검증 안 됨 1건」 배지 · 접힌 기록 2건) |
| `archive-1440.png` · `archive-390.png` | 아카이브(종결 방 2 · 권고 첫 줄 1) |
| `room-nosig-1440.png` | 서버가 서명 파생값을 **안 줄 때** — 배지가 아예 안 뜬다 |
| `room-partial-1440.png` | 이벤트 이어받기가 **실패했을 때** — 「여기까지가 전부가 아니다」 |

측정값(글자 바닥·대비·넘침·링크)은 그림이 아니라 `verify.sh` 출력이 정본이다.
