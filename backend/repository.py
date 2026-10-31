"""Versioned JSON snapshots. CURRENT is the only commit point; no database needed."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .security import assert_safe_url


def now():
    return datetime.now(timezone.utc).isoformat()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def loads(raw):
    return json.loads(raw, object_pairs_hook=unique_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid JSON number")))


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class ConflictError(ValueError):
    pass


class JsonRepository:
    def __init__(self, root, publish_callback=None, *, initializer=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        self.recovery_notice = None
        # Optional delivery hint for an application cache. It never changes the
        # strict read/validation contract of snapshot, transactions or backups.
        self.publish_callback = publish_callback
        self.publish_error = None
        self.initial_snapshot = None
        with self._writer():
            if not (self.root / "CURRENT.json").exists():
                if (self.root / "PREVIOUS.json").exists():
                    self._recover()
                elif any((self.root / "generations").glob("*/manifest.json")):
                    raise ValueError("CURRENT missing; restore a verified backup. Uncommitted generations are not activated.")
                else:
                    self._commit({}, parent=None)
            try:
                current = self._read()
            except (OSError, ValueError, KeyError, TypeError):
                self._recover()
                current = self._read() if initializer is not None else None
            if initializer is not None:
                # Initialization and migration share this writer lock and the
                # exact snapshot just checksum-verified above. No detached cache
                # or trust-by-mtime is used for a write. Ordinary transactions
                # and recovery retain their existing strict reads.
                datasets = copy.deepcopy(current['datasets'])
                initializer(datasets)
                if datasets != current['datasets']:
                    current = self._commit(datasets, current['generation'], current)
                self.initial_snapshot = current

    @contextmanager
    def _writer(self):
        with self._thread_lock:
            lock = self.root / "writer.lock"
            with lock.open("a+b") as handle:
                handle.seek(0, 2)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                deadline = time.monotonic() + 10
                while True:
                    try:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("JSON writer is busy")
                        time.sleep(0.025)
                try:
                    yield
                finally:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self, pointer=None, *, workers=None, reuse_snapshot=None):
        pointer = pointer or loads((self.root / "CURRENT.json").read_text(encoding="utf-8"))
        generation = pointer["generation"]
        if not re.fullmatch(r"[0-9a-f]{32}", generation):
            raise ValueError("Invalid generation")
        folder = self.root / "generations" / generation
        manifest_raw = (folder / "manifest.json").read_bytes()
        if digest(manifest_raw) != pointer["manifest_sha256"]:
            raise ValueError("Manifest checksum mismatch")
        manifest = loads(manifest_raw)
        if manifest["schema_version"] != 1 or manifest["generation"] != generation:
            raise ValueError("Unsupported snapshot schema")
        reuse = reuse_snapshot is not None and reuse_snapshot.get('generation') == generation
        datasets = reuse_snapshot['datasets'] if reuse else {}
        if reuse and set(datasets) != set(manifest['datasets']):
            raise ValueError('Cached dataset identity mismatch')
        entries = []
        for dataset, records in manifest["datasets"].items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", dataset):
                raise ValueError("Invalid dataset")
            if reuse:
                if set(datasets[dataset]) != set(records):
                    raise ValueError('Cached record identity mismatch')
            else:
                datasets[dataset] = {}
            for entity_id, ref in records.items():
                filename = ref["file"]
                if not re.fullmatch(r"[0-9a-f]{64}\.json", filename):
                    raise ValueError("Invalid record path")
                record_generation = ref.get('generation', generation)
                if not re.fullmatch(r'[0-9a-f]{32}',record_generation):
                    raise ValueError('Invalid record generation')
                entries.append((dataset, entity_id, record_generation, filename, ref['sha256']))

        def checked_record(entry):
            dataset, entity_id, record_generation, filename, expected_hash = entry
            raw = (self.root / 'generations' / record_generation / dataset / filename).read_bytes()
            if digest(raw) != expected_hash:
                raise ValueError("Record checksum mismatch")
            item = loads(raw)
            if item["entity_id"] != entity_id or item["dataset"] != dataset or item["schema_version"] != 1:
                raise ValueError("Record identity/schema mismatch")
            if reuse:
                if item['payload'] != datasets[dataset][entity_id]:
                    raise ValueError('Cached record payload mismatch')
                # All bytes, JSON and envelope checks still execute. Retain only
                # the already-owned immutable payload, not a second full archive.
                return dataset, entity_id, None
            return dataset, entity_id, item['payload']

        parallelism = 8 if workers is None and len(entries) >= 1000 else workers or 1
        if not isinstance(parallelism, int) or not 1 <= parallelism <= 8:
            raise ValueError('Invalid checksum reader count')
        if parallelism > 1:
            from concurrent.futures import ThreadPoolExecutor
            # Bounded queue, deterministic assembly, same checks on every file.
            # Immutable generation records are never modified by reader workers.
            with ThreadPoolExecutor(max_workers=parallelism, thread_name_prefix='atlas-json-check') as executor:
                for offset in range(0, len(entries), 256):
                    for dataset, entity_id, payload in executor.map(checked_record, entries[offset:offset + 256]):
                        if not reuse:
                            datasets[dataset][entity_id] = payload
        else:
            for entry in entries:
                dataset, entity_id, payload = checked_record(entry)
                if not reuse:
                    datasets[dataset][entity_id] = payload
        self.validate(datasets)
        return {"generation": generation, "as_of": manifest["created_at"], "datasets": datasets}

    def _recover(self):
        previous_raw = (self.root / "PREVIOUS.json").read_bytes()
        previous = loads(previous_raw)
        self._read(previous)
        atomic_write(self.root / "CURRENT.json", previous_raw)
        self.recovery_notice = "손상된 현재 세대 대신 검증된 직전 세대를 복구했습니다."

    def snapshot(self):
        return self._read()

    def revalidate_snapshot(self, owned_snapshot):
        """Strictly reread every object; share only an exact verified cache.

        The caller owns this read-only snapshot. A changed generation takes the
        ordinary full path. Checksums, JSON, schemas and references are not skipped.
        """
        return self._read(reuse_snapshot=owned_snapshot)

    def _publish_verified(self, snapshot, pointer_raw):
        if self.publish_callback is None:
            return
        try:
            # A consumer cannot mutate the object returned by transact or the
            # writer's verified data. Callback failure cannot roll back CURRENT.
            self.publish_callback(copy.deepcopy(snapshot), bytes(pointer_raw))
            self.publish_error = None
        except Exception:
            self.publish_error = 'Verified snapshot cache publication failed; strict reads remain available.'

    @staticmethod
    def validate(datasets):
        if not isinstance(datasets, dict):
            raise ValueError("Datasets must be objects")
        # Validation needs strict JSON, not the indented on-disk representation.
        # Large collection checkpoints otherwise spend seconds formatting discarded text.
        for dataset, records in datasets.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", dataset) or not isinstance(records, dict):
                raise ValueError("Invalid dataset")
            for entity_id, record in records.items():
                if not isinstance(entity_id, str) or not isinstance(record, dict) or record.get("id") != entity_id:
                    raise ValueError("Records require matching stable IDs")
                # Validate strict JSON record by record without allocating one
                # giant serialized copy of a large multi-year article archive.
                json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        for dataset, field, target in [
            ("changes", "project_id", "projects"), ("claims", "project_id", "projects"),
            ("claims", "article_id", "articles"), ("relationships", "project_id", "projects"),
            ("relationships", "company_id", "companies"), ("bookmarks", "article_id", "articles"),
            ("notifications", "change_id", "changes"), ("internal_links", "company_id", "companies")
            , ("news_updates","article_id","articles"), ("news_read_states","article_id","articles")
            , ("project_mentions", "article_id", "articles"), ("company_mentions", "article_id", "articles")
            , ('company_classifications', 'company_id', 'companies')
            , ('company_classification_history', 'company_id', 'companies')
        ]:
            for record in datasets.get(dataset, {}).values():
                ref = record.get(field)
                if ref is not None and (not isinstance(ref, str) or ref not in datasets.get(target, {})):
                    raise ValueError("Dangling reference: " + dataset + "." + field)
        if datasets.get('dart_reports'):
            from .dart_company import validate_report
            for record in datasets['dart_reports'].values():
                validate_report(record)
                if record.get('company_id') not in datasets.get('companies', {}) or record.get('identity_confirmed') is not True:
                    raise ValueError('Invalid DART company reference or identity confirmation')
        def check_ref(value, target, location):
            if not isinstance(value, str) or value not in datasets.get(target, {}):
                raise ValueError("Dangling reference: " + location)
        def check_list(record, field, target, location):
            if field not in record:
                return
            values = record[field]
            if not isinstance(values, list):
                raise ValueError("Reference list required: " + location)
            for value in values:
                check_ref(value, target, location)
        for dataset, field, target in [
            ("projects", "company_ids", "companies"), ("projects", "article_ids", "articles"),
            ("companies", "project_ids", "projects"), ("articles", "project_ids", "projects"),
            ("relationships", "article_ids", "articles"), ("relationships", "claim_ids", "claims"),
            ("changes", "article_ids", "articles"), ("internal_links", "project_ids", "projects"),
            ("extraction_runs", "article_ids", "articles"), ("notifications", "article_ids", "articles")
            , ("articles","company_ids","companies"), ("articles","candidate_project_ids","projects")
            , ("news_updates","company_ids","companies"), ("news_updates","project_ids","projects")
        ]:
            for record in datasets.get(dataset, {}).values():
                check_list(record, field, target, dataset + "." + field)
        for dataset, field, target in [
            ("notifications", "project_id", "projects"),
            ("extraction_runs", "article_id", "articles")
        ]:
            for record in datasets.get(dataset, {}).values():
                if record.get(field) is not None:
                    check_ref(record[field], target, dataset + "." + field)
        if datasets.get('project_identity_groups'):
            from .project_identity import validate_records
            validate_records(datasets)
        if datasets.get('article_scope_decisions') or datasets.get('company_identity_groups') or datasets.get('project_scope_decisions'):
            from .ai_cleanup import validate_records
            validate_records(datasets)
        # Strategy JSON is durable evidence, with the same reference guarantees
        # as bookmarks and project relationships. Default board is virtual.
        from . import strategy
        for board in datasets.get('strategy_boards', {}).values():
            strategy.save_board({}, board)
        strategy_boards = {b['id']: b for b in strategy.boards(datasets)}
        for summary in datasets.get('strategy_summaries', {}).values():
            board = strategy_boards.get(summary.get('board_id'))
            if not board or summary.get('company_id') not in {c['id'] for c in board['companies']} or summary.get('row_id') not in {r['id'] for r in board['rows']}:
                raise ValueError('Dangling strategy board/company/row reference')
            check_list(summary, 'article_ids', 'articles', 'strategy_summaries.article_ids')
            for paragraph in summary.get('paragraphs', []):
                if not isinstance(paragraph, dict) or paragraph.get('article_id') not in summary.get('article_ids', []):
                    raise ValueError('Dangling strategy paragraph source')
        for record in datasets.get("articles", {}).values():
            for field in ("url", "canonical_url"):
                if field in record:
                    assert_safe_url(record[field])
        for record in datasets.get("internal_links", {}).values():
            if "url" in record:
                assert_safe_url(record["url"], allow_private=True)
        from .company_classifications import validate_categories
        for cid, record in datasets.get('company_classifications', {}).items():
            if cid != record.get('company_id'):
                raise ValueError('Company classification identity mismatch')
            validate_categories(record.get('categories'))
            if not isinstance(record.get('note', ''), str) or len(record.get('note', '')) > 1000:
                raise ValueError('Invalid company classification note')
            check_ref(record.get('history_id'), 'company_classification_history', 'company_classifications.history_id')
            if datasets['company_classification_history'][record['history_id']]['company_id'] != cid:
                raise ValueError('Classification history belongs to a different company')
        for record in datasets.get('company_classification_history', {}).values():
            if record.get('operation') not in ('set', 'reset'):
                raise ValueError('Invalid company classification operation')
            for side in ('previous', 'current'):
                value = record.get(side)
                if value is not None:
                    if not isinstance(value, dict) or value.get('company_id') != record['company_id']:
                        raise ValueError('Invalid company classification history state')
                    validate_categories(value.get('categories'))
        for record in datasets.get("read_states", {}).values():
            if record["id"] not in datasets.get("changes", {}):
                raise ValueError("Unknown read-state change")
        for record in datasets.get('news_read_states',{}).values():
            if record['id'] not in datasets.get('news_updates',{}):
                raise ValueError('Unknown news read-state update')
        for record in datasets.get("projects", {}).values():
            history = record.get("capacity_history", [])
            if not isinstance(history, list) or any(not isinstance(item, dict) for item in history):
                raise ValueError("Capacity history list required")
            for revision in history:
                for side in ("previous", "candidate"):
                    fact = revision.get(side)
                    if not isinstance(fact, dict):
                        raise ValueError("Capacity history requires previous and candidate facts")
                    if fact.get("claim_id") is not None:
                        check_ref(fact["claim_id"], "claims", "projects.capacity_history.claim_id")
                        if datasets["claims"][fact["claim_id"]].get("project_id") != record["id"]:
                            raise ValueError("Historical capacity claim belongs to another project")
            for collection in ("capacities", "milestones"):
                items = record.get(collection, [])
                if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                    raise ValueError("Project capacity/milestone lists required")
                for item in items:
                    for field, target in (("claim_id", "claims"), ("article_id", "articles")):
                        if item.get(field) is not None:
                            check_ref(item[field], target, "projects." + collection + "." + field)
                    for field, target in (("claim_ids", "claims"), ("article_ids", "articles")):
                        check_list(item, field, target, "projects." + collection + "." + field)
                    if item.get("claim_id") is not None:
                        claim = datasets["claims"][item["claim_id"]]
                        if claim.get("project_id") != record["id"]:
                            raise ValueError("Capacity/milestone claim belongs to a different project")
            parent = record.get("parent_id")
            if parent is not None and (not isinstance(parent, str) or parent not in datasets.get("projects", {})):
                raise ValueError("Unknown parent project")
            visited = {record["id"]}
            while parent:
                if parent in visited:
                    raise ValueError("Cyclic project hierarchy")
                visited.add(parent)
                parent = datasets["projects"][parent].get("parent_id")

    def _commit(self, datasets, parent, previous_snapshot=None):
        self.validate(datasets)
        generation = uuid.uuid4().hex
        folder = self.root / "generations" / generation
        manifest = {"schema_version": 1, "generation": generation, "parent": parent,
                    "created_at": now(), "datasets": {}}
        old = (previous_snapshot or self._read())["datasets"] if parent else {}
        old_manifest = loads((self.root / 'generations' / parent / 'manifest.json').read_bytes()) if parent else {'datasets':{}}
        for dataset, records in sorted(datasets.items()):
            manifest["datasets"][dataset] = {}
            for entity_id, payload in sorted(records.items()):
                previous_payload = old.get(dataset, {}).get(entity_id)
                previous_ref = old_manifest['datasets'].get(dataset,{}).get(entity_id)
                if previous_ref and previous_payload == payload:
                    # Reuse immutable record versions rather than copying every article on each checkpoint.
                    manifest['datasets'][dataset][entity_id] = {**previous_ref,'generation':previous_ref.get('generation',parent)}
                    continue
                record_version = 1
                if previous_payload is not None:
                    if previous_ref:
                        record_parent = previous_ref.get('generation',parent)
                        previous_item = loads((self.root / "generations" / record_parent / dataset / previous_ref["file"]).read_bytes())
                        record_version = previous_item["record_version"] + int(previous_payload != payload)
                envelope = {"schema_version": 1, "dataset": dataset, "entity_id": entity_id,
                            "record_version": record_version, "payload": payload}
                raw = encoded(envelope)
                filename = digest(entity_id.encode("utf-8")) + ".json"
                atomic_write(folder / dataset / filename, raw)
                manifest["datasets"][dataset][entity_id] = {"file": filename, "sha256": digest(raw), 'generation':generation}
        raw_manifest = encoded(manifest)
        atomic_write(folder / "manifest.json", raw_manifest)
        pointer = {"schema_version": 1, "generation": generation, "manifest_sha256": digest(raw_manifest)}
        # Verify every staged object before activating the generation.
        verified = self._read(pointer)
        current = self.root / "CURRENT.json"
        if current.exists():
            atomic_write(self.root / "PREVIOUS.json", current.read_bytes())
        pointer_raw = encoded(pointer)
        atomic_write(current, pointer_raw)
        self._publish_verified(verified, pointer_raw)
        return verified

    def transact(self, mutator, expected_generation=None):
        with self._writer():
            current = self._read()
            if expected_generation and current["generation"] != expected_generation:
                raise ConflictError("Snapshot changed; reload before saving")
            datasets = copy.deepcopy(current["datasets"])
            mutator(datasets)
            if datasets == current["datasets"]:
                self._publish_verified(current, (self.root / 'CURRENT.json').read_bytes())
                return current
            return self._commit(datasets, current["generation"], current)

    def backup(self, destination):
        snapshot = self.snapshot()
        raw = encoded({"schema_version": 1, "snapshot": snapshot})
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("snapshot.json", raw)
            archive.writestr("sha256.txt", digest(raw))
        return destination

    def restore(self, archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            if set(archive.namelist()) != {"snapshot.json", "sha256.txt"}:
                raise ValueError("Unsupported backup layout")
            if archive.getinfo("snapshot.json").file_size > 50_000_000:
                raise ValueError("Backup is too large")
            raw = archive.read("snapshot.json")
            if digest(raw) != archive.read("sha256.txt").decode("ascii"):
                raise ValueError("Backup checksum mismatch")
            payload = loads(raw)
            if payload["schema_version"] != 1:
                raise ValueError("Backup migration required")
            datasets = payload["snapshot"]["datasets"]
            self.validate(datasets)
        def replace(target):
            target.clear()
            target.update(datasets)
        return self.transact(replace)
