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

공개 범위는 `config/publication.json`에 명시합니다. 사내 목적·개발 인계·의사결정 문서와 로컬 REV 대장은 공개하지 않습니다.
'''
    (dest / "README.md").write_text(readme, encoding="utf-8")
    (dest / ".gitignore").write_text("store/\nruntime/\nbackups/\nexports/\nderived_index/\noutput/\n.env\n.env.*\n*.local.json\n*.lnk\n__pycache__/\n*.py[cod]\nnode_modules/\n", encoding="utf-8")
    for name in ["README.md", ".gitignore"]:
        hashes[name] = hashlib.sha256((dest / name).read_bytes()).hexdigest()
    manifest = {"schema_version": "1.0", "source_commit": source_commit, "source_revision": revision,
                "repository": policy["repository"], "exported_at": stamp, "files": hashes,
                "exclusions": policy["excluded_roots"], "secret_pattern_scan": "PASS"}
    (dest / "PUBLICATION.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
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
