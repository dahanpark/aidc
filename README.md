# AIDC ATLAS

DC·AIDC 사업과 기업의 공개 기사 근거를 연결하는 로컬 정보 모니터링 파일럿입니다.
사업자·발주처·테넌트·운영사·시공사·설계사·장비사·PF사 간 관계를 탐색하고 사업 기회 파악을 지원합니다.

## 실행

Python 3.10 이상에서 저장소를 내려받아 다음 명령으로 실행합니다. Python 외 별도 패키지는 필요하지 않습니다.

```sh
python run_atlas.py
```

Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_atlas.ps1`
주소는 기본 `http://127.0.0.1:8765/`입니다. Windows 바로가기는 `scripts/create_shortcut.ps1`로 생성할 수 있습니다.

## 메뉴

- DASHBOARD: 국내 AIDC 기본 범위, 관계도 우선·오른쪽 검색/지표·지도·기사
- COMPANY: 기업 성격과 1-hop 관계, 관련 사업·기사, 사용자 분류
- PROJECT: 프로젝트별 기업·정보·기사 근거
- LOCATION: 국내 AIDC 기본 범위, 지도 우선·오른쪽 조건/지역 기사
- NEWS / SYNTHESIS / SCRAP / ALERTS / SETTINGS

## 개발 자료와 다운로드 경로

기획서·매뉴얼·스킬과 정의서·발표자료·시연영상은 [개발 산출물 릴리스](https://github.com/dahanpark/aidc/releases/tag/atlas-project-deliverables-20261020)에 공개했습니다. 각 파일은 아래 경로에서 내려받습니다.

|자료|파일과 다운로드 경로|
|---|---|
|세부 프로젝트 기획서 v2.1|[DEVELOPMENT_PLAN.md](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/DEVELOPMENT_PLAN.md)|
|사용자 매뉴얼|[USER_MANUAL.html](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/USER_MANUAL.html) · [USER_MANUAL.md](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/USER_MANUAL.md)|
|프로젝트 스킬 13개 v0.2.1|[atlas-skills-v0.2.1.zip](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/atlas-skills-v0.2.1.zip)|
|13개 스킬 전체 정의서|[SKILL_DEFINITIONS.md](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/SKILL_DEFINITIONS.md)|
|스킬 목록과 사용 조건|[SKILL_CATALOG.md](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/SKILL_CATALOG.md)|
|발표자료 PDF 18장|[AIDC-ATLAS-PRESENTATION.pdf](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/AIDC-ATLAS-PRESENTATION.pdf)|
|시연영상 MP4 약160MB|[AIDC-ATLAS-DEMO.mp4](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/AIDC-ATLAS-DEMO.mp4)|
|목적·구축·AI 활용·효과 설명서|[HTML](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/AIDC-ATLAS-OVERVIEW.html) · [Word DOCX](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/AIDC-ATLAS-OVERVIEW.docx)|
|전체 파일 안내와 해시|[README.TXT](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/README.TXT) · [DELIVERABLES.json](https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020/DELIVERABLES.json)|
|기획·스킬·매뉴얼·설명서 문서 ZIP|[AIDC.ATLAS.PROJECT.ZIP](https://github.com/dahanpark/aidc/releases/download/project-documents-20261019-ff855ff5/AIDC.ATLAS.PROJECT.ZIP)|

HTML 파일은 내려받은 뒤 브라우저로 엽니다. PDF에서 동영상은 재생되지 않으므로 별도 MP4를 사용합니다. 문서와 발표자료는 기능 기준 REV012이며, 실행 소스는 main 브랜치를 사용합니다. 문서의 향후 개발 제안과 실제 구현·실측을 구분합니다.

## 데이터와 한계

처음 실행하면 공개 공식자료 기반 고정 검증 사례로 시작합니다. 실제 공개 기사 메타데이터 수집은 앱에서 실행·설정합니다.
기본 기사 조회는 최근 1년이며 3년을 포함한 기간 선택과 기존 자료를 유지합니다. 관계도는 일반 마우스 휠 확대/축소와 드래그 이동을 지원합니다.
이 저장소에는 사용자의 수집 이력, 업무 JSON, 사내 링크·메모, 비밀키, 백업, 원본 압축파일이 없습니다.
기사 전문·유료벽 우회·실제 사내 AI 연결은 제공하지 않습니다. 관측 후보·같은 기사 등장과 확정 참여·직접 계약을 구분합니다.
전체 개발 계약 완료본이나 시장 전체 사업 목록이 아닌 v0.4 로컬 파일럿입니다.

## 검증과 이력

```sh
python -B run_atlas.py --check
python -B -m unittest discover -s tests
```

소스 REV: **REV012**. 로컬 원본과 공개 이력의 연결은 `PUBLICATION.json`에 기록합니다.
공개본은 별도 Git 이력이며 로컬 전체 Git 객체를 전송하지 않습니다. 로컬 폴더·과거 검증 결과에 의존하는 일부 운영 검증 스크립트는 공개본에서 사용할 수 없습니다.

자동 소스 공개 범위는 `config/publication.json`에 명시합니다. 위 산출물은 사용자가 별도로 공개를 지시한 파일만 릴리스에 첨부했습니다. 그 밖의 업무 자료·개발 인계·의사결정 문서와 로컬 REV 대장은 전송하지 않습니다.
