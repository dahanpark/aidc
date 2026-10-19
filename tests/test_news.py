from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile
import unittest

from backend import news
from backend.repository import JsonRepository

NOW = '2026-10-16T03:00:00+00:00'


class NewsTests(unittest.TestCase):
    def ds(self):
        fixture = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/official_manual_gold.json').read_text(encoding='utf-8'))
        return {k: {record['id']: record for record in fixture[k]} for k in ('articles', 'projects', 'companies', 'claims', 'relationships')}

    def article(self, aid='live-1', **kwargs):
        article = {'id': aid, 'title': 'Oracle expands AI data center power in United States',
                   'published_at': '2026-10-15T12:00:00Z', 'collected_at': '2026-10-16T01:00:00Z',
                   'url': 'https://www.reuters.com/technology/' + aid, 'publisher': 'Reuters',
                   'source_id': 'reuters', 'project_ids': [], 'summary': '공개 제목 기반 요약 · 본문 미확인',
                   'mode': 'live_metadata', 'access_status': 'feed_metadata_only'}
        article.update(kwargs)
        return article

    def workspace(self, ds, filters=None):
        return news.build_workspace({'datasets': ds}, {'period':'1m',**(filters or {})}, NOW)

    def test_all_nine_periods_and_half_open_elapsed_boundaries(self):
        for period in ('3y', '1y', '6m', '3m', '1m', '2w', '1w', '3d', '1d'):
            with self.subTest(period=period):
                bounds = news.period_bounds(period, NOW)
                ds = self.ds()
                ds['articles'] = {'start': self.article('start', published_at=bounds['start']),
                                  'end': self.article('end', published_at=bounds['end'])}
                work = self.workspace(ds, {'period': period})
                self.assertEqual([a['id'] for a in work['articles']], ['start'])
        self.assertIsNone(news.period_bounds('all', NOW)['start'])
        with self.assertRaises(ValueError):
            news.period_bounds('3years', NOW)

    def test_calendar_months_leap_year_and_kst_crossing(self):
        self.assertEqual(news.period_bounds('1m', '2024-03-31T23:30:00+09:00')['start'], '2024-02-29T14:30:00+00:00')
        self.assertEqual(news.period_bounds('1y', '2024-02-29T00:30:00+09:00')['start'], '2023-02-27T15:30:00+00:00')
        self.assertEqual(news.period_bounds('1d', '2026-10-16T00:30:00+09:00')['start'], '2026-10-14T15:30:00+00:00')
        self.assertEqual(news.period_bounds('1m', '2026-03-31T23:30:00+00:00')['start'], '2026-02-28T23:30:00+00:00')

    def test_kst_date_only_and_invalid_future_excluded(self):
        ds = self.ds()
        ds['articles'] = {'local': self.article('local', published_at='2026-10-16'),
                          'bad': self.article('bad', published_at='invalid'),
                          'future': self.article('future', published_at='2026-10-17')}
        work = self.workspace(ds)
        self.assertEqual([a['id'] for a in work['articles']], ['local'])
        self.assertEqual(work['articles'][0]['published_at_kst'], '2026-10-16T00:00:00+09:00')
        self.assertEqual(work['counts']['excluded_invalid_date'], 1)
        self.assertEqual(work['counts']['excluded_future'], 1)

    def test_filter_normalization_and_validation(self):
        got = news.normalize_filters({'query': ' AI ', 'source_ids': ['reuters,bloomberg', 'reuters'], 'country': 'UAE', 'city': '울산광역시'}, NOW)
        self.assertEqual(got['source_ids'], ['bloomberg', 'reuters'])
        self.assertEqual(got['q'], 'AI')
        self.assertEqual(got['country'], 'AE')
        self.assertEqual(got['city'], '울산')
        self.assertEqual(got['period'], '3y')
        with self.assertRaises(ValueError):
            news.normalize_filters({'source_ids': {'bad': 'shape'}})
        with self.assertRaises(ValueError):
            news.normalize_filters({'scope': 'Europe'})

    def test_multi_term_and_quoted_phrase_queries(self):
        ds = self.ds()
        ds['articles'] = {'en': self.article('en', title='Oracle expansion in new AI data center locations'),
                          'kr': self.article('kr', title='데이터센터 투자 확대와 액침 냉각 개발'),
                          'gap': self.article('gap', title='data design center expansion')}
        self.assertEqual([a['id'] for a in self.workspace(ds, {'q': '데이터센터 냉각'})['articles']], ['kr'])
        self.assertEqual({a['id'] for a in self.workspace(ds, {'q': 'data center expansion'})['articles']}, {'en'})
        self.assertEqual([a['id'] for a in self.workspace(ds, {'q': '"data center" expansion'})['articles']], ['en'])
        with self.assertRaisesRegex(ValueError, '부울'):
            self.workspace(ds, {'q': 'Oracle OR AWS'})
        with self.assertRaisesRegex(ValueError, '따옴표'):
            self.workspace(ds, {'q': '"unclosed phrase'})

    def test_company_alias_candidates_do_not_change_verified_facts(self):
        ds = self.ds()
        before = deepcopy({k: ds[k] for k in ('projects', 'relationships', 'claims')})
        ds['articles']['live-1'] = self.article(title='오라클 AWS SKT invest in AI data centers')
        news.enrich_articles(ds, ['live-1'])
        article = ds['articles']['live-1']
        self.assertTrue({'co-oracle', 'co-aws', 'co-skt'} <= set(article['company_ids']))
        self.assertEqual(article['project_ids'], [])
        self.assertEqual(article['candidate_project_ids'], [])
        self.assertTrue(all(x['confidence'] == 'name_match_candidate' for x in article['entity_matches']))
        for key in before:
            self.assertEqual(ds[key], before[key])

    def test_ambiguous_project_name_not_merged_exact_alias_is_candidate(self):
        ds = self.ds()
        ds['projects']['prj-ulsan']['aliases'] = ['Ulsan SK AI campus']
        ds['articles']['ambiguous'] = self.article('ambiguous', title='Stargate UAE expands')
        ds['articles']['exact'] = self.article('exact', title='Ulsan SK AI campus begins construction')
        news.enrich_articles(ds, ['ambiguous', 'exact'])
        self.assertEqual(ds['articles']['ambiguous']['candidate_project_ids'], [])
        self.assertEqual(ds['articles']['exact']['candidate_project_ids'], ['prj-ulsan'])
        self.assertEqual(ds['articles']['exact']['project_ids'], [])

    def test_known_new_company_is_observed_without_participant_role(self):
        ds = self.ds()
        ds['articles']['live-1'] = self.article(title='Microsoft AI data center expansion in Japan')
        news.enrich_articles(ds, ['live-1'])
        company = ds['companies'][ds['articles']['live-1']['company_ids'][0]]
        self.assertEqual(company['name'], 'Microsoft')
        self.assertEqual(company['classification'], 'observed_name_only')
        self.assertEqual(company['project_ids'], [])
        self.assertEqual(company['role'], '미확인')

    def test_enrichment_idempotent_and_dedicated_read_state(self):
        ds = self.ds()
        ds['articles']['live-1'] = self.article()
        news.enrich_articles(ds, ['live-1', 'live-1'])
        first = deepcopy(ds)
        news.enrich_articles(ds, ['live-1'])
        self.assertEqual(ds, first)
        work = self.workspace(ds)
        uid = work['articles'][0]['news_update_id']
        ds['news_read_states'] = {uid: {'id': uid, 'read_at': NOW}}
        self.assertFalse(self.workspace(ds)['articles'][0]['is_new'])
        self.assertNotIn('read_states', ds)

    def test_same_filtered_articles_in_summary_table_and_updates(self):
        ds = self.ds()
        ds['articles']['chosen'] = self.article('chosen', title='Oracle invests in AI data center power in United States')
        ds['articles']['other'] = self.article('other', source_id='bloomberg', title='Microsoft cooling in Japan')
        ds['articles']['older'] = self.article('older', published_at='2024-01-01')
        work = self.workspace(ds, {'source_ids': 'reuters', 'q': 'Oracle', 'company_id': 'co-oracle', 'scope': 'global-ai'})
        chosen = {'chosen'}
        self.assertEqual({a['id'] for a in work['articles']}, chosen)
        self.assertEqual({r['article_id'] for r in work['rows']}, chosen)
        self.assertEqual({aid for s in work['summary'] for aid in s['article_ids']}, chosen)
        self.assertTrue(all(set(u['article_ids']) <= chosen for u in work['company_updates']))
        self.assertEqual(work['counts']['articles'], 1)

    def test_multi_article_digest_has_all_ids_no_market_claim(self):
        ds = self.ds()
        ds['articles'] = {str(i): self.article(str(i), title=f'Oracle power AI data center {i}', publisher='Reuters' if i else 'Bloomberg') for i in range(3)}
        work = self.workspace(ds)
        self.assertEqual(len(work['summary']), 1)
        digest = work['summary'][0]
        self.assertEqual(set(digest['article_ids']), {'0', '1', '2'})
        self.assertEqual(digest['basis'], 'metadata_digest')
        self.assertIn('본문 미확인', digest['text'])
        self.assertIsNone(digest['independent_evidence_count'])
        self.assertEqual(digest['summary_method'], 'metadata_digest')
        self.assertEqual(digest['common_companies'][0]['name'], 'Oracle')
        self.assertEqual(set(digest['common_companies'][0]['article_ids']), {'0', '1', '2'})
        self.assertEqual({e['article_id'] for e in digest['evidence_links']}, {'0', '1', '2'})
        self.assertTrue(any(o['label'] == '전력' for o in digest['topic_observations']))
        self.assertFalse(work['full_coverage_guaranteed'])

    def test_real_capacity_and_status_history_highlights_with_evidence(self):
        ds = self.ds()
        ds['articles']['new-capacity'] = self.article('new-capacity', project_ids=['prj-stargate-us-oracle'])
        ds['claims']['new-claim'] = {'id': 'new-claim', 'project_id': 'prj-stargate-us-oracle', 'article_id': 'new-capacity'}
        old = {'value': 4.5, 'unit': 'GW', 'claim_id': 'claim-us-45gw'}
        after = {'value': 5.5, 'unit': 'GW', 'claim_id': 'new-claim', 'event_date': '2026-10-15'}
        project = ds['projects']['prj-stargate-us-oracle']
        project['capacity_history'] = [{'previous': old, 'candidate': after, 'candidate_selected': True, 'value_changed': True}]
        project['status_history'] = [{'previous': '계획', 'candidate': '설계 발표', 'candidate_selected': True,
                                     'event_date': '2026-10-15', 'article_ids': ['new-capacity']}]
        project['capacity_history'].append({'previous': old, 'candidate': old, 'candidate_selected': True, 'value_changed': False})
        work = self.workspace(ds)
        changes = [x for x in work['highlights'] if x['kind'] == 'verified_fact_change']
        self.assertEqual(len(changes), 2)
        capacity = next(c for c in changes if c['field'] == 'capacity')
        self.assertEqual(capacity['before']['value'], 4.5)
        self.assertEqual(capacity['after']['value'], 5.5)
        self.assertEqual(capacity['article_ids'], ['new-capacity'])
        new_article = next(c for c in work['highlights'] if c['kind'] == 'new_article')
        self.assertIsNone(new_article['before'])

    def test_confirmations_older_reprints_and_candidate_only_are_not_fact_changes(self):
        ds = self.ds()
        ds['articles']['recent'] = self.article('recent', title='Oracle Stargate confirmation')
        ds['claims']['new'] = {'id': 'new', 'article_id': 'recent'}
        previous = {'value': 4.5, 'unit': 'GW', 'claim_id': 'claim-us-45gw'}
        same = {'value': 4.5, 'unit': 'GW', 'claim_id': 'new', 'event_date': '2026-10-15'}
        older = {'value': 2, 'unit': 'GW', 'claim_id': 'new', 'event_date': '2024-01-01'}
        project = ds['projects']['prj-stargate-us-oracle']
        project['capacity_history'] = [
            {'previous': previous, 'candidate': same, 'candidate_selected': True, 'value_changed': False},
            {'previous': previous, 'candidate': older, 'candidate_selected': False, 'value_changed': True}]
        project['status_history'] = [{'previous': '계획', 'candidate': '착공', 'candidate_selected': False,
                                     'article_ids': ['recent'], 'event_date': '2026-10-15'}]
        self.assertFalse(any(h['kind'] == 'verified_fact_change' for h in self.workspace(ds)['highlights']))
        self.assertEqual(ds['articles']['recent']['project_ids'], [])

    def test_collection_history_marks_current_condition_jobs(self):
        ds = self.ds()
        filters = news.normalize_filters({'period':'1m','q': 'Oracle', 'source_ids': ['reuters'], 'country': 'UAE'}, NOW)
        ds['news_jobs'] = {
            'same': {'id': 'same', 'filters': filters, 'updated_at': NOW},
            'different': {'id': 'different', 'filters': {**filters, 'country': 'US'}, 'updated_at': NOW},
            'legacy': {'id': 'legacy', 'status': 'partial'}}
        work = self.workspace(ds, {'q': 'Oracle', 'source_ids': 'reuters', 'country': 'AE'})
        self.assertEqual(len(work['jobs']), 3)
        self.assertEqual(work['jobs_scope'], 'all_collection_history')
        self.assertEqual(work['matching_job_ids'], ['same'])
        self.assertEqual(work['latest_matching_job_id'], 'same')

    def test_geography_explicit_places_no_company_hq_inference(self):
        ds = self.ds()
        ds['articles'] = {'none': self.article('none', title='Oracle AI power expansion'),
                          'ulsan': self.article('ulsan', title='SKT 울산광역시 AI 데이터센터 투자'),
                          'uae': self.article('uae', title='Oracle expands AI data center in Abu Dhabi UAE')}
        work = self.workspace(ds, {'country': '대한민국', 'city': '울산'})
        self.assertEqual([a['id'] for a in work['articles']], ['ulsan'])
        self.assertEqual(work['rows'][0]['country'], ['KR'])
        self.assertEqual({c['id'] for c in work['geography']['countries']}, {'KR', 'AE'})
        self.assertEqual([a['id'] for a in self.workspace(ds, {'country': 'US'})['articles']], [])

    def test_workspace_does_not_mutate_snapshot_or_hide_registered_projects(self):
        ds = self.ds()
        before = deepcopy(ds)
        work = self.workspace(ds)
        self.assertEqual(work['articles'], [])
        self.assertEqual(work['matching_project_ids'], [])
        self.assertEqual(ds, before)
        self.assertEqual(len(ds['projects']), 4)

    def test_public_feed_description_and_domestic_municipalities(self):
        ds = self.ds()
        ds['articles'] = {
            'daejeon': self.article('daejeon', title='Data center expansion',
                feed_excerpt='Oracle announces data center cooling in Daejeon South Korea'),
            'sejong': self.article('sejong', title='세종특별자치시 데이터센터 투자'),
            'gimhae': self.article('gimhae', title='김해시 데이터센터 설계'),
            'canada': self.article('canada', title='AI data center in Canada'),
            'unknown': self.article('unknown', title='Oracle data center expansion plans')}
        work = self.workspace(ds, {'q': 'Oracle', 'city': '대전'})
        self.assertEqual([a['id'] for a in work['articles']], ['daejeon'])
        self.assertIn('Oracle', work['rows'][0]['company_names'])
        self.assertIn('냉각', work['rows'][0]['categories'])
        all_work = self.workspace(ds)
        self.assertTrue({'대전', '세종', '김해'} <= {c['id'] for c in all_work['geography']['domestic_cities']})
        self.assertIn('CA', {c['id'] for c in all_work['geography']['foreign_countries']})
        self.assertFalse(next(a for a in all_work['articles'] if a['id']=='unknown')['geography']['countries'])

    def test_news_state_survives_json_repository_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = JsonRepository(folder)
            def save(ds):
                ds['articles'] = {'live-1': self.article()}
                news.enrich_articles(ds, ['live-1'])
                uid = next(iter(ds['news_updates']))
                ds['news_read_states'] = {uid: {'id': uid, 'read_at': NOW}}
                ds['news_jobs'] = {'job': {'id': 'job', 'status': 'partial', 'created_at': NOW}}
                ds['news_coverage'] = {'window': {'id': 'window', 'status': 'capped'}}
            repo.transact(save)
            reopened = JsonRepository(folder)
            work = news.build_workspace(reopened.snapshot(), as_of=NOW)
            self.assertFalse(work['articles'][0]['is_new'])
            self.assertEqual(work['jobs'][0]['status'], 'partial')
            self.assertEqual(work['coverage'][0]['status'], 'capped')

    def test_topic_gate_excludes_general_ai_and_publisher_country_false_positive(self):
        ds=self.ds()
        ds['articles']={
            'park':self.article('park',title='도시공원 물놀이장 보수와 미술 작업 진행',summary='도시공원 보수'),
            'weekly':self.article('weekly',title='주간 THE WALL STREET JOURNAL',publisher='한국경제',summary='주간',feed_excerpt='주간 한국경제'),
            'chip':self.article('chip',title='AI 반도체 기술 발표 South Korea',summary='AI chip'),
            'publisher':self.article('publisher',title='AI chip update',publisher='Data Center Dynamics',summary='AI chip',feed_excerpt='AI chip update Data Center Dynamics'),
            'dc':self.article('dc',title='대전 데이터센터 설계',summary='신규 데이터센터'),
            'ai':self.article('ai',title='울산 AI 데이터센터 확장',summary='AI 데이터센터'),
            'foreign':self.article('foreign',title='AI data center in United States',summary='AI data center'),
            'unresolved':self.article('unresolved',title='New data center announced',summary='data center')}
        work=self.workspace(ds)
        self.assertEqual({a['id'] for a in work['articles']},{'dc','ai','foreign','unresolved'})
        self.assertEqual(work['counts']['excluded_out_of_scope'],4)
        self.assertEqual(work['counts']['archive_articles'],8)
        self.assertEqual(work['counts']['scope_counts'],{'all':4,'kr-dc':1,'kr-ai':1,'global-ai':1,'unresolved':1})
        self.assertEqual(sum(work['counts']['scope_counts'][key] for key in ['kr-dc','kr-ai','global-ai','unresolved']),4)
        self.assertEqual([a['id'] for a in self.workspace(ds,{'scope':'unresolved'})['articles']],['unresolved'])
        self.assertFalse(news._geography(ds['articles']['weekly'],{})['countries'])
        self.assertIn('OpenAI',news._text({'title':'OpenAI AI data center','publisher':'OpenAI','feed_excerpt':'OpenAI AI data center OpenAI'}))

    def test_default_query_horizon_is_calendar_three_years(self):
        filters=news.normalize_filters(as_of=NOW)
        self.assertEqual(filters['period'],'3y')
        self.assertEqual(filters['start'],'2023-10-16T03:00:00+00:00')

    def test_filtered_views_do_not_enrich_or_mark_read_in_the_shared_snapshot(self):
        ds = self.ds()
        ds['articles'] = {'live-1': self.article(title='Microsoft AI data center in South Korea')}
        ds['news_jobs'] = {'job': {'id':'job', 'status':'partial', 'filters':{'period':'3y'},
                                 'pending_windows':[{'start':NOW,'end':NOW}]}}
        before = deepcopy(ds)
        domestic = self.workspace(ds, {'scope':'kr-ai'})
        self.assertEqual(ds, before)
        self.assertTrue(domestic['articles'])
        self.assertTrue(domestic['articles'][0]['is_new'])
        other = self.workspace(ds, {'scope':'global-ai'})
        self.assertFalse(other['articles'])
        self.assertEqual(ds, before)
        self.assertEqual(domestic['jobs'], list(before['news_jobs'].values()))


if __name__ == '__main__':
    unittest.main()
