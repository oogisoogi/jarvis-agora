/**
 * 오류 계약 — 코드의 유일한 정의처(파이썬 `agora/errors.py` 와 같은 값).
 *
 * ★같은 숫자를 다른 파일에 다시 적지 않는다. 두 곳이 조용히 갈라진다.
 * ★판정의 정본은 본문 `code` 다. HTTP 상태는 관례이고, 둘이 갈리면 code 가 이긴다(docs/RELAY.md §3-0).
 */

export const OK = 0;
export const PRECONDITION = 2;
export const GATE_REJECT = 3;
export const SIGNATURE = 4;
export const PERMISSION = 5;
export const STORE = 7;
export const UNKNOWN_COMMIT = 8;
export const STATE_CONFLICT = 9;
export const ARGUMENT = 10;

export const ALL_CODES = [PRECONDITION, GATE_REJECT, SIGNATURE, PERMISSION,
  STORE, UNKNOWN_COMMIT, STATE_CONFLICT, ARGUMENT] as const;

export const NAMES: Record<number, string> = {
  [PRECONDITION]: "precondition",
  [GATE_REJECT]: "gate_reject",
  [SIGNATURE]: "signature",
  [PERMISSION]: "permission",
  [STORE]: "store",
  [UNKNOWN_COMMIT]: "unknown_commit",
  [STATE_CONFLICT]: "state_conflict",
  [ARGUMENT]: "argument",
};

/** 코드별 기본 HTTP 상태(docs/RELAY.md §3-7). 엔드포인트가 더 좁은 상태를 줄 수 있다. */
const DEFAULT_STATUS: Record<number, number> = {
  [PRECONDITION]: 400,
  [ARGUMENT]: 400,
  [SIGNATURE]: 401,
  [PERMISSION]: 403,
  [GATE_REJECT]: 422,
  [STATE_CONFLICT]: 409,
  [STORE]: 500,
  [UNKNOWN_COMMIT]: 500,
};

export class AgoraError extends Error {
  code: number;
  detail: unknown;
  status: number;
  headers: Record<string, string>;

  constructor(code: number, message: string, detail?: unknown,
              opts?: { status?: number; headers?: Record<string, string> }) {
    super(message);
    if (!(ALL_CODES as readonly number[]).includes(code)) {
      // 계약 밖 코드로 실패를 만들려는 시도 자체가 인자 오류다.
      code = ARGUMENT;
      detail = { bad_code: code };
    }
    this.code = code;
    this.detail = detail ?? null;
    this.status = opts?.status ?? DEFAULT_STATUS[code] ?? 500;
    this.headers = opts?.headers ?? {};
  }

  toBody() {
    return { code: this.code, name: NAMES[this.code], message: this.message, detail: this.detail };
  }
}

export function fail(code: number, message: string, detail?: unknown,
                     opts?: { status?: number; headers?: Record<string, string> }): never {
  throw new AgoraError(code, message, detail, opts);
}
