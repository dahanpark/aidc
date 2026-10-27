(function(global){
  'use strict';
  const list=v=>Array.isArray(v)?v:[],scopes={'kr-dc':'국내 DC','kr-ai':'국내 AIDC','global-ai':'해외 AIDC',unresolved:'판별 보류'};
  function mount(root,opts={}){
    const doc=root.ownerDocument||global.document;
    let workspace=opts.workspace||{},mode=opts.mode==='company'?'company':'classify',busy=false,error='',notice='',prepared=null,consent=false,run=null,merge=null,mergePayload=null,mergeConsent=false;
    const limit=Math.max(1,Math.min(20,Number(opts.connection?.max_articles_per_run||3)));
    const publicArticles=list(opts.articles).filter(a=>a.mode==='live_metadata'&&!['private','internal'].includes(a.visibility));
    let selected=new Set(),acknowledged=new Set();
    const connected=()=>opts.connection?.connected===true;
    function el(tag,text,cls){const n=doc.createElement(tag);if(text!==undefined)n.textContent=String(text??'');if(cls)n.className=cls;return n;}
    function button(text,action,disabled=false){const n=el('button',text,'button small');n.type='button';n.disabled=busy||disabled;n.addEventListener('click',action);return n;}
    function check(text,value,action,disabled=false){const label=el('label',undefined,'strategy-check'),n=el('input');n.type='checkbox';n.checked=value;n.disabled=busy||disabled;n.addEventListener('change',()=>action(n.checked));label.append(n,el('span',text));return label;}
    function pool(){return mode==='classify'?list(workspace.unclassified_articles):publicArticles.slice(0,50);}
    function reset(){prepared=null;consent=false;error='';merge=null;mergeConsent=false;}
    function chooseInitial(){const wanted=new Set(list(opts.selectedArticleIds));selected=new Set(pool().filter(a=>wanted.has(a.id)).slice(0,limit).map(a=>a.id));}
    chooseInitial();
    async function action(fn){if(busy)return;busy=true;error='';render();try{await fn();}catch(e){error=String(e.message||e);if(/지원하지 않는 작업|API 경로가 없습니다|404/.test(error))error='현재 실행 서버에는 AI 정리 적용 기능이 없습니다. 원본을 유지하고 정상 종료 후 최신 CMD로 다시 실행하세요.';}finally{busy=false;render();}}
    async function refresh(){const next=await opts.loadWorkspace?.();if(next)workspace=next;}
    function sources(container,ids){list(ids).forEach(id=>container.append(button('기사 근거 '+id,()=>opts.openArticles?.([id],run?.id),!opts.openArticles)));}
    function results(container){
      if(!run)return;
      const section=el('section',undefined,'ai-cleanup-results');section.append(el('h4','저장된 AI 후보 · 확인 후 적용'),el('p',`기사 ${list(run.article_ids).length}개 표본 · ${run.model||'모델 미상'} · 자동 원본 병합 없음`));
      if(run.status!=='completed'){section.append(el('p',run.error?.message||'완료된 분석 결과가 없습니다. 자동 유료 재시도하지 않습니다.'));container.append(section);return;}
      list(run.result?.classifications).forEach(item=>{
        const row=el('article',undefined,'ai-extraction'),decision=list(workspace.scope_decisions).find(d=>d.article_id===item.article_id);
        row.append(el('strong',`${scopes[item.scope]||item.scope} · ${item.article_id}`),el('p',item.reason),el('blockquote',item.quote||'근거 부족 · 보류'));sources(row,[item.article_id]);
        if(decision?.active)row.append(el('p',`현재 확인 분류: ${scopes[decision.scope]}${decision.stale?' · 자료 변경으로 적용 보류':''}`));
        if(scopes[item.scope]&&item.scope!=='unresolved'){
          const key=run.id+':'+item.article_id,eligible=Boolean(run.article_source_stamps?.[item.article_id]);
          if(!eligible)row.append(el('p','과거 후보에 적용용 기사 지문이 없습니다. 최신 표본으로 재분석한 후보만 적용할 수 있습니다.'));
          row.append(check('인용 근거를 확인했고 이 분류를 적용합니다.',acknowledged.has(key),v=>{v?acknowledged.add(key):acknowledged.delete(key);render();},!eligible));
          row.append(button('확인한 분류 적용',()=>{if(!acknowledged.has(run.id+':'+item.article_id)||busy)return;return action(async()=>{await opts.confirmScope({run_id:run.id,article_id:item.article_id,confirmed:true});await refresh();notice='사용자 확인 분류를 적용했습니다. 원본 기사·읽음·스크랩은 유지합니다.';});},!eligible||!acknowledged.has(key)||!opts.confirmScope));
        }
        if(decision?.active)row.append(button('확인 분류 해제',()=>action(async()=>{await opts.undoScope({article_id:item.article_id,action:'undo'});await refresh();notice='규칙 기반 표시로 되돌렸습니다. 확인 이력은 보존합니다.';}),!opts.undoScope));
        list(workspace.project_type_candidates?.[run.id]?.[item.article_id]).forEach(project=>{
          const key=run.id+':project:'+project.id;
          row.append(check(project.name+' · 사업 성격 '+scopes[project.scope]+'의 인용 근거를 확인했습니다.',acknowledged.has(key),v=>{v?acknowledged.add(key):acknowledged.delete(key);render();}));
          row.append(button('확인한 사업 성격 적용',()=>{if(!acknowledged.has(key)||busy)return;return action(async()=>{await opts.confirmProjectScope({run_id:run.id,article_id:item.article_id,project_id:project.id,confirmed:true});await refresh();notice='미확인 사업의 분류 표시를 적용했습니다. 원본·부지·단계는 보존합니다.';});},!acknowledged.has(key)||!opts.confirmProjectScope));
        });
        section.append(row);
      });
      if(run.task==='company_identity')list(run.result?.matches).forEach(item=>{
        const targets=list(run.target_snapshots),name=id=>targets.find(t=>t.id===id)?.name||id,row=el('article',undefined,'ai-extraction');
        row.append(el('strong',`${name(item.left_id)} ↔ ${name(item.right_id)}`),el('p',`${{same_legal_entity:'동일 법인 후보',different:'서로 다른 법인',uncertain:'판단 보류'}[item.assessment]} · ${item.reason}`));
        list(item.evidence).forEach(e=>{row.append(el('blockquote',e.quote));sources(row,[e.article_id]);});
        if(item.assessment==='same_legal_entity')row.append(button('대표 기업 연결 미리보기',()=>action(async()=>{mergePayload={run_id:run.id,match_id:item.id};merge=await opts.previewMerge(mergePayload);mergeConsent=false;}),!opts.previewMerge));
        section.append(row);
      });
      if(!list(run.result?.classifications).length&&!list(run.result?.matches).length)section.append(el('p','이 표본에서 근거가 확보된 정리 후보가 없습니다. 전체 자료 정리 완료를 뜻하지 않습니다.'));
      if(merge){
        const panel=el('section',undefined,'strategy-preview'),select=el('select');select.setAttribute('aria-label','대표 기업');
        list(merge.members).forEach(member=>{const option=el('option',member.name);option.value=member.id;select.append(option);});select.value=merge.canonical_id;select.disabled=busy;
        select.addEventListener('change',()=>action(async()=>{mergePayload={...mergePayload,canonical_id:select.value};merge=await opts.previewMerge(mergePayload);mergeConsent=false;}));
        panel.append(el('h4','대표 기업 통합 표시 · 원본 보존'),el('p',list(merge.members).map(m=>m.name).join(' / ')),select,el('p','서로 다른 법인·자회사·SPC를 합치지 않습니다. 역할·직접 계약·수치를 새로 확정하지 않습니다. 근거가 바뀌면 적용을 보류하며 통합 해제로 원래 표시를 복구합니다.'));
        panel.append(check('이 원본들이 같은 법인임을 확인했고 대표 기업 연결에 동의합니다.',mergeConsent,v=>{mergeConsent=v;render();}));
        panel.append(button('확인한 기업 통합 표시',()=>{if(!mergeConsent||!merge||busy)return;return action(async()=>{await opts.confirmMerge({...mergePayload,canonical_id:merge.canonical_id,preview_hash:merge.preview_hash,confirmed:true});await refresh();merge=null;mergeConsent=false;notice='대표 기업으로 함께 표시합니다. 원본 회사·기사·관계 근거는 보존합니다.';});},!mergeConsent||!opts.confirmMerge));section.append(panel);
      }
      container.append(section);
    }
    function render(){
      root.replaceChildren();root.className='atlas-ai-cleanup';root.setAttribute('aria-busy',String(busy));
      root.append(el('h3','AI 자료 정리 · 근거 확인 후 적용'),el('p','소량 공개 기사 표본 → AI 후보 → 사용자 확인 → 표시 반영. 원본 삭제·자동 통합·자동 읽음 처리는 하지 않습니다.'));
      const tabs=el('div',undefined,'card-actions');
      for(const kind of ['classify','company'])tabs.append(button(kind==='classify'?'미분류 기사':'중복 기업',()=>{mode=kind;run=null;reset();chooseInitial();render();}));
      if(opts.analyseProjects)tabs.append(button('유사 사업 AI 분석 준비',()=>opts.analyseProjects(),!connected()));
      if(opts.openProjects)tabs.append(button('중복 사업 연결 검토',()=>opts.openProjects()));root.append(tabs);
      if(error){const n=el('p',error,'callout warning');n.setAttribute('role','alert');root.append(n);}
      if(notice){const n=el('p',notice,'callout');n.setAttribute('role','status');root.append(n);}
      root.append(el('p',mode==='classify'?'현재 기간·검색·기업/지역 조건의 최근 미분류 후보 최대20개입니다. 아직 범위가 없는 기사는 국내/해외 분류 탭과 별도로 검토합니다.':'현재 조회 공개 기사 중 최근50개에서 비교 표본을 선택합니다. 같은 법인이라는 명시 근거가 필요하며 회사 그룹·자회사·SPC는 구분합니다.'));
      const candidates=pool(),fieldset=el('fieldset');fieldset.append(el('legend',`전송 후보 선택 · 최대 ${limit}개`));
      if(!candidates.length)fieldset.append(el('p','현재 조건에서 검토할 공개 기사 후보가 없습니다. 기간·검색 조건을 확인하세요.'));
      candidates.forEach(a=>fieldset.append(check(a.title||a.id,selected.has(a.id),value=>{reset();if(value){if(selected.size>=limit){error=`한 번에 최대 ${limit}개까지 선택할 수 있습니다.`;}else selected.add(a.id);}else selected.delete(a.id);render();})));root.append(fieldset);
      root.append(el('p',connected()?'이 PC의 AI 연결 있음 · 표본과 사용량 확인 후 명시 실행':'AI 미연결 · 기존 결과 확인/적용·해제는 가능하며 새 분석은 연결 후 실행합니다.'));
      root.append(button('전송 표본 미리보기',()=>action(async()=>{prepared=await opts.preview(mode,{article_ids:[...selected]});consent=false;}),!connected()||!selected.size||!opts.preview));
      if(prepared){
        const panel=el('section',undefined,'strategy-preview');panel.append(el('h4','실제로 전송할 공개 입력'),el('pre',JSON.stringify({articles:prepared.articles,targets:prepared.targets||[]},null,2)),el('p',`입력 ${prepared.input_chars}/${prepared.max_input_chars}자 · 출력 최대 ${prepared.max_output_tokens}토큰 · ${prepared.truncated?'일부 입력 축약':'표본 입력'} · 자동 재시도 없음`));
        panel.append(check('위 공개 기사 전송과 개인 API 사용량 발생에 동의합니다.',consent,v=>{consent=v;render();}));
        panel.append(button('선택 표본 AI 분석 실행',()=>{if(!consent||!connected()||!prepared||busy)return;return action(async()=>{const result=await opts.analyse(mode,{article_ids:[...selected],consent_public_metadata:true});if(!['completed','cached'].includes(result.status))throw Error(result.error?.message||'분석이 완료되지 않았습니다. 자동 재시도하지 않습니다.');run=await opts.loadRun(result.run_id);prepared=null;consent=false;await refresh();notice=result.status==='cached'?'동일한 저장 분석을 재사용했습니다.':'후보를 저장했습니다. 아래 근거를 확인한 후 적용하세요.';});},!consent||!connected()||!opts.analyse||!opts.loadRun));root.append(panel);
      }
      results(root);
      const history=el('details');history.append(el('summary','최근 후보 분석·확인 분류·기업 통합 이력'));
      list(workspace.runs).forEach(item=>history.append(button(`${item.task==='classify'?'미분류':'기업 비교'} · ${item.status} · ${item.created_at||item.id}`,()=>action(async()=>{run=await opts.loadRun(item.id);merge=null;acknowledged=new Set();}),!opts.loadRun)));
      history.append(el('p',`확인 분류 ${workspace.counts?.scope_decisions??list(workspace.scope_decisions).length}개 · 기업 연결 ${workspace.counts?.company_groups??list(workspace.company_groups).length}개 · 각 최근 ${workspace.history_limit||50}개 표시, 원본 전체 이력 보존`));
      list(workspace.scope_decisions).forEach(item=>{const row=el('div');row.append(el('span',`${item.article_id} · ${scopes[item.scope]} · ${item.active?(item.stale?'자료 변경·표시 보류':'적용 중'):'해제됨'}`));sources(row,[item.article_id]);if(item.active)row.append(button('확인 분류 해제',()=>action(async()=>{await opts.undoScope({article_id:item.article_id,action:'undo'});await refresh();notice='확인 분류를 해제했습니다.';}),!opts.undoScope));history.append(row);});
      list(workspace.company_groups).forEach(item=>{const row=el('div');row.append(el('p',`${list(item.members).map(m=>m.name).join(' / ')||list(item.member_ids).join(' / ')} · ${item.state==='approved'?(item.stale?'자료 변경·표시 보류':'통합 표시 중'):'해제됨'}`));if(item.state==='approved')row.append(button('통합 해제·원본 표시',()=>action(async()=>{await opts.undoMerge({group_id:item.id});await refresh();notice='기업 통합 표시를 해제했습니다. 원본과 이력은 유지합니다.';}),!opts.undoMerge));history.append(row);});root.append(history);
      list(workspace.project_scope_decisions).forEach(item=>{if(item.active)history.append(el('p','사업 성격 확인 이력 · '+item.project_id+' · '+scopes[item.scope]),button('사업 성격 적용 해제',()=>action(async()=>{await opts.undoProjectScope({project_id:item.project_id,action:'undo'});await refresh();notice='사업 성격 표시를 원래대로 복구했습니다.';}),!opts.undoProjectScope));});
    }
    render();if(opts.initialRunId&&opts.loadRun)action(async()=>{run=await opts.loadRun(opts.initialRunId);});
    return {getSelection:()=>[...selected],getMode:()=>mode,destroy:()=>root.replaceChildren()};
  }
  global.AtlasAICleanup={mount};if(typeof module!=='undefined'&&module.exports)module.exports=global.AtlasAICleanup;
})(typeof window!=='undefined'?window:globalThis);
