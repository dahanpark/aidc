"""Logical grouping against isolated public metadata; no source records merge."""
import copy
import unittest
from backend import project_identity as identity
from backend.project_discovery import _stamp


class ProjectIdentityTests(unittest.TestCase):
    def setUp(self):
        self.ds={'articles':{
            'a':{'id':'a','mode':'live_metadata','title':'서울 알파 데이터센터 추진',
                 'feed_excerpt':'알파 데이터센터 사업 검토','note':'SECRET_NOTE','body':'SECRET_BODY'},
            'b':{'id':'b','mode':'live_metadata','title':'알파 AIDC 서울 건립',
                 'feed_excerpt':'알파 AIDC 개발 계획'},
            'c':{'id':'c','mode':'live_metadata','title':'알파 제3명칭 서울 사업 추진'},
        },'projects':{'p':{'id':'p','name':'알파 데이터센터','city':'서울','country':'KR','article_ids':['a'],
                           'memo':'SECRET_PROJECT','capacity':100}},
        'project_mentions':{'b':{'id':'b','article_id':'b','mentions':[
                   {'id':'m','name':'알파 AIDC','cities':['서울'],'countries':['KR'],'article_id':'b',
                    'evidence':{'article_id':'b','field':'title','text':'알파 AIDC'}}]},
                            'legacy':{'id':'legacy','name':'알파 제3명칭','city':'서울','country':'KR','article_id':'c'}},
        'attention':{'n':{'read':False}}}
        self.ds['project_mentions']['b']['source_hash']=_stamp(self.ds['articles']['b'])
        self.payload={'canonical_ref':'project:p','member_refs':['project:p','mention:m'],
                      'evidence_article_ids':['a','b']}

    def apply(self,payload=None):
        payload=copy.deepcopy(payload or self.payload)
        view=identity.preview(self.ds,payload)
        return identity.apply(self.ds,{**payload,'input_hash':view['input_hash'],'consent_user_confirmed':True})

    def ai(self):
        match={'id':'run:match:0','article_id':'b','project_name':'알파 AIDC','target_id':'p',
               'assessment':'possible_same','quote':'알파 AIDC 서울 건립'}
        self.ds['ai_runs']={'run':{'id':'run','status':'completed','result':{'matches':[match]},
                     'input_snapshots':[{'id':'b','title':self.ds['articles']['b']['title'],
                                         'text':self.ds['articles']['b']['title']+'\n'+self.ds['articles']['b']['feed_excerpt']}],
                     'target_snapshots':[{'id':'p','name':'알파 데이터센터'}]}}
        self.ds['ai_match_decisions']={match['id']:{'run_id':'run','decision':'accepted_candidate','at':'2026-10-27'}}
        return {**self.payload,'run_id':'run','match_id':match['id']}

    def test_nested_legacy_typed_refs_and_read_only_preview(self):
        before=copy.deepcopy(self.ds);view=identity.preview(self.ds,self.payload);ws=identity.workspace(self.ds)
        self.assertTrue(view['applicable']);self.assertEqual(view['canonical_title'],'알파 데이터센터')
        self.assertEqual(set(ws['by_ref']),{'project:p','mention:m','mention:legacy'})
        self.assertEqual(ws['by_ref']['mention:m']['kind'],'mention');self.assertEqual(ws['by_ref']['project:p']['cities'],['서울'])
        self.assertEqual(self.ds,before);self.assertNotIn('SECRET',str(view));self.assertNotIn('SECRET',str(ws))

    def test_manual_apply_preserves_sources_and_dedupes_articles(self):
        before=copy.deepcopy(self.ds);group=self.apply()
        for field in before:self.assertEqual(self.ds[field],before[field])
        self.assertEqual(group['state'],'approved');self.assertEqual(len(group['history']),1)
        ws=identity.workspace(self.ds);self.assertEqual(len(ws['active_groups']),1)
        self.assertEqual(ws['active_groups'][0]['article_count'],2);self.assertFalse(group['direct_contract_confirmed'])
        self.assertEqual(group['label'],identity.LABEL);self.assertEqual(group['members'][0]['kind'],'mention')

    def test_consent_and_preview_hash_required(self):
        for extra in [{},{'consent_user_confirmed':True},{'input_hash':'wrong','consent_user_confirmed':True}]:
            with self.assertRaises(ValueError):identity.apply(self.ds,{**self.payload,**extra})
        self.assertNotIn('project_identity_groups',self.ds)

    def test_idempotent_apply_and_undo_history(self):
        first=self.apply();again=self.apply();self.assertEqual(first,again)
        revoked=identity.undo(self.ds,{'group_id':first['id'],'consent_user_confirmed':True})
        self.assertEqual(revoked['state'],'revoked');self.assertEqual(len(revoked['history']),2)
        self.assertEqual(revoked['history'][-1]['previous']['state'],'approved')
        self.assertEqual(revoked['history'][-1]['current']['state'],'revoked')
        self.assertEqual(identity.workspace(self.ds)['active_groups'],[])
        self.assertEqual(identity.undo(self.ds,{'group_id':first['id'],'consent_user_confirmed':True}),revoked)
        restored=self.apply();self.assertEqual(restored['id'],first['id']);self.assertEqual(len(restored['history']),3)
        self.assertEqual(len({h['action_id'] for h in restored['history']}),3)

    def test_no_overlap_no_chain_and_explicit_update_required(self):
        first=self.apply()
        payload={'canonical_ref':'mention:m','member_refs':['mention:m','mention:legacy'],'evidence_article_ids':['b','c']}
        self.assertFalse(identity.preview(self.ds,payload)['applicable'])
        with self.assertRaises(ValueError):self.apply(payload)
        changed={**self.payload,'canonical_ref':'mention:m'}
        with self.assertRaises(ValueError):self.apply(changed)
        changed['group_id']=first['id'];updated=self.apply(changed)
        self.assertEqual(updated['id'],first['id']);self.assertEqual(updated['canonical_ref'],'mention:m')
        self.assertEqual(len(updated['history']),2)

    def test_invalid_refs_duplicate_members_and_missing_name_evidence(self):
        for update in [{'member_refs':['project:p']},{'member_refs':['project:p','project:p']},
                       {'canonical_ref':'mention:legacy'},{'member_refs':['project:p','mention:missing']}]:
            payload={**self.payload,**update}
            try:self.assertFalse(identity.preview(self.ds,payload)['applicable'])
            except ValueError:pass
        self.ds['articles']['a']['title']='명칭이 없는 공개 기사';self.ds['articles']['a']['feed_excerpt']=''
        self.assertIn('member_name_not_evidenced',{c['code'] for c in identity.preview(self.ds,self.payload)['conflicts']})

    def test_geography_and_entity_level_conflicts_block_apply(self):
        for change,code in [({'cities':['부산']},'cities_conflict'),({'countries':['US']},'countries_conflict'),
                            ({'phase':'2'},'phase_conflict'),({'site_id':'site-b'},'site_ids_conflict'),
                            ({'program_id':'program-b'},'program_ids_conflict'),({'entity_level':'program'},'entity_level_conflict')]:
            with self.subTest(code=code):
                ds=copy.deepcopy(self.ds)
                ds['projects']['p'].update(phase='1',site_id='site-a',program_id='program-a',entity_level='site')
                ds['project_mentions']['b']['mentions'][0].update(change)
                view=identity.preview(ds,self.payload)
                self.assertIn(code,{c['code'] for c in view['conflicts']})
                with self.assertRaises(ValueError):identity.apply(ds,{**self.payload,'input_hash':view['input_hash'],'consent_user_confirmed':True})

    def test_phase_in_names_and_unknown_units_do_not_create_facts(self):
        self.ds['projects']['p']['phase']=1;self.ds['project_mentions']['b']['mentions'][0]['phase']=2
        self.assertFalse(identity.preview(self.ds,self.payload)['applicable'])
        self.ds['project_mentions']['b']['mentions'][0].pop('phase');self.ds['projects']['p'].pop('phase')
        self.ds['project_mentions']['b']['mentions'][0]['capacity_signals']=[{'value':999,'unit':'MVA','metric':'unspecified'}]
        group=self.apply();self.assertNotIn('capacity',group);self.assertNotIn('capacity_signals',str(group))
        self.assertTrue(identity.preview(self.ds,self.payload)['warnings'])

    def test_source_change_between_preview_and_apply_rejected(self):
        view=identity.preview(self.ds,self.payload)
        self.ds['articles']['a']['feed_excerpt']+=' 新보도'
        with self.assertRaises(ValueError):identity.apply(self.ds,{**self.payload,'input_hash':view['input_hash'],'consent_user_confirmed':True})
        self.assertNotIn('project_identity_groups',self.ds)

    def test_private_fields_do_not_change_hash_but_public_changes_disable_active(self):
        view=identity.preview(self.ds,self.payload);group=self.apply()
        self.ds['articles']['a']['note']='other secret';self.ds['projects']['p']['memo']='other memo'
        self.assertEqual(view['input_hash'],identity.preview(self.ds,self.payload)['input_hash'])
        self.ds['articles']['a']['feed_excerpt']+=' 공개 수정'
        ws=identity.workspace(self.ds);self.assertEqual(ws['active_groups'],[]);self.assertTrue(ws['groups'][0]['stale'])
        self.assertEqual(self.ds['project_identity_groups'][group['id']]['state'],'approved')

    def test_stale_nested_record_and_deleted_ref_not_projected(self):
        group=self.apply();self.ds['articles']['b']['title']+=' 수정'
        ws=identity.workspace(self.ds,['a']);self.assertEqual(ws['active_groups'],[])
        self.assertIn('stale_reference',{c['code'] for c in ws['groups'][0]['conflicts']})
        self.ds['project_mentions']['b']['mentions']=[]
        self.assertFalse(identity.workspace(self.ds)['groups'][0]['resolvable'])
        self.assertEqual(self.ds['project_identity_groups'][group['id']]['member_refs'],group['member_refs'])

    def test_selected_article_filter_does_not_change_full_group_validity(self):
        self.apply();ws=identity.workspace(self.ds,['a'])
        self.assertEqual(set(ws['by_ref']),{'project:p'});self.assertEqual(ws['active_groups'][0]['article_count'],1)
        self.assertEqual(len(ws['active_groups'][0]['members']),2)
        self.assertEqual(identity.workspace(self.ds,[])['groups'],[])

    def test_private_or_manual_evidence_is_rejected(self):
        for change in [{'visibility':'private'},{'mode':'manual'}]:
            ds=copy.deepcopy(self.ds);ds['articles']['a'].update(change)
            view=identity.preview(ds,self.payload);self.assertFalse(view['applicable'])
            self.assertIn('non_public_or_missing_evidence',{c['code'] for c in view['conflicts']})

    def test_ai_acceptance_alone_never_groups_and_exact_pair_is_required(self):
        payload=self.ai();self.assertEqual(identity.workspace(self.ds)['active_groups'],[])
        self.assertEqual(self.apply(payload)['run_id'],'run')
        for mutate in [lambda ds:ds['ai_runs']['run'].update(status='failed'),
                       lambda ds:ds['ai_match_decisions']['run:match:0'].update(decision='pending'),
                       lambda ds:ds['ai_runs']['run']['result']['matches'][0].update(target_id='wrong'),
                       lambda ds:ds['ai_runs']['run']['result']['matches'][0].update(project_name='다른 명칭'),
                       lambda ds:ds['ai_runs']['run']['input_snapshots'][0].update(title='옛 기사')]:
            ds=copy.deepcopy(self.ds);mutate(ds)
            with self.assertRaises(ValueError):identity.preview(ds,payload)

    def test_ai_basis_does_not_copy_arbitrary_model_fields(self):
        payload=self.ai();self.ds['ai_runs']['run']['result']['matches'][0]['internal_note']='SECRET_AI'
        self.assertNotIn('SECRET_AI',str(identity.preview(self.ds,payload)))

    def test_ambiguous_multi_city_overlap_is_not_identity_approval(self):
        self.ds['project_mentions']['b']['mentions'][0]['cities']=['서울','부산']
        view=identity.preview(self.ds,self.payload)
        self.assertFalse(view['applicable']);self.assertIn('cities_conflict',{c['code'] for c in view['conflicts']})

    def test_read_count_is_unique_when_two_members_share_an_article(self):
        self.ds['projects']['p']['article_ids'].append('b')
        self.apply();ws=identity.workspace(self.ds)
        self.assertEqual(ws['active_groups'][0]['article_ids'],['a','b'])
        self.assertEqual(ws['active_groups'][0]['article_count'],2)
        self.assertFalse(self.ds['attention']['n']['read'])

    def test_validate_records_allows_public_updates_and_geography_staleness(self):
        group=self.apply();before=copy.deepcopy(self.ds)
        self.assertTrue(identity.validate_records(self.ds));self.assertEqual(self.ds,before)
        self.ds['articles']['a']['feed_excerpt']+=' 새 공개 내용'
        self.ds['project_mentions']['b']['mentions'][0]['cities']=['부산']
        self.assertTrue(identity.validate_records(self.ds))
        self.assertEqual(identity.workspace(self.ds)['active_groups'],[])
        identity.undo(self.ds,{'group_id':group['id'],'consent_user_confirmed':True})
        self.assertTrue(identity.validate_records(self.ds))

    def test_validate_records_rejects_missing_raw_refs_and_articles_even_revoked(self):
        group=self.apply()
        for revoked in (False,True):
            baseline=copy.deepcopy(self.ds)
            if revoked:identity.undo(baseline,{'group_id':group['id'],'consent_user_confirmed':True})
            for mutate in [lambda ds:ds['projects'].pop('p'),
                           lambda ds:ds['project_mentions']['b'].update(mentions=[]),
                           lambda ds:ds['articles'].pop('a'),lambda ds:ds['articles'].pop('b'),
                           lambda ds:ds['project_mentions']['b'].update(article_id='missing')]:
                ds=copy.deepcopy(baseline);mutate(ds)
                with self.assertRaises(ValueError):identity.validate_records(ds)

    def test_validate_records_rejects_schema_identity_and_history_corruption(self):
        group=self.apply();gid=group['id']
        for mutate in [lambda g:g.update(id='other'),lambda g:g.update(state='active'),
                       lambda g:g.update(history=[]),lambda g:g.update(auto_merge=True),
                       lambda g:g.update(input_hash='bad'),lambda g:g.update(members=[]),
                       lambda g:g.update(evidence_article_ids=['missing']),
                       lambda g:g['history'][0].update(action='update'),
                       lambda g:g['history'][0].update(at='not-a-date'),
                       lambda g:g['history'][0]['current'].update(canonical_title='tampered')]:
            ds=copy.deepcopy(self.ds);mutate(ds['project_identity_groups'][gid])
            with self.assertRaises(ValueError):identity.validate_records(ds)

    def test_validate_records_checks_history_raw_references_and_chain(self):
        first=self.apply()
        changed={'group_id':first['id'],'canonical_ref':'project:p','member_refs':['project:p','mention:legacy'],
                 'evidence_article_ids':['a','c']}
        self.apply(changed);self.assertTrue(identity.validate_records(self.ds))
        ds=copy.deepcopy(self.ds);ds['project_mentions']['b']['mentions']=[]
        with self.assertRaises(ValueError):identity.validate_records(ds)
        ds=copy.deepcopy(self.ds)
        ds['project_identity_groups'][first['id']]['history'][1]['previous']['canonical_title']='broken chain'
        with self.assertRaises(ValueError):identity.validate_records(ds)

    def test_validate_records_ai_decision_change_is_stale_not_dangling(self):
        payload=self.ai();self.apply(payload)
        self.ds['ai_match_decisions']['run:match:0']['decision']='pending'
        self.assertTrue(identity.validate_records(self.ds));self.assertEqual(identity.workspace(self.ds)['active_groups'],[])
        self.ds['ai_runs'].pop('run')
        with self.assertRaises(ValueError):identity.validate_records(self.ds)


if __name__=='__main__':unittest.main()
