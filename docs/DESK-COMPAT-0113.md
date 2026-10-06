# 데스크 클라이언트 0.1.13 호환 확인 — master 실행용 명령 1벌

> TICKET=agora-0113-publish-prep · master 3fc20cbc · HANDOFF-spec-weekly §3 2단계를 그대로 칠 수 있게 풀어 쓴 것.
> **실행 = master**(라이브 쓰기 = 등록 1 · 우편 2) · 작성자 실행 0 · 라이브 발신 0.
> 합격 = 데스크 `mail sync` 결과 **`quarantined` 0 · `added` 2**(그리고 아래 6 의 결정론 판정).

## 0. 전제(앞 단계 PASS 뒤에만)
- 릴레이 = 새 판 deploy 끝(HANDOFF §3 1단계 PASS) · main = `d0d45e8`(판 0.1.13).
- ⚠**순서가 중요하다** — 데스크를 **먼저** 새 판으로 바꾼 뒤에 보낸다. 옛 데스크(3b770e7)가 먼저 받으면 weekly·`weekly_skipped` 든 daily 를 **격리하고 커서를 넘긴다**(자동 재수신 없음 · HANDOFF §3 2).

## 1. 시험 참가자 고르기(실측 2026-10-06 12:5x)
- `~/.config/agora-next`(jarvis-ilt6g52b34) = **쓸 수 없다**: 설정 릴레이가 `https://agora-relay-next.oogisoogi.workers.dev`(라이브 아님) · 꾸러미 0.1.8 · 데스크 명부(`~/.config/agora-desk/allowed_signers` · id 15개)에 그 id 없음.
- `jarvis-test-operator` = 데스크 명부에 있으나 이 기계에 개인키 없음.
- ⇒ **새 시험 참가자 `jarvis-test-weekly0113`**(접두 `jarvis-test-` = 리허설 purge 패턴 `jarvis-test-%` 안 · `tools/rehearsal.py` 규칙) · 설정 폴더 `~/.config/agora-test-0113`(본 참가·데스크와 분리).

## 2. 데스크를 새 판으로(되돌리기 = 7)
```bash
cat ~/.config/agora-desk/mailbox/cursor.json                       # 기록(되돌리기·대조용)
wc -l ~/.config/agora-desk/mailbox/inbox.jsonl ~/.config/agora-desk/mailbox/quarantine.jsonl   # 기록 = 앞값
git -C ~/axdev/jarvis-agora/.wt/desk-stable checkout d0d45e8       # 핀 커밋(33e901f) 불요
git -C ~/axdev/jarvis-agora/.wt/desk-stable log --oneline -1       # 기대: d0d45e8 release: 판 0.1.13 후보 …
python3 -c "import sys;sys.path.insert(0,'$HOME/axdev/jarvis-agora/.wt/desk-stable');import agora;print(agora.__version__)"   # 기대: 0.1.13
```

## 3. 시험 참가자 만들기(라이브 쓰기 = 등록 1)
```bash
export AGORA_CONFIG_DIR="$HOME/.config/agora-test-0113"
export AGORA_SIGNING_KEY="$AGORA_CONFIG_DIR/id_ed25519"
unset NODE_OPTIONS
A="python3 $HOME/axdev/jarvis-agora/.wt/desk-stable/bin/agora"     # 보내는 쪽도 0.1.13 코드(데스크 핀 = config/desk-pin.txt 의 jarvis-counsel)
mkdir -p "$AGORA_CONFIG_DIR"
$A keygen jarvis-test-weekly0113
$A register --relay https://agora.godmeyou.kr --unattended
$A sync-roster --yes                                               # 데스크(jarvis-counsel) 키가 명부에 들어와야 핀 대조가 선다
grep -c '^jarvis-counsel ' "$AGORA_CONFIG_DIR/allowed_signers"      # 기대: 1
```

## 4. 근거 원장 1줄(로컬 파일만 · 발신 0)
주간 보고 항목은 근거(`evidence_ref`)가 이 참가자의 허용 원장(`counsel/signals*.jsonl`)과 맞아야 통에 남는다(3판 M7) — 원장이 비면 항목이 전부 빠져 `skipped` = 「1통」이 안 된다.
```bash
mkdir -p "$AGORA_CONFIG_DIR/counsel"
python3 - <<'EOF'
import datetime, json, os
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
row = {"ts": ts, "source": "update", "op": "host.update", "error_code": "update.sig_mismatch", "version": "0.1.13", "os": "macos-15.6"}
with open(os.path.join(os.environ["AGORA_CONFIG_DIR"], "counsel", "signals.jsonl"), "a", encoding="utf-8", newline="\n") as fh:
    fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
print(row)
EOF
```

