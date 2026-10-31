import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from backend.dart_company import DartCompany, DartVault, official_request, registry_candidates
from backend.repository import JsonRepository


class Vault:
    def __init__(self): self.value = None
    def read(self, _): return self.value
    def write(self, _, value): self.value = value
    def delete(self, _): self.value = None


class DartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = JsonRepository(self.tmp.name)
        def seed(ds):
            ds['companies'] = {'c': {'id': 'c', 'name': '테스트 건설사'}}
            ds['bookmarks'] = {}
        self.repo.transact(seed)
        self.vault, self.calls, self.tick = Vault(), [], 0
        self.vault.value = 'a' * 40
        self.dart = DartCompany(self.repo, 'test', self.repo.snapshot, self.vault, self.fetch, lambda: self.tick)
        self.payload = {'company_id': 'c', 'corp_code': '00000001', 'year': '2025', 'report_code': '11011', 'fs_div': 'CFS'}

    def tearDown(self): self.tmp.cleanup()

    def fetch(self, endpoint, params, key):
        self.calls.append((endpoint, params))
        if endpoint == 'company.json':
            return {'corp_name': '공식 테스트 법인', 'corp_code': params['corp_code'], 'stock_code': '000001'}
        return {'list': [{'corp_code': params['corp_code'], 'bsns_year': params['bsns_year'], 'reprt_code': params['reprt_code'],
                 'fs_div': 'CFS', 'account_nm': '매출액', 'thstrm_nm': '제 10 기', 'thstrm_amount': '-1,500',
                 'thstrm_add_amount': '', 'currency': 'KRW', 'rcept_no': '20260301000001'}]}

    def test_preview_no_store_write_two_calls_and_no_key_in_output(self):
        before = self.repo.snapshot()
        p = self.dart.preview(self.payload)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(before, self.repo.snapshot())
        self.assertNotIn(self.vault.value, json.dumps(p))
        self.assertEqual(p['report']['accounts'][0]['thstrm_amount'], '-1,500')
        self.assertEqual(p['report']['accounts'][0]['thstrm_add_amount'], '')
        self.assertEqual(p['ai_tokens'], 0)

    def test_confirm_save_is_durable_preserves_business_datasets(self):
        before = self.repo.snapshot()['datasets']
        p = self.dart.preview(self.payload)
        body = {'preview_id': p['preview_id'], 'confirm_same_legal_entity': True}
        saved = self.dart.save(body)
        ds = JsonRepository(self.tmp.name).snapshot()['datasets']
        self.assertTrue(ds['dart_reports'][saved['report_id']]['identity_confirmed'])
        for key, value in before.items(): self.assertEqual(value, ds[key])
        self.dart.save(body)
        self.assertEqual(len(self.repo.snapshot()['datasets']['dart_reports']), 1)

    def test_confirmation_required_and_expiry(self):
        p = self.dart.preview(self.payload)
        with self.assertRaises(ValueError): self.dart.save({'preview_id': p['preview_id'], 'confirm_same_legal_entity': False})
        self.tick = 601
        with self.assertRaises(ValueError): self.dart.save({'preview_id': p['preview_id'], 'confirm_same_legal_entity': True})
        self.assertNotIn('dart_reports', self.repo.snapshot()['datasets'])

    def test_no_cfs_to_ofs_or_period_fallback(self):
        with self.assertRaises(ValueError): self.dart.preview({**self.payload, 'fs_div': 'OFS'})
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn('dart_reports', self.repo.snapshot()['datasets'])

    def test_company_changed_after_preview_prevents_save(self):
        p = self.dart.preview(self.payload)
        self.repo.transact(lambda ds: ds['companies']['c'].update(name='다른 회사'))
        with self.assertRaises(ValueError): self.dart.save({'preview_id': p['preview_id'], 'confirm_same_legal_entity': True})

    def test_cannot_replace_child_with_parent(self):
        first = self.dart.preview(self.payload)
        self.dart.save({'preview_id': first['preview_id'], 'confirm_same_legal_entity': True})
        second = self.dart.preview({**self.payload, 'corp_code': '00000002'})
        with self.assertRaises(ValueError): self.dart.save({'preview_id': second['preview_id'], 'confirm_same_legal_entity': True})

    def test_strict_repository_rejects_forged_source_and_dangling_company(self):
        p = self.dart.preview(self.payload)
        self.dart.save({'preview_id': p['preview_id'], 'confirm_same_legal_entity': True})
        ds = self.repo.snapshot()['datasets']
        report = next(iter(ds['dart_reports'].values()))
        report['accounts'][0]['source_url'] = 'https://evil.example/?key=SECRET'
        with self.assertRaises(ValueError): JsonRepository.validate(ds)
        ds = self.repo.snapshot()['datasets']
        next(iter(ds['dart_reports'].values()))['company_id'] = 'missing'
        with self.assertRaises(ValueError): JsonRepository.validate(ds)

    def test_missing_key_and_invalid_period_make_no_network_call(self):
        self.vault.value = None
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError): self.dart.preview(self.payload)
        for body in ({**self.payload, 'year': '9999'}, {**self.payload, 'corp_code': 'X'}, {**self.payload, 'endpoint': 'evil'}):
            with self.assertRaises(ValueError): self.dart.preview(body)
        self.assertEqual(self.calls, [])

    def test_vault_registration_has_no_json_key_and_environment_is_not_deleted(self):
        self.dart.connect({'api_key': 'b' * 40})
        self.assertNotIn('b' * 40, json.dumps(self.repo.snapshot()))
        with patch.dict(os.environ, {'DART_API_KEY': 'c' * 40}):
            self.assertEqual(self.dart.key(), 'b' * 40)
            self.vault.value = None
            self.assertEqual(self.dart.key(), 'c' * 40)
        self.assertIn(':dart', DartVault('test')._target('dart'))

    def test_transport_uses_fixed_host_redacts_exception_no_retry(self):
        with patch('backend.dart_company.request_bytes', side_effect=OSError('SECRET-BEARING-URL')) as call:
            with self.assertRaises(ValueError) as error: official_request('company.json', {'corp_code': '00000001'}, 'PRIVATE-KEY')
        self.assertNotIn('PRIVATE', str(error.exception))
        self.assertNotIn('SECRET', str(error.exception))
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.kwargs['allowed_hosts'], {'opendart.fss.or.kr'})
        with self.assertRaises(ValueError): official_request('https://evil.example', {}, 'PRIVATE')

    def test_official_no_data_or_key_errors_are_not_saved(self):
        with patch('backend.dart_company.request_bytes', return_value=b'{"status":"013","message":"RAW-SECRET"}'):
            with self.assertRaises(ValueError) as error: official_request('company.json', {}, 'PRIVATE')
        self.assertNotIn('RAW', str(error.exception))
        self.assertNotIn('dart_reports', self.repo.snapshot()['datasets'])

    def test_workspace_read_never_calls_network_or_acknowledges(self):
        before = self.repo.snapshot()
        data = self.dart.workspace(before['datasets'], 'c')
        self.assertEqual(data['reports'], [])
        self.assertFalse(data['latest_available_period_verified'])
        self.assertEqual(before, self.repo.snapshot())
        self.assertEqual(self.calls, [])

    def test_existing_dart_registry_is_only_an_explicit_choice_candidate(self):
        data = registry_candidates('삼성전자')
        self.assertTrue(any(c['name'] == '삼성전자' and c['corp_code'] == '00126380' for c in data['candidates']))
        self.assertIn('2026-10-04', data['registry_as_of'])
        self.assertEqual(registry_candidates('존재하지않는해외사업법인XYZ')['candidates'], [])
        self.assertEqual(registry_candidates('')['candidates'], [])
        self.assertLessEqual(len(registry_candidates('현대')['candidates']), 20)
        self.assertEqual(self.calls, [])

    def test_explicit_withdraw_keeps_original_and_allows_manual_identity_correction(self):
        preview = self.dart.preview(self.payload)
        saved = self.dart.save({'preview_id': preview['preview_id'], 'confirm_same_legal_entity': True})
        with self.assertRaises(ValueError): self.dart.withdraw({'company_id': 'c', 'report_id': saved['report_id'], 'confirm_withdraw': False})
        self.dart.withdraw({'company_id': 'c', 'report_id': saved['report_id'], 'confirm_withdraw': True})
        with self.assertRaises(ValueError): self.dart.save({'preview_id': preview['preview_id'], 'confirm_same_legal_entity': True})
        ds = self.repo.snapshot()['datasets']
        self.assertEqual(ds['dart_reports'][saved['report_id']]['corp_code'], '00000001')
        self.assertEqual(self.dart.workspace(ds, 'c')['reports'], [])
        self.assertEqual(len(self.dart.workspace(ds, 'c')['withdrawn_reports']), 1)
        second = self.dart.preview({**self.payload, 'corp_code': '00000002'})
        self.dart.save({'preview_id': second['preview_id'], 'confirm_same_legal_entity': True})
        self.assertEqual(len(self.repo.snapshot()['datasets']['dart_reports']), 2)
