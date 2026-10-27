"""Confirmed AI cleanup overlays. Original articles, entities and user state survive."""
from copy import deepcopy
import hashlib,json,re,uuid
from .repository import now
from .ai_analysis import public_article

SCOPES=('kr-dc','kr-ai','global-ai')
def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def article_stamp(article):
    return digest({k:article.get(k) for k in ('id','title','feed_excerpt','description','mode','visibility','published_at','publisher','source_id','url','scope','country','city','project_ids','company_ids')})
def company_stamp(company):
    return digest({k:company.get(k) for k in ('id','name','aliases','country','entity_type','visibility','registration_number','business_registration_number','parent_company_id')})

def project_stamp(project):
    return digest({k:project.get(k) for k in ('id','name','aliases','country','location','scope','article_ids','level','parent_id')})

def project_type_candidates(ds,run,item):
    """Require a registered link and exact project name in the transmitted quote."""
    aid=item.get('article_id');article=ds.get('articles',{}).get(aid,{})
    if item.get('scope') not in SCOPES:return []
    result=[]
    for p in ds.get('projects',{}).values():
        if p.get('scope') in SCOPES or p.get('visibility') in ('private','internal'):continue
        if p['id'] not in article.get('project_ids',[]) and aid not in p.get('article_ids',[]):continue
        if not any(len(n.strip())>=3 and n.casefold() in item.get('quote','').casefold() for n in [p.get('name',''),*p.get('aliases',[])]):continue
        country=p.get('country')
        if country and ((country in ('KR','KOR','대한민국','한국')) != item['scope'].startswith('kr-')):continue
        result.append({'id':p['id'],'name':p['name'],'scope':item['scope']})
    return result

def project_scope_decide(ds,payload):
    pid=payload.get('project_id');records=ds.setdefault('project_scope_decisions',{})
    if payload.get('action')=='undo':
        old=records.get(pid)
        if not old:raise ValueError('사업 분류 적용 이력이 없습니다.')
        if old.get('active'):
            before={k:deepcopy(v) for k,v in old.items() if k!='history'};old['active']=False;old['updated_at']=now();old['history'].append(_event('undo',before,{'active':False}))
        return old
    if payload.get('confirmed') is not True:raise ValueError('사업 이름·분류 근거를 확인하세요.')
    run,item=run_item(ds,payload,'classify','classifications')
    if pid not in {p['id'] for p in project_type_candidates(ds,run,item)}:raise ValueError('미확인 사업의 연결·명칭·지역 근거가 일치하지 않습니다.')
    stamps=current_evidence(ds,run,[{'article_id':item['article_id'],'quote':item['quote']}])
    old=records.get(pid);history=deepcopy(old.get('history',[])) if old else []
    record={'id':pid,'project_id':pid,'article_id':item['article_id'],'run_id':run['id'],'scope':item['scope'],'quote':item['quote'],'source_stamp':stamps[item['article_id']],'project_stamp':project_stamp(ds['projects'][pid]),'active':True,'updated_at':now()}
    history.append(_event('confirm',{},record));record['history']=history;records[pid]=record;return record

def project_scope_snapshot(snapshot):
    """Only a read projection; never rewrite project IDs, sites, phases or facts."""
    source=snapshot['datasets'];projects=source.get('projects',{});updated=dict(projects)
    for pid,d in source.get('project_scope_decisions',{}).items():
        if d.get('active') and pid in projects and d.get('project_stamp')==project_stamp(projects[pid]) and d.get('source_stamp')==article_stamp(source.get('articles',{}).get(d.get('article_id'),{})):
            updated[pid]={**projects[pid],'scope':d['scope'],'source_scope':projects[pid].get('scope'),'confirmed_ai_project_type':{'scope':d['scope'],'quote':d['quote'],'article_id':d['article_id'],'run_id':d['run_id']}}
    return {**snapshot,'datasets':{**source,'projects':updated}}
def run_item(ds,payload,task,field):
    run=ds.get('ai_runs',{}).get(payload.get('run_id'),{})
    if run.get('status')!='completed' or run.get('task')!=task:raise ValueError('완료된 해당 AI 분석을 선택하세요.')
    key=payload.get('article_id') if field=='classifications' else payload.get('match_id')
    item=next((v for v in run.get('result',{}).get(field,[]) if v.get('article_id' if field=='classifications' else 'id')==key),None)
    if not item:raise ValueError('저장된 AI 후보를 찾을 수 없습니다.')
    return run,item
