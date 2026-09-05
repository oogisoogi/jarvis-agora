// 저장소의 정본 규칙 파일을 **원문 텍스트**로 싣는다(wrangler rules: Text).
// ★JSON 으로 import 하면 파서가 다시 직렬화해 원본 바이트가 사라지고 digest 가 파이썬과 갈린다.
declare module "*.json" { const content: string; export default content; }
declare module "*.txt" { const content: string; export default content; }
