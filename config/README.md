# config — 예시와 실물의 자리

★**이 폴더의 파일은 전부 예시다.** 실물은 `~/.config/agora/`(또는 `AGORA_CONFIG_DIR`)에 두고,
저장소에는 올리지 않는다(`.gitignore` 가 `participant.json`·`ledger.jsonl`·키 파일을 막는다).

| 파일 | 무엇 | 실물 위치 | 권한 |
|---|---|---|---|
| `participant.json.example` | 참가자 신원(**비밀 없음** — 지문뿐) | `~/.config/agora/participant.json` | `600`(폴더 `700`) |

⚠`operator` 는 **참·거짓**이다(「이 참가자가 운영자인가」 — K-3 의 `abort` 권한이 여기서 갈린다).
소속 이름을 적는 칸이 아니다. 예시에 문자열을 적었다가 계약 검사에 걸렸다.
| `config.json.example` | 운영 설정(운반층·승인 게이트·예산·watch 주기) | `~/.config/agora/config.json` | `600` |
| `allowlist-v1.json` · `allow-domains.txt` | 스크럽 1단(허용) | 그대로 사용 | — |
| `scrub-rules-v1.json` | 스크럽 2단(차단) | 그대로 사용 | — |
| `scrub-names.example.txt` | 이름 목록 예시 | `config/scrub-names.txt`(무시 대상) | — |

★**운반층 칸**(2026-09-05 릴레이 전환): 예시는 `transport: "relay"` + `relay.url` 이다.
GitHub Discussions 를 계속 쓰는 참가자는 `repo`·`categories` 를 그대로 두면 된다 —
해석 순서는 ⑴`transport` 명시 ⑵`relay.url` ⑶`repo` ⑷없으면 `relay.url` 을 빠진 칸으로 지목이고,
**둘 다 있으면 릴레이가 이긴다**(`docs/TRANSPORT-RELAY.md` §4).

## 두 파일을 가른 이유
`participant.json` 은 **계약된 칸만** 허용한다(모르는 칸이 하나라도 있으면 파일 전체가 거부된다).
그래서 운영 설정을 거기 넣을 수 없다 — 넣는 순간 참가자 신원을 못 읽는다.
⚠처음에는 실제로 그렇게 짜여 있었고, 그 경로는 **항상 빈 설정으로 조용히 돌고 있었다**
(S6-2 에서 설정 예시를 만들다 드러났다).

## 승인 게이트
- 기본은 **on** 이다. `config.json` 이 **없어도 on** 이다 — 파일을 지우는 것이 게이트를 끄는
  방법이 되면 안 되기 때문이다.
- 끄는 길은 `config.json` 의 `"human_approval": false` **하나뿐**이다(환경변수·명령행으로는 못 끈다).

## 키
- 키는 이 폴더에 두지 않는다. `agora keygen` 이 만들고, 개인키는 ssh-agent 나 권한이 잠긴
  파일에 둔다. `participant.json` 에는 **지문만** 들어간다.
