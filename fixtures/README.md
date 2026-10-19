# 공식 기사 수동 gold fixture

2026-10-16 공식 페이지 3개를 확인하여 짧은 발췌와 자체 요약을 전사했다. 원문 전문·이미지는 저장하지 않았다. 실제 출처를 사용하지만 추출/자동반영은 fixture_mock이며 실제 AI 품질·실시간 수집·현재 운영상태를 검증한 자료가 아니다.

- [SK텔레콤 울산 AI 데이터센터 기공식, 2025-08-29](https://news.sktelecom.com/214708)
- [OpenAI·Oracle 미국 4.5GW 개발 협약, 2025-07-22](https://openai.com/index/stargate-advances-with-partnership-with-oracle/)
- [Stargate UAE, 2025-05-22](https://openai.com/index/introducing-stargate-uae/)

원본은 official_manual_gold.json. UAE 1GW와 포함분200MW는 program/phase 및 parent_id로 구분하고 합산하지 않는다. capacity는 IT/수전 여부가 특정되지 않아 announced_capacity다. 2026년 가동 예상은 계획이며 실제 가동 여부는 미확인이다. 국내 일반 DC는 근거 fixture가 없으므로 빈 범위를 유지한다. 반복 수집은 이 파일의 재생이며 네트워크를 호출하지 않는다. 수동 기사 입력 역시 URL을 fetch하지 않는다.
