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

- DASHBOARD: 국내 AIDC 기본 범위, 지표·온톨로지·지도·기사
- COMPANY: 기업 성격과 1-hop 관계, 관련 사업·기사, 사용자 분류
- PROJECT: 프로젝트별 기업·정보·기사 근거
- LOCATION: 지역별 지도와 기사
- NEWS / SYNTHESIS / SCRAP / ALERTS / SETTINGS

## 데이터와 한계

처음 실행하면 공개 공식자료 기반 고정 검증 사례로 시작합니다. 실제 공개 기사 메타데이터 수집은 앱에서 실행·설정합니다.
이 저장소에는 사용자의 수집 이력, 업무 JSON, 사내 링크·메모, 비밀키, 백업, 원본 압축파일이 없습니다.
기사 전문·유료벽 우회·실제 사내 AI 연결은 제공하지 않습니다. 관측 후보·같은 기사 등장과 확정 참여·직접 계약을 구분합니다.
전체 개발 계약 완료본이나 시장 전체 사업 목록이 아닌 v0.4 로컬 파일럿입니다.

## 검증과 이력

```sh
python -B run_atlas.py --check
python -B -m unittest discover -s tests
```

소스 REV: **REV011**. 로컬 원본과 공개 이력의 연결은 `PUBLICATION.json`에 기록합니다.
공개본은 별도 Git 이력이며 로컬 전체 Git 객체를 전송하지 않습니다. 로컬 폴더·과거 검증 결과에 의존하는 일부 운영 검증 스크립트는 공개본에서 사용할 수 없습니다.

공개 범위는 `config/publication.json`에 명시합니다. 사내 목적·개발 인계·의사결정 문서와 로컬 REV 대장은 공개하지 않습니다.