def current_evidence(ds,run,evidence):
    snapshots={a['id']:a for a in run.get('input_snapshots',[])}
    stamps={}
    for e in evidence:
        aid=e.get('article_id');a=ds.get('articles',{}).get(aid,{})
        current=public_article(a,8000);sample=snapshots.get(aid)
        if run.get('article_source_stamps',{}).get(aid)!=article_stamp(a):
            raise ValueError('적용용 기사 지문이 없거나 자료가 바뀌었습니다. 최신 표본으로 후보를 다시 검토하세요.')
        if not current or not sample or current['title']!=sample.get('title') or not current['text'].startswith(sample.get('text','')) or len(e.get('quote','').strip())<4 or e['quote'] not in sample.get('text',''):
            raise ValueError('AI 입력 기사나 인용 근거가 변경됐습니다. 최신 표본으로 재분석하세요.')
        stamps[aid]=article_stamp(a)
    if not stamps:raise ValueError('공개 인용 근거가 필요합니다.')
    return stamps
def _event(action,previous,current):
    return {'id':'cleanup-action-'+uuid.uuid4().hex,'action':action,'at':now(),'previous':deepcopy(previous),'current':deepcopy(current)}
def scope_decide(ds,payload):
    aid=payload.get('article_id');records=ds.setdefault('article_scope_decisions',{})
    if payload.get('action')=='undo':
        old=records.get(aid)
        if not old:raise ValueError('되돌릴 분류가 없습니다.')
        if old.get('active') is False:return old
        before={k:v for k,v in old.items() if k!='history'};old['active']=False;old['updated_at']=now()
        old.setdefault('history',[]).append(_event('undo',before,{k:v for k,v in old.items() if k!='history'}));return old
    if payload.get('confirmed') is not True:raise ValueError('근거를 확인한 분류만 적용하세요.')
    run,item=run_item(ds,payload,'classify','classifications')
    if item.get('scope') not in SCOPES:raise ValueError('판별 보류 후보는 확정 분류로 적용하지 않습니다.')
    stamps=current_evidence(ds,run,[{'article_id':aid,'quote':item['quote']}])
    old=records.get(aid);history=deepcopy(old.get('history',[])) if old else []
    record={'id':aid,'article_id':aid,'run_id':run['id'],'scope':item['scope'],'quote':item['quote'],'reason':item['reason'],'source_stamp':stamps[aid],'active':True,'updated_at':now()}
    history.append(_event('confirm',{k:v for k,v in (old or {}).items() if k!='history'},record));record['history']=history;records[aid]=record;return record
def apply_scopes(ds,articles,source_articles=None):
    source_articles=articles if source_articles is None else source_articles
    for aid,item in ds.get('article_scope_decisions',{}).items():
        a=articles.get(aid)
        if a and item.get('active') and article_stamp(source_articles.get(aid,{}))==item.get('source_stamp'):
            a['rule_scope_classification']=deepcopy(a.get('scope_classification'))
            a['scope_classification']={'primary_scope':item['scope'],'status':'user_confirmed_ai','reason':'confirmed_public_ai_evidence'}
            a['domain_relevance']={'status':'relevant','reason':'user_confirmed_ai_scope'}
            a['confirmed_ai_classification']={k:item[k] for k in ('run_id','scope','quote','reason','updated_at')}
def group_current(ds,group):
    return bool(group.get('state')=='approved' and all(company_stamp(ds.get('companies',{}).get(cid,{}))==stamp for cid,stamp in group.get('company_stamps',{}).items()) and all(article_stamp(ds.get('articles',{}).get(aid,{}))==stamp for aid,stamp in group.get('article_stamps',{}).items()))
def company_map(ds):
    return {cid:g['canonical_id'] for g in ds.get('company_identity_groups',{}).values() if group_current(ds,g) for cid in g['member_ids']}
