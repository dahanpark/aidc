"""Export committed, allowlisted source to a separate public Git history."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
AI_DOC_TAG = 'atlas-ai-documents-20261024'
AI_DOC_VERSION = '2.3'


def ai_documentation_readme():
    base = f'https://github.com/dahanpark/aidc/releases/download/{AI_DOC_TAG}'
    return f'''## 최신 기획서·매뉴얼 · AI 분석 v{AI_DOC_VERSION}

[AI 문서 릴리스](https://github.com/dahanpark/aidc/releases/tag/{AI_DOC_TAG})는 REV013의 선택형 AI 분석을 설명합니다. 공개 기사 근거 추출·동일 사업 후보 비교·동향/점검 요약, PC별 키 등록·삭제, 전송 확인·호출 한도·실제 품질 검증 절차를 포함합니다. 실제 개인 API 품질·회사 PC·화면 인수 완료를 뜻하지 않습니다.

|최신 자료|다운로드|
|---|---|
|세부 개발 기획서 v{AI_DOC_VERSION}|[DEVELOPMENT_PLAN.md]({base}/DEVELOPMENT_PLAN.md)|
|사용자 매뉴얼 v{AI_DOC_VERSION}|[USER_MANUAL.html]({base}/USER_MANUAL.html) · [USER_MANUAL.md]({base}/USER_MANUAL.md)|
|파일 안내·SHA256|[README.TXT]({base}/README.TXT) · [DELIVERABLES.json]({base}/DELIVERABLES.json)|

키는 프로그램의 **AI 연결**에서 Windows 보안 저장소에 등록합니다. `.env` 자동 생성·읽기는 지원하지 않습니다. AI 미연결 기능은 유지하며 분석은 표본/사용량 확인 후 명시 실행합니다. 아래 기존 문서·발표·스킬·시연·ZIP 릴리스는 과거 버전으로 보존합니다.
'''


def git(*args, cwd=ROOT, binary=False):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    if result.returncode:
        # Git errors might contain a credential-bearing URL; never echo them.
        raise RuntimeError("Git command failed: " + args[0])
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def api(path, token, payload=None):
    req = urllib.request.Request("https://api.github.com" + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "User-Agent": "AIDC-Atlas-Publication", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def scan(name, raw):
    text = raw.decode("utf-8-sig")
    # This exact reserved-domain dummy verifies credential-URL rejection.
    # Exempt only this literal in this file, never a whole test directory.
    if name == "tests/test_pipeline.py":
        text = text.replace("https://" + "user:" + "secret@example.com/", "https://example.com/")
    patterns = [r"gh[pousr]_[A-Za-z0-9]{30,}", r"github_pat_[A-Za-z0-9_]{30,}",
                r"AKIA[A-Z0-9]{16}", r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}",
                r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                r"https?://[^\s/:]+:[^\s/@]+@"]
    if any(re.search(pattern, text) for pattern in patterns):
        raise RuntimeError("Potential credential found; publication stopped: " + name)


def write_generated(path, text):
    # Public hashes must describe the exact Git blob even on Windows.
    path.write_bytes(text.replace('\r\n', '\n').replace('\r', '\n').encode('utf-8'))


def staged_file_hashes(directory, names):
    # Existing source blobs may themselves contain CRLF. Git filters on add;
    # the manifest describes the resulting index, not the working tree bytes.
    return {name: hashlib.sha256(git('show', ':' + name, cwd=directory, binary=True)).hexdigest()
            for name in names}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    policy = json.loads((ROOT / "config/publication.json").read_text(encoding="utf-8-sig"))
    owner, repo = policy["repository"].split("/")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", owner) or repo != "aidc" or policy["visibility"] != "public":
        raise RuntimeError("Unexpected publication destination")
    tracked = git("ls-files").splitlines()
    selected = []
    for name in tracked:
        path = PurePosixPath(name)
        if any(name == p or name.startswith(p + "/") for p in policy["excluded_roots"]):
            continue
        if path.name in policy["excluded_file_names"] or path.suffix not in policy["allowed_extensions"]:
            continue
        if name in policy["include_files"] or any(name.startswith(p + "/") for p in policy["include_directories"]):
            selected.append(name)
    if not set(policy["include_files"]).issubset(selected):
        raise RuntimeError("Required publication files are not committed")
    changed = set(git("diff", "HEAD", "--name-only").splitlines())
    if changed.intersection(selected):
        raise RuntimeError("Commit selected source changes before publication")
    source_commit = git("rev-parse", "HEAD")
    revision = json.loads(git("show", "HEAD:config/revisions.json"))["current_revision"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = ROOT / "runtime" / "publication" / stamp / "aidc"
    dest.mkdir(parents=True, exist_ok=False)
    remote = f"https://github.com/{owner}/{repo}.git"
    token = None
    remote_exists = False
    if args.publish:
        creds = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                               text=True, capture_output=True)
        fields = dict(line.split("=", 1) for line in creds.stdout.splitlines() if "=" in line)
        token = fields.get("password")
        if creds.returncode or not token:
            raise RuntimeError("GitHub credentials unavailable")
        if api("/user", token)["login"].lower() != owner.lower():
            raise RuntimeError("Authenticated account does not own destination")
        try:
            existing = api(f"/repos/{owner}/{repo}", token)
            if existing["private"] or not existing.get("permissions", {}).get("push"):
                raise RuntimeError("Existing destination is private or not writable")
            remote_exists = True
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
    git("init", "-b", "main", cwd=dest)
    git("remote", "add", "origin", remote, cwd=dest)
    if remote_exists:
        existing = api(f"/repos/{owner}/{repo}", token)
        if existing.get("size", 0) or existing.get("default_branch"):
            # Empty GitHub repositories may report a default branch without refs.
            refs = git("ls-remote", "--heads", "origin", "main", cwd=dest)
            if refs:
                git("fetch", "--depth=1", "origin", "main", cwd=dest)
                git("checkout", "-B", "main", "FETCH_HEAD", cwd=dest)
                previous = dest / "PUBLICATION.json"
                if not previous.exists():
                    raise RuntimeError("Existing repository is not an Atlas managed publication")
                for name in json.loads(previous.read_text(encoding="utf-8"))["files"]:
                    target = dest.joinpath(*PurePosixPath(name).parts).resolve()
                    if not target.is_relative_to(dest.resolve()) or ".git" in target.relative_to(dest).parts:
                        raise RuntimeError("Invalid previous manifest path")
                    target.unlink(missing_ok=True)
    hashes = {}
    for name in selected:
        raw = git("show", "HEAD:" + name, binary=True)
        scan(name, raw)
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    deliverables = 'https://github.com/dahanpark/aidc/releases/download/atlas-project-deliverables-20261020'
    readme = f'''# AIDC ATLAS

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

## 선택형 AI 분석과 회사망 연결 · REV013

AI 미연결 상태에서도 수집·규칙 분류·관계도·스크랩·명시 확인을 사용합니다. 상단 **AI 연결**에서 OpenAI/Claude/Gemini 키를 이 PC의 Windows 보안 저장소에 등록하거나 전용 환경변수 참조를 사용합니다. 키 형식이 모호하면 제공사 하나를 선택하며 여러 회사에 키를 순차 전송하지 않습니다. 키 인증은 모델 목록 조회이고 기사 분석은 별도 선택 실행입니다.

DASHBOARD 현황 아래 **동향 · 점검 요약**에서 선택/최신 공개 기사 표본의 근거 추출·동일 사업 후보·출처 연결 동향을 생성합니다. 기본 5기사/회·50호출/UTC일이며 SETTINGS에서 조정합니다. 전송 표본과 API 사용량 안내를 확인한 뒤 실행하며 금액 한도는 제공사 계정에서도 설정합니다. 본문·수동 메모·사내 링크는 전송하지 않습니다. 동일 사업 후보 확인은 자동 원본 병합이 아닙니다. 실제 계정 모델 접근성과 분석 품질은 별도로 확인해야 합니다.

SETTINGS에서 제공사/모델/인증 시각/호출량/연결 해제/키 삭제를 관리합니다. 환경변수 연결은 `ATLAS_AI_OPENAI_KEY`, `ATLAS_AI_ANTHROPIC_KEY`, `ATLAS_AI_GOOGLE_KEY`만 참조하며 선택 삭제는 해당 프로세스·Windows 사용자 변수에 한정됩니다. `.env` 파일·머신 변수·제공사 키 폐기는 별도입니다.

회사망에서 실패하면 SETTINGS의 **사내망 수집 연결 진단**을 실행합니다. 시스템/환경 HTTPS 프록시와 회사 CA 추가 신뢰(`ATLAS_CA_BUNDLE`/`SSL_CERT_FILE`)를 지원합니다. TLS 검증은 유지합니다. PAC·통합인증·방화벽 정책은 IT 담당자의 `HTTPS_PROXY`/CA/도메인 허용 설정이 필요할 수 있습니다. 수집은 `news.google.com:443`, `www.datacenterdynamics.com:443`, AI는 선택한 제공사의 API 도메인을 사용합니다.

정상 재기동의 중복 전체 읽기를 3회에서 1회로 줄이고 큰 저장소의 검증을 최대 8작업으로 나눕니다. 최초 업그레이드는 새 세대 활성화 전 전체 검증까지 2회를 유지합니다.

스크랩은 한 번 클릭으로 저장하고 SCRAP에서 기사 필터와 무관하게 전체 저장분을 확인합니다. 신규 기사 표시 기본 30일은 SETTINGS에서 변경하며, 관계도 배지 팝업에서 원문과 정확한 기사 확인 버튼을 사용합니다. 기존 미확인 알림은 보존합니다.

{ai_documentation_readme()}

## 이전 개발 자료와 다운로드 경로 · REV012 보존본

기획서·매뉴얼·스킬과 정의서·발표자료·시연영상은 [개발 산출물 릴리스](https://github.com/dahanpark/aidc/releases/tag/atlas-project-deliverables-20261020)에 공개했습니다. 각 파일은 아래 경로에서 내려받습니다.

|자료|파일과 다운로드 경로|
|---|---|
|세부 프로젝트 기획서 v2.1|[DEVELOPMENT_PLAN.md]({deliverables}/DEVELOPMENT_PLAN.md)|
|사용자 매뉴얼|[USER_MANUAL.html]({deliverables}/USER_MANUAL.html) · [USER_MANUAL.md]({deliverables}/USER_MANUAL.md)|
|프로젝트 스킬 13개 v0.2.1|[atlas-skills-v0.2.1.zip]({deliverables}/atlas-skills-v0.2.1.zip)|
|13개 스킬 전체 정의서|[SKILL_DEFINITIONS.md]({deliverables}/SKILL_DEFINITIONS.md)|
|스킬 목록과 사용 조건|[SKILL_CATALOG.md]({deliverables}/SKILL_CATALOG.md)|
|발표자료 PDF 18장|[AIDC-ATLAS-PRESENTATION.pdf]({deliverables}/AIDC-ATLAS-PRESENTATION.pdf)|
|시연영상 MP4 약160MB|[AIDC-ATLAS-DEMO.mp4]({deliverables}/AIDC-ATLAS-DEMO.mp4)|
|목적·구축·AI 활용·효과 설명서|[HTML]({deliverables}/AIDC-ATLAS-OVERVIEW.html) · [Word DOCX]({deliverables}/AIDC-ATLAS-OVERVIEW.docx)|
|전체 파일 안내와 해시|[README.TXT]({deliverables}/README.TXT) · [DELIVERABLES.json]({deliverables}/DELIVERABLES.json)|
|기획·스킬·매뉴얼·설명서 문서 ZIP|[AIDC.ATLAS.PROJECT.ZIP](https://github.com/dahanpark/aidc/releases/download/project-documents-20261019-ff855ff5/AIDC.ATLAS.PROJECT.ZIP)|

HTML 파일은 내려받은 뒤 브라우저로 엽니다. PDF에서 동영상은 재생되지 않으므로 별도 MP4를 사용합니다. 이 릴리스 문서·발표자료는 REV012 시점 보존본이며, 실행 소스와 REV013 AI/회사망 안내는 main 브랜치를 사용합니다. 문서의 향후 개발 제안과 실제 구현·실측을 구분합니다.

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

소스 REV: **{revision}**. 로컬 원본과 공개 이력의 연결은 `PUBLICATION.json`에 기록합니다.
공개본은 별도 Git 이력이며 로컬 전체 Git 객체를 전송하지 않습니다. 로컬 폴더·과거 검증 결과에 의존하는 일부 운영 검증 스크립트는 공개본에서 사용할 수 없습니다.

자동 소스 공개 범위는 `config/publication.json`에 명시합니다. 위 산출물은 사용자가 별도로 공개를 지시한 파일만 릴리스에 첨부했습니다. 그 밖의 업무 자료·개발 인계·의사결정 문서와 로컬 REV 대장은 전송하지 않습니다.
'''
    write_generated(dest / "README.md", readme)
    write_generated(dest / ".gitignore", "store/\nruntime/\nbackups/\nexports/\nderived_index/\noutput/\n.env\n.env.*\n*.local.json\n*.lnk\n__pycache__/\n*.py[cod]\nnode_modules/\n")
    for name in ["README.md", ".gitignore"]:
        hashes[name] = hashlib.sha256((dest / name).read_bytes()).hexdigest()
    git('add', '--all', cwd=dest)
    hashes = staged_file_hashes(dest, hashes)
    manifest = {"schema_version": "1.0", "source_commit": source_commit, "source_revision": revision,
                "repository": policy["repository"], "exported_at": stamp, "files": hashes,
                "exclusions": policy["excluded_roots"], "secret_pattern_scan": "PASS"}
    write_generated(dest / "PUBLICATION.json", json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    result = subprocess.run([sys.executable, "-B", "run_atlas.py", "--check"], cwd=dest, capture_output=True)
    if result.returncode:
        raise RuntimeError("Exported runtime check failed")
    git("add", "--all", cwd=dest)
    git("diff", "--cached", "--check", cwd=dest)
    report = {"status": "PASS", "repository": policy["repository"], "source_commit": source_commit,
              "source_revision": revision, "files": len(hashes), "export_directory": str(dest), "published": False}
    if args.publish:
        if not remote_exists:
            created = api("/user/repos", token, {"name": repo, "private": False,
                         "description": "AIDC ATLAS — evidence-linked data center project and company intelligence"})
            if created["private"] or created["full_name"].lower() != policy["repository"].lower():
                raise RuntimeError("Unexpected created repository")
        git("-c", "user.name=Atlas", "-c", "user.email=atlas@localhost", "-c", "commit.gpgsign=false",
            "commit", "-m", f"Publish {revision} source {source_commit[:12]}", cwd=dest)
        git("push", "-u", "origin", "main", cwd=dest)
        sha = git("rev-parse", "HEAD", cwd=dest)
        remote_sha = git("ls-remote", "origin", "refs/heads/main", cwd=dest).split()[0]
        if sha != remote_sha:
            raise RuntimeError("Remote commit mismatch")
        report.update(published=True, public_commit=sha, url=f"https://github.com/{owner}/{repo}")
    (ROOT / "runtime" / "github_publication.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not echo HTTP headers, response bodies, or Git credential output.
        print(json.dumps({"status": "FAIL", "error": str(error) if isinstance(error, RuntimeError) else type(error).__name__}))
        raise SystemExit(1)
