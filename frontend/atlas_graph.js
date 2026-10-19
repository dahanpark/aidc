/* Local, dependency-free evidence graph. Selecting an item never marks it read. */
'use strict';
(() => {
  const NS='http://www.w3.org/2000/svg';
  const ROLES=[['client','발주처','#fda4af'],['developer','사업자','#5eead4'],['tenant','테넌트','#c4b5fd'],['operator','운영사','#7dd3fc'],['contractor','시공사','#fbbf24'],['designer','설계사','#c4d278'],['equipment_supplier','장비사','#f0abfc'],['financier','PF사·금융주선사','#fb923c'],['unknown','역할 미확인','#94a3b8']];
  const TYPES={scope:'사업 분류',location:'나라·도시',project:'등록 사업',pending:'기사 사업명·식별 대기',company:'기업',keyword:'기사 키워드',role:'참여 역할'};
  const COLORS={scope:'#75dccb',location:'#8cb8da',project:'#5eead4',pending:'#d5b879',company:'#afbbf3',keyword:'#87c7d0',role:'#94a3b8'};
  const viewCache=new Map(),activeMounts=new Map();let removalObserver=null,graphSequence=0;
  function remember(key,value){if(!key)return;viewCache.delete(key);viewCache.set(key,value);while(viewCache.size>40)viewCache.delete(viewCache.keys().next().value);}
  function watchMount(root,cleanup){activeMounts.set(root,cleanup);if(typeof MutationObserver==='undefined')return;if(!removalObserver)removalObserver=new MutationObserver(()=>{for(const [mount,dispose] of [...activeMounts])if(!mount.isConnected)dispose();if(!activeMounts.size)removalObserver.disconnect();});removalObserver.observe(document.documentElement,{childList:true,subtree:true});}
  const create=(tag,cls,value)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=value;return n;};
  const svg=(tag,attrs,value)=>{const n=document.createElementNS(NS,tag);Object.entries(attrs||{}).forEach(([k,v])=>n.setAttribute(k,String(v)));if(value!==undefined)n.textContent=value;return n;};
  const append=(parent,...children)=>{children.filter(Boolean).forEach(child=>parent.append(child));return parent;};
  const str=value=>value===null||value===undefined?'':String(value);
  const endpoint=value=>typeof value==='object'?value?.id:value;
  const number=value=>Number.isFinite(Number(value))?Math.max(0,Number(value)):0;
  const name=node=>str(node.name||node.label||node.entity_id||node.id);
  const unread=item=>number(item.unread_count??item.attention?.unread_count??(item.has_unread?1:0));
  const facts=item=>number(item.fact_change_count??item.attention?.fact_change_count);
  const articleIds=item=>Array.isArray(item.article_ids)?item.article_ids:[];
  const role=node=>str(node.role||node.role_id||node.entity_id||node.id).replace(/^role:/,'');
  const color=node=>node.type==='company'&&node.profile_categories?.length?(ROLES.find(([id])=>id===node.profile_categories[0])?.[2]||COLORS.company):node.type==='role'?(ROLES.find(([id])=>id===role(node))?.[2]||COLORS.role):(COLORS[node.type]||COLORS.project);
  const confirmed=edge=>edge.basis==='explicit_stored_relationship'||edge.status==='registered_evidence'||['project_hierarchy','registered_project','registered_role'].includes(edge.type);
  function short(value,max=27){const chars=[...str(value)];return chars.length>max?chars.slice(0,max-1).join('')+'…':chars.join('');}
  function wrap(value,width=18,limit=2){const words=[...str(value)],lines=[];let line='',size=0;for(const c of words){const w=/[\u0000-\u00ff]/.test(c)?.56:1;if(size+w>width){lines.push(line);line='';size=0;if(lines.length===limit){lines[limit-1]=short(lines[limit-1],Math.max(3,[...lines[limit-1]].length-1))+'…';return lines;}}line+=c;size+=w;}if(line)lines.push(line);return lines.slice(0,limit);}
  function normalized(input){
    const unique=new Map();(input.nodes||[]).forEach(n=>{if(n&&n.id!==undefined&&!unique.has(String(n.id)))unique.set(String(n.id),{...n,id:String(n.id),type:n.type||'project'});});
    const all=[...unique.values()],selected=all.slice(0,250),hasFocus=input.centerId!==undefined&&input.centerId!==null&&input.centerId!=='',focus=hasFocus?all.find(n=>n.id===input.centerId||n.entity_id===input.centerId):null;
    if(focus&&!selected.includes(focus)){if(selected.length===250)selected.pop();selected.push(focus);}
    const ids=new Set(selected.map(n=>n.id));
    const edges=(input.edges||[]).map((e,i)=>({...e,id:str(e.id||`edge-${i}`),source:str(endpoint(e.source??e.from)),target:str(endpoint(e.target??e.to))})).filter(e=>ids.has(e.source)&&ids.has(e.target));
    return {nodes:selected,edges,inputCount:all.length};
  }
  function layout(nodes,edges,mode,centerId){
    const points=new Map(),headings=[];
    const ordered=list=>list.slice().sort((a,b)=>number(b.article_count)-number(a.article_count)||name(a).localeCompare(name(b),'ko')||a.id.localeCompare(b.id));
    if(mode==='company-network'){
      const center=nodes.find(n=>n.id===centerId||n.entity_id===centerId)||nodes[0];
      if(center)points.set(center.id,{x:790,y:480,w:248,h:116,center:true});
      ordered(nodes.filter(n=>n!==center)).forEach((n,i)=>{const near=i<8;points.set(n.id,{x:near?(i%2?1110:470):350+((i-8)%4)*280,y:near?220+Math.floor(i/2)*175:1100+Math.floor((i-8)/4)*125,w:224,h:90});});
      headings.push({x:260,y:55,text:'연결 기업 · 근거별 관계'},{x:670,y:55,text:'선택 기업 중심'},{x:1110,y:55,text:'참여·관측과 직접 계약 구분'});
    }else if(mode==='company'){
      const companies=ordered(nodes.filter(n=>n.type==='company'));
      const center=companies.find(n=>n.id===centerId||n.entity_id===centerId)||companies[0];
      if(center)points.set(center.id,{x:790,y:480,w:228,h:106,center:true});
      const hubs=nodes.filter(n=>n.type==='role');
      const roleOrder=[...ROLES.map(([id])=>id),...hubs.map(role).filter(id=>!ROLES.some(([known])=>known===id))];
      hubs.forEach(n=>{const index=roleOrder.indexOf(role(n)),angle=(-90+index*360/roleOrder.length)*Math.PI/180;points.set(n.id,{x:790+Math.cos(angle)*290,y:480+Math.sin(angle)*280,w:154,h:70,hub:true});});
      const keywords=ordered(nodes.filter(n=>n.type==='keyword'));
      keywords.forEach((n,i)=>points.set(n.id,{x:100+(Math.floor(i/9)%2)*205,y:110+(i%9)*110+Math.floor(i/18)*1100,w:180,h:66}));
      const right=ordered(nodes.filter(n=>['project','pending','location','scope'].includes(n.type)));
      right.forEach((n,i)=>points.set(n.id,{x:1290+(Math.floor(i/8)%2)*225,y:120+(i%8)*115+Math.floor(i/16)*1100,w:200,h:76}));
      const companyBelow=Math.max(1040,...[...points.values()].map(p=>p.y+p.h/2+120));
      companies.filter(n=>n!==center).forEach((n,i)=>points.set(n.id,{x:530+(i%4)*230,y:companyBelow+Math.floor(i/4)*118,w:190,h:76}));
      headings.push({x:70,y:45,text:'기사 키워드 · 관측'},{x:670,y:45,text:`기업 · ${roleOrder.length}개 참여 역할`},{x:1160,y:45,text:'사업 · 근거 연결'});
    }else if(centerId!==undefined&&centerId!==null&&centerId!==''&&nodes.some(n=>(n.type==='project'||n.is_named_candidate)&&(n.id===centerId||n.entity_id===centerId))){
      const center=nodes.find(n=>(n.type==='project'||n.is_named_candidate)&&(n.id===centerId||n.entity_id===centerId));
      points.set(center.id,{x:790,y:430,w:258,h:116,center:true});
      const connectedIds=new Set(edges.filter(e=>e.source===center.id||e.target===center.id).flatMap(e=>[e.source,e.target]));
      const near=nodes.filter(n=>n.id!==center.id&&(connectedIds.has(n.id)||(['scope','location'].includes(n.type)&&n.scope&&n.scope===center.scope)));
      const geography=ordered(near.filter(n=>['scope','location'].includes(n.type)));
      geography.forEach((n,i)=>points.set(n.id,{x:220,y:120+i*112,w:190,h:74}));
      const companies=ordered(near.filter(n=>n.type==='company'));
      companies.forEach((n,i)=>points.set(n.id,{x:1240+(Math.floor(i/6)%2)*230,y:125+(i%6)*120+Math.floor(i/12)*850,w:205,h:78}));
      const linked=ordered(near.filter(n=>!['scope','location','company'].includes(n.type)));
      linked.forEach((n,i)=>points.set(n.id,{x:560+(i%3)*230,y:i<3?160:730+Math.floor((i-3)/3)*118,w:200,h:76}));
      const others=ordered(nodes.filter(n=>!points.has(n.id)));
      const below=Math.max(1000,...[...points.values()].map(p=>p.y+p.h+150));
      others.forEach((n,i)=>points.set(n.id,{x:180+(i%6)*245,y:below+Math.floor(i/6)*115,w:205,h:74}));
      headings.push({x:125,y:45,text:'사업 분류 · 국내 도시 · 해외 국가'},{x:670,y:45,text:'선택 사업 중심 관계'},{x:1150,y:45,text:'연결 기업 · 명시 근거'});
      if(others.length)headings.push({x:80,y:below-65,text:'같은 선택 범위의 나머지 근거 · 확인되지 않은 관계는 연결하지 않음'});
    }else{
      const columns=[{types:['scope'],x:140,w:195,title:'01  사업 분류'},{types:['location'],x:435,w:185,title:'02  국내 도시 · 해외 국가'},{types:['project','pending'],x:780,w:225,title:'03  등록 사업 · 식별 대기'},{types:['company'],x:1165,w:205,title:'04  참여·관측 기업'},{types:['keyword','role'],x:1460,w:180,title:'05  키워드 · 역할'}];
      const maxRows=Math.max(5,...columns.map(c=>nodes.filter(n=>c.types.includes(n.type)).length));
      const fullHeight=Math.max(700,(maxRows-1)*110+180);
      columns.forEach(column=>{const list=ordered(nodes.filter(n=>column.types.includes(n.type)));if(!list.length)return;headings.push({x:column.x-column.w/2,y:38,text:column.title});const top=fullHeight/2-(list.length-1)*110/2;list.forEach((n,i)=>{const y=top+i*110;points.set(n.id,{x:column.x,y,w:column.w,h:n.type==='scope'?76:74});});});
    }
    nodes.forEach((n,i)=>{if(!points.has(n.id))points.set(n.id,{x:1600+(i%2)*210,y:100+Math.floor(i/2)*100,w:180,h:70});});
    const values=[...points.values()];return {points,headings,width:Math.max(1500,...values.map(p=>p.x+p.w/2+65)),height:Math.max(880,...values.map(p=>p.y+p.h/2+65))};
  }
  function createGraph(options={}){
    let config={height:650,mode:'project',...options},data,positions,scene,svgRoot,view={x:0,y:0,k:1},selection=null,drag=null,clickSuppressed=false,resizeObserver=null,destroyed=false;
    const graphId=`atlas-network-${++graphSequence}`;
    const initialView=viewCache.get(str(config.viewKey||config.stateKey));
    const root=create('section','atlas-network');root.dataset.graphMode=config.mode;root.setAttribute('aria-label',config.title||'사업과 기업의 근거 관계 지도');
    const toolbar=create('div','atlas-network-toolbar'),intro=create('div','atlas-network-intro'),tools=create('div','atlas-network-tools');
    const title=create('strong','',config.title||'사업·기업 관계 지도'),counts=create('span','atlas-network-counts');append(intro,title,counts);
    const stage=create('div','atlas-network-stage');stage.style.height=`${Math.max(440,number(config.height))}px`;
    const status=create('div','atlas-network-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    const scaleLabel=create('span','atlas-network-scale','100%');
    const tool=(label,aria,fn)=>{const b=create('button','atlas-network-tool',label);b.type='button';b.setAttribute('aria-label',aria);b.addEventListener('click',fn);tools.append(b);return b;};
    tool('−','관계 지도 축소',()=>zoom(.8));tool('+','관계 지도 확대',()=>zoom(1.25));tools.append(scaleLabel);
    tool('전체 맞춤','관계 지도 전체 맞춤',()=>fit(true));tool('선택 중심','선택한 관계 노드 중심으로 보기',()=>focusSelection());
    tool('⛶','관계 지도 전체 화면',async()=>{try{if(document.fullscreenElement===root)await document.exitFullscreen();else if(root.requestFullscreen)await root.requestFullscreen();}catch{status.textContent='이 브라우저에서 전체 화면을 사용할 수 없습니다.';}});
    append(toolbar,intro,tools);
    const footer=create('div','atlas-network-footer'),legend=create('div','atlas-network-legend'),hint=create('span','atlas-network-hint','마우스 휠 확대·축소 · 배경 드래그 이동 · 노드·연결선 선택');
    [['verified','확인된 저장 근거'],['observed','후보·이름·지역 관측'],['new','새 기사'],['fact','사업 사실 변화']].forEach(([cls,label])=>legend.append(append(create('span'),create('i',cls),document.createTextNode(label))));
    append(footer,legend,hint);append(root,toolbar,stage,status,footer);
    function dimensions(){const r=stage.getBoundingClientRect();return {w:Math.max(280,r.width||1200),h:Math.max(440,r.height||650)};}
    function viewState(){const {w,h}=dimensions();return {...view,centerX:(w/2-view.x)/view.k,centerY:(h/2-view.y)/view.k,width:w,height:h};}
    function transform(){if(scene)scene.setAttribute('transform',`translate(${view.x} ${view.y}) scale(${view.k})`);scaleLabel.textContent=`${Math.round(view.k*100)}%`;root.dataset.zoom=String(view.k);if(root.isConnected){const state=viewState();remember(str(config.viewKey||config.stateKey),state);if(typeof config.onViewChange==='function')config.onViewChange(state);}}
    function restoreView(state){if(!state)return false;const {w,h}=dimensions(),cx=Number.isFinite(Number(state.centerX))?Number(state.centerX):0,cy=Number.isFinite(Number(state.centerY))?Number(state.centerY):0;view.k=Math.max(.01,Math.min(3.5,number(state.k)||1));view.x=w/2-cx*view.k;view.y=h/2-cy*view.k;transform();return true;}
    function fit(all=false){if(!positions)return;const {w,h}=dimensions(),projectCenter=config.centerId?data.nodes.find(n=>(n.type==='project'||n.is_named_candidate)&&(n.id===config.centerId||n.entity_id===config.centerId)):null,isFocus=['company','company-network'].includes(config.mode)||Boolean(projectCenter),minimum=config.mode==='company-network'?Math.min(.85,(w-44)/900):isFocus ? .85 : .75,scale=Math.min((w-70)/positions.width,(h-60)/positions.height,1.15);view.k=all?Math.max(.01,scale):Math.max(minimum,scale);view.x=(w-positions.width*view.k)/2;view.y=(h-positions.height*view.k)/2;if(!all&&scale<minimum&&isFocus){const center=projectCenter||data.nodes.find(n=>n.id===config.centerId||n.entity_id===config.centerId)||data.nodes.find(n=>n.type==='company')||data.nodes[0];const p=center&&positions.points.get(center.id);if(p){view.x=w/2-p.x*view.k;view.y=h/2-p.y*view.k;}}transform();}
    function zoom(factor,point){const {w,h}=dimensions(),at=point||{x:w/2,y:h/2},previous=view.k;view.k=Math.max(.01,Math.min(3.5,view.k*factor));view.x=at.x-(at.x-view.x)*view.k/previous;view.y=at.y-(at.y-view.y)*view.k/previous;transform();}
    function focusSelection(){const id=selection?.kind==='node'?selection.id:(config.centerId||config.selectedId);const node=data.nodes.find(n=>n.id===id||n.entity_id===id)||data.nodes.find(n=>n.type===(config.mode==='company'?'company':'project'))||data.nodes[0];if(!node)return;const p=positions.points.get(node.id),{w,h}=dimensions();view.k=Math.max(.8,Math.min(1.2,view.k));view.x=w/2-p.x*view.k;view.y=h/2-p.y*view.k;transform();}
    function select(kind,item){
      selection={kind,id:item.id};root.dataset.selectedId=item.id;
      const connected=new Set([item.id]);if(kind==='node')data.edges.filter(e=>e.source===item.id||e.target===item.id).forEach(e=>{connected.add(e.source);connected.add(e.target);connected.add(e.id);});else{connected.add(item.source);connected.add(item.target);}
      stage.querySelectorAll('[data-node-id],[data-edge-id]').forEach(el=>{const id=el.dataset.nodeId||el.dataset.edgeId;el.classList.toggle('is-selected',id===item.id);el.classList.toggle('is-connected',connected.has(id));el.classList.toggle('is-muted',!connected.has(id));if(el.dataset.nodeId)el.setAttribute('aria-pressed',id===item.id?'true':'false');});
      status.replaceChildren();const label=kind==='node'?name(item):str(item.label||item.role||item.type||'근거 연결');
      status.append(create('strong','',label),create('span','',`근거 기사 ${articleIds(item).length}개${unread(item)?` · 미확인 ${unread(item)}건`:''}`));
      if(unread(item)&&typeof config.onAcknowledge==='function'){const b=create('button','atlas-network-ack','선택 항목 확인 완료');b.type='button';b.addEventListener('click',()=>config.onAcknowledge({kind,id:item.id,[kind]:item,article_ids:articleIds(item),attention_ids:item.unread_attention_ids||item.attention_ids||[],unread_attention_ids:item.unread_attention_ids||[]}));status.append(b);}
      if(typeof config.onSelect==='function')config.onSelect({kind,id:item.id,[kind]:item,article_ids:articleIds(item)});
    }
    function activate(element,kind,item){element.setAttribute('tabindex','0');element.setAttribute('role','button');element.addEventListener('click',event=>{if(clickSuppressed)return;event.stopPropagation();select(kind,item);});element.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(kind,item);}if(kind==='node'&&['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();const p=positions.points.get(item.id),candidates=data.nodes.filter(n=>n.id!==item.id).map(n=>({n,p:positions.points.get(n.id)})).filter(({p:q})=>event.key==='ArrowUp'?q.y<p.y:event.key==='ArrowDown'?q.y>p.y:event.key==='ArrowLeft'?q.x<p.x:q.x>p.x).sort((a,b)=>Math.hypot(a.p.x-p.x,a.p.y-p.y)-Math.hypot(b.p.x-p.x,b.p.y-p.y));const next=candidates[0];if(next){const target=[...stage.querySelectorAll('[data-node-id]')].find(n=>n.dataset.nodeId===next.n.id);target?.focus();}}});}
    function draw(){
      data=normalized(config);root.dataset.graphMode=config.mode;
      // Missing role slots are explicit empty visual placeholders, never inferred participation.
      if(config.mode==='company')ROLES.forEach(([id,label])=>{if(!data.nodes.some(n=>n.type==='role'&&role(n)===id)){if(data.nodes.length>=250){const index=data.nodes.findLastIndex(n=>n.type!=='role'&&n.id!==config.centerId&&n.entity_id!==config.centerId);if(index>=0)data.nodes.splice(index,1);}data.nodes.push({id:`atlas-empty-role:${id}`,entity_id:id,type:'role',role:id,name:label,article_count:0,article_ids:[],placeholder:true});}});
      const shownIds=new Set(data.nodes.map(n=>n.id));data.edges=data.edges.filter(e=>shownIds.has(e.source)&&shownIds.has(e.target));
      positions=layout(data.nodes,data.edges,config.mode,config.centerId);stage.replaceChildren();
      svgRoot=svg('svg',{class:'atlas-network-svg',role:'group','aria-label':`${config.title||'근거 관계 지도'}. 탭 키로 노드와 연결선 선택, 방향 키로 주변 노드 이동.`});const size=dimensions();svgRoot.setAttribute('viewBox',`0 0 ${size.w} ${size.h}`);stage.append(svgRoot);
      const defs=svg('defs'),pattern=svg('pattern',{id:`${graphId}-grid`,width:96,height:96,patternUnits:'userSpaceOnUse'});
      pattern.append(svg('path',{d:'M96 0H0V96',class:'atlas-network-grid-major'}));
      for(let x=0;x<96;x+=24)for(let y=0;y<96;y+=24)pattern.append(svg('circle',{cx:x,cy:y,r:.75,class:'atlas-network-grid-dot'}));
      defs.append(pattern);svgRoot.append(defs,svg('rect',{width:'100%',height:'100%',fill:`url(#${pattern.id})`,class:'atlas-network-background','aria-hidden':'true'}));
      scene=svg('g',{'data-atlas-scene':'true'});svgRoot.append(scene);
      positions.headings.forEach(h=>scene.append(svg('text',{x:h.x,y:h.y,class:'atlas-network-column-title'},h.text)));
      const edgeLayer=svg('g',{class:'atlas-network-edges'}),nodeLayer=svg('g',{class:'atlas-network-nodes'});scene.append(edgeLayer,nodeLayer);
      data.edges.forEach(edge=>{const a=positions.points.get(edge.source),b=positions.points.get(edge.target);if(!a||!b)return;const dx=b.x-a.x,dir=dx>=0?1:-1,from={x:a.x+dir*a.w/2,y:a.y},to={x:b.x-dir*b.w/2,y:b.y};const bend=Math.max(65,Math.abs(dx)*.43);const d=`M${from.x},${from.y} C${from.x+dir*bend},${from.y} ${to.x-dir*bend},${to.y} ${to.x},${to.y}`;
        const group=svg('g',{class:`atlas-network-edge ${confirmed(edge)?'is-verified':'is-observed'}${unread(edge)?' has-unread':''}${facts(edge)&&unread(edge)?' has-fact':''}`,'data-edge-id':edge.id,'aria-label':`${name(data.nodes.find(n=>n.id===edge.source)||{})}에서 ${name(data.nodes.find(n=>n.id===edge.target)||{})} · ${edge.label||edge.role||edge.type} · 근거 기사 ${articleIds(edge).length}개`});
        group.append(svg('path',{d,class:'atlas-network-edge-hit'}),svg('path',{d,class:'atlas-network-edge-line'}),svg('circle',{cx:from.x,cy:from.y,r:3,class:'atlas-network-edge-port'}),svg('circle',{cx:to.x,cy:to.y,r:3,class:'atlas-network-edge-port'}));group.append(svg('title',{},`${edge.label||edge.role||edge.type} · ${edge.basis||'근거 유형 미확인'} · 기사 ${articleIds(edge).length}개`));
        const label=svg('text',{x:(from.x+to.x)/2,y:(from.y+to.y)/2-8,class:'atlas-network-edge-label','text-anchor':'middle'},short(edge.label||edge.role||'',26));group.append(label);activate(group,'edge',edge);edgeLayer.append(group);
      });
      data.nodes.forEach(node=>{const p=positions.points.get(node.id),isCluster=Array.isArray(node.clustered_ids)&&node.clustered_ids.length>0,isEmpty=node.type==='role'&&(node.placeholder||number(node.article_count??articleIds(node).length)===0),isUnread=unread(node)>0;const group=svg('g',{transform:`translate(${p.x-p.w/2},${p.y-p.h/2})`,class:`atlas-network-node type-${node.type}${isCluster?' is-cluster':''}${p.center?' is-center':''}${isEmpty?' is-placeholder':''}${isUnread?' has-unread':''}${facts(node)&&isUnread?' has-fact':''}`,'data-node-id':node.id,'data-entity-id':node.entity_id||node.id,'data-node-type':node.type,'aria-label':`${name(node)}, ${isCluster?`원본 자료 ${node.clustered_ids.length}개 묶음`:TYPES[node.type]||'자료'}, 기사 ${number(node.article_count??articleIds(node).length)}개${isEmpty?', 역할 근거 없음':''}${isUnread?`, 미확인 ${unread(node)}건`:''}`,'aria-pressed':'false',style:`--node-color:${color(node)}`});
        if(isCluster)group.append(svg('rect',{x:4,y:4,width:p.w,height:p.h,rx:p.center?16:12,class:'atlas-network-cluster-back'}));
        if(isUnread)group.append(svg('rect',{x:-6,y:-6,width:p.w+12,height:p.h+12,rx:p.h>90?22:17,class:'atlas-network-unread-halo'}));
        group.append(svg('rect',{width:p.w,height:p.h,rx:p.center?16:12,class:'atlas-network-node-shape'}),svg('path',{d:`M${p.center?18:14} 1H${p.w-(p.center?18:14)}`,class:'atlas-network-node-accent'}),svg('circle',{cx:15,cy:17,r:3.2,fill:isEmpty?'#627587':color(node)}));
        const count=number(node.article_count??articleIds(node).length),countLabel=isEmpty?'—':`${count.toLocaleString('ko-KR')}개`,pillWidth=Math.max(30,[...countLabel].length*6+13);
        const typeLabel=isCluster?`묶음 · 원본 ${node.clustered_ids.length}개`:node.type==='role'?(isEmpty?'역할 근거 없음':'명시된 참여 역할'):node.type==='company'&&node.profile_categories?.length?`${(node.profile_categories[0]==='unknown'?'성격 미확인':ROLES.find(([id])=>id===node.profile_categories[0])?.[1])||'성격 미확인'} · 기업 성격`:(TYPES[node.type]||'근거 자료');
        const visibleType=p.h>90?typeLabel:wrap(typeLabel,Math.max(3,(p.w-pillWidth-46)/9),1)[0];group.append(svg('text',{x:25,y:20,class:'atlas-network-node-type'},visibleType));
        const lines=wrap(name(node),(p.w-26)/(p.center?17:12),2);lines.forEach((line,i)=>group.append(svg('text',{x:13,y:p.center?46+i*21:40+i*15,class:'atlas-network-node-label'},line)));
        if(p.h>90){group.append(svg('path',{d:`M13 ${p.h-32}H${p.w-13}`,class:'atlas-network-center-divider'}),svg('text',{x:13,y:p.h-13,class:'atlas-network-node-count'},`연결 기사 ${count.toLocaleString('ko-KR')}개`));}else{group.append(svg('rect',{x:p.w-pillWidth-8,y:7,width:pillWidth,height:19,rx:6,class:'atlas-network-count-pill'}),svg('text',{x:p.w-14,y:20,class:'atlas-network-node-count','text-anchor':'end'},countLabel));}
        if(isUnread){const count=Math.min(999,unread(node));group.append(svg('circle',{cx:p.w-2,cy:0,r:13,class:'atlas-network-unread-badge'}),svg('text',{x:p.w-2,y:4,'text-anchor':'middle',class:'atlas-network-unread-count'},count>99?'99+':String(count)));}
        group.append(svg('title',{},`${name(node)} · ${typeLabel} · 근거 ${articleIds(node).length}개${facts(node)?` · 사업 사실 변화 ${facts(node)}건`:''}`));activate(group,'node',node);nodeLayer.append(group);
      });
      const actual=data.nodes.length,total=Math.max(actual,number(config.totalNodes??config.total_nodes??config.graph?.total_nodes)||data.inputCount);counts.textContent=`노드 ${actual} / 전체 ${total} · 연결 ${data.edges.length}개${total>actual?' · 나머지 자료는 목록·표에서 확인':''}${data.nodes.some(n=>n.type==='role'&&n.placeholder)?' · 빈 역할 자리 포함':''}`;
      if(!data.inputCount){status.textContent='현재 조건에 표시할 근거 노드가 없습니다. 기간·분류·검색 조건을 변경하세요.';}else status.textContent='노드와 연결선을 선택하면 해당 근거와 미확인 변화를 확인할 수 있습니다. 선택만으로 읽음 상태는 바뀌지 않습니다.';
      svgRoot.addEventListener('pointerdown',event=>{if(event.button!==0||event.target.closest('[data-node-id],[data-edge-id]'))return;drag={x:event.clientX,y:event.clientY,tx:view.x,ty:view.y,moved:false};svgRoot.setPointerCapture(event.pointerId);stage.classList.add('is-panning');});
      svgRoot.addEventListener('pointermove',event=>{if(!drag)return;const dx=event.clientX-drag.x,dy=event.clientY-drag.y;drag.moved=drag.moved||Math.abs(dx)+Math.abs(dy)>5;view.x=drag.tx+dx;view.y=drag.ty+dy;transform();});
      const release=()=>{clickSuppressed=Boolean(drag?.moved);drag=null;stage.classList.remove('is-panning');setTimeout(()=>{clickSuppressed=false;},80);};svgRoot.addEventListener('pointerup',release);svgRoot.addEventListener('pointercancel',release);
      svgRoot.addEventListener('wheel',event=>{const delta=event.deltaY||event.deltaX;if(!delta)return;event.preventDefault();const r=svgRoot.getBoundingClientRect();zoom(delta<0?1.12:.89,{x:event.clientX-r.left,y:event.clientY-r.top});},{passive:false});
      if(!restoreView(viewCache.get(str(config.viewKey||config.stateKey))))fit(false);
      if(config.selectedId){const n=data.nodes.find(n=>n.id===config.selectedId||n.entity_id===config.selectedId);if(n){const old=config.onSelect;config.onSelect=null;select('node',n);config.onSelect=old;}}
    }
    root.update=next=>{config={...config,...next};draw();return root;};root.fit=()=>fit(true);root.focusSelection=focusSelection;root.getViewState=viewState;
    root.destroy=()=>{if(destroyed)return;destroyed=true;resizeObserver?.disconnect();activeMounts.delete(root);if(!activeMounts.size)removalObserver?.disconnect();};
    draw();requestAnimationFrame(()=>{if(!root.isConnected||destroyed){root.destroy();return;}if(!restoreView(initialView))fit(false);if(typeof ResizeObserver!=='undefined'){resizeObserver=new ResizeObserver(()=>{if(!root.isConnected){root.destroy();return;}const state=viewCache.get(str(config.viewKey||config.stateKey)),{w,h}=dimensions();svgRoot?.setAttribute('viewBox',`0 0 ${w} ${h}`);if(state)restoreView(state);});resizeObserver.observe(stage);}watchMount(root,root.destroy);});
    return root;
  }
  window.AtlasGraph=Object.freeze({create:createGraph,roles:ROLES.map(([id,label,color])=>({id,label,color}))});
})();