def company_preview(ds,payload):
    run,item=run_item(ds,payload,'company_identity','matches')
    if item.get('assessment')!='same_legal_entity':raise ValueError('동일 법인 후보만 통합할 수 있습니다. 그룹·계열사·SPC는 구분하세요.')
    members=set((item['left_id'],item['right_id']))
    companies=ds.get('companies',{})
    targets={c['id']:c for c in run.get('target_snapshots',[])}
    for cid in members:
        if cid not in companies or cid not in targets or company_stamp(companies[cid])!=run.get('target_stamps',{}).get(cid):
            raise ValueError('기업 명칭/법인 정보가 분석 이후 변경됐습니다.')
    evidence=current_evidence(ds,run,item.get('evidence',[]))
    groups=[g for g in ds.get('company_identity_groups',{}).values() if g.get('state')=='approved' and members.intersection(g['member_ids'])]
    if len(groups)>1:raise ValueError('서로 다른 기존 통합 그룹입니다. 먼저 기존 연결을 되돌려 검토하세요.')
    old=groups[0] if groups else None
    if old and not group_current(ds,old):raise ValueError('기존 통합 그룹의 근거가 변경됐습니다. 먼저 기존 연결을 되돌리세요.')
    if old:members.update(old['member_ids'])
    if len(members)>30:raise ValueError('기업 통합 그룹은 최대 30개 원본 ID입니다.')
    canonical=payload.get('canonical_id') or (old['canonical_id'] if old else item['left_id'])
    if canonical not in members:raise ValueError('대표 기업은 선택한 원본 기업이어야 합니다.')
    for field in ('country','entity_type','registration_number','business_registration_number','parent_company_id'):
        values={str(companies[c].get(field)).strip().casefold() for c in members if companies[c].get(field)}
        if len(values)>1:raise ValueError('법인·국가·모회사 정보가 충돌합니다. 동일 그룹을 동일 법인으로 통합하지 마세요.')
    if any(companies[c].get('visibility') in ('private','internal') for c in members):raise ValueError('비공개 기업 정보는 AI 통합 대상으로 사용할 수 없습니다.')
    quote_text=' '.join(e['quote'] for e in item['evidence'])
    if re.search(r'자회사|모회사|계열사|별도\s*법인|subsidiary|parent\s+company|separate\s+legal',quote_text,re.I):raise ValueError('인용이 모회사·자회사·별도 법인 관계를 설명합니다. 동일 법인 통합을 보류하세요.')
    if old:evidence={**old['article_stamps'],**evidence}
    preview={'group_id':old['id'] if old else 'company-identity-'+digest(sorted(members))[:24],'canonical_id':canonical,'member_ids':sorted(members),'members':[{'id':c,'name':companies[c]['name']} for c in sorted(members)],'run_id':run['id'],'match_id':item['id'],'company_stamps':{c:company_stamp(companies[c]) for c in members},'article_stamps':evidence,'evidence':deepcopy(item['evidence']),'reason':item['reason'],'label':'사용자 확인 동일 법인 · 원본/역할/계약 보존'}
    preview['preview_hash']=digest(preview);return preview
def company_confirm(ds,payload):
    if payload.get('confirmed') is not True:raise ValueError('대표 기업·원본 목록·근거를 확인하세요.')
    preview=company_preview(ds,payload)
    if payload.get('preview_hash')!=preview['preview_hash']:raise ValueError('통합 미리보기가 변경됐습니다. 최신 미리보기를 다시 확인하세요.')
    groups=ds.setdefault('company_identity_groups',{});old=groups.get(preview['group_id']);before={k:v for k,v in (old or {}).items() if k!='history'}
    record={**preview,'id':preview['group_id'],'state':'approved','updated_at':now()};record.pop('preview_hash',None)
    record['history']=deepcopy(old.get('history',[])) if old else []
    record['history'].append(_event('confirm',before,{k:v for k,v in record.items() if k!='history'}));groups[record['id']]=record;return record
def company_undo(ds,payload):
    record=ds.get('company_identity_groups',{}).get(payload.get('group_id'))
    if not record:raise ValueError('되돌릴 기업 연결을 찾을 수 없습니다.')
    before={k:v for k,v in record.items() if k!='history'};record['state']='revoked';record['updated_at']=now();record.setdefault('history',[]).append(_event('undo',before,{k:v for k,v in record.items() if k!='history'}));return record
