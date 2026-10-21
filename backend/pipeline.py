"""Manual-gold fixture replay and metadata import. No network or paid AI calls."""
from copy import deepcopy
from datetime import datetime, timezone, date
import hashlib
import ipaddress
import json
import math
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .security import assert_safe_url

DATASETS = ('projects','companies','articles','claims','relationships','changes','read_states','bookmarks','internal_links','notifications','settings','jobs','coverage','extraction_runs','audit')
POWER_UNITS = {'kW':0.001,'MW':1,'GW':1000}
CAPACITY_UNITS = {'announced_capacity':set(POWER_UNITS),'it_capacity':set(POWER_UNITS),'grid_capacity':set(POWER_UNITS),'generation_capacity':set(POWER_UNITS),'apparent_power':{'MVA'}}

def _now():
    return datetime.now(timezone.utc).isoformat()

def _id(prefix, value):
    return prefix + '-' + hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]

def normalize_url(value):
    value=assert_safe_url(value)
    if not isinstance(value,str) or len(value)>4096 or any(ord(c)<32 for c in value):
        raise ValueError('A public HTTP(S) URL is required')
    p=urlsplit(value.strip())
    if p.scheme.lower() not in ('http','https') or not p.hostname or p.username is not None or p.password is not None:
        raise ValueError('Only public HTTP(S) URLs without credentials are accepted')
    host=p.hostname.lower().rstrip('.')
    if host in ('localhost','localhost.localdomain') or host.endswith(('.localhost','.local','.internal')) or '.' not in host:
        raise ValueError('Local/private hosts are not accepted')
    try:
        ip=ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host) or '..' in host:
            raise ValueError('Invalid public hostname')
        # Reject alternative numeric IPv4 representations too; no DNS or fetch is performed.
        if host.replace('.','').isdigit() or host.startswith('0x'):
            raise ValueError('Numeric host representation is not accepted')
    else:
        if not ip.is_global:
            raise ValueError('Local/private IP addresses are not accepted')
    try:
        port=p.port
    except ValueError as exc:
        raise ValueError('Invalid port') from exc
    host=host.encode('idna').decode('ascii')
    if ':' in host:host='['+host+']'
    authority=host+((':'+str(port)) if port and not (p.scheme.lower()=='https' and port==443 or p.scheme.lower()=='http' and port==80) else '')
    query=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid','mc_cid','mc_eid')]
    path=p.path.rstrip('/') or '/'
    return urlunsplit((p.scheme.lower(),authority,path,urlencode(sorted(query)),''))

def _content_hash(article):
    body=article.get('evidence_excerpt') or article.get('summary') or article.get('title','')
    if isinstance(body,list):body=' '.join(body)
    return hashlib.sha256(re.sub(r'\s+',' ',str(body)).strip().casefold().encode('utf-8')).hexdigest()

