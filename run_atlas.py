"""Run AIDC ATLAS locally; no installation, remote service or paid API required."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from backend.repository import atomic_write, encoded, now


def main():
    parser = argparse.ArgumentParser(description="AIDC ATLAS local pilot")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--store", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate runtime and fixtures without starting a server")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 이상이 필요합니다.")
    from backend import pipeline
    if args.check:
        fixture = json.loads((root / "fixtures" / "official_manual_gold.json").read_text(encoding="utf-8-sig"))
        print("AIDC ATLAS runtime OK; Python", sys.version.split()[0], "; fixture loaded")
        return
    identity = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    runtime = root / "runtime"
    runtime.mkdir(exist_ok=True)
    # Hold a process lock for the full server lifetime, including slow bootstrap.
    instance_lock = (runtime / "instance.lock").open("a+b")
    instance_lock.seek(0, 2)
    if instance_lock.tell() == 0:
        instance_lock.write(b"0")
        instance_lock.flush()
    instance_lock.seek(0)
    owns_lock = False
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(instance_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        owns_lock = True
    except OSError:
        # A first launch may still be preparing its verified snapshot.
        time.sleep(1)
    # A second launch opens the existing instance rather than creating another worker.
    for port in range(args.port, args.port + 10):
        try:
            with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=0.3) as response:
                health = json.load(response)
            if health.get("app") == "aidc-atlas" and health.get("identity") == identity:
                url = f"http://127.0.0.1:{port}/"
                if not args.no_browser:
                    webbrowser.open(url)
                print("AIDC ATLAS already running:", url, flush=True)
                return
        except (OSError, ValueError):
            pass
    if not owns_lock:
        instance_lock.close()
        raise RuntimeError("AIDC ATLAS is already starting. Retry shortly.")
    from backend.server import AtlasApplication, make_server
    app = AtlasApplication(root, args.store)
    server = None
    for port in range(args.port, args.port + 10):
        try:
            server = make_server(app, port)
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("8765~8774 포트가 사용 중입니다. --port로 다른 번호를 지정하십시오.")
    url = f"http://127.0.0.1:{server.server_port}/"
    atomic_write(runtime / "instance.json", encoded({"url": url, "identity": identity, "started_at": now()}))
    app.scheduler.start()
    print("AIDC ATLAS:", url, flush=True)
    print("공개 기사 메타데이터 실수집 + 고정 검증 사례. 기사 본문과 실제 사내 AI는 미연결입니다.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        server.server_close()
        (runtime / "instance.json").unlink(missing_ok=True)
        instance_lock.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Do not print traceback/input values that may contain private material.
        print("실행하지 못했습니다. Python 3.10 이상 및 저장소 파일 상태를 확인하십시오.", file=sys.stderr)
        raise SystemExit(1)
