"""REV015 real nested project observations and public-only comparison targets."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend.ai_analysis import (comparison_target, comparison_targets, decide_match,
                                 prepare_analysis, public_article, shortlist, validate_result, SYSTEM)
from backend.project_discovery import _stamp, analyse_article
from backend.repository import JsonRepository


def article(ident, title='용인 테스트 AI 데이터센터 투자 계획', **fields):
    return {'id': ident, 'title': title, 'mode': 'live_metadata',
            'url': 'https://example.com/' + ident, 'publisher': '테스트 공개매체',
            'published_at': '2026-10-26T00:00:00Z', 'feed_excerpt': '', **fields}


def record(source, ident='nested-1', phase=None):
    mention = {'id': ident, 'article_id': source['id'], 'article_ids': [source['id']],
               'name': '용인 테스트 AI 데이터센터', 'cities': ['용인'],
               'note': 'PRIVATE-NESTED-NOTE', 'company_observations': [{'note': 'PRIVATE-COMPANY-NOTE'}]}
    if phase is not None:
        mention['phase'] = phase
    return {'id': source['id'], 'article_id': source['id'], 'source_hash': _stamp(source), 'mentions': [mention]}


class IdentityTargetTests(unittest.TestCase):
    def setUp(self):
        self.source = article('old')
        self.selected = article('new', '용인 테스트 AI 데이터센터 증설 검토')
        self.ds = {'articles': {'old': self.source, 'new': self.selected},
                   'project_mentions': {'old': record(self.source)}}

    def targets(self, ds=None):
        return shortlist(ds or self.ds, [public_article(self.selected)])

    def test_actual_extractor_shape_is_included_with_stable_nested_id(self):
        extracted = analyse_article(self.source)
        self.assertTrue(extracted['mentions'])
        self.ds['project_mentions']['old'] = extracted
        target = self.targets()[0]
        self.assertEqual(target['id'], 'mention:' + extracted['mentions'][0]['id'])
        self.assertEqual(target['source_article_ids'], ['old'])
        self.assertEqual(comparison_target(self.ds, target['id']), target)

    def test_nested_safe_fields_only_and_no_private_source_ids(self):
        self.ds['articles']['private'] = article('private', visibility='private')
        mention = self.ds['project_mentions']['old']['mentions'][0]
        mention.update(program='공개 프로그램', site='공개 부지', phase='1단계',
                       location='용인시', internal_links=['PRIVATE-INTERNAL-LINK'],
                       article_ids=['private', 'old'], extra={'note': 'PRIVATE-EXTRA'})
        target = self.targets()[0]
        self.assertEqual(target['source_article_ids'], ['old'])
        self.assertEqual((target['program'], target['site'], target['phase'], target['location']),
                         ('공개 프로그램', '공개 부지', '1단계', '용인시'))
        self.assertNotIn('PRIVATE-', json.dumps(target))
        self.assertNotIn('private', json.dumps(target))

    def test_stale_record_and_private_manual_sources_excluded(self):
        for mode, visibility, stamp in [('live_metadata', 'public', 'stale'),
                                        ('live_metadata', 'private', None), ('manual', 'public', None),
                                        ('live_metadata', 'internal', None)]:
            ds = copy.deepcopy(self.ds)
            ds['articles']['old'].update(mode=mode, visibility=visibility)
            if stamp:
                ds['project_mentions']['old']['source_hash'] = stamp
            with self.subTest(mode=mode, visibility=visibility):
                self.assertEqual(self.targets(ds), [])

    def test_unstamped_nested_requires_current_title_name(self):
        self.ds['project_mentions']['old'].pop('source_hash')
        self.assertEqual(len(self.targets()), 1)
        self.ds['project_mentions']['old']['mentions'][0]['name'] = '용인 공개 근거 없는 데이터센터'
        self.assertEqual(self.targets(), [])

    def test_own_selected_nested_observation_excluded(self):
        self.ds['project_mentions']['new'] = record(self.selected, 'selected-own')
        ids = [target['id'] for target in self.targets()]
        self.assertIn('mention:nested-1', ids)
        self.assertNotIn('mention:selected-own', ids)

    def test_conflicting_phases_or_sites_are_not_grouped(self):
        items = self.ds['project_mentions']['old']['mentions']
        items[0].update(phase='1단계', site='부지A')
        items.append({**items[0], 'id': 'nested-2', 'phase': '2단계'})
        items.append({**items[0], 'id': 'nested-3', 'site': '부지B'})
        targets = self.targets()
        self.assertEqual(len(targets), 3)
        self.assertEqual({target['id'] for target in targets}, {'mention:nested-1', 'mention:nested-2', 'mention:nested-3'})

    def test_exact_name_location_group_collects_source_ids_without_mutation(self):
        other = article('other')
        self.ds['articles']['other'] = other
        self.ds['project_mentions']['other'] = record(other, 'nested-2')
        before = copy.deepcopy(self.ds)
        target = self.targets()[0]
        self.assertEqual(len(self.targets()), 1)
        self.assertEqual(target['source_article_ids'], ['old', 'other'])
        self.assertEqual(self.ds, before)

    def test_flat_legacy_fixture_kept_and_own_source_excluded(self):
        ds = {'articles': {'old': {'mode': 'live_metadata'}, 'other': {'mode': 'live_metadata'},
                            'new': self.selected},
              'project_mentions': {'m1': {'id': 'm1', 'article_id': 'old', 'name': '용인 테스트 AI 데이터센터'},
                                   'm2': {'id': 'm2', 'article_id': 'other', 'name': '용인 테스트 AI 데이터센터'},
                                   'own': {'id': 'own', 'article_id': 'new', 'name': '용인 테스트 AI 데이터센터'}}}
        targets = self.targets(ds)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]['id'], 'mention:m1')
        self.assertEqual(targets[0]['source_article_ids'], ['old', 'other'])

    def test_registered_target_filters_sources_and_identity_dict_notes(self):
        self.ds['articles']['manual'] = article('manual', mode='manual')
        self.ds['articles']['private'] = article('private', visibility='private')
        self.ds['projects'] = {'p': {'id': 'p', 'name': '용인 테스트 AI 데이터센터',
            'article_ids': ['private', 'old', 'manual'], 'phase': '1단계',
            'location': {'city': '용인', 'note': 'PRIVATE-LOCATION-NOTE'}, 'note': 'PRIVATE-PROJECT-NOTE'},
            'hidden': {'id': 'hidden', 'name': '용인 테스트 AI 데이터센터', 'article_ids': ['private']}}
        registered = [target for target in comparison_targets(self.ds) if target['kind'] == 'registered_project']
        self.assertEqual(len(registered), 1)
        self.assertEqual(registered[0]['source_article_ids'], ['old'])
        self.assertEqual(registered[0]['phase'], '1단계')
        self.assertNotIn('PRIVATE', json.dumps(registered))

    def test_many_real_nested_targets_keep_total_input_cap(self):
        for index in range(25):
            ident = 'source-' + str(index)
            source = article(ident)
            self.ds['articles'][ident] = source
            target = record(source, 'target-' + str(index), '단계-' + str(index))
            target['mentions'][0]['site'] = '공개 부지 ' + ('용인 ' * 180)
            self.ds['project_mentions'][ident] = target
        prepared = prepare_analysis(self.ds, {'max_input_chars': 6000}, ['new'])
        self.assertLessEqual(prepared['preview']['input_chars'], 6000)
        self.assertGreater(prepared['preview']['removed_targets'], 0)
        self.assertLessEqual(len(prepared['input_data']['targets']), 15)

    def test_decision_resolves_nested_target_and_stale_accept_rejected(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        repo = JsonRepository(Path(temp.name) / 'isolated')
        target = self.targets()[0]
        run = {'id': 'run', 'status': 'completed', 'target_snapshots': [target],
               'result': {'matches': [{'id': 'match', 'article_id': 'new', 'target_id': target['id']}]}}
        repo.transact(lambda ds: ds.update(**self.ds, ai_runs={'run': run}))
        self.assertFalse(decide_match(repo, {'run_id': 'run', 'match_id': 'match', 'decision': 'accepted_candidate'})['merged'])
        saved = repo.snapshot()['datasets']['ai_match_decisions']['match']
        self.assertEqual(saved['target_id'], 'mention:nested-1')
        self.assertEqual(saved['source_article_ids'], ['old'])
        repo.transact(lambda ds: ds['articles']['old'].update(title='원본 공개 제목 변경'))
        with self.assertRaisesRegex(ValueError, '공개 근거가 변경'):
            decide_match(repo, {'run_id': 'run', 'match_id': 'match', 'decision': 'accepted_candidate'})
        self.assertEqual(decide_match(repo, {'run_id': 'run', 'match_id': 'match', 'decision': 'rejected'})['status'], 'saved')

    def test_decision_rejects_unprovided_or_changed_identity(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        repo = JsonRepository(Path(temp.name) / 'isolated')
        target = self.targets()[0]
        run = {'id': 'run', 'status': 'completed', 'target_snapshots': [],
               'result': {'matches': [{'id': 'match', 'article_id': 'new', 'target_id': target['id']}]}}
        repo.transact(lambda ds: ds.update(**self.ds, ai_runs={'run': run}))
        with self.assertRaisesRegex(ValueError, '제공되지 않은'):
            decide_match(repo, {'run_id': 'run', 'match_id': 'match', 'decision': 'accepted_candidate'})
        repo.transact(lambda ds: ds['ai_runs']['run'].update(target_snapshots=[{**target, 'phase': '이전 단계'}]))
        with self.assertRaisesRegex(ValueError, '단계가 변경'):
            decide_match(repo, {'run_id': 'run', 'match_id': 'match', 'decision': 'accepted_candidate'})

    def test_grouped_snapshot_multiple_sources_accepts_stable_raw_target(self):
        other = article('other')
        self.ds['articles']['other'] = other
        self.ds['project_mentions']['other'] = record(other, 'nested-2')
        target = self.targets()[0]
        self.assertEqual(target['source_article_ids'], ['old', 'other'])
        current = comparison_target(self.ds, target['id'])
        self.assertEqual(current['source_article_ids'], ['old'])
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        repo = JsonRepository(Path(temp.name) / 'isolated')
        run = {'id': 'run', 'status': 'completed', 'target_snapshots': [target],
               'result': {'matches': [{'id': 'match', 'article_id': 'new', 'target_id': target['id']}]}}
        repo.transact(lambda ds: ds.update(**self.ds, ai_runs={'run': run}))
        result = decide_match(repo, {'run_id': 'run', 'match_id': 'match', 'decision': 'accepted_candidate'})
        self.assertEqual(result['status'], 'saved')
        self.assertFalse(result['merged'])

    def test_two_selected_articles_can_compare_other_article_target_but_not_self(self):
        self.ds['project_mentions']['new'] = record(self.selected, 'nested-2')
        articles = [public_article(self.source), public_article(self.selected)]
        targets = shortlist(self.ds, articles)
        self.assertEqual(len(targets), 1)  # exact-name display grouping only
        target = targets[0]
        self.assertEqual(target['id'], 'mention:nested-1')
        self.assertEqual(target['primary_source_article_id'], 'old')
        self.assertEqual(target['source_article_ids'], ['new', 'old'])
        def output(aid):
            return {'extractions': [], 'briefing': [], 'matches': [{
                'article_id': aid, 'project_name': '용인 테스트 AI 데이터센터',
                'target_id': target['id'], 'assessment': 'possible_same',
                'reason': '서로 다른 기사에서 동일 명칭 관측', 'quote': '용인 테스트 AI 데이터센터'}]}
        valid = validate_result(output('new'), articles, targets)
        self.assertEqual(valid['matches'][0]['validation_state'], 'evidence_linked_ai_candidate')
        with self.assertRaisesRegex(ValueError, '자기 기사'):
            validate_result(output('old'), articles, targets)
        self.assertIn('primary_source_article_id', SYSTEM)

    def test_single_article_own_only_target_still_excluded(self):
        target = comparison_target(self.ds, 'mention:nested-1')
        self.assertEqual(target['primary_source_article_id'], 'old')
        self.assertEqual(shortlist(self.ds, [public_article(self.source)]), [])


if __name__ == '__main__': unittest.main()
