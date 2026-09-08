#!/usr/bin/env python3
"""클라이언트 배포 꾸러미를 만든다 — 같은 트리에서 두 번 만들면 **같은 바이트**가 나온다.

왜 재현 가능해야 하는가
-----------------------
설치기는 이 꾸러미를 주소와 **sha256 한 줄**로 가리킨다(`AGORA_CLI_URL`·`AGORA_CLI_SHA`).
해시가 빌드마다 달라지면 「내가 만든 것과 게시된 것이 같은가」를 아무도 물을 수 없고,
그때 그 핀은 **무결성 검사가 아니라 장식**이 된다.

무엇을 고정했나(그리고 무엇을 못 고정했나)
-----------------------------------------
고정한 것 = 파일 목록·순서(정렬)·시각(1980-01-01)·권한 비트·압축 방식.
★같은 바이트가 나오는 **조건**을 정직하게 적는다(이종 검증 2026-09-09 로 좁혀졌다):
  ⑴ 빌드 도중 입력이 안 바뀐다 ⑵ 같은 파이썬·zlib ⑶ 산출물이 소스 트리 밖에 있다
  ⑷ 체크아웃의 줄바꿈이 같다.
⚠**못 고정한 것 = ⑵ 와 ⑷**다. 다른 zlib 판본이 같은 바이트를 내는지, 줄바꿈 설정이 다른
기계에서 같은 바이트가 되는지는 **재지 않았다**(⑷ 는 실제로 달라진다 — 그 트리는 바이트가
다른 트리이므로 「같은 트리」라는 전제가 이미 깨진 것이다).
그래서 이 도구가 내는 해시는 「이 기계에서 만든 그 꾸러미」의 이름이고, 그 이상을 뜻하지 않는다.
⑶ 은 이제 도구가 **거부해서** 지킨다(`_assert_output_is_outside`).
⇒ 게시하는 사람과 해시를 재는 사람이 **같은 산출물 파일**을 봐야 한다(다시 만들어 대조하지 마라).

담는 것
-------
`MANIFEST` 가 정본이다. 「돌아가는 데 필요한 것」을 손으로 적지 않고 목록 하나로 둔다 —
목록이 모자라면 `selftest` 의 꾸러미 케이스가 적색을 낸다(푼 자리에서 실제로 돌려 본다).

사용
----
    python3 tools/build_client_zip.py                 # dist/agora-client-<ver>.zip
    python3 tools/build_client_zip.py --out <경로>
    python3 tools/build_client_zip.py --print-sha     # 해시만
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ★꾸러미에 담기는 것의 정본. 「무엇이 필요한가」를 여기 한 곳에서만 정한다.
#   폴더는 그 아래 파일을 규칙(`suffixes`)으로 훑고, 파일은 그대로 담는다.
MANIFEST: tuple[dict[str, object], ...] = (
    # 실행기 두 개 — `bin/agora` 는 설치기가 만드는 껍데기가 가리키는 자리고,
    # `bin/agora-signer` 는 서명 전담 프로세스다(`sign.py` 가 절대경로로 부른다).
    {"path": "bin/agora", "kind": "file", "mode": 0o755},
    {"path": "bin/agora-signer", "kind": "file", "mode": 0o755},
    # 코어 패키지.
    {"path": "agora", "kind": "dir", "suffixes": (".py",), "mode": 0o644},
    # ★스크럽 규칙 3종 — **빠뜨리기 쉬운 자리다.** `scrub.py` 가 저장소 루트 상대경로로 읽고,
    #   스크럽은 쓰기 경로의 ⑵ 단계다. 없으면 발신이 통째로 막힌다(브리프 목록에는 없었다).
    {"path": "config/scrub-rules-v1.json", "kind": "file", "mode": 0o644},
    {"path": "config/allowlist-v1.json", "kind": "file", "mode": 0o644},
    {"path": "config/allow-domains.txt", "kind": "file", "mode": 0o644},
    # 설정 예시 — 사람이 무엇을 적는 자리인지 볼 수 있게 함께 둔다(실물은 설정 폴더에 있다).
    {"path": "config/config.json.example", "kind": "file", "mode": 0o644},
    {"path": "config/participant.json.example", "kind": "file", "mode": 0o644},
    {"path": "config/README.md", "kind": "file", "mode": 0o644},
    # 대리인 브리프 — 파송이 읽는 문서다.
    {"path": "skills/agora-delegate", "kind": "dir", "suffixes": (".md",), "mode": 0o644},
    # 명부 **빈 서식** 3종. ★실물 명부가 아니다 — 실물은 설치기가 릴레이에서 받아
    #   설정 폴더에 납작한 이름으로 둔다. 여기 담기는 것은 키가 한 줄도 없는 서식이고,
    #   그래서 이 꾸러미는 **낡은 명부를 실어 나르지 않는다**(아래 `_assert_roster_is_template`).
    {"path": "participants", "kind": "dir", "suffixes": ("",), "mode": 0o644},
    # 뿌리 안내문.
    {"path": "README.md", "kind": "file", "mode": 0o644},
)

# 1980-01-01 00:00:00 — zip 이 표현할 수 있는 가장 이른 시각. 파일 mtime 을 지운다.
FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def client_version() -> str:
    """판본은 **산출물 안**에서 읽는다 — 빌드 스크립트가 따로 적으면 두 값이 갈린다."""
    ns: dict[str, object] = {}
    with open(os.path.join(_ROOT, "agora", "__init__.py"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("__version__"):
                exec(line, ns)  # noqa: S102 — 한 줄, 우리 파일
                break
    v = ns.get("__version__")
    if not isinstance(v, str) or not v:
        raise SystemExit("agora/__init__.py 에서 __version__ 을 읽지 못했다")
    return v


def _assert_roster_is_template(root: str) -> None:
    """명부 서식에 **키 줄이 없는지** 본다.

    ★약속을 문서에 적는 대신 여기서 잰다. 언젠가 누가 실물 명부를 저장소에 커밋하면
      그날부터 이 꾸러미는 **낡은 명부를 배포하는 물건**이 된다 — 그리고 아무 오류도 안 난다.
    """
    bad = []
    for name in ("allowed_signers", "revoked_keys", "operators"):
        path = os.path.join(root, "participants", name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                s = line.strip()
                if s and not s.startswith("#"):
                    bad.append(f"participants/{name}:{i}")
    if bad:
        raise SystemExit(
            "명부 서식에 키 줄이 있다 — 꾸러미가 낡은 명부를 실어 나르게 된다: " + ", ".join(bad))


def collect(root: str | None = None) -> list[tuple[str, int]]:
    """담을 파일을 (저장소 상대경로, 권한) 으로 모은다. **정렬해서** 돌려준다."""
    root = root or _ROOT
    out: list[tuple[str, int]] = []
    for item in MANIFEST:
        rel = str(item["path"])
        mode = int(item["mode"])  # type: ignore[arg-type]
        full = os.path.join(root, rel)
        if item["kind"] == "file":
            if not os.path.exists(full):
                raise SystemExit(f"목록에 있는데 파일이 없다: {rel}")
            out.append((rel, mode))
            continue
        if not os.path.isdir(full):
            raise SystemExit(f"목록에 있는데 폴더가 없다: {rel}")
        suffixes = tuple(item["suffixes"])  # type: ignore[arg-type]
        for dirpath, dirnames, filenames in os.walk(full):
            # 캐시·숨김은 담지 않는다 — 담으면 기계마다 다른 바이트가 들어간다.
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__" and not d.startswith("."))
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                if suffixes != ("",) and not fn.endswith(suffixes):
                    continue
                out.append((os.path.relpath(os.path.join(dirpath, fn), root), mode))
    # 같은 파일이 두 항목에 걸리면 zip 안에 두 번 들어간다 — 이름으로 눌러 하나만 남긴다.
    dedup: dict[str, int] = {}
    for rel, mode in out:
        dedup[rel] = mode
    return sorted(dedup.items())


MANIFEST_NAME = "PACKAGE-MANIFEST.json"


def manifest_document(blobs: dict[str, bytes], version: str) -> dict[str, object]:
    """꾸러미 안에 함께 담는 **내용물 표** — 파일마다 sha256 한 줄.

    ★★해시는 **꾸러미에 실제로 담은 그 바이트**에서 낸다 — 파일을 다시 읽지 않는다.
      전에는 zip 을 쓴 뒤 트리를 **다시 순회해** 해시를 냈고, 그 사이 파일이 바뀌면
      표에는 새 해시가 들어가는데 꾸러미 안에는 옛 바이트가 들어갔다 ⇒ 갓 만든 꾸러미가
      그 자리에서 `selfcheck` 무결성 실패를 냈다(이종 검증 2026-09-09 지적 · HIGH).
      ★검증한 것과 봉인한 것이 다르면 검증은 통과하면서 다른 것이 남는다.

    ★`selfcheck` 의 무결성 축이 이 표를 읽어 실제 파일과 대조한다. 표가 없으면 그 축은
      「잰 것이 없다」가 되고, 그것을 통과로 세면 안 된다(그래서 `selfcheck` 는 미측정으로 낸다).
    ⚠**표 자신은 표에 없다**(자기 해시를 자기 안에 적을 수 없다). 그래서 이 표는
      「담긴 파일이 바뀌지 않았다」를 말하지, 「표가 바뀌지 않았다」는 말하지 못한다 —
      그 축은 꾸러미 **전체 sha256**(설치기 핀)이 진다. 두 겹이 서로 다른 것을 잰다.
    """
    return {
        "version": version,
        "files": {rel: hashlib.sha256(blob).hexdigest()
                  for rel, blob in sorted(blobs.items())},
        "note": ("이 표에 표 자신은 없다 — 표의 무결성은 꾸러미 전체 sha256(설치기 핀)이 진다."),
    }


def _assert_output_is_outside(root: str, out_path: str) -> None:
    """산출물이 **소스 안에** 놓이지 않게 한다(이종 검증 2026-09-09 지적 · HIGH).

    ★`--out participants/x.zip` 처럼 **수집되는 경로** 아래로 내면, 이번 빌드가 만든 파일(과 그
      `.tmp`)이 **다음 빌드의 입력**이 된다. 그러면 「같은 트리면 같은 바이트」가
      한 번 만드는 순간 거짓이 되고, 재현 가능성이 조용히 무너진다.
    ★막는 것은 「트리 안」이 아니라 **「수집되는 자리」**다. 트리 안이어도 목록이 훑지 않는
      곳(`dist/`)은 안전하고, 그것까지 막으면 기본 산출 경로가 자기 손에 막힌다
      (처음 쓴 판이 실제로 그랬다 — 규칙을 넓게 잡으면 정상 사용을 먼저 때린다).
    """
    targets = {os.path.realpath(os.path.abspath(out_path)),
               os.path.realpath(os.path.abspath(out_path + ".tmp"))}
    for item in MANIFEST:
        full = os.path.realpath(os.path.join(root, str(item["path"])))
        for t in targets:
            if item["kind"] == "dir":
                if t == full or t.startswith(full + os.sep):
                    raise SystemExit(
                        f"산출 경로가 수집 대상 안이다 — 다음 빌드의 입력이 된다: {out_path}\n"
                        f"  수집 대상: {item['path']}/ · 목록 밖(예: dist/)으로 지정하라.")
            elif t == full:
                raise SystemExit(
                    f"산출 경로가 담기는 파일과 같다: {out_path}")


def build(out_path: str, root: str | None = None) -> tuple[str, int, int]:
    """꾸러미를 만들고 (sha256, 바이트, 파일 수) 를 돌려준다."""
    root = root or _ROOT
    _assert_roster_is_template(root)
    version = client_version()
    files = collect(root)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    # 임시 이름으로 만들고 마지막에 옮긴다 — 중간에 죽으면 반쪽 꾸러미가 남고,
    # 그 반쪽이 게시되면 sha 는 맞는데 내용이 모자란 물건이 된다.
    tmp = out_path + ".tmp"
    blobs: dict[str, bytes] = {}
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, mode in files:
            with open(os.path.join(root, rel), "rb") as fh:
                data = fh.read()
            # ★담은 바이트를 그대로 들고 있는다 — 표는 이 바이트에서 만든다(다시 읽지 않는다).
            blobs[rel] = data
            info = zipfile.ZipInfo(rel, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            # create_system 을 고정한다 — 기본값은 만든 운영체제를 적어 넣는다.
            info.create_system = 3  # unix
            info.external_attr = (mode & 0o7777) << 16
            zf.writestr(info, data)
        # 내용물 표를 마지막에 넣는다. 정렬·개행까지 고정해야 두 번 만든 것이 같은 바이트가 된다.
        doc = json.dumps(manifest_document(blobs, version), ensure_ascii=False,
                         sort_keys=True, indent=2) + "\n"
        info = zipfile.ZipInfo(MANIFEST_NAME, date_time=FIXED_DATE)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (0o644 & 0o7777) << 16
        zf.writestr(info, doc.encode("utf-8"))
    os.replace(tmp, out_path)
    with open(out_path, "rb") as fh:
        blob = fh.read()
    return hashlib.sha256(blob).hexdigest(), len(blob), len(files) + 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="아고라 클라이언트 배포 꾸러미 빌더")
    ap.add_argument("--out", default=None, help="산출 경로(기본 dist/agora-client-<ver>.zip)")
    ap.add_argument("--print-sha", action="store_true", help="해시만 한 줄로 낸다")
    args = ap.parse_args(argv)

    ver = client_version()
    out = args.out or os.path.join(_ROOT, "dist", f"agora-client-{ver}.zip")
    _assert_output_is_outside(_ROOT, out)
    sha, size, count = build(out)
    if args.print_sha:
        print(sha)
        return 0
    print(f"판본   : {ver}")
    print(f"산출   : {out}")
    print(f"파일   : {count}개")
    print(f"크기   : {size} 바이트")
    print(f"sha256 : {sha}")
    print()
    print("설치기 핀에 넣을 두 줄:")
    print(f'  AGORA_CLI_URL="https://<설치 사이트>/install/agora-client-{ver}.zip"')
    print(f'  AGORA_CLI_SHA="{sha}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
