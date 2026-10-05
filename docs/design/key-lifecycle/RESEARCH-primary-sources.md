# 서명 키 수명주기 설계를 위한 1차 출처 조사 (SSHSIG · allowed_signers · 키 상태 · 선례)

- 조사일(retrieval date): **2026-09-29**
- 범위: OpenSSH SSHSIG(`ssh-keygen -Y`, ed25519) + allowed_signers, macOS/Windows 기본 탑재 OpenSSH 버전, NIST SP 800-57, RFC 5280/3161, 키 회전·투명성 선례(Keybase·Matrix·Sigstore·Git/GitHub·TUF), SSH 인증서·KRL
- 표기 규칙: 모든 주장에 1차 출처 URL + 짧은 원문 인용. 확인하지 못한 것은 **【미확인】**, 출처 없이 논리로 이끈 것은 **【추론】**, 이 기계에서 직접 실행한 것은 **【실측】**(macOS 26.6.2, build 25G83, `/usr/bin/ssh-keygen` = `OpenSSH_10.3p1, LibreSSL 3.3.6`).

---

## 0. 설계에 직결되는 핵심 발견 (요약)

| # | 발견 | 근거 절 |
|---|---|---|
| 1 | **SSHSIG 서명 자체에는 서명 시각 필드가 없다.** 서명 blob·서명 대상 데이터 어디에도 timestamp가 없다. 그래서 `valid-after/valid-before` 판정에 쓰는 "시각"은 언제나 서명 **밖에서** 가져와야 한다(기본값은 검증하는 순간의 현재 시각). | §1.1, §1.4 |
| 2 | `ssh-keygen -Y verify`는 `-Overify-time=` 을 주지 않으면 **검증 시점의 현재 시각(`time(NULL)`)** 으로 판정한다. 따라서 `valid-before`가 지난 키로 만든 **과거 서명도 오늘 검증하면 실패한다.** | §1.3, 실측 §1.6 |
| 3 | `-r revocation_file`(KRL/폐기 키 목록)은 **시각과 무관**하다. 폐기 목록에 있는 키의 서명은 과거 서명까지 **전부** 실패한다. 반면 `valid-before`는 **시각 범위만** 끊는다. ⇒ "정상 회전(과거 서명 보존)"과 "유출(전부 불신)"을 서로 다른 도구로 표현할 수 있다. | §6, 실측 §1.6 |
| 4 | 버전 하한: `valid-after/valid-before`와 `verify-time`은 **OpenSSH 8.7**에서 도입됐다(git 문서의 "8.8"은 부정확 — git 커밋 메시지 자체가 "Strictly speaking … available in 8.7"이라고 적음). `find-principals`가 일반 키 수명을 검사하는 것은 **8.9**부터. 시각 뒤 `Z`(UTC) 접미사는 **9.1**부터. | §1.2 |
| 5 | macOS 14.0 = OpenSSH 9.3p2 · 14.4 = 9.6p1 · 15.0 = 9.8p1 · 15.4 = 9.9p1 · 15.5~15.6 = 9.9p2 · 26.0~26.2 = 10.0p2 · 26.3~26.5 = 10.2p1(Apple OSS 배포 태그 기준) · 이 기계 26.6.2 = **10.3p1**(실측). ⇒ **macOS 14 이상은 모두 요구 기능 충족.** | §2.1 |
| 6 | Windows 기본 탑재(inbox) OpenSSH는 Microsoft 문서가 "7.7p1 or 8.1p1" 같은 구버전이라고 명시한다. Windows 10 22H2 사용자 보고 = `OpenSSH_for_Windows_8.1p1`. **8.1은 `valid-after` 등이 있는 allowed_signers 줄을 "unknown key option"으로 거부**하고 `-O verify-time`도 없다(소스 확인). Windows 11 24H2 사용자 보고 = `OpenSSH_for_Windows_9.5p1`(요구 기능 충족). ⇒ **참가자 기기마다 `ssh -V` 실측 게이트가 필요하다.** | §2.2 |
| 7 | NIST SP 800-57: 서명 개인키의 사용기간(originator-usage)과 공개키의 검증기간(recipient-usage)을 분리한다. 비활성화(deactivated) 공개키로도 "사용기간 끝 이전에 만든 서명"은 검증할 수 있다. 유출(compromised)된 경우에는 "유출 이전부터 물리적으로 보호됐거나 **신뢰할 수 있는 타임스탬프**가 있는" 서명만, 그것도 엄격히 통제된 조건에서만 검증한다. | §3 |
| 8 | 선례의 공통분모: **"과거 서명의 유효성은 서명자가 주장하는 시각이 아니라, 서명자가 조작할 수 없는 순서·시각 기록에 비추어 판정한다."** Keybase(sigchain 순서 + 공개 Merkle 트리), Sigstore(Rekor 편입 시각 또는 RFC 3161 TSA), GitHub(push 시점 검증 기록 영구 보존), RFC 3161 부록 B. Git의 `verify-time`은 **커밋 안의 committer/tagger 날짜**(서명자가 적는 값)를 쓴다. | §4, §5 |
| 9 | Sigstore 문서는 자기네 Rekor v1 타임스탬프에 대해서도 "Rekor 내부 시계에서 오며 **외부에서 검증할 수 없고**, append-only 구조에 포함되지 않아 **탐지 없이 바뀔 수 있다**"고 직접 경고한다. ⇒ 릴레이 서버가 수신 시각을 찍는 방식도 같은 한계가 있다. | §5(c) |

---

## 1. OpenSSH allowed_signers `valid-after`/`valid-before` 와 `-Overify-time`

### 1.1 문법 (ssh-keygen(1) ALLOWED SIGNERS)

출처: https://man.openbsd.org/ssh-keygen.1 (및 로컬 `man ssh-keygen`, OpenSSH_10.3p1) 【실측: 로컬 man 페이지에서 같은 문구 확인】

