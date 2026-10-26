"""User-confirmed logical project display groups; source records never merge."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
import uuid
from .repository import now
from .project_discovery import _stamp
from .news import CITIES

VERSION='project-identity-1'
LABEL='사용자 확인 연결·직접 계약 미확인'
UNKNOWN={'','unknown','unresolved','미확인','확인 필요',None}


def _hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _norm(value):
    return re.sub(r'\s+',' ',value).strip().casefold() if isinstance(value,str) else ''


def _ids(value,maximum=100):
    if not isinstance(value,list) or len(value)>maximum or any(not isinstance(v,str) or not v or len(v)>200 or any(ord(c)<32 for c in v) for v in value):
        raise ValueError('유효한 ID 배열이 필요합니다.')
    return sorted(set(value))


def _article(ds,aid):
    a=ds.get('articles',{}).get(aid,{})
    if a.get('mode')!='live_metadata' or a.get('visibility')=='private':return None
    return {'id':aid,'title':a.get('title','') if isinstance(a.get('title',''),str) else '',
            'feed_excerpt':a.get('feed_excerpt','') if isinstance(a.get('feed_excerpt',''),str) else '',
            'publisher':str(a.get('publisher',''))[:160],'published_at':str(a.get('published_at',''))[:80]}


def _strings(value):
    return [v for v in (value if isinstance(value,list) else [value]) if isinstance(v,str) and v not in UNKNOWN and len(v)<=200]


def _member(ds,kind,key,record,aid=None,parent=None):
    name=record.get('name','')
    if not isinstance(name,str) or not name or len(name)>500:return None
    aids=set(_strings(record.get('article_ids',[])))
    aids.update(_strings(record.get('article_id')))
    if aid:aids.add(aid)
    if kind=='project':
        aids.update(a for a,v in ds.get('articles',{}).items() if key in (v.get('project_ids') or []))
    aids=sorted(a for a in aids if _article(ds,a))
    location=record.get('location','') if isinstance(record.get('location',''),str) else ''
    cities=set(_strings(record.get('cities',[]))+_strings(record.get('city')))
    cities.update(city for city,(_,pattern) in CITIES.items() if location and re.search(pattern,location,re.I))
    countries=set(_strings(record.get('countries',[]))+_strings(record.get('country')))
    countries={ {'한국':'KR','대한민국':'KR','Korea':'KR','South Korea':'KR'}.get(c,c) for c in countries }
    phase=_strings(str(record['phase']) if type(record.get('phase')) is int else record.get('phase')) or _strings(record.get('phase_id'))
    if not phase:
        phase=[m.group(1) for m in re.finditer(r'(\d+)\s*단계|phase\s*(\d+)',name,re.I) for _ in [0] if m.group(1)]
        phase += [m.group(1) for m in re.finditer(r'phase\s*(\d+)',name,re.I)]
    phase=[re.sub(r'(?:phase|단계|\s)','',p,flags=re.I) for p in phase]
    evidence=record.get('evidence',{})
    stale=False
    if kind=='mention':
        if parent and parent.get('source_hash'):
            source=ds.get('articles',{}).get(aid or record.get('article_id'),{})
            stale=parent['source_hash']!=_stamp(source)
        if isinstance(evidence,dict) and evidence.get('field') in ('title','feed_excerpt') and evidence.get('text'):
            source=_article(ds,evidence.get('article_id') or aid or record.get('article_id'))
            stale=stale or not source or evidence['text'] not in source[evidence['field']]
    return {'ref':kind+':'+key,'kind':kind,'id':key,'name':name,'label':name,
            'aliases':sorted(set([name,*_strings(record.get('aliases',[]))])), 'article_ids':aids,
            'cities':sorted(cities),'countries':sorted(countries),'phase':sorted(set(phase)),
            'entity_level':record.get('entity_level') if record.get('entity_level') in ('program','site','phase') else 'unknown',
            'site_ids':sorted(set(_strings(record.get('site_id')))),
            'program_ids':sorted(set(_strings(record.get('program_id')))),
            'stale':bool(stale),'identity_status':'registered_source' if kind=='project' else 'article_name_candidate',
            'direct_contract_confirmed':False}


def refs(ds):
    """Safe typed references from registered records and nested/legacy mentions."""
    result={}; ambiguous=set()
    def add(item):
        if not item:return
        if item['ref'] in result:ambiguous.add(item['ref'])
        else:result[item['ref']]=item
    for key,record in ds.get('projects',{}).items():
        if isinstance(record,dict):add(_member(ds,'project',key,record))
    for key,record in ds.get('project_mentions',{}).items():
        if not isinstance(record,dict):continue
        if isinstance(record.get('mentions'),list):
            for item in record['mentions']:
                if isinstance(item,dict) and isinstance(item.get('id'),str):
                    add(_member(ds,'mention',item['id'],item,record.get('article_id',key),record))
        elif isinstance(record.get('id',key),str):
            add(_member(ds,'mention',record.get('id',key),record,record.get('article_id')))
    for ref in ambiguous:result[ref]['stale']=True;result[ref]['ambiguous_reference']=True
    return result


def _conflicts(members):
    output=[]
    for field in ('cities','countries','phase','site_ids','program_ids'):
        values=[set(m[field]) for m in members if m[field]]
        if len(values)>1 and any(v!=values[0] for v in values[1:]):output.append({'code':field+'_conflict','field':field})
    levels={m['entity_level'] for m in members if m['entity_level']!='unknown'}
    if len(levels)>1:output.append({'code':'entity_level_conflict','field':'entity_level'})
    return output


def _ai_basis(ds,payload,members,evidence):
    run_id=payload.get('run_id');match_id=payload.get('match_id')
    if not run_id and not match_id:return None
    if not isinstance(run_id,str) or not isinstance(match_id,str):raise ValueError('AI 실행/후보 ID를 함께 선택하세요.')
    run=ds.get('ai_runs',{}).get(run_id,{})
    match=next((m for m in run.get('result',{}).get('matches',[]) if m.get('id')==match_id),None)
    decision=ds.get('ai_match_decisions',{}).get(match_id,{})
    if run.get('status')!='completed' or not match or decision.get('decision')!='accepted_candidate' or decision.get('run_id')!=run_id or match.get('assessment')!='possible_same':
        raise ValueError('완료된 AI 실행의 사용자가 확인한 동일 사업 후보만 연결할 수 있습니다.')
    target=match.get('target_id','')
    target_ref=target if target.startswith(('project:','mention:')) else 'project:'+target
    source=[m for m in members if match.get('article_id') in m['article_ids'] and _norm(match.get('project_name')) in {_norm(n) for n in m['aliases']} and m['ref']!=target_ref]
    if len(members)!=2 or target_ref not in {m['ref'] for m in members} or len(source)!=1 or match.get('article_id') not in evidence:
        raise ValueError('선택 참조가 제공된 AI 후보의 정확한 출처/비교 대상 쌍과 다릅니다.')
    source_article=_article(ds,match['article_id']);text='\n'.join([source_article['title'],source_article['feed_excerpt']]) if source_article else ''
    if not isinstance(match.get('quote'),str) or len(match['quote'].strip())<4 or match['quote'] not in text:
        raise ValueError('AI 후보 인용이 현재 공개 기사 근거와 다릅니다.')
    snapshot=next((a for a in run.get('input_snapshots',[]) if a.get('id')==match['article_id']),None)
    if not snapshot or snapshot.get('title')!=source_article['title'] or not isinstance(snapshot.get('text'),str) or not snapshot['text'] or not text.startswith(snapshot['text']):
        raise ValueError('AI 후보의 입력 기사와 현재 공개 근거가 다릅니다.')
    target_member=next(m for m in members if m['ref']==target_ref)
    target_snapshot=next((t for t in run.get('target_snapshots',[]) if t.get('id') in (target,target_ref)),None)
    if not target_snapshot or _norm(target_snapshot.get('name')) not in {_norm(n) for n in target_member['aliases']}:
        raise ValueError('AI 후보 비교 대상의 현재 이름이 실행 시점과 다릅니다.')
    return {'run_id':run_id,'match_id':match_id,'decision':'accepted_candidate',
            'match':{k:deepcopy(match.get(k)) for k in ('id','article_id','project_name','target_id','assessment','quote')},
            'decision_at':decision.get('at')}


def _preview(ds,payload,*,exclude_group=None):
    if not isinstance(payload,dict):raise ValueError('연결 미리보기 객체가 필요합니다.')
    raw=payload.get('member_refs');member_refs=_ids(raw,30)
    if len(member_refs)<2 or len(member_refs)!=len(raw):raise ValueError('서로 다른 참조 2~30개를 선택하세요.')
    canonical=payload.get('canonical_ref')
    if not isinstance(canonical,str) or canonical not in member_refs:raise ValueError('대표 참조는 선택 구성원이어야 합니다.')
    evidence=_ids(payload.get('evidence_article_ids'),100)
    if not evidence:raise ValueError('공개 근거 기사를 선택하세요.')
    index=refs(ds);members=[];conflicts=[]
    for ref in member_refs:
        if ref not in index:conflicts.append({'code':'missing_reference','ref':ref})
        else:
            members.append(index[ref])
            if index[ref]['stale']:conflicts.append({'code':'stale_reference','ref':ref})
    articles=[_article(ds,aid) for aid in evidence]
    if any(a is None for a in articles):conflicts.append({'code':'non_public_or_missing_evidence'})
    public=[a for a in articles if a]
    for member in members:
        eligible=[a for a in public if a['id'] in member['article_ids']]
        if not any(_norm(alias) in _norm(a['title']+'\n'+a['feed_excerpt']) for alias in member['aliases'] for a in eligible):
            conflicts.append({'code':'member_name_not_evidenced','ref':member['ref']})
    conflicts.extend(_conflicts(members))
    basis=_ai_basis(ds,payload,members,evidence)
    normalized={'canonical_ref':canonical,'member_refs':member_refs,'evidence_article_ids':evidence,
                'run_id':payload.get('run_id'),'match_id':payload.get('match_id')}
    source_hash=_hash({'version':VERSION,'members':members,'articles':public,'ai_basis':basis})
    input_hash=_hash({'request':normalized,'source_hash':source_hash})
    for group in ds.get('project_identity_groups',{}).values():
        if group.get('state')!='approved' or group.get('id')==exclude_group:continue
        if set(member_refs)&set(group.get('member_refs',[])):
            # An exact replay is idempotent; broader/different requests need an explicit group_id.
            if group.get('input_hash')!=input_hash:conflicts.append({'code':'member_already_grouped','group_id':group['id']})
    warnings=[{'code':'unknown_identity_attribute','ref':m['ref']} for m in members if not m['cities'] or not m['countries'] or m['entity_level']=='unknown']
    warnings.append({'code':'units_roles_and_direct_contract_not_identity_proof'})
    title=index.get(canonical,{}).get('name','')
    return {**normalized,'canonical_title':title,'members':members,'aliases':sorted({a for m in members for a in m['aliases']}),
            'source_article_ids':sorted({a for m in members for a in m['article_ids']}),'source_hash':source_hash,
            'input_hash':input_hash,'conflicts':conflicts,'warnings':warnings,'applicable':not conflicts,
            'label':LABEL,'direct_contract_confirmed':False,'auto_merge':False}


def preview(ds,payload):
    group_id=payload.get('group_id') if isinstance(payload,dict) else None
    if group_id and group_id not in ds.get('project_identity_groups',{}):raise ValueError('수정할 연결 그룹을 찾을 수 없습니다.')
    return _preview(ds,payload,exclude_group=group_id)


def _state(group):
    return {k:deepcopy(group.get(k)) for k in ('state','canonical_ref','canonical_title','member_refs','evidence_article_ids','source_hash','input_hash')}


def apply(ds,payload):
    if not isinstance(payload,dict) or payload.get('consent_user_confirmed') is not True:raise ValueError('대표 사업 연결을 사용자가 명시적으로 확인해야 합니다.')
    result=preview(ds,payload)
    if payload.get('input_hash')!=result['input_hash']:raise ValueError('미리보기 뒤 근거/참조가 바뀌었습니다. 다시 확인하세요.')
    if result['conflicts']:raise ValueError('참조·위치·단계 또는 그룹 충돌을 먼저 해결하세요.')
    groups=ds.get('project_identity_groups',{})
    prior=next((g for g in groups.values() if g.get('state')=='approved' and g.get('input_hash')==result['input_hash']),None)
    if prior:return deepcopy(prior)
    gid=payload.get('group_id') or 'identity-'+_hash(result['member_refs'])[:24]
    previous=groups.get(gid)
    if previous and previous.get('state')=='approved' and not payload.get('group_id'):raise ValueError('기존 그룹 변경에는 group_id를 명시하세요.')
    record={k:deepcopy(v) for k,v in result.items() if k not in ('conflicts','warnings','applicable')}
    record.update(id=gid,state='approved',updated_at=now(),version=VERSION,history=deepcopy(previous.get('history',[]) if previous else []))
    record['history'].append({'action_id':'identity-action-'+uuid.uuid4().hex,'action':'update' if previous and previous.get('state')=='approved' else 'approve',
                              'at':record['updated_at'],'previous':_state(previous) if previous else None,'current':_state(record)})
    ds.setdefault('project_identity_groups',{})[gid]=record
    return deepcopy(record)


def undo(ds,payload):
    if not isinstance(payload,dict) or payload.get('consent_user_confirmed') is not True:raise ValueError('연결 취소를 명시적으로 확인하세요.')
    group=ds.get('project_identity_groups',{}).get(payload.get('group_id'))
    if not group:raise ValueError('연결 그룹을 찾을 수 없습니다.')
    if group.get('state')=='revoked':return deepcopy(group)
    prior=_state(group);updated=deepcopy(group);updated.update(state='revoked',updated_at=now())
    updated['history'].append({'action_id':'identity-action-'+uuid.uuid4().hex,'action':'revoke','at':updated['updated_at'],'previous':prior,'current':_state(updated)})
    ds['project_identity_groups'][group['id']]=updated
    return deepcopy(updated)


def workspace(ds,article_ids=None):
    selected=set(_ids(article_ids,100000)) if article_ids is not None else None
    index=refs(ds);groups=[];active=[]
    # Validate full current references before applying a display-only article filter.
    for stored in ds.get('project_identity_groups',{}).values():
        item=deepcopy(stored)
        try:
            current=_preview(ds,stored,exclude_group=stored['id'])
            item['conflicts']=current['conflicts'];item['stale']=current['source_hash']!=stored.get('source_hash')
            item['resolvable']=len(current['members'])==len(stored.get('member_refs',[]))
        except (ValueError,TypeError,KeyError):
            item.update(conflicts=[{'code':'stale_or_invalid_basis'}],stale=True,resolvable=False)
        item['active']=item.get('state')=='approved' and not item['stale'] and not item['conflicts'] and item['resolvable']
        source_ids=sorted({aid for ref in stored.get('member_refs',[]) for aid in index.get(ref,{}).get('article_ids',[])})
        item['article_ids']=[aid for aid in source_ids if selected is None or aid in selected]
        item['article_count']=len(item['article_ids']);item['label']=LABEL
        if selected is None or item['article_ids']:groups.append(item)
        if item['active'] and (selected is None or item['article_ids']):active.append(deepcopy(item))
    visible=[deepcopy(m) for m in index.values() if selected is None or selected.intersection(m['article_ids'])]
    return {'groups':groups,'active_groups':active,'refs':visible,'by_ref':{m['ref']:m for m in visible},
            'label':LABEL,'auto_merge':False,'source_records_modified':False}


def validate_records(ds):
    """Structural/reference integrity only, never reject legitimate stale evidence.

    Source edits, changed geography and changed AI decisions are display validity
    concerns for workspace(). Missing raw references are repository corruption,
    including references retained by revoked groups and their audit history.
    """
    groups=ds.get('project_identity_groups',{})
    if not isinstance(groups,dict):raise ValueError('대표 사업 연결 원장은 ID별 JSON 객체여야 합니다.')
    if not groups:return True
    index=refs(ds);articles=ds.get('articles',{})
    def require(condition):
        if not condition:raise ValueError('대표 사업 연결 JSON 구조 또는 원본 참조가 올바르지 않습니다.')
    def strings(value,limit=100):
        require(isinstance(value,list) and len(value)<=limit and all(isinstance(v,str) and v and len(v)<=500 for v in value))
        require(len(value)==len(set(value)))
        return value
    def article_refs(value):
        for aid in strings(value,10000):require(aid in articles)
    def raw_ref(ref):
        require(isinstance(ref,str) and ref in index and not index[ref].get('ambiguous_reference'))
        kind,key=ref.split(':',1)
        if kind=='project':raw=ds['projects'][key];source_ids=_strings(raw.get('article_ids',[]))+_strings(raw.get('article_id'))
        else:
            found=[]
            for record_key,record in ds.get('project_mentions',{}).items():
                if not isinstance(record,dict):continue
                if isinstance(record.get('mentions'),list):
                    for mention in record['mentions']:
                        if isinstance(mention,dict) and mention.get('id')==key:
                            found.append((mention,record.get('article_id',record_key)))
                elif record.get('id',record_key)==key:found.append((record,record.get('article_id')))
            require(len(found)==1);raw,parent_aid=found[0]
            source_ids=_strings(raw.get('article_ids',[]))+_strings(raw.get('article_id'))+_strings(parent_aid)
            require(bool(source_ids))
        for aid in source_ids:require(aid in articles)
    def timestamp(value):
        require(isinstance(value,str))
        try:require(datetime.fromisoformat(value.replace('Z','+00:00')).tzinfo is not None)
        except (ValueError,TypeError):raise ValueError('대표 사업 연결 이력 시각이 올바르지 않습니다.') from None
    def state(value):
        require(isinstance(value,dict) and value.get('state') in ('approved','revoked'))
        member_refs=strings(value.get('member_refs'),30);require(len(member_refs)>=2)
        require(value.get('canonical_ref') in member_refs)
        require(isinstance(value.get('canonical_title'),str) and 0<len(value['canonical_title'])<=500)
        for ref in member_refs:raw_ref(ref)
        article_refs(value.get('evidence_article_ids'))
        require(bool(value['evidence_article_ids']))
        for field in ('input_hash','source_hash'):require(isinstance(value.get(field),str) and bool(re.fullmatch(r'[0-9a-f]{64}',value[field])))
    occupied={}
    for key,group in groups.items():
        require(isinstance(group,dict) and key==group.get('id') and isinstance(key,str) and bool(re.fullmatch(r'identity-[0-9a-f]{24}',key)))
        state(group)
        require(group.get('version')==VERSION and group.get('label')==LABEL)
        require(group.get('auto_merge') is False and group.get('direct_contract_confirmed') is False)
        strings(group.get('aliases'),1000);article_refs(group.get('source_article_ids'))
        timestamp(group.get('updated_at'))
        members=group.get('members');require(isinstance(members,list) and len(members)==len(group['member_refs']))
        require(all(isinstance(m,dict) and m.get('ref') in group['member_refs'] for m in members))
        require({m['ref'] for m in members}==set(group['member_refs']))
        for member in members:
            kind,ident=member['ref'].split(':',1)
            require(member.get('kind')==kind and member.get('id')==ident)
            require(isinstance(member.get('name'),str) and isinstance(member.get('label'),str))
            article_refs(member.get('article_ids'))
            for field in ('aliases','cities','countries','phase','site_ids','program_ids'):strings(member.get(field),1000)
            require(member.get('entity_level') in ('unknown','program','site','phase'))
            require(type(member.get('stale')) is bool and member.get('direct_contract_confirmed') is False)
        run_id=group.get('run_id');match_id=group.get('match_id')
        require((run_id is None and match_id is None) or (isinstance(run_id,str) and isinstance(match_id,str)))
        if run_id is not None:
            run=ds.get('ai_runs',{}).get(run_id);require(isinstance(run,dict))
            require(any(m.get('id')==match_id for m in run.get('result',{}).get('matches',[]) if isinstance(m,dict)))
        history=group.get('history');require(isinstance(history,list) and bool(history))
        action_ids=set();prior=None
        for i,event in enumerate(history):
            require(isinstance(event,dict) and set(event)=={'action_id','action','at','previous','current'})
            aid=event['action_id'];require(isinstance(aid,str) and bool(re.fullmatch(r'identity-action-[0-9a-f]{32}',aid)) and aid not in action_ids)
            action_ids.add(aid);timestamp(event['at']);require(event['action'] in ('approve','update','revoke'))
            if i==0:require(event['previous'] is None and event['action']=='approve')
            else:require(event['previous']==prior);state(event['previous'])
            state(event['current']);prior=event['current']
        require(prior==_state(group) and history[-1]['at']==group['updated_at'])
        if group['state']=='approved':
            for ref in group['member_refs']:
                require(ref not in occupied);occupied[ref]=key
    return True
