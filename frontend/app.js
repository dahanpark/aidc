'use strict';
(() => {
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const S = {data: null, token: '', view: 'overview', scope: 'kr-ai', query: '', includeRead: false, selected: null, selectedCompany: null, region: '', role: '', stage: '', zoom: 1, selectedArticles: new Set(), busy: false, period:'1y', newsQuery:'', country:'', city:'', newsCompany:'', newsProject:'', sourceIds:[], poll:null, request:0, closedGroups:new Set(),newsPage:1,newsContext:'',ontologySelection:null,companyRole:'all',companyFocus:null};
  const scopeLabels = {'kr-dc': '국내 DC', 'kr-ai': '국내 AIDC', 'global-ai': '해외 AIDC',unresolved:'분류 미확인'};
  const titles = {overview: ['사업의 변화에서, 다음 기회로.', '공개 근거를 따라 사업과 참여 기업의 연결을 살펴보세요.'], projects: ['사업을 한눈에, 근거는 가까이.', '프로그램·사이트·단계와 계획·실제, 용량의 기준을 구분합니다.'], companies: ['기업의 오늘에서, 향후 3년으로.', '확인된 사업 참여와 공개 일정만 모아 봅니다. 미정·장기는 별도로 표시합니다.'], sources: ['모든 연결에는 근거가 있습니다.', '공개 출처와 발행 시점, 확인된 원문 범위를 함께 확인하세요.'], bookmarks: ['다시 볼 근거를 모아 두는 곳.', '태그·폴더·직접 메모로 정리합니다. 메모는 외부 보고서에서 제외합니다.'], notifications: ['중요한 변화, 놓치지 않도록.', '저장된 변화에 대한 로컬 알림함입니다. OS 알림 발송은 연결되지 않았습니다.'], settings: ['인텔리전스의 작동 방식을 설정합니다.', '로컬 데이터, 고정 자료 재처리, 사내 AI 연결 상태를 관리합니다.']};
  titles.news=['기사에서 변화로, 근거를 연결합니다.', '중요매체 기사 · 출처별 발행시각 · 메타데이터 종합 · 통합표를 같은 조건으로 살펴보세요.'];
  titles.synthesis=['기사 종합과 관계 분석','근거를 사업·기업·역할·지역·기간으로 비교합니다.'];
  titles.regions=['지역별 AIDC 인텔리전스','국내 도시·해외 국가의 사업 후보·기업·기사를 비교합니다.'];
  const arr = (key) => Array.isArray(S.data?.[key]) ? S.data[key] : [];
  const find = (key, id) => arr(key).find(x => x.id === id);
  const text = (value, fallback = '미확인') => value === null || value === undefined || value === '' ? fallback : String(value);
  const terms = {planned:'계획',actual:'실제',announced_actual:'발표된 실제',program:'프로그램',site:'사이트',phase:'단계',announced_capacity:'발표 용량 (IT·수전 구분 미확인)',it_capacity:'IT 부하',grid_capacity:'수전 용량',generation_capacity:'발전 용량',apparent_power:'피상 전력',manual_gold_mock:'수동 정답·모의 검증',not_live:'실시간 미연결',explicit:'원문 명시',year:'연도',month:'월',day:'일'};
  const term = value => terms[value] || text(value);
  function el(tag, cls, value) { const n = document.createElement(tag); if (cls) n.className = cls; if (value !== undefined) n.textContent = value; return n; }
  function add(parent, ...children) { children.flat().forEach(n => { if (n) parent.append(n); }); return parent; }
  function button(label, cls, handler) { const n = el('button', cls || 'button', label); n.type = 'button'; n.addEventListener('click', handler); return n; }
  function badge(label, cls = '') { return el('span', `tag ${cls}`, label); }
  function safeURL(value) { try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password ? u.href : null; } catch { return null; } }
  function link(label, url, cls = '') { const href = safeURL(url); if (!href) return el('span', 'muted', `${label} · URL 미확인`); const a = el('a', cls, label); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; }
  function date(value) { if (!value) return '일자 미정'; const t = String(value); return t.slice(0, 10).replaceAll('-', '.'); }
  function toast(message, error = false) { const n = $('#toast'); n.textContent = message; n.classList.toggle('error', error); n.hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { n.hidden = true; }, 5000); }
  function unread(project) { const read = new Set(arr('read_states').map(r => r.id)); return arr('changes').some(c => c.project_id === project.id && !read.has(c.id)); }
  function projectChanges(project) { const read = new Set(arr('read_states').map(r => r.id)); return arr('changes').filter(c => c.project_id === project.id && (S.includeRead || !read.has(c.id))); }
  function projectArticles(project) { const ids = new Set(project.article_ids || []); return arr('articles').filter(a => ids.has(a.id) || (a.project_ids || []).includes(project.id)); }
  function projectCompanies(project) { return arr('companies').filter(c => (project.company_ids || []).includes(c.id) || (c.project_ids || []).includes(project.id)); }
  function matchingProjects(onlyChanges = false) {
    return arr('projects').filter(p => {
      if (S.scope !== 'all' && p.scope !== S.scope) return false;
      if (S.selectedCompany && !(p.company_ids || []).includes(S.selectedCompany) && !(find('companies', S.selectedCompany)?.project_ids || []).includes(p.id)) return false;
      if (S.region && geography(p).key !== S.region) return false;
      if (S.country && (isKorean(p) || countryName(p.country)!==countryName(S.country))) return false;
      if (S.city && (!isKorean(p) || cityName(p)!==S.city)) return false;
      if (S.stage && text(p.status, '') !== S.stage) return false;
      if (S.role && !arr('relationships').some(r => r.project_id === p.id && r.role === S.role)) return false;
      if (onlyChanges && !S.includeRead && !unread(p)) return false;
      if (S.query) {
        const corpus = [p.name, p.country, p.location, p.status, ...(p.summary || []), ...projectCompanies(p).map(c => c.name), ...projectArticles(p).map(a => a.title)].join(' ').toLocaleLowerCase();
        if (!corpus.includes(S.query.toLocaleLowerCase())) return false;
      }
      return true;
    }).sort((a,b) => (Number(b.importance) || 0) - (Number(a.importance) || 0) || text(b.latest_change_at, '').localeCompare(text(a.latest_change_at, '')) || a.id.localeCompare(b.id));
  }
  function articlesInContext(bookmarked = false) {
    const saved = new Set(arr('bookmarks').map(b => b.article_id || b.id));
    // SCRAP is a durable personal collection, independent of NEWS filters.
    const all=new Map(arr('articles').map(a=>[a.id,a]));nitems('articles').forEach(a=>all.set(a.id,a));
    const articles=bookmarked?[...all.values()].filter(a=>saved.has(a.id)):nitems('articles').slice();
    return articles.sort((a,b)=>text(b.published_at,'').localeCompare(text(a.published_at,'')));
  }
  async function api(path, payload, method = 'POST') {
    const res = await fetch(path, {method, headers: {'Content-Type': 'application/json', 'X-Atlas-Token': S.token}, body: payload === undefined ? undefined : JSON.stringify(payload), cache: 'no-store'});
    let response; try { response = await res.json(); } catch { throw new Error(`서버 응답을 읽지 못했습니다 (${res.status}).`); }
    if (!res.ok) throw new Error(text(response.error?.message || response.error || response.message, `요청 실패 (${res.status})`));
    return response;
  }
  async function load(initial = false) {
    clearTimeout(S.poll);clearTimeout(S.slowLoad);S.loadController?.abort();const controller=new AbortController();S.loadController=controller;S.loading=true;
    $('#loading').hidden=false;$('#loading').classList.toggle('is-refresh',Boolean(S.data));$('#loadingMessage').textContent=initial?'JSON 저장소에서 탐색 공간을 준비하고 있습니다.':'선택한 조건의 기사와 관계도를 준비하고 있습니다.';
    $('#viewContainer').setAttribute('aria-busy','true');
    const currentContext=newsParams().toString();if(S.newsContext!==currentContext){S.newsPage=1;S.newsContext=currentContext;S.mapSelection=null;S.dashboardArticleIds=null;S.dashboardRegionName='';}const request=++S.request;
    S.slowLoad=setTimeout(()=>{if(request===S.request)$('#loadingMessage').textContent='대량의 저장 기사와 근거를 검증하고 있습니다. 준비가 끝나면 자동으로 표시됩니다.';},8000);
    const timeout=setTimeout(()=>controller.abort(),90000);
    try {
      const response = await fetch(`/api/state?${newsParams()}`, {cache: 'no-store',signal:controller.signal});
      const envelope = await response.json();
      if (!response.ok){const failure=new Error(envelope.error||`저장소 응답 오류 (${response.status})`);failure.code=envelope.code;throw failure;}
      if(request!==S.request)return;
      if (!envelope.data || !Array.isArray(envelope.data.projects)) throw new Error('저장소 데이터 형식이 올바르지 않습니다.');
      S.data = envelope.data; S.token = envelope.csrf_token || ''; S.generation=envelope.snapshot_id;
      if(S.graphSelection&&!S.graphSelection.node?.clustered_ids){const current=[...(S.data.ontology?.nodes||[]),...(S.data.ontology?.company_ontology?.nodes||[])].find(n=>n.id===S.graphSelection.id);const edge=[...(S.data.ontology?.edges||[]),...(S.data.ontology?.company_ontology?.edges||[])].find(e=>e.id===S.graphSelection.id);S.graphSelection=current?{kind:'node',id:current.id,node:current,article_ids:current.article_ids}:edge?{kind:'edge',id:edge.id,edge,article_ids:edge.article_ids}:null;}
      S.integrityError=false;$('#errorBanner').hidden = true; $('#connection').replaceChildren(add(el('i')), document.createTextNode('로컬 저장소 연결'));
      $('#snapshot').textContent = `JSON 원본 · 스냅샷 ${text(envelope.snapshot_id, '—')}`;
      $('#asof').textContent = `저장소 기준 ${date(envelope.as_of)}`;
      syncScopeCounts();
      $('#viewContainer').hidden = false;
      const notices = S.data.attention?.counts?.unread ?? arr('notifications').filter(n => !n.read_at).length;
      $('#noticeCount').textContent = notices; $('#noticeCount').hidden = !notices;
      syncNewsControls();
      const ai=S.data.ai?.connection||{};if($('#aiConnect')){ $('#aiConnect').textContent=ai.connected?'● AI 연결됨':'AI 연결';$('#aiConnect').title=ai.connected?`${ai.provider_label} · ${ai.model} · SETTINGS에서 연결 관리`:'이 PC의 API 키로 AI 설정'; }
      render();
      if(new URLSearchParams(location.search).has('update_required')){$('#errorBanner').textContent='새 파일을 받았지만 실행 중인 서버는 구버전입니다. 진행 작업이 끝난 뒤 서버를 정상 종료하고 다시 실행해야 업데이트가 적용됩니다.';$('#errorBanner').hidden=false;}
      scheduleNewsPoll();
    } catch (error) {
      if(request!==S.request)return;
      $('#connection').textContent = '로컬 연결 끊김';
      const message=error.name==='AbortError'?'자료 준비 시간이 길어 요청을 중단했습니다.':error.message;
      S.integrityError=error.code==='store_integrity_error';$('#errorBanner').textContent = S.integrityError?message:`${message} AIDC ATLAS 바로가기로 서버를 열고 상단 새로고침을 누르세요.${S.data ? ' 마지막으로 읽은 화면을 유지합니다. 저장은 서버 연결 후 가능합니다.' : ''}`;
      $('#errorBanner').hidden = false;
      scheduleNewsPoll();
    } finally { clearTimeout(timeout);if(request===S.request){clearTimeout(S.slowLoad);S.loading=false;$('#loading').hidden=true;$('#viewContainer').setAttribute('aria-busy','false');} }
  }
  async function mutate(path, payload, success, method) { try { const result = await api(path, payload, method); await load(); if (success) toast(success); return result; } catch (error) { toast(error.message, true); throw error; } }
  function navigate(view,scopeOverride) {view=view==='sources'?'news':view;view=titles[view]?view:'overview';S.viewScopes||={};const changed=S.view!==view;if(changed)S.viewScopes[S.view]=S.scope;const nextScope=scopeOverride||(changed&&['overview','projects','companies','regions'].includes(view)?S.viewScopes[view]||(view==='companies'?'all':'kr-ai'):S.scope),changedScope=nextScope!==S.scope;if(changed||changedScope){S.graphCluster=null;S.graphSelection=null;S.mapSelection=null;S.dashboardArticleIds=null;S.dashboardRegionName='';}if(changed){S.country='';S.city='';S.region='';S.selectedCompany=null;S.newsCompany='';S.newsProject='';S.explorerMode='project';S.companyRole='all';S.explorerRole='all';S.companyCategory='all';}S.view=view;S.scope=nextScope;location.hash=view;if(changedScope){S.projectFocus=null;S.companyKeyword='';S.country='';S.city='';load();}else render();}
  function render() {
    if (!S.data) return;
    const controls=[$('.contextbar'),$('.news-searchbar'),$('#loading')];window.AtlasWorkbench?.restore($('#workspaceControlsHome'),controls);
    const root = $('#viewContainer');const previousTree=$('.retained-ontology',root);if(previousTree)S.legacyOntologyOpen=previousTree.open;root.replaceChildren();
    $$('[data-view]').forEach(n => { n.classList.toggle('active', n.dataset.view === S.view); if (n.dataset.view === S.view) n.setAttribute('aria-current', 'page'); else n.removeAttribute('aria-current'); });
    if (S.selectedCompany && !['overview','companies','projects','regions'].includes(S.view)) {
      const crumb = el('div', 'callout'); add(crumb, el('strong', '', `기업 맥락 · ${text(find('companies', S.selectedCompany)?.name)}`), document.createTextNode('　'), button('전체로 복귀 ↗', 'button small', () => { S.selectedCompany = null; S.selected = null; S.newsCompany=''; load(); })); root.append(crumb);
    }
    if(S.view==='news'&&S.newsProject)root.append(add(el('div','callout'),el('strong','',`선택 사업 · ${find('projects',S.newsProject)?.name||S.newsProject}`),button('사업 조건 해제','button small',()=>{S.newsProject='';load();})));
    ({overview: renderOverview, projects: renderProjects, companies: renderCompanies, regions:renderRegions, news:renderNews, synthesis:renderSynthesis, sources:renderNews, bookmarks: () => renderSources(true), notifications: renderNotifications, settings: renderSettings})[S.view](root);
    window.AtlasWorkbench?.compose(root,{view:S.view,controls});
  }
  function empty(title, description) { return add(el('div', 'empty'), el('span', 'empty-icon', '◈'), el('h3', '', title), el('p', '', description)); }
  function section(title, subtitle, action) { return add(el('div', 'section-head'), add(el('div'), el('h2', '', title), subtitle ? el('p', '', subtitle) : null), action); }
  const ontology = () => S.data?.ontology || {};
  const oitems = key => Array.isArray(ontology()[key]) ? ontology()[key] : [];
  function syncScopeCounts(){
    const counts=S.data?.news?.counts?.scope_counts||S.data?.news?.scope_counts||ontology().counts?.scope_articles||{};
    const total=Number(counts.all??['kr-dc','kr-ai','global-ai','unresolved'].reduce((n,key)=>n+(Number(counts[key])||0),0));
    $$('[data-scope]').forEach(b=>{const key=b.dataset.scope;let count=b.querySelector('span');if(!count){count=el('span');b.append(count);}count.textContent=`기사 ${key==='all'?total:Number(counts[key]||0)}`;b.title=`${key==='all'?'전체':scopeLabels[key]} · 같은 기간·검색 조건의 관련 기사 수`;b.classList.toggle('active',key===S.scope);b.setAttribute('aria-pressed',key===S.scope?'true':'false');});
  }
  function ontologyArticles(ids){const wanted=new Set(ids||[]);return nitems('articles').filter(a=>wanted.has(a.id));}
  function articleCollection(ids,title){
    const articles=ontologyArticles(ids),content=el('div');
    add(content,el('p','callout',`현재 선택 기간·분류 조건에 맞는 관련 기사 ${articles.length}개를 모두 취합했습니다. 제목·공개 설명 기준이며 사업 참여와 역할 확정은 별도입니다.`));
    const list=el('div','source-grid ontology-evidence-list');articles.forEach(a=>list.append(sourceCard(a,true)));content.append(list);if(!articles.length)content.append(empty('현재 기간의 연결 기사가 없습니다','고정 사례 근거는 사업 상세에서 별도로 확인하세요.'));modal(title,content);
  }
  function ontologySelection(type,id){S.ontologySelection={type,id};render();}
  function ontologyEntry(type,id){
    if(type==='all')return {id:'all',name:'선택 범위 전체',article_ids:nitems('articles').map(a=>a.id),summary:ontology().summary};
    if(type==='location')return oitems('scopes').flatMap(s=>s.location_groups||[]).find(g=>g.id===id);
    return oitems(({scope:'scopes',project:'projects',pending:'pending_groups',company:'companies'})[type]||'').find(x=>x.id===id);
  }
  function ontologySynthesis(){
    let type=S.ontologySelection?.type||'all',entry=ontologyEntry(type,S.ontologySelection?.id);
    if(!entry){type='all';entry=ontologyEntry('all','all');}
    const articles=ontologyArticles(entry.article_ids),panel=el('aside','ontology-synthesis');panel.setAttribute('aria-label','선택 관계 종합');
    add(panel,el('p','eyebrow','EVIDENCE SYNTHESIS'),el('h3','',entry.name||'선택 관계 종합'),badge(`${articles.length}개 관련 기사 취합`,'neutral'));
    const lines=el('ol','ontology-summary-lines');
    const provided=(Array.isArray(entry.summary)?entry.summary:entry.summary?[entry.summary]:[]).map(s=>typeof s==='object'?s.text:s).filter(Boolean);
    const summary=provided.slice(0,3);
    if(!summary.length)summary.push(`${articles.length}개 기사에서 ${type==='pending'?'사업 식별을 기다리는 지역·기업 이름의 동시 관측':type==='company'?'이 기업 이름의 등장과 등록 사업 근거':'선택 지역·사업 분류의 공개 소식'}을 모았습니다.`);
    if(articles.length)summary.push(`발행 범위는 ${date(articles.at(-1)?.published_at)} ~ ${date(articles[0]?.published_at)}이며, ${new Set(articles.map(a=>a.publisher)).size}개 매체의 근거를 포함합니다.`);
    const named=[...new Set(articles.flatMap(a=>(a.company_ids||[]).map(id=>find('companies',id)?.name)).filter(Boolean))];
    if(summary.length<4)summary.push(named.length?`관측 기업은 ${named.slice(0,6).join(' · ')}${named.length>6?` 외 ${named.length-6}개`:''}입니다. 이름 등장은 확인된 시공·설계·운영 역할과 구분합니다.`:'기업·역할·사업명을 확인할 근거가 부족한 기사는 식별 대기로 유지합니다.');
    if(summary.length<5)summary.push(type==='project'?'등록 사업의 정확한 명칭 연결과 후보 연결은 구분하며, 아래 근거에서 각각 확인합니다.':'사업 식별 대기 묶음은 같은 지역·기업 이름의 기사 묶음입니다. 개별 사업이나 확정 참여 관계를 새로 만든 것이 아닙니다.');
    summary.slice(0,5).forEach(s=>lines.append(el('li','',s)));panel.append(lines);
    const fresh=el('div','ontology-latest');articles.slice(0,3).forEach(a=>fresh.append(add(el('div'),link(a.title,a.url),el('small','',`${text(a.publisher)} · ${dateTime(a.published_at)}`))));panel.append(fresh);
    panel.append(button(`취합 기사 ${articles.length}개 · 전체 근거 보기 ↗`,'button primary small',()=>articleCollection(entry.article_ids,`${entry.name} · 전체 기사`)));
    if(type==='project')panel.append(button('고정 검증 사업 상세 ↗','button small',()=>{S.selected=entry.id;S.includeRead=true;$('#includeRead').checked=true;render();const next=$('.historical-projects');if(next){next.open=true;next.scrollIntoView({block:'start'});}}));
    if(type==='company')panel.append(button('기업 기사 · 종합표 ↗','button small',()=>focusNews('company',entry.id)));
    panel.append(el('p','metadata-label','제목·공개 설명의 종합 · 본문 미확인 · 사내 AI 미연결'));return panel;
  }
  function renderOntology(root){
    const data=ontology(),counts=data.counts||{},panel=el('section','ontology-panel');panel.id='ontologyMap';panel.setAttribute('aria-label','사업 관계 지도 온톨로지');
    add(panel,section('사업 관계 지도 · 온톨로지','국내 DC / 국내 AIDC / 해외 AIDC → 국내 도시·해외 국가 → 사업·식별 대기 → 기업·기사 근거',button('전체 종합','button small',()=>ontologySelection('all','all'))));
    const metrics=el('div','ontology-metrics');[['관련 기사',counts.articles??nitems('articles').length],['기사로 연결된 등록 사업',counts.verified_projects||0],['사업 식별 대기 기사',counts.pending_articles||0],['관측 기업',counts.observed_companies??oitems('companies').length]].forEach(([label,value])=>metrics.append(add(el('div'),el('strong','',Number(value).toLocaleString()),el('span','',label))));panel.append(metrics);const admission=S.data?.news?.counts||{};panel.append(el('p','metadata-label',`분류 선택 전 관련 ${Number(admission.scope_counts?.all||0)}개 / 보관 원본 ${Number(admission.archive_articles||0)}개 · 주제 외 ${Number(admission.excluded_out_of_scope||0)}개 · 주제 확인 대기 ${Number(admission.topic_unresolved||0)}개. 원본을 삭제하지 않고 동일 기간·검색 조건으로 구분합니다.`));
    const layout=el('div','ontology-layout'),tree=el('div','ontology-tree');
    oitems('scopes').forEach(scope=>{
      const column=el('article',`ontology-scope scope-${scope.id}`);column.dataset.ontologyScope=scope.id;
      column.append(button(`${scope.name||scopeLabels[scope.id]} · 기사 ${scope.article_count||0}개`,'ontology-scope-root',()=>ontologySelection('scope',scope.id)));
      (scope.location_groups||[]).forEach((group,groupIndex)=>{
        const region=el('details','ontology-location');region.open=groupIndex===0;
        region.append(el('summary','',`${group.kind==='city'?'도시':group.kind==='country'?'국가':'지역'} · ${group.name} / 기사 ${group.article_count||0}개`));
        region.append(button('이 지역 종합 보기 ↗','button text small',()=>ontologySelection('location',group.id)));
        const projects=oitems('projects').filter(p=>(group.project_ids||[]).includes(p.id));
        projects.forEach(p=>{region.append(button(`${p.name} · 기사 ${p.article_count||0}개`,'ontology-project',()=>ontologySelection('project',p.id)));const companies=el('div','ontology-company-links');(p.company_ids||[]).slice(0,5).forEach(id=>{const c=oitems('companies').find(x=>x.id===id)||find('companies',id);if(c)companies.append(button(c.name,'button text small',()=>ontologySelection('company',id)));});region.append(companies);});
        const groups=oitems('pending_groups').filter(p=>(group.pending_group_ids||[]).includes(p.id));
        groups.slice(0,8).forEach(p=>{
          const pending=el('div','ontology-pending');pending.append(button(`${p.name} · 기사 ${p.article_count||0}개`,'ontology-pending-button',()=>ontologySelection('pending',p.id)));
          const companies=el('div','ontology-company-links');(p.company_ids||[]).slice(0,4).forEach(id=>{const c=oitems('companies').find(x=>x.id===id)||find('companies',id);if(c)companies.append(button(c.name,'button text small',()=>ontologySelection('company',id)));});pending.append(companies);region.append(pending);
        });
        if(groups.length>8)region.append(el('p','metadata-label',`지도에는 주요 묶음 8개를 표시합니다. 지역 종합의 전체 기사 ${group.article_count}개에 나머지 ${groups.length-8}개 묶음의 근거도 포함됩니다.`));
        if(!projects.length&&!groups.length)region.append(el('p','muted','사업 연결을 확인할 근거가 없습니다.'));column.append(region);
      });
      if(!(scope.location_groups||[]).length)column.append(el('p','muted','현재 조건에서 취합된 기사가 없습니다.'));tree.append(column);
    });
    if(!tree.children.length)tree.append(empty('관계 근거를 정리하고 있습니다','현재 API에 온톨로지 자료가 없습니다. 저장소 새로고침 후 확인하세요.'));
    add(layout,tree,ontologySynthesis());panel.append(layout);
    add(panel,el('p','ontology-legend','실선 테두리 = 등록 사업 · 점선 테두리 = 사업 식별 대기 기사 묶음 · 기업 연결 = 이름 관측, 역할 확정과 별도'),el('p','metadata-label',`등록 사업 ${counts.registered_projects??arr('projects').length}개는 고정 검증 사례를 포함합니다. 기사 ${counts.articles??nitems('articles').length}개와 사업 개수는 서로 다른 단위입니다. 분류 미확인도 전체 기사 수에 포함합니다.`));root.append(panel);
  }
  function selectProject(id) { S.selected = id; render(); }
  function openProject(id) { S.selected=id;S.projectFocus=id; const p=find('projects',id); if(p&&!unread(p)){S.includeRead=true;$('#includeRead').checked=true;} navigate('projects',p?.scope||S.scope); }
  const visualSettings=()=>S.data?.settings?.visualization||{};
  const attentionItems=()=>S.data?.attention?.items||[];
  function itemsForGraph(selection){
    const item=selection?.node||selection?.edge||selection||{},aids=new Set(selection?.article_ids||item.article_ids||[]);
    if(Array.isArray(item.attention_ids)){const ids=new Set(item.attention_ids);return attentionItems().filter(a=>ids.has(a.id));}
    return attentionItems().filter(a=>aids.size?(a.article_ids||[]).some(id=>aids.has(id)):
      item.type==='project'?(a.project_ids||[]).includes(item.entity_id):item.type==='company'?(a.company_ids||[]).includes(item.entity_id):false);
  }
  function visualizationChoices(){
    formShell('관계도·지도 표시 기준',grid=>{
      const settings=visualSettings();
      const questions=[['ack_scope','알림 확인 범위',[['items','선택한 알림만 확인 (추천)'],['entity','선택 사업·기업 알림 전체'],['screen','현재 화면의 알림 전체']]],
        ['map_mode','사업 전체 지도',[['split','한국·세계 나란히 (추천)'],['world-inset','세계지도 + 한국 확대지도']]],
        ['position_policy','사업장 좌표 미확인',[['approximate','도시·국가 대표점에 근사 표시 (추천)'],['exact_only','정확한 사업장 좌표만 표시']]]];
      questions.forEach(([name,label,options])=>{const box=el('fieldset','visual-choice field full');box.append(el('legend','',label));options.forEach(([value,title])=>{const input=el('input');input.type='radio';input.name=name;input.value=value;input.checked=settings[name]===value;box.append(add(el('label'),input,document.createTextNode(title)));});grid.append(box);});
    },async data=>{const visualization=Object.fromEntries(['ack_scope','map_mode','position_policy'].map(k=>[k,data.get(k)]));if(Object.values(visualization).some(v=>!v))throw Error('세 가지 표시 기준을 직접 선택해 주세요.');await mutate('/api/settings',{visualization},'선택한 관계도·지도 기준을 저장했습니다.');});
  }
  async function acknowledgeAttention(ids){
    if(!ids.length)return;try{await mutate('/api/attention/read',{ids},`${ids.length}개 알림을 확인 완료로 기록했습니다.`);if($('#modal').open&&$('#modal .attention-list'))$('#modal').close();}catch{}
  }
  function showAttention(selection){
    const items=selection?itemsForGraph(selection):attentionItems();const content=el('div');
    content.append(el('p','callout','노드·관계선·기사를 여는 것만으로는 확인 처리하지 않습니다. 확인할 신규·변경을 직접 선택하세요.'));
    content.append(attentionList(items));modal('신규·변경 알림 확인',content);
  }
  function attentionList(items){
    const root=el('div','attention-list');const pending=items.filter(a=>a.unread),chosen=new Set();let shown=0;
    const submit=button('선택 알림 확인 완료','button primary small',()=>acknowledgeAttention([...chosen]));submit.disabled=true;root.append(submit);
    if(!pending.length)root.append(el('p','muted','이 맥락의 미확인 알림이 없습니다. 새 자료가 들어오면 다시 강조됩니다.'));
    const more=button('다음 알림 50건 보기','button small',()=>appendPage());
    function appendPage(){more.remove();pending.slice(shown,shown+50).forEach(item=>{const row=el('article',`attention-row ${item.type==='fact_change'?'fact-change':'new-article'}`);row.dataset.attentionId=item.id;const check=el('input');check.type='checkbox';check.setAttribute('aria-label',`${item.title||item.label||item.id} 확인 선택`);check.addEventListener('change',()=>{check.checked?chosen.add(item.id):chosen.delete(item.id);submit.disabled=!chosen.size;submit.textContent=`선택 알림 ${chosen.size}개 확인 완료`;});
      add(row,check,add(el('div'),badge(item.type==='fact_change'?'등록 근거 변화':'새 기사 발견','warning'),item.type==='new_article'?link((item.title||item.label||item.id)+' ↗',item.url||find('articles',item.article_ids?.[0])?.url,'attention-article-link'):el('p','',item.title||item.label||item.id),el('small','',dateTime(item.created_at))),button('이 알림 확인','button small',()=>acknowledgeAttention([item.id])));root.append(row);});shown=Math.min(pending.length,shown+50);if(shown<pending.length){more.textContent=`다음 알림 보기 · ${shown} / ${pending.length}건`;root.append(more);}}
    appendPage();return root;
  }
  function graphAcknowledge(selection){
    const policy=visualSettings().ack_scope;
    if(policy==='entity')acknowledgeAttention(itemsForGraph(selection).filter(a=>a.unread).map(a=>a.id));
    else if(policy==='screen')acknowledgeAttention(attentionItems().filter(a=>a.unread).map(a=>a.id));
    else showAttention(selection);
  }
  function graphInspector(selection){
    const panel=el('aside','network-inspector');panel.setAttribute('aria-label','선택 관계와 새 알림');
    if(!selection){add(panel,el('h3','','관계에서 근거로'),el('p','','사업·기업·관계선을 누르면 종합 내용과 원문을 확인할 수 있습니다.'),button(`새 알림 ${S.data?.attention?.counts?.unread||0}건 보기`,'button primary',()=>showAttention()));return panel;}
    const item=selection.node||selection.edge||selection,articles=ontologyArticles(selection.article_ids||item.article_ids||[]),items=itemsForGraph(selection);
    add(panel,el('h3','',item.name||item.label||item.id),el('p','metadata-label',`${item.type||'관계'} · 근거 기사 ${articles.length}개 · 미확인 알림 ${items.filter(a=>a.unread).length}건`));
    if(item.clustered_ids){panel.append(el('p','callout',`관측 노드 ${item.clustered_ids.length}개의 표시 묶음입니다. 같은 사업·계약 관계로 병합한 것이 아닙니다.`));panel.append(button(`개별 관계 ${item.clustered_ids.length}개 펼치기`,'button primary small',()=>{S.graphCluster={id:item.id,node_ids:item.clustered_ids};S.graphSelection=null;render();}));panel.append(el('p','metadata-label',(item.clustered_names||[]).slice(0,8).join(' · ')));}
    const discovered=item.is_named_candidate?discoveredProjects().find(p=>p.id===item.entity_id):null;if(discovered)panel.append(button('기사 사업명 후보·근거 보기','button primary small',()=>candidateDetails(discovered)));
    if(item.type==='company'){
      const company=companyCatalog().find(c=>c.id===item.entity_id)||item,profiles=company.profile_evidence||company.company_profile?.evidence||[];
      panel.append(el('h4','','기업 성격'),el('p','company-profile-summary',companyCategories(company).map(id=>companyCategoryNames().find(r=>r.id===id)?.label||roleName(id)).join(' · ')),el('p','metadata-label','기업 자체 분류이며 이 프로젝트의 발주·계약·참여 확정과 다릅니다.'));
      profiles.forEach(profile=>{const row=el('div','company-profile-evidence'),label={registered_metadata:'등록 기업 설명',metadata_descriptor:'기사의 기업 설명',classification_proposal:'기업 성격 후보',official_business_nature:'공식 기업 설명',user_classification:'사용자 분류'}[profile.status]||'성격 미확인';add(row,badge(roleName(profile.category),'neutral'),el('small','',`${label} · ${profile.evidence?.text||profile.raw_role||'근거 확인 필요'}`));if(profile.article_ids?.length)row.append(button('분류 근거','button small',()=>articleCollection(profile.article_ids,`${company.name} 기업 성격 근거`)));if(profile.evidence?.source_url)row.append(link('공식 분류 출처 ↗',profile.evidence.source_url));panel.append(row);});
    }
    if(item.evidence&&Array.isArray(item.evidence)){panel.append(el('p','callout','기사 표현으로 추출한 연결입니다. 참여·직접 계약을 자동 확정하지 않습니다.'));item.evidence.slice(0,5).forEach(e=>panel.append(el('p','network-source-span',`${e.field||'기사'}: ${e.text||''}`)));}
    const entry=item.type==='company'?oitems('companies').find(c=>c.id===item.entity_id):item.type==='project'?oitems('projects').find(p=>p.id===item.entity_id):oitems('pending_groups').find(p=>p.id===item.entity_id);
    const summary=item.context_keyword?[`${item.name}의 ${item.context_keyword} 관련 근거 ${articles.length}개를 취합했습니다.`,`${new Set(articles.map(a=>a.publisher)).size}개 매체 · 최신 발행 ${dateTime(articles[0]?.published_at)}`, '키워드는 기사에서 관측한 주제입니다. 참여 역할과 계약은 명시된 원문 근거로만 연결합니다.']:entry?.summary_lines||entry?.summary||[];
    (Array.isArray(summary)?summary:[summary]).slice(0,4).forEach(s=>panel.append(el('p','',typeof s==='object'?s.text:s)));
    articles.slice(0,3).forEach(a=>panel.append(add(el('div','network-evidence'),link(a.title,a.url),el('small','',`${a.publisher} · ${dateTime(a.published_at)}`))));
    panel.append(button(`전체 근거 ${articles.length}개 ↗`,'button small',()=>articleCollection(articles.map(a=>a.id),item.name||'선택 관계의 근거')));
    if(item.type==='project'&&find('projects',item.entity_id))panel.append(button('사업 상세 보기','button small',()=>{S.selected=item.entity_id;modal('사업 상세',renderDetail(find('projects',item.entity_id)));}));
    if(item.type==='company'&&!item.clustered_ids)panel.append(button('기업 상세 · 사내 링크','button small',()=>openCompany(item.entity_id)));
    panel.append(attentionList(items));return panel;
  }
  function graphSelection(value){
    S.graphSelection=value;const node=value.node;
    if(node?.type==='company'&&!node.clustered_ids&&S.view==='companies'){S.companyCategory='all';S.companyNameFilter='';S.companyRole='all';focusCompany(node.entity_id);return;}
    if(S.view==='projects'&&(node?.type==='project'||node?.is_named_candidate)){S.projectFocus=node.is_named_candidate?`candidate:${node.entity_id}`:node.entity_id;S.graphCluster=null;}
    render();
  }
  function compactNetwork(input,mode,centerId,keywordId){
    let nodes=input.nodes||[],edges=input.edges||[];
    if(mode==='company-network')return {nodes,edges};
    const center=nodes.find(n=>n.id===centerId),expanded=S.graphCluster?.node_ids;
    if(center||expanded){
      const focus=new Set(expanded||[center.id]),ids=new Set(focus);
      edges.forEach(e=>{if(focus.has(e.source)||focus.has(e.target)){ids.add(e.source);ids.add(e.target);}});
      if(mode==='company')nodes.filter(n=>n.type==='role').forEach(n=>ids.add(n.id));
      nodes=nodes.filter(n=>ids.has(n.id));edges=edges.filter(e=>ids.has(e.source)&&ids.has(e.target));
      if(mode==='company'&&center){
        const keyword=nodes.find(n=>n.type==='keyword'&&n.id===keywordId),context=new Set(keyword?edges.filter(e=>(e.source===centerId&&e.target===keyword.id)||(e.target===centerId&&e.source===keyword.id)).flatMap(e=>e.article_ids||[]):center.article_ids||[]);
        if(keyword){edges=edges.map(e=>{const aids=(e.article_ids||[]).filter(id=>context.has(id));return {...e,article_ids:aids,...contextAttention(e,aids)};}).filter(e=>e.article_ids.length);const linked=new Set(edges.flatMap(e=>[e.source,e.target]));nodes=nodes.filter(n=>linked.has(n.id)||n.id===centerId||n.type==='role');}
        nodes=nodes.map(n=>{if(n.type==='keyword'){const aids=[...new Set(edges.filter(e=>e.source===n.id||e.target===n.id).flatMap(e=>e.article_ids||[]))].filter(id=>context.has(id));return {...n,article_ids:aids,article_count:aids.length,...contextAttention(n,aids)};}if(keyword&&n.id===centerId){const aids=[...context];return {...n,article_ids:aids,article_count:aids.length,context_keyword:keyword.name,...contextAttention(n,aids)};}return n;});
      }
      if(mode==='company')nodes=nodes.map(n=>{if(n.type!=='role')return n;const roleEdges=edges.filter(e=>e.source===n.id||e.target===n.id),aids=[...new Set(roleEdges.flatMap(e=>e.article_ids||[]))];return {...n,...clusterAttention(roleEdges),article_ids:aids,article_count:aids.length,placeholder:!roleEdges.length};});
      if(expanded)return {nodes,edges};
    }
    if(nodes.length<=36)return {nodes,edges};
    const mapping=new Map(nodes.map(n=>[n.id,n.id])),groups=[];
    function group(type,key,members,label){
      if(!members.length)return;const id=`cluster:${mode}:${type}:${key}`,article_ids=[...new Set(members.flatMap(n=>n.article_ids||[]))];
      members.forEach(n=>mapping.set(n.id,id));groups.push({id,entity_id:id,type,name:`${label} · ${members.length}개`,article_ids,article_count:article_ids.length,clustered_ids:members.map(n=>n.id),clustered_names:members.map(n=>n.name),scope:key,...clusterAttention(members),basis:'visual_group_only',status:'묶음 표시 · 개별 사업 확정 아님'});
    }
    const ordered=list=>list.slice().sort((a,b)=>(b.article_count||0)-(a.article_count||0)||a.id.localeCompare(b.id));
    const named=nodes.filter(n=>n.is_named_candidate&&n.id!==centerId);group('pending','named',ordered(named).slice(12),'그 외 기사 사업명 후보');
    const pending=nodes.filter(n=>n.type==='pending'&&!n.is_named_candidate);
    if(mode==='project'&&!center){['kr-dc','kr-ai','global-ai','unresolved'].forEach(scope=>group('pending',scope,pending.filter(n=>n.scope===scope),`${scopeLabels[scope]} 식별 대기 묶음`));}
    else group('pending','other',ordered(pending).slice(6),'그 외 사업 식별 대기');
    const locations=nodes.filter(n=>n.type==='location');
    ['kr-dc','kr-ai','global-ai','unresolved'].forEach(scope=>group('location',scope,ordered(locations.filter(n=>n.scope===scope)).slice(2),`${scopeLabels[scope]} 그 외 지역`));
    const companies=ordered(nodes.filter(n=>n.type==='company'&&n.id!==centerId));
    companyCategoryNames().forEach(category=>{const members=companies.filter(n=>(n.profile_categories||companyCategories({id:n.entity_id}))[0]===category.id);group('company',category.id,members.slice(mode==='company'?10:4),`${category.label} 기업 성격`);});
    group('keyword','other',ordered(nodes.filter(n=>n.type==='keyword')).slice(12),'그 외 기사 키워드');
    if(!groups.length)return {nodes,edges};
    const result=nodes.filter(n=>mapping.get(n.id)===n.id).concat(groups),merged=new Map();
    edges.forEach(edge=>{const source=mapping.get(edge.source),target=mapping.get(edge.target);if(!source||!target||source===target)return;const grouped=source!==edge.source||target!==edge.target;
      const id=grouped?`cluster-edge:${source}:${target}:${edge.type}`:edge.id;
      if(!merged.has(id))merged.set(id,{...edge,id,source,target,...(grouped?{basis:'visual_aggregation',status:'grouped_evidence_context',label:'묶음 연결 · 원문별 관계 구분'}:{}),members:[]});merged.get(id).members.push(edge);
    });
    const links=[...merged.values()].map(edge=>{const {members,...value}=edge;return {...value,article_ids:[...new Set(members.flatMap(e=>e.article_ids||[]))],...clusterAttention(members)};});return {nodes:result,edges:links,clustered:true};
  }
  function clusterAttention(members){
    const ids=new Set(members.flatMap(n=>n.attention_ids||[])),items=attentionItems().filter(n=>ids.has(n.id)),pending=items.filter(n=>n.unread&&(n.type!=='new_article'||n.is_recent!==false));
    return {attention_ids:[...ids],unread_attention_ids:pending.map(n=>n.id),unread_count:pending.length,new_article_count:pending.filter(n=>n.type==='new_article').length,fact_change_count:pending.filter(n=>n.type==='fact_change').length,has_unread:pending.length>0};
  }
  function contextAttention(item,articleIds){const aids=new Set(articleIds),allowed=new Set(item.attention_ids||[]);return clusterAttention([{attention_ids:attentionItems().filter(a=>allowed.has(a.id)&&(a.article_ids||[]).some(id=>aids.has(id))).map(a=>a.id)}]);}
  function companyCatalog(){
    const result=new Map(),selected=new Set(nitems('articles').map(a=>a.id));
    arr('companies').forEach(c=>result.set(c.id,{...c,roles:['unknown'],article_ids:[],article_count:0,selected_article_count:0}));
    (S.data?.company_catalog?.companies||oitems('companies')).forEach(c=>result.set(c.id,{...result.get(c.id),...c}));
    oitems('companies').forEach(c=>{if(result.has(c.id))result.set(c.id,{...result.get(c.id),...c,selected_article_count:(c.article_ids||[]).filter(id=>selected.has(id)).length});});
    return [...result.values()].sort((a,b)=>(b.article_count||0)-(a.article_count||0)||a.name.localeCompare(b.name));
  }
  function companyCategories(company){
    const profile=(S.data?.company_catalog?.companies||[]).find(c=>c.id===company.id)||oitems('companies').find(c=>c.id===company.id)||arr('companies').find(c=>c.id===company.id)||company;
    return profile.profile_categories||profile.company_profile?.categories||company.profile_categories||['unknown'];
  }
  function companyCategoryMatches(company){return !S.companyCategory||S.companyCategory==='all'||companyCategories(company).includes(S.companyCategory);}
  function companyCategoryNames(){return S.data?.company_catalog?.profile_taxonomy||companyRoleNames();}
  function profileClassificationGraph(data){
    const companies=oitems('companies').filter(companyCategoryMatches),allowed=new Set(companies.map(c=>c.id));
    const nodes=(data.nodes||[]).filter(n=>n.type!=='company'||allowed.has(n.entity_id)).map(n=>n.type==='company'?{...n,profile_categories:companyCategories({id:n.entity_id})}:n),edges=[...(data.edges||[])];
    if(S.companyCategory&&S.companyCategory!=='all'){
      const aids=new Set(companies.flatMap(c=>c.article_ids||[]));
      const visible=nodes.filter(n=>n.type==='company'||(n.article_ids||[]).some(id=>aids.has(id))),ids=new Set(visible.map(n=>n.id));
      return {...data,nodes:visible,edges:edges.filter(e=>ids.has(e.source)&&ids.has(e.target))};
    }
    const ids=new Set(nodes.map(n=>n.id));return {...data,nodes,edges:edges.filter(e=>ids.has(e.source)&&ids.has(e.target))};
  }
  function renderCompanyCategories(panel,companyMode){
    const companies=companyMode?companyCatalog():oitems('companies'),bar=el('div','company-category-bar');bar.setAttribute('aria-label','기업 성격별 분류');
    bar.append(el('strong','','기업 성격'));
    [['all','전체 성격'],...companyCategoryNames().map(r=>[r.id,r.label])].forEach(([id,label])=>{const count=id==='all'?companies.length:companies.filter(c=>companyCategories(c).includes(id)).length;
      const item=button(`${label} ${count}`,'button small',()=>{S.companyCategory=id;S.graphCluster=null;S.graphSelection=null;if(companyMode){const next=companyCatalog().find(c=>companyCategoryMatches(c)&&companyRoleMatches(c));S.companyFocus=next?.id||null;load();}else render();});
      item.dataset.companyCategory=id;item.setAttribute('aria-pressed',(S.companyCategory||'all')===id?'true':'false');bar.append(item);
    });
    panel.append(bar,el('p','company-profile-note','기업 성격은 회사의 업종·설명·상호 표현에 따른 분류입니다. 사업별 참여 역할·계약과 구분하며, 신규 관측 기업도 같은 기준으로 분류하고 근거가 부족하면 미확인으로 남깁니다.'));
  }
  function discoveredProjects(){
    const discovery=S.data?.project_discovery||{},provided=discovery.project_candidates||discovery.candidate_groups||discovery.candidates;
    if(Array.isArray(provided))return provided.map(p=>({...p,article_ids:p.article_ids||[],article_count:p.article_ids?.length||p.article_count||0,is_candidate:true}));
    const groups=new Map();(discovery.mentions||[]).forEach(m=>{const key=JSON.stringify([m.name,m.scope,m.city||m.cities||null]);if(!groups.has(key))groups.set(key,{...m,id:m.id,article_ids:[],is_candidate:true});const p=groups.get(key);p.article_ids=[...new Set([...p.article_ids,...(m.article_ids||[]),...(m.article_id?[m.article_id]:[])])];});
    return [...groups.values()].map(p=>({...p,article_count:p.article_ids.length})).sort((a,b)=>b.article_count-a.article_count||a.name.localeCompare(b.name));
  }
  function discoveryGraph(data){
    const candidates=discoveredProjects(),nodes=[...(data.nodes||[])],edges=[...(data.edges||[])];
    candidates.forEach(p=>{const id=`discovery:${p.id}`,articles=ontologyArticles(p.article_ids),attention=clusterAttention([{attention_ids:attentionItems().filter(a=>(a.article_ids||[]).some(id=>p.article_ids.includes(id))).map(a=>a.id)}]);nodes.push({id,entity_id:p.id,type:'pending',is_named_candidate:true,name:p.name,scope:p.scope,article_ids:p.article_ids,article_count:articles.length,status:p.user_confirmed_identity?'사용자 확인 연결 · 직접 계약 미확인':'기사 명칭 후보 · 독립 사업 확정 전',...attention});
      if(nodes.some(n=>n.id===`scope:${p.scope}`))edges.push({id:`discovery-scope:${p.id}`,source:`scope:${p.scope}`,target:id,type:'article_project_candidate',basis:'source_named_project_observation',status:'candidate',article_ids:p.article_ids,label:'명칭 관측 · 사업 식별 확인 필요',...attention});});
    const links=[...(S.data?.project_discovery?.company_links||[]),...candidates.flatMap(p=>(p.company_links||[]).map(e=>({...e,project_id:e.project_id||p.id})))],seen=new Set();
    links.forEach(link=>{
      const key=link.id||`${link.project_id}:${link.company_id}:${link.role}:${(link.article_ids||[]).join(',')}`;if(seen.has(key))return;seen.add(key);
      const projectId=candidates.some(p=>p.id===link.project_id)?`discovery:${link.project_id}`:`project:${link.project_id}`,companyId=`company:${link.company_id}`;
      if(!nodes.some(n=>n.id===projectId))return;
      if(link.basis==='explicit_stored_relationship'&&edges.some(e=>((e.source===projectId&&e.target===companyId)||(e.source===companyId&&e.target===projectId))&&e.basis==='explicit_stored_relationship'))return;
      const company=oitems('companies').find(c=>c.id===link.company_id)||companyCatalog().find(c=>c.id===link.company_id);if(!company)return;
      if(!nodes.some(n=>n.id===companyId))nodes.push({id:companyId,entity_id:company.id,type:'company',name:company.name,article_ids:link.article_ids||[],article_count:link.article_ids?.length||0,roles:company.roles||['unknown'],profile_categories:companyCategories(company)});
      const aids=link.article_ids||[],attention=clusterAttention([{attention_ids:attentionItems().filter(a=>(a.article_ids||[]).some(id=>aids.includes(id))).map(a=>a.id)}]);
      edges.push({...link,id:`observed-link:${key}`,source:projectId,target:companyId,type:'project_company_observation',article_ids:aids,label:link.role&&link.role!=='unknown'?`${roleName(link.role)} · ${link.is_confirmed_participation?'명시 저장 근거':'기사 표현 · 검토 필요'}`:link.label||'기사 기업 관측 · 역할 미확인',direct_contract_confirmed:false,...attention});
    });
    return {...data,nodes,edges};
  }
  function projectRoleGraph(data,selectedRole='all'){
    const nodes=(data.nodes||[]).map(n=>({...n})),edges=[...(data.edges||[])],companies=oitems('companies'),nodeIds=new Set(nodes.map(n=>n.id));
    companies.forEach(c=>{const id=`company:${c.id}`;if(!nodeIds.has(id)){nodes.push({id,entity_id:c.id,type:'company',name:c.name,article_ids:c.article_ids||[],article_count:c.article_count||0,roles:c.roles||['unknown'],...clusterAttention([{attention_ids:attentionItems().filter(a=>(a.company_ids||[]).includes(c.id)).map(a=>a.id)}])});nodeIds.add(id);}});
    companyRoleNames().forEach(role=>{const members=companies.filter(c=>(c.roles||['unknown']).includes(role.id)),evidence=members.flatMap(c=>(c.role_evidence||[]).filter(e=>e.role===role.id)),aids=[...new Set(role.id==='unknown'?members.flatMap(c=>c.article_ids||[]):evidence.flatMap(e=>e.article_ids||[]))],id=`explore-role:${role.id}`;
      const aidSet=new Set(aids),annotations=clusterAttention([{attention_ids:attentionItems().filter(a=>(a.article_ids||[]).some(id=>aidSet.has(id))).map(a=>a.id)}]);nodes.push({id,entity_id:role.id,role:role.id,type:'role',name:role.label,article_ids:aids,article_count:aids.length,placeholder:!aids.length,...annotations});
      members.forEach(c=>{const ids=role.id==='unknown'?c.article_ids||[]:(c.role_evidence||[]).filter(e=>e.role===role.id).flatMap(e=>e.article_ids||[]);if(ids.length)edges.push({id:`explore-role-edge:${role.id}:${c.id}`,source:`company:${c.id}`,target:id,type:role.id==='unknown'?'role_unknown_observation':'registered_role',basis:role.id==='unknown'?'metadata_observation':'explicit_stored_relationship',article_ids:[...new Set(ids)],label:role.id==='unknown'?'기사 이름 관측 · 역할 미확인':`${role.label} · 사업별 명시 근거`});});
    });
    if(selectedRole==='all')return {...data,nodes,edges};
    const roleNode=nodes.find(n=>n.id===`explore-role:${selectedRole}`),allowedArticles=new Set(roleNode?.article_ids||[]),allowedCompanies=new Set(companies.filter(c=>(c.roles||['unknown']).includes(selectedRole)).map(c=>c.id));
    const visible=nodes.filter(n=>n.type==='role'?n.id===roleNode?.id:n.type==='company'?allowedCompanies.has(n.entity_id):(n.article_ids||[]).some(id=>allowedArticles.has(id))),visibleIds=new Set(visible.map(n=>n.id));
    return {...data,nodes:visible,edges:edges.filter(e=>visibleIds.has(e.source)&&visibleIds.has(e.target)).map(e=>({...e,article_ids:(e.article_ids||[]).filter(id=>allowedArticles.has(id))})).filter(e=>e.article_ids.length)};
  }
  function candidateDetails(project){
    const content=el('div');add(content,el('p','callout','기사 원문 표현을 구조화한 사업명 후보입니다. 등록 사업·계약·실제 용량으로 확정하지 않았습니다.'),el('h3','',project.name),el('p','metadata-label',`${scopeLabels[project.scope]||'범위 미확인'} · ${project.city||(project.cities||[]).join(' · ')||'도시 미확인'} · 기사 ${project.article_ids.length}개`));
    const labels={cancelled:'취소·무산',funding:'자금 조달',completed:'준공·개소',construction:'착공·공사',planning:'계획·개발',operating:'운영·가동'};
    const signals=[...(project.stage_observations||project.stage_signals||[]),...(project.capacity_observations||project.capacity_signals||[])];signals.forEach(s=>content.append(el('p','',typeof s==='string'?s:`기사 표현 신호 · ${s.raw||labels[s.stage]||s.text||'미확인'}${s.evidence?.text?' · '+s.evidence.text:''}`)));
    (project.company_links||[]).forEach(item=>{const company=companyCatalog().find(c=>c.id===item.company_id)||find('companies',item.company_id);if(!company)return;const row=el('div','company-profile-evidence');add(row,el('strong','',company.name),el('p','',`${roleName(item.role||'unknown')} · ${item.status==='role_observation'?'기사 역할 표현 · 검토 필요':'동일 기사 이름 관측 · 참여 미확인'}`),button('연결 근거 기사','button small',()=>articleCollection(item.article_ids,`${project.name} · ${company.name}`)));content.append(row);});
    const list=el('div','source-grid');ontologyArticles(project.article_ids).forEach(a=>list.append(sourceCard(a)));content.append(list);modal('기사 사업명 후보 · 원문 근거',content);
  }
  function renderDiscoveryLedger(root){
    const candidates=discoveredProjects(),discovery=S.data?.project_discovery||{};
    if(!discovery.counts&&!candidates.length)return;
    const panel=el('section','panel discovery-ledger');add(panel,section(`기사에서 발견한 사업명 후보 · ${candidates.length}묶음`,'고정 등록 사업과 구분한 원문 명칭 후보입니다. 같은 도시·기업만으로 합치지 않으며 원문을 눌러 확인할 수 있습니다.'));
    const controls=el('div','pivot-controls'),search=el('input');search.type='search';search.placeholder='사업명·도시·기사 표현 검색';search.setAttribute('aria-label','기사 사업명 후보 검색');search.value=S.discoveryQuery||'';const apply=button('후보 검색','button small',()=>{S.discoveryQuery=search.value;S.discoveryPage=1;render();});search.addEventListener('keydown',e=>{if(e.key==='Enter')apply.click();});add(controls,search,apply,button('모든 근거 기사','button small',()=>articleCollection(candidates.flatMap(p=>p.article_ids),'사업명 후보 기사')));panel.append(controls);
    const q=(S.discoveryQuery||'').trim().toLocaleLowerCase(),matching=candidates.filter(p=>!q||[p.name,p.city,...p.cities||[],...(p.company_observations||[]).map(c=>c.name)].join(' ').toLocaleLowerCase().includes(q));
    const pendingIds=new Set((discovery.analysis_pending||[]).map(p=>p.article_id)),pendingArticles=nitems('articles').filter(a=>pendingIds.has(a.id)&&(!q||[a.title,a.publisher].join(' ').toLocaleLowerCase().includes(q)));
    panel.append(el('p','pivot-note',`선택 기사 ${nitems('articles').length}개 · 명칭 후보 ${candidates.length}묶음 · 사업명 자동 식별 보류 ${(discovery.analysis_pending||[]).length}개 기사. 묶음 수는 고유 사업 수가 아닙니다.`));
    const page=Math.max(1,Math.min(S.discoveryPage||1,Math.ceil(matching.length/12)||1));S.discoveryPage=page;
    const grid=el('div','discovery-grid');matching.slice((page-1)*12,page*12).forEach(p=>{const card=el('article','discovery-card');add(card,badge('기사 사업명 후보','warning'),button(p.name,'button text discovery-name',()=>{S.projectFocus=`candidate:${p.id}`;S.graphSelection=null;if(S.view==='projects'||S.view==='overview'){render();document.querySelector('.visual-ontology')?.scrollIntoView({block:'start',behavior:'smooth'});}else candidateDetails(p);}),el('p','',`${p.city||(p.cities||[]).join(' · ')||'지역 상세 미확인'} · 근거 ${p.article_ids.length}개`));const a=ontologyArticles(p.article_ids)[0];if(a)add(card,link(a.title+' ↗',a.url),el('small','',`${a.publisher} · ${date(a.published_at)}`));card.append(button('후보 정보·전체 근거','button small',()=>candidateDetails(p)));grid.append(card);});
    if(!matching.length)grid.append(empty('검색된 사업명 후보가 없습니다','기사에 사업명·입지 표현이 부족한 자료는 식별 대기로 보존합니다.'));panel.append(grid);
    const pager=add(el('div','news-pagination'),el('span','',`${page} / ${Math.ceil(matching.length/12)||1} · 전체 ${matching.length}개 명칭 묶음`)),prev=button('← 이전','button small',()=>{S.discoveryPage--;render();}),next=button('다음 →','button small',()=>{S.discoveryPage++;render();});prev.disabled=page<=1;next.disabled=page*12>=matching.length;add(pager,prev,next);panel.append(pager);
    const pending=el('details','discovery-pending');pending.append(el('summary','',`사업명 식별 보류 기사 ${pendingArticles.length}개 · 원문에서 확인`));pending.append(el('p','pivot-note','짧은 제목·입지 불명·일반 동향 등으로 사업명을 안전하게 추출하지 못한 기사입니다. 삭제하거나 실제 사업이 없는 것으로 처리하지 않습니다.'));
    pending.append(button(`보류 기사 전체 근거 ${pendingArticles.length}개`,'button small',()=>articleCollection(pendingArticles.map(a=>a.id),'사업명 식별 보류 기사')));const list=el('div','source-grid');pendingArticles.slice(0,12).forEach(a=>list.append(sourceCard(a)));pending.append(list);panel.append(pending);root.append(panel);
  }
  function focusCompany(id){
    const previousScope=S.scope,chosen=companyCatalog().find(c=>c.id===id);S.companyFocus=id||null;S.companyKeyword='';S.graphCluster=null;S.graphSelection=null;
    if(chosen&&!chosen.selected_article_count&&chosen.selected_article_count!==undefined){S.scope='all';S.country='';S.city='';S.newsCompany='';S.selectedCompany=null;}
    if(S.data&&S.scope===previousScope&&!S.integrityError)render();
    load();
  }
  function mapDescription(marker){
    const ids=new Set(marker?.article_ids||nitems('articles').map(a=>a.id)),articles=ontologyArticles([...ids]);
    const projects=oitems('projects').filter(p=>(p.article_ids||[]).some(id=>ids.has(id))).map(p=>{
      const aids=(p.article_ids||[]).filter(id=>ids.has(id));
      const roles=oitems('companies').flatMap(c=>(c.role_evidence||[]).filter(e=>e.project_id===p.id&&(e.article_ids||[]).some(id=>ids.has(id))).map(e=>`${c.name} · ${roleName(e.role)}`));
      return {...p,article_ids:aids,article_count:aids.length,roles:[...new Set(roles)],summary:(Array.isArray(p.summary)?p.summary:[p.summary||'']).map(x=>typeof x==='object'?x.text:x).join(' ')};
    });
    const companies=oitems('companies').filter(c=>(c.article_ids||[]).some(id=>ids.has(id))).map(c=>({name:c.name,role:[...new Set((c.role_evidence||[]).filter(e=>(e.article_ids||[]).some(id=>ids.has(id))).map(e=>roleName(e.role)))].join(' · ')||'참여 역할 미확인'}));
    const candidates=discoveredProjects().filter(p=>(p.article_ids||[]).some(id=>ids.has(id))).map(p=>{const roles=[...new Set((p.company_links||[]).filter(e=>(e.article_ids||[]).some(id=>ids.has(id))).map(e=>`${companyCatalog().find(c=>c.id===e.company_id)?.name||'관측 기업'} · ${roleName(e.role||'unknown')} · 기사 관측`))];return {...p,status:'기사 사업명 후보',location:p.city||(p.cities||[]).join(' · '),roles:roles.length?roles:['참여 역할은 기사 근거 추가 확인'],article_count:p.article_ids.filter(id=>ids.has(id)).length};});
    return {projects:[...projects,...candidates],companies,articles,article_count:articles.length,pending_count:oitems('pending_groups').filter(p=>(p.article_ids||[]).some(id=>ids.has(id))).length,
      summary:[`${marker?.name||'현재 범위'}의 기사 ${articles.length}개와 연결된 등록 사업 ${projects.length}개입니다.`, '지역 관측만 있는 자료는 사업명·참여 역할을 확정하지 않습니다.']};
  }
  function focusProject(project){
    S.projectFocus=project.is_candidate?`candidate:${project.id}`:project.id;S.selected=project.is_candidate?null:project.id;S.graphSelection=null;S.graphCluster=null;S.explorerRole='all';S.companyCategory='all';
    if(S.view!=='projects'){navigate('projects',S.scope);return;}render();document.querySelector('.visual-ontology')?.scrollIntoView({block:'start',behavior:'smooth'});
  }
  function renderVisualNetwork(root,options={}){
    let contextualCenter;
    const mode=options.mode||S.explorerMode||'project',companyMode=mode==='company';
    const data=companyMode?discoveryGraph(ontology().company_ontology||{}):profileClassificationGraph(projectRoleGraph(discoveryGraph(ontology()),S.explorerRole||'all'));
    const panel=el('section','visual-ontology');panel.id=options.id||'visualOntology';panel.dataset.workspaceScope=S.scope;panel.setAttribute('aria-label',companyMode?'기업 중심 그래픽 관계도':'사업 중심 그래픽 관계도');
    const toolbar=add(el('div','network-context-controls'),el('strong','',companyMode?'기업 중심 관계도':'사업 중심 관계도'));
    if(!options.mode)[['project','사업 중심'],['company','기업 중심']].forEach(([value,label])=>{const b=button(label,'button small',()=>{S.explorerMode=value;S.graphCluster=null;S.graphSelection=null;render();});b.dataset.networkMode=value;b.setAttribute('aria-pressed',mode===value?'true':'false');toolbar.append(b);});
    if(!companyMode){const role=el('select');role.setAttribute('aria-label','탐색 관계도 사업별 참여 역할');[['all','전체 참여 역할'],...companyRoleNames().map(r=>[r.id,r.label])].forEach(([id,label])=>{const count=id==='all'?oitems('companies').length:oitems('companies').filter(c=>(c.roles||['unknown']).includes(id)).length;role.append(Object.assign(el('option','',`${label} · ${count}개사`),{value:id}));});role.value=S.explorerRole||'all';role.addEventListener('change',()=>{S.explorerRole=role.value;S.graphSelection=null;S.graphCluster=null;render();});toolbar.append(role);}
    const catalog=companyCatalog();const choices=companyMode?catalog.filter(companyRoleMatches).filter(companyCategoryMatches):[...oitems('projects'),...discoveredProjects().map(p=>({...p,id:`candidate:${p.id}`,name:`[기사 후보] ${p.name}`}))];
    const select=el('select');select.setAttribute('aria-label',companyMode?'관계도 중심 기업':'관계도 중심 사업');select.append(Object.assign(el('option','','전체 관계'),{value:''}));
    choices.forEach(c=>select.append(Object.assign(el('option','',companyMode?`${c.name} · 기사 ${c.article_count||0}개`:c.name),{value:c.id})));select.value=companyMode?(choices.some(c=>c.id===S.companyFocus)?S.companyFocus:choices.find(c=>c.selected_article_count>0)?.id||choices[0]?.id||''):(S.projectFocus||'');if(companyMode)S.companyFocus=select.value||null;
    select.addEventListener('change',()=>{if(companyMode){focusCompany(select.value);return;}S.projectFocus=select.value;S.companyKeyword='';S.graphCluster=null;S.graphSelection=null;render();});
    if(companyMode){const roles=el('select');roles.setAttribute('aria-label','기업 관계도 사업별 참여 역할');[['all','전체 참여 역할'],...companyRoleNames().map(r=>[r.id,r.label])].forEach(([id,label])=>roles.append(Object.assign(el('option','',`${label} · ${id==='all'?catalog.length:catalog.filter(c=>(c.roles||['unknown']).includes(id)).length}개사`),{value:id})));roles.value=S.companyRole;roles.addEventListener('change',()=>{S.companyRole=roles.value;const next=catalog.find(c=>companyRoleMatches(c)&&companyCategoryMatches(c));if(next)focusCompany(next.id);else{S.companyFocus=null;S.companyKeyword='';render();}});toolbar.append(roles);const search=el('input','company-search-control');search.type='search';search.placeholder='국내외 기업 이름 검색';search.setAttribute('aria-label','관계도 기업 이름 검색');search.value=S.companyNameFilter||'';const fill=()=>{const q=search.value.trim().toLocaleLowerCase();S.companyNameFilter=search.value;select.replaceChildren(Object.assign(el('option','',q?'검색 결과에서 기업 선택':'기업 선택'),{value:''}));choices.filter(c=>!q||c.name.toLocaleLowerCase().includes(q)).forEach(c=>select.append(Object.assign(el('option','',`${c.name} · 기사 ${c.article_count||0}개`),{value:c.id})));select.value=choices.some(c=>c.id===S.companyFocus&&(!q||c.name.toLocaleLowerCase().includes(q)))?S.companyFocus:'';};search.addEventListener('input',fill);toolbar.append(search);if(search.value)fill();}
    add(toolbar,select,button(`새 알림 ${S.data?.attention?.counts?.unread||0}건`,'button small attention-open',()=>showAttention(contextualCenter)),button('표시 기준','button small',visualizationChoices));panel.append(toolbar);
    if(S.graphCluster)toolbar.append(button('전체 요약 관계로','button small',()=>{S.graphCluster=null;S.graphSelection=null;render();}));
    const centerId=companyMode?(S.companyFocus?`company:${S.companyFocus}`:null):(S.projectFocus?(S.projectFocus.startsWith('candidate:')?`discovery:${S.projectFocus.slice(10)}`:`project:${S.projectFocus}`):null);
    if(companyMode){const company=oitems('companies').find(c=>`company:${c.id}`===centerId),keywords=company?.keywords||[];const filter=el('select');filter.setAttribute('aria-label','기업 관계도 키워드');filter.append(Object.assign(el('option','','전체 키워드'),{value:''}));keywords.forEach(k=>filter.append(Object.assign(el('option','',`${k.label} · 기사 ${k.article_ids.length}개 · 미확인 ${k.unread_count||0}건`),{value:k.id})));if(!keywords.some(k=>k.id===S.companyKeyword))S.companyKeyword='';filter.value=S.companyKeyword||'';filter.addEventListener('change',()=>{S.companyKeyword=filter.value;S.graphSelection=null;S.graphCluster=null;render();});toolbar.append(filter);}
    if(companyMode)toolbar.append(el('p','company-catalog-note',`국내외 관측 기업 ${catalog.length}개 · 현재 역할 ${choices.length}개 · 기간·검색어·출처·사업 조건 유지. 다른 범위 기업 선택 시 전체 범위로 전환합니다. 기업 성격과 사업별 참여 역할은 별도로 표시합니다.`));
    if(!companyMode&&S.explorerRole&&S.explorerRole!=='all')toolbar.append(el('p','company-catalog-note',`${roleName(S.explorerRole)} 관점 · 사업별 기사에 명시된 역할만 연결합니다. 같은 기사 조건의 전체 수치는 유지하며 근거가 없는 역할은 빈 상태로 둡니다.`));
    renderCompanyCategories(panel,companyMode);
    const layout=el('div','visual-network-layout');
    const graphNodes=(data.nodes||[]).map(n=>n.type==='company'?{...n,profile_categories:companyCategories({id:n.entity_id})}:n).filter(n=>(!companyMode||choices.length>0||n.type==='role')&&(n.type!=='scope'||S.scope==='all'||n.entity_id===S.scope)),visibleIds=new Set(graphNodes.map(n=>n.id));
    const display=compactNetwork({nodes:graphNodes,edges:(data.edges||[]).filter(e=>visibleIds.has(e.source)&&visibleIds.has(e.target))},mode,centerId,companyMode?S.companyKeyword:null);
    if(centerId){const node=display.nodes.find(n=>n.id===centerId);if(node){contextualCenter={kind:'node',id:node.id,node,article_ids:node.article_ids};toolbar.querySelector('.attention-open').textContent=`선택 ${companyMode?'기업':'사업'} 새 알림 ${node.unread_count||0}건`;}}
    if(S.graphSelection){const node=display.nodes.find(n=>n.id===S.graphSelection.id),edge=display.edges.find(e=>e.id===S.graphSelection.id);S.graphSelection=node?{kind:'node',id:node.id,node,article_ids:node.article_ids}:edge?{kind:'edge',id:edge.id,edge,article_ids:edge.article_ids}:null;}
    if(display.clustered)panel.append(el('p','metadata-label','가독성을 위해 지역·기업·식별 대기를 묶었습니다. 묶음을 선택하면 개별 관계를 펼치거나 포함된 전체 근거를 확인할 수 있습니다. 원본·기사·집계는 모두 유지됩니다.'));
    if(window.AtlasGraph){layout.append(window.AtlasGraph.create({nodes:display.nodes,edges:display.edges,mode,centerId,
      selectedId:S.graphSelection?.id,height:650,totalNodes:data.graph?.total_nodes||data.nodes?.length||0,viewKey:`${S.view}:${mode}:${newsParams()}:${centerId||'all'}:${S.graphCluster?.id||'summary'}:${S.companyKeyword||'all-keywords'}:${S.explorerRole||'all-roles'}:${S.companyCategory||'all-profiles'}`,
      title:companyMode?'기업 · 사업자 · 테넌트 · 운영 · 시공 · 설계 · 장비 · PF 관계':`사업 관계 지도 · ${S.explorerRole&&S.explorerRole!=='all'?roleName(S.explorerRole):'전체 참여 역할'}`,
      articleAlerts:attentionItems(),onArticleAlerts:showAttention,onConfirmArticle:id=>acknowledgeAttention([id]),onSelect:graphSelection,onAcknowledge:graphAcknowledge}));}
    else layout.append(empty('관계도를 준비하고 있습니다','화면을 새로고침해 주세요. 기존 계층·표·근거 보기는 아래에 유지됩니다.'));
    layout.append(graphInspector(S.graphSelection||contextualCenter));panel.append(layout);root.append(panel);
  }
  function renderBusinessMaps(root,regionMode=false){
    const panel=el('section','business-map-panel');panel.id=regionMode?'regionMaps':'businessMaps';const controls=el('div','map-workspace-controls');controls.append(button('지도 표시 기준','button small',visualizationChoices));panel.append(controls);
    const settings=visualSettings(),mapData=annotatedMaps(S.data?.maps?.variants?.[settings.position_policy]);
    if(!settings.position_policy||!settings.map_mode){panel.append(add(el('div','map-policy-required'),el('p','','지도 배치와 미확인 좌표 표시 기준을 선택해 주세요. 사업장 위치를 임의로 정하지 않습니다.'),button('표시 기준 선택','button primary',visualizationChoices)));}
    else if(window.AtlasMap&&mapData){panel.append(window.AtlasMap.create({layers:mapData,mode:settings.map_mode,positionPolicy:settings.position_policy,scope:S.scope,detailMode:regionMode?'articles':'projects',selectedMarkerId:S.mapSelection,describeMarker:mapDescription,onClearSelection:()=>{S.mapSelection=null;S.graphSelection=null;S.dashboardArticleIds=null;S.dashboardRegionName='';render();},onProjectSelect:p=>focusProject(p),onArticlesSelect:marker=>articleCollection(marker.article_ids,marker.name||'지도 선택 근거'),viewKey:`maps:${newsParams()}:${settings.map_mode}:${settings.position_policy}`,onSelect:marker=>{S.mapSelection=marker.id;if(S.view==='overview'){S.dashboardArticleIds=marker.article_ids||[];S.dashboardRegionName=marker.name||'선택 지역';}const node=(ontology().nodes||[]).find(n=>marker.project_id?n.type==='project'&&n.entity_id===marker.project_id:n.id===marker.location_group_id||n.entity_id===marker.location_group_id);const available=mapDescription(marker).projects,chosen=available.find(p=>(p.is_candidate?`candidate:${p.id}`:p.id)===S.projectFocus)||available[0];S.projectFocus=marker.project_id||(chosen?(chosen.is_candidate?`candidate:${chosen.id}`:chosen.id):null);S.explorerRole='all';S.companyCategory='all';S.graphCluster=null;S.graphSelection=node?{kind:'node',id:node.id,node,article_ids:marker.article_ids}: {kind:'node',id:marker.id,node:{...marker,type:'location'},article_ids:marker.article_ids};render();}}));}
    root.append(panel);
  }
  function annotatedMaps(value){
    if(!value)return value;const result=structuredClone(value);
    const annotate=marker=>{const articles=new Set(marker.article_ids||[]);marker.unread_count=attentionItems().filter(item=>item.unread&&(marker.project_id?(item.project_ids||[]).includes(marker.project_id):(item.article_ids||[]).some(id=>articles.has(id)))).length;};
    (result.scope_layers||[]).forEach(layer=>(layer.markers||[]).forEach(annotate));return result;
  }
  function renderRegions(root){
    renderBusinessMaps(root,true);
    const articles=nitems('articles'),groups=new Map();
    articles.forEach(a=>{const scope=a.scope_classification?.primary_scope||'unresolved',domestic=['kr-dc','kr-ai'].includes(scope),values=domestic?(a.geography?.cities||[]).map(value=>({key:`city:${value}`,name:value,city:value})):(a.geography?.countries||[]).filter(c=>c!=='KR').map(value=>({key:`country:${value}`,name:countryName(value),country:value}));
      if(!values.length)values.push({key:'unknown',name:'지역 미확인'});
      values.forEach(place=>{if(!groups.has(place.key))groups.set(place.key,{...place,articles:[]});groups.get(place.key).articles.push(a);});
    });
    groups.forEach(group=>{group.articles=[...new Map(group.articles.map(article=>[article.id,article])).values()];});
    const panel=el('section','panel region-index');add(panel,section('지역별 사업·기업 관측','지역은 기사에 명시된 도시·국가입니다. 기업 본사나 기사 발행 매체 위치를 사업장으로 쓰지 않습니다.'));
    if(S.city||S.country)panel.append(button('지역 조건 해제','button small',()=>{S.city='';S.country='';S.mapSelection=null;load();}));
    const cards=el('div','region-cards');[...groups.values()].sort((a,b)=>b.articles.length-a.articles.length||a.name.localeCompare(b.name)).forEach(group=>{const ids=new Set(group.articles.map(a=>a.id)),companies=oitems('companies').filter(c=>(c.article_ids||[]).some(id=>ids.has(id))),projects=oitems('projects').filter(p=>(p.article_ids||[]).some(id=>ids.has(id))),candidates=discoveredProjects().filter(p=>(p.article_ids||[]).some(id=>ids.has(id))),unread=group.articles.filter(a=>a.is_new).length,card=el('article','region-card');
      add(card,el('h3','',group.name),el('p','region-card-count',`기사 ${ids.size}개 · 새 기사 ${unread}개`),el('p','',`등록 사업 ${projects.length}개 · 사업명 후보 ${candidates.length}묶음 · 기업 ${companies.length}개`));
      const counts=el('div','tag-list');Object.entries(scopeLabels).forEach(([scope,label])=>{const count=group.articles.filter(a=>(a.scope_classification?.primary_scope||'unresolved')===scope).length;if(count)counts.append(badge(`${label} ${count}`,'neutral'));});card.append(counts);
      const latest=group.articles.slice().sort((a,b)=>String(b.published_at).localeCompare(String(a.published_at)))[0];if(latest)add(card,link(latest.title+' ↗',latest.url),el('small','',`${latest.publisher} · ${date(latest.published_at)}`));
      const actions=el('div','card-actions');actions.append(button('지역 근거 기사','button small',()=>articleCollection([...ids],`${group.name} 지역 근거`)));if(group.city||group.country)actions.append(button('이 지역으로 좁히기','button small',()=>{S.city=group.city||'';S.country=group.country||'';S.mapSelection=null;load();}));card.append(actions);cards.append(card);
    });if(!groups.size)cards.append(empty('현재 조건에 지역 관측이 없습니다','기간이나 범위를 바꿔 확인하세요.'));panel.append(cards);root.append(panel);
    renderDiscoveryLedger(root);
  }
  function renderNotifications(root){
    const counts=S.data?.attention?.counts||{};
    root.append(section(`신규·변경 확인 · ${counts.unread||0}건 미확인`,`새 기사 ${counts.unread_new_articles||0}건 · 등록 근거 변화 ${counts.unread_fact_changes||0}건 · 현재 기간·분류 조건`,button('확인 범위 설정','button small',visualizationChoices)));
    root.append(el('p','callout','노드·관계선·원문을 여는 동작은 확인 처리하지 않습니다. 아래에서 선택하거나 개별 확인 버튼을 누르면 관계도의 강조 표시에도 반영됩니다.'));
    root.append(attentionList(attentionItems()));
    const history=el('details','panel retained-notifications');history.append(el('summary','','기존 로컬 알림 발송 기록과 확인 상태'));renderNotificationHistory(history);root.append(history);
  }
  function renderOverviewLegacy(root) {
    renderVisualNetwork(root);
    if(S.explorerMode==='company'){const details=el('details','panel retained-company-details');details.open=Boolean(S.companyDetailsOpen);details.append(el('summary','','기업별 상세 · 역할 근거 · 미래 일정 · 사내 자료 링크'));details.addEventListener('toggle',()=>{S.companyDetailsOpen=details.open;});renderCompanies(details,false);root.append(details);return;}
    renderDiscoveryLedger(root);
    const hierarchy=el('details','retained-ontology');hierarchy.open=Boolean(S.legacyOntologyOpen);hierarchy.append(el('summary','','계층형 온톨로지 · 기존 전체 취합 보기'));renderOntology(hierarchy);root.append(hierarchy);
    renderNewsPulse(root);
    const projects = matchingProjects(true);
    if (!projects.some(p => p.id === S.selected)) S.selected = projects[0]?.id || null;
    const explorer = el('section', 'explorer'); explorer.setAttribute('aria-label', '사업 관계 탐색');
    const graphPanel = el('div', 'graph-panel');
    const graphHead = add(el('div', 'graph-head'), add(el('div'), el('h2', '', '사업 관계 지도'), el('p', '', S.includeRead ? '전체 변화 · 영업 중요도순 · 공개 근거로 확인된 관계' : '미확인 변화 · 영업 중요도순 · 공개 근거로 확인된 관계')), el('span', 'graph-count', `${projects.length} PROJECTS`));
    const filters = el('div', 'graph-filters');
    function filter(label, key, values) {
      const s = el('select'); s.setAttribute('aria-label', label); const op = el('option', '', label); op.value = ''; s.append(op);
      [...new Set(values.filter(Boolean))].sort().forEach(v => { const o = el('option', '', key==='region'?v.replace(/^kr:/,'국내 · ').replace(/^global:/,'해외 · '):v); o.value = v; s.append(o); }); s.value = S[key];
      s.addEventListener('change', () => { S[key] = s.value; S.selected = null; render(); }); filters.append(s);
    }
    filter('나라 / 국내 도시', 'region', arr('projects').map(p => geography(p).key)); filter('전체 역할', 'role', arr('relationships').filter(r=>r.directness==='explicit').map(r => r.role)); filter('전체 단계', 'stage', arr('projects').map(p => p.status));
    const actions = el('div', 'graph-actions');
    const stage = el('div', 'graph-stage'); stage.id = 'graphStage';
    const graph = createGraph(projects); stage.append(graph);
    function setZoom(value) { S.zoom = Math.max(.65, Math.min(2, value)); const g = graph.querySelector('[data-scene]'); if (g) g.setAttribute('transform', `translate(${450 * (1-S.zoom)} ${220 * (1-S.zoom)}) scale(${S.zoom})`); }
    add(actions, button('−', '', () => setZoom(S.zoom - .15)), button('+', '', () => setZoom(S.zoom + .15)), button('초기화', 'wide', () => setZoom(1)), button('⛶', '', async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else await stage.requestFullscreen(); } catch { toast('현재 브라우저에서 전체화면을 지원하지 않습니다.', true); } }));
    [...actions.children].forEach((b,i) => b.setAttribute('aria-label', ['관계 지도 축소', '관계 지도 확대', '관계 지도 배율 초기화', '관계 지도 전체화면'][i]));
    if (!projects.length) stage.append(el('div', 'graph-empty', '조건에 맞는 미확인 변화가 없습니다.\n읽은 변화 포함을 켜거나 검색·필터를 해제해 보세요.'));
    const legend = el('div', 'graph-legend'); [['#a5b4fc','AI 수요·테넌트'], ['#5eead4','개발·운영'], ['#fcd34d','설계·CM'], ['#93c5fd','시공']].forEach(([color,label]) => { const n = el('span'); const i = el('i'); i.style.background = color; add(n,i,document.createTextNode(label)); legend.append(n); }); legend.append(el('span', '', '실선 = 출처에 명시된 관계'));
    add(graphPanel, graphHead, add(el('div','graph-toolbar'), filters, actions), stage, legend);
    add(explorer, graphPanel, renderDetail(find('projects', S.selected)));
    const historical=el('details','historical-projects');historical.append(el('summary','','공식 발표 고정 사례 · 사업 상세와 검증된 역할 지도'),el('p','metadata-label','기존 4개 사업은 공식 발표 당시 자료의 모의 처리 사례입니다. 수집 기사 전체나 현재 검증된 신규 사업 수를 뜻하지 않습니다.'),explorer);root.append(historical);setZoom(S.zoom);
    renderHighlights(root);
    root.append(section('검증 근거의 사업 변화', '공식 고정 사례입니다. 단순 재수집과 기사 발견은 사업 사실 변경과 구분합니다.', button('사업 전체 보기 ↗', 'button text', () => navigate('projects'))));
    const ids = new Set(projects.map(p => p.id)); const read = new Set(arr('read_states').map(r => r.id));
    const changes = arr('changes').filter(c => ids.has(c.project_id) && (S.includeRead || !read.has(c.id))).sort((a,b) => (Number(b.importance)||0)-(Number(a.importance)||0));
    const grid = el('div', 'changes-grid');
    changes.slice(0, 6).forEach((c,i) => { const p = find('projects', c.project_id); const card = button('', 'change-card', () => { selectProject(c.project_id); $('#graphStage')?.scrollIntoView({block:'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}); }); add(card, add(el('div','card-meta'), el('span','card-index', `${String(i+1).padStart(2,'0')} / ${scopeLabels[p?.scope] || '공개 자료'}`), badge(read.has(c.id) ? '확인 완료' : '미확인', read.has(c.id) ? 'neutral' : 'warning')), el('h3','',text(p?.name)), el('p','',Array.isArray(c.summary) ? c.summary.join(' ') : text(c.summary)), add(el('div','card-bottom'), el('span','',date(c.meaningful_at)),el('span','',`${(c.article_ids||[]).length}개 근거 ↗`))); grid.append(card); });
    if (!changes.length) grid.append(empty('미확인 변화가 없습니다', '읽은 변화 포함에서 기존 사업을 계속 탐색할 수 있습니다.')); root.append(grid);
    root.append(section('사업 구성 미리보기', '그래프와 같은 프로젝트를 표로 확인합니다.', button('구성표 열기 ↗', 'button text', () => navigate('projects')))); root.append(projectTable(projects.slice(0,5)));
  }
  function workspaceGraph(root,data,{id,title,mode='project',centerId=null}={}){
    const panel=el('section','visual-ontology workspace-network');panel.id=id;panel.dataset.workspaceScope=S.scope;
    panel.append(section(title,'선택한 범위의 기사 근거를 연결합니다. 점선 관측과 확인된 참여는 구분하며 직접 계약을 뜻하지 않습니다.'));
    const display=compactNetwork(data,mode,centerId),layout=el('div','visual-network-layout');
    const selected=display.nodes.find(n=>n.id===S.graphSelection?.id),edge=display.edges.find(e=>e.id===S.graphSelection?.id),center=display.nodes.find(n=>n.id===centerId);
    const context=selected?{kind:'node',id:selected.id,node:selected,article_ids:selected.article_ids}:edge?{kind:'edge',id:edge.id,edge,article_ids:edge.article_ids}:center?{kind:'node',id:center.id,node:center,article_ids:center.article_ids}:null;
    if(window.AtlasGraph)layout.append(window.AtlasGraph.create({nodes:display.nodes,edges:display.edges,mode,centerId,height:620,title,selectedId:context?.id,totalNodes:data.graph?.total_nodes||data.nodes.length,viewKey:`${S.view}:${S.scope}:${newsParams()}:${centerId||'scope'}:${S.graphCluster?.id||'summary'}`,articleAlerts:attentionItems(),onArticleAlerts:showAttention,onConfirmArticle:id=>acknowledgeAttention([id]),onSelect:graphSelection,onAcknowledge:graphAcknowledge}));
    else layout.append(empty('관계도를 준비하고 있습니다','저장된 근거와 기사 목록은 아래에서 볼 수 있습니다.'));
    const inspector=graphInspector(context);if(mode==='company-network'&&context?.node&&['project','pending'].includes(context.node.type))inspector.append(button('PROJECT에서 사업·기사 보기','button small',()=>focusProject({id:context.node.entity_id,is_candidate:!!context.node.is_named_candidate})));layout.append(inspector);panel.append(layout);root.append(panel);
  }
  function workspaceArticles(root,articles,title,key){
    const rows=[...new Map(articles.map(a=>[a.id,a])).values()].sort((a,b)=>String(b.published_at||'').localeCompare(String(a.published_at||''))||a.id.localeCompare(b.id));
    const panel=el('section','workspace-evidence');panel.dataset.evidenceContext=key;panel.append(section(`${title} · ${rows.length}개`,'최신 발행순 · 원문 열기와 확인·스크랩은 별도 동작입니다.'));
    S.workspacePages||={};const pages=Math.max(1,Math.ceil(rows.length/24)),page=Math.max(1,Math.min(S.workspacePages[key]||1,pages)),pager=el('div','news-pagination');
    const prev=button('← 이전','button small',()=>{S.workspacePages[key]=page-1;render();}),next=button('다음 →','button small',()=>{S.workspacePages[key]=page+1;render();});prev.disabled=page<=1;next.disabled=page>=pages;
    add(pager,el('span','',`${page} / ${pages} · 전체 ${rows.length}개`),prev,next);panel.append(pager);
    const feed=el('div','source-grid workspace-articles');rows.slice((page-1)*24,page*24).forEach(a=>feed.append(sourceCard(a,true)));if(!rows.length)feed.append(empty('현재 조건의 연결 기사가 없습니다','기간·범위를 조정하거나 검색 조건을 해제해 보세요.'));panel.append(feed);root.append(panel);
  }
  function renderOverview(root){
    const model=window.AtlasWorkspaces?.dashboard(S.data);if(!model){root.append(empty('DASHBOARD를 준비하고 있습니다','화면을 새로고침해 주세요.'));return;}
    const stats=el('section','dashboard-stats');stats.setAttribute('aria-label','DASHBOARD 확인 현황');
    const showCandidates=()=>{const content=el('div');content.append(el('p','callout',model.counting_note));model.new_candidate_projects.forEach(p=>content.append(button(p.name,'button dashboard-project-link',()=>{$('#modal').close();focusProject({...p,is_candidate:true});})));if(!model.new_candidate_projects.length)content.append(empty('새 기사에 연결된 사업명 관측이 없습니다','확인 상태와 현재 기간·범위에 따른 결과입니다.'));modal('신규 사업 관측',content);};
    [['신규 기사',model.counts.new_articles,'아직 확인하지 않은 기사',()=>articleCollection(model.new_articles.map(a=>a.id),'신규 기사')],['신규 사업 관측',model.counts.new_candidate_projects,'새 기사에 연결된 사업명 후보',showCandidates],['협약·계약 뉴스',model.counts.agreement_articles,'업무협약·계약·수주 제목 신호',()=>articleCollection(model.agreement_articles.map(a=>a.id),'협약·계약 뉴스')],['확인 대기',model.counts.unread_attention,'선택한 알림만 확인 처리',()=>showAttention()]].forEach(([label,count,note,action])=>{const card=button('','dashboard-stat',action);add(card,el('span','',label),el('strong','',Number(count).toLocaleString()),el('small','',note));stats.append(card);});root.append(stats);
    root.append(el('p','workspace-count-note',`${scopeLabels[S.scope]||'전체'} · 선택 기간 기사 ${model.counts.articles}개. 신규 사업 관측은 고유 확정 사업 수가 아니며 협약·계약 뉴스는 기사 제목 신호입니다.`));
    renderAIBriefing(root);
    workspaceGraph(root,discoveryGraph(ontology()),{id:'dashboardNetwork',title:`${scopeLabels[S.scope]||'전체'} · 범위 전체 관계도`});
    renderBusinessMaps(root,true);
    const regionalIds=S.dashboardArticleIds?new Set(S.dashboardArticleIds):null;workspaceArticles(root,regionalIds?model.articles.filter(a=>regionalIds.has(a.id)):model.articles,regionalIds?`${S.dashboardRegionName} 관련 기사`:'범위별 관련 기사',`dashboard:${S.scope}:${S.mapSelection||'all'}`);
    const advanced=el('details','workspace-advanced');advanced.append(el('summary','','사업명 후보·식별 보류 자료 보기'));renderDiscoveryLedger(advanced);root.append(advanced);
  }
  function companyClassificationForm(company){
    const current=companyCategories(company);formShell(`${company.name} · 기업 성격 분류`,grid=>{
      grid.append(el('p','callout field full','회사 자체의 성격을 분류합니다. 특정 사업의 참여 역할·계약은 바뀌지 않으며 자동 근거와 변경 이력을 보존합니다.'));
      const choices=el('fieldset','classification-grid field full');choices.append(el('legend','','기업 성격 · 복수 선택 가능'));
      companyCategoryNames().forEach(category=>{const input=el('input');input.type='checkbox';input.name='category';input.value=category.id;input.checked=current.includes(category.id);choices.append(add(el('label'),input,document.createTextNode(category.label)));});grid.append(choices);field(grid,'분류 메모 · 선택','note',company.manual_classification?.note||'','textarea',true);
    },async form=>{const categories=form.getAll('category');if(!categories.length)throw Error('기업 성격을 선택해 주세요.');if(categories.includes('unknown')&&categories.length>1)throw Error('성격 미확인은 다른 성격과 함께 선택할 수 없습니다.');await mutate('/api/company-classification',{company_id:company.id,categories,note:form.get('note')||''},'기업 성격을 저장했습니다. 자동 분류와 변경 이력을 보존합니다.');});
  }
  function renderCompanies(root){
    const catalog=companyCatalog(),categories=companyCategoryNames(),controls=el('section','company-workspace-controls');
    const nature=el('select');nature.setAttribute('aria-label','COMPANY 기업 성격');[['all','전체 성격'],...categories.map(r=>[r.id,r.label])].forEach(([id,label])=>nature.append(Object.assign(el('option','',`${label} · ${id==='all'?catalog.length:catalog.filter(c=>companyCategories(c).includes(id)).length}`),{value:id})));nature.value=S.companyCategory||'all';nature.addEventListener('change',()=>{S.companyCategory=nature.value;S.companyFocus=null;S.graphSelection=null;S.graphCluster=null;render();});
    const search=el('input');search.type='search';search.placeholder='기업 이름 검색';search.setAttribute('aria-label','COMPANY 기업 이름 검색');search.value=S.companyNameFilter||'';
    const matches=catalog.filter(companyCategoryMatches).filter(c=>!search.value||c.name.toLocaleLowerCase().includes(search.value.toLocaleLowerCase())),selected=matches.find(c=>c.id===S.companyFocus)||matches.find(c=>c.selected_article_count>0)||matches[0];S.companyFocus=selected?.id||null;
    const select=el('select');select.setAttribute('aria-label','COMPANY 중심 기업');select.append(Object.assign(el('option','','기업 선택'),{value:''}));matches.forEach(c=>select.append(Object.assign(el('option','',c.name),{value:c.id})));select.value=selected?.id||'';select.addEventListener('change',()=>focusCompany(select.value));
    const searchAction=()=>{S.companyNameFilter=search.value.trim();S.companyFocus=null;S.graphSelection=null;S.graphCluster=null;render();};search.addEventListener('keydown',e=>{if(e.key==='Enter')searchAction();});
    add(controls,nature,search,button('기업 찾기','button small',searchAction),select);if(selected)controls.append(button('기업 분류 관리','button primary small',()=>companyClassificationForm(selected)));root.append(controls);
    if(!selected){root.append(empty('이 조건의 기업이 없습니다','전체 성격이나 다른 이름으로 검색해 보세요. 미확인 기업도 분류 관리에서 직접 지정할 수 있습니다.'));return;}
    const model=window.AtlasWorkspaces?.companyGraph(S.data,selected.id);if(!model)return;
    const profile=el('div','company-profile-strip');add(profile,el('strong','',selected.name),...companyCategories(selected).map(id=>badge(categories.find(c=>c.id===id)?.label||roleName(id),'neutral')),el('small','',selected.company_profile?.manual_override?'사용자 분류':selected.profile_evidence?.some(e=>e.status==='classification_proposal')?'자동 분류 후보 포함':'자동 근거 분류'));
    if(selected.company_profile?.manual_override)profile.append(button('자동 분류로 복귀','button text small',async()=>{try{await mutate('/api/company-classification',{company_id:selected.id,reset:true},'사용자 분류를 해제했습니다. 이전 분류 이력은 보존합니다.');}catch{}}));root.append(profile);
    workspaceGraph(root,model,{id:'companyNetwork',title:`${selected.name} · 1단계 관계사 · DC/AIDC 프로젝트`,mode:'company-network',centerId:model.centerId});
    const projects=el('section','workspace-project-context');projects.append(section(`관련 사업지 · ${model.projects.length}개`,'등록 사업과 기사 사업명 후보를 구분합니다. 같은 이름의 관측은 동일 부지·참여 확정이 아닙니다.'));
    const cards=el('div','workspace-project-cards');model.projects.forEach(project=>{const card=el('article','workspace-project-card'),candidate=project.is_named_candidate||project.kind==='candidate';add(card,badge(candidate?'기사 사업명 후보':'등록 사업','neutral'),button(project.name,'button text',()=>focusProject({...project,is_candidate:candidate})),el('p','',project.location||(project.cities||[]).join(' · ')||project.country||'지역 미확인'),el('small','',`관련 기사 ${project.article_ids?.length||0}개`));cards.append(card);});if(!model.projects.length)cards.append(empty('연결된 사업지가 없습니다','회사 이름 관측만 있는 기사와 실제 사업 연결을 구분합니다.'));projects.append(cards);root.append(projects);
    workspaceArticles(root,ontologyArticles(model.article_ids),`${selected.name} 관련 기사`,`company:${selected.id}:${S.scope}`);
    const detail=el('details','workspace-advanced company-details');detail.append(el('summary','','기업 요약·키워드·미래 일정·사내 자료'));
    const context=oitems('companies').find(c=>c.id===selected.id)||selected;add(detail,...(context.summary_lines||[]).map(v=>el('p','',typeof v==='object'?v.text:v)));
    const keywords=el('div','company-keyword-actions');(context.keywords||[]).forEach(k=>keywords.append(button(`${k.label} · ${k.article_ids?.length||0}개`,'button small',()=>articleCollection(k.article_ids,`${selected.name} · ${k.label}`))));detail.append(keywords);
    const plans=arr('projects').filter(p=>(p.company_ids||[]).includes(selected.id)||(selected.project_ids||[]).includes(p.id));let milestones=0;plans.forEach(p=>(p.milestones||[]).forEach(m=>{if(parseInt(String(m.date||''),10)<new Date().getFullYear())return;detail.append(el('p','',`${date(m.date)} · ${p.name} · ${m.kind||'공개 일정'} · ${term(m.basis)}`));milestones++;}));if(!milestones)detail.append(el('p','muted','공개된 향후 일정은 현재 미확인입니다.'));detail.append(button('기업 상세·사내 자료 링크','button small',()=>openCompany(selected.id)));root.append(detail);
  }
  function renderProjects(root){
    const choices=[...oitems('projects').map(p=>({...p,is_candidate:false})),...discoveredProjects()],selected=choices.find(p=>(p.is_candidate?`candidate:${p.id}`:p.id)===S.projectFocus)||choices.filter(p=>p.is_candidate).sort((a,b)=>(b.article_count||0)-(a.article_count||0))[0]||choices[0];
    const controls=el('section','project-workspace-controls'),select=el('select');select.setAttribute('aria-label','PROJECT 중심 프로젝트');choices.forEach(p=>select.append(Object.assign(el('option','',`${p.is_candidate?'[기사 후보] ':'[등록] '}${p.name}`),{value:p.is_candidate?`candidate:${p.id}`:p.id})));select.value=selected?(selected.is_candidate?`candidate:${selected.id}`:selected.id):'';select.addEventListener('change',()=>{S.projectFocus=select.value;S.graphSelection=null;S.graphCluster=null;render();});controls.append(select);root.append(controls);
    if(!selected){root.append(empty('선택할 프로젝트 근거가 없습니다','현재 범위의 기사에서 안전하게 추출한 사업명이 없으면 식별 보류로 남깁니다.'));workspaceArticles(root,nitems('articles'),'사업명 식별 보류 기사',`project-pending:${S.scope}`);return;}
    S.projectFocus=selected.is_candidate?`candidate:${selected.id}`:selected.id;const centerId=selected.is_candidate?`discovery:${selected.id}`:`project:${selected.id}`;
    workspaceGraph(root,discoveryGraph(ontology()),{id:'projectNetwork',title:`${selected.name} · 기업·근거 관계도`,centerId});
    const summary=el('section','panel project-context-summary');add(summary,badge(selected.user_confirmed_identity?'사용자 확인 연결 · 원본 보존':selected.is_candidate?'기사 사업명 후보 · 확인 전':'등록 사업 근거','neutral'),el('h2','',selected.name),el('p','',selected.location||(selected.cities||[]).join(' · ')||selected.country||'지역 미확인'));
    const lines=selected.summary_lines||selected.summary||[];(Array.isArray(lines)?lines:[lines]).slice(0,4).forEach(line=>summary.append(el('p','',typeof line==='object'?line.text:line)));
    const ids=selected.article_ids||[],links=(S.data?.project_discovery?.company_links||[]).filter(e=>e.project_id===selected.id),names=[...new Set(links.map(e=>`${companyCatalog().find(c=>c.id===e.company_id)?.name||'관측 기업'} · ${roleName(e.role||'unknown')} · ${e.is_confirmed_participation?'명시 저장':'기사 관측'}`))];if(selected.user_confirmed_identity)summary.append(el('p','callout',`사용자 확인 연결 · 별칭: ${(selected.aliases||[]).join(' · ')} · 원본/수치는 유지하며 직접 계약은 미확인입니다.`));names.forEach(value=>summary.append(el('p','project-participant',value)));if(!names.length)summary.append(el('p','muted','현재 기사에서 연결 기업·참여 역할 근거가 부족합니다.'));root.append(summary);
    if(selected.user_confirmed_identity){const sourceIds=new Set(selected.source_project_ids||[]),source=(S.data?.identity_display?.source_projects||[]).filter(p=>sourceIds.has(p.id));if(source.length){const original=el('details','workspace-advanced');original.append(el('summary','','연결 전 사업 정보·수치·근거'));source.forEach(p=>{const card=el('section','panel');add(card,el('h3','',p.name),el('p','metadata-label',`원본 ${p.id} · ${text(p.entity_level,'수준 미확인')} · ${text(p.phase,'단계 미확인')}`));(p.capacities||[]).forEach(c=>card.append(el('p','',`${text(c.metric,'용량 구분 미확인')} · ${text(c.value)} ${text(c.unit,'')} · ${text(c.status,'상태 미확인')}`)));if(p.capacity!=null&&typeof p.capacity!=='object')card.append(el('p','',`원본 용량 표현: ${p.capacity} · 단위/계획 여부는 원문 확인`));card.append(articleRefs(p.article_ids||[]));original.append(card);});root.append(original);}}
    workspaceArticles(root,ontologyArticles(ids),'선택 프로젝트 관련 기사',`project:${selected.id}:${S.scope}`);
    const identity=el('details','workspace-advanced');identity.append(el('summary','','중복 후보 확인·대표 사업 연결·별칭·해제 이력'),el('p','muted','확인한 후보만 함께 표시합니다. 원본 사업·기사·숫자·읽음·스크랩은 유지하며 직접 계약을 확정하지 않습니다.'),button('대표 사업 연결 관리','button',()=>openProjectIdentity()));root.append(identity);
    const location=el('details','workspace-advanced');location.append(el('summary','','사업 위치 지도·범위 전체 사업명 후보'));renderBusinessMaps(location);renderDiscoveryLedger(location);root.append(location);
    const records=el('details','workspace-advanced');records.append(el('summary','','등록 사업 구성표·계획/실제·용량/일정 근거'));records.append(projectTable(matchingProjects()));if(!selected.is_candidate&&find('projects',selected.id))records.append(renderDetail(find('projects',selected.id)));root.append(records);
  }
  function createGraph(projects) {
    const ns = 'http://www.w3.org/2000/svg';
    function svg(tag, attrs, value) { const n = document.createElementNS(ns,tag); for(const [k,v] of Object.entries(attrs||{})) n.setAttribute(k,v); if(value !== undefined) n.textContent = value; return n; }
    const mobile=matchMedia('(max-width:560px)').matches;const columns=mobile?1:2;
    const groups=new Map();projects.forEach(p=>{const geo=geography(p);if(!groups.has(geo.key))groups.set(geo.key,{...geo,projects:[]});groups.get(geo.key).projects.push(p);});
    let offset=12;const positions=new Map();groups.forEach(group=>{group.top=offset;const closed=S.closedGroups.has(group.key);group.height=closed?58:Math.ceil(group.projects.length/columns)*210+65;group.projects.forEach((p,i)=>positions.set(p.id,{x:230+(i%columns)*440,y:offset+132+Math.floor(i/columns)*210,closed}));offset+=group.height+12;});
    const height = Math.max(400,offset);
    const root = svg('svg',{viewBox:`0 0 ${mobile?460:900} ${height}`,role:'group','aria-label':'사업 및 기업 관계 지도. 탭 키로 사업, 기업, 관계를 선택할 수 있습니다.'});
    root.style.minWidth=mobile?'460px':'780px';root.style.height=`${height}px`;root.style.position='relative';
    const scene = svg('g', {'data-scene':'true'}); root.append(scene);
    groups.forEach(group=>{const width=mobile?440:880;scene.append(svg('rect',{x:10,y:group.top,width,height:group.height,rx:9,fill:'#102238',stroke:'#31475e'}));const header=svg('g',{class:'graph-node graph-group',role:'button',tabindex:'0','aria-expanded':!S.closedGroups.has(group.key),'aria-label':`${group.label} 사업 ${group.projects.length}개 그룹 접기 또는 펼치기`});header.append(svg('rect',{x:20,y:group.top+7,width:width-140,height:34,fill:'transparent','pointer-events':'all'}));header.append(svg('text',{x:27,y:group.top+29,fill:'#c9f4eb','font-size':13,'font-weight':600},`${S.closedGroups.has(group.key)?'＋':'−'} ${group.label} · ${group.projects.length}개 사업`));const toggle=()=>{S.closedGroups.has(group.key)?S.closedGroups.delete(group.key):S.closedGroups.add(group.key);render();};header.addEventListener('click',toggle);header.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();toggle();}});scene.append(header);const articleCount=nitems('articles').filter(a=>group.domestic?(a.geography?.cities||[]).includes(group.value):(a.geography?.countries||[]).some(c=>countryName(c)===group.value)).length;const go=svg('g',{class:'graph-node',role:'button',tabindex:'0','aria-label':`${group.label} 기사 보기`});go.append(svg('rect',{x:width-115,y:group.top+7,width:110,height:34,fill:'transparent','pointer-events':'all'}));go.append(svg('text',{x:width-15,y:group.top+29,fill:'#80c8bd','font-size':10,'text-anchor':'end'},`기사 ${articleCount}개 ↗`));const open=()=>openGeoNews(group);go.addEventListener('click',open);go.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();open();}});scene.append(go);});
    const truncate = (s,n) => { const v=text(s);let length=0,result='';for(const c of v){length+=c.charCodeAt(0)>255?1.8:1;if(length>n)return result+'…';result+=c;}return result; };
    const colors = role => /설계|CM|design/i.test(role) ? '#fcd34d' : /시공|construction/i.test(role) ? '#93c5fd' : /테넌트|수요|tenant|demand/i.test(role) ? '#a5b4fc' : '#5eead4';
    projects.forEach((p,index) => {
      const position=positions.get(p.id);if(position.closed)return;const {x,y}=position;
      const relations = arr('relationships').filter(r => r.project_id === p.id);
      const rels = relations.slice(0,4);
      rels.forEach((r,ri) => {
        const c = find('companies',r.company_id); if (!c) return;
        const right = ri % 2 === 1; const cx = x + (right ? 156 : -156); const cy = y + (ri < 2 ? -62 : 75);
        const line = svg('path',{d:`M ${x} ${y} C ${x} ${cy}, ${cx} ${y}, ${cx} ${cy}`,class:'graph-line',tabindex:'0',role:'button','aria-label':`${p.name}, ${c.name}, ${r.role}, 근거 ${(r.article_ids||[]).length}개`});
        line.append(svg('title',{}, `${c.name} · ${r.role} · 출처 명시 관계`));
        const relationAction=()=>{S.selected=p.id;render();toast(`${c.name} · ${r.role} · 출처 명시 관계`);}; line.addEventListener('click',relationAction); line.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();relationAction();}}); scene.append(line);
        const node = svg('g',{class:'graph-node',tabindex:'0',role:'button','aria-label':`${c.name}, 역할 ${r.role}. 기업 상세 열기`,transform:`translate(${cx-69} ${cy-23})`});
        node.append(svg('rect',{width:138,height:46,rx:6,fill:'#15283f',stroke:'#435b74'}),svg('circle',{cx:12,cy:13,r:2.5,fill:colors(r.role)}),svg('text',{x:21,y:16,fill:colors(r.role),'font-size':8},truncate(r.role,19)),svg('text',{x:12,y:33,fill:'#ecf2fa','font-size':10},truncate(c.name,18)),svg('title',{},`${c.name} / ${r.role}`));
        node.addEventListener('click',()=>openCompany(c.id)); node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openCompany(c.id);}});scene.append(node);
      });
      const node = svg('g',{class:`graph-node${S.selected===p.id?' selected':''}`,tabindex:'0',role:'button','aria-pressed':S.selected===p.id?'true':'false','aria-label':`${p.name}, ${scopeLabels[p.scope]||p.scope}, ${text(p.status)}. 사업 상세 선택`,transform:`translate(${x-97} ${y-35})`});
      node.append(svg('rect',{width:194,height:70,rx:8,fill:'#193c43',stroke:'#468a82'}),svg('text',{x:13,y:19,fill:'#79dece','font-size':8,'letter-spacing':1},`${scopeLabels[p.scope]||'PROJECT'} / ${p.entity_level||'site'}`),svg('text',{x:13,y:38,fill:'#f4f9ff','font-size':12,'font-weight':600},truncate(p.name,22)),svg('text',{x:13,y:55,fill:'#c1d5dc','font-size':8},truncate(`${text(p.location,p.country)} · ${text(p.status)}`,34)),svg('title',{},p.name));
      if(unread(p)) node.append(svg('circle',{cx:181,cy:13,r:3,fill:'#fcd34d'}));
      if(relations.length>4) node.append(svg('text',{x:180,y:83,fill:'#9eafc4','font-size':8,'text-anchor':'end'},`외 ${relations.length-4}개 관계 · 상세에서 전체 확인`));
      node.addEventListener('click',()=>selectProject(p.id));node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectProject(p.id);}});scene.append(node);
    });
    let drag=null; let panX=0, panY=0;
    root.addEventListener('pointerdown',e=>{if(e.target===root){drag={x:e.clientX,y:e.clientY,px:panX,py:panY};root.setPointerCapture(e.pointerId);}});
    root.addEventListener('pointermove',e=>{if(!drag)return;const factor=900/root.getBoundingClientRect().width;panX=drag.px+(e.clientX-drag.x)*factor;panY=drag.py+(e.clientY-drag.y)*factor;scene.setAttribute('transform',`translate(${450*(1-S.zoom)+panX} ${220*(1-S.zoom)+panY}) scale(${S.zoom})`);});
    root.addEventListener('pointerup',()=>{drag=null;});root.addEventListener('pointercancel',()=>{drag=null;}); return root;
  }
  function renderDetail(project) {
    const root=el('aside','detail-panel');root.setAttribute('aria-label','선택 사업 상세');
    if(!project){add(root,el('p','eyebrow','PROJECT INTELLIGENCE'),el('h2','','새로운 변화를 기다리는 중'),el('p','muted','지도의 사업 또는 구성표를 선택하면 요약과 근거가 이곳에 연결됩니다.'));return root;}
    const changes=projectChanges(project);add(root,add(el('div','detail-top'),el('span','eyebrow','PROJECT INTELLIGENCE'),badge(unread(project)?'미확인 변화':'확인 완료',unread(project)?'warning':'neutral')),el('h2','',project.name),el('p','detail-location',`${text(project.country)} / ${text(project.location)} · ${text(project.entity_level)}`));
    const summary=el('ul','detail-summary');(project.summary||[]).slice(0,5).forEach(s=>summary.append(el('li','',s)));if(!summary.children.length)summary.append(el('li','','요약 미확인'));root.append(summary);
    root.append(el('p','muted','공식 발표 시점의 고정 자료입니다. 현재 진행 상태는 실시간 검증되지 않았습니다.'));
    const facts=el('dl','detail-facts');function fact(k,v){add(facts,el('dt','',k),el('dd','',v));}
    fact('발표 단계',text(project.status));fact('규모 기준',(project.capacities||[]).map(c=>`${text(c.value)} ${text(c.unit,'')} · ${term(c.metric)} · ${term(c.basis)} · ${term(c.scope)} · ${date(c.event_date)}`).join('\n')||'공개 근거에서 미확인');fact('주요 일정',(project.milestones||[]).map(m=>`${date(m.date)} ${text(m.kind)} (${term(m.basis)}·${term(m.precision)})`).join(' / ')||'미정');fact('판정',`${term(project.classification)} / ${term(project.validation_state)}`);if(project.parent_id)fact('상위 사업',text(find('projects',project.parent_id)?.name));root.append(facts);
    const companies=el('div','detail-source');companies.append(el('strong','','참여 기업 · 역할'));arr('relationships').filter(r=>r.project_id===project.id&&r.directness==='explicit').forEach(r=>{const c=find('companies',r.company_id);if(c)companies.append(button(`${c.name} · ${r.role} ↗`,'button text small',()=>openCompany(c.id)));});root.append(companies);
    const actions=el('div','detail-actions');const ids=changes.filter(c=>!arr('read_states').some(r=>r.id===c.id)).map(c=>c.id);const read=button(ids.length?`변화 ${ids.length}건 확인 완료`:'변화 확인 완료됨','button primary small',async()=>{read.disabled=true;try{await mutate('/api/read',{change_ids:ids},'선택한 변화만 확인 완료로 기록했습니다.');}catch{}finally{read.disabled=false;}});read.disabled=!ids.length;
    add(actions,read,button('근거 보기 ↗','button small',()=>openProjectSources(project)));root.append(actions);
    const sources=el('div','detail-source');sources.append(el('strong','',`검증 근거 ${projectArticles(project).length}개`));projectArticles(project).slice(0,3).forEach(a=>sources.append(link(`${text(a.publisher)} · ${a.title} ↗`,a.url)));root.append(sources);root.append(entityNews('project',project.id,project.name));return root;
  }
  function projectTable(projects){
    if(!projects.length)return empty('표시할 사업이 없습니다','검색이나 범위 필터를 변경해 보세요.');
    const table=el('table');const head=el('tr');['프로젝트 / 지역','발표 단계','참여 기업 · 역할','규모 / 기준','일정 / 기준','공개 근거'].forEach(t=>head.append(el('th','',t)));table.append(add(el('thead'),head));const body=el('tbody');
    projects.forEach(p=>{const tr=el('tr',S.selected===p.id?'row-selected':'');const name=el('td');add(name,button(p.name,'',()=>{openProject(p.id);}),el('small','',`${scopeLabels[p.scope]||p.scope} · ${text(p.location,p.country)} · ${text(p.entity_level)}`));const co=el('td');arr('relationships').filter(r=>r.project_id===p.id&&r.directness==='explicit').forEach(r=>{const c=find('companies',r.company_id);if(c){add(co,button(c.name,'',()=>openCompany(c.id)),el('small','',r.role));}});const cap=el('td');(p.capacities||[]).forEach(c=>add(cap,el('span','',`${text(c.value)} ${text(c.unit,'')} ${term(c.metric)}`),el('small','',`${term(c.basis)} · ${term(c.scope)}`)));if(!cap.children.length)cap.textContent='미확인';const milestones=el('td');(p.milestones||[]).forEach(m=>add(milestones,el('span','',`${date(m.date)} · ${text(m.kind)}`),el('small','',`${term(m.basis)} · ${term(m.precision)}`)));if(!milestones.children.length)milestones.textContent='미정';const source=el('td');projectArticles(p).forEach(a=>source.append(link(`${text(a.publisher)} ↗`,a.url,'source-link')));add(tr,name,add(el('td'),badge(text(p.status),'neutral')),co,cap,milestones,source);body.append(tr);});add(table,body);return add(el('div','table-wrap'),table);
  }
  function renderProjectsArchive(root){
    renderVisualNetwork(root,{mode:'project',id:'projectNetwork'});
    renderBusinessMaps(root);renderDiscoveryLedger(root);
    const projects=oitems('projects'),pending=oitems('pending_groups');
    root.append(section(`사업 관련 기사 취합 · ${nitems('articles').length}개`,'등록 사업과 사업 식별 대기 기사 묶음을 나누어 봅니다. 기간·분류·지역 조건은 전체 기사 취합·종합·표에 동일하게 적용됩니다.',button('전체 기사 근거 보기 ↗','button small',()=>articleCollection(nitems('articles').map(a=>a.id),'사업 분류 · 전체 기사'))));
    const table=el('table','ontology-business-table');table.append(add(el('thead'),add(el('tr'),...['사업 / 식별 대기 묶음','분류 · 상태','관측 기업','취합 기사'].map(v=>el('th','',v)))));const body=el('tbody');
    [...projects.map(p=>({...p,kind:'project'})),...pending.map(p=>({...p,kind:'pending'}))].forEach(p=>{const co=(p.company_ids||[]).map(id=>oitems('companies').find(c=>c.id===id)?.name||find('companies',id)?.name).filter(Boolean);const label=p.kind==='pending'?'사업 식별 대기':p.match_status==='name_match_candidate'?'등록 사업명 후보':p.article_count?'등록 사업 연결':'고정 사례 · 현재 기간 기사 없음';body.append(add(el('tr'),add(el('td'),button(p.name,'button text small',()=>{if(p.kind==='project')focusProject(p);else articleCollection(p.article_ids,p.name);})),add(el('td'),badge(scopeLabels[p.scope]||'분류 미확인','neutral'),el('small','',label)),el('td','',co.join(' · ')||'미확인'),add(el('td'),button(`${p.article_count||0}개 · 전체 근거 ↗`,'button text small',()=>articleCollection(p.article_ids,p.name)))));});table.append(body);root.append(add(el('div','table-wrap'),table));
    if(!projects.length&&!pending.length)root.append(empty('표시할 사업 근거가 없습니다','기간·분류 조건을 변경해 보세요.'));
    newsSummaries(root);newsTable(root);
    const fixed=el('details','historical-projects');add(fixed,el('summary','',`공식 발표 고정 검증 사업 구성표 · ${matchingProjects().length}개`),el('p','metadata-label','수집 기사 수와 별도인 등록 사업입니다. 발표 당시 자료이며 현재 사업 상태 확인과 구분합니다.'),projectTable(matchingProjects()));root.append(fixed);
  }
  function companyRoleNames(){return ontology().role_taxonomy||[{id:'developer',label:'사업자'},{id:'tenant',label:'테넌트'},{id:'contractor',label:'시공사'},{id:'designer',label:'설계사'},{id:'operator',label:'운영사'},{id:'equipment_supplier',label:'장비사'},{id:'financier',label:'PF사·금융주선사'},{id:'unknown',label:'역할 미확인·기타'}];}
  function roleName(id){return companyRoleNames().find(r=>r.id===id)?.label||id;}
  function companyRoleMatches(c){return S.companyRole==='all'||(c.roles?.length?c.roles:['unknown']).includes(S.companyRole);}
  function renderCompanyOntology(root){
    const companies=oitems('companies'),matching=companies.filter(companyRoleMatches);let company=matching.find(c=>c.id===S.companyFocus)||matching[0];
    const panel=el('section','ontology-panel company-ontology');panel.id='companyOntology';panel.setAttribute('aria-label','기업 중심 키워드 온톨로지');
    panel.append(section('기업 관계 지도 · 키워드 온톨로지','기업을 중심으로 기사 키워드 → 등록 사업·식별 대기 → 역할 근거를 연결합니다. 역할은 공개 근거에 명시된 경우만 표시합니다.'));
    const tabs=el('div','company-role-tabs');[['all','전체 기업'],...companyRoleNames().map(r=>[r.id,r.label])].forEach(([id,label])=>{const count=id==='all'?companies.length:companies.filter(c=>(c.roles?.length?c.roles:['unknown']).includes(id)).length;const b=button(`${label} ${count}`,'button small',()=>{S.companyRole=id;S.companyFocus=null;render();});b.dataset.companyRole=id;b.classList.toggle('active',S.companyRole===id);b.setAttribute('aria-pressed',S.companyRole===id?'true':'false');tabs.append(b);});panel.append(tabs);
    panel.append(el('p','metadata-label','역할은 사업별 명시 근거에 따릅니다. 한 기업이 여러 역할·사업에 등장하므로 역할별 기업 수와 기사 수를 더하면 전체와 중복될 수 있습니다.'));
    const selector=el('div','company-selector');matching.forEach(c=>{const b=button(`${c.name} · 기사 ${c.article_count||0}개`,'button small',()=>{S.companyFocus=c.id;render();});b.classList.toggle('active',c.id===company?.id);b.setAttribute('aria-pressed',c.id===company?.id?'true':'false');selector.append(b);});panel.append(selector);
    if(!company){panel.append(empty('이 역할로 확인된 기업이 없습니다','역할 미확인·기타 또는 전체 기업에서 기사 관측 기업을 확인하세요.'));root.append(panel);return;}
    const graph=el('div','company-keyword-graph');graph.setAttribute('aria-label',`${company.name} 키워드와 사업 연결`);
    const keywords=el('div','company-keyword-nodes');keywords.append(el('h3','','기사에서 관측한 키워드'));
    (company.keywords||[]).slice(0,12).forEach(k=>keywords.append(button(`${k.label} · 기사 ${k.article_count||k.article_ids?.length||0}개`,'company-keyword-node',()=>articleCollection(k.article_ids,`${company.name} · ${k.label}`))));if(!(company.keywords||[]).length)keywords.append(el('p','muted','현재 기사에서 분류 가능한 키워드 미확인'));
    const center=el('article','company-center-node');add(center,el('p','eyebrow','COMPANY'),el('h3','',company.name),el('strong','company-center-count',`관련 기사 ${company.article_count||0}개`));const roles=el('div','tag-list');(company.roles?.length?company.roles:['unknown']).forEach(r=>roles.append(badge(roleName(r),r==='unknown'?'warning':'neutral')));center.append(roles);
    const lines=el('ol','company-summary-lines');const provided=company.summary_lines||company.summary_evidence||company.summary||[];(Array.isArray(provided)?provided:[provided]).slice(0,5).forEach(s=>lines.append(el('li','',typeof s==='object'?s.text:s)));if(!lines.children.length){add(lines,el('li','',`${company.article_count||0}개 관련 기사의 기업 이름과 등록 사업 근거를 취합했습니다.`),el('li','',`등록 사업 ${company.verified_project_ids?.length||0}개, 식별 대기 묶음 ${company.pending_group_ids?.length||0}개와 연결됩니다.`),el('li','','이름 관측만으로 사업 참여나 설계·시공·운영 역할을 확정하지 않습니다.'));}center.append(lines);center.append(button('취합 기사 전체 근거 ↗','button primary small',()=>articleCollection(company.article_ids,`${company.name} · 전체 기사`)));
    const connections=el('div','company-business-nodes');connections.append(el('h3','','사업 · 역할 근거'));
    const projectIds=new Set([...(company.verified_project_ids||[]),...(company.candidate_project_ids||[])]);oitems('projects').filter(p=>projectIds.has(p.id)).forEach(p=>connections.append(button(`${p.name} · ${company.verified_project_ids?.includes(p.id)?'등록 근거':'사업명 후보'}`,'company-business-node',()=>{S.ontologySelection={type:'project',id:p.id};navigate('overview');})));
    oitems('pending_groups').filter(p=>(company.pending_group_ids||[]).includes(p.id)).slice(0,6).forEach(p=>connections.append(button(`${p.location||scopeLabels[p.scope]||'지역 미확인'} · 사업 식별 대기 · 기사 ${p.article_count}개`,'company-business-node pending',()=>articleCollection(p.article_ids,p.name))));
    (company.role_evidence||[]).forEach(e=>{const row=el('div','company-role-evidence');add(row,badge(roleName(e.role),'neutral'),el('span','',`${text(find('projects',e.project_id)?.name,e.project_id)} · 원문 역할: ${text(e.raw_role)}`),articleRefs(e.article_ids));connections.append(row);});
    if(!(company.role_evidence||[]).length)connections.append(el('p','metadata-label','명시된 사업 참여 역할 근거가 없어 역할 미확인으로 유지합니다.'));
    add(graph,keywords,center,connections);panel.append(graph,el('p','ontology-legend','키워드·식별 대기 연결 = 제목·공개 설명의 관측 · 역할 연결 = 출처가 명시한 저장 근거 · 기사 수는 기업 간 중복될 수 있습니다.'));root.append(panel);
  }
  function renderCompaniesArchive(root,withGraph=true){
    if(withGraph)renderVisualNetwork(root,{mode:'company',id:'companyNetwork'});
    renderCompanyOntology(root);
    const entities=oitems('companies').filter(companyRoleMatches),list=entities.map(c=>({...find('companies',c.id),...c}));const grid=el('div','company-grid');const start=new Date().getFullYear(),end=start+3;
    root.append(section(`기사 관측 기업 · ${list.length}개 / 관련 기사 ${nitems('articles').length}개`,`선택 기간의 기사에 등장한 기업을 모두 취합합니다. 이름 관측과 검증된 사업 참여를 구분합니다. 공개 일정은 ${start}–${end} 및 장기·미정을 별도로 표시합니다.`,button('전체 기사 근거 보기 ↗','button small',()=>articleCollection(nitems('articles').map(a=>a.id),'기업 분류 · 전체 기사'))));
    list.forEach(c=>{const card=el('article','company-card');add(card,badge(c.classification==='observed_name_only'?'이름 관측 · 역할 미확인':'공개 근거 연결 기업','neutral'),el('h3','',c.name),el('p','',Array.isArray(c.summary)?c.summary.map(x=>typeof x==='object'?x.text:x).join(' '):text(c.summary,'공개 사업 참여 근거를 확인하세요.')));const timeline=el('div','timeline');const ps=arr('projects').filter(p=>(c.project_ids||[]).includes(p.id)||(p.company_ids||[]).includes(c.id));let shown=0;ps.forEach(p=>(p.milestones||[]).forEach(m=>{const year=parseInt(String(m.date||''),10);if(Number.isFinite(year)&&year<start)return;const long=Number.isFinite(year)&&year>end;add(timeline,add(el('div','timeline-item'),el('strong','',`${date(m.date)} ${long?'· 장기 계획':!m.date?'· 미정':''}`),button(p.name,'button text small',()=>{openProject(p.id);}),el('small','',`${text(m.kind)} · ${term(m.basis)} · ${term(p.entity_level)}`)));shown++;}));if(!shown)timeline.append(el('p','muted','공개된 향후 일정 미확인'));add(card,timeline,entityNews('company',c.id,c.name),add(el('div','card-actions'),button('기업 상세 · 사내 링크 ↗','button small',()=>openCompany(c.id)),button('이 기업에 초점','button text small',()=>{S.selectedCompany=c.id;S.newsCompany=c.id;S.newsProject='';S.selected=null;navigate('overview',S.scope);load();})));grid.append(card);});if(!list.length)grid.append(empty('조건에 맞는 기업이 없습니다','사업 범위나 검색어를 변경해 보세요.'));root.append(grid);newsSummaries(root);newsTable(root);
  }
  function sourceCard(article, compact=false){
    const card=el('article',`source-card compact-article${article.is_new?' article-new':''}`);card.dataset.articleId=article.id;
    const saved=arr('bookmarks').find(b=>(b.article_id||b.id)===article.id);
    const main=el('div','compact-article-main'),title=el('div','compact-article-title');
    add(title,article.is_new?badge('NEW','warning'):null,link(article.title,article.url));
    const summary=Array.isArray(article.summary)?article.summary.join(' '):text(article.summary,'공개 요약 없음');
    add(main,title,el('div','compact-article-meta',`${text(article.publisher)} · ${dateTime(article.published_at)} KST`),el('p','compact-article-summary',summary.replace(/\s+/g,' ')));card.append(main);
    const actions=el('div','compact-article-actions'),check=el('input');check.type='checkbox';check.checked=S.selectedArticles.has(article.id);check.setAttribute('aria-label',`${article.title} 내보내기 선택`);check.addEventListener('change',()=>{if(check.checked)S.selectedArticles.add(article.id);else S.selectedArticles.delete(article.id);});
    const read=(article.is_unread??article.is_new)?button('확인','button text small',async()=>{try{await mutate('/api/news/read',{article_ids:[article.id]},'이 기사만 확인 완료로 기록했습니다.');}catch{}}):null;if(read)read.setAttribute('aria-label','새 기사 확인 완료');
    const scrap=button(saved?'스크랩 편집':'스크랩','button text small',async()=>{if(saved){bookmarkForm(article);return;}scrap.disabled=true;try{await mutate('/api/bookmarks',{article_id:article.id},'스크랩에 추가했습니다. SCRAP 메뉴에서 확인하세요.');}catch{}finally{scrap.disabled=false;}});scrap.setAttribute('aria-label',saved?'스크랩 편집':'기사 스크랩 추가');
    add(actions,link('원문 ↗',article.url,'compact-original'),read,scrap,saved?button('해제','button text small',async()=>{try{await mutate(`/api/bookmarks/${encodeURIComponent(article.id)}`,undefined,'스크랩을 해제했습니다.','DELETE');}catch{}}):null,check);card.append(actions);
    if(saved?.note){const note=el('details','compact-saved-note');add(note,el('summary','','내 메모'),el('p','note',saved.note));card.append(note);}
    return card;
  }
  function renderSources(saved){const root=$('#viewContainer');const list=articlesInContext(saved);root.append(section(`${saved?'내 스크랩':'공개 근거 자료'} · ${list.length}개`,saved?'기간·분류 조건과 관계없이 저장한 모든 스크랩 · 편집에서 폴더·태그·직접 메모 관리 · 메모는 외부 내보내기 제외':'최신 발행 순 · 제목 · 매체 · 발행일 · 원문 링크 · 한 줄 요약'));const grid=el('div','source-grid');list.forEach(a=>grid.append(sourceCard(a)));if(!list.length)grid.append(empty(saved?'아직 스크랩이 없습니다':'일치하는 근거가 없습니다',saved?'기사의 스크랩 버튼을 한 번 누르면 바로 저장됩니다.':'검색어 또는 범위를 바꾸거나 공개 자료를 수동 등록하세요.'));root.append(grid);}
  const countryLabels={KR:'대한민국',KOR:'대한민국',US:'미국',USA:'미국',UAE:'아랍에미리트',AE:'아랍에미리트',JP:'일본',JPN:'일본',CN:'중국',CHN:'중국',GB:'영국',UK:'영국',DE:'독일',FR:'프랑스',SG:'싱가포르',AU:'호주',IN:'인도',SA:'사우디아라비아',CA:'캐나다',MY:'말레이시아',ID:'인도네시아',VN:'베트남',TH:'태국',NL:'네덜란드',IE:'아일랜드',ES:'스페인',IT:'이탈리아',TW:'대만'};
  const nitems=key=>Array.isArray(S.data?.news?.[key])?S.data.news[key]:[];
  const countryName=value=>countryLabels[text(value,'').toUpperCase()]||(S.data?.news?.geography?.countries||[]).find(c=>c.id===value)?.name||text(value,'국가 미확인');
  const isKorean=p=>/^kr-/.test(p.scope||'')||['KR','KOR','대한민국','한국','South Korea'].includes(p.country);
  function cityName(p){const explicit=p.city||p.location_city;if(explicit)return text(explicit).replace(/특별자치시|특별시|광역시|시$/g,'');const match=text(p.location,'').match(/(?:^|\s|[,/])(서울|부산|대구|인천|광주|대전|울산|세종|[가-힣]{2,5}시)(?:특별자치시|특별시|광역시)?(?:\s|[,/]|$)/);return match?match[1].replace(/시$/,''):'도시 미확인';}
  function geography(p){const domestic=isKorean(p);const value=domestic?cityName(p):countryName(p.country);return {key:`${domestic?'kr':'global'}:${value}`,value,domestic,label:`${domestic?'국내 · 도시':'해외 · 나라'} / ${value}`};}
  function dateTime(value){if(!value)return '일자 미확인';const d=new Date(value);return Number.isNaN(d.getTime())?text(value):new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d);}
  function accessLabel(value){return ({feed_metadata_only:'공개 제목·설명 · 본문 미확인',metadata_only:'메타데이터 · 본문 미확인',public:'공개 원문',public_metadata_only:'공개 메타데이터',manual_evidence:'직접 확인 근거'})[value]||text(value,'본문 미확인');}
  function newsParams(){return new URLSearchParams({period:S.period,q:S.newsQuery,scope:S.scope,company_id:S.newsCompany||S.selectedCompany||'',project_id:S.newsProject,source_ids:S.sourceIds.join(','),country:S.country,city:S.city,graph_company_id:(S.view==='companies')?S.companyFocus||'':''});}
  function newsRequest(resume){return {period:S.period,q:S.newsQuery,scope:S.scope,company_id:S.newsCompany||S.selectedCompany||'',project_id:S.newsProject,source_ids:S.sourceIds,country:S.country,city:S.city,resume_job_id:resume||null};}
  function sourceRegistry(){const data=S.data?.news_sources;const sources=Array.isArray(data)?data:Array.isArray(data?.sources)?data.sources:[];return sources.map(s=>({...s,id:s.id||s.source_id}));}
  function syncNewsControls(){
    S.query=S.newsQuery;['#search','#newsQuery'].forEach(id=>{const input=$(id);if(document.activeElement!==input)input.value=S.newsQuery;});
    $('#newsPeriod').value=S.period;
    const geo=S.data?.news?.geography||S.data?.news?.geo||{};
    const normalize=(items)=>Array.isArray(items)?items.map(x=>typeof x==='object'?(x.code||x.id||x.country||x.city||x.name||x.value):x):Object.keys(items||{});
    const countries=[...new Set([...arr('projects').filter(p=>!isKorean(p)).map(p=>p.country),...normalize(geo.countries)].filter(v=>v&&!['KR','KOR','대한민국','한국'].includes(v)))];
    const cities=[...new Set([...arr('projects').filter(isKorean).map(cityName),...normalize(geo.domestic_cities||(geo.cities||[]).filter(c=>c.country==='KR'))].filter(v=>v&&v!=='도시 미확인'))];
    function fill(id,values,label,value,convert){const select=$(id);select.replaceChildren();const all=el('option','',label);all.value='';select.append(all);const seen=new Set();values.concat(value?[value]:[]).sort().forEach(v=>{const display=convert(v);if(seen.has(display))return;seen.add(display);const o=el('option','',display);o.value=v;select.append(o);});select.value=value;}
    fill('#newsCountry',countries,'전체 나라',S.country,countryName);fill('#newsCity',cities,'전체 도시',S.city,v=>v);
    const control=window.AtlasCollectionLive.controlState(S.busy,nitems('jobs'),collectionLive?.getState());$('#newsCollect').disabled=control.disabled;$('#newsCollect').textContent=control.label;
    const f=S.data?.news?.filters;$('#newsFilterNote').textContent=f?`${text(f.label,S.period)} · ${f.start?dateTime(f.start):'전체 보관 기간'} ~ ${dateTime(f.end)} KST · 목록·요약·표·내보내기 동일 조건`:'기간·범위·나라·도시는 기사 목록·종합 요약·통합표·내보내기에 함께 적용됩니다.';
  }
  function scheduleNewsPoll(){
    clearTimeout(S.poll);const running=nitems('jobs').some(j=>['running','queued'].includes(j.status));
    S.poll=setTimeout(async()=>{
      if(document.hidden||S.loading){scheduleNewsPoll();return;}
      try{
        const response=await fetch('/api/updates',{cache:'no-store'}),value=await response.json();
        if(!response.ok){if(value.code==='store_integrity_error'){S.integrityError=true;$('#errorBanner').textContent=value.error;$('#errorBanner').hidden=false;$('#connection').textContent='저장 자료 무결성 점검 필요';}else throw Error('갱신 확인 실패');}
        else if((value.snapshot_id!==S.generation||S.integrityError)&&!S.loading){await load();return;}
      }catch{}
      scheduleNewsPoll();
    },running?2500:15000);
  }
  let collectionLive;
  function liveCollection(){return collectionLive||(collectionLive=window.AtlasCollectionLive?.mount($('#collectionLiveStatus'),{onState:()=>syncNewsControls(),onFinish:d=>{(d.jobs||[]).forEach(j=>{const old=nitems('jobs').find(x=>x.id===j.id);if(old)Object.assign(old,{status:j.status,error_code:j.error_code,new_articles:j.new_articles});});syncNewsControls();if(!S.loading)load();}}));}
  async function collectNews(resume){if(S.busy||collectionLive?.isActive())return;let payload=newsRequest(resume);if(resume){const job=nitems('jobs').find(j=>j.id===resume);if(job?.filters){payload={...job.filters,resume_job_id:resume};S.period=payload.period||S.period;S.newsQuery=payload.q||'';S.scope=payload.scope||'all';S.newsCompany=payload.company_id||'';S.newsProject=payload.project_id||'';S.country=payload.country||'';S.city=payload.city||'';S.sourceIds=payload.source_ids||[];$('#newsQuery').value=S.newsQuery;$$('[data-scope]').forEach(n=>{n.classList.toggle('active',n.dataset.scope===S.scope);n.setAttribute('aria-pressed',n.dataset.scope===S.scope?'true':'false');});}}S.busy=true;syncNewsControls();liveCollection()?.start();try{const response=await api('/api/news/search',payload);liveCollection()?.setJob(response.data?.job_id);toast(`기사 수집을 시작했습니다. ${text(response.data?.job_id,'')}`);S.view='news';location.hash='news';await load();}catch(error){liveCollection()?.stop('수집 시작 요청 실패 · '+error.message);toast(error.message,true);}finally{S.busy=false;syncNewsControls();}}
  function openGeoNews(group){const country=group.domestic?'':(Object.keys(countryLabels).find(code=>countryLabels[code]===group.value&&code.length===2)||(S.data?.news?.geography?.countries||[]).find(c=>c.name===group.value)?.id||group.value);navigate('news',S.scope);S.country=country;S.city=group.domestic?group.value:'';S.selectedCompany=null;S.newsCompany='';S.newsProject='';load();}
  function focusNews(kind,id){const geo={country:S.country,city:S.city};$('#modal').close();navigate('news',S.scope);S.newsCompany=kind==='company'?id:'';S.selectedCompany=kind==='company'?id:null;S.newsProject=kind==='project'?id:'';S.country=geo.country;S.city=geo.city;load();}
  function openArticle(id){const article=nitems('articles').find(a=>a.id===id)||find('articles',id);if(!article){toast('현재 조건에 없는 근거입니다. 기간을 넓혀 확인하세요.',true);return;}modal('기사 근거 확인',sourceCard(article));}
  function articleRefs(ids){const refs=el('div','article-refs');(ids||[]).forEach((id,i)=>{const a=nitems('articles').find(x=>x.id===id)||find('articles',id);const b=button(`[${i+1}] ${a?text(a.publisher):'근거 기사'}`,'button text small',()=>openArticle(id));b.title=a?.title||id;refs.append(b);});return refs;}
  function renderNewsPulse(root){
    const articles=nitems('articles'),fresh=articles.filter(a=>a.is_new);const panel=el('section','news-pulse');
    add(panel,add(el('div'),el('p','eyebrow','LIVE ARTICLE INTELLIGENCE'),el('h2','',`선택 기간 기사 ${articles.length}개`),el('p','',`새 기사 ${fresh.length}개 · 해외는 나라별, 국내는 도시별 · 제목·공개 설명 기반`)),button('기사 · 요약 · 통합표 열기 ↗','button primary',()=>navigate('news')));
    const feed=el('div','pulse-feed');articles.slice(0,3).forEach(a=>feed.append(link(`${a.is_new?'NEW · ':''}${text(a.publisher)} · ${a.title} ↗`,a.url,'pulse-item')));if(!articles.length)feed.append(el('p','muted','선택 기간의 기사가 없습니다. 기간 기사 수집으로 공개 출처를 조회하세요.'));panel.append(feed);root.append(panel);
    renderJobStatus(root,true);
  }
  function displayValue(value){if(value===null||value===undefined)return '이전 값 없음';if(Array.isArray(value))return value.map(displayValue).join(' / ');if(typeof value==='object')return Object.entries(value).map(([k,v])=>`${term(k)}: ${displayValue(v)}`).join(' · ');return text(value);}
  function renderHighlights(root,projectId){
    const list=nitems('highlights').filter(h=>(!projectId||h.project_id===projectId)&&(S.includeRead||h.unread!==false)).sort((a,b)=>Number(a.kind==='new_article')-Number(b.kind==='new_article')||text(b.changed_at,'').localeCompare(text(a.changed_at,'')));if(!list.length)return;
    root.append(section('변경 하이라이트', '실제 이전/이후 값과 새 기사 발견을 구분합니다. 원문 근거를 눌러 확인하세요.'));
    const grid=el('div','highlight-grid');list.slice(0,12).forEach(h=>{const fresh=h.kind==='new_article'||h.before==null;const card=el('article',`highlight-card ${fresh?'discovery':'verified-change'}`);add(card,add(el('div','card-meta'),badge(fresh?'새 기사 발견 · 본문 미확인':'사업 사실 변경',fresh?'warning':''),el('small','',dateTime(h.changed_at))),el('h3','',text(h.label||h.field)),h.project_id?el('p','',text(find('projects',h.project_id)?.name,'')):null);
      if(fresh)add(card,link(displayValue(h.after)+' ↗',find('articles',h.article_ids?.[0])?.url,'highlight-article-link'),el('small','muted','신규 근거 발견이며 사업 수치·관계 변경 확정이 아닙니다.'));else add(card,add(el('div','before-after'),add(el('div','before'),el('small','','이전'),el('del','',displayValue(h.before))),el('span','change-arrow','→'),add(el('div','after'),el('small','','변경'),el('mark','',displayValue(h.after)))));
      add(card,articleRefs(h.article_ids));grid.append(card);});root.append(grid);
  }
  function coverageNote(c){const reason=text(c.error_message||c.error||c.reason||c.note,'검색 결과 상한 가능');return ['failed','error'].includes(c.status)?`오류 코드: ${text(c.error_code,'이전 기록에 없음 · 최신 연결 진단 필요')} · ${reason}`:reason;}
  function coverageRows(){const coverage=S.data?.news?.coverage;return Array.isArray(coverage)?coverage:Array.isArray(coverage?.sources)?coverage.sources:Array.isArray(coverage?.rows)?coverage.rows:[];}
  async function collectionDiagnostic(){
    const content=el('div');
    try{
      const response=await api('/api/collection/status',undefined,'GET'),d=response.data||response;
      const labels={worker_missing:'진행 상태만 남음 · 실제 수집 작업 없음',running:'수집 실행 중',failed:'수집 처리 실패',source_errors:'출처 연결 오류',saved:'신규 기사 저장',duplicates_only:'이미 저장된 기사만 발견',no_matching_metadata:'응답은 있으나 기간·출처·주제 조건에 맞는 기사 없음',no_results:'조회 결과 없음'};
      add(content,el('p','callout',d.note),el('p','muted',`실제 작업 ${d.worker_alive?'실행 중':'없음'} · 수집 잠금 ${d.collection_lock_held?'사용 중':'없음'} · HTTPS 프록시 ${d.environment?.https_proxy_configured?'설정':'미설정'} · PAC ${d.environment?.pac_detected?'감지':'미감지'}`));
      (d.jobs||[]).forEach(j=>{content.append(el('p',j.worker_missing||j.status==='failed'?'callout warning':'callout',`${j.id} · ${labels[j.result_code]||j.result_code} · 누적 요청 ${j.request_count}회 / 응답 ${j.returned_items}건 / 신규 ${j.new_articles}건 / 중복 ${j.duplicate_count}건 · 오류 ${j.error_code||'없음'}`));if(j.worker_missing)content.append(button('원래 조건으로 수집 재개','button small',()=>{$('#modal').close();collectNews(j.id);}));});
      content.append(el('pre','note',JSON.stringify(d.coverage_error_counts||{},null,2)));
      content.append(button('진단 JSON 내려받기 · 키/기사/검색어 제외','button',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download='AIDC-ATLAS-collection-diagnostic.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}));
      modal('이 PC의 기사 수집 진단',content);
    }catch(e){toast(`수집 진단 API를 확인하지 못했습니다. 실행 중인 백엔드에 최신 소스 적용 여부를 확인하세요. ${e.message}`,true);}
  }
  function renderJobStatus(root,compact=false){
    const jobs=nitems('jobs').slice().sort((a,b)=>text(b.updated_at||b.created_at,'').localeCompare(text(a.updated_at||a.created_at,'')));const latest=jobs.find(j=>S.period==='3y'&&S.scope==='all'&&j.id===S.data?.settings?.baseline_job_id)||jobs.find(j=>['running','queued'].includes(j.status))||jobs.find(j=>j.id===S.data?.news?.latest_matching_job_id)||jobs[0];if(!latest&&!coverageRows().length)return;
    const panel=el('section',`collection-status${compact?' compact':''}`);panel.setAttribute('aria-label','실시간 기사 수집 상태');panel.append(button('수집 중단 원인·진단 저장','button small',collectionDiagnostic));
    if(latest){const matches=(S.data?.news?.matching_job_ids||[]).includes(latest.id);panel.append(el('small','muted',`${matches?'현재 기사 조건의 수집 작업':'다른 조건의 최근 수집 작업'} · 기간 ${text(latest.filters?.period)} · 검색 ${text(latest.filters?.q,'기본 주제')} · 범위 ${text(scopeLabels[latest.filters?.scope],latest.filters?.scope||'전체')}`));const status=({running:'수집 진행 중',queued:'수집 대기',completed:'조회 작업 종료',partial:'일부 조회 · 남은 범위 있음',failed:'수집 실패',paused:'일시 중지',interrupted:'중단됨'})[latest.status]||text(latest.status);const progress=latest.progress||{};add(panel,add(el('div','collection-head'),el('strong','',status),badge(`작업 ${text(latest.id)}`,'neutral')),el('p','',`최근 실행 ${dateTime(latest.updated_at||latest.finished_at||latest.started_at||latest.created_at)} KST · 신규 ${Number(latest.new_articles??latest.articles_added??latest.stats?.new_articles??0)}개 · 요청 ${Number(latest.requests_made??latest.request_count??progress.requests_completed??0)}회`));
      const completed=Number(latest.completed_windows??progress.completed_windows??latest.stats?.completed_windows??0),total=Number(latest.total_windows??progress.total_windows??0);if(total){const bar=el('progress');bar.max=total;bar.value=completed;bar.setAttribute('aria-label','조회 구간 진행률');add(panel,bar,el('small','',`${completed} / ${total} 조회 구간`));}
      const pending=Array.isArray(latest.pending_windows)?latest.pending_windows.length:Number(latest.pending_count??progress.pending_windows??0);if(pending||latest.failed_windows?.length||latest.truncated||latest.limit_reached)panel.append(el('p','coverage-warning',`범위 미확보 · 남은 조회 구간 ${pending}개. 요청 상한·검색 제공자의 결과 제한이 적용됩니다.`));if(latest.stop_reason)panel.append(el('p','callout',({request_limit:'설정된 요청 상한에 도달했습니다. 남은 구간 수집을 재개할 수 있습니다.',article_limit:'이번 기사 저장 상한에 도달했습니다.',user_cancelled:'사용자가 수집을 중단했습니다.',network_blocked:'연속 연결 실패로 일시 중지했습니다. 회사 DNS·프록시·방화벽을 진단하고 재개하세요.',source_errors:'출처 연결 오류가 있습니다. 네트워크 진단 후 실패 구간을 재개하세요.',worker_error:'수집 처리 오류입니다. 진단을 저장하고 원인을 확인한 후 재개하세요.',queue_exhausted:'계획한 조회 구간을 마쳤습니다. 제공사의 검색 결과 제한으로 전체 기사 확보를 보장하지 않습니다.'})[latest.stop_reason]||latest.stop_reason));if(latest.message)panel.append(el('p','coverage-warning',text(latest.message)));if(latest.error_code)panel.append(el('p','coverage-warning',`오류 코드: ${latest.error_code}`));if(latest.error||latest.last_error)panel.append(el('p','coverage-warning',text(latest.error||latest.last_error)));
      if(['running','queued'].includes(latest.status))panel.append(button('현재 수집 중단','button small',async()=>{try{await mutate('/api/news/cancel',{job_id:latest.id},'현재 요청 후 수집을 중단합니다. 남은 범위는 저장됩니다.');}catch{}}));if(!['running','queued'].includes(latest.status)&&(latest.can_resume||pending||['partial','paused','interrupted','failed','cancelled'].includes(latest.status)))panel.append(button('남은 범위 수집 계속','button small',()=>collectNews(latest.id)));
    }
    panel.append(el('small','muted','작업 종료는 해당 기간의 모든 기사가 확보되었다는 뜻이 아닙니다. 선정 출처·성공·실패·미연결·미확보 범위를 구분합니다.'));
    if(!compact){const coverage=coverageRows().filter(c=>!latest||c.job_id===latest.id);const stats=S.data?.news?.coverage||{};panel.append(el('p','',`선정 출처 ${sourceRegistry().length||stats.registry_total||101}개 · 이번 조회 연결성공 ${Number(stats.connected_sources??stats.successful_sources??new Set(coverage.filter(x=>['ok','success','completed','queried','supplemental_latest_feed','provider_cap_split','provider_cap_unresolved'].includes(x.status)).map(x=>x.source_id)).size)}개 · 실패 응답 ${Number(stats.failed_sources??new Set(coverage.filter(x=>['failed','error'].includes(x.status)).map(x=>x.source_id)).size)}개 · 미조회/미연결 ${Math.max(0,sourceRegistry().length-new Set(coverage.map(x=>x.source_id)).size)}개`));const details=el('details');details.append(el('summary','',`출처별 범위와 연결 결과 ${coverage.length}건`));const table=el('table');table.className='coverage-table';table.append(add(el('thead'),add(el('tr'),...['출처','조회 상태','기간 / 조회 구간','기사 / 미확보 사유'].map(v=>el('th','',v)))));const body=el('tbody');coverage.forEach(c=>{const reg=sourceRegistry().find(s=>s.id===(c.source_id||c.id));body.append(add(el('tr'),el('td','',text(c.publisher||c.source_name||reg?.name||reg?.publisher||c.source_id||c.id)),el('td','',({queried:'공개 검색 응답',supplemental_latest_feed:'최신 RSS 응답',provider_cap_split:'제공자 상한 · 기간 분할',provider_cap_unresolved:'제공자 상한 · 미확보',failed:'연결 실패'})[c.status]||text(c.status)),el('td','',`${date(c.start||c.period_start)} ~ ${date(c.end||c.period_end)}`),el('td','',`${Number(c.article_count??c.articles_found??c.accepted??0)}개 · ${coverageNote(c)}`)));});table.append(body);details.append(add(el('div','table-wrap'),table));panel.append(details);}
    root.append(panel);
  }
  function newsSummaries(root){const summaries=nitems('summary');root.append(section('기사 종합 요약','같은 조건의 제목·공개 설명을 주제별로 종합합니다. 각 항목 아래 근거 기사를 확인하세요.'));const list=el('div','digest-grid');summaries.forEach(s=>{const card=el('article','digest-card');add(card,badge((s.article_ids||[]).length>1?'여러 기사 종합':'단일 기사 정리','neutral'),el('p','',text(s.text)),articleRefs(s.article_ids),el('small','metadata-label','메타데이터 종합 · 본문 미확인 · 사내 AI 미연결'));list.append(card);});if(!summaries.length)list.append(empty('종합할 기사가 없습니다','기간 기사 수집 또는 검색 조건 변경 후 확인하세요.'));root.append(list);}
  function newsTable(root){root.append(section('기사 통합 정리표','현재 기사 목록 페이지와 동일한 조건입니다. CSV는 조건에 맞는 모든 기사를 포함합니다.',button('현재 조건 CSV ↓','button small',()=>downloadNews('news-csv'))));const table=el('table','news-table');table.append(add(el('thead'),add(el('tr'),...['발행 KST / 매체','기사 / 원문','기업 후보','사업 후보 / 분류','나라 / 국내 도시','통합 정리 / 변경'].map(v=>el('th','',v)))));const body=el('tbody');nitems('rows').slice((S.newsPage-1)*24,S.newsPage*24).forEach(row=>{const tr=el('tr',/신규/.test(row.change_label||'')?'news-updated-row':'');add(tr,add(el('td'),el('strong','',text(row.publisher)),el('small','',dateTime(row.published_at))),add(el('td'),link(row.title,row.url),el('small','',accessLabel(row.access_status))),el('td','',(row.company_names||[]).join(' · ')||'명시 매칭 없음'),add(el('td'),el('span','',(row.project_names||[]).join(' · ')||'사업 미확정'),el('small','',(row.categories||[]).map(term).join(' · '))),el('td','',`${(Array.isArray(row.country)?row.country.map(countryName).join(' · '):countryName(row.country))}${row.city?.length?' / '+(Array.isArray(row.city)?row.city.join(' · '):row.city):''}`),add(el('td'),el('p','',text(row.summary,'공개 요약 없음')),row.change_label?badge(row.change_label,'warning'):null));body.append(tr);});table.append(body);if(!body.children.length)root.append(empty('표에 표시할 기사가 없습니다','기사 목록과 동일한 조건을 사용합니다.'));else root.append(add(el('div','table-wrap'),table));}
  function downloadNews(kind){const params=newsParams();params.set('kind',kind);const a=el('a');a.href=`/api/export?${params}`;a.download='';document.body.append(a);a.click();a.remove();toast('현재 기사 조건으로 내보내기를 요청했습니다.');}
  function entityNews(kind,id,name){const panel=el('section','entity-news');const updates=nitems(kind==='company'?'company_updates':'project_updates');const update=oitems(kind==='company'?'companies':'projects').find(x=>x.id===id)||updates.find(x=>x.id===id);const ids=new Set(update?.article_ids||[]);const articles=nitems('articles').filter(a=>ids.has(a.id)||(kind==='company'?(a.company_ids||[]):[...(a.project_ids||[]),...(a.candidate_project_ids||[])]).includes(id));add(panel,el('h3','',`기사 취합 · ${articles.length}개`),el('p','metadata-label','현재 선택 기간의 전체 연결 기사 · 이름 매칭 후보와 검증된 사업 참여는 별도'));if(update?.summary)panel.append(el('p','',Array.isArray(update.summary)?update.summary.map(x=>typeof x==='object'?x.text:x).join(' '):text(update.summary)));articles.slice(0,3).forEach(a=>add(panel,button(`${a.is_new?'NEW · ':''}${text(a.publisher)} · ${a.title}`,'entity-article',()=>openArticle(a.id)),el('small','muted',`${dateTime(a.published_at)} KST`)));if(!articles.length)panel.append(el('p','muted','현재 조건에 일치하는 최신 기사가 없습니다.'));add(panel,button(`${articles.length}개 취합 근거 모두 보기 ↗`,'button small',()=>articleCollection(articles.map(a=>a.id),`${name} · 전체 기사`)),button(`${name} 기사 · 종합표 ↗`,'button text small',()=>focusNews(kind,id)));return panel;}
  function renderNews(root){
    renderAIBriefing(root);
    if(!S.data.news){root.append(empty('기사 API를 연결하고 있습니다','서버 업데이트 후 새로고침하세요. 기존 검증 근거는 근거 메뉴에서 확인할 수 있습니다.'));return;}
    if(S.newsCompany||S.newsProject){const name=S.newsCompany?find('companies',S.newsCompany)?.name:find('projects',S.newsProject)?.name;root.append(add(el('div','callout'),el('strong','',`기사 초점 · ${text(name)}`),button('기업·사업 조건 해제','button small',()=>{S.newsCompany='';S.newsProject='';load();})));}
    const counts=S.data.news.counts||{};const stats=el('div','news-metrics');[['조회 기사',nitems('articles').length],['새 기사',nitems('articles').filter(a=>a.is_new).length],['매체',new Set(nitems('articles').map(a=>a.publisher)).size],['종합 항목',nitems('summary').length]].forEach(([label,value])=>stats.append(add(el('div'),el('strong','',Number(value).toLocaleString()),el('span','',label))));root.append(stats);
    const support=el('details','panel article-support');support.append(el('summary','','수집 현황 · 출처 · 지역 · 변화 · 기존 종합 보기'));renderJobStatus(support);renderNewsSourceFilter(support);renderGeoIndex(support);renderHighlights(support);newsSummaries(support);
    root.append(section(`최신 기사 · ${nitems('articles').length}개`,'기사 선택과 원문 열기로 읽음이 바뀌지 않습니다. 새 기사 확인 완료 버튼으로 직접 표시합니다.',button('기사 종합 HTML ↓','button small',()=>downloadNews('news-report'))));const feed=el('div','source-grid news-feed');const articleList=nitems('articles'),pageCount=Math.max(1,Math.ceil(articleList.length/24));S.newsPage=Math.min(S.newsPage,pageCount);const pagination=add(el('div','news-pagination'),el('span','',`${S.newsPage} / ${pageCount}페이지 · 전체 ${articleList.length}개 / 페이지당 24개`));const previous=button('← 이전','button small',()=>{S.newsPage--;render();});previous.disabled=S.newsPage<=1;const next=button('다음 →','button small',()=>{S.newsPage++;render();});next.disabled=S.newsPage>=pageCount;add(pagination,previous,next);root.append(pagination);articleList.slice((S.newsPage-1)*24,S.newsPage*24).forEach(a=>feed.append(sourceCard(a)));if(!feed.children.length)feed.append(empty('현재 조건의 기사가 없습니다','기간을 넓히거나 기간 기사 수집으로 공개 출처를 조회하세요.'));root.append(feed);newsTable(support);root.append(support);
    const limitations=Array.isArray(S.data.news.limitations)?S.data.news.limitations:[];if(limitations.length){const details=el('details','panel news-limitations');details.append(el('summary','','수집·해석 범위와 한계'));limitations.forEach(v=>details.append(el('p','',typeof v==='object'?text(v.message||v.text||JSON.stringify(v)):v)));root.append(details);}
  }
  function synthesisCsv(rows,filename){
    const quote=value=>{let s=value===null||value===undefined?'':String(value);if(/^[\s]*[=+@-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
    const blob=new Blob(['\uFEFF'+rows.map(row=>row.map(quote).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function renderSynthesis(root){
    renderAIBriefing(root);
    if(!window.AtlasAnalysis){root.append(empty('종합 분석을 준비하고 있습니다','페이지를 새로고침해 주세요. 기존 기사·통합표는 기사 메뉴에 유지됩니다.'));return;}
    S.pivot||={row:'candidate',column:'stage',metric:'articles',page:1,columnPage:1,query:''};const options=S.pivot;
    const key=`${S.generation}:${newsParams()}`;if(S.analysisKey!==key){S.analysisModel=window.AtlasAnalysis.build(S.data);S.analysisKey=key;}
    const model=S.analysisModel,result=window.AtlasAnalysis.pivot(model,options),metrics=[['articles','고유 기사 수'],['companies','고유 기업 수'],['projects','등록 사업 수'],['unread','미확인 새 기사 수'],['latest','최신 발행일']];
    const panel=el('section','synthesis-panel');panel.append(section('종합 · 기사에서 사업 구조로','행·열·집계값을 바꾸고 숫자를 눌러 근거 기사까지 확인합니다. 명시 역할과 기사 이름 관측을 구분합니다.'));
    const presets=el('div','pivot-presets');[['사업 진행 관측','candidate','stage','articles'],['사업 참여 구조','project','role','companies'],['기업 역할','company','role','articles'],['지역 동향','location','scope','articles'],['월별 변화','month','scope','articles'],['기술·설비 주제','category','scope','articles']].forEach(([label,row,column,metric])=>presets.append(button(label,'button small',()=>{Object.assign(options,{row,column,metric,page:1,columnPage:1});render();})));panel.append(presets);
    const controls=el('div','pivot-controls');[['row','행',model.dimensions.map(d=>[d.id,d.label])],['column','열',model.dimensions.map(d=>[d.id,d.label])],['metric','집계',metrics]].forEach(([field,label,values])=>{const select=el('select');select.setAttribute('aria-label',`종합 ${label}`);values.forEach(([value,name])=>select.append(Object.assign(el('option','',name),{value})));select.value=options[field];select.addEventListener('change',()=>{options[field]=select.value;options.page=1;options.columnPage=1;render();});controls.append(add(el('label'),el('span','',label),select));});
    controls.append(button('행·열 바꾸기','button small pivot-axis-swap',()=>{[options.row,options.column]=[options.column,options.row];options.page=1;options.columnPage=1;render();}));const query=el('input');query.type='search';query.placeholder='기업·사업·지역·키워드 찾기';query.value=options.query;query.setAttribute('aria-label','종합 항목 검색');const search=button('항목 찾기','button small',()=>{options.query=query.value;options.page=1;options.columnPage=1;render();});query.addEventListener('keydown',e=>{if(e.key==='Enter')search.click();});add(controls,query,search,button('피벗 전체 CSV ↓','button small',()=>{const head=[model.dimensions.find(d=>d.id===options.row)?.label,...result.columns.map(c=>c.label),'고유 합계'];synthesisCsv([['기준 snapshot',S.generation],['집계',metrics.find(m=>m[0]===options.metric)[1]],['기간·조건',newsParams().toString()],head,...result.rows.map(r=>[r.label,...r.cells.map(c=>c.value),r.total.value]),['고유 합계',...result.columns.map(c=>c.total.value),result.total.value]],'AIDC-ATLAS-pivot.csv');}));panel.append(controls);
    const summary=el('div','pivot-metrics');[['선택 기사',nitems('articles').length],['관측 기업',oitems('companies').length],['등록 사업',oitems('projects').length],['기사 사업명 후보',discoveredProjects().length]].forEach(([label,value])=>summary.append(add(el('span'),el('strong','',Number(value).toLocaleString()),document.createTextNode(label))));panel.append(summary);
    panel.append(el('p','pivot-note','행·열·전체 합계는 각 범위에서 중복을 제거한 값입니다. 한 기사가 여러 기업·지역·주제에 연결되므로 셀의 합과 전체 합이 다를 수 있습니다. 사업 수는 등록 사업만 집계하며 후보 묶음·MW·투자액을 합산하지 않습니다. 기사 진행 표현은 보도 당시의 신호이며 현재 상태 확정이 아닙니다. 후보·진행 축은 독립 관측만 집계하고, 명칭 없는 기사만 후보 미확인 행에 둡니다. 기업·등록 사업과의 결합은 확정하지 않습니다.'));
    const page=Math.max(1,Math.min(options.page,Math.ceil(result.rows.length/24)||1)),columnPage=Math.max(1,Math.min(options.columnPage,Math.ceil(result.columns.length/10)||1));options.page=page;options.columnPage=columnPage;const columns=result.columns.slice((columnPage-1)*10,columnPage*10);
    const scroll=el('div','pivot-scroll'),table=el('table','pivot-table'),head=el('thead'),header=el('tr');header.append(el('th','',`${model.dimensions.find(d=>d.id===options.row)?.label} / ${model.dimensions.find(d=>d.id===options.column)?.label}`));columns.forEach(c=>header.append(el('th','',c.label)));header.append(el('th','','고유 합계'));head.append(header);table.append(head);
    const cell=value=>{const td=el('td');if(value.value===0||value.value===null){td.append(el('span','pivot-cell-empty','—'));return td;}const label=options.metric==='latest'?date(value.value):Number(value.value).toLocaleString();td.append(button(label,'button text',()=>articleCollection(value.article_ids,`종합 · ${metrics.find(m=>m[0]===options.metric)[1]} 근거`)));return td;};
    const body=el('tbody');result.rows.slice((page-1)*24,page*24).forEach(r=>{const tr=el('tr');tr.append(el('th','',r.label));columns.forEach(c=>tr.append(cell(r.cells.find(v=>v.column_id===c.id))));tr.append(cell(r.total));body.append(tr);});table.append(body);const foot=el('tfoot'),total=el('tr');total.append(el('th','','고유 합계'));columns.forEach(c=>total.append(cell(c.total)));total.append(cell(result.total));foot.append(total);table.append(foot);scroll.append(table);panel.append(scroll);
    const pager=add(el('div','news-pagination'),el('span','',`행 ${page}/${Math.ceil(result.rows.length/24)||1} · 열 ${columnPage}/${Math.ceil(result.columns.length/10)||1} · 전체 ${result.rows.length}행 × ${result.columns.length}열`));[['행 이전','page',-1,page<=1],['행 다음','page',1,page*24>=result.rows.length],['열 이전','columnPage',-1,columnPage<=1],['열 다음','columnPage',1,columnPage*10>=result.columns.length]].forEach(([label,key,delta,disabled])=>{const b=button(label,'button small',()=>{options[key]+=delta;render();});b.disabled=disabled;pager.append(b);});panel.append(pager);root.append(panel);
    renderDiscoveryLedger(root);
    const detail=el('details','panel pivot-detail');detail.append(el('summary','','관계 정보 원장 · 근거별 기업/역할/사업/지역/주제'));
    const headers=['발행일','기사 제목','기업','역할','등록 사업','기사 사업명 후보','기사 진행 표현','지역','주제','근거 구분','출처','링크'];const articleIndex=new Map(nitems('articles').map(a=>[a.id,a]));const rows=model.records.map(r=>{const a=articleIndex.get(r.article_id)||{},label=(key,id)=>model.labels[key]?.[id||'unknown']||'미확인';return [date(r.published_at),a.title,label('company',r.company_id),label('role',r.role),label('project',r.project_id),label('candidate',r.candidate_id),(r.stage||[]).map(v=>label('stage',v)).join(' · '),(r.location||[]).map(v=>label('location',v)).join(' · '),(r.category||[]).map(v=>label('category',v)).join(' · '),r.basis,a.publisher,a.url];});
    detail.append(el('p','pivot-note',`같은 기사의 서로 다른 역할은 별도 원장 행입니다. ${rows.length}행 전체를 CSV로 받거나 아래에서 페이지별로 볼 수 있습니다. 역할 미확인과 사업 미확인을 그대로 남깁니다.`),button('정보 원장 전체 CSV ↓','button small',()=>synthesisCsv([headers,...rows],'AIDC-ATLAS-evidence-ledger.csv')));
    const detailPage=Math.max(1,Math.min(S.ledgerPage||1,Math.ceil(rows.length/24)||1));S.ledgerPage=detailPage;const detailScroll=el('div','pivot-scroll'),ledger=el('table','synthesis-evidence-table'),thead=el('tr');headers.slice(0,-1).forEach(h=>thead.append(el('th','',h)));ledger.append(thead);rows.slice((detailPage-1)*24,detailPage*24).forEach(row=>{const tr=el('tr');row.slice(0,-1).forEach((v,i)=>tr.append(i===1?add(el('td'),link(v,row.at(-1))):el('td','',v)));ledger.append(tr);});detailScroll.append(ledger);detail.append(detailScroll);const dp=add(el('div','news-pagination'),el('span','',`${detailPage}/${Math.ceil(rows.length/24)||1} · ${rows.length}행`));[['이전',-1,detailPage<=1],['다음',1,detailPage*24>=rows.length]].forEach(([label,delta,disabled])=>{const b=button(label,'button small',()=>{S.ledgerPage+=delta;S.ledgerOpen=true;render();});b.disabled=disabled;dp.append(b);});detail.open=Boolean(S.ledgerOpen);detail.addEventListener('toggle',()=>{S.ledgerOpen=detail.open;});detail.append(dp);root.append(detail);
    mountStrategy(root);
  }
  function mountStrategy(root){
    if(!window.AtlasStrategy)return;
    const host=el('section','panel');root.append(host);
    const getBoard=async id=>{const r=await api('/api/strategy?'+newsParams()+'&board_id='+encodeURIComponent(id),undefined,'GET');return r.data||r;};
    window.AtlasStrategy.mount(host,{workspace:S.data.strategy,articles:nitems('articles'),connection:S.data?.ai?.connection||{},
      loadBoard:getBoard,
      saveBoard:async payload=>{await api('/api/strategy/save',payload);return getBoard(payload.id);},
      preview:async payload=>{const r=await api('/api/strategy/preview',payload);return r.data||r;},
      analyse:async payload=>{const r=await api('/api/strategy/analyse',payload),d=r.data||r;if(!['completed','cached'].includes(d.status))throw Error(d.error?.message||'전략 분석 실패');return getBoard(payload.board_id);},
      exportBoard:id=>{const a=el('a');a.href='/api/strategy/report?'+newsParams()+'&board_id='+encodeURIComponent(id);a.target='_blank';a.rel='noopener';a.download='AIDC-ATLAS-Strategy-A3.html';document.body.append(a);a.click();a.remove();},
      openArticles:ids=>{const c=el('div');c.append(articleRefs(ids));modal('전략표 근거 기사',c);}
    });
  }
  function renderNewsSourceFilter(root){const sources=sourceRegistry();if(!sources.length)return;const details=el('details','source-filter panel');details.append(el('summary','',`선정 출처 ${sources.length}개 · ${S.sourceIds.length?S.sourceIds.length+'개 선택':'수집은 기본 주요출처 / 저장 조회는 전체'} · 매체 필터`));details.append(el('p','metadata-label','작업 지시서의 출처 레지스트리 기준입니다. 등록과 실제 연결 성공은 별도입니다.'));const grid=el('div','source-checks');sources.forEach(source=>{const input=el('input');input.type='checkbox';input.value=source.id;input.checked=S.sourceIds.includes(source.id);input.addEventListener('change',()=>{S.sourceIds=input.checked?[...S.sourceIds,source.id]:S.sourceIds.filter(id=>id!==source.id);});grid.append(add(el('label'),input,document.createTextNode(`${text(source.name||source.publisher||source.id)} · ${text(source.connector||source.status||source.access_mode,'조회 결과 확인')}`)));});add(details,grid,button('선택 매체 적용','button small',()=>load()),button('101개 출처 전체 선택','button small',()=>{S.sourceIds=sources.map(s=>s.id);load();}),button('매체 선택 해제','button text small',()=>{S.sourceIds=[];load();}));root.append(details);}
  function renderGeoIndex(root){const geo=S.data?.news?.geography||{};const panel=el('section','panel');add(panel,el('h2','','지역별 기사 탐색'),el('p','metadata-label','해외는 나라, 국내는 도시로 묶습니다. 기사 메타데이터에 명시된 지역이며 사업 입지 확정과 구분합니다.'));const countries=el('div','geography-index'),cities=el('div','geography-index');(geo.countries||[]).filter(c=>!['KR','KOR','대한민국'].includes(c.id||c.code||c.name)).forEach(c=>{const value=c.id||c.code||c.name;countries.append(button(`${countryName(value)} · 기사 ${Number(c.article_count||0)}개`,'button small',()=>openGeoNews({domestic:false,value})));});(geo.domestic_cities||geo.cities||[]).filter(c=>!c.country||c.country==='KR').forEach(c=>{const value=c.id||c.name;cities.append(button(`${value} · 기사 ${Number(c.article_count||0)}개`,'button small',()=>openGeoNews({domestic:true,value})));});add(panel,el('strong','metadata-label','해외 · 나라'),countries,el('strong','metadata-label','국내 · 도시'),cities);if(!countries.children.length&&!cities.children.length)panel.append(el('p','muted','현재 조건에서 명시된 지역이 없습니다.'));root.append(panel);}
  function renderNotificationHistory(root){const list=arr('notifications').slice().sort((a,b)=>text(b.created_at,'').localeCompare(text(a.created_at,'')));root.append(section(`로컬 알림 · ${list.filter(n=>!n.read_at).length}건 미확인`,'알림 확인과 사업 변화 확인은 별도입니다.',button('알림 모두 확인','button small',async()=>{try{await mutate('/api/notifications/read',{ids:list.filter(n=>!n.read_at).map(n=>n.id)},'알림을 확인했습니다.');}catch{}})));if(!list.length)root.append(empty('새 알림이 없습니다','의미 있는 변화가 저장되면 이곳에 표시됩니다.'));list.forEach(n=>{const div=el('article',`notification${n.read_at?' read':''}`);add(div,el('span','notification-dot'),add(el('div'),el('h3','',n.title),el('p','',`${date(n.created_at)} · ${text(n.severity)} · ${n.read_at?'확인 완료':'미확인'}`)),button('사업 보기 ↗','button small',()=>{openProject(n.project_id);}),!n.read_at?button('알림 확인','button small',async()=>{try{await mutate('/api/notifications/read',{ids:[n.id]},'알림을 확인했습니다.');}catch{}}):null);root.append(div);});}
  function modal(title,content){$('#modalTitle').textContent=title;$('#modalContent').replaceChildren(content);if(!$('#modal').open)$('#modal').showModal();}
  function field(form,label,name,value='',type='text',full=false,help=''){const wrap=el('label',`field${full?' full':''}`);const input=el(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;input.name=name;input.value=value??'';add(wrap,el('span','',label),input,help?el('small','',help):null);form.append(wrap);return input;}
  function formShell(title,build,onSubmit,options={}){const form=el('form');const grid=el('div','form-grid');form.append(grid);build(grid);const error=el('div','form-error');error.setAttribute('role','alert');const submit=el('button','button primary','저장');submit.type='submit';const progress=options.connection&&window.AtlasConnectionStatus?window.AtlasConnectionStatus.mount(form,{check:async()=>{const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),6000);try{const r=await fetch('/api/ai/status',{cache:'no-store',signal:controller.signal});if(!r.ok)throw Error('상태 조회 실패');const d=await r.json();return d.data||d;}finally{clearTimeout(timeout);}}}):null;add(form,error,add(el('div','form-actions'),button('취소','button',()=>$('#modal').close()),submit));form.addEventListener('submit',async e=>{e.preventDefault();error.textContent='';if(submit.disabled)return;submit.disabled=true;submit.textContent=options.connection?'연결·저장 중…':'저장';progress?.start();try{await onSubmit(new FormData(form),progress);if($('#modalContent').contains(form))$('#modal').close();}catch(err){error.textContent=err.message;}finally{progress?.stop();submit.disabled=false;submit.textContent='저장';}});modal(title,form);return form;}
  function bookmarkForm(article){const current=arr('bookmarks').find(b=>(b.article_id||b.id)===article.id);formShell('스크랩 정리',grid=>{field(grid,'자료','title',article.title,'text',true).readOnly=true;field(grid,'폴더','folder',current?.folder||'');field(grid,'태그 · 쉼표로 구분','tags',(current?.tags||[]).join(', '));field(grid,'직접 메모 · 로컬 전용','note',current?.note||'','textarea',true,'키·인증정보를 입력하지 마세요. 메모는 외부 AI나 보고서로 전송하지 않습니다.');},async f=>{await mutate('/api/bookmarks',{article_id:article.id,folder:f.get('folder'),tags:String(f.get('tags')).split(',').map(t=>t.trim()).filter(Boolean),note:f.get('note')},'스크랩을 JSON 원본에 저장했습니다.');});}
  function openProjectSources(project){const content=el('div');content.append(el('p','callout',`${project.name} · 원문은 선택한 공개 웹사이트에서 열립니다. 선택만으로 변화 확인 상태를 바꾸지 않습니다.`));projectArticles(project).forEach(a=>content.append(sourceCard(a,true)));modal('사업의 공개 근거',content);}
  function openCompany(id){const c=find('companies',id);if(!c)return;const content=el('div');add(content,badge(text(c.country),'neutral'),el('p','',Array.isArray(c.summary)?c.summary.join(' '):text(c.summary,'기업 요약 미확인')),button('이 기업의 사업에 초점 맞추기','button primary',()=>{$('#modal').close();S.companyFocus=id;S.selectedCompany=null;S.newsCompany='';S.newsProject='';S.selected=null;navigate('companies',S.scope);load();}),section('사내 자료 링크','링크·메타데이터·직접 메모만 저장합니다. 원문 자동 접근과 AI 전송은 없습니다.',button('＋ 링크 등록','button small',()=>internalLinkForm(c))));const links=arr('internal_links').filter(l=>l.company_id===id);if(!links.length)content.append(el('p','muted','등록한 사내 링크가 없습니다.'));links.forEach(l=>{const div=el('div','panel');add(div,link(`${l.title} ↗`,l.url),el('p','meta',`${text(l.document_type)} · ${date(l.authored_date)} · ${text(l.visibility)}`));if(l.user_note)div.append(el('p','note',l.user_note));content.append(div);});content.prepend(entityNews('company',id,c.name));modal(c.name,content);}
  function internalLinkForm(company){formShell(`${company.name} · 사내 자료 링크`,grid=>{field(grid,'자료 제목','title','','text',true).required=true;field(grid,'사내 URL','url','','url',true,'이 URL을 서버가 자동으로 열거나 수집하지 않습니다.').required=true;field(grid,'자료 유형','document_type','');field(grid,'작성일','authored_date','','date');field(grid,'직접 메모','user_note','','textarea',true);},async f=>{if(!safeURL(f.get('url')))throw new Error('http 또는 https URL을 입력하세요.');await mutate('/api/internal-links',{company_id:company.id,project_ids:company.project_ids||[],title:f.get('title'),url:f.get('url'),document_type:f.get('document_type'),authored_date:f.get('authored_date'),user_note:f.get('user_note'),visibility:'local_private'},'사내 링크 메타데이터만 저장했습니다.');});}
  function importForm(){formShell('공개 자료 수동 등록',grid=>{add(grid,el('p','callout field full','공개 자료의 제목과 URL, 확인한 근거를 직접 입력하세요. URL 자동 수집·AI 추출 없이 수동 자료로 저장합니다.'));field(grid,'공개 자료 제목','title','','text',true).required=true;field(grid,'공개 원문 URL','url','','url',true).required=true;field(grid,'발행 기관','publisher','').required=true;field(grid,'발행일','published_at','','date');const wrap=el('label','field full');const select=el('select');select.name='project_id';const empty=el('option','','연결 사업 없음 · 메타데이터만 저장');empty.value='';select.append(empty);arr('projects').forEach(p=>{const o=el('option','',p.name);o.value=p.id;select.append(o);});add(wrap,el('span','','연결할 기존 사업'),select);grid.append(wrap);field(grid,'직접 요약','summary','','textarea',true);field(grid,'직접 확인한 근거 발췌','evidence_excerpt','','textarea',true);},async f=>{if(!safeURL(f.get('url')))throw new Error('공개 http 또는 https URL을 입력하세요.');await mutate('/api/import',Object.fromEntries([...f.entries()].map(([k,v])=>[k,k==='project_id'&&!v?null:v])),'수동 메타데이터를 저장했습니다. AI 추출은 실행하지 않았습니다.');});}
  function exports(){const content=el('div');const projects=matchingProjects();add(content,el('p','callout',`현재 조건의 사업 ${projects.length}개 · 선택 근거 ${S.selectedArticles.size}개. 근거를 선택하지 않으면 현재 범위의 자료를 사용합니다. 사내 링크·직접 메모·비밀정보는 공개 내보내기에서 제외합니다.`));const options=el('div','export-options');[['news-report','기사 종합 보고서','현재 기사 조건의 근거·종합·통합표 HTML','▧'],['news-csv','기사 통합표 CSV','현재 기사 조건의 매체·기사·기업·사업 후보 표','▦'],['report','사업 분석 보고서','근거 URL과 기준을 포함한 독립 HTML','▤'],['newsletter','선택 뉴스레터','선택한 근거와 변화의 HTML 브리핑','▧'],['csv','사업 구성표 CSV','사업·기준·시점 비교를 위한 파생 표','▦'],['charter','제품 목적 JSON','공유 가능한 제품 목적과 구성 정보','{}']].forEach(([kind,title,desc,icon])=>{const b=button('','export-option',()=>{if(kind.startsWith('news-')){downloadNews(kind);return;}const params=new URLSearchParams({kind,project_ids:projects.map(p=>p.id).join(','),article_ids:[...S.selectedArticles].join(',')});const a=el('a');a.href=`/api/export?${params}`;a.download='';document.body.append(a);a.click();a.remove();toast('내보내기 파일을 요청했습니다. 브라우저 다운로드를 확인하세요.');});add(b,el('span','',icon),add(el('span'),el('strong','',title),el('small','',desc)),el('span','','↓'));options.append(b);});content.append(options);modal('작업 공간 내보내기',content);}
  async function restoreDialog(){
    const content=el('div');content.append(el('p','callout warning','선택한 백업의 JSON으로 현재 업무데이터 전체를 교체합니다. 백업 이후에 저장한 스크랩·메모·읽음 상태·설정도 교체됩니다. 복구할 파일을 확인한 후 실행하세요.'));modal('로컬 JSON 백업 복구',content);
    const status=el('p','muted','복구 가능한 로컬 백업을 확인하고 있습니다.');content.append(status);
    try{const response=await api('/api/backups',undefined,'GET');const files=Array.isArray(response.data)?response.data:response.data?.backups||[];status.remove();if(!files.length){content.append(empty('복구할 백업이 없습니다','먼저 설정 화면에서 JSON 백업을 생성하세요.'));return;}
      const label=el('label','field');const select=el('select');select.setAttribute('aria-label','복구할 로컬 백업 파일');files.forEach(file=>{const option=el('option','',`${file.filename} · ${Number(file.bytes||0).toLocaleString()} bytes`);option.value=file.filename;select.append(option);});add(label,el('span','','복구할 백업'),select);content.append(label);
      const check=el('input');check.type='checkbox';const ack=add(el('label','switch-label'),check,document.createTextNode('선택한 백업으로 현재 데이터가 교체됨을 확인했습니다.'));ack.style.marginTop='20px';content.append(ack);
      const error=el('p','form-error');error.setAttribute('role','alert');content.append(error);
      const restore=button('선택한 백업으로 전체 복구','button primary',async()=>{restore.disabled=true;error.textContent='';try{await mutate('/api/restore',{filename:select.value},'선택한 로컬 백업으로 복구했습니다.');S.selected=null;S.selectedCompany=null;S.selectedArticles.clear();$('#modal').close();render();}catch(e){error.textContent=e.message;}finally{restore.disabled=!check.checked;}});restore.disabled=true;check.addEventListener('change',()=>{restore.disabled=!check.checked;});select.addEventListener('change',()=>{check.checked=false;restore.disabled=true;});content.append(add(el('div','form-actions'),button('취소','button',()=>$('#modal').close()),restore));
    }catch(e){status.textContent=`백업 목록을 읽지 못했습니다. ${e.message}`;}
  }
  function shutdownDialog(){
    const content=el('div');content.append(el('p','callout','로컬 서버를 정상 종료합니다. 저장된 JSON은 유지되며 이 브라우저 화면의 연결이 끊깁니다. 다시 시작하려면 AIDC ATLAS 실행 바로가기를 여세요.'));
    const status=el('p','form-error');status.setAttribute('role','alert');content.append(status);const stop=button('로컬 앱 서버 종료','button primary',async()=>{stop.disabled=true;try{await api('/api/shutdown',{});$('#modal').close();$('#connection').textContent='로컬 서버 종료';$('#viewContainer').replaceChildren(empty('아틀라스가 종료되었습니다','다시 시작하려면 AIDC ATLAS 실행 바로가기를 여세요.'));$('#refresh').disabled=true;$('#importOpen').disabled=true;$('#exportOpen').disabled=true;toast('로컬 서버를 정상 종료했습니다.');}catch(e){status.textContent=e.message;stop.disabled=false;}});content.append(add(el('div','form-actions'),button('취소','button',()=>$('#modal').close()),stop));modal('아틀라스 종료',content);
  }
  function aiConnectForm(){
    const profile=S.data?.ai?.connection||{};
    formShell('이 PC의 AI 연결',grid=>{
      add(grid,el('p','callout field full','OpenAI·Claude·Gemini API 키를 지원합니다. 형식으로 제공사를 추정하고 불명확하면 직접 선택합니다. 키 인증은 모델 목록 조회만 수행하며, 기사 분석은 별도 실행합니다.'));
      const wrap=el('label','field'),select=el('select');select.name='provider';
      [['','키 형식으로 자동 추정'],['openai','OpenAI'],['anthropic','Anthropic · Claude'],['google','Google · Gemini'],['corporate','사내 AI · 프로필 편집 (실제 연결 준비 중)']].forEach(([id,label])=>select.append(Object.assign(el('option','',label),{value:id})));add(wrap,el('span','','AI 제공사'),select);grid.append(wrap);
      const key=field(grid,'API 키 · Windows 보안 저장소에 보관','key','','password',true);key.autocomplete='new-password';key.spellcheck=false;
      const hint=el('p','muted field full','키를 여러 제공사에 차례로 전송하지 않습니다.');grid.append(hint);
      key.addEventListener('input',()=>{const k=key.value,guess=k.startsWith('sk-ant-')?'anthropic':k.startsWith('sk-proj-')||k.startsWith('sk-svcacct-')?'openai':k.startsWith('AIza')?'google':'';hint.textContent=guess?`제공사 추정: ${guess} · 인증 전입니다.`:'제공사를 구분하지 못하면 위에서 하나 선택하세요.';});
      const secretRef=field(grid,'환경변수 참조 · 키 직접 입력 대신 선택 사용','secret_ref','','text',true,'예: env:ATLAS_AI_OPENAI_KEY. 기존 키를 재확인할 때는 제공사를 선택하고 키를 비워 두세요.');
      select.addEventListener('change',()=>{if(select.value==='corporate'){key.value='';secretRef.value='';profileForm(S.data?.settings||{});}});
      add(grid,el('p','metadata-label field full',profile.provider?`현재 설정: ${profile.provider_label} · ${profile.model||'모델 선택 필요'}`:'키는 JSON·GitHub·백업에 포함하지 않습니다.'));
    },async (form,progress)=>{
      const payload=Object.fromEntries(form.entries()),keyInput=$('#modalContent input[name="key"]');
      try{if(payload.provider==='corporate')throw Error('사내 API의 인증 헤더와 요청·응답 JSON을 확인한 후 연결을 적용합니다. 키는 전송하지 않았습니다.');const response=await api('/api/ai/connect',payload),r=response.data||response;
        if(['failed','provider_required','protocol_required'].includes(r.status))throw Error(r.message||'AI 연결을 확인하지 못했습니다.');
        if(keyInput)keyInput.value='';progress?.confirmed();await load();toast(r.message||'AI 연결 설정을 저장했습니다.');
        if(r.status==='model_required')setTimeout(aiModelForm,0);
      }finally{payload.key='';}
    },{connection:true});
  }
  function aiModelForm(){
    const profile=S.data?.ai?.connection||{};
    formShell('사용 모델 선택',grid=>{const wrap=el('label','field full'),select=el('select');select.name='model';select.required=true;select.append(Object.assign(el('option','','모델을 선택하세요'),{value:''}));(profile.available_models||[]).forEach(id=>select.append(Object.assign(el('option','',id),{value:id})));select.value=profile.model||'';add(wrap,el('span','','이 키로 접근 가능한 모델'),select);grid.append(wrap);add(grid,el('p','callout field full','제공사별 경량 모델을 우선 추천합니다. 모델 접근 권한과 요금은 해당 API 계정 기준입니다.'));},async form=>{const response=await api('/api/ai/connect',{provider:profile.provider,model:form.get('model')});const r=response.data||response;if(!r.connected)throw Error(r.message||'모델 연결 실패');await load();toast('선택한 모델로 연결했습니다.');});
  }
  function aiForgetDialog(){
    const profile=S.data?.ai?.connection||{},content=el('div');add(content,el('p','callout warning','이 PC의 AI 연결을 끊고 선택한 인증 참조를 지웁니다. 저장 기사·분석 결과는 유지됩니다. 제공사 계정의 키 폐기는 제공사 콘솔에서 별도로 해야 합니다.'));
    const check=el('input');check.type='checkbox';
    if(profile.secret_ref?.startsWith('env:'))add(content,add(el('label','switch-label'),check,document.createTextNode('이 앱 전용 환경변수도 현재 프로세스와 내 Windows 사용자 환경에서 삭제')));
    const action=button('연결 해제 및 키 삭제','button primary',async()=>{action.disabled=true;try{await mutate('/api/ai/forget',{delete_environment:check.checked},'이 PC의 AI 인증 설정을 삭제했습니다. 다른 실행 중 프로세스는 환경변수 사본을 보유할 수 있습니다.');$('#modal').close();}catch{}finally{action.disabled=false;}});content.append(action);modal('AI 키 삭제',content);
  }
  function aiSettingsPanel(){
    const profile=S.data?.ai?.connection||{},panel=el('section','panel ai-settings');
    add(panel,el('h2','','AI 연결과 분석'),el('p','callout',profile.connected?'키 인증을 확인한 연결입니다. 기사 분석은 선택 실행이며 실제 품질은 별도 검증 대상입니다.':'AI 미연결 · 수집·규칙 분류·관계도·스크랩은 계속 사용할 수 있습니다.'));
    const list=el('ul','settings-list');[['상태',profile.connected?'연결 사용 중':profile.credential_present?'키 보관 · 연결 해제':'미연결 / 이 PC에 키 없음'],['제공사',profile.provider_label||'미설정'],['모델',profile.model||'미설정'],['인증 보관',profile.secret_ref||'미설정'],['마지막 키 인증',profile.verified_at?dateTime(profile.verified_at):'미확인'],['실제 분석 성공',profile.inference_verified_at?dateTime(profile.inference_verified_at):'아직 실행하지 않음'],['계정 정보','API 키 연결 · 이메일/구독 정보는 조회하지 않음'],['오늘 호출',`${S.data?.ai?.today_calls||0} / ${profile.daily_call_limit||10}회 · 실패 포함`]].forEach(([k,v])=>list.append(add(el('li'),el('span','',k),el('small','',v))));panel.append(list);
    add(panel,add(el('div','card-actions'),button('API 키 연결','button',aiConnectForm),profile.credential_present?button('모델 선택','button',aiModelForm):null,profile.connected?button('연결 해제','button',async()=>{try{await mutate('/api/ai/disconnect',{},'AI 연결을 해제했습니다. 보관 키와 분석 자료는 유지합니다.');}catch{}}):null,profile.secret_ref?button('키·환경변수 삭제','button',aiForgetDialog):null,button('분석 한도','button',()=>formShell('AI 사용 한도',g=>{const batch=field(g,'한 번에 분석할 기사 · 1~20개','max_articles_per_run',profile.max_articles_per_run||3,'number');batch.min=1;batch.max=20;batch.required=true;const daily=field(g,'하루 API 호출 · 1~500회','daily_call_limit',profile.daily_call_limit||10,'number');daily.min=1;daily.max=500;daily.required=true;add(g,el('p','metadata-label field full','호출 횟수 제한이며 금액 상한은 아닙니다. 금액 한도는 제공사 계정에서도 설정하세요. 같은 입력은 저장 결과를 재사용합니다.'));},async f=>{await mutate('/api/settings',{ai_limits:{max_articles_per_run:Number(f.get('max_articles_per_run')),daily_call_limit:Number(f.get('daily_call_limit'))}},'AI 분석 한도를 저장했습니다.');}))));
    panel.append(button('미분류 기사 AI 후보 검토','button',()=>startAIAnalysis(true)));
    if(window.AtlasAILimits)window.AtlasAILimits.mount(panel,{profile,save:async limits=>{await mutate('/api/settings',{ai_limits:limits},'AI 사용 한도와 역할을 저장했습니다.');}});
    if(profile.credential_error)panel.append(el('p','callout warning','Windows 보안 저장소에 접근하지 못했습니다. 이 PC에서 키를 다시 연결하거나 Windows 사용자 상태를 확인하세요.'));
    return panel;
  }
  async function startAIAnalysis(classify=false){
    classify = classify === true;
    if(!S.data?.ai?.connection?.connected){aiConnectForm();return;}
    const limit=S.data.ai.connection.max_articles_per_run||3,pool=nitems('articles').filter(a=>a.mode==='live_metadata'&&(!classify||!a.scope_classification?.primary_scope)),selected=pool.filter(a=>S.selectedArticles.has(a.id)),articles=(selected.length?selected:pool).slice(0,limit),content=el('div');
    let prepared;
    try{const r=await api(classify?'/api/ai/classify-preview':'/api/ai/preview',{article_ids:articles.map(a=>a.id)});prepared=r.data||r;}catch(e){toast(e.message,true);return;}
    add(content,el('p','callout',`실제 전송 입력 ${prepared.input_chars} / ${prepared.max_input_chars}자 · 출력 상한 ${prepared.max_output_tokens}토큰 · ${prepared.truncated?'공개 설명 일부 축약':'선택 표본'} · 자동 재시도 없음`));
    const preview=el('details');preview.append(el('summary','','실제 전송 공개 기사·비교 후보 확인'),el('pre','note',JSON.stringify({articles:prepared.articles,targets:prepared.targets||[]},null,2)));content.append(preview);
    add(content,el('p','callout',`현재 범위의 ${selected.length?'선택':'최신'} 공개 기사 ${articles.length}개 / 관련 공개 기사 ${pool.length}개를 분석합니다. 제목·공개 RSS 설명과 비교할 공개 사업명 후보만 전송하며 API 사용량이 발생할 수 있습니다. 본문·사내 링크·스크랩 메모는 전송하지 않습니다.`));
    articles.forEach(a=>content.append(link(a.title,a.url,'ai-source-link')));
    const consent=el('input');consent.type='checkbox';const status=el('p','form-error');status.setAttribute('role','status');
    const action=button('공개 기사 분석 실행','button primary',async()=>{action.disabled=true;status.textContent='AI가 공개 기사 근거와 동향을 분석하고 있습니다. 중복 재요청하지 마세요.';try{const response=await api(classify?'/api/ai/classify':'/api/ai/analyse',{article_ids:articles.map(a=>a.id),consent_public_metadata:true}),r=response.data||response;await load();if(!['completed','cached'].includes(r.status))throw Error(r.error?.message||'분석이 완료되지 않았습니다.');$('#modal').close();if(classify){const rr=await api('/api/ai/run?run_id='+encodeURIComponent(r.run_id));showAIResults(rr.data||rr);}toast(r.status==='cached'?'저장된 동일 입력의 분석을 재사용했습니다.':'기사 근거와 동향 분석을 저장했습니다.');}catch(e){status.textContent=e.message;}finally{action.disabled=!consent.checked||!articles.length;}});action.disabled=true;
    consent.addEventListener('change',()=>{action.disabled=!consent.checked||!articles.length;});add(content,add(el('label','switch-label'),consent,document.createTextNode('위 공개 자료의 전송과 API 사용량 발생을 확인했습니다.')),status,action);modal(classify?'미분류 기사 후보 분석 범위':'AI 분석 범위 확인',content);
  }
  async function projectIdentityWorkspace(){const r=await api('/api/project-identities?include_all=true',undefined,'GET');return r.data||r;}
  function mountProjectIdentity(root,workspace,selection){
    if(!window.AtlasProjectIdentity)return;
    window.AtlasProjectIdentity.mount(root,{workspace,articles:arr('articles').filter(a=>a.mode==='live_metadata'&&!['private','internal'].includes(a.visibility)).map(a=>({id:a.id,title:a.title,publisher:a.publisher,published_at:a.published_at,url:a.url})),selection,
      preview:async payload=>{const r=await api('/api/project-identity/preview',payload);return r.data||r;},
      confirm:async payload=>{await api('/api/project-identity/confirm',payload);await load();return projectIdentityWorkspace();},
      undo:async payload=>{await api('/api/project-identity/undo',payload);await load();return projectIdentityWorkspace();},
      openArticles:ids=>{const wanted=new Set(ids),rows=arr('articles').filter(a=>wanted.has(a.id)&&a.mode==='live_metadata'&&!['private','internal'].includes(a.visibility)),host=el('div');let page=0;const draw=()=>{host.replaceChildren(el('p','metadata-label',`공개 근거 ${rows.length}개 · 제목 선택은 읽음 처리가 아닙니다.`));rows.slice(page*24,page*24+24).forEach(a=>host.append(add(el('article','ai-source-link'),link(a.title,a.url),el('small','muted',`${text(a.publisher)} · ${date(a.published_at)}`))));const controls=el('div','card-actions');if(page>0)controls.append(button('이전','button small',()=>{page--;draw();}));if((page+1)*24<rows.length)controls.append(button('다음','button small',()=>{page++;draw();}));host.append(controls);};draw();modal('동일 사업 확인 근거',host);}});
  }
  async function openProjectIdentity(run,match){
    const host=el('div');host.append(el('p','muted','공개 원본 참조를 준비합니다. 키나 기사 원문을 외부로 전송하지 않습니다.'));modal('대표 사업 연결 · 원본 보존',host);
    try{const workspace=await projectIdentityWorkspace();let selection;
      if(run&&match){const target=match.target_id.startsWith('mention:')||match.target_id.startsWith('project:')?match.target_id:'project:'+match.target_id;
        const normalize=value=>String(value||'').replace(/\s+/g,' ').trim().toLocaleLowerCase(),sources=(workspace.refs||[]).filter(ref=>ref.ref!==target&&(ref.article_ids||[]).includes(match.article_id)&&(ref.aliases||[ref.name]).some(name=>normalize(name)===normalize(match.project_name)));
        if(sources.length===1)selection={member_refs:[target,sources[0].ref],canonical_ref:target,run_id:run.id,match_id:match.id};
        else{host.replaceChildren(el('p','callout warning','AI 후보의 출처를 하나의 원본 명칭으로 특정할 수 없습니다. 후보를 보류하고 원문 명칭·단계를 먼저 확인하세요.'));return;}}
      mountProjectIdentity(host,workspace,selection);
    }catch(e){host.replaceChildren(el('p','callout warning','대표 사업 연결 기능은 현재 서버에 아직 적용되지 않았거나 조회에 실패했습니다. 기존 자료는 유지됩니다.'));}
  }
  function showAIResults(run){
    const content=el('div');add(content,el('p','callout',`AI 후보 · ${run.article_ids.length}개 기사 표본 · ${run.model} · ${dateTime(run.finished_at)} · 본문 미확인 · 자동 병합 없음`));
    (run.result?.classifications||[]).forEach(item=>{const row=el('article','ai-extraction');add(row,el('strong','',`${scopeLabels[item.scope]||item.scope} · 분류 검토 후보`),el('p','',item.reason),el('blockquote','',item.quote||'분류 근거 부족 · 보류'),articleRefs([item.article_id]));content.append(row);});
    (run.result?.extractions||[]).forEach(item=>{const row=el('article','ai-extraction');add(row,el('strong','',`${item.project_name||item.company_name||item.kind} · ${item.value}`),el('p','muted',`${item.company_name||''} · ${companyRoleNames().find(r=>r.id===item.role)?.label||item.role} · 근거 연결 후보`),el('blockquote','',item.quote),articleRefs([item.article_id]));content.append(row);});
    (run.result?.matches||[]).forEach(match=>{const target=(run.target_snapshots||[]).find(t=>t.id===match.target_id),decision=S.data.ai.decisions.find(d=>d.id===match.id),row=el('article','ai-extraction');add(row,el('strong','',`${match.project_name} ↔ ${target?.name||match.target_id}`),el('p','',`${({possible_same:'동일 사업 가능',different:'다른 사업',uncertain:'판단 보류'})[match.assessment]||match.assessment} · ${match.reason}`),el('blockquote','',match.quote),articleRefs([match.article_id]),el('small','muted',`확인 상태: ${({accepted_candidate:'동일 사업 후보 확인',rejected:'다른 사업',pending:'보류'})[decision?.decision]||'보류'} · 원본 사업 병합 없음`));
      const action=(label,value)=>button(label,'button small',async()=>{try{await mutate('/api/ai/match-decision',{run_id:run.id,match_id:match.id,decision:value},'동일 사업 비교 후보의 확인 상태를 저장했습니다.');showAIResults(run);}catch{}});add(row,add(el('div','card-actions'),action('같은 사업 후보로 확인','accepted_candidate'),action('다른 사업','rejected'),action('판단 보류·되돌리기','pending'),decision?.decision==='accepted_candidate'&&match.assessment==='possible_same'?button('대표 사업 연결 검토','button small primary',()=>openProjectIdentity(run,match)):null));content.append(row);});
    if(!(run.result?.classifications||[]).length&&!(run.result?.extractions||[]).length&&!(run.result?.matches||[]).length)content.append(el('p','muted','이 표본에서 근거를 확보한 추출·동일 사업 비교 후보가 없습니다.'));
    modal('AI 추출·동일 사업 비교 후보',content);
  }
  function renderAIBriefing(root){
    const ai=S.data?.ai||{},profile=ai.connection||{},run=ai.latest,panel=el('section','panel ai-briefing');panel.setAttribute('aria-label','AI 동향과 점검 요약');
    add(panel,add(el('div','section-head'),el('h2','','동향 · 점검 요약'),button(profile.connected?'공개 기사 AI 분석':'AI 연결','button small',profile.connected?startAIAnalysis:aiConnectForm)));
    if(run){add(panel,el('small','muted',`AI 해석 · 기사 ${run.article_ids.length}개 표본 · ${dateTime(run.finished_at)} · ${run.model}${profile.connected?'':' · 연결 해제 전 저장 결과'}`));
      if(ai.source_changed||ai.newer_articles_count)panel.append(el('p','callout warning',ai.source_changed?'분석 이후 입력 기사가 갱신됐습니다. 재분석이 필요합니다.':`요약 이후 최신 기사 ${ai.newer_articles_count}개가 있습니다. 최신 기사 분석으로 갱신하세요.`));
      (run.result?.briefing||[]).forEach(item=>{const row=el('div','ai-briefing-row');add(row,badge({trend:'동향',change:'보도 변화',check:'확인 필요'}[item.kind]||'AI 해석','neutral'),el('p','',item.text),articleRefs(item.article_ids));panel.append(row);});panel.append(button('추출 근거·동일 사업 비교 후보','button small',()=>showAIResults(run)));
    }else{add(panel,el('p','muted',profile.connected?'선택한 기사 범위의 AI 분석 결과가 없습니다. 공개 기사 표본 분석을 실행하면 출처가 연결된 동향·보도 변화·추가 확인 사항을 표시합니다.':'규칙 기반 수집·분류·기사 연결을 사용 중입니다. AI 연결 후 근거 추출·동일 사업 후보·동향 요약을 추가할 수 있습니다.'));
      nitems('digest').slice(0,2).forEach(item=>panel.append(el('p','metadata-label',item.text||'')));
    }
    if(ai.last_attempt&&['failed','interrupted'].includes(ai.last_attempt.status))panel.append(el('p','callout warning',ai.last_attempt.error?.message||'이전 분석이 중단되었습니다. 자동 재호출하지 않았습니다.'));
    root.append(panel);
  }
  function renderSettings(root){
    root.append(section('관계도·지도와 알림 확인','지도 배치·위치 정밀도·확인 범위는 선택한 기준으로 저장합니다.',button('표시 기준 선택','button primary',visualizationChoices)));
    const settings=S.data.settings||{};const profile=settings.api||{};const grid=el('div','settings-grid');const col=el('section','panel');const live=settings.collection_mode==='live_metadata';add(col,el('h2','','기사 수집과 로컬 저장'),el('p','callout',live?'실제 공개 기사 수집 모드입니다. 자동 수집을 켜면 최근 공개 검색 조건으로 1시간마다 하루 범위를 증분 조회합니다. 기사 본문과 사내 AI는 연결되지 않았습니다.':'아직 실제 기사 검색을 실행하지 않았습니다. 상단 기간 기사 수집을 실행하면 공개 기사 메타데이터 수집 모드로 전환됩니다.'));
    const list=el('ul','settings-list');[['자료 모드',live?'실시간 기사 메타데이터 + 고정 검증 사례':'고정 검증 사례 · 기사 검색 미실행'],['자동 수집',settings.collection_enabled?(live?'사용 · 실제 기사 증분 조회':'사용 · 현재 고정 자료 재처리'):'사용 안 함'],['조회 간격',`${settings.collection_interval_minutes||60}분`],['JSON 저장소','지속 업무데이터의 원본'],['사내 AI',profile.verified?'검증 결과는 연결 테스트에서 확인':'미검증 · 자동 외부 fallback 없음']].forEach(([k,v])=>list.append(add(el('li'),el('span','',k),el('small','',v))));col.append(list);
    const collect=button('고정 자료 지금 재처리','button primary',async()=>{collect.disabled=true;try{const r=await mutate('/api/collect',{},'고정 자료 재처리를 완료했습니다. 중복 근거는 재등록하지 않습니다.');if(r?.data?.status)toast(`재처리: ${r.data.status}`);}catch{}finally{collect.disabled=false;}});
    add(col,add(el('div','card-actions'),collect,button('자동 수집 설정','button',()=>collectionForm(settings)),button('검색 인덱스 재생성','button',async()=>{try{await mutate('/api/index/rebuild',{},'JSON 원본에서 파생 검색 인덱스를 재생성했습니다.');}catch{}})),add(el('div','card-actions'),button('JSON 백업 생성','button',async()=>{try{const res=await mutate('/api/backup',{},'JSON 백업을 생성했습니다.');const url=res?.data?.url;if(url){const u=new URL(url,location.origin);if(u.origin!==location.origin)throw new Error('백업 다운로드 경로가 로컬 서버와 다릅니다.');const a=el('a');a.href=u.href;a.download='';document.body.append(a);a.click();a.remove();}else if(res?.data?.file)toast(`백업 저장: ${res.data.file}`);}catch{}})));
    col.append(add(el('div','card-actions'),button('사내망 수집 연결 진단','button',async()=>{try{const r=await api('/api/network/test',{});const d=r.data||r,content=el('div');add(content,el('p','callout',d.environment.note),el('p','muted',`HTTPS 프록시 ${d.environment.https_proxy_configured?'설정됨':'미설정'} · 회사 CA ${d.environment.custom_ca_configured?'추가 설정됨':'기본 신뢰 저장소'} · PAC ${d.environment.pac_detected?'감지':'미감지'}`));d.results.forEach(x=>content.append(el('p',x.status==='ok'?'callout':'callout warning',`${x.provider} · ${x.status==='ok'?'RSS 연결 확인':x.message} · ${x.code}`)));modal('기사 수집 네트워크 진단',content);}catch(e){toast(e.message,true);}}),button(`신규 기사 표시 · ${settings.new_article_days||30}일`,'button',()=>formShell('신규 기사 표시 기간',g=>{add(g,el('p','callout field full','발행일 기준 최근 기간입니다. 과거 미확인 알림과 기존 저장 자료는 유지됩니다.'));const n=field(g,'기간 · 일','days',settings.new_article_days||30,'number');n.min=1;n.max=365;n.required=true;},async f=>{await mutate('/api/settings',{new_article_days:Number(f.get('days'))},'신규 기사 표시 기간을 저장했습니다.');}))));
    const apiPanel=el('section','panel');add(apiPanel,el('h2','','사내 AI 연결 준비 · 참조 프로필'),el('p','callout','프로필 저장만 지원합니다. 사내 API 연결·분석 어댑터는 아직 구현되지 않았으며 이 프로필을 채워도 AI 연결로 전환되지 않습니다. 비밀키·직번 원문을 입력하지 않습니다. 환경변수의 참조명(env:변수명)만 저장하세요.'));
    const apiList=el('ul','settings-list');[['실행 모드',text(profile.mode,'mock')],['Endpoint',text(profile.endpoint,'미설정')],['Protocol',text(profile.protocol,'unconfigured')],['모델',text(profile.model,'미설정')],['Secret 참조',text(profile.secret_ref,'미설정')]].forEach(([k,v])=>apiList.append(add(el('li'),el('span','',k),el('small','',v))));
    add(apiPanel,apiList,add(el('div','card-actions'),button('프로필 편집','button',()=>profileForm(settings)),button('연결 상태 진단','button',async()=>{try{const r=await api('/api/connection/test',{});const d=r.data||r;const result=el('div');result.append(el('p','callout',text(d.message||d.reason||d.status,'진단 응답을 확인했습니다.')));result.append(el('pre','note',JSON.stringify(d,null,2)));modal('사내 AI 연결 진단',result);}catch(e){toast(e.message,true);}})));
    add(grid,col,aiSettingsPanel(),apiPanel);root.append(grid);
    root.append(section('실제 기사 수집 상태','작업 지시서 출처와 실제 수집 결과를 구분합니다.'));renderJobStatus(root);renderNewsSourceFilter(root);
    const operations=el('div','panel');add(operations,el('h2','','백업 복구와 종료'),el('p','muted','기존 로컬 JSON 백업을 선택해 복구하거나 서버를 정상 종료할 수 있습니다.'),add(el('div','card-actions'),button('로컬 백업에서 복구','button',restoreDialog),button('앱 서버 종료','button',shutdownDialog)));root.append(operations);
    renderFixtureJobStatus(root);
  }
  function renderFixtureJobStatus(root){const jobs=arr('jobs');if(!jobs.length)return;const panel=el('div','panel');panel.append(el('h2','','로컬 재처리 이력 · 실제 뉴스 수집과 별도'),el('p','callout','fixture_mock는 고정 검증 자료의 모의 재처리입니다. completed도 실제 뉴스 수집 성공을 뜻하지 않습니다. 실제 요청·수신·중복·신규 저장·오류는 위의 실제 기사 수집 상태와 수집 진단에서 확인하세요.'));jobs.forEach(j=>panel.append(el('p','muted',`${j.mode==='fixture_mock'?'고정 자료 재처리':text(j.id)} · ${text(j.status)} · 최근 실행 ${date(j.last_run)} · ${text(j.mode,'모드 미확인')}`)));root.append(panel);}
  function collectionForm(settings){formShell('실제 기사 자동 수집 설정',grid=>{add(grid,el('p','callout warning field full','최근 검색 조건으로 하루 범위의 공개 기사 메타데이터를 주기적으로 조회합니다. 먼저 상단 기사 수집을 실행해 검색 조건을 저장하세요.'));const wrap=el('label','field');const select=el('select');select.name='enabled';[['false','사용 안 함'],['true','실제 기사 자동 수집']].forEach(([v,t])=>{const o=el('option','',t);o.value=v;select.append(o);});select.value=String(!!settings.collection_enabled);add(wrap,el('span','','자동 수집'),select);grid.append(wrap);const interval=field(grid,'재처리 간격 · 분','interval',settings.collection_interval_minutes||60,'number');interval.min=60;interval.max=1440;interval.required=true;},async f=>{await mutate('/api/settings',{collection_enabled:f.get('enabled')==='true',collection_interval_minutes:Number(f.get('interval')),collection_mode:'live_metadata'},'실제 기사 자동 수집 설정을 저장했습니다.');});}
  function profileForm(settings){const p=settings.api||{};formShell('사내 AI 프로필 편집 · 연결 준비',grid=>{add(grid,el('p','callout warning field full','현재는 프로필 저장만 지원하며 사내 API 연결·분석 어댑터는 아직 구현되지 않았습니다. 공개 API 키 인증과 별도입니다. 인증/요청 형식만으로 연결 완료가 되지 않으며 응답 JSON 구조와 전송 보안 규약 확인이 필요합니다. 비밀키·직번 원문을 입력하지 마세요. 환경변수 참조명만 저장하며 이 저장은 API를 호출하지 않습니다.'));field(grid,'Endpoint','endpoint',p.endpoint||'','url',true);field(grid,'Protocol','protocol',p.protocol||'unconfigured');field(grid,'모델 이름','model',p.model||'');field(grid,'인증 방식','auth_type',p.auth_type||'bearer');field(grid,'Secret 참조명 · 환경변수 이름 등','secret_ref',p.secret_ref||'','text',true,'예: env:ATLAS_ENTERPRISE_TOKEN. 실제 키 값을 입력하지 마세요.');},async f=>{const data=Object.fromEntries(f.entries());if(data.endpoint&&!safeURL(data.endpoint))throw new Error('올바른 http 또는 https endpoint를 입력하세요.');if(data.secret_ref&&!/^env:[A-Z][A-Z0-9_]*$/.test(data.secret_ref))throw new Error('참조는 env:환경변수명 형식으로 입력하세요.');await mutate('/api/settings',{api:{...data,mode:'mock',verified:false}},'사내 AI 참조 프로필만 저장했습니다. 실제 연결·기사 분석은 실행하지 않았습니다.');});}
  $('#navigation').addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(b)navigate(b.dataset.view);});$('.rail-bottom').addEventListener('click',()=>navigate('settings'));
  $('#aiConnect')?.addEventListener('click',()=>S.data?.ai?.connection?.connected?navigate('settings'):aiConnectForm());
  $('#scopeTabs').addEventListener('click',e=>{const b=e.target.closest('[data-scope]');if(!b)return;S.scope=b.dataset.scope;S.mapSelection=null;S.dashboardArticleIds=null;S.dashboardRegionName='';S.selected=null;S.graphSelection=null;S.graphCluster=null;S.projectFocus=null;S.country='';S.city='';S.region='';S.ontologySelection=null;$$('[data-scope]').forEach(n=>{n.classList.toggle('active',n===b);n.setAttribute('aria-pressed',n===b?'true':'false');});load();});
  $('#includeRead').addEventListener('change',e=>{S.includeRead=e.target.checked;render();});
  $('#newsPeriod').addEventListener('change',e=>{S.period=e.target.value;load();});
  $('#newsCountry').addEventListener('change',e=>{S.country=e.target.value;S.city='';S.region='';load();});
  $('#newsCity').addEventListener('change',e=>{S.city=e.target.value;S.country='';S.region='';load();});
  $('#newsSearch').addEventListener('click',()=>{S.newsQuery=$('#newsQuery').value.trim();load();});
  $('#newsQuery').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();$('#newsSearch').click();}});
  $('#newsCollect').addEventListener('click',()=>{S.newsQuery=$('#newsQuery').value.trim();collectNews();});
  let searchTimer;$('#search').addEventListener('input',e=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{S.query=e.target.value.trim();S.newsQuery=S.query;$('#newsQuery').value=S.newsQuery;S.selected=null;load();},300);});
  $('#refresh').addEventListener('click',()=>load());$('#importOpen').addEventListener('click',importForm);$('#exportOpen').addEventListener('click',exports);$('#modalClose').addEventListener('click',()=>$('#modal').close());
  $('#modal').addEventListener('click',e=>{if(e.target===$('#modal')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
  document.addEventListener('keydown',e=>{if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&!$('#modal').open){e.preventDefault();$('#search').focus();}});
  window.addEventListener('hashchange',()=>{const view=location.hash.slice(1);if(titles[view]&&S.view!==view)navigate(view);});
  let mobileGraph=matchMedia('(max-width:560px)').matches;window.addEventListener('resize',()=>{const now=matchMedia('(max-width:560px)').matches;if(now!==mobileGraph){mobileGraph=now;render();}});
  window.addEventListener('offline',()=>{toast('네트워크 연결이 끊겼습니다. 로컬 서버 연결 상태를 확인하세요.',true);});
  const initial=location.hash.slice(1);if(titles[initial])S.view=initial==='sources'?'news':initial;if(initial==='companies')S.scope='all';if(initial==='regions')S.scope='kr-ai';if(initial==='sources')history.replaceState(null,'','#news');load(true);
})();
