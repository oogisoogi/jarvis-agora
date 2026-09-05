// flags.js — 화면 기능 켜고 끄는 **유일한 자리**.
//
// ★기본값은 여기 한 곳에만 있다. 쿼리로 임시로 켤 수 있게 하되, **기본은 언제나 꺼짐**이다
//   — 기본값을 바꾸는 것은 화면이 사람에게 말하는 내용을 바꾸는 일이라 이 파일 밖(운영 판단)에서 정한다.

/** 판정 배지 기본값. ⛔이 상수를 true 로 바꾸는 것은 운영 결정이다(워커가 뒤집지 않는다). */
export const VERDICT_BADGES_DEFAULT = false;

/** 이번 화면에서 판정 배지를 켤 것인가 — `?verdict=1` 이면 켠다. */
export function verdictBadgesOn() {
  try {
    const q = new URLSearchParams(location.search).get('verdict');
    if (q === '1') return true;
    if (q === '0') return false;
  } catch {
    // 주소를 못 읽는 자리(테스트 등)에서는 기본값으로 간다
  }
  return VERDICT_BADGES_DEFAULT;
}