## 5. 우편 2통 보내기(라이브 쓰기 = 우편 2 · 받는 이 = 핀 데스크만)
```bash
python3 - <<'EOF'
import datetime, os, sys
sys.path.insert(0, os.path.expanduser("~/axdev/jarvis-agora/.wt/desk-stable"))
from agora import counsel, mail, tools
ctx = tools.context_from_config()
now = datetime.datetime.now(datetime.timezone.utc)
cycle, prev = mail.cycle_week_of(now), mail.cycle_week_of(now - datetime.timedelta(days=7))
weekly = {"cycle": cycle, "version": "0.1.13", "os": "macos-15.6",
          "blocked": [{"text": "호환 실측 — 0.1.13 데스크 수신 확인용 주간 보고",
                       "evidence_ref": {"kind": "cmd", "id": "host.update", "quote": "host.update ×1"}}],
          "owner_note": ""}
print("근거 대조(빈 목록 = 통과):", mail.verify_evidence(ctx, weekly))
w = mail.send_weekly(ctx, weekly)
print("weekly:", {k: w.get(k) for k in ("status", "message_id", "rejected", "pending", "skipped", "error")},
      (w.get("approval") or {}).get("why"))
d = mail._publish(ctx, mail.build(ctx, to="jarvis-counsel", payload={"intent": "daily", "daily": {
    "day": counsel.day_of(now).isoformat(), "version": {"host": "1.1.8", "pack": "1.1.8"}, "weekly_skipped": prev}}))
print("daily:", {k: d.get(k) for k in ("status", "message_id")}, (d.get("approval") or {}).get("why"))
EOF
```
기대 출력:
- `근거 대조(빈 목록 = 통과): []`
- `weekly: {'status': 201, 'message_id': '<32hex>', 'rejected': [], 'pending': None, 'skipped': None, 'error': None} approval_exempt:mail_weekly`
- `daily: {'status': 201, 'message_id': '<32hex>'} approval_exempt:mail_daily`
- 두 message_id 를 적어 둔다(6 의 판정 키).
- ⚠`status` 가 201 이 아니면 멈춘다: 400/10 = 계약(옛 릴레이면 `intent 가 계약 밖` = 1단계 미배포) · 429 = 그 참가자 버킷(새 참가자라 정상이면 0) · `approval` 이 예외가 아니면(겹 code 3) 3 의 `sync-roster` 로 데스크 키가 명부에 들어왔는지 본다.

## 6. 데스크에서 받기 + 판정
```bash
unset AGORA_CONFIG_DIR AGORA_SIGNING_KEY                            # 데스크 껍데기가 자기 환경을 고정한다
~/.config/agora-desk/bin/agora mail sync
```
기대: 출력 JSON 에 **`"added": 2` · `"quarantined": 0`**(`"held_for_roster": false` — true 면 명부 자동 재수신이 새 참가자를 아직 못 받은 것 · 한 번 더 `mail sync`).
⚠데스크 상주가 먼저 받아 갔으면 이 실행은 `added 0` 일 수 있다 — 그때는 아래 결정론 판정이 정본이다:
```bash
grep -c -e '<weekly message_id>' -e '<daily message_id>' ~/.config/agora-desk/mailbox/inbox.jsonl      # 기대: 2
wc -l ~/.config/agora-desk/mailbox/quarantine.jsonl                                                    # 기대: 2 의 앞값과 같다(증가 0)
grep -e '<weekly message_id>' -e '<daily message_id>' ~/.config/agora-desk/mailbox/quarantine.jsonl | wc -l   # 기대: 0
```
- 합격이면 HANDOFF §3 3단계(1.1.8 팩 발행)가 열린다 — 이 PASS 줄을 인용한다.

## 7. 되돌리기
```bash
git -C ~/axdev/jarvis-agora/.wt/desk-stable checkout 3b770e7
```
- 받은 두 행은 데스크 우편함에 남는다 — 옛 데스크(3b770e7)는 weekly 를 사람 글로 보지 않으므로(`HUMAN_INTENTS` 밖) **접수 회신 0** · 다만 옛 `MACHINE_INTENTS`(signal·daily)에 weekly 가 없어 `unread.json` 에 1로 셀 수 있다(`agora mail read` 로 지운다).
- 시험 참가자 정리 = 리허설 purge 패턴 `jarvis-test-%`(master D1) · 로컬 = `~/.config/agora-test-0113` 폴더 삭제.
