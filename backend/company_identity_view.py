"""Display confirmed company aliases together without rewriting any source IDs."""
from copy import deepcopy
import json
from .ai_cleanup import group_current

def unique(values):
    seen=set();out=[]
    for v in values:
        key=json.dumps(v,ensure_ascii=False,sort_keys=True)
        if key not in seen:seen.add(key);out.append(v)
    return out

def apply(data,ds):
    groups=[g for g in ds.get('company_identity_groups',{}).values() if group_current(ds,g)]
    if not groups:return data
    mapping={cid:g['canonical_id'] for g in groups for cid in g['member_ids']}
    companies=ds.get('companies',{});contexts={g['canonical_id']:g for g in groups}
    selected={a['id'] for a in data.get('news',{}).get('articles',[])}
    article_index={a['id']:a for a in [*data.get('articles',[]),*data.get('news',{}).get('articles',[])]}
    name_map={companies[c]['name']:companies[canonical]['name'] for c,canonical in mapping.items()}
    def mapped_node(value):
        return 'company:'+mapping.get(value[8:],value[8:]) if isinstance(value,str) and value.startswith('company:') else value
    def combine(rows,key):
        first=next((r for r in rows if r.get('id')==key),rows[0]);out=deepcopy(first)
        for field in ('article_ids','company_ids','roles','profile_categories','role_evidence','profile_evidence','project_ids','verified_project_ids','candidate_project_ids','scopes','attention_ids','unread_attention_ids','source_company_ids','source_node_ids','source_edge_ids','aliases'):
            values=[v for r in rows for v in (r.get(field) if isinstance(r.get(field),list) else [])]
            if values:out[field]=unique(values)
        if any('article_ids' in r for r in rows):
            aids=out.get('article_ids',[]);out['article_count']=len(aids)
            if any('selected_article_count' in r for r in rows):out['selected_article_count']=len(selected.intersection(aids))
            if any('scope_article_counts' in r for r in rows):
                out['scope_article_counts']={scope:sum(article_index.get(a,{}).get('scope_classification',{}).get('primary_scope')==scope for a in aids) for scope in ('kr-dc','kr-ai','global-ai','unresolved')}
        if 'unread_attention_ids' in out:out['unread_count']=len(out['unread_attention_ids'])
        if isinstance(out.get('company_ids'),list):out['company_count']=len(out['company_ids'])
        for field in ('latest_at','updated_at'):
            values=[r[field] for r in rows if isinstance(r.get(field),str)]
            if values:out[field]=max(values)
        if any('keywords' in r for r in rows):
            keywords={}
            for r in rows:
                for k in r.get('keywords',[]):
                    if isinstance(k,dict) and k.get('id'):
                        old=keywords.setdefault(k['id'],deepcopy(k));old['article_ids']=unique([*old.get('article_ids',[]),*k.get('article_ids',[])]);old['article_count']=len(old['article_ids'])
            out['keywords']=list(keywords.values())
        out['id']=key;return out
    def company_rows(rows):
        grouped={}
        for r in rows:
            item=walk(r);cid=mapping.get(r['id'],r['id']);item['source_company_ids']=unique([*item.get('source_company_ids',[]),r['id']]);grouped.setdefault(cid,[]).append(item)
        result=[]
        for cid,items in grouped.items():
            if cid not in contexts:result.extend(items);continue
            item=combine(items,cid);group=contexts[cid]
            item.update(name=companies[cid]['name'],identity_group_id=group['id'],user_confirmed_identity=True,identity_label=group['label'])
            item['aliases']=unique([*item.get('aliases',[]),*(companies[c]['name'] for c in group['member_ids'])]);result.append(item)
        return result
    def graph(value):
        output={k:walk(v) for k,v in value.items() if k not in ('nodes','edges')};nodes={}
        for source in value['nodes']:
            n=walk(source);nid=mapped_node(source['id'])
            if n.get('type')=='company':
                cid=mapping.get(source.get('entity_id'),source.get('entity_id'));n['entity_id']=cid
                if cid in contexts:n.update(name=companies[cid]['name'],user_confirmed_identity=True,identity_group_id=contexts[cid]['id'])
            n['source_node_ids']=[source['id']];nodes.setdefault(nid,[]).append(n)
        output['nodes']=[combine(rows,nid) for nid,rows in nodes.items()]
        edges={};collapsed=[]
        for source in value['edges']:
            edge=walk(source);edge['source']=mapped_node(source.get('source'));edge['target']=mapped_node(source.get('target'));edge['source_edge_ids']=[source['id']]
            if edge['source']==edge['target'] and source.get('source')!=source.get('target'):collapsed.append(deepcopy(source));continue
            key=tuple(str(edge.get(k,'')) for k in ('source','target','type','role','basis','status','directness','label'))
            edges.setdefault(key,[]).append(edge)
        output['edges']=[combine(rows,rows[0]['id']) for rows in edges.values()]
        output['identity_collapsed_edges']=collapsed
        meta=output.get('graph')
        if isinstance(meta,dict):
            reduction=len(value['nodes'])-len(output['nodes'])
            meta['source_total_nodes']=meta.get('total_nodes',len(value['nodes']))
            meta['total_nodes']=max(len(output['nodes']),meta['source_total_nodes']-reduction)
            meta['displayed_nodes']=len(output['nodes'])
            meta['displayed_edges']=len(output['edges'])
            meta['truncated']=meta['total_nodes']>len(output['nodes'])
        for key,size in (('nodes',len(output['nodes'])),('edges',len(output['edges']))):
            if isinstance(output.get('counts'),dict) and key in output['counts']:output['counts'][key]=size
        return output
    def walk(value):
        if isinstance(value,list):return [walk(v) for v in value]
        if not isinstance(value,dict):return value
        if isinstance(value.get('nodes'),list) and isinstance(value.get('edges'),list):return graph(value)
        out={}
        for key,v in value.items():
            if key in ('ai','ai_cleanup','strategy','project_identity','read_states','news_read_states','jobs','coverage','news_sources','extraction_runs') or key.startswith('source_'):out[key]=deepcopy(v)
            elif key=='focus_company_id' and isinstance(v,str):out[key]=mapping.get(v,v)
            elif key=='company_id' and isinstance(v,str):
                out[key]=mapping.get(v,v)
                if out[key]!=v:out['source_company_id']=v
            elif key=='company_ids' and isinstance(v,list):
                out[key]=unique(mapping.get(c,c) for c in v)
                if out[key]!=v:out['source_company_ids']=deepcopy(v)
            elif key=='company_names' and isinstance(v,list):out[key]=unique(name_map.get(n,n) for n in v)
            elif key in ('companies','matched_companies','company_updates') and isinstance(v,list) and all(isinstance(c,dict) and 'id' in c for c in v):out[key]=company_rows(v)
            else:out[key]=walk(v)
        if isinstance(out.get('company_ids'),list):
            for field in ('company_count','hubcount'):
                if field in out:out[field]=len(out['company_ids'])
        return out
    result=walk(data)
    result['company_identity_map']=mapping
    if isinstance(result.get('company_catalog'),dict):
        catalog=result['company_catalog'];catalog.get('counts',{})['companies']=len(catalog.get('companies',[]))
        if 'role_counts' in catalog.get('counts',{}):catalog['counts']['role_counts']={r:sum(r in c.get('roles',[]) for c in catalog.get('companies',[])) for r in catalog['counts']['role_counts']}
    if isinstance(result.get('ontology',{}).get('counts'),dict) and 'companies' in result['ontology']['counts']:result['ontology']['counts']['companies']=len(result['ontology'].get('companies',[]))
    ontology=result.get('ontology',{})
    company_graph=ontology.get('company_ontology',{})
    if isinstance(company_graph.get('counts'),dict):company_graph['counts']['companies']=len(ontology.get('companies',[]))
    news=result.get('news',{})
    if isinstance(news.get('counts'),dict):news['counts']['companies']=len({c['id'] for a in news.get('articles',[]) for c in a.get('matched_companies',[])})
    return result
