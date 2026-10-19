from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from backend.company_classifications import apply_company_classification
from backend.company_profiles import build_company_profile, profile_fields
from backend.company_catalog import build_company_catalog
from backend.ontology import build_ontology
from backend.project_discovery import enrich_discovery
from backend.repository import JsonRepository


class CompanyClassificationTests(unittest.TestCase):
    def datasets(self):
        article = {'id': 'a', 'title': '한빛건설 울산 AI 데이터센터 현장 점검',
            'url': 'https://example.org/a', 'published_at': '2026-10-18',
            'company_ids': ['c'], 'project_ids': [], 'domain_relevance': {'status': 'relevant'},
            'scope_classification': {'primary_scope': 'kr-ai'}}
        return {'companies': {'c': {'id': 'c', 'name': '한빛건설'}}, 'articles': {'a': article},
            'projects': {}, 'relationships': {}, 'read_states': {}, 'news_read_states': {}, 'bookmarks': {}}

    def test_user_priority_multicategory_reset_and_append_only_history(self):
        ds = self.datasets()
        enrich_discovery(ds, ['a'])
        protected = deepcopy({key: ds[key] for key in ('projects', 'relationships', 'read_states', 'news_read_states', 'bookmarks')})
        result = apply_company_classification(ds, {'company_id': 'c', 'categories': ['operator', 'developer'], 'note': '분류 메모'}, 't1')
        self.assertEqual(result['profile_categories'], ['developer', 'operator'])
        self.assertTrue(result['company_profile']['manual_override'])
        self.assertEqual(result['company_profile']['automatic_profile']['categories'], ['contractor'])
        original_history = deepcopy(ds['company_classification_history'])
        apply_company_classification(ds, {'company_id': 'c', 'categories': ['unknown']}, 't2')
        for key, value in original_history.items():
            self.assertEqual(ds['company_classification_history'][key], value)
        reset = apply_company_classification(ds, {'company_id': 'c', 'reset': True}, 't3')
        self.assertEqual(reset['profile_categories'], ['contractor'])
        self.assertFalse(reset['company_profile']['manual_override'])
        self.assertIsNone(reset['manual_classification'])
        self.assertEqual(len(ds['company_classification_history']), 3)
        self.assertEqual(len(ds['audit']), 3)
        self.assertEqual(protected, {key: ds[key] for key in protected})

    def test_catalog_ontology_and_reanalysis_preserve_user_nature_but_never_role(self):
        ds = self.datasets()
        apply_company_classification(ds, {'company_id': 'c', 'categories': ['designer']}, 't')
        enrich_discovery(ds, ['a'])
        workspace = {'articles': list(ds['articles'].values()), 'filters': {}}
        source = {'articles': workspace['articles'], 'companies': ds['companies']}
        for company in [build_company_catalog(ds, workspace, source)['companies'][0], build_ontology(ds, workspace)['companies'][0]]:
            self.assertEqual(company['profile_categories'], ['designer'])
            self.assertTrue(company['company_profile']['manual_override'])
            self.assertEqual(company['roles'], ['unknown'])
        self.assertEqual(ds['relationships'], {})

    def test_invalid_payload_is_atomic_before_any_dataset_mutation(self):
        payloads = [
            {'company_id': 'missing', 'categories': ['operator']},
            {'company_id': 'c', 'categories': []}, {'company_id': 'c', 'categories': ['fake']},
            {'company_id': 'c', 'categories': ['unknown', 'tenant']},
            {'company_id': 'c', 'categories': ['operator', 'operator']},
            {'company_id': 'c', 'categories': ['operator'], 'role': 'contractor'},
            {'company_id': 'c', 'reset': 'true'},
            {'company_id': 'c', 'reset': True, 'categories': ['tenant']},
            {'company_id': 'c', 'categories': ['tenant'], 'note': 'x' * 1001}]
        for payload in payloads:
            with self.subTest(payload=payload):
                ds = self.datasets()
                before = deepcopy(ds)
                with self.assertRaises(ValueError):
                    apply_company_classification(ds, payload, 't')
                self.assertEqual(ds, before)

    def test_json_reload_backup_restore_keeps_manual_choices_and_history(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = JsonRepository(Path(folder) / 'store')
            repo.transact(lambda ds: ds.update(self.datasets()))
            repo.transact(lambda ds: apply_company_classification(ds, {'company_id': 'c', 'categories': ['tenant', 'operator']}, 't1'))
            expected = repo.snapshot()['datasets']
            backup = Path(folder) / 'backup.zip'
            repo.backup(backup)
            repo.transact(lambda ds: apply_company_classification(ds, {'company_id': 'c', 'reset': True}, 't2'))
            repo.restore(backup)
            restored = JsonRepository(Path(folder) / 'store').snapshot()['datasets']
            self.assertEqual(restored['company_classifications'], expected['company_classifications'])
            self.assertEqual(restored['company_classification_history'], expected['company_classification_history'])

    def test_repository_rejects_dangling_or_cross_company_classification_history(self):
        ds = self.datasets()
        apply_company_classification(ds, {'company_id': 'c', 'categories': ['operator']}, 't')
        JsonRepository.validate(ds)
        del ds['company_classification_history'][ds['company_classifications']['c']['history_id']]
        with self.assertRaises(ValueError):
            JsonRepository.validate(ds)

    def test_official_registry_uses_exact_alias_and_never_establishes_project_role(self):
        for name, category in [('AWS', 'operator'), ('엔비디아', 'equipment_supplier'), ('LG CNS', 'operator')]:
            result = build_company_profile({'id': 'c', 'name': name})
            self.assertIn(category, result['profile_categories'])
            evidence = next(item for item in result['profile_evidence'] if item['basis'] == 'official_company_profile_registry')
            self.assertEqual(evidence['status'], 'official_business_nature')
            self.assertTrue(evidence['evidence']['source_url'].startswith('https://'))
            self.assertTrue(result['company_profile']['project_role_separate'])
        self.assertEqual(build_company_profile({'id': 'c', 'name': 'AWS 신설자회사'})['profile_categories'], ['unknown'])
        self.assertEqual(build_company_profile({'id': 'c', 'name': '아마존'})['profile_categories'], ['unknown'])

    def test_explicit_stored_description_and_ambiguous_description(self):
        explicit = build_company_profile({'id': 'c', 'name': '한빛', 'descriptor': '데이터센터 운영사 및 장비 공급업체'})
        self.assertEqual(explicit['profile_categories'], ['operator', 'equipment_supplier'])
        ambiguous = build_company_profile({'id': 'c', 'name': '한빛', 'summary': '운영사가 아닌 회사'})
        self.assertEqual(ambiguous['profile_categories'], ['unknown'])
        supplier_context = build_company_profile({'id': 'c', 'name': '한빛', 'summary': '운영사에 장비 공급 서비스를 제공한다'})
        self.assertEqual(supplier_context['profile_categories'], ['unknown'])


if __name__ == '__main__':
    unittest.main()
