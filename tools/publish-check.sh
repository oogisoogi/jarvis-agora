#!/usr/bin/env bash
# 게시 직전 게이트 — **올릴 파일**과 **초대장이 적은 것**이 같은지 본다.
#
# 왜 이것이 필요한가 (2026-09-11 · 하루에 세 번 밟은 자리)
#   초대장(docs/INVITE.md)은 꾸러미 주소와 지문을 **손으로** 적는다. 그런데 꾸러미에는
#   하네스 파일(`agora/*.py`)이 함께 담기므로 **소스를 한 줄만 고쳐도 지문이 바뀐다.**
#   판본을 올리지 않은 채 다시 빌드하면 문서의 지문은 **조용히 낡는다** — 그리고 그 낡음은
#   어디서도 붉어지지 않는다. 받는 사람 화면에만 「지문이 다릅니다」가 뜨고, 그 사람은
#   자기가 뭘 잘못했는지 묻게 된다. (실제로 0.1.3 작업 중 세 번 재핀했다.)
#
# 왜 CI 가 아니라 여기인가 (agy 2R [4] · master 판정 2026-09-11)
#   CI 에서 빌드해 대조하면 **우리가 하지 않은 약속**을 강제하게 된다 — 「다른 기계에서도
#   같은 바이트」는 우리 빌더가 보증하지 않는 축이다(zlib·줄바꿈은 미측정). 러너의 zlib 이
#   다르면 결함이 아닌데 붉어진다. ⇒ 진짜 자리는 **게시 시점**이다: 올릴 그 파일을 놓고
#   그 파일의 지문이 문서와 같은지 보는 것. 그것은 기계마다 달라지지 않는다.
#
# 쓰기
#   bash tools/publish-check.sh <올릴 zip> <INVITE.md>
#   rc 0 = 게시 가능(올릴 경로와 지문 한 줄을 찍는다) · 1 = 어긋남(무엇이 다른지 찍는다)
#   rc 2 = 쓸 수 없음(파일 없음·인자 부족)
set -u

usage() {
  echo "쓰기: bash tools/publish-check.sh <올릴 zip> <INVITE.md>" >&2
  exit 2
}

[ $# -eq 2 ] || usage
ZIP="$1"; INVITE="$2"
[ -f "$ZIP" ] || { echo "없는 파일: $ZIP" >&2; exit 2; }
[ -f "$INVITE" ] || { echo "없는 파일: $INVITE" >&2; exit 2; }

python3 - "$ZIP" "$INVITE" <<'PY'
import hashlib, json, os, re, sys, zipfile

zip_path, invite_path = sys.argv[1], sys.argv[2]

def fail(lines):
    print("== 게시 불가 — 어긋난 것 ==")
    for ln in lines:
        print("  ·", ln)
    raise SystemExit(1)

problems = []

# ── 축 ⑴ 지문 — 올릴 그 파일의 sha256 이 문서의 지문과 같은가 ────────────────
digest = hashlib.sha256()
with open(zip_path, "rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        digest.update(chunk)
zip_sha = digest.hexdigest()
size = os.path.getsize(zip_path)

invite = open(invite_path, encoding="utf-8").read()
doc_shas = set(re.findall(r"\b[0-9a-f]{64}\b", invite))
if not doc_shas:
    problems.append("초대장에 지문이 한 자리도 없다")
elif len(doc_shas) > 1:
    problems.append(f"초대장의 지문이 한 값이 아니다({len(doc_shas)}종) — 옛 지문이 남았다: {sorted(doc_shas)}")
elif zip_sha not in doc_shas:
    problems.append(f"지문이 다르다 — 파일 {zip_sha} ↔ 초대장 {doc_shas.pop()}")

# ── 축 ⑵ 판본 — 문서의 주소·꾸러미 안의 판본·내용물 표가 한 값인가 ────────────
doc_vers = set(re.findall(r"agora-client-([0-9][^.]*\.[^.]*\.[^.\s/]+)\.zip", invite))
if not doc_vers:
    problems.append("초대장에 꾸러미 주소가 없다")

with zipfile.ZipFile(zip_path) as z:
    names = set(z.namelist())
    try:
        init = z.read("agora/__init__.py").decode("utf-8")
    except KeyError:
        init = ""
        problems.append("꾸러미에 agora/__init__.py 가 없다")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    pkg_ver = m.group(1) if m else None
    if pkg_ver is None:
        problems.append("꾸러미에서 판본을 읽지 못했다")

    manifest = None
    if "PACKAGE-MANIFEST.json" in names:
        try:
            manifest = json.loads(z.read("PACKAGE-MANIFEST.json").decode("utf-8"))
        except ValueError as e:
            problems.append(f"내용물 표를 읽지 못했다: {e}")
    else:
        problems.append("꾸러미에 내용물 표(PACKAGE-MANIFEST.json)가 없다")

    if doc_vers and pkg_ver and doc_vers != {pkg_ver}:
        problems.append(f"판본이 갈렸다 — 초대장 {sorted(doc_vers)} ↔ 꾸러미 {pkg_ver}")
    if manifest and pkg_ver and manifest.get("version") != pkg_ver:
        problems.append(f"내용물 표의 판본이 다르다 — 표 {manifest.get('version')} ↔ 꾸러미 {pkg_ver}")

    # ── 축 ⑶ 크기·내용물 — 표에 적힌 것이 **그 해시로** 실제로 들어 있는가 ─────
    #    ★지문 한 값만 보면 「이 파일이 통째로 그 파일인가」까지만 안다. 표 대조는
    #      **무엇이 들었는지**를 본다 — 빠진 파일·바뀐 파일·표 밖 파일이 여기서 드러난다.
    if manifest:
        listed = manifest.get("files") or {}
        in_zip = {n for n in names if n != "PACKAGE-MANIFEST.json"}
        missing = sorted(set(listed) - in_zip)
        extra = sorted(in_zip - set(listed))
        changed = []
        for name, want in sorted(listed.items()):
            if name not in in_zip:
                continue
            got = hashlib.sha256(z.read(name)).hexdigest()
            if got != want:
                changed.append(name)
        if missing:
            problems.append(f"표에 있는데 꾸러미에 없다({len(missing)}): {missing[:5]}")
        if extra:
            problems.append(f"표에 없는데 꾸러미에 있다({len(extra)}): {extra[:5]}")
        if changed:
            problems.append(f"표와 내용이 다르다({len(changed)}): {changed[:5]}")

if problems:
    fail(problems)

print("== 게시 가능 ==")
print(f"  파일   : {os.path.abspath(zip_path)}")
print(f"  크기   : {size:,} 바이트 · {len(names)} 항목")
print(f"  판본   : {pkg_ver}")
print(f"  sha256 : {zip_sha}")
print("  ⚠이 파일을 그대로 올려라 — 다시 빌드해 대조하지 마라(기계가 다르면 바이트가 달라질 수 있다).")
PY