def _date(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise ValueError('Expected ISO event date YYYY-MM-DD') from exc

def _datasets(ds):
    for name in DATASETS:ds.setdefault(name,{})

def _defaults(ds, now):
    _datasets(ds)
    ds['settings'].setdefault('app',{'id':'app','collection_enabled':False,'collection_interval_minutes':60,'digest_hour':18,'collection_mode':'fixture_mock','collection_notice':'Fixed official manual-gold fixture replay only; no live collection.','api':{'mode':'mock','endpoint':'','protocol':'unconfigured','model':'','auth_type':'bearer','secret_ref':'','verified':False}})
    ds['jobs'].setdefault('collection',{'id':'collection','status':'idle','mode':'fixture_mock','watermark':None,'last_run':None,'count':0,'live_collection':False})
    for scope in ('kr-dc','kr-ai','global-ai'):
        ds['coverage'].setdefault(scope,{'id':scope,'scope':scope,'mode':'fixture_mock','status':'not_live','article_count':0,'notice':'Only a fixed manual-gold fixture is replayed. No live search, backfill or complete coverage is claimed.','checked_at':now})

def _validate_bundle(bundle, ds):
    if bundle.get('mode')!='fixture_mock':raise ValueError('Fixture ingestion requires explicit fixture_mock mode')
    articles={a['id']:a for a in bundle.get('articles',[])}
    projects={p['id']:p for p in bundle.get('projects',[])}
    companies={c['id']:c for c in bundle.get('companies',[])}
    for key in ('articles','projects','companies','claims','relationships'):
        ids=[x['id'] for x in bundle.get(key,[])]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate record IDs in fixture '+key)
    for a in articles.values():
        normalize_url(a['url']);_date(a['published_at']);_date(a['event_date'])
        if not a.get('evidence_excerpt') or not a.get('summary'):raise ValueError('Fixture article requires evidence and summary')
    for p in projects.values():
        if p.get('scope') not in ('kr-dc','kr-ai','global-ai') or p.get('entity_level') not in ('program','site','phase'):raise ValueError('Invalid project scope or entity level')
        if not isinstance(p.get('summary'),list) or not 3<=len(p['summary'])<=5:raise ValueError('Project summary must contain 3 to 5 lines')
        parent=p.get('parent_id')
        if parent and parent not in projects and parent not in ds['projects']:raise ValueError('Missing project parent')
        visited={p['id']};cursor=parent
        while cursor:
            if cursor in visited:raise ValueError('Project hierarchy cycle')
            visited.add(cursor);cursor=projects.get(cursor,ds['projects'].get(cursor,{})).get('parent_id')
        if any(cid not in companies and cid not in ds['companies'] for cid in p.get('company_ids',[])):raise ValueError('Missing project company')
        if any(aid not in articles and aid not in ds['articles'] for aid in p.get('article_ids',[])):raise ValueError('Missing project article')
    for c in bundle.get('claims',[]):
        a=articles.get(c.get('article_id')) or ds['articles'].get(c.get('article_id'))
        p=projects.get(c.get('project_id')) or ds['projects'].get(c.get('project_id'))
        if not a or not p:raise ValueError('Claim requires an existing article and project')
        excerpt=c.get('evidence_excerpt','')
        if not excerpt or excerpt not in a.get('evidence_excerpt',''):raise ValueError('Claim evidence is missing or absent from article excerpt')
        pred=c.get('predicate');unit=c.get('unit');value=c.get('value')
        if pred not in CAPACITY_UNITS or unit not in CAPACITY_UNITS[pred]:raise ValueError('Invalid capacity metric/unit combination')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('Capacity must be a finite positive number')
        # Manual gold must tie the asserted number to the short evidence locator.
        numbers=[float(x) for x in re.findall(r'\d+(?:\.\d+)?',excerpt)]
        if value not in numbers:raise ValueError('Claim value is absent from its evidence locator')
        unit_aliases={'kW':r'kW|kilowatts?', 'MW':r'MW|megawatts?', 'GW':r'GW|gigawatts?', 'MVA':r'MVA'}
        if not re.search(r'(?<![A-Za-z])(?:'+unit_aliases[unit]+r')(?![A-Za-z])',excerpt,re.I):raise ValueError('Claim unit is absent from its evidence locator')
        metric_evidence={
            'it_capacity':r'\bIT\b|IT부하|information technology',
            'grid_capacity':r'\bgrid\b|수전',
            'generation_capacity':r'\bgeneration\b|\bgenerat(?:ing|ion)\b|발전',
            'apparent_power':r'\bapparent\s+power\b|피상\s*전력|\bMVA\b',
        }
        if pred in metric_evidence and not re.search(metric_evidence[pred],excerpt,re.I):
            raise ValueError('Capacity type must be explicitly identified by the source: '+pred)
        if c.get('scope')!=p['entity_level'] or c.get('basis') not in ('planned','announced_actual','actual'):raise ValueError('Claim scope/basis mismatch')
        if c.get('validation_state')!='manual_gold_verified':raise ValueError('Only manually verified gold claims may be auto-applied')
        _date(c['event_date'])
    for rel in bundle.get('relationships',[]):
        if rel.get('project_id') not in projects and rel.get('project_id') not in ds['projects']:raise ValueError('Missing relationship project')
        if rel.get('company_id') not in companies and rel.get('company_id') not in ds['companies']:raise ValueError('Missing relationship company')
        if rel.get('directness')!='explicit' or not rel.get('role'):raise ValueError('Relationship requires an explicit source role')
        if not rel.get('article_ids') or any(a not in articles and a not in ds['articles'] for a in rel['article_ids']):raise ValueError('Relationship requires source articles')

def _apply_claim(ds, claim):
    """Preserve every gold claim; return whether the selected factual value changed."""
    cid=claim['id']
    if cid in ds['claims']:
        if ds['claims'][cid]!=claim:raise ValueError('Immutable claim ID collision')
        return False
    ds['claims'][cid]=deepcopy(claim)
    p=ds['projects'][claim['project_id']]
    slot=(claim['predicate'],claim['scope'],claim['basis'])
    capacities=p.setdefault('capacities',[])
    current=next((c for c in capacities if (c['metric'],c['scope'],c['basis'])==slot),None)
    candidate={k:claim[k] for k in ('value','unit','basis','scope','event_date')}
    candidate.update({'metric':claim['predicate'],'claim_id':cid})
    if current:
        old_mw=current['value']*POWER_UNITS.get(current['unit'],1)
        new_mw=claim['value']*POWER_UNITS.get(claim['unit'],1)
        same_value=old_mw==new_mw
        selected=claim['event_date']>current['event_date']
        reason=('newer_same_value_confirmation' if same_value else 'newer_substantive_event') if selected else 'older_or_same_date_event_preserved'
        p.setdefault('capacity_history',[]).append({'previous':deepcopy(current),'candidate':deepcopy(candidate),'candidate_selected':selected,'value_changed':not same_value,'reason':reason,'recorded_at':_now()})
        if not selected:return False
        capacities.remove(current)
        capacities.append(candidate)
        return not same_value
    capacities.append(candidate)
    return True

def _milestone_key(milestone):
    return tuple(milestone.get(k) for k in ('kind','date','precision','basis'))

def _ingest(ds,bundle,now):
    _defaults(ds,now)
    _validate_bundle(bundle,ds)
    accepted=[];deduplicated=0;article_map={}
    by_url={a.get('canonical_url',normalize_url(a['url'])):a['id'] for a in ds['articles'].values()}
    by_hash={a.get('content_hash',_content_hash(a)):a['id'] for a in ds['articles'].values()}
    for incoming in bundle.get('articles',[]):
        article=deepcopy(incoming);canonical=normalize_url(article['url']);content=_content_hash(article)
        duplicate=by_url.get(canonical) or by_hash.get(content)
        if duplicate:
            article_map[article['id']]=duplicate;deduplicated+=1;continue
        aid=article['id']
        if aid in ds['articles']:raise ValueError('Article ID collision')
        article.update({'url':canonical,'canonical_url':canonical,'content_hash':content,'collected_at':now,'mode':'fixture_mock','extraction_mode':'manual_gold_mock','current_status_verified':False})
        ds['articles'][aid]=article;accepted.append(aid);article_map[aid]=aid;by_url[canonical]=aid;by_hash[content]=aid
    # Collection, evidence freshness and substantive business changes are separate concepts.
    changed={};incoming_projects={p['id']:p for p in bundle.get('projects',[])}
    prior_projects=deepcopy(ds['projects'])
    def record_change(pid,aids,event,reason):
        item=changed.setdefault(pid,{'article_ids':set(),'event_dates':[],'reasons':[]})
        item['article_ids'].update(aids);item['event_dates'].append(event)
        if reason not in item['reasons']:item['reasons'].append(reason)
    if accepted:
        for company in bundle.get('companies',[]):
            if company['id'] not in ds['companies']:ds['companies'][company['id']]=deepcopy(company)
            else:
                record=ds['companies'][company['id']]
                record['project_ids']=sorted(set(record.get('project_ids',[])+company.get('project_ids',[])))
        for incoming in bundle.get('projects',[]):
            mapped=[article_map.get(a,a) for a in incoming['article_ids']]
            new_aids=[a for a in mapped if a in accepted]
            if not new_aids:continue
            p=deepcopy(incoming);p['article_ids']=mapped
            event=max(ds['articles'][a]['event_date'] for a in new_aids)
            existing=ds['projects'].get(p['id'])
            if not existing:
                p['capacities']=[];p['status_event_date']=event;p['evidence_updated_at']=event
                ds['projects'][p['id']]=p
                record_change(p['id'],new_aids,event,'new_project')
                continue
            previous=prior_projects[p['id']]
            existing['article_ids']=list(dict.fromkeys(existing.get('article_ids',[])+mapped))
            existing['company_ids']=list(dict.fromkeys(existing.get('company_ids',[])+p.get('company_ids',[])))
            status_date=existing.get('status_event_date',existing['latest_change_at'])
            if p.get('status')!=existing.get('status'):
                selected=event>status_date
                existing.setdefault('status_history',[]).append({'previous':existing.get('status'),'candidate':p.get('status'),'event_date':event,'article_ids':new_aids,'candidate_selected':selected})
                if selected:
                    existing['status']=p['status'];existing['status_event_date']=event
                    record_change(p['id'],new_aids,event,'explicit_status_change')
            elif event>status_date:
                existing['status_event_date']=event
            known_milestones={_milestone_key(m) for m in existing.get('milestones',[])}
            for milestone in p.get('milestones',[]):
                if _milestone_key(milestone) not in known_milestones:
                    existing.setdefault('milestones',[]).append(deepcopy(milestone));known_milestones.add(_milestone_key(milestone))
                    if event>=previous.get('evidence_updated_at',previous['latest_change_at']):
                        record_change(p['id'],new_aids,event,'explicit_milestone_change')
            existing['evidence_updated_at']=max(event,existing.get('evidence_updated_at',existing['latest_change_at']))
        for incoming in bundle.get('claims',[]):
            claim=deepcopy(incoming);claim['article_id']=article_map.get(claim['article_id'],claim['article_id'])
            if claim['article_id'] in accepted:
                if _apply_claim(ds,claim):record_change(claim['project_id'],[claim['article_id']],claim['event_date'],'latest_capacity_value_changed')
                p=ds['projects'][claim['project_id']]
                p['evidence_updated_at']=max(claim['event_date'],p.get('evidence_updated_at',p['latest_change_at']))
        for incoming in bundle.get('relationships',[]):
            rel=deepcopy(incoming);rel['article_ids']=[article_map.get(a,a) for a in rel['article_ids']]
            aids=[a for a in rel['article_ids'] if a in accepted]
            if not aids:continue
            semantic=(rel['project_id'],rel['company_id'],rel['role'])
            existing=next((r for r in ds['relationships'].values() if (r['project_id'],r['company_id'],r['role'])==semantic),None)
            if existing:
                existing['article_ids']=list(dict.fromkeys(existing.get('article_ids',[])+rel['article_ids']))
                existing['claim_ids']=list(dict.fromkeys(existing.get('claim_ids',[])+rel.get('claim_ids',[])))
            else:
                if rel['id'] in ds['relationships']:raise ValueError('Relationship ID collision')
                ds['relationships'][rel['id']]=rel
                p=ds['projects'][rel['project_id']]
                if rel['company_id'] not in p['company_ids']:p['company_ids'].append(rel['company_id'])
                company=ds['companies'][rel['company_id']]
                if p['id'] not in company['project_ids']:company['project_ids'].append(p['id'])
                event=max(ds['articles'][a]['event_date'] for a in aids)
                prior=prior_projects.get(p['id'])
                if not prior or event>=prior.get('evidence_updated_at',prior['latest_change_at']):
                    record_change(p['id'],aids,event,'explicit_new_relationship')
        for pid,change in changed.items():
            p=ds['projects'][pid];aids=sorted(change['article_ids']);event=max(change['event_dates'])
            incoming=incoming_projects.get(pid)
            if incoming and event>=p['latest_change_at']:
                for key in ('summary','importance','importance_reasons'):p[key]=deepcopy(incoming[key])
            p['latest_change_at']=max(p['latest_change_at'],event)
            change_id=_id('change',pid+'|'+','.join(aids))
            ds['changes'].setdefault(change_id,{'id':change_id,'project_id':pid,'article_ids':aids,'summary':deepcopy(p['summary']),'kind':'official_fixture_announcement','meaningful_at':event,'importance':p['importance'],'created_at':now,'mode':'fixture_mock','change_reasons':change['reasons']})
            notification_id='notice-'+change_id
            ds['notifications'].setdefault(notification_id,{'id':notification_id,'change_id':change_id,'project_id':pid,'title':p['name']+' · fixed fixture replay','severity':'important','created_at':now,'read_at':None,'desktop_delivered':False,'mode':'fixture_mock'})
    for scope in ('kr-dc','kr-ai','global-ai'):
        aids={a for p in ds['projects'].values() if p['scope']==scope for a in p['article_ids']}
        ds['coverage'][scope].update({'article_count':len(aids),'project_count':sum(p['scope']==scope for p in ds['projects'].values()),'checked_at':now})
    from .news import enrich_articles
    enrich_articles(ds,list(ds['articles']))
    ds['jobs']['collection'].update({'status':'completed','mode':'fixture_mock','last_run':now,'watermark':max((a['event_date'] for a in ds['articles'].values() if a.get('event_date')),default=None),'count':len(accepted),'changes_count':len(changed),'deduplicated':deduplicated,'live_collection':False})
    run_id=_id('run',now)
    ds['extraction_runs'][run_id]={'id':run_id,'mode':'fixture_mock','created_at':now,'accepted_articles':len(accepted),'substantive_changes':len(changed),'deduplicated':deduplicated,'status':'completed','real_ai_verified':False}
    return {'status':'completed','count':len(accepted),'changes_count':len(changed),'deduplicated':deduplicated,'mode':'fixture_mock','live_collection':False}

def _fixture(root):
    from pathlib import Path
    return json.loads((Path(root)/'fixtures/official_manual_gold.json').read_text(encoding='utf-8'))

def initialize_datasets(ds, root):
    """Called only within the repository writer transaction/initialization."""
    fresh = not any(bool(value) for value in ds.values())
    if fresh:
        return _ingest(ds, _fixture(root), _now())
    _defaults(ds, _now())
    return {'status':'existing_state_preserved','count':0,'changes_count':0,'mode':'fixture_mock','live_collection':False}


def bootstrap(repo,root):
    # Check again inside the write transaction to preserve state even under concurrent startup.
    result={}
    def mutate(ds):
        result.update(initialize_datasets(ds, root))
    repo.transact(mutate)
    return result

def collect(repo,root):
    bundle=_fixture(root);result={}
    def mutate(ds):result.update(_ingest(ds,bundle,_now()))
    repo.transact(mutate)
    return result

def import_article(repo,payload):
    if not isinstance(payload,dict):raise ValueError('Expected an article object')
    title=str(payload.get('title','')).strip()
    if not title or len(title)>500:raise ValueError('A title of 1 to 500 characters is required')
    url=normalize_url(payload.get('url',''))
    summary=payload.get('summary','')
    if isinstance(summary,list):summary='\n'.join(str(x) for x in summary)
    if not isinstance(summary,str) or len(summary)>20000:raise ValueError('Summary must be text, at most 20000 characters')
    excerpt=payload.get('evidence_excerpt','')
    if not isinstance(excerpt,str) or len(excerpt)>2000:raise ValueError('Evidence excerpt must be text, at most 2000 characters')
    published=_date(payload.get('published_at') or _now())
    now=_now();article={'id':_id('manual',url),'title':title,'url':url,'canonical_url':url,'publisher':str(payload.get('publisher','manual input'))[:300],'published_at':published,'event_date':published,'collected_at':now,'access_status':'manual_metadata_not_fetched','summary':summary,'evidence_excerpt':excerpt,'mode':'manual','project_ids':[],'validation_state':'user_input_unverified','extraction_mode':'none','current_status_verified':False}
    article['content_hash']=_content_hash(article);result={}
    def mutate(ds):
        _defaults(ds,now)
        for existing in ds['articles'].values():
            if existing.get('canonical_url',normalize_url(existing['url']))==url or existing.get('content_hash',_content_hash(existing))==article['content_hash']:
                result.update({'status':'deduplicated','count':0,'article_id':existing['id'],'mode':'manual','fetched':False});return
        pid=payload.get('project_id')
        if pid:
            if pid not in ds['projects']:raise ValueError('Unknown project_id; ambiguous businesses are not merged automatically')
            article['project_ids']=[pid]
            ds['projects'][pid]['article_ids']=list(dict.fromkeys(ds['projects'][pid]['article_ids']+[article['id']]))
        ds['articles'][article['id']]=article
        from .news import enrich_articles
        enrich_articles(ds,[article['id']])
        from .project_discovery import enrich_discovery
        enrich_discovery(ds,[article['id']])
        result.update({'status':'imported','count':1,'article_id':article['id'],'mode':'manual','fetched':False,'claims_created':0})
    repo.transact(mutate)
    return result

def view(repo):
    return repo.snapshot()['datasets']
