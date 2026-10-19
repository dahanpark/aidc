/* Offline evidence map. No tiles, geocoding, external scripts, or inferred sites. */
'use strict';
(() => {
  const NS='http://www.w3.org/2000/svg', W=1000, H=640;
  const COLORS={'kr-dc':'#3984d5','kr-ai':'#1a978b','global-ai':'#e3a045'};
  const cache=new Map();
  const cameras=new Map();
  const regionNames=new Map([['KR','대한민국']]);
  const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const svgNode=(tag,attrs,text)=>{const n=document.createElementNS(NS,tag);Object.entries(attrs||{}).forEach(([key,value])=>n.setAttribute(key,String(value)));if(text!==undefined)n.textContent=text;return n;};
  const button=(label,aria,action)=>{const b=node('button','atlas-map-control',label);b.type='button';b.setAttribute('aria-label',aria);b.addEventListener('click',action);return b;};
  const finite=(n,limit)=>typeof n==='number'&&Number.isFinite(n)&&Math.abs(n)<=limit;
  const aidSet=markers=>new Set(markers.flatMap(m=>m.article_ids||[]));
  const valid=m=>finite(m.longitude,180)&&finite(m.latitude,90);

  function boundary(name){
    if(!cache.has(name))cache.set(name,fetch(`/assets/maps/${name}.geojson`,{cache:'force-cache',credentials:'same-origin'})
      .then(r=>{if(!r.ok)throw new Error('경계 파일을 읽을 수 없습니다.');return r.json();})
      .then(data=>{if(data.type!=='FeatureCollection'||!Array.isArray(data.features)||data.features.length>1000)throw new Error('경계 형식 오류');return data;})
      .catch(error=>{cache.delete(name);throw error;}));
    return cache.get(name);
  }

  function mapPanel({kind,title,markers,onSelect,onGroupSelect,onCountrySelect,selectedMarkerId,inset=false,viewKey=''}){
    const panel=node('section',`atlas-map-panel${inset?' atlas-map-inset':''}`);panel.dataset.mapKind=kind;
    panel.setAttribute('aria-label',title);
    const heading=node('div','atlas-map-heading'),headingText=node('div');
    headingText.append(node('h3','',title),node('p','atlas-map-count',`표식 ${markers.length}개 · 관련 기사 ${aidSet(markers).size}개`));
    heading.append(headingText);panel.append(heading);
    const canvas=node('div','atlas-map-canvas'), svg=svgNode('svg',{viewBox:`0 0 ${W} ${H}`,role:'group','aria-label':`${title}. 버튼으로 확대·축소, 배경 드래그로 이동, 표식 선택으로 사업 관계 확인`,tabindex:'0'});
    svg.classList.add('atlas-map-svg');canvas.append(svg);panel.append(canvas);
    const bg=svgNode('rect',{x:-4000,y:-3000,width:9000,height:7000,class:'atlas-map-ocean'}),grid=svgNode('g',{class:'atlas-map-graticule'}),land=svgNode('g',{class:'atlas-map-land'}),points=svgNode('g',{class:'atlas-map-points'});
    svg.append(bg,grid,land,points);
    const north=node('div','atlas-map-north','N ↑');north.setAttribute('aria-hidden','true');canvas.append(north);
    const coords=node('div','atlas-map-coordinate-note',kind==='korea'?'대한민국 · 도시 대표점과 사업 부지 구분':'세계 · 국가 대표점과 사업 부지 구분');canvas.append(coords);
    const help=node('p','atlas-map-help','스크롤 확대·축소 · 배경 드래그 이동 · 표식/국가 선택 → 오른쪽 사업 목록');panel.append(help);
    const controls=node('div','atlas-map-controls');heading.append(controls);
    const bounds=kind==='korea'?[124.2,32.6,131.6,39.2]:[-180,-60,180,85];
    const cosine=kind==='korea'?Math.cos(36*Math.PI/180):1;
    const spanX=(bounds[2]-bounds[0])*cosine,spanY=bounds[3]-bounds[1],scale=Math.min((W-80)/spanX,(H-65)/spanY);
    const marginX=(W-spanX*scale)/2,marginY=(H-spanY*scale)/2;
    const project=(lon,lat)=>[marginX+(lon-bounds[0])*cosine*scale,marginY+(bounds[3]-lat)*scale];
    function homeCamera(){
      if(kind!=='korea')return {x:0,y:0,w:W,h:H};
      const a=project(124.5,39),b=project(131,32.6),aspect=(canvas.clientWidth||W)/(canvas.clientHeight||H);
      const width=Math.max(b[0]-a[0]+35,(b[1]-a[1]+35)*aspect),height=width/aspect;
      return {x:(a[0]+b[0]-width)/2,y:(a[1]+b[1]-height)/2,w:width,h:height};
    }
    const cameraKey=`${viewKey}:${kind}`,saved=cameras.get(cameraKey);
    let camera=saved?{...saved.camera}:homeCamera(),selectedIds=new Set(selectedMarkerId?[selectedMarkerId]:[]),drag=null,viewChanged=Boolean(saved?.viewChanged),ignoreCountryClick=false;
    svg.setAttribute('viewBox',`${camera.x} ${camera.y} ${camera.w} ${camera.h}`);
    function apply(){
      cameras.delete(cameraKey);cameras.set(cameraKey,{camera:{...camera},viewChanged});
      if(cameras.size>40)cameras.delete(cameras.keys().next().value);
      svg.setAttribute('viewBox',`${camera.x} ${camera.y} ${camera.w} ${camera.h}`);renderMarkers();
    }
    function zoom(factor,anchor){
      viewChanged=true;
      const old=camera.w,newW=Math.max(W/20,Math.min(W*1.5,old/factor)),ratio=newW/old;
      const x=anchor?.[0]??camera.x+camera.w/2,y=anchor?.[1]??camera.y+camera.h/2;
      camera={x:x-(x-camera.x)*ratio,y:y-(y-camera.y)*ratio,w:newW,h:camera.h*ratio};apply();
    }
    function reset(){viewChanged=false;camera=homeCamera();apply();}
    function fitMarkers(){
      if(!markers.length){reset();return;}
      const xy=markers.map(m=>project(m.longitude,m.latitude));
      let x1=Math.min(...xy.map(p=>p[0])),x2=Math.max(...xy.map(p=>p[0])),y1=Math.min(...xy.map(p=>p[1])),y2=Math.max(...xy.map(p=>p[1]));
      const aspect=(canvas.clientWidth||W)/(canvas.clientHeight||H),width=Math.max(kind==='korea'?210:90,x2-x1+110,(y2-y1+110)*aspect),height=width/aspect;
      viewChanged=true;
      camera={x:(x1+x2-width)/2,y:(y1+y2-height)/2,w:width,h:height};apply();
    }
    controls.append(button('+',`${title} 지도 확대`,()=>zoom(1.5)),button('−',`${title} 지도 축소`,()=>zoom(1/1.5)),
      button('전체',`${title} 지도 전체 맞춤`,reset),button('표식',`${title} 표식 전체 맞춤`,fitMarkers),
      button('⛶',`${title} 지도 전체 화면`,async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await panel.requestFullscreen();}catch{help.textContent='전체 화면은 현재 브라우저에서 지원되지 않습니다.';}}));
    function choose(marker){
      selectedIds=new Set([marker.id]);renderMarkers();
      if(typeof onSelect==='function')onSelect(marker);
    }
    function clusterSelect(group){
      if(group.length===1){choose(group[0]);return;}
      selectedIds=new Set(group.map(m=>m.id));renderMarkers();
      if(typeof onGroupSelect==='function')onGroupSelect(group);
    }
    function renderMarkers(){
      points.replaceChildren();
      const px=camera.w/Math.max(canvas.clientWidth,100),cell=30*px,groups=new Map();
      markers.forEach(m=>{const [x,y]=project(m.longitude,m.latitude),key=`${Math.round(x/cell)}:${Math.round(y/cell)}`;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(m);});
      groups.forEach(group=>{
        const coords=group.map(m=>project(m.longitude,m.latitude)),x=coords.reduce((a,p)=>a+p[0],0)/coords.length,y=coords.reduce((a,p)=>a+p[1],0)/coords.length;
        const r=(group.length>1?14:9)*px,isNew=group.some(m=>Number(m.unread_count)>0),exact=group.every(m=>m.precision==='exact');
        const first=group[0],label=group.length>1?`겹친 표식 ${group.length}개 · 기사 ${aidSet(group).size}개`:`${first.name} · ${first.position_label} · 기사 ${first.article_count||0}개`;
        const g=svgNode('g',{class:`atlas-map-marker${exact?' exact':' approximate'}${group.some(m=>selectedIds.has(m.id))?' selected':''}`,
          transform:`translate(${x} ${y})`,role:'button',tabindex:0,'aria-label':label,'data-marker-id':group.length===1?first.id:group.map(m=>m.id).join('|'),'data-cluster-size':group.length});
        if(isNew)g.append(svgNode('circle',{r:r+7*px,class:'atlas-map-unread-halo','stroke-width':2.5*px}));
        g.append(svgNode('circle',{r,fill:group.length>1?'#284b62':COLORS[first.scope]||'#657588',class:'atlas-map-marker-dot','stroke-width':2*px,...(!exact?{'stroke-dasharray':`${3*px} ${2*px}`}:{})}));
        if(group.length>1)g.append(svgNode('text',{'text-anchor':'middle','dominant-baseline':'central','font-size':11*px,fill:'#fff',class:'atlas-map-cluster-number'},group.length));
        else if(first.kind==='project')g.append(svgNode('rect',{x:-3*px,y:-3*px,width:6*px,height:6*px,fill:'#fff'}));
        if(isNew)g.append(svgNode('text',{x:r+2*px,y:-r-4*px,'font-size':8*px,class:'atlas-map-new-label'},'NEW'));
        const name=group.length>1?'':String(first.name||'').slice(0,kind==='korea'?18:13);
        if(name)g.append(svgNode('text',{x:r+5*px,y:4*px,'font-size':11*px,'stroke-width':3*px,class:'atlas-map-marker-label'},name));
        g.append(svgNode('title',{},label));
        const action=()=>clusterSelect(group);g.addEventListener('click',action);g.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();action();}});points.append(g);
      });
    }
    svg.addEventListener('pointerdown',event=>{
      if(event.button!==0||event.target.closest('[data-marker-id]'))return;
      ignoreCountryClick=false;viewChanged=true;drag={x:event.clientX,y:event.clientY,camera:{...camera}};svg.setPointerCapture(event.pointerId);svg.classList.add('dragging');
    });
    svg.addEventListener('pointermove',event=>{if(!drag)return;const ratio=drag.camera.w/svg.getBoundingClientRect().width;
      if(Math.hypot(event.clientX-drag.x,event.clientY-drag.y)>4)ignoreCountryClick=true;
      camera={...drag.camera,x:drag.camera.x-(event.clientX-drag.x)*ratio,y:drag.camera.y-(event.clientY-drag.y)*ratio};apply();});
    const end=()=>{drag=null;svg.classList.remove('dragging');};svg.addEventListener('pointerup',end);svg.addEventListener('pointercancel',end);
    svg.addEventListener('wheel',event=>{event.preventDefault();const rect=svg.getBoundingClientRect();if(!rect.width||!rect.height)return;const a=[camera.x+(event.clientX-rect.left)/rect.width*camera.w,camera.y+(event.clientY-rect.top)/rect.height*camera.h],delta=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?rect.height:1);zoom(Math.exp(-Math.max(-150,Math.min(150,delta))*.002),a);},{passive:false});
    svg.addEventListener('keydown',event=>{if(event.target!==svg)return;
      if(['+','=','-'].includes(event.key)){event.preventDefault();zoom(event.key==='-'?1/1.5:1.5);}
      if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();viewChanged=true;camera.x+=(event.key==='ArrowLeft'?-1:event.key==='ArrowRight'?1:0)*camera.w*.1;camera.y+=(event.key==='ArrowUp'?-1:event.key==='ArrowDown'?1:0)*camera.h*.1;apply();}
    });
    let connected=false;
    const observer=new ResizeObserver(()=>{if(svg.isConnected){connected=true;if(!viewChanged&&kind==='korea'){camera=homeCamera();svg.setAttribute('viewBox',`${camera.x} ${camera.y} ${camera.w} ${camera.h}`);}renderMarkers();}else if(connected)observer.disconnect();});observer.observe(canvas);
    const ready=boundary(kind==='korea'?'korea':'world').then(data=>{
      for(let lon=-180;lon<=180;lon+=30){const a=project(lon,-60),b=project(lon,85);grid.append(svgNode('path',{d:`M${a[0]},${a[1]}L${b[0]},${b[1]}`}));}
      for(let lat=-60;lat<=80;lat+=20){const a=project(-180,lat),b=project(180,lat);grid.append(svgNode('path',{d:`M${a[0]},${a[1]}L${b[0]},${b[1]}`}));}
      const active=new Set(markers.map(m=>m.country));
      data.features.forEach(feature=>{
        const polys=feature.geometry?.type==='Polygon'?[feature.geometry.coordinates]:feature.geometry?.type==='MultiPolygon'?feature.geometry.coordinates:[];
        const d=polys.flatMap(poly=>poly.map(ring=>ring.filter(p=>finite(p[0],180)&&finite(p[1],90)).map((p,index)=>{const xy=project(p[0],p[1]);return `${index?'L':'M'}${xy[0].toFixed(2)},${xy[1].toFixed(2)}`;}).join('')+'Z')).join('');
        const path=svgNode('path',{d,class:`atlas-map-country${active.has(feature.id)?' active-country':''}${feature.id==='KR'?' map-korea':''}`,'data-country':feature.id,'fill-rule':'evenodd'});
        if(active.has(feature.id)&&typeof onCountrySelect==='function'){
          path.classList.add('atlas-map-selectable-country');path.setAttribute('role','button');path.setAttribute('tabindex','0');path.setAttribute('aria-label',`${feature.properties?.name_ko||feature.properties?.name||feature.id} 관련 사업과 기사 목록`);
          const selectCountry=()=>onCountrySelect(feature.id,feature.properties?.name_ko||feature.properties?.name||feature.id);
          path.addEventListener('click',()=>{if(!ignoreCountryClick)selectCountry();});path.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();selectCountry();}});
        }
        path.append(svgNode('title',{},feature.properties?.name_ko||feature.properties?.name||feature.id));land.append(path);
      });
      renderMarkers();panel.dataset.mapStatus='ready';
      if(!markers.length)canvas.append(node('p','atlas-map-empty','이 조건에서 지도에 배치할 위치 근거가 없습니다. 미배치 자료를 확인하세요.'));
    }).catch(error=>{panel.dataset.mapStatus='error';canvas.append(node('p','atlas-map-error',`지도 경계를 표시할 수 없습니다. ${error.message}`));});
    return {element:panel,ready,setSelected(ids){selectedIds=new Set(ids);renderMarkers();},focus(id){const m=markers.find(item=>item.id===id);if(m){const [x,y]=project(m.longitude,m.latitude);viewChanged=true;camera={x:x-150,y:y-96,w:300,h:192};apply();choose(m);}},destroy(){observer.disconnect();}};
  }

  function create({layers,mode,positionPolicy,onSelect,scope='all',viewKey,selectedMarkerId,describeMarker,onProjectSelect,onArticlesSelect,onClearSelection,detailMode='projects'}={}){
    const root=node('section','atlas-map-workspace');root.setAttribute('aria-label','사업 지리 지도');
    if(!['split','world-inset'].includes(mode)||!['approximate','exact_only'].includes(positionPolicy)){
      root.append(node('p','atlas-map-policy-needed','지도 구성과 위치 표시 정책을 선택하면 지도를 표시합니다.'));root.dataset.mapStatus='awaiting-policy';return root;
    }
    const workspace=Array.isArray(layers)?{scope_layers:layers}:layers||{};
    if(workspace.position_policy&&workspace.position_policy!==positionPolicy){
      root.append(node('p','atlas-map-policy-needed','선택한 위치 정책과 지도 데이터가 다릅니다. 자료를 새로고침하세요.'));root.dataset.mapStatus='policy-mismatch';return root;
    }
    root.dataset.detailMode=detailMode==='articles'?'articles':'projects';root.dataset.mapMode=mode;root.dataset.positionPolicy=positionPolicy;root.dataset.mapStatus='loading';root.dataset.scope=scope;
    const list=(workspace.scope_layers||[]).filter(layer=>scope==='all'||layer.id===scope).flatMap(layer=>(layer.markers||[]).filter(valid));
    const domestic=list.filter(m=>['kr-dc','kr-ai'].includes(m.scope)),foreign=list.filter(m=>m.scope==='global-ai');
    const layout=node('div',`atlas-map-layout atlas-map-${mode}${scope!=='all'?' atlas-map-single':''}`),panels=[];
    const body=node('div','atlas-map-body'),detail=node('aside','atlas-map-detail');detail.setAttribute('aria-label','선택 지역의 사업과 근거 기사');detail.setAttribute('aria-live','polite');body.append(layout,detail);
    const uniqueProjects=items=>[...new Map(items.filter(item=>item.kind==='project').map(item=>[item.project_id||item.id,item])).values()];
    const unlocated=(workspace.unlocated||[]).filter(item=>scope==='all'||item.scope===scope);
    const count=value=>Number.isFinite(Number(value))?Math.max(0,Number(value)):0;
    const articleCount=item=>Array.isArray(item.article_ids)?new Set(item.article_ids).size:count(item.article_count);
    const registeredProject=marker=>({id:marker.project_id||marker.id,name:marker.name,entity_level:marker.entity_level,article_count:articleCount(marker),location:marker.city||marker.position_label,status:'상태 미확인',article_ids:marker.article_ids});
    function select(marker,notify=true){
      panels.forEach(panel=>panel.setSelected(marker.markers?.map(m=>m.id)||[marker.id]));renderDetail(marker);
      if(notify&&typeof onSelect==='function')onSelect(marker);
    }
    function region(country,name){
      if(name)regionNames.set(country,name);
      const markers=list.filter(marker=>marker.country===country),article_ids=[...aidSet(markers)];
      return {id:`map-region:${country}`,kind:'region',country,name:regionNames.get(country)||country,scope:scope==='all'?(country==='KR'?'domestic':'global-ai'):scope,markers,article_ids,article_count:article_ids.length,position_label:'국가 범위 선택 · 개별 사업 부지와 구분'};
    }
    function markerChoice(marker){
      const choice=button('',`${marker.name} 지도 표식 선택`,()=>select(marker));choice.classList.add('atlas-map-cluster-choice');choice.dataset.markerId=marker.id;
      const title=node('span','atlas-map-list-title',marker.name),meta=node('span','atlas-map-list-meta',`${marker.kind==='project'?'등록 사업':'지역 관측 · 사업 미확정'} · 기사 ${articleCount(marker)}개`);
      choice.append(title,meta);if(count(marker.unread_count))choice.append(node('span','atlas-map-item-new',`미확인 ${count(marker.unread_count)}`));return choice;
    }
    function showCluster(group){
      if(detailMode==='articles'){renderDetail({id:`map-cluster:${group.map(m=>m.id).sort().join('|')}`,kind:'cluster',name:`같은 위치의 표식 ${group.length}개`,markers:group,article_ids:[...aidSet(group)]});const choices=node('details','atlas-map-observations');choices.append(node('summary','',`표식 ${group.length}개 개별 선택`));const list=node('div','atlas-map-cluster-list');group.forEach(marker=>list.append(markerChoice(marker)));choices.append(list);detail.append(choices);return;}
      detail.replaceChildren(node('div','atlas-map-detail-eyebrow','OVERLAPPING LOCATIONS'),node('h3','atlas-map-detail-title',`같은 위치의 표식 ${group.length}개`),node('p','atlas-map-detail-summary',`관련 기사 ${aidSet(group).size}개 · 등록 사업과 사업 미확정 지역 관측을 선택하세요.`));
      const choices=node('div','atlas-map-cluster-list');[...group].sort((a,b)=>Number(b.kind==='project')-Number(a.kind==='project')||articleCount(b)-articleCount(a)).forEach(marker=>choices.append(markerChoice(marker)));detail.append(choices);
    }
    function renderArticles(values,marker){
      const articles=[...new Map((Array.isArray(values)?values:[]).filter(article=>article?.id).map(article=>[article.id,article])).values()].sort((a,b)=>String(b.published_at||'').localeCompare(String(a.published_at||''))||String(a.id).localeCompare(String(b.id))),pageSize=12;
      const section=node('section','atlas-map-article-browser');section.setAttribute('aria-label','선택 지역의 최신 기사 목록');detail.append(section);let page=1;
      const draw=()=>{section.replaceChildren();const pages=Math.max(1,Math.ceil(articles.length/pageSize)),start=(page-1)*pageSize,heading=node('div','atlas-map-detail-section-title');heading.append(node('h4','','최신 기사'),node('span','',`${articles.length}개 · 발행일 최신순`));section.append(heading);
        if(!articles.length){section.append(node('p','atlas-map-detail-empty','이 지역 조건의 근거 기사가 없습니다. 지도 표식을 선택하거나 검색 조건을 변경하세요.'));return;}
        const sources=node('div','atlas-map-source-list');articles.slice(start,start+pageSize).forEach(article=>{const item=node('article','atlas-map-source');item.dataset.articleId=article.id;let title=node('strong','',article.title||'제목 미확인');try{const url=new URL(article.url);if(['https:','http:'].includes(url.protocol)){title=node('a','',article.title||'제목 미확인');title.href=url.href;title.target='_blank';title.rel='noopener noreferrer';}}catch{}item.append(title,node('small','',[article.publisher||'출처 미확인',String(article.published_at||'발행일 미확인').slice(0,10),article.is_new?'NEW · 미확인':''].filter(Boolean).join(' · ')));if(article.summary){const summary=Array.isArray(article.summary)?article.summary.map(x=>typeof x==='object'?x.text||'':x).join(' '):typeof article.summary==='object'?article.summary.text||'':String(article.summary);if(summary)item.append(node('p','atlas-map-source-summary',summary));}sources.append(item);});section.append(sources);
        const pagination=node('nav','atlas-map-pagination');pagination.setAttribute('aria-label','지도 기사 목록 페이지');const previous=button('이전','지도 기사 이전 페이지',()=>{page--;draw();}),next=button('다음','지도 기사 다음 페이지',()=>{page++;draw();});previous.disabled=page===1;next.disabled=page===pages;pagination.append(previous,node('span','',`${page} / ${pages} · ${start+1}–${Math.min(start+pageSize,articles.length)}개`),next);section.append(pagination);
        if(typeof onArticlesSelect==='function'){const selected={...(marker||{}),id:marker?.id||'map-visible-articles',name:marker?.name||'현재 지역 조건 전체 기사',article_ids:articles.map(article=>article.id),article_count:articles.length};const open=button(`기사 ${articles.length}개 전체 보기 ↗`,'현재 지도 기사 전체 근거 열기',()=>onArticlesSelect(selected));open.classList.add('atlas-map-articles-open');section.append(open);}
      };draw();
    }
    function renderDetail(marker){
      detail.replaceChildren();detail.dataset.selectedMarker=marker?.id||'';
      const selected=marker?(marker.markers||[marker]):list,ids=aidSet(selected),linked=list.filter(item=>item.kind==='project'&&item.article_ids?.some(aid=>ids.has(aid)));
      let description={};
      if((marker||detailMode==='articles')&&typeof describeMarker==='function'){try{description=describeMarker(marker)||{};}catch{description={summary:'상세 연결 정보를 표시하지 못했습니다. 표식과 근거 기사 목록에서 다시 확인하세요.'};}}
      const projects=Array.isArray(description.projects)?description.projects:uniqueProjects(marker?linked:list).map(registeredProject);
      const observations=selected.filter(item=>item.kind==='observation'),registered=projects.filter(project=>!project.is_candidate),candidates=projects.filter(project=>project.is_candidate);
      detail.append(node('div','atlas-map-detail-eyebrow',marker?'SELECTED LOCATION':detailMode==='articles'?'REGIONAL ARTICLE INTELLIGENCE':'PROJECT INTELLIGENCE'),node('h3','atlas-map-detail-title',marker?.name||(detailMode==='articles'?'지역별 최신 기사':'지도에서 사업을 탐색하세요')));
      const stats=node('div','atlas-map-detail-stats');[[registered.length,'등록 사업'],[count(description.article_count??(marker?articleCount(marker):ids.size)),'관련 기사'],[count(description.pending_count??observations.length),description.pending_count===undefined?'지역 관측':'식별 대기']].forEach(([value,label])=>{const item=node('div');item.append(node('strong','',value.toLocaleString()),node('span','',label));stats.append(item);});detail.append(stats);
      if(marker)detail.append(node('p','atlas-map-precision',marker.position_label||'위치 미배치 · 위치 정밀도 미확인'));
      if(description.summary){const lines=Array.isArray(description.summary)?description.summary:[description.summary];lines.filter(Boolean).forEach(line=>detail.append(node('p','atlas-map-detail-summary',String(line))));}
      else detail.append(node('p','atlas-map-detail-summary',marker?'선택한 근거 기사에 연결된 사업과 참여 기업을 확인합니다.':'도시 표식이나 관측 국가를 누르면 사업·기업·최신 근거를 이곳에서 함께 확인합니다.'));
      if(detailMode==='articles')renderArticles(description.articles||[],marker);
      const context=detailMode==='articles'?node('details','atlas-map-context'):detail;if(detailMode==='articles'){context.append(node('summary','',`연결 사업·기업 보기 · ${projects.length}개 사업·후보`));detail.append(context);}
      const projectHeading=node('div','atlas-map-detail-section-title');projectHeading.append(node('h4','',candidates.length?'연결 사업·기사 후보':'등록 사업'),node('span','',candidates.length?`등록 ${registered.length}개 · 후보 ${candidates.length}묶음`:`${registered.length}개`));context.append(projectHeading);
      const projectList=node('div','atlas-map-project-list');
      projects.forEach(project=>{
        const card=node('article','atlas-map-project-card');card.dataset.projectId=project.id||'';card.dataset.projectBasis=project.is_candidate?'article_name_candidate':'registered';
        const name=node('strong','atlas-map-project-name',project.name||project.id||'사업명 미확인');card.append(name);if(project.is_candidate)card.append(node('small','atlas-map-unknown','기사 명칭 후보 · 등록 사업과 구분'));
        const meta=node('p','atlas-map-project-meta'),level={program:'프로그램',site:'사이트',phase:'단계'}[project.entity_level];
        meta.textContent=[project.status||'상태 미확인',level,project.location||'위치 미확인',`근거 기사 ${articleCount(project)}개`].filter(Boolean).join(' · ');card.append(meta);
        if(project.summary)card.append(node('p','atlas-map-project-summary',Array.isArray(project.summary)?project.summary.join(' '):String(project.summary)));
        const roles=Array.isArray(project.roles)?project.roles:[];
        if(roles.length){const tags=node('div','atlas-map-project-roles');roles.forEach(role=>tags.append(node('span','',typeof role==='string'?role:[role.role,role.name].filter(Boolean).join(' · '))));card.append(tags);}
        else card.append(node('small','atlas-map-unknown','참여 기업 역할 · 미확인'));
        if(typeof onProjectSelect==='function'&&project.id){const open=button('사업 중심 관계도 ↗',`${project.name||project.id} 사업 중심 관계도 열기`,()=>onProjectSelect(project,marker));open.classList.add('atlas-map-project-open');card.append(open);}projectList.append(card);
      });
      if(!projects.length)projectList.append(node('p','atlas-map-detail-empty','이 선택에 연결된 등록 사업은 없습니다. 지역 관측 기사는 사업 식별 대기로 구분해 확인하세요.'));context.append(projectList);
      if(Array.isArray(description.companies)&&description.companies.length){context.append(node('h4','atlas-map-detail-subtitle','관련 기업'));const companies=node('div','atlas-map-company-list');description.companies.forEach(company=>companies.append(node('span','',[company.name||company.id||'기업명 미확인',company.role].filter(Boolean).join(' · '))));context.append(companies);}
      if(detailMode!=='articles')renderArticles(description.articles||[],marker);
      if(detailMode!=='articles'&&marker&&typeof onArticlesSelect==='function'){const articlesButton=button(`선택 근거 기사 ${articleCount(marker)}개 보기 ↗`,'선택한 지도 표식의 근거 기사 열기',()=>onArticlesSelect(marker));articlesButton.classList.add('atlas-map-articles-open');detail.append(articlesButton);}
      if(observations.length){const details=node('details','atlas-map-observations');details.open=!marker;details.append(node('summary','',`지역 관측 ${observations.length}개 · 사업 미확정`));const choices=node('div','atlas-map-cluster-list');observations.forEach(item=>choices.append(markerChoice(item)));details.append(choices);detail.append(details);}
      if(marker){const resetButton=button('지도 전체 목록으로','선택을 해제하고 지도 전체 사업 목록 보기',()=>{panels.forEach(panel=>panel.setSelected([]));renderDetail(null);if(typeof onClearSelection==='function')onClearSelection();});resetButton.classList.add('atlas-map-detail-reset');detail.append(resetButton);}
    }
    const key=viewKey||`${mode}:${scope}:${positionPolicy}`;
    const panelOptions={onSelect:select,onGroupSelect:showCluster,onCountrySelect:(country,name)=>select(region(country,name)),selectedMarkerId,viewKey:key};
    const korea=['all','kr-dc','kr-ai'].includes(scope)?mapPanel({kind:'korea',title:'대한민국 · 국내 DC / 국내 AIDC',markers:domestic,...panelOptions,inset:mode==='world-inset'&&scope==='all'}):null;
    const world=['all','global-ai'].includes(scope)?mapPanel({kind:'world',title:'세계 · 해외 AIDC',markers:foreign,...panelOptions}):null;
    if(korea)panels.push(korea);if(world)panels.push(world);
    if(mode==='split'){if(korea)layout.append(korea.element);if(world)layout.append(world.element);}else{if(world)layout.append(world.element);if(korea)layout.append(korea.element);}
    if(!panels.length)layout.append(node('p','atlas-map-policy-needed','분류 미확인 자료는 위치와 사업 범위를 확정할 근거가 부족해 지도에 배치하지 않습니다. 아래 미배치 자료에서 확인하세요.'));root.append(body);
    let selected=list.concat(unlocated).find(item=>item.id===selectedMarkerId);
    if(!selected&&String(selectedMarkerId||'').startsWith('map-region:')){const country=selectedMarkerId.slice('map-region:'.length);if(list.some(item=>item.country===country))selected=region(country);}
    if(selected)select(selected,false);else renderDetail(null);
    const legend=node('div','atlas-map-legend');Object.entries(COLORS).forEach(([scope,color])=>{const item=node('span');item.append(node('i'));item.firstChild.style.background=color;item.append(document.createTextNode({'kr-dc':'국내 DC','kr-ai':'국내 AIDC','global-ai':'해외 AIDC'}[scope]));legend.append(item);});
    legend.append(node('span','','■ 사업 · ● 기사 지역 관측'),node('span','',positionPolicy==='exact_only'?'근거가 확인된 부지 좌표만 표시':'실선: 확인 좌표 / 점선: 도시·국가 대표점 · 부지 아님'));root.append(legend);
    const mappedIds=aidSet(list),unmappedIds=new Set(unlocated.flatMap(item=>item.article_ids||[]).filter(id=>!mappedIds.has(id))),details=node('details','atlas-map-unlocated');details.append(node('summary','',`지도 미배치 자료 ${unlocated.length}개 · 미배치 기사 ${unmappedIds.size}개`));
    details.append(node('p','','위치 근거가 없거나 표시 정책으로 배치하지 않은 자료입니다. 동일 기사가 여러 사업·관측에 연결될 수 있습니다.'));
    const missing=node('div','atlas-map-unlocated-list');unlocated.forEach(item=>{const b=button(`${item.name} · 기사 ${item.article_count||item.article_ids?.length||0}개`,`${item.name} 미배치 자료 선택`,()=>select(item));b.classList.add('atlas-map-unlocated-item');missing.append(b);});details.append(missing);root.append(details);
    const attribution=node('p','atlas-map-attribution');const credit=node('a','','Made with Natural Earth · public domain');credit.href='https://www.naturalearthdata.com/about/terms-of-use/';credit.target='_blank';credit.rel='noopener noreferrer';attribution.append(credit,document.createTextNode(' · 오프라인 국가 경계 · 사업 부지/영토 판정용 아님'));root.append(attribution);
    root.ready=Promise.all(panels.map(panel=>panel.ready)).then(()=>{root.dataset.mapStatus=panels.some(panel=>panel.element.dataset.mapStatus==='error')?'error':'ready';return root;});
    root.atlasMap={focus(id){panels.forEach(panel=>panel.focus(id));},destroy(){panels.forEach(panel=>panel.destroy());}};
    return root;
  }
  window.AtlasMap=Object.freeze({create});
})();
