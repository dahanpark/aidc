/* Read-only, source-restricted projections for the three distinct workspaces. */
'use strict';
(() => {
  const list=value=>Array.isArray(value)?value:[];
  const entries=value=>Array.isArray(value)?value:Object.values(value||{});
  const str=value=>value===null||value===undefined?'':String(value);
  const unique=values=>[...new Set(values.filter(value=>value!==null&&value!==undefined&&str(value)).map(str))];
  const endpoint=value=>str(value&&typeof value==='object'?value.id:value);
  const clone=value=>JSON.parse(JSON.stringify(value));
  function sourceArticles(data){
    const index=new Map();list(data.news?.articles).forEach(article=>{if(article?.id!==undefined&&!index.has(str(article.id)))index.set(str(article.id),article);});
    return [...index.values()].sort((a,b)=>str(b.published_at).localeCompare(str(a.published_at))||str(a.id).localeCompare(str(b.id)));
  }
  function attentionItems(data,selected){
    const attention=data.ontology?.attention||data.attention||{};
    const seen=new Set();return list(attention.items).filter(item=>item?.id&&!seen.has(item.id)&&list(item.article_ids).some(id=>selected.has(str(id)))&&seen.add(item.id));
  }
  function dashboard(data={}){
    const articles=sourceArticles(data),selected=new Set(articles.map(a=>str(a.id))),attention=attentionItems(data,selected);
    const unreadNew=new Set(attention.filter(item=>item.type==='new_article'&&item.unread===true).flatMap(item=>list(item.article_ids).map(str)));
    const newArticles=articles.filter(article=>article.is_new===true||unreadNew.has(str(article.id))),freshIds=new Set(newArticles.map(a=>str(a.id)));
    const candidates=new Map();list(data.project_discovery?.project_candidates).forEach(candidate=>{
      if(candidate?.id===undefined||candidates.has(str(candidate.id)))return;
      const articleIds=unique(list(candidate.article_ids)).filter(id=>freshIds.has(id));
      if(articleIds.length)candidates.set(str(candidate.id),{...clone(candidate),article_ids:articleIds,article_count:articleIds.length,is_confirmed_project:false,counting_basis:'exact_name_observation_group_with_unread_article'});
    });
    const agreementArticles=articles.filter(article=>/업무\s*(?:협약|체결)|협약|입주\s*계약|계약|수주|\bMOU\b|\bmemorandum\s+of\s+understanding\b/i.test(str(article.title))).map(article=>{
      const match=str(article.title).match(/업무\s*(?:협약|체결)|협약|입주\s*계약|계약|수주|\bMOU\b|\bmemorandum\s+of\s+understanding\b/i);
      return {...clone(article),agreement_signal:{field:'title',text:match[0],start:match.index,end:match.index+match[0].length,basis:'headline_expression_observation',is_confirmed_contract:false}};
    });
    return {articles:clone(articles),new_articles:clone(newArticles),new_candidate_projects:[...candidates.values()],agreement_articles:agreementArticles,
      unread_attention:clone(attention.filter(item=>item.unread===true)),
      counts:{articles:articles.length,new_articles:newArticles.length,new_candidate_projects:candidates.size,agreement_articles:agreementArticles.length,unread_attention:attention.filter(item=>item.unread===true).length},
      counting_note:'신규 사업명 묶음은 새 기사에 연결된 명칭 관측이며 고유 신규 사업 수가 아닙니다. 협약·계약 뉴스는 제목 표현 관측이며 계약 확정이 아닙니다.',read_on_get:false};
  }
  function companyGraph(data={},companyId=''){
    const cid=str(companyId).replace(/^company:/,''),centerId='company:'+cid,articles=sourceArticles(data),articleIndex=new Map(articles.map(a=>[str(a.id),a]));
    const selected=new Set(articleIndex.keys()),order=new Map(articles.map((a,i)=>[str(a.id),i]));
    const ordered=values=>unique(values).filter(id=>selected.has(id)).sort((a,b)=>order.get(a)-order.get(b));
    const catalog=new Map();[...entries(data.companies),...entries(data.company_catalog?.companies),...entries(data.ontology?.companies)].forEach(company=>{if(company?.id!==undefined)catalog.set(str(company.id),{...catalog.get(str(company.id)),...company});});
    const sourceGraph=data.ontology?.company_ontology||{},sourceNodes=new Map(list(sourceGraph.nodes).map(node=>[str(node.id),node]));
    const company=catalog.get(cid)||sourceNodes.get(centerId);
    const empty={nodes:[],edges:[],projects:[],article_ids:[],role_groups:[],centerId,company_id:cid,counts:{companies:0,registered_projects:0,candidate_name_groups:0,articles:0},graph:{truncated:false,total_nodes:0,displayed_nodes:0},read_on_get:false};
    if(!cid||!company)return empty;
    const ownIds=new Set(ordered(list(company.article_ids)));
    articles.forEach(article=>{if(list(article.company_ids).map(str).includes(cid)||list(article.matched_companies).some(item=>str(item.id)===cid))ownIds.add(str(article.id));});
    const nodes=new Map(),edges=[],edgeIds=new Set(),projectContexts=new Map();
    const nodeFor=(id,aids=[])=>{
      const original=catalog.get(id)||sourceNodes.get('company:'+id);if(!original)return null;
      const node=nodes.get(id)||{id:'company:'+id,type:'company',entity_id:id,name:original.name||id,roles:list(original.roles).slice(),profile_categories:list(original.profile_categories).slice(),profile_evidence:clone(list(original.profile_evidence)),article_ids:[]};
      node.article_ids=ordered([...node.article_ids,...aids]);node.article_count=node.article_ids.length;nodes.set(id,node);return node;
    };
    nodeFor(cid,[...ownIds]);
    const addEdge=(otherId,input)=>{
      const other=str(otherId).replace(/^company:/,''),aids=ordered(list(input.article_ids));
      if(!other||other===cid||!aids.length||!nodeFor(other,aids))return;
      const id=str(input.id||('workspace:'+JSON.stringify([cid,other,input.basis,input.project_ids||[],aids])));if(edgeIds.has(id))return;
      edgeIds.add(id);const edge={...clone(input),id,source:centerId,target:'company:'+other,article_ids:aids,direct_contract_confirmed:input.direct_contract_confirmed===true&&input.basis==='explicit_stored_relationship'};
      edges.push(edge);nodeFor(cid,aids);
    };
    // Retain only existing one-hop company-to-company evidence, never unrelated
    // role hubs or a company clique inferred from a broad project article.
    list(sourceGraph.edges).forEach(edge=>{
      const source=endpoint(edge.source),target=endpoint(edge.target);
      if(source===centerId&&target.startsWith('company:'))addEdge(target,edge);
      else if(target===centerId&&source.startsWith('company:'))addEdge(source,edge);
    });
    const projectIndex=new Map();[...entries(data.projects),...entries(data.ontology?.projects)].forEach(project=>{if(project?.id!==undefined)projectIndex.set(str(project.id),project);});
    const participation=new Map();
    catalog.forEach((firm,id)=>list(firm.role_evidence).forEach(evidence=>{
      if(evidence.basis!=='explicit_stored_relationship'||!projectIndex.has(str(evidence.project_id)))return;
      const aids=ordered(list(evidence.article_ids));if(!aids.length)return;
      const pid=str(evidence.project_id);if(!participation.has(pid))participation.set(pid,new Map());
      const members=participation.get(pid),current=members.get(id)||{article_ids:[],roles:[]};current.article_ids=ordered([...current.article_ids,...aids]);current.roles=unique([...current.roles,evidence.role]);members.set(id,current);
    }));
    participation.forEach((members,pid)=>{
      const own=members.get(cid);if(!own)return;
      const project=projectIndex.get(pid);projectContexts.set('registered:'+pid,{...clone(project),kind:'registered',is_named_candidate:false,article_ids:own.article_ids.slice(),roles:own.roles.slice(),company_ids:[...members.keys()]});
      members.forEach((other,id)=>{if(id!==cid)addEdge(id,{id:'workspace-shared:'+pid+':'+cid+':'+id,type:'shared_project_context',project_ids:[pid],article_ids:[...own.article_ids,...other.article_ids],roles:other.roles,basis:'explicit_shared_project_context',status:'context_association',label:'같은 등록 사업의 명시 참여 · 직접 계약 미확인',direct_contract_confirmed:false});});
    });
    // Direct article names justify a dashed observation, not a participation role.
    articles.forEach(article=>{
      const aids=[str(article.id)],named=unique([...list(article.company_ids),...list(article.matched_companies).map(item=>item.id)]);
      if(!named.includes(cid))return;
      named.filter(id=>id!==cid).forEach(id=>addEdge(id,{id:'workspace-article:'+article.id+':'+cid+':'+id,type:'company_name_cooccurrence',article_ids:aids,basis:'same_article_name_observations',status:'cooccurrence_observation',label:'같은 기사 기업명 관측 · 참여·직접 계약 미확인',direct_contract_confirmed:false}));
    });
    const discovery=data.project_discovery||{},allLinks=[...list(discovery.company_links)];
    list(discovery.project_candidates).forEach(candidate=>{
      const links=[...list(candidate.company_links),...allLinks.filter(link=>str(link.project_id)===str(candidate.id))].filter(link=>ordered(list(link.article_ids)).length);
      const own=links.filter(link=>str(link.company_id)===cid),candidateAids=ordered(list(candidate.article_ids)),ownAids=ordered(own.flatMap(link=>list(link.article_ids)));
      const associated=ownAids.length?ownAids:candidateAids.filter(id=>ownIds.has(id));if(!associated.length)return;
      projectContexts.set('candidate:'+candidate.id,{...clone(candidate),kind:'candidate',is_named_candidate:true,is_confirmed_project:false,article_ids:associated,roles:unique(own.map(link=>link.role))});
      if(!own.length)return;
      const otherMembers=new Map();links.filter(link=>str(link.company_id)!==cid).forEach(link=>{const id=str(link.company_id);otherMembers.set(id,ordered([...(otherMembers.get(id)||[]),...list(link.article_ids)]));});
      otherMembers.forEach((aids,id)=>addEdge(id,{id:'workspace-candidate:'+candidate.id+':'+cid+':'+id,type:'candidate_name_context',project_ids:[str(candidate.id)],project_is_candidate:true,article_ids:[...ownAids,...aids],basis:'same_candidate_name_group_observations',status:'cooccurrence_observation',label:'같은 사업명 묶음의 기업 관측 · 동일 사업·참여 미확정',direct_contract_confirmed:false}));
    });
    // Keep registered project links below the graph even when no counterpart has
    // enough evidence for a company-to-company edge.
    projectIndex.forEach((project,pid)=>{
      const aids=ordered(list(project.article_ids)).filter(id=>ownIds.has(id));
      const ownLinks=allLinks.filter(link=>str(link.project_id)===pid&&str(link.company_id)===cid),linkIds=ordered(ownLinks.flatMap(link=>list(link.article_ids)));
      const references=ordered([...aids,...linkIds,...articles.filter(article=>ownIds.has(str(article.id))&&list(article.project_ids).map(str).includes(pid)).map(article=>article.id)]);
      if(!references.length)return;
      const key='registered:'+pid,previous=projectContexts.get(key)||{};projectContexts.set(key,{...clone(project),...previous,kind:'registered',is_named_candidate:false,article_ids:ordered([...list(previous.article_ids),...references]),roles:unique([...list(previous.roles),...ownLinks.filter(link=>link.basis==='explicit_stored_relationship').map(link=>link.role)])});
    });
    // Expand project leaves for the already established 1-hop company set only.
    // A project never pulls additional companies into the company neighborhood.
    const firmIds=new Set(nodes.keys()),firmArticles=new Map([...firmIds].map(id=>[id,new Set(ordered(list(catalog.get(id)?.article_ids)))]));
    articles.forEach(article=>unique([...list(article.company_ids),...list(article.matched_companies).map(item=>item.id)]).forEach(id=>firmArticles.get(id)?.add(str(article.id))));
    const branchProjects=new Map(),branchEdges=[];
    const category=project=>{
      const scope=project.scope||project.scope_classification?.primary_scope;
      if(scope==='kr-dc')return {project_category:'dc',project_category_label:'DC',category_basis:'stored_scope'};
      if(['kr-ai','global-ai'].includes(scope))return {project_category:'aidc',project_category_label:'AIDC',category_basis:'stored_scope'};
      if(/\bAIDC\b|\bAI\s*(?:data\s*cent(?:er|re)|DC)\b|(?:AI|인공지능)\s*데이터\s*센터/i.test(str(project.name)))return {project_category:'aidc',project_category_label:'AIDC · 명칭 관측',category_basis:'name_observation'};
      return {project_category:'unresolved',project_category_label:'DC/AIDC 미확인',category_basis:'unresolved'};
    };
    const attach=(project,kind,id,aids,roles=[],explicit=false)=>{
      const selectedIds=ordered(aids);if(!selectedIds.length||!firmIds.has(id))return;
      const key=kind+':'+project.id,nodeId=(kind==='candidate'?'candidate:':'project:')+project.id;
      const previous=branchProjects.get(key)||{...clone(project),...category(project),kind,is_named_candidate:kind==='candidate',is_confirmed_project:kind==='candidate'?false:project.is_confirmed_project,article_ids:[],roles:[],related_company_ids:[],center_related:false};
      previous.article_ids=ordered([...previous.article_ids,...selectedIds]);previous.roles=unique([...previous.roles,...roles]);previous.related_company_ids=unique([...previous.related_company_ids,id]);previous.center_related||=id===cid;branchProjects.set(key,previous);
      branchEdges.push({id:'company-project:'+kind+':'+project.id+':'+id+':'+(explicit?'participation':'context'),source:'company:'+id,target:nodeId,type:explicit?'registered_role':'project_context',
        article_ids:selectedIds,project_ids:[str(project.id)],roles:unique(roles),basis:explicit?'explicit_stored_relationship':kind==='candidate'?'candidate_name_company_context':'article_project_company_context',
        status:explicit?'registered_evidence':'context_association',is_confirmed_participation:explicit,direct_contract_confirmed:false,
        label:explicit?'등록 사업의 명시 참여 · 회사 간 직접 계약 아님':kind==='candidate'?'사업명 후보 관측 · 동일 사업·참여 미확정':'기업·사업의 기사 맥락 · 참여·계약 미확인'});
    };
    projectIndex.forEach((project,pid)=>firmIds.forEach(id=>{
      const member=participation.get(pid)?.get(id),own=firmArticles.get(id),observed=ordered([...list(project.article_ids),...articles.filter(a=>list(a.project_ids).map(str).includes(pid)).map(a=>a.id)]).filter(aid=>own.has(aid));
      const linked=allLinks.filter(link=>str(link.project_id)===pid&&str(link.company_id)===id);
      const explicitIds=new Set(list(member?.article_ids));
      if(member)attach(project,'registered',id,list(member.article_ids),list(member.roles),true);
      attach(project,'registered',id,[...observed,...linked.flatMap(link=>list(link.article_ids))].filter(aid=>!explicitIds.has(aid)),[],false);
    }));
    list(discovery.project_candidates).forEach(project=>{
      const links=[...list(project.company_links),...allLinks.filter(link=>str(link.project_id)===str(project.id))];
      firmIds.forEach(id=>{const linked=links.filter(link=>str(link.company_id)===id),own=firmArticles.get(id);
        const aids=ordered([...list(project.article_ids).filter(aid=>own.has(str(aid))),...linked.flatMap(link=>list(link.article_ids))]);
        attach(project,'candidate',id,aids,[],false);
      });
    });
    const projects=[...branchProjects.values()].sort((a,b)=>Number(b.center_related)-Number(a.center_related)||(b.article_ids.length-a.article_ids.length)||str(a.name).localeCompare(str(b.name),'ko'));
    const projectNodes=projects.map(project=>({id:(project.kind==='candidate'?'candidate:':'project:')+project.id,type:project.kind==='candidate'?'pending':'project',entity_id:str(project.id),name:project.name||str(project.id),scope:project.scope,
      ...category(project),is_named_candidate:project.kind==='candidate',article_ids:project.article_ids,article_count:project.article_ids.length,related_company_ids:project.related_company_ids,center_related:project.center_related}));
    const allCompanies=[...nodes.values()],companyBudget=250-Math.min(projectNodes.length,100),visibleCompanies=allCompanies.slice(0,companyBudget),visibleCompanyIds=new Set(visibleCompanies.map(n=>n.id));
    const available=projectNodes.filter(node=>branchEdges.some(edge=>edge.target===node.id&&visibleCompanyIds.has(edge.source)));
    // Round-robin project categories so DC/AIDC and unresolved leaves survive a cap.
    const buckets=['aidc','dc','unresolved'].map(key=>available.filter(n=>n.project_category===key)),visibleProjects=[];
    while(visibleProjects.length<250-visibleCompanies.length&&buckets.some(bucket=>bucket.length))buckets.forEach(bucket=>{if(bucket.length&&visibleProjects.length<250-visibleCompanies.length)visibleProjects.push(bucket.shift());});
    const allNodes=[...allCompanies,...projectNodes],visible=[...visibleCompanies,...visibleProjects],visibleIds=new Set(visible.map(node=>node.id)),allEdges=[...edges,...branchEdges];
    const visibleEdges=allEdges.filter(edge=>visibleIds.has(edge.source)&&visibleIds.has(edge.target)),allAids=ordered([...ownIds,...edges.flatMap(edge=>edge.article_ids)]);
    const attention=attentionItems(data,selected);[...visible,...visibleEdges].forEach(node=>{
      const aids=new Set(node.article_ids),items=attention.filter(item=>list(item.article_ids).some(id=>aids.has(str(id)))&&item.unread===true);
      node.attention_ids=items.map(item=>item.id);node.unread_count=items.length;node.has_unread=!!items.length;node.fact_change_count=items.filter(item=>item.type==='fact_change').length;
    });
    const contextIds=new Set(allAids),roleGroups=list(sourceGraph.role_groups).map(group=>{
      const companyIds=list(group.company_ids).filter(id=>nodes.has(str(id))),aids=ordered(list(group.article_ids)).filter(id=>contextIds.has(id)),roleAids=ordered(list(group.role_evidence_article_ids)).filter(id=>contextIds.has(id));
      return {...clone(group),company_ids:companyIds,company_count:companyIds.length,article_ids:aids,article_count:aids.length,role_evidence_article_ids:roleAids};
    });
    return {nodes:visible,edges:visibleEdges,projects,article_ids:allAids,centerId,company_id:cid,role_groups:roleGroups,
      project_article_ids:ordered(branchEdges.flatMap(edge=>edge.article_ids)),
      counts:{companies:allCompanies.length,registered_projects:projects.filter(project=>project.kind==='registered').length,candidate_name_groups:projects.filter(project=>project.kind==='candidate').length,dc_projects:projects.filter(p=>p.project_category==='dc').length,aidc_projects:projects.filter(p=>p.project_category==='aidc').length,unresolved_projects:projects.filter(p=>p.project_category==='unresolved').length,articles:allAids.length},
      graph:{truncated:allNodes.length>visible.length,total_nodes:allNodes.length,displayed_nodes:visible.length,total_edges:allEdges.length,displayed_edges:visibleEdges.length,max_nodes:250},
      counting_note:'선택 기업의 1단계 관계사와 그 회사들의 관련 프로젝트를 표시합니다. 프로젝트는 DC/AIDC/미확인을 구분하며 기사 맥락·명시 참여·직접 계약은 다릅니다. 후보는 등록 사업이 아닙니다.',read_on_get:false};
  }
  (typeof window!=='undefined'?window:globalThis).AtlasWorkspaces=Object.freeze({dashboard,companyGraph});
})();
