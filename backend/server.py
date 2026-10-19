"""Local-only API and static UI, with one in-process collection scheduler."""
from __future__ import annotations
import copy
import hashlib
import json
import mimetypes
import os
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__
from .repository import JsonRepository, atomic_write, encoded, loads, now
from . import reports
from . import pipeline
from .security import assert_safe_url
from . import news
from .ontology import build_ontology
from .company_catalog import build_company_catalog
from .project_discovery import enrich_discovery, build_project_discovery
from .attention import build_attention, apply_acknowledgement


class SnapshotIntegrityError(RuntimeError):
    """A failed strict validation must be visible without exposing record data."""


INTEGRITY_MESSAGE = '저장 자료 무결성 재검증에 실패했습니다. 마지막 정상 화면을 유지합니다. 원본 점검 또는 검증된 백업 복구가 필요합니다.'


class AtlasApplication:
    def __init__(self, root, store=None):
        self.root = Path(root).resolve()
        self.repo = JsonRepository(store or self.root / "store")
        self.csrf = secrets.token_urlsafe(32)
        self.identity = hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:16]
        self.stop = threading.Event()
        self.collection_lock = threading.Lock()
        self.news_thread = None
        self._view_lock = threading.Lock()
        self._view_snapshot = None
        self._view_pointer = None
        self._view_checked_at = 0
        self._view_error_pointer = None
        self._view_validator = None
        self._view_refresh_lock = threading.Lock()
        self.repo.publish_callback = self._publish_view_snapshot
        pipeline.bootstrap(self.repo, self.root)
        def migrate(ds):
            news.enrich_articles(ds,list(ds.get('articles',{})))
            enrich_discovery(ds,list(ds.get('articles',{})))
            settings = ds.setdefault('settings',{}).setdefault('app',{'id':'app'})
            settings['news_default_period'] = '3y'
            settings.setdefault('baseline_backfill_enabled',True)
            for job in ds.get('news_jobs', {}).values():
                if job.get('status') in ('running', 'queued'):
                    job.update(status='interrupted', updated_at=now(), message='앱이 재시작되었습니다. 남은 기간 수집을 재개할 수 있습니다.')
        # One atomic startup transaction, reusing its fully verified result for
        # the first view instead of immediately rereading thousands of files.
        startup_snapshot = self.repo.transact(migrate)
        self._publish_view_snapshot(startup_snapshot, (self.repo.root / 'CURRENT.json').read_bytes())
        self.scheduler = threading.Thread(target=self._schedule, name="atlas-hourly", daemon=True)

    def _publish_view_snapshot(self, snapshot, pointer):
        if loads(pointer).get('generation') != snapshot.get('generation'):
            return False
        defensive = copy.deepcopy(snapshot)
        # This cheap pointer read is the only filesystem operation under the
        # cache lock. Full checksum scans and copies never hold the lock.
        with self._view_lock:
            if (self.repo.root / 'CURRENT.json').read_bytes() != pointer:
                return False
            self._view_snapshot = defensive
            self._view_pointer = bytes(pointer)
            self._view_checked_at = time.monotonic()
            self._view_error_pointer = None
        return True

    def _read_view_pointer(self):
        try:
            return (self.repo.root / 'CURRENT.json').read_bytes()
        except OSError as error:
            raise SnapshotIntegrityError(INTEGRITY_MESSAGE) from error

    def _validate_view_background(self, pointer):
        try:
            verified = self.repo.snapshot()
            if verified.get('generation') != loads(pointer).get('generation'):
                return
            # Publication repeats the exact CURRENT check, so an old validator
            # can never overwrite a newer internal commit or external generation.
            self._publish_view_snapshot(verified, pointer)
        except Exception:
            with self._view_lock:
                if self._view_pointer == pointer:
                    try:
                        current_matches = self._read_view_pointer() == pointer
                    except SnapshotIntegrityError:
                        current_matches = True
                    if current_matches:
                        self._view_error_pointer = pointer
        finally:
            with self._view_lock:
                if self._view_validator is threading.current_thread():
                    self._view_validator = None

    def view_snapshot(self):
        pointer = self._read_view_pointer()
        validator = None
        with self._view_lock:
            if self._view_error_pointer == pointer:
                raise SnapshotIntegrityError(INTEGRITY_MESSAGE)
            cached = self._view_snapshot if pointer == self._view_pointer else None
            if cached is not None and time.monotonic() - self._view_checked_at > 20 and self._view_validator is None and not self.stop.is_set():
                validator = threading.Thread(target=self._validate_view_background, args=(pointer,),
                    name='atlas-integrity-check', daemon=True)
                self._view_validator = validator
        if cached is not None:
            if validator is not None:
                validator.start()
            return copy.deepcopy(cached)
        # A generation changed outside this application's verified writer path.
        # Validate it synchronously before it can become visible; parallel GETs
        # share the completed cache rather than repeating a large disk scan.
        with self._view_refresh_lock:
            for _ in range(3):
                pointer = self._read_view_pointer()
                with self._view_lock:
                    if self._view_error_pointer == pointer:
                        raise SnapshotIntegrityError(INTEGRITY_MESSAGE)
                    cached = self._view_snapshot if pointer == self._view_pointer else None
                if cached is not None:
                    return copy.deepcopy(cached)
                try:
                    verified = self.repo.snapshot()
                    if self._publish_view_snapshot(verified, pointer):
                        return copy.deepcopy(verified)
                except Exception as error:
                    with self._view_lock:
                        if self._read_view_pointer() == pointer:
                            self._view_error_pointer = pointer
                    raise SnapshotIntegrityError(INTEGRITY_MESSAGE) from error
        raise SnapshotIntegrityError('저장 세대가 변경 중입니다. 잠시 후 다시 조회하십시오.')

    def state(self, filters=None):
        snapshot = self.view_snapshot()
        datasets = snapshot["datasets"]
        names = ["projects", "companies", "articles", "claims", "relationships", "changes", "read_states",
                 "bookmarks", "internal_links", "notifications", "jobs", "coverage", "extraction_runs", "news_updates", "news_read_states"]
        data = {name: list(datasets.get(name, {}).values()) for name in names}
        from .company_profiles import profile_fields
        data['companies'] = [{**item, **profile_fields(item, datasets.get('company_classifications', {}).get(item['id']))} for item in data['companies']]
        data["settings"] = datasets.get("settings", {}).get("app", {})
        data['news'] = news.build_workspace(snapshot, filters, include_catalog=True)
        catalog_source = data['news'].pop('_company_catalog_source')
        data['company_catalog'] = build_company_catalog(snapshot, data['news'], catalog_source)
        data['project_discovery'] = build_project_discovery(snapshot, data['news'])
        focus_company = (filters or {}).get('graph_company_id') or ''
        if not isinstance(focus_company, str) or len(focus_company) > 200:
            raise ValueError('잘못된 관계도 기업 선택입니다.')
        known_companies = set(datasets.get('companies', {})) | {item['id'] for item in data['company_catalog']['companies']}
        focus_company = focus_company.strip() if focus_company.strip() in known_companies else None
        data['ontology'] = build_ontology(snapshot,data['news'], focus_company_id=focus_company)
        data['attention'] = build_attention(snapshot,data['news'])
        from .geo import build_map_workspace
        visual = data['settings'].get('visualization',{})
        map_workspace = {**data['news'], 'ontology':data['ontology']}
        data['maps'] = {'variants':{policy:build_map_workspace(snapshot,map_workspace,policy)
                                   for policy in ('approximate','exact_only')},
                        'requires_position_policy':not visual.get('position_policy')}
        sources_path = self.root / 'config' / 'news_sources.json'
        data['news_sources'] = loads(sources_path.read_text(encoding='utf-8')) if sources_path.exists() else {'sources':[], 'providers':[]}
        has_live = any(a.get('mode') == 'live_metadata' for a in datasets.get('articles', {}).values())
        data.update({"mode": "live_metadata_with_verified_fixtures" if has_live else "fixture_mock", "version": __version__,
                     "capabilities": {"live_collection": sources_path.exists(), "real_ai_verified": False,
                                      "json_persistence": True, "internal_fetch": False,
                                      "backup_restore": True, "exports": True}})
        return {"data": data, "snapshot_id": snapshot["generation"], "as_of": snapshot["as_of"],
                "csrf_token": self.csrf, "warnings": [self.repo.recovery_notice] if self.repo.recovery_notice else []}

    def search_news(self, payload):
        from . import collector
        snapshot = self.repo.snapshot()
        ds = snapshot['datasets']
        resume_id = payload.get('resume_job_id')
        if resume_id:
            if not isinstance(resume_id, str) or resume_id not in ds.get('news_jobs', {}):
                raise ValueError('재개할 수집 작업을 찾을 수 없습니다.')
            prior = ds['news_jobs'][resume_id]
            if prior.get('status') in ('running','queued'):
                return {'job_id': resume_id, 'status': 'running'}
            request = dict(prior.get('request') or prior.get('filters') or {})
            if not request:
                raise ValueError('원래 검색 조건이 없습니다. 새 검색을 시작하십시오.')
            request['resume_job_id'] = resume_id
            job_id = resume_id
        else:
            request = news.normalize_filters(payload)
            # IDs are local; only the selected public name is sent as a search term.
            for field, dataset, label in (('company_id','companies','name'),('project_id','projects','name')):
                selected = request.get(field)
                if selected and selected not in ds.get(dataset, {}):
                    raise ValueError('선택 기업·사업이 존재하지 않습니다.')
            public_terms = [ds[dataset][request[field]]['name'] for field, dataset in (('company_id','companies'),('project_id','projects')) if request.get(field)]
            if public_terms:
                request['provider_query'] = ' '.join([request.get('q','')] + [term for term in public_terms if term.casefold() not in request.get('q','').casefold()]).strip()
            request['max_requests'] = payload.get('max_requests', 24)
            request['max_articles'] = payload.get('max_articles', 600)
            baseline_request = request['period']=='3y' and request['scope']=='all' and not any(request.get(key) for key in ('q','country','city','company_id','project_id'))
            purpose = payload.get('purpose','baseline_backfill' if baseline_request else 'manual')
            if purpose not in ('manual','baseline_backfill','latest_incremental'):
                raise ValueError('수집 목적이 올바르지 않습니다.')
            request['purpose'] = purpose
            job_id = 'news-job-' + uuid.uuid4().hex
        for key, maximum in (('max_requests',40), ('max_articles',1000)):
            value = request.get(key, 24 if key == 'max_requests' else 600)
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
                raise ValueError('수집 요청 상한이 올바르지 않습니다.')
            request[key] = value
        if not self.collection_lock.acquire(blocking=False):
            raise ValueError('다른 수집 작업이 진행 중입니다. 완료 후 다시 시도하십시오.')
        try:
            def queue(target):
                jobs = target.setdefault('news_jobs', {})
                prior = jobs.get(job_id, {})
                jobs[job_id] = {**prior, 'id':job_id, 'request':request, 'status':'running',
                                'created_at':prior.get('created_at',now()), 'updated_at':now(), 'cancel_requested':False}
                settings = target.setdefault('settings',{}).setdefault('app',{'id':'app'})
                first_live_search = settings.get('collection_mode') != 'live_metadata'
                settings['news_search'] = {k:v for k,v in request.items() if k not in ('resume_job_id',)}
                settings['collection_mode'] = 'live_metadata'
                if request.get('purpose') == 'baseline_backfill':
                    settings['baseline_job_id'] = job_id
                    settings['collection_source_ids'] = request.get('source_ids',[])
                if first_live_search:
                    settings['collection_enabled'] = True
                    settings.setdefault('collection_interval_minutes',60)
            self.repo.transact(queue)
        except Exception:
            self.collection_lock.release()
            raise
        def run():
            try:
                result = collector.collect_news(self.repo, self.root, request, job_id=job_id)
                def finish(target):
                    job = target['news_jobs'][job_id]
                    if job.get('status') in ('running','queued'):
                        job['status'] = result.get('status','partial')
                    job['updated_at'] = now()
                self.repo.transact(finish)
            except Exception:
                def failed(target):
                    target['news_jobs'][job_id].update(status='failed',updated_at=now(),message='외부 기사 수집을 마치지 못했습니다. 진행 상태를 보존했으며 재개할 수 있습니다.')
                self.repo.transact(failed)
            finally:
                self.collection_lock.release()
        self.news_thread = threading.Thread(target=run, name='atlas-news', daemon=True)
        self.news_thread.start()
        return {'job_id':job_id,'status':'running'}

    def collect(self):
        if not self.collection_lock.acquire(blocking=False):
            return {"status": "busy", "message": "수집 작업이 이미 실행 중입니다."}
        try:
            return pipeline.collect(self.repo, self.root)
        finally:
            self.collection_lock.release()

    def _schedule(self):
        while not self.stop.wait(15):
            try:
                ds = self.view_snapshot()["datasets"]
                settings = ds.get("settings", {}).get("app", {})
                if settings.get('collection_mode') == 'live_metadata':
                    if not self.collection_lock.locked():
                        request = self._next_news_request(ds)
                        if request:
                            self.search_news(request)
                    continue
                job = ds.get("jobs", {}).get("collection", {})
                last = job.get("last_run") or job.get("last_run_at")
                due = True
                if last:
                    due = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() >= settings.get("collection_interval_minutes", 60) * 60
                if settings.get("collection_enabled") and due:
                    if self.collection_lock.locked():
                        continue
                    self.collect()
            except Exception:
                # No endpoints, keys, original body or internal notes in error logs.
                log = self.root / "runtime" / "scheduler_error.json"
                atomic_write(log, encoded({"at": now(), "status": "collection_failed"}))

    def _next_news_request(self, ds, current_time=None):
        """Keep the global three-year baseline independent of a user's view filters."""
        settings = ds.get('settings',{}).get('app',{})
        if not settings.get('collection_enabled'):
            return None
        current_time = current_time or datetime.now(timezone.utc)
        interval = settings.get('collection_interval_minutes',60)*60
        jobs = ds.get('news_jobs',{})
        if any(j.get('status') in ('running','queued') for j in jobs.values()):
            return None
        base = {'scope':'all','q':'','source_ids':settings.get('collection_source_ids',[]),
                'max_requests':24,'max_articles':600}
        baseline = jobs.get(settings.get('baseline_job_id'))
        def due(job):
            stamp = job.get('updated_at') or job.get('created_at')
            return not stamp or (current_time-datetime.fromisoformat(stamp.replace('Z','+00:00'))).total_seconds()>=interval
        if settings.get('baseline_backfill_enabled',True):
            if not baseline:
                return {**base,'period':'3y','purpose':'baseline_backfill'}
            if baseline.get('can_resume') and due(baseline):
                return {'resume_job_id':baseline['id']}
        latest = [j for j in jobs.values() if j.get('request',{}).get('purpose')=='latest_incremental']
        if not latest or due(max(latest,key=lambda j:j.get('updated_at') or j.get('created_at') or '')):
            return {**base,'period':'1d','purpose':'latest_incremental'}
        return None

    def rebuild_index(self):
        snap = self.repo.snapshot()
        index = {"schema_version": 1, "generation": snap["generation"], "created_at": now(), "records": []}
        for dataset in ("projects", "companies", "articles"):
            for record in snap["datasets"].get(dataset, {}).values():
                index["records"].append({"dataset": dataset, "id": record["id"],
                    "text": " ".join(str(record.get(key, "")) for key in ("name", "title", "summary", "country")).lower()})
        atomic_write(self.root / "derived_index" / "search.json", encoded(index))
        return {"status": "rebuilt", "records": len(index["records"]), "generation": snap["generation"]}

    def mutate(self, operation, payload):
        if operation == 'company-classification':
            from .company_classifications import apply_company_classification
            response = {}
            def classify(ds):
                response.update(apply_company_classification(ds, payload, now()))
            snapshot = self.repo.transact(classify)
            return {'status': 'saved', 'snapshot_id': snapshot['generation'], **response}
        if operation == 'news/search':
            return self.search_news(payload)
        if operation == 'news/cancel':
            job_id = payload.get('job_id')
            def cancel(ds):
                if job_id not in ds.get('news_jobs', {}):
                    raise ValueError('수집 작업이 존재하지 않습니다.')
                ds['news_jobs'][job_id]['cancel_requested'] = True
            self.repo.transact(cancel)
            return {'status':'cancel_requested','job_id':job_id}
        if operation == "collect":
            return self.collect()
        if operation == "import":
            return pipeline.import_article(self.repo, payload)
        if operation == "index/rebuild":
            return self.rebuild_index()
        if operation == "backup":
            filename = "atlas-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6] + ".zip"
            self.repo.backup(self.root / "backups" / filename)
            return {"status": "created", "filename": filename, "url": "/api/backups/" + filename,
                    "notice": "로컬 복구용 백업에는 사내 링크와 메모가 포함될 수 있습니다."}
        if operation == "restore":
            filename = payload.get("filename", "")
            if not re.fullmatch(r"atlas-[a-zA-Z0-9-]+\.zip", filename):
                raise ValueError("백업 파일 이름이 올바르지 않습니다.")
            result = self.repo.restore(self.root / "backups" / filename)
            self.rebuild_index()
            return {"status": "restored", "snapshot_id": result["generation"]}
        if operation == "connection/test":
            api = self.repo.snapshot()["datasets"].get("settings", {}).get("app", {}).get("api", {})
            return {"status": "not_verified", "connected": False,
                    "message": "연결 프로필만 저장됩니다. 사내 프로토콜 확인 후 어댑터 구현과 실제 연결 검증이 필요합니다. 유료 API를 호출하지 않았습니다.",
                    "configured": bool(api.get("endpoint") and api.get("model"))}

        def edit(ds):
            stamp = now()
            if operation == 'attention/read':
                apply_acknowledgement(ds,payload.get('ids'),stamp)
            elif operation == "read":
                ids = payload.get("change_ids")
                if not isinstance(ids, list) or len(ids) > 1000 or any(x not in ds.get("changes", {}) for x in ids):
                    raise ValueError("읽음 처리할 변경 ID를 확인하십시오.")
                for item in ids:
                    ds.setdefault("read_states", {})[item] = {"id": item, "read_at": stamp}
            elif operation == 'news/read':
                ids = payload.get('article_ids')
                if not isinstance(ids,list) or len(ids)>2000 or any(not isinstance(a,str) or a not in ds.get('articles',{}) for a in ids):
                    raise ValueError('확인할 기사 ID가 올바르지 않습니다.')
                for update in ds.get('news_updates',{}).values():
                    if update.get('article_id') in ids:
                        ds.setdefault('news_read_states',{})[update['id']] = {'id':update['id'],'article_id':update['article_id'],'read_at':stamp}
            elif operation == "bookmarks":
                aid = payload.get("article_id")
                if aid not in ds.get("articles", {}):
                    raise ValueError("자료가 존재하지 않습니다.")
                tags = payload.get("tags", [])
                if not isinstance(tags, list) or len(tags) > 30 or any(not isinstance(x, str) or len(x) > 100 for x in tags):
                    raise ValueError("태그 형식을 확인하십시오.")
                ds.setdefault("bookmarks", {})[aid] = {"id": aid, "article_id": aid, "tags": tags,
                    "folder": limited(payload.get("folder", "스크랩"), 200), "note": limited(payload.get("note", ""), 10000), "created_at": stamp}
            elif operation.startswith("bookmarks/delete/"):
                ds.setdefault("bookmarks", {}).pop(operation.split("/", 2)[-1], None)
            elif operation == "notifications/read":
                ids = payload.get("ids", [])
                if not isinstance(ids, list) or any(x not in ds.get("notifications", {}) for x in ids):
                    raise ValueError("알림 ID를 확인하십시오.")
                for item in ids:
                    ds["notifications"][item]["read_at"] = stamp
            elif operation == "internal-links":
                company = payload.get("company_id")
                projects = payload.get("project_ids", [])
                if company not in ds.get("companies", {}) or not isinstance(projects, list) or any(x not in ds.get("projects", {}) for x in projects):
                    raise ValueError("기업 또는 사업 ID를 확인하십시오.")
                url = limited(payload.get("url", ""), 4000)
                url = assert_safe_url(url, allow_private=True)
                item_id = str(uuid.uuid4())
                ds.setdefault("internal_links", {})[item_id] = {"id": item_id, "company_id": company,
                    "project_ids": projects, "title": limited(payload.get("title", ""), 500), "url": url,
                    "document_type": limited(payload.get("document_type", "자료"), 100),
                    "authored_date": limited(payload.get("authored_date", ""), 40),
                    "user_note": limited(payload.get("user_note", ""), 10000), "visibility": "private", "created_at": stamp}
            elif operation == "settings":
                settings = ds.setdefault("settings", {}).setdefault("app", {"id": "app"})
                if 'visualization' in payload:
                    visual=payload['visualization']
                    options={'map_mode':('split','world-inset'),'position_policy':('approximate','exact_only'),
                             'ack_scope':('items','entity','screen')}
                    if not isinstance(visual,dict) or set(visual)-set(options) or any(value not in options[key] for key,value in visual.items()):
                        raise ValueError('관계도·지도 확인 설정이 올바르지 않습니다.')
                    settings['visualization']={**settings.get('visualization',{}),**visual}
                if 'collection_mode' in payload:
                    if payload['collection_mode'] not in ('live_metadata','fixture_mock'):
                        raise ValueError('수집 모드가 올바르지 않습니다.')
                    settings['collection_mode'] = payload['collection_mode']
                if "collection_enabled" in payload:
                    if not isinstance(payload["collection_enabled"], bool):
                        raise ValueError("수집 설정은 참/거짓 값이어야 합니다.")
                    settings["collection_enabled"] = payload["collection_enabled"]
                if "collection_interval_minutes" in payload:
                    value = payload["collection_interval_minutes"]
                    if not isinstance(value, int) or isinstance(value, bool) or value < 60 or value > 1440:
                        raise ValueError("실행 간격은 60~1440분입니다.")
                    settings["collection_interval_minutes"] = value
                if "digest_hour" in payload:
                    value = payload["digest_hour"]
                    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 23:
                        raise ValueError("요약 시각은 0~23시입니다.")
                    settings["digest_hour"] = value
                if "api" in payload:
                    api = payload["api"]
                    allowed = {"mode", "endpoint", "protocol", "model", "auth_type", "secret_ref", "verified"}
                    if not isinstance(api, dict) or set(api) - allowed:
                        raise ValueError("키 원문 대신 secret_ref만 입력하십시오.")
                    clean = {k: limited(v, 4000) for k, v in api.items() if k != "verified"}
                    if clean.get("secret_ref") and not re.fullmatch(r"env:[A-Z][A-Z0-9_]*", clean["secret_ref"]):
                        raise ValueError("secret_ref는 env:환경변수명 형식입니다.")
                    endpoint = clean.get("endpoint", "")
                    if endpoint:
                        assert_safe_url(endpoint, allow_private=True)
                        parsed = urlsplit(endpoint)
                        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                            raise ValueError("API 주소에는 인증정보·쿼리·조각을 넣지 마십시오.")
                    clean["verified"] = False
                    settings["api"] = {**settings.get("api", {}), **clean}
            else:
                raise ValueError("지원하지 않는 작업입니다.")
            audit_id = uuid.uuid4().hex
            ds.setdefault("audit", {})[audit_id] = {"id": audit_id, "operation": operation.split("/")[0], "at": stamp}
        result = self.repo.transact(edit)
        return {"status": "saved", "snapshot_id": result["generation"]}


