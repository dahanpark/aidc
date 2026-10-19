"""Pipeline integration tests with the real generation-based JSON repository."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from backend.repository import JsonRepository
from backend import pipeline

ROOT=Path(__file__).resolve().parents[1]

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo=JsonRepository(Path(self.temp.name)/'store')
        self.fixture=json.loads((ROOT/'fixtures/official_manual_gold.json').read_text(encoding='utf-8'))
    def apply(self,bundle):
        result={}
        self.repo.transact(lambda ds:result.update(pipeline._ingest(ds,bundle,pipeline._now())))
        return result
    def seed(self):
        return pipeline.bootstrap(self.repo,ROOT)
    def test_bootstrap_real_sources_and_scope_parent_separation(self):
        self.assertEqual(self.seed()['count'],3)
        ds=pipeline.view(self.repo)
        self.assertEqual(len(ds['projects']),4)
        self.assertEqual(ds['coverage']['kr-dc']['project_count'],0)
        phase=ds['projects']['prj-stargate-uae-phase1']
        self.assertEqual(phase['parent_id'],'prj-stargate-uae')
        self.assertEqual(phase['capacities'][0]['value'],200)
        self.assertEqual(phase['capacities'][0]['metric'],'announced_capacity')
        self.assertEqual(phase['milestones'][0]['date'],'2026')
        self.assertEqual(phase['milestones'][0]['basis'],'planned')
        self.assertTrue(all(len(p['summary']) in (3,4,5) for p in ds['projects'].values()))
    def test_replay_idempotent_and_restart_preserves_user_state(self):
        self.seed();ds=pipeline.view(self.repo);change=next(iter(ds['changes']))
        def user_edit(data):
            data['read_states'][change]={'id':change,'read_at':'2026-10-16T00:00:00Z'}
            data['settings']['app']['digest_hour']=20
            data['projects']['prj-ulsan']['user_note']='preserve this note'
        self.repo.transact(user_edit)
        before=pipeline.view(self.repo)
        result=pipeline.collect(self.repo,ROOT)
        after=pipeline.view(self.repo)
        self.assertEqual(result['count'],0);self.assertEqual(result['deduplicated'],3)
        self.assertEqual(after['changes'],before['changes'])
        self.assertEqual(after['notifications'],before['notifications'])
        self.assertEqual(after['read_states'],before['read_states'])
        self.assertEqual(pipeline.bootstrap(self.repo,ROOT)['status'],'existing_state_preserved')
        self.assertEqual(pipeline.view(self.repo)['settings']['app']['digest_hour'],20)
        self.assertEqual(pipeline.view(self.repo)['projects']['prj-ulsan']['user_note'],'preserve this note')
    def test_view_never_marks_changes_read(self):
        self.seed();before=self.repo.snapshot()['generation']
        for _ in range(3):pipeline.view(self.repo)
        self.assertEqual(before,self.repo.snapshot()['generation'])
        self.assertEqual(pipeline.view(self.repo)['read_states'],{})
    def test_corrupted_evidence_rejected_atomically(self):
        bundle=deepcopy(self.fixture);bundle['claims'][0]['evidence_excerpt']='99 gigawatts not in source'
        before=self.repo.snapshot()
        with self.assertRaisesRegex(ValueError,'evidence'):self.apply(bundle)
        self.assertEqual(self.repo.snapshot(),before)
    def test_unit_and_metric_misclassification_rejected(self):
        for field,value in [('unit','MVA'),('unit','MW'),('predicate','it_capacity')]:
            with self.subTest(field=field,value=value):
                bundle=deepcopy(self.fixture);bundle['claims'][0][field]=value
                with self.assertRaises(ValueError):self.apply(bundle)
        self.assertFalse(self.repo.snapshot()['datasets'])
    def test_wrong_value_rejected(self):
        bundle=deepcopy(self.fixture);bundle['claims'][0]['value']=45
        with self.assertRaisesRegex(ValueError,'value'):self.apply(bundle)
    def event_bundle(self,event,published,value,suffix):
        old=next(p for p in self.fixture['projects'] if p['id']=='prj-stargate-us-oracle')
        project=deepcopy(old);aid='art-update-'+suffix;project['article_ids']=[aid];project['latest_change_at']=event
        article={'id':aid,'title':'Synthetic test-only source update '+suffix,'url':'https://example.com/test/'+suffix,'publisher':'test_fixture_only','published_at':published,'event_date':event,'summary':'synthetic test '+suffix,'evidence_excerpt':str(value)+' gigawatts; synthetic test source '+suffix,'mode':'fixture_mock','project_ids':[project['id']]}
        claim={'id':'claim-'+suffix,'project_id':project['id'],'article_id':aid,'predicate':'announced_capacity','value':value,'unit':'GW','scope':'program','basis':'planned','event_date':event,'evidence_excerpt':str(value)+' gigawatts','validation_state':'manual_gold_verified'}
        return {'mode':'fixture_mock','articles':[article],'projects':[project],'companies':[],'claims':[claim],'relationships':[]}
    def test_latest_event_wins_and_previous_values_remain(self):
        self.seed()
        self.apply(self.event_bundle('2025-06-01','2026-10-15',3.5,'old-republished'))
        p=pipeline.view(self.repo)['projects']['prj-stargate-us-oracle']
        self.assertEqual(p['capacities'][0]['value'],4.5)
        self.assertFalse(p['capacity_history'][-1]['candidate_selected'])
        self.apply(self.event_bundle('2025-08-01','2025-08-02',5.5,'new-event'))
        p=pipeline.view(self.repo)['projects']['prj-stargate-us-oracle']
        self.assertEqual(p['capacities'][0]['value'],5.5)
        self.assertTrue(p['capacity_history'][-1]['candidate_selected'])
        self.assertEqual(p['capacity_history'][-1]['previous']['value'],4.5)
        self.assertEqual(len(p['capacity_history']),2)
    def test_same_date_conflict_not_silently_overwritten(self):
        self.seed();self.apply(self.event_bundle('2025-07-22','2026-10-16',9.5,'same-date'))
        p=pipeline.view(self.repo)['projects']['prj-stargate-us-oracle']
        self.assertEqual(p['capacities'][0]['value'],4.5)
        self.assertFalse(p['capacity_history'][-1]['candidate_selected'])
    def test_reprinted_content_deduplicates_across_urls(self):
        self.seed();bundle=deepcopy(self.fixture)
        for article in bundle['articles']:
            article['id']+='-reprint';article['url']='https://example.com/reprint/'+article['id']
        # Only articles are submitted: no invented business linkage or duplicate changes.
        bundle.update(projects=[],claims=[],companies=[],relationships=[])
        result=self.apply(bundle)
        self.assertEqual(result['count'],0);self.assertEqual(result['deduplicated'],3)
        self.assertEqual(len(pipeline.view(self.repo)['articles']),3)
    def test_manual_import_normalizes_and_never_fetches_or_creates_claims(self):
        self.seed();before=pipeline.view(self.repo)
        payload={'title':'Manual note','url':'https://example.com/news/?utm_source=x&b=2&a=1#section','published_at':'2026-10-16','summary':'User says 900 MW, unverified.','project_id':'prj-ulsan'}
        with patch('socket.create_connection',side_effect=AssertionError('network forbidden')):
            result=pipeline.import_article(self.repo,payload)
        self.assertEqual(result['claims_created'],0);self.assertFalse(result['fetched'])
        ds=pipeline.view(self.repo);a=ds['articles'][result['article_id']]
        self.assertEqual(a['url'],'https://example.com/news?a=1&b=2')
        self.assertEqual(a['mode'],'manual');self.assertEqual(ds['claims'],before['claims'])
        self.assertEqual(ds['projects']['prj-ulsan']['capacities'],[])
        payload['url']='https://example.com/news?a=1&b=2'
        self.assertEqual(pipeline.import_article(self.repo,payload)['status'],'deduplicated')
    def test_private_or_credential_urls_rejected(self):
        for url in ['file:///secret','ftp://example.com/x','http://localhost/x','http://127.0.0.1/x','http://10.0.0.1/x','http://169.254.169.254/x','https://user:secret@example.com/','http://2130706433/','http://0x7f000001/','http://[::1]/']:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):pipeline.import_article(self.repo,{'title':'x','url':url})
    def test_ambiguous_project_is_not_created_or_merged(self):
        self.seed();before=self.repo.snapshot()
        with self.assertRaisesRegex(ValueError,'Unknown project_id'):
            pipeline.import_article(self.repo,{'title':'Another same-city business','url':'https://example.com/different-site','summary':'Different unknown business','project_id':'unknown-same-city'})
        self.assertEqual(self.repo.snapshot(),before)

    def mark_all_read(self):
        def mutate(ds):
            for cid in ds['changes']:ds['read_states'][cid]={'id':cid,'read_at':'2026-10-16T00:00:00Z'}
        self.repo.transact(mutate)
    def test_same_value_confirmation_advances_evidence_date_without_business_change(self):
        self.seed();self.mark_all_read();before=pipeline.view(self.repo)
        result=self.apply(self.event_bundle('2025-09-01','2025-09-02',4.5,'september-confirmation'))
        self.assertEqual(result['count'],1);self.assertEqual(result['changes_count'],0)
        result2=self.apply(self.event_bundle('2025-08-01','2026-10-16',5.5,'late-august-reprint'))
        self.assertEqual(result2['changes_count'],0)
        after=pipeline.view(self.repo);p=after['projects']['prj-stargate-us-oracle']
        self.assertEqual(p['capacities'][0]['value'],4.5)
        self.assertEqual(p['capacities'][0]['event_date'],'2025-09-01')
        self.assertEqual(p['capacities'][0]['claim_id'],'claim-september-confirmation')
        self.assertEqual(p['latest_change_at'],'2025-07-22')
        self.assertEqual(len(p['capacity_history']),2)
        self.assertTrue(p['capacity_history'][0]['candidate_selected'])
        self.assertEqual(p['capacity_history'][0]['reason'],'newer_same_value_confirmation')
        self.assertFalse(p['capacity_history'][1]['candidate_selected'])
        self.assertEqual(after['changes'],before['changes'])
        self.assertEqual(after['notifications'],before['notifications'])
        self.assertEqual(after['read_states'],before['read_states'])
    def test_different_url_old_event_collects_without_unread_change(self):
        self.seed();self.mark_all_read();before=pipeline.view(self.repo)
        bundle=self.event_bundle('2025-06-01','2026-10-16',3.5,'different-url-different-copy')
        result=self.apply(bundle);after=pipeline.view(self.repo)
        self.assertEqual(result['count'],1);self.assertEqual(result['changes_count'],0)
        self.assertEqual(len(after['articles']),len(before['articles'])+1)
        self.assertEqual(after['changes'],before['changes'])
        self.assertEqual(after['notifications'],before['notifications'])
        self.assertEqual(after['projects']['prj-stargate-us-oracle']['latest_change_at'],'2025-07-22')
    def test_real_latest_value_change_creates_exactly_one_change(self):
        self.seed();before=pipeline.view(self.repo)
        result=self.apply(self.event_bundle('2025-08-01','2025-08-02',5.5,'genuine-new-value'))
        after=pipeline.view(self.repo)
        self.assertEqual(result['count'],1);self.assertEqual(result['changes_count'],1)
        self.assertEqual(len(after['changes']),len(before['changes'])+1)
        self.assertEqual(len(after['notifications']),len(before['notifications'])+1)
        self.assertEqual(after['projects']['prj-stargate-us-oracle']['latest_change_at'],'2025-08-01')
    def test_explicit_status_and_relation_changes_are_meaningful(self):
        self.seed();bundle=self.event_bundle('2025-09-01','2025-09-02',4.5,'explicit-status')
        bundle['projects'][0]['status']='Synthetic test only: construction started'
        self.assertEqual(self.apply(bundle)['changes_count'],1)
        bundle=self.event_bundle('2025-10-01','2025-10-02',4.5,'explicit-new-partner')
        bundle['projects'][0]['status']='Synthetic test only: construction started'
        cid='co-test-explicit';pid='prj-stargate-us-oracle';aid=bundle['articles'][0]['id']
        bundle['companies']=[{'id':cid,'name':'Synthetic test company','country':'US','role':'test-only partner','project_ids':[pid],'summary':'test only'}]
        bundle['projects'][0]['company_ids'].append(cid)
        bundle['relationships']=[{'id':'rel-test-explicit','project_id':pid,'company_id':cid,'role':'explicit test-only construction partner','article_ids':[aid],'claim_ids':[],'directness':'explicit'}]
        self.assertEqual(self.apply(bundle)['changes_count'],1)
        before=pipeline.view(self.repo)
        bundle=self.event_bundle('2025-11-01','2025-11-02',4.5,'same-partner-reconfirmed')
        bundle['projects'][0]['status']='Synthetic test only: construction started'
        bundle['relationships']=[{'id':'rel-test-reconfirmed','project_id':pid,'company_id':cid,'role':'explicit test-only construction partner','article_ids':[bundle['articles'][0]['id']],'claim_ids':[],'directness':'explicit'}]
        self.assertEqual(self.apply(bundle)['changes_count'],0)
        self.assertEqual(pipeline.view(self.repo)['changes'],before['changes'])
    def test_explicit_capacity_types_accept_valid_english_and_korean_evidence(self):
        self.seed()
        cases=[('it_capacity','5.5 GW IT load','GW'),('grid_capacity','5.5 GW grid capacity','GW'),('generation_capacity','5.5 GW generation capacity','GW'),('apparent_power','5.5 MVA apparent power','MVA')]
        for pred,excerpt,unit in cases:
            with self.subTest(predicate=pred):
                bundle=self.event_bundle('2025-09-01','2025-09-02',5.5,'typed-'+pred)
                bundle['articles'][0]['evidence_excerpt']=excerpt
                bundle['claims'][0].update(predicate=pred,unit=unit,evidence_excerpt=excerpt)
                self.assertEqual(self.apply(bundle)['count'],1)
                values=pipeline.view(self.repo)['projects']['prj-stargate-us-oracle']['capacities']
                self.assertTrue(any(c['metric']==pred and c['unit']==unit and c['scope']=='program' for c in values))
        bundle=self.event_bundle('2025-10-01','2025-10-02',6.5,'korean-grid')
        bundle['articles'][0]['evidence_excerpt']='6.5 GW 수전 용량'
        bundle['claims'][0].update(predicate='grid_capacity',value=6.5,evidence_excerpt='6.5 GW 수전 용량')
        self.assertEqual(self.apply(bundle)['count'],1)
    def test_untyped_generation_grid_it_and_wrong_mva_scope_rejected(self):
        self.seed()
        for pred in ('it_capacity','grid_capacity','generation_capacity'):
            with self.subTest(predicate=pred):
                bundle=self.event_bundle('2025-09-01','2025-09-02',5.5,'untyped-'+pred)
                bundle['claims'][0]['predicate']=pred
                before=self.repo.snapshot()
                with self.assertRaisesRegex(ValueError,'type'):self.apply(bundle)
                self.assertEqual(self.repo.snapshot(),before)
        bundle=self.event_bundle('2025-09-01','2025-09-02',5.5,'mva-wrong-scope')
        bundle['articles'][0]['evidence_excerpt']='5.5 MVA apparent power'
        bundle['claims'][0].update(predicate='apparent_power',unit='MVA',scope='site',evidence_excerpt='5.5 MVA apparent power')
        with self.assertRaisesRegex(ValueError,'scope'):self.apply(bundle)
    def test_authentication_query_and_fragment_never_enter_repository(self):
        for suffix in ('?token=sensitive-value','?api_key=sensitive-value','?%61ccess_token=sensitive-value','#token=sensitive-value'):
            before=self.repo.snapshot()
            with self.subTest(suffix=suffix):
                with self.assertRaises(ValueError) as caught:
                    pipeline.import_article(self.repo,{'title':'do not persist credentials','url':'https://example.com/news'+suffix})
                self.assertNotIn('sensitive-value',str(caught.exception))
                self.assertEqual(self.repo.snapshot(),before)
        bundle=deepcopy(self.fixture);bundle['articles'][0]['url']='https://example.com/news?access_token=sensitive-value'
        with self.assertRaises(ValueError):self.apply(bundle)
        self.assertFalse(self.repo.snapshot()['datasets'])

if __name__=='__main__':unittest.main()
