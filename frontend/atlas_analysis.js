/* Selected public article metadata only. A pivot cell is not a contract or site count. */
'use strict';
(() => {
  const UNKNOWN='unknown';
  const DIMENSIONS=[['scope','사업 범위'],['company','기업'],['role','참여 역할'],['project','등록 사업'],['candidate','기사 사업명 후보'],['stage','기사 진행 표현'],['location','기사 관측 지역'],['category','기사 키워드'],['month','발행 월']];
  const SCOPES={'kr-dc':'국내 DC','kr-ai':'국내 AIDC','global-ai':'해외 AIDC',unresolved:'범위 분류 대기'};
  const ROLES={client:'발주처',developer:'사업자',tenant:'테넌트',operator:'운영사',contractor:'시공사',designer:'설계사',equipment_supplier:'장비사',financier:'PF사·금융주선사',unknown:'역할 미확인'};
  const STAGES={planning:'계획·개발',funding:'자금 조달',construction:'착공·공사',completed:'준공·개소',operating:'가동',cancelled:'취소·무산',unknown:'진행 표현 미확인'};
  const list=value=>Array.isArray(value)?value:[];
  const string=value=>value===null||value===undefined?'':String(value);
  const ids=values=>[...new Set(list(values).filter(value=>value!==null&&value!==undefined&&string(value).trim()).map(string))];
  const entries=value=>Array.isArray(value)?value:Object.values(value||{});
  const owns=(value,key)=>Object.prototype.hasOwnProperty.call(value,key);
  function build(data={}){
    const labels=Object.create(null);DIMENSIONS.forEach(([key])=>{labels[key]=Object.create(null);labels[key][UNKNOWN]='미확인';});
    Object.assign(labels.scope,SCOPES);Object.assign(labels.role,ROLES);Object.assign(labels.stage,STAGES);labels.candidate[UNKNOWN]='사업명 후보 미확인';
    labels.company[UNKNOWN]='기업 미확인';labels.project[UNKNOWN]='등록 사업 미확인';labels.location[UNKNOWN]='지역 미확인';labels.category[UNKNOWN]='키워드 미확인';labels.month[UNKNOWN]='발행 월 미확인';
    const companies=entries(data.ontology?.companies),projects=entries(data.projects),projectIndex=new Map();
    [...projects,...entries(data.ontology?.projects)].forEach(project=>{if(project?.id!==undefined){const id=string(project.id);projectIndex.set(id,project);labels.project[id]=string(project.name||id);}});
    companies.forEach(company=>{labels.company[string(company.id)]=string(company.name||company.id);});
    const articles=new Map();list(data.news?.articles).forEach(article=>{if(article?.id!==undefined&&!articles.has(string(article.id)))articles.set(string(article.id),article);});
    const companyByArticle=new Map(),evidenceByArticle=new Map(),candidatesByArticle=new Map();
    const add=(index,key,item)=>{if(!index.has(key))index.set(key,[]);index.get(key).push(item);};
    companies.forEach(company=>{
      const cid=string(company.id);
      ids(company.article_ids).forEach(aid=>{if(articles.has(aid))add(companyByArticle,aid,cid);});
      list(company.role_evidence).forEach(evidence=>{
        // Only the backend's explicit, source-restricted relationship projection
        // can couple a company's role with a registered project in this table.
        if(evidence.basis!=='explicit_stored_relationship'||!projectIndex.has(string(evidence.project_id)))return;
        ids(evidence.article_ids).forEach(aid=>{if(articles.has(aid))add(evidenceByArticle,aid,{company_id:cid,project_id:string(evidence.project_id),role:owns(ROLES,evidence.role)?evidence.role:UNKNOWN,basis:evidence.basis});});
      });
    });
    list(data.project_discovery?.project_candidates).forEach(candidate=>{
      if(candidate?.id===undefined||candidate.id===null)return;
      const candidateId=string(candidate.id);labels.candidate[candidateId]=string(candidate.name||candidateId);
      ids(candidate.article_ids).forEach(aid=>{
        if(!articles.has(aid))return;
        const stages=ids(list(candidate.stage_signals).filter(signal=>string(signal?.evidence?.article_id)===aid).map(signal=>owns(STAGES,signal.stage)?signal.stage:UNKNOWN));
        add(candidatesByArticle,aid,{company_id:null,project_id:null,role:UNKNOWN,candidate_id:candidateId,stage:stages.length?stages:[UNKNOWN],basis:'source_named_project_observation'});
      });
    });
    const records=[],seen=new Set();
    for(const [aid,article] of articles){
      const classification=article.scope_classification,rawScope=classification&&typeof classification==='object'?classification.primary_scope:article.scope;
      const scope=owns(SCOPES,rawScope)?rawScope:'unresolved';
      const geography=article.geography||{},domestic=scope==='kr-ai'||scope==='kr-dc';
      const places=scope==='global-ai'?ids(geography.countries).filter(code=>code!=='KR'):domestic?ids(geography.cities):[];
      const location=places.length?places:[UNKNOWN],category=ids(article.business_categories||article.categories);
      const published=string(article.published_at),stamp=string(article.published_at_kst||published);
      const month=Number.isFinite(Date.parse(stamp))&&/^\d{4}-\d{2}-/.test(stamp)?stamp.slice(0,7):UNKNOWN;
      location.forEach(id=>{labels.location[id]=id===UNKNOWN?'지역 미확인':id;});category.forEach(id=>{labels.category[id]=id;});if(month!==UNKNOWN)labels.month[month]=month;
      const base={article_id:aid,scope,location,category:category.length?category:[UNKNOWN],month,published_at:published,is_new:article.is_new===true,candidate_id:null,stage:[UNKNOWN]};
      const write=context=>{const key=JSON.stringify([aid,context.company_id,context.project_id,context.role,context.candidate_id||null]);if(!seen.has(key)){seen.add(key);records.push({...base,...context});}};
      const explicit=evidenceByArticle.get(aid)||[];explicit.forEach(write);
      const associated=new Set(companyByArticle.get(aid)||[]);
      ids(article.company_ids).forEach(cid=>associated.add(cid));
      list(article.matched_companies).forEach(company=>{if(company?.id!==undefined){const cid=string(company.id);associated.add(cid);labels.company[cid]=string(company.name||labels.company[cid]||cid);}});
      associated.forEach(cid=>{if(!owns(labels.company,cid))labels.company[cid]=cid;if(!explicit.some(evidence=>evidence.company_id===cid))write({company_id:cid,project_id:null,role:UNKNOWN,basis:'article_company_observation'});});
      // A project's article context remains independent of company observations.
      // Candidate project IDs and pending groups never become registered projects.
      const registered=ids(article.project_ids).filter(pid=>projectIndex.has(pid));
      registered.forEach(pid=>{if(!explicit.some(evidence=>evidence.project_id===pid))write({company_id:null,project_id:pid,role:UNKNOWN,basis:'registered_article_project'});});
      const identityRegistered=ids(article.identity_project_ids).filter(pid=>projectIndex.has(pid));identityRegistered.forEach(pid=>write({company_id:null,project_id:pid,role:UNKNOWN,basis:'user_confirmed_project_identity'}));
      if(!explicit.length&&!associated.size&&!registered.length&&!identityRegistered.length)write({company_id:null,project_id:null,role:UNKNOWN,basis:'article_metadata_only'});
      // Named candidates and progress expressions are independent observations.
      // They never borrow company roles or turn into registered project facts.
      (candidatesByArticle.get(aid)||[]).forEach(write);
    }
    return {records,dimensions:DIMENSIONS.map(([id,label])=>({id,label})),labels};
  }
  function pivot(model,options={}){
    const valid=new Set(DIMENSIONS.map(([id])=>id)),row=valid.has(options.row)?options.row:'scope',column=valid.has(options.column)?options.column:'role';
    const metric=['articles','companies','projects','unread','latest'].includes(options.metric)?options.metric:'articles';
    const candidateAxis=['candidate','stage'].includes(row)||['candidate','stage'].includes(column),candidateArticles=new Set(list(model.records).filter(record=>record.candidate_id).map(record=>record.article_id));
    const query=string(options.query).trim().toLocaleLowerCase('ko-KR'),label=(dimension,id)=>model.labels?.[dimension]?.[id]||id;
    const values=(record,dimension)=>dimension==='company'?[record.company_id||UNKNOWN]:dimension==='project'?[record.project_id||UNKNOWN]:dimension==='candidate'?[record.candidate_id||UNKNOWN]:['location','category','stage'].includes(dimension)?ids(record[dimension]).length?ids(record[dimension]):[UNKNOWN]:[record[dimension]||UNKNOWN];
    const accumulator=()=>({articles:new Set(),companies:new Set(),projects:new Set(),companyArticles:new Set(),projectArticles:new Set(),unread:new Set(),latest:null,latestTime:-Infinity,latestArticles:new Set()});
    const include=(bucket,record)=>{bucket.articles.add(record.article_id);if(record.company_id){bucket.companies.add(record.company_id);bucket.companyArticles.add(record.article_id);}if(record.project_id){bucket.projects.add(record.project_id);bucket.projectArticles.add(record.article_id);}if(record.is_new)bucket.unread.add(record.article_id);const time=Date.parse(record.published_at);if(Number.isFinite(time)&&time>=bucket.latestTime){if(time>bucket.latestTime){bucket.latest=record.published_at;bucket.latestTime=time;bucket.latestArticles.clear();}bucket.latestArticles.add(record.article_id);}};
    const finish=bucket=>{const sources=metric==='companies'?bucket.companyArticles:metric==='projects'?bucket.projectArticles:metric==='unread'?bucket.unread:metric==='latest'?bucket.latestArticles:bucket.articles;return {value:metric==='latest'?bucket.latest:bucket[metric].size,article_ids:[...sources].sort()};};
    const rows=new Map(),columns=new Map(),total=accumulator();
    for(const record of list(model.records)){
      // A named article uses its independent candidate contexts on candidate or
      // progress axes. Its other facts stay in the model, not a false unknown row.
      // Without any named candidate, existing contexts retain the article in the
      // unknown bucket; metric sets still deduplicate company/project contexts.
      if(candidateAxis&&candidateArticles.has(record.article_id)&&!record.candidate_id)continue;
      if(query&&!DIMENSIONS.some(([dimension])=>values(record,dimension).some(id=>string(label(dimension,id)).toLocaleLowerCase('ko-KR').includes(query))))continue;
      include(total,record);
      const rowIds=values(record,row),columnIds=values(record,column);
      rowIds.forEach(rowId=>{if(!rows.has(rowId))rows.set(rowId,{id:rowId,label:label(row,rowId),cells:new Map(),bucket:accumulator()});include(rows.get(rowId).bucket,record);});
      columnIds.forEach(columnId=>{if(!columns.has(columnId))columns.set(columnId,{id:columnId,label:label(column,columnId),bucket:accumulator()});include(columns.get(columnId).bucket,record);});
      rowIds.forEach(rowId=>columnIds.forEach(columnId=>{if(row===column&&rowId!==columnId)return;const cells=rows.get(rowId).cells;if(!cells.has(columnId))cells.set(columnId,accumulator());include(cells.get(columnId),record);}));
    }
    const ordered=items=>[...items].sort((a,b)=>a.id===UNKNOWN?b.id===UNKNOWN?0:1:b.id===UNKNOWN?-1:a.label.localeCompare(b.label,'ko',{numeric:true}));
    const finalColumns=ordered(columns.values()).map(item=>({id:item.id,label:item.label,total:finish(item.bucket)}));
    return {rows:ordered(rows.values()).map(item=>({id:item.id,label:item.label,cells:finalColumns.map(col=>({column_id:col.id,...finish(item.cells.get(col.id)||accumulator())})),total:finish(item.bucket)})),columns:finalColumns,total:finish(total),metric};
  }
  const api=Object.freeze({build,pivot});if(typeof window!=='undefined')window.AtlasAnalysis=api;else globalThis.AtlasAnalysis=api;
})();
