/**
 * 받아들이기 차단(은퇴) — 설계 docs/design/key-lifecycle/DESIGN-v3.md §5 · 표 = migrations/0002_admission_blocks.sql
 *
 * ★이 모듈은 **새 쓰기를 받을지 말지**(POST /events · /register · /participants/checkpoint)와 /home 알림에서만 쓴다.
 *   명부 렌더·체크포인트 산식·서명 검증(rosterView·lookupTable·verifyDetail)·방 판정(deriveThread·리듀서)에서
 *   부르면 안 된다 — 판정은 참가자가 명부 파일로 다시 계산하는 정본이고, 서버의 참고 판정은 참가자의 쓰기 경로가
 *   쓰므로 서버에만 있는 사실이 섞이면 그 방 전원의 쓰기가 멈춘다(설계 §1-3 경계 · 시험 T8·T13).
 * ★여기의 검사는 **친절한 응답**을 위한 것이고, 최종 집행은 DB 트리거다(경합·코드 롤백에도 남는다).
 */

/** 트리거가 RAISE 하는 표식. D1 은 메시지를 감싸므로 **포함**으로 비교한다(같음 비교 금지 · r2 D2-5).
 *  ★짝 = migrations/0002_admission_blocks.sql 의 RAISE 문자열 4곳 — 한쪽만 바꾸면 catch 가 500 으로 샌다(경합 시험 race 가 잡는다). */
export const ADMISSION_MARK = "agora:admission_blocked";

export interface AdmissionBlock {
  participant_id: string;
  fingerprint: string;
  blocked_at: string;
}

/** id 또는 지문으로 차단 행을 찾는다. 모르는 쪽은 null 로 넘긴다(NULL 과의 = 는 어떤 행과도 맞지 않는다). */
export async function admissionBlock(db: D1Database, participantId: string | null,
                                     fingerprint: string | null): Promise<AdmissionBlock | null> {
  const row = await db.prepare(
    "SELECT participant_id, fingerprint, blocked_at FROM admission_blocks WHERE participant_id = ?1 OR fingerprint = ?2 LIMIT 1"
  ).bind(participantId, fingerprint).first<AdmissionBlock>();
  return row ?? null;
}

/** INSERT 가 차단 트리거에 걸려 실패했는가(원인 사슬까지 본다). */
export function isAdmissionBlockedError(e: unknown): boolean {
  let cur: unknown = e;
  for (let i = 0; i < 4 && cur; i++) {
    const msg = cur instanceof Error ? cur.message : String(cur);
    if (msg.includes(ADMISSION_MARK)) return true;
    cur = cur instanceof Error ? (cur as Error & { cause?: unknown }).cause : null;
  }
  return false;
}