| 항목 | 원문 인용 |
|---|---|
| 줄 형식 | "Each line of the file contains the following space-separated fields: principals, options, keytype, base64-encoded key." |
| 옵션 구분 | "The options (if present) consist of comma-separated option specifications. No spaces are permitted, except within double quotes." · "(note that option keywords are case-insensitive)" |
| `valid-after` | "Indicates that the key is valid for use at or after the specified timestamp, which may be a date or time in the YYYYMMDD[Z] or YYYYMMDDHHMM[SS][Z] formats. Dates and times will be interpreted in the current system time zone unless suffixed with a Z character, which causes them to be interpreted in the UTC time zone." |
| `valid-before` | "Indicates that the key is valid for use at or before the specified timestamp." |
| `namespaces` | "Specifies a pattern-list of namespaces that are accepted for this key. If this option is present, the signature namespace embedded in the signature object and presented on the verification command-line must match the specified list before the key will be considered acceptable." |
| `cert-authority` | "Indicates that this key is accepted as a certificate authority (CA) and that certificates signed by this CA may be accepted for verification." |

예시(설계용):
```
alice@agora namespaces="agora-event@example",valid-after="20260101Z",valid-before="20260601Z" ssh-ed25519 AAAA...
```

경계값 의미(소스 확인): `sshsig.c`는 `verify_time < valid_after` 이면 "key is not yet valid", `verify_time > valid_before` 이면 "key has expired"로 실패한다 ⇒ **양 끝 모두 포함(inclusive)**. 또 `valid_before <= valid_after`이면 그 줄 자체가 파싱 오류다.
- 출처: https://github.com/openssh/openssh-portable/blob/V_10_3_P1/sshsig.c — 원문: `if (sigopts->valid_after != 0 && (uint64_t)verify_time < sigopts->valid_after) { … "key is not yet valid: " …` / `if (sigopts->valid_before != 0 && (uint64_t)verify_time > sigopts->valid_before) { … "key has expired: " …`
- 같은 파일: `if (ret->valid_after != 0 && ret->valid_before != 0 && ret->valid_before <= ret->valid_after)` (Win32 포트 9.5 동일 조건의 오류 문구: `"\"valid-before\" time is before \"valid-after\""` — https://github.com/PowerShell/openssh-portable/blob/v9.5.0.0/sshsig.c)

### 1.2 도입 버전 (OpenSSH 릴리스 노트)

출처: https://www.openssh.com/releasenotes.html

| 버전(릴리스일) | 변경 | 원문 인용 |
|---|---|---|
| **8.1** (2019-10-09) | `-Y sign/verify` 최초 도입(실험적) | "ssh-keygen(1): add an experimental lightweight signature and verification ability. Signatures may be made using regular ssh keys held on disk or stored in a ssh-agent and verified against an authorized_keys-like list of allowed keys." |
| **8.2** (2020-02-14) | `find-principals` 추가 | "ssh-keygen(1): add a new signature operations \"find-principals\" to look up the principal associated with a signature from an allowed-signers file." |
| **8.7** (2021-08-20) | **`valid-after/valid-before` + 검증 시각 지정** | "ssh-keygen(1): allowed signers files used by ssh-keygen(1) signatures now support listing key validity intervals alongside they key, and ssh-keygen(1) can optionally check during signature verification whether a specified time falls inside this interval. This feature is intended for use by git to support signing and verifying objects using ssh keys." |
| **8.9** (2022-02-23) | find-principals 수명 검사 버그 수정, verify-time 파싱 | "ssh-keygen(1): the \"-Y find-principals\" command was verifying key validity when using ca certs but not with simple key lifetimes within the allowed signers file." · "ssh-keygen(1): make sshsig verify-time argument parsing optional" · "add \"ssh-keygen -Y match-principals\" operation" |
| **9.1** (2022-10-04) | **UTC `Z` 접미사** | "ssh-keygen(1), sshd(8): allow certificate validity intervals, sshsig verification times and authorized_keys expiry-time options to accept dates in the UTC time zone in addition to the default of interpreting them in the system time zone. YYYYMMDD and YYMMDDHHMM[SS] dates/times will be interpreted as UTC if suffixed with a 'Z' character." |
| 9.5 (2023-10-04) | CRLF 처리 | "ssh-keygen(1): handle cr+lf (instead of just cr) line endings in sshsig signature files." |

소스로 교차확인(8.7 도입): `V_8_6_P1`의 ssh-keygen.c/sshsig.c에는 `verify-time`·`valid-before` 문자열이 **0건**, `V_8_7_P1`에는 존재. V_8_7_P1 man: ".It Cm verify-time Ns = Ns Ar timestamp / Specifies a time to use when validating signatures instead of the current time." — https://github.com/openssh/openssh-portable/blob/V_8_7_P1/ssh-keygen.1

⚠ 출처 간 불일치: git 문서는 "Since OpensSSH 8.8 this file allows specifying a key lifetime using valid-after & valid-before options."(https://git-scm.com/docs/git-config)라고 적지만, 해당 git 커밋 메시지는 "Strictly speaking this feature is available in 8.7, but since 8.7 has a bug that makes it unusable in another needed call we require 8.8."라고 설명한다(https://github.com/git/git/commit/6393c956f4e7061d6b19981bd8cd28ef037b911e). ⇒ **기능 도입 = 8.7, git이 요구하는 하한 = 8.8, find-principals 수명 검사 완전 = 8.9.**

### 1.3 `-Y verify`는 어떤 시각으로 판정하나

- man(`-O` 옵션, `-Y` 서명 연산용): "verify-time=timestamp — Specifies a time to use when validating signatures instead of the current time. The time may be specified as a date or time in the YYYYMMDD[Z] or in YYYYMMDDHHMM[SS][Z] formats." — https://man.openbsd.org/ssh-keygen.1
- 소스(기본값 = 현재 시각): `sig_process_opts()`가 옵션이 없으면 `time(NULL)`을 넣는다 — https://github.com/openssh/openssh-portable/blob/V_10_3_P1/ssh-keygen.c
  원문: `if (verify_timep && *verify_timep == 0) { if ((now = time(NULL)) < 0) { … } *verify_timep = (uint64_t)now; }`
- ⇒ **`-Overify-time` 미지정 = 검증하는 기계의 현재 시계.** 검증자 시계가 틀리면 판정도 틀린다 【추론】.

### 1.4 SSHSIG 형식에는 시각이 없다

출처: https://github.com/openssh/openssh-portable/blob/V_10_3_P1/PROTOCOL.sshsig
- Blob: `byte[6] MAGIC_PREAMBLE / uint32 SIG_VERSION / string publickey / string namespace / string reserved / string hash_algorithm / string signature`
- 서명 대상: `byte[6] MAGIC_PREAMBLE / string namespace / string reserved / string hash_algorithm / string H(message)`
- reserved: "The reserved value is present to encode future information (e.g. tags) into the signature. Implementations should ignore the reserved field if it is not empty."
- ⇒ 서명 시각은 SSHSIG가 증명하지 않는다. 이벤트 본문 안에 서명자가 적은 시각은 **서명자가 임의로 쓸 수 있는 값**이다 【추론 — 형식 정의에서 직접 도출】.

### 1.5 `-Y find-principals` / `check-novalidate` / `match-principals` 와 유효기간

| 연산 | 유효기간 검사 | 근거 |
|---|---|---|
| `-Y verify` | **검사함**(verify_time 기준) + `-r` 폐기 검사 | 소스: `sig_verify()` → `sshkey_check_revoked()` 후 `sshsig_check_allowed_keys(…, verify_time)` (V_10_3_P1 ssh-keygen.c) |
| `-Y find-principals` | **검사함**(8.9부터 일반 키도). `-O verify-time` 수용. `-r` 인자는 없음 | man 개요: "ssh-keygen -Y find-principals [-O option] -s signature_file -f allowed_signers_file". 소스: `sshsig_find_principals(allowed_keys, sign_key, verify_time, &principals)`. 8.9 노트(위) |
| `-Y check-novalidate` | **검사 안 함**(서명 구조·암호학적 검증만, allowed_signers·폐기 미사용) | man: "Checks that a signature generated using ssh-keygen -Y sign has a valid structure. This does not validate if a signature comes from an authorized signer." 소스: `sig_verify(ca_key_path, cert_principals, NULL, NULL, NULL, opts, nopts)` (allowed/revoked 모두 NULL) |
| `-Y match-principals` | 시각 무관(이름 패턴 매칭만) | 소스: `sig_process_opts(opts, nopts, NULL, NULL, NULL)` — verify_time 포인터 자체를 안 넘김 |

### 1.6 실측 (이 기계, `/usr/bin/ssh-keygen` OpenSSH_10.3p1, 2026-09-29 KST)

allowed_signers: `alice valid-after="20260101Z",valid-before="20260601Z" ssh-ed25519 …`

| 명령 | 결과 |
|---|---|
| `-Y verify` (옵션 없음 = 현재 2026-09-29) | `key has expired: verify time 2026-09-29T15:27:27 > valid-before 2026-06-01T09:00:00` / rc=255 |
| `-Y verify -Overify-time=20260301Z` | `Good "test@x" signature for alice …` / rc=0 |
| `-Y verify -Overify-time=20250101Z` | `key is not yet valid: verify time 2025-01-01T09:00:00 < valid-after 2026-01-01T09:00:00` / rc=255 |
| `-Y find-principals` (현재) | `key has expired …` `No principal matched.` / rc=255 |
| `-Y find-principals -Overify-time=20260301Z` | `alice` / rc=0 |
| `-Y check-novalidate` | `Good "test@x" signature with ED25519 key …` / rc=0 (기간 무시) |
| `-Y verify -r <그 공개키>` (기간 옵션 없는 줄) | `Could not verify signature.` / rc=255 (폐기 사유 문구는 debug 레벨에만) |

(출력의 시각 표시는 로컬 시간대 KST=UTC+9로 찍힌다: `20260601Z` → `2026-06-01T09:00:00`.)

---

## 2. 참가자 OS별 OpenSSH 버전

### 2.1 macOS

**방법**: Apple 오픈소스 배포 저장소(`apple-oss-distributions/distribution-macOS`)의 macOS 릴리스 태그 → `OpenSSH` 서브모듈 커밋 → `apple-oss-distributions/OpenSSH` 태그 → 그 태그의 `openssh/version.h`.
- https://github.com/apple-oss-distributions/distribution-macOS (태그 `macos-140` … `macos-265`)
- https://github.com/apple-oss-distributions/OpenSSH (예: https://github.com/apple-oss-distributions/OpenSSH/blob/OpenSSH-354.120.2/openssh/version.h — 원문 `#define SSH_VERSION "OpenSSH_10.2"` / `#define SSH_PORTABLE "p1"`)

| macOS | Apple OpenSSH 태그 | version.h |
|---|---|---|
| 14.0 Sonoma (`macos-140`) | OpenSSH-319 | OpenSSH_9.3 p2 |
| 14.4 (`macos-144`) | OpenSSH-328.100.5 | OpenSSH_9.6 p1 |
| 14.6 (`macos-146`) | OpenSSH-328.141.1 | OpenSSH_9.7 p1 |
| 15.0 / 15.1 Sequoia | OpenSSH-341 | OpenSSH_9.8 p1 |
| 15.3 | OpenSSH-342 | OpenSSH_9.8 p1 |
| 15.4 | OpenSSH-346 | OpenSSH_9.9 p1 |
| 15.5 / 15.6 | OpenSSH-346.120.3 | OpenSSH_9.9 p2 |
| 26.0 / 26.1 / 26.2 Tahoe | OpenSSH-354.0.3 | OpenSSH_10.0 p2 |
| 26.3 | OpenSSH-354.80.3 | OpenSSH_10.2 p1 |
| 26.4 | OpenSSH-354.100.6 | OpenSSH_10.2 p1 |
| 26.5 | OpenSSH-354.120.2 | OpenSSH_10.2 p1 |
| 26.6.2 (이 기계) | (배포 태그 미공개) | **【실측】 `OpenSSH_10.3p1, LibreSSL 3.3.6`** |

- 교차 확인(Apple 보안 노트): macOS Sonoma 14.4 — "Multiple issues were addressed by updating to OpenSSH 9.6." (https://support.apple.com/en-us/120895) → 위 표의 14.4 = 9.6p1과 일치.
- Sequoia 15.5 / Sonoma 14.7.6 보안 노트: OpenSSH 항목 "CVE-2025-26465 CVE-2025-26466" (https://support.apple.com/en-us/122716 , https://support.apple.com/en-us/122717) — 버전 번호는 명시 없음.
- **【미확인】** Sonoma 14.7.x~14.8.x, Sequoia 15.7.x의 정확한 OpenSSH 버전(배포 태그가 `macos-146`, `macos-156`까지만 존재). 다만 모두 14.0의 9.3p2 이상이므로 ≥9.1 요건은 충족한다 【추론 — 보안 업데이트로 버전이 내려갈 이유 없음, 단 미확인】.
- ⇒ macOS 14+는 `valid-after/before`(≥8.7), find-principals 수명검사(≥8.9), `Z`(≥9.1) 모두 충족.

### 2.2 Windows (내장 OpenSSH = Win32-OpenSSH 포트)

| 항목 | 근거(원문) |
|---|---|
| 내장 버전은 구버전으로 지체 | Microsoft Learn: "the built-in (in-box) version that ships as part of the Windows and Windows Server installation media, such as 7.7p1 or 8.1p1, often lags behind the latest Win32-OpenSSH releases that are available on GitHub." · "The in-box version is Microsoft-supported and stable, but it updates only when Windows itself updates." (ms.date 2026-02-12) — https://learn.microsoft.com/en-us/troubleshoot/windows-server/system-management-components/upgrade-in-box-openssh-to-latest-openssh-release |
| 기본 설치 상태 | "Windows 10 build 1809 + — Not installed, install and enable using optional features" · "Windows Server 2025 — Installed but not enabled" — https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-overview |
| Windows 10 22H2 = 8.1p1 (사용자 보고 + MS 유지보수자 답변) | 사용자: "OpenSSH_for_Windows_8.1p1, LibreSSL 3.0.2"(2024-01-18). maertendMSFT(2024-01-22): "only the latest version of Windows Client and Windows Server receive the latest Win32-OpenSSH versions. Given you are using Windows 10, under our normal process you would not receive another update." — https://github.com/PowerShell/Win32-OpenSSH/discussions/2194 |
| Windows 11 24H2 = 9.5p1 (사용자 보고) | "Windows 11 24H2 build 26100.1742" / "OpenSSH_for_Windows_9.5p1, LibreSSL 3.8.2" (2024-10-08) — https://github.com/PowerShell/Win32-OpenSSH/issues/2279 |
| Windows 11 25H2 = 9.5p2 (사용자 보고) | "Windows 11 25H2, build 26200.9457" / "OpenSSH_9.5p2 for Windows" (file version 9.5.6.2, 2026-09-18) — https://github.com/PowerShell/Win32-OpenSSH/issues/2460 |
| MS 문서의 9.5 언급 | "After you install a Windows update for OpenSSH Version 9.5.2.1, the OpenSSH Server service doesn't start. This problem typically involves updates that were released between October 8, 2024, and March 11, 2025" (나열된 KB에 24H2/Server 2025, 11 22H2·23H2·21H2, Server 2022/2019, **Windows 10 22H2(KB5044273)** 포함) — https://learn.microsoft.com/en-us/troubleshoot/windows-server/system-management-components/error-1053-1067-7034-after-update-openssh-doesnt-start |

- **【미확인】** Microsoft 공식 문서에서 "Windows 11 24H2 = OpenSSH 9.5p1"을 버전표로 명시한 문장은 찾지 못했다(위는 사용자 보고 + 9.5 관련 장애 문서). 2024-10 누적 업데이트(CVE-2024-43581) 이후 Windows 10 22H2 / Windows 11 22H2·23H2의 내장 버전이 9.5로 올라갔는지도 **【미확인】**(장애 문서는 "might relate"라고만 적음).
- Windows 11 22H2/23H2 내장 = 8.6p1이라는 서술은 사용자 게시글 수준에서만 보임 — **【미확인】** (https://techcommunity.microsoft.com/discussions/windows-servicing/update-schedule-for-windows-openssh/4145020 는 8.6p1이 오래됐다는 질문만 있고 공식 답 없음).

**Win32 포트의 `-Y` 지원(소스 확인)**
- v9.5.0.0 (`#define SSH_VERSION "OpenSSH_for_Windows_9.5"`): ssh-keygen.c에 `find-principals`/`sign`/`check-novalidate`/`verify` 분기와 `"verify-time="` 파싱 존재, sshsig.c에 `valid-after`/`valid-before` 존재, man에 `YYYYMMDD[Z]` 명시, misc.c `parse_absolute_time`에 `is_utc` 처리 존재 — https://github.com/PowerShell/openssh-portable/tree/v9.5.0.0 ⇒ **9.5 내장이면 요구 기능 모두 지원.**
- v8.1.0.0 (`OpenSSH_for_Windows_8.1`): `sign`/`check-novalidate`/`verify`만 있고 **`find-principals`·`verify-time` 없음**. allowed_signers 옵션 파서는 `cert-authority`·`namespaces`만 알고, 그 밖의 옵션은 `errstr = "unknown key option"` → `error("%s:%lu: bad options: %s", …)` 로 **그 줄을 버린다** — https://github.com/PowerShell/openssh-portable/blob/v8.1.0.0/sshsig.c
  ⇒ **Windows 10 내장 8.1p1에 `valid-after=`가 들어간 allowed_signers를 주면 그 서명자의 검증이 실패한다** 【소스에서 도출; Windows 실기 실측 아님】.

**Windows `-Y` 알려진 이슈**
- #2300 (open, 2024-11-12, `OpenSSH_for_Windows_9.5p1`, PowerShell 5.1): `type test.txt|ssh-keygen -Y verify …` → "Signature verification failed: incorrect signature" — https://github.com/PowerShell/Win32-OpenSSH/issues/2300 (댓글 0건, 원인 미규명)
  - 관련 사실: "The automatic variable `$OutputEncoding` affects the encoding PowerShell uses to communicate with external programs." — https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_character_encoding?view=powershell-5.1
  - 원인이 PowerShell 파이프라인의 텍스트 재인코딩(바이트가 바뀜)일 가능성 **【추론·미확인】**. ⇒ 설계 권고: 메시지를 stdin 파이프로 넘기지 말고 **바이트 그대로 파일에 쓰고 cmd `<` 리다이렉트나 프로세스 API로 바이트 전달** 【추론】.
- 저장소 이슈 검색(`allowed_signers`, `find-principals`, `sshsig`, `verify-time`, `allowedSignersFile`)에서 다른 `-Y` 관련 이슈는 찾지 못함(2026-09-29 GitHub search API).

---

## 3. NIST SP 800-57 Part 1 Rev. 5 (2020)

출처 PDF: https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-57pt1r5.pdf (doi 10.6028/NIST.SP.800-57pt1r5)

### 3.1 키 상태 (§7 Key States and Transitions)

| 상태 | 절 | 핵심 원문 |
|---|---|---|
| Pre-activation | §7.1 | "The key has been generated but has not been authorized for use." · "A key enters the pre-activation state immediately upon generation." |
| Active | §7.2 | "In the active state, the key may be used to cryptographically protect information … cryptographically process previously protected information … or both." · "asymmetric private signature keys … are implicitly designated for only applying protection; public signature-verification keys … are designated for processing only." |
| Suspended | §7.3 | "One reason for a suspension might be a possible key compromise; in this case, the suspension might be issued to allow for time to investigate the situation." · "signatures purportedly signed during the suspension time would be invalid." · "If the reason for the suspension is a suspected compromise, it may not be prudent to verify any signatures using the public key until and unless the key pair is subsequently reactivated" · "Information for which protection is known to have been applied during the suspension period shall not be processed." |
| Deactivated | §7.4 | "Keys in the deactivated state shall not be used to apply cryptographic protection but, in some cases, may be used to process cryptographically protected information." · "Public signature verification keys may be used to verify the digital signatures that were generated before the end of the corresponding private key's originator-usage period" |
| Compromised | §7.5 | "A compromised key shall not be used to apply cryptographic protection to information." · "a signature may be verified to determine the integrity of signed data if its signature has been physically protected since a time before the compromise occurred or a reliable timestamp has been included in the signed data. This processing shall be done only under highly controlled conditions where the users of the information are fully aware of the possible consequences." · "Whether or not the public keys are destroyed, the metadata should be retained for audit purposes" |
| Destroyed | §7.6 | "Even though the key no longer exists when in this state, certain metadata (e.g., key state transition history, key name, type, and cryptoperiod) may be retained for audit purposes" · "It is possible that a compromise of the destroyed key could be determined after the key has been destroyed. In this case, the event shall be recorded" |

### 3.2 Cryptoperiod 와 사용기간 분리

- §5.3: "A cryptoperiod is the time span during which a specific key is authorized for use by legitimate entities or the keys for a given system will remain in effect." · "If a key is compromised, its cryptoperiod shall no longer be considered valid."
- §5.3.4 (originator vs recipient): "One key of the key pair is used to apply cryptographic protection (e.g., create a digital signature), and its cryptoperiod is called the "originator-usage period." The other key of the key pair is used to process the protected information (e.g., verify a digital signature); its cryptoperiod is called the "recipient-usage period."" · "the recipient-usage period may extend beyond the originator-usage period." · (서명키) "the private key is intended for use for a fixed period of time, after which the key owner shall destroy the private key. The public key may be available for a longer period for verifying signatures."
- §5.3.6 권고치: 서명 개인키 "a maximum cryptoperiod of about one to three years is recommended. A private signature key shall be destroyed at the end of its cryptoperiod." · 검증 공개키 "The cryptoperiod may be on the order of several years."
- §5.3.6 타임스탬프: "Some systems use a cryptographic timestamping function to place an unforgeable timestamp on each signed message. Even when the cryptoperiod of a private signature key has expired, the corresponding public signature-verification key may be used to verify signatures on messages whose timestamps are within the cryptoperiod of the private signature key. In this case, one is relying on the cryptographic timestamp function to provide assurance that the message was signed within the private signature key's originator-usage period."

### 3.3 유출 처리 (§5.5, §8.3.5)

- §5.5: "When a key is compromised, all use of the key to apply cryptographic protection to information (e.g., compute a digital signature or encrypt information) shall cease, and the compromised key shall be revoked" · "The continued use of a compromised key shall be limited to processing information that has already been protected. In this case, the entity that uses the information must be made fully aware of the dangers involved."
- §5.5.1 (유출 이전 서명): "The unauthorized disclosure of a private signature key means that the integrity and non-repudiation qualities of all data signed by that key are suspect." · "In cases where it can be shown that the signed data was protected by other mechanisms (e.g., physical security) from a time before the compromise, the signature may still have some value. For example, if a signed message was received on day 1 and it was later determined that the private signing key was compromised on day 15, the receiver may still have confidence that the message is valid because it was maintained in the receiver's possession before day 15. Note that cryptographic timestamping may also provide protection for messages signed before the private signature key was compromised."
- §8.3.5 Key Revocation: "Key revocation is used in cases where 1) the authorized use of a key needs to be terminated prior to the end of the established cryptoperiod of that key, or 2) a key whose usage period has expired has been compromised." · "a cryptographic key should be revoked as soon as feasible after the need for revocation has been determined." · "Entities that have been, are, or would be using the key (e.g., relying parties) need to be notified that the key has been revoked."

⇒ 설계 대응 【추론】: 정상 회전 = Deactivated(과거 서명 검증 허용, "originator-usage 종료 이전" 서명만). 유출 = Compromised(원칙적으로 전부 의심; **수신자가 유출 이전부터 보관한 증거**—예: 릴레이가 이미 받아 둔 기록—가 있을 때만 제한적으로 가치 인정). day1/day15 예시가 "릴레이 수신 기록"과 정확히 같은 구조다.

---

## 4. RFC 5280 invalidityDate / RFC 3161 타임스탬프

### 4.1 RFC 5280 §5.3.2 Invalidity Date — https://www.rfc-editor.org/rfc/rfc5280#section-5.3.2
- "The invalidity date is a non-critical CRL entry extension that provides the date on which it is known or suspected that the private key was compromised or that the certificate otherwise became invalid. This date may be earlier than the revocation date in the CRL entry, which is the date at which the CA processed the revocation."
- "The GeneralizedTime values included in this field MUST be expressed in Greenwich Mean Time (Zulu)"
- ⇒ **폐기 처리 시각(revocationDate)과 실제 무효 시작 시각(invalidityDate)은 다른 값**이며 후자가 더 이를 수 있다. allowed_signers에서 유출 키의 `valid-before`를 "폐기를 처리한 지금"이 아니라 "유출 추정 시각"으로 소급해 적는 것에 해당한다 【추론】.

### 4.2 RFC 3161 — https://www.rfc-editor.org/rfc/rfc3161
- §1: "A time-stamping service supports assertions of proof that a datum existed before a particular time." · "An example of how to prove that a digital signature was generated during the validity period of a public key certificate is given in an annex."
- Appendix A: "One of the major uses of time-stamping is to time-stamp a digital signature to prove that the digital signature was created before a given time. Should the corresponding public key certificate be revoked this allows a verifier to know whether the signature was created before or after the revocation date."
- Appendix B (절차): "Time-stamping information needs to be obtained soon after the signature has been produced (e.g., within a few minutes or hours)." · "The date/time indicated by the TSA MUST be within the validity period of the signer's certificate." · "Should the certificate be revoked, then the date/time of revocation shall be later than the date/time indicated by the TSA." · "If all these conditions are successful, then the digital signature shall be declared as valid."
- ETSI CAdES/LTV 문서는 이번에 직접 조회하지 않음 — **【미확인】**(원리는 RFC 3161 부록 B로 충분히 인용됨).

---

## 5. 키 회전·투명성 선례

### (a) Keybase sigchain — https://book.keybase.io/docs/server
| 주제 | 원문 |
|---|---|
| 체인 구조 | "Every sigchain link is signed by one of the user's keys and includes a sequence number and the hash of the previous link. Because of this, the server can't create links on its own or omit links without invalidating the whole sigchain." |
| 롤백 방지 | "We use a public Merkle tree to make it difficult for us to roll back a sigchain to an earlier state without being noticed." |
| 기기 키 추가 | "You add and remove sibkeys by adding links to your sigchain." · sibkey 링크: "reverse_sig is a signature of the link by the new sibkey itself, made with the reverse_sig field set to null , and makes sure that a user can't claim another user's key as their own." |
| **폐기 후 과거 서명** | "Since every link is checked against the state of the account at that point in the sigchain , old links remain valid even if their signing keys are revoked later." · revoke 링크: "Remove the keys in kids from your account. Any previous links they've signed are still valid, but they can no longer sign new links" |
| 상태 재생 | "the client … plays back the sigchain link by link, keeping track of valid sibkeys and the effects of other links." |

⇒ 시각이 아니라 **체인 내 순서(seqno)** 로 "그 시점의 키 상태"를 판정한다. 유출 키가 과거 seqno로 끼워 넣는 것은 해시 체인+공개 Merkle 루트가 막는다.

### (b) Matrix cross-signing — https://spec.matrix.org/latest/client-server-api/ (v1.19)
- "the cross-signing feature allows users to sign their device keys such that Alice and Bob only need to verify once."
- "A user's user-signing and self-signing keys are intended to be easily replaceable if they are compromised by re-issuing a new key signed by the user's master signing key and possibly by re-verifying devices or users."
- "If a user's client sees that any other user has changed their master key, that client must notify the user about the change before allowing communication between the users to continue."
- 기기 삭제: `/logout` "The device associated with the access token is also deleted. Device keys for the device are deleted alongside the device."
- **【미확인】** 스펙 본문에서 "기기 키 폐기/삭제 후 **과거 메시지의 진위 표시**를 어떻게 재평가하는가"를 규정한 문장은 찾지 못했다(검색어: revoke, deleted, historical, previously verified, compromised). 과거 메시지 경고 표시는 클라이언트(Element 등) 구현 사항으로 보이나 이번에 확인하지 않음.

### (c) Sigstore (Fulcio + Rekor)
| 주제 | 원문 · 출처 |
|---|---|
| 단수명 인증서 | "Based on an OpenID Connect email address, Fulcio signs X.509 certificates valid for 10 minutes." — https://docs.sigstore.dev/certificate_authority/overview/ |
| 개인키 폐기 | "For security, the private key is destroyed shortly after and the short-lived identity certificate expires. Users who wish to verify the software will use the transparency log entry, rather than relying on the signer to safely store and manage the private key." — https://docs.sigstore.dev/cosign/signing/overview/ |
| **검증 시각 = 벽시계가 아님** | "Time is a critical component of Sigstore. It's used to verify that a short-lived certificate issued by Fulcio was valid at a previous point, when the artifact was signed." · "When verifying the short-lived code signing certificate, Sigstore verifies that the provided timestamp falls within the certificate's validity period. Sigstore clients can use either the time of inclusion in Rekor or a signed timestamp provided by a trusted timestamping authority." — https://docs.sigstore.dev/cosign/verifying/timestamps/ |
| Rekor v1 시각 | "Sigstore clients relying on Rekor to provide the timestamp use the entry's inclusion time from the integratedTime response field , which is signed over in the signedEntryTimestamp signature ." |
| **자기 한계 고지** | "Note that this timestamp comes from Rekor's internal clock, which is not externally verifiable, and a timestamp is not a part of the node that goes into the append-only data structure that backs Rekor, meaning the timestamp is mutable in Rekor without detection." · "When using Rekor v2, Sigstore clients will get a signed timestamp from a timestamp authority separate from Rekor." · "Since the timestamps are signed, the time becomes immutable and verifiable." (같은 페이지) |
| 번들 요건 | "When using short lived Fulcio certificates where verification may occur after the certificate has expired, bundles must include at least one transparency log's signed entry timestamp or an RFC3161 timestamp to provide proof that signing occurred during the certificates validity window." — https://docs.sigstore.dev/about/bundle/ |

### (d) Git `gpg.ssh.allowedSignersFile` + GitHub
- git-config: "Since OpensSSH 8.8 this file allows specifying a key lifetime using valid-after & valid-before options. Git will mark signatures as valid if the signing key was valid at the time of the signature's creation. This allows users to change a signing key without invalidating all previously made signatures." — https://git-scm.com/docs/git-config (및 https://github.com/git/git/blob/v2.56.0/Documentation/config/gpg.adoc)
- `gpg.ssh.revocationFile`: "Either a SSH KRL or a list of revoked public keys (without the principal prefix). … If a public key is found in this file then it will always be treated as having trust level "never" and signatures will show as invalid." (같은 문서) ⇒ 폐기 파일은 **시각 무관 전면 무효**.
- **git이 쓰는 "서명 시각" = 커밋/태그 본문의 committer/tagger 날짜** (소스 v2.56.0 `gpg-interface.c`):
  - `case SIGNATURE_PAYLOAD_COMMIT: signer_header = "committer";` / `case SIGNATURE_PAYLOAD_TAG: signer_header = "tagger";`
  - `sigc->payload_timestamp = parse_timestamp(ident.date_begin, NULL, 10);`
  - `strbuf_addf(&verify_time, "-Overify-time=%s", show_date(sigc->payload_timestamp, 0, verify_date_mode));` (주석: "SSH signing key validity has no timezone information - Use the local timezone")
  - https://github.com/git/git/blob/v2.56.0/gpg-interface.c
- 커밋 메시지(6393c956): "If valid-before/after dates are configured for this signatures key in the allowedSigners file then the verification should check if the key was valid at the time the commit was made. This allows for graceful key rollover and revoking keys without invalidating all previous commits." · "Older ssh-keygen versions will simply ignore this flag and use the current time." — https://github.com/git/git/commit/6393c956f4e7061d6b19981bd8cd28ef037b911e
- **caveat(committer date는 서명자가 정하는 값)**: git 공식 문서·해당 커밋 메시지에서 이 위험을 경고하는 문장은 **찾지 못함 【미확인】**. 다만 committer 날짜는 서명 대상 payload 안에 서명자가 적는 값이고(위 소스), SSHSIG에는 별도 시각이 없으므로(§1.4), **유출된 키를 가진 공격자는 committer 날짜를 `valid-before` 이전으로 적어 검증을 통과시킬 수 있다** 【추론 — 두 1차 출처의 결합】. 이것이 git 방식을 "정상 회전"에는 쓰되 "유출"에는 쓰면 안 되는 이유다.
- GitHub의 보완 방식(서버 수신 시점 기록): "When a commit signature is verified upon being pushed to GitHub, a verification record is stored alongside the commit. This record can't be edited and will persist so that signatures remain verified over time, even if signing keys are rotated, revoked, or if contributors leave the organization." · "GitHub will not re-verify previously signed commits or retroactively adjust their verification status in response to changes in the key's state." — https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification

### (e) TUF — https://theupdateframework.github.io/specification/latest/ (Version 1.0.36, Last modified 5 August 2026)
- 루트 회전 규칙: "Version N+1 of the root metadata file MUST have been signed by: (1) a THRESHOLD of keys specified in the trusted root metadata file (version N), and (2) a THRESHOLD of keys specified in the new root metadata file being validated (version N+1)." · "each SIGNATURE which is counted towards the THRESHOLD MUST have a unique KEYID"
- "To replace a compromised root key or any other top-level role key, the root role signs a new root.json file that lists the updated trusted keys for the role. When replacing root keys, an application will sign the new root.json file with both the new and old root keys." · "Clients that have outdated root keys can update to the latest set of trusted root keys, by incrementally downloading all intermediate root metadata"
- "If less than a threshold of Root keys are compromised, the repository should revoke trust on the compromised keys. This can be accomplished with a normal rotation of root keys"
- 만료: "The expiration timestamp in the trusted root metadata file MUST be higher than the fixed update start time. If the trusted root metadata file has expired, abort the update cycle, report the potential freeze attack."
- ⇒ allowed_signers(명부) 자체를 버전 번호를 붙여 "이전 판 임계치 서명 + 새 판 임계치 서명"으로 넘기는 구조의 선례 【추론】.

---

## 6. SSH 인증서(CA)·KRL과 `-Y verify`

출처: https://man.openbsd.org/ssh-keygen.1 , 소스 V_10_3_P1

| 질문 | 답 · 원문 |
|---|---|
| allowed_signers가 `cert-authority`를 지원하나 | **예.** "cert-authority — Indicates that this key is accepted as a certificate authority (CA) and that certificates signed by this CA may be accepted for verification." 예시: `*@example.com cert-authority ssh-ed25519 AAAB4...` · "When verifying signatures made by certificates, the expected principal name must match both the principals pattern in the allowed signers file and the principals embedded in the certificate itself." |
| 인증서 유효기간도 verify_time 기준인가 | **예(소스).** `sshkey_cert_check_authority(sign_key, 0, 0, verify_time, principal, &reason)` (sshsig.c) |
| `-Y verify`가 폐기 파일을 받나 | **예.** 개요 `ssh-keygen -Y verify [-O option] -f allowed_signers_file -I signer_identity -n namespace -s signature_file [-r revocation_file]` · "A file containing revoked keys can be passed using the -r flag. The revocation file may be a KRL or a one-per-line list of public keys." |
| KRL | "These binary files specify keys or certificates to be revoked using a compact format, taking as little as one bit per certificate if they are being revoked by serial number." · "Plain public keys are revoked by listing their hash or contents in the KRL and certificates revoked by serial number or key ID" |
| `find-principals`에 `-r` | 없음(개요에 `-r` 없음) — 폐기 검사는 `verify`에서만 【man 개요에서 확인】 |

**【실측】 CA + 인증서 (OpenSSH_10.3p1)**: CA로 `-V 20260101Z:20260601Z`, key id `bob-id`인 사용자 인증서를 발급하고 `-Y sign -f u-cert.pub`로 서명(※ `-f u`로 주면 인증서가 아닌 일반 키로 서명됨 — 소스 `load_sign_key()`가 `-cert.pub` 경로일 때만 인증서를 접붙임):
- 현재 시각 검증: `certificate not authorized: Certificate invalid: expired` rc=255
- `-Overify-time=20260301Z`: `Good "test@x" signature for bob with ED25519-CERT key …` rc=0
- 같은 조건 + KRL(`id: bob-id`) `-r`: `Could not verify signature.` rc=255 ⇒ **KRL은 verify-time과 무관하게 거부.**
- 참고: 이미 만료된 인증서로도 `-Y sign`은 성공했다(서명 시 유효기간 미검사) 【실측】.

---

## 7. 설계 시사점 (조사 결과에서 도출 — 전부 【추론】, 결정은 별도)

1. **"검증 시각"의 출처를 정해야 한다.** SSHSIG는 시각을 증명하지 않는다. 선택지: (A) 이벤트 본문의 서명자 주장 시각(git 방식 — 정상 회전엔 충분, 유출엔 무력), (B) 릴레이 수신 시각(GitHub push 기록·Rekor v1 방식 — 서버가 신뢰 앵커, Sigstore 스스로 "외부 검증 불가·탐지 없이 변경 가능"이라 경고), (C) 해시 체인 순서(Keybase 방식 — 시각 대신 순서, 롤백 방지용 공개 루트 필요), (D) 외부 RFC 3161 TSA.
2. **정상 회전과 유출을 다른 장치로 표현.** 회전 = 옛 키 줄에 `valid-before=<회전시각>Z` (과거 서명 보존, NIST Deactivated). 유출 = `-r` 폐기 목록(과거 전부 무효, NIST Compromised) 또는 `valid-before=<유출추정시각>Z`(RFC 5280 invalidityDate와 같은 소급) — 후자는 검증 시각 출처가 서명자 통제 밖일 때만 의미가 있다.
3. **클라이언트 검증은 반드시 `-Overify-time=<…>Z`를 명시**하고(현재 시각 기본값·로컬 시간대 해석 회피), allowed_signers의 시각도 모두 `Z`로 적는다(≥9.1 필요).
4. **버전 게이트**: 참가 시 `ssh -V` 실측 → `< 8.9`(특히 Windows 10 내장 8.1p1)는 거부 또는 GitHub Win32-OpenSSH 설치 안내. 8.1은 `valid-*` 줄을 버리므로 "조용한 검증 실패"가 난다.
5. **Windows 입력 경로**: PowerShell 5.1 파이프로 메시지를 넘기지 말 것(#2300 미해결; 원인 추정).
6. **서버(TypeScript) 검증기**는 ssh-keygen과 동일한 경계 의미(양 끝 포함, `valid_before <= valid_after` 줄 거부, namespaces 패턴, 폐기는 시각 무관)를 맞춰야 클라이언트 판정과 어긋나지 않는다.

---

## 부록: 확인 방법 기록
- OpenSSH 릴리스 노트: `curl https://www.openssh.com/releasenotes.html` 후 절 헤더 줄번호로 소속 버전 판정(예: valid-after 항목은 "OpenSSH 8.7/8.7p1 (2021-08-20)" 절 안).
- 소스 태그: `raw.githubusercontent.com/openssh/openssh-portable/{V_8_1_P1,V_8_6_P1,V_8_7_P1,V_8_8_P1,V_10_3_P1}/…`, `PowerShell/openssh-portable/{v8.1.0.0,v9.5.0.0}/…`, `git/git/v2.56.0/…`.
- macOS 매핑: `gh api repos/apple-oss-distributions/distribution-macOS/contents/OpenSSH?ref=macos-XXX` → 서브모듈 SHA → OpenSSH 태그 → `openssh/version.h`.
- NIST: PDF를 `pdftotext -layout`로 변환 후 절 번호로 인용.