def workspace(ds,filters=None):
    from .news import classify_article,normalize_filters,_dt,_text,_geography
    filters=normalize_filters(filters);queue=[]
    identities=company_map(ds);selected_company=filters.get('company_id')
    company_ids={c for c,target in identities.items() if target==identities.get(selected_company,selected_company)} | ({selected_company} if selected_company else set())
    for a in sorted(ds.get('articles',{}).values(),key=lambda a:str(a.get('published_at','')),reverse=True):
        if not public_article(a):continue
        try:
            stamp=_dt(a['published_at'])
            if (filters['start'] and stamp<_dt(filters['start'])) or stamp>_dt(filters['end']):continue
        except (ValueError,KeyError,TypeError):continue
        if filters.get('q') and filters['q'].casefold() not in _text(a).casefold():continue
        if selected_company and not company_ids.intersection(a.get('company_ids',[])):continue
        if filters.get('project_id') and filters['project_id'] not in a.get('project_ids',[]):continue
        if filters.get('country') or filters.get('city'):
            geo=_geography(a,ds.get('projects',{}))
            if filters.get('country') and filters['country'] not in geo.get('countries',[]):continue
            if filters.get('city') and filters['city'] not in geo.get('cities',[]):continue
        decision=ds.get('article_scope_decisions',{}).get(a['id'],{})
        if decision.get('active') and decision.get('source_stamp')==article_stamp(a):continue
        classification=classify_article(a,ds.get('projects',{}))
        if classification['scope_classification'].get('primary_scope') or classification['domain_relevance']['status']=='out_of_scope':continue
        queue.append({k:deepcopy(a[k]) for k in ('id','title','url','mode','published_at') if k in a})
        if len(queue)==20:break
    decisions=[{**d,'stale':article_stamp(ds.get('articles',{}).get(d['article_id'],{}))!=d['source_stamp']} for d in sorted(ds.get('article_scope_decisions',{}).values(),key=lambda d:d.get('updated_at',''),reverse=True)[:50]]
    groups=[{**g,'stale':g.get('state')=='approved' and not group_current(ds,g)} for g in sorted(ds.get('company_identity_groups',{}).values(),key=lambda g:g.get('updated_at',''),reverse=True)[:50]]
    runs=sorted((r for r in ds.get('ai_runs',{}).values() if r.get('task') in ('classify','company_identity')),key=lambda r:r.get('created_at',''),reverse=True)[:10]
    project_candidates={r['id']:{i['article_id']:project_type_candidates(ds,r,i) for i in r.get('result',{}).get('classifications',[])} for r in runs if r.get('status')=='completed' and r.get('task')=='classify'}
    return {'unclassified_articles':queue,'project_type_candidates':project_candidates,'project_scope_decisions':list(ds.get('project_scope_decisions',{}).values()),'queue_limit':20,'queue_scope':'all_unclassified_within_period_search_geography','history_limit':50,'counts':{'scope_decisions':len(ds.get('article_scope_decisions',{})),'company_groups':len(ds.get('company_identity_groups',{}))},'scope_decisions':decisions,'company_groups':groups,'runs':[{k:r.get(k) for k in ('id','task','status','article_ids','created_at','error')} for r in runs]}
def validate_records(ds):
    def require(value):
        if not value:raise ValueError('AI 정리 원본 참조/이력 형식이 올바르지 않습니다.')
    for pid,record in ds.get('project_scope_decisions',{}).items():
        require(record.get('id')==pid==record.get('project_id') and pid in ds.get('projects',{}) and record.get('article_id') in ds.get('articles',{}) and record.get('scope') in SCOPES and type(record.get('active')) is bool)
        run,item=run_item(ds,record,'classify','classifications')
        require(record.get('quote')==item.get('quote') and record['scope']==item.get('scope') and record.get('source_stamp')==run.get('article_source_stamps',{}).get(record['article_id']))
        require(all(isinstance(record.get(k),str) and bool(re.fullmatch('[0-9a-f]{64}',record[k])) for k in ('source_stamp','project_stamp')) and isinstance(record.get('history'),list) and bool(record['history']))
    for aid,record in ds.get('article_scope_decisions',{}).items():
        require(record.get('id')==aid==record.get('article_id') and aid in ds.get('articles',{}) and record.get('scope') in SCOPES and type(record.get('active')) is bool)
        run,item=run_item(ds,record,'classify','classifications')
        require(record.get('quote')==item.get('quote') and record['scope']==item.get('scope') and isinstance(record.get('source_stamp'),str) and bool(re.fullmatch('[0-9a-f]{64}',record['source_stamp'])))
        require(record.get('source_stamp')==run.get('article_source_stamps',{}).get(aid))
        require(isinstance(record.get('history'),list) and bool(record['history']))
    used=set()
    for gid,group in ds.get('company_identity_groups',{}).items():
        members=group.get('member_ids',[])
        require(group.get('id')==gid==group.get('group_id') and isinstance(members,list) and 2<=len(members)<=30 and len(set(members))==len(members) and all(c in ds.get('companies',{}) for c in members) and group.get('canonical_id') in members and group.get('state') in ('approved','revoked'))
        require(set(group.get('company_stamps',{}))==set(members) and bool(group.get('article_stamps')) and all(a in ds.get('articles',{}) for a in group['article_stamps']))
        require(all(isinstance(s,str) and bool(re.fullmatch('[0-9a-f]{64}',s)) for s in [*group['company_stamps'].values(),*group['article_stamps'].values()]))
        run,item=run_item(ds,group,'company_identity','matches');require(item.get('assessment')=='same_legal_entity' and {item['left_id'],item['right_id']}<=set(members))
        require(isinstance(group.get('history'),list) and bool(group['history']))
        if group['state']=='approved':require(not used.intersection(members));used.update(members)