def limited(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("입력 길이 또는 형식이 올바르지 않습니다.")
    return value.strip()


class AtlasServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(app, port=8765):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AIDC-ATLAS"

        def log_message(self, *_):
            pass

        def _guard(self, write=False):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host", "") not in allowed:
                self._json({"error": "Local host required"}, 403)
                return False
            origin = self.headers.get("Origin")
            if (origin and origin not in {"http://" + host for host in allowed}) or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self._json({"error": "Same-origin request required"}, 403)
                return False
            if write and not secrets.compare_digest(self.headers.get("X-Atlas-Token", ""), app.csrf):
                self._json({"error": "앱을 다시 연 뒤 저장하십시오."}, 403)
                return False
            return True

        def _send(self, raw, content_type, status=200, filename=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if filename:
                self.send_header("Content-Disposition", 'attachment; filename="' + filename + '"')
            self.end_headers()
            self.wfile.write(raw)

        def _json(self, payload, status=200):
            raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
            self._send(raw, "application/json; charset=utf-8", status)

        def do_GET(self):
            if not self._guard():
                return
            try:
                parsed = urlsplit(self.path)
                path = unquote(parsed.path)
                filters = {k:v[-1] for k,v in parse_qs(parsed.query,keep_blank_values=True).items()}
                if path == "/api/health":
                    self._json({"app": "aidc-atlas", "version": __version__, "identity": app.identity, "status": "ready"})
                elif path == '/api/session':
                    # Launcher/shutdown must not build every graph just to get a token.
                    self._json({'app':'aidc-atlas', 'version':__version__, 'identity':app.identity, 'csrf_token':app.csrf})
                elif path == "/api/state":
                    self._json(app.state(filters))
                elif path == '/api/updates':
                    raw_pointer = app._read_view_pointer()
                    with app._view_lock:
                        if app._view_error_pointer == raw_pointer:
                            raise SnapshotIntegrityError(INTEGRITY_MESSAGE)
                    pointer = loads(raw_pointer)
                    self._json({'snapshot_id': pointer['generation'], 'version': __version__})
                elif path == '/api/news':
                    snap = app.view_snapshot()
                    self._json({'data':news.build_workspace(snap,filters),'snapshot_id':snap['generation'],'as_of':snap['as_of'],'warnings':[]})
                elif path == "/api/export":
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    pids = [x for x in query["project_ids"][0].split(",") if x] if "project_ids" in query else None
                    aids = [x for x in query.get("article_ids", [""])[0].split(",") if x] or None
                    charter = loads((app.root / "config" / "product_charter.json").read_text(encoding="utf-8"))
                    kind = query.get('kind',['report'])[0]
                    if kind in ('news-report','news-csv'):
                        from .news_reports import export_workspace
                        snap = app.repo.snapshot()
                        raw,mime,filename = export_workspace(news.build_workspace(snap,filters),kind,snap['generation'])
                    else:
                        raw, mime, filename = reports.export(app.repo.snapshot(),kind, pids, aids, charter)
                    self._send(raw, mime, filename=filename)
                elif path.startswith("/api/backups/"):
                    filename = path.rsplit("/", 1)[-1]
                    if not re.fullmatch(r"atlas-[a-zA-Z0-9-]+\.zip", filename):
                        raise ValueError("Invalid backup filename")
                    self._send((app.root / "backups" / filename).read_bytes(), "application/zip", filename=filename)
                elif path == "/api/backups":
                    self._json({"data": [{"filename": p.name, "bytes": p.stat().st_size} for p in sorted((app.root / "backups").glob("atlas-*.zip"), reverse=True)]})
                elif path.startswith("/api/"):
                    self._json({"error": "API 경로가 없습니다."}, 404)
                else:
                    relative = path.lstrip("/") or "index.html"
                    base = (app.root / "frontend").resolve()
                    target = (base / relative).resolve()
                    public_map = target.is_relative_to(base / 'assets' / 'maps') and target.suffix in ('.json','.geojson')
                    if not target.is_relative_to(base) or (not public_map and target.suffix not in (".html", ".css", ".js", ".svg", ".ico")):
                        self._json({"error": "File not found"}, 404)
                        return
                    mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml",
                            '.json':'application/json','.geojson':'application/geo+json'}.get(target.suffix, "application/octet-stream")
                    self._send(target.read_bytes(), mime + "; charset=utf-8")
            except SnapshotIntegrityError:
                self._json({'error': INTEGRITY_MESSAGE, 'code': 'store_integrity_error', 'preserve_last_view': True}, 503)
            except (ValueError, KeyError, TypeError):
                self._json({"error": "요청 형식을 확인하십시오."}, 400)
            except FileNotFoundError:
                self._json({"error": "파일이 없습니다."}, 404)
            except Exception:
                self._json({"error": "로컬 저장소를 확인하십시오. 비밀정보를 로그에 기록하지 않았습니다."}, 500)

        def _write(self, operation=None):
            if not self._guard(write=True):
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Chunked request unsupported")
                if not self.headers.get("Content-Type", "").startswith("application/json"):
                    raise ValueError("JSON 입력이 필요합니다.")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= 1_000_000:
                    self._json({"error": "입력이 너무 큽니다."}, 413)
                    return
                payload = loads(self.rfile.read(size) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("JSON 객체가 필요합니다.")
                path = urlsplit(self.path).path
                if path == "/api/shutdown":
                    self._json({"data": {"status": "stopping"}})
                    app.stop.set()
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                result = app.mutate(operation or path.removeprefix("/api/"), payload)
                self._json({"data": result, "as_of": now(), "snapshot_id": app.repo.snapshot()["generation"], "warnings": []})
            except (ValueError, KeyError, TypeError) as error:
                # Validation messages are deliberately fixed; never echo untrusted body/keys.
                self._json({"error": str(error) if isinstance(error, ValueError) else "입력 형식을 확인하십시오."}, 400)
            except TimeoutError:
                self._json({"error": "저장 작업이 진행 중입니다. 잠시 뒤 다시 시도하십시오."}, 409)
            except Exception:
                self._json({"error": "저장에 실패했습니다. 원본 JSON은 이전 정상 세대를 유지합니다."}, 500)

        def do_POST(self):
            self._write()

        def do_DELETE(self):
            path = urlsplit(self.path).path
            if path.startswith("/api/bookmarks/"):
                self._write("bookmarks/delete/" + unquote(path.rsplit("/", 1)[-1]))
            else:
                self._json({"error": "Unsupported delete"}, 404)

    return AtlasServer(("127.0.0.1", port), Handler)
