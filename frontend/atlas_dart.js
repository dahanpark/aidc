'use strict';
((scope)=>{
  function reportPrompt(company,report){
    return `DART 스킬로 ${JSON.stringify(company.name)}의 재무·공시 리포트를 작성해 주세요.\n`+
      (report?`확인한 공시 법인: ${report.corp_name}, corp_code ${report.corp_code}. 참고 조회: ${report.year} ${report.report_label}, ${report.fs_div}.\n`:'먼저 정확한 공시 법인을 식별하고 동명이인·계열사·상장 모회사를 대신 선택하지 마세요.\n')+
      '현재 실제 제출된 보고서 기간을 먼저 확인하고 연결/별도·누적/당기·단위·출처·조회일을 구분하세요. 회사 전체 실적을 DC/AIDC 부문 실적으로 해석하지 마세요. 기존 DART 스킬의 조립·숫자·출처 검증을 통과한 보고서를 생성하세요. 상장 여부나 데이터가 불명확하면 보류하세요. ATLAS의 사내 메모·링크·키는 읽거나 전송하지 마세요.';
  }
  function mount(root,company,opts){
    const doc=root.ownerDocument||document;
    const el=(tag,value)=>{const n=doc.createElement(tag);if(value!==undefined)n.textContent=value;return n;};
    const button=(label,action)=>{const b=el('button',label);b.type='button';b.className='button small';b.addEventListener('click',action);return b;};
    const input=(label,type='text')=>{const l=el('label',label),n=el('input');n.type=type;l.append(n);return [l,n];};
    const select=(label,values)=>{const l=el('label',label),n=el('select');values.forEach(([value,name])=>{const o=el('option',name);o.value=value;n.append(o);});l.append(n);return[l,n];};
    const panel=el('section');panel.className='panel company-dart';panel.setAttribute('aria-label','DART 재무·공시');
    const title=el('h2','DART · 재무·공시'),status=el('p','선택 기업의 공시 법인을 확인하여 기간별 재무 근거를 연결합니다.'),body=el('div');status.setAttribute('role','status');
    panel.append(title,status);root.append(panel);
    let ws=null,preview=null,busy=false,query=company.name;
    async function run(action){if(busy)return;busy=true;panel.setAttribute('aria-busy','true');try{await action();}catch(e){status.textContent=e.message||'DART 조회에 실패했습니다.';}finally{busy=false;panel.setAttribute('aria-busy','false');}}
    function showReport(report,target){
      target.append(el('h3',`${report.corp_name} · ${report.year} ${report.report_label} · ${report.fs_div==='CFS'?'연결':'별도'} · 고유번호 ${report.corp_code}`));
      target.append(el('p',`조회 ${report.fetched_at} · 선택 기간 공시입니다. 최신 제출 기간을 자동 확정하지 않습니다.`));
      const table=el('table');table.className='data-table';const head=el('tr');['계정','공시 기간 명칭','당기 공시 금액','당기 누적 금액','통화·원문'].forEach(x=>head.append(el('th',x)));table.append(head);
      report.accounts.forEach(a=>{const row=el('tr');[a.account_nm,a.thstrm_nm,a.thstrm_amount||'미제공',a.thstrm_add_amount||'미제공'].forEach(x=>row.append(el('td',x)));const cell=el('td'),link=el('a',`${a.currency||'통화 미확인'} · 공시 원문 ↗`);link.href=a.source_url;link.target='_blank';link.rel='noopener noreferrer';cell.append(link);row.append(cell);table.append(row);});
      const scroll=el('div');scroll.className='table-scroll';scroll.append(table);target.append(scroll);
    }
    function draw(){
      body.replaceChildren();preview=null;
      body.append(el('p',ws.note));
      const settings=el('details'),summary=el('summary','DART 연결·조회 설정');settings.append(summary);
      settings.append(el('p',ws.credential_present?'이 PC의 DART 인증키 등록됨 · 조회 시 인증 확인':'DART 인증키가 없습니다. AI 키와 별개입니다.'));
      const [keyLabel,key]=input('이 PC의 DART 인증키 (Windows 보안 저장소)','password');key.autocomplete='new-password';
      settings.append(keyLabel,button('DART 키 등록',()=>run(async()=>{const raw=key.value;key.value='';await opts.api('/api/dart/connect',{api_key:raw});status.textContent='DART 키 등록 완료. 실제 인증은 조회 결과로 확인합니다.';await load();})),button('저장한 DART 키 삭제',()=>run(async()=>{await opts.api('/api/dart/disconnect',{});await load();status.textContent='이 앱의 저장 키를 삭제했습니다. DART_API_KEY 환경변수는 별도 관리됩니다.';})));
      settings.append(el('p','환경변수 DART_API_KEY도 지원합니다. 키를 JSON·Git·채팅에 저장하지 않습니다. 기본 조회는 AI 토큰 0, 공식 API 최대 2회이며 자동 재시도하지 않습니다.'));
      const recent=ws.reports[0];
      const [corpLabel,corp]=input('DART 법인 고유번호 (8자리)');corp.value=recent?.corp_code||'';corp.maxLength=8;
      const [searchLabel,search]=input('공시 법인명·별칭 찾기');search.value=query;
      settings.append(searchLabel,button('기업 후보 찾기',()=>run(async()=>{query=search.value.trim();await load();status.textContent='법인 후보 목록입니다. 같은 법인인지 공식 조회로 확인하세요.';})),el('p',`${ws.registry_as_of||'시점 미확인'} · ${ws.registry_note||'공식 법인 고유번호로 조회하세요.'}`));
      const [candidateLabel,candidate]=select('기업 후보 선택 (자동 연결하지 않음)',[['','직접 입력·선택 대기'],...(ws.candidates||[]).map(c=>[c.corp_code,`${c.name} · ${c.stock_code} · ${c.corp_code}`])]);
      candidate.addEventListener('change',()=>{if(candidate.value)corp.value=candidate.value;});settings.append(candidateLabel);
      const [yearLabel,year]=input('사업연도','number');year.min='2015';year.max=String(new Date().getFullYear());year.value=recent?.year||String(new Date().getFullYear()-1);
      const [periodLabel,period]=select('보고서',[['11011','사업보고서'],['11013','1분기'],['11012','반기'],['11014','3분기']]);period.value=recent?.report_code||'11011';
      const [basisLabel,basis]=select('재무제표',[['CFS','연결'],['OFS','별도']]);basis.value=recent?.fs_div||'CFS';
      const fields=el('div');fields.className='dart-fields';fields.append(corpLabel,yearLabel,periodLabel,basisLabel);settings.append(fields);
      const prepared=el('div');
      settings.append(button('공식 자료 조회 · 2회 이내',()=>run(async()=>{status.textContent='DART 공식 자료 조회 중… 자동 재시도하지 않습니다.';preview=(await opts.api('/api/dart/preview',{company_id:company.id,corp_code:corp.value.trim(),year:year.value,report_code:period.value,fs_div:basis.value})).data;prepared.replaceChildren();showReport(preview.report,prepared);const confirmation=el('label'),check=el('input');check.type='checkbox';confirmation.append(check,doc.createTextNode(` ${company.name}와 ${preview.report.corp_name}는 동일 법인입니다. 모회사·자회사 대체가 아닙니다.`));prepared.append(confirmation,button('동일 법인 확인 후 저장',()=>run(async()=>{if(!check.checked)throw Error('공시 법인과 선택 기업의 동일성을 확인하세요.');await opts.api('/api/dart/save',{preview_id:preview.preview_id,confirm_same_legal_entity:true});await load();status.textContent='DART 재무·공시 근거를 저장했습니다. 기사·관계·확인 상태는 유지합니다.';})));status.textContent='조회 완료 · 저장 전 법인 확인이 필요합니다.';})),prepared);
      body.append(settings);
      if(recent){showReport(recent,body);const clear=el('details');clear.append(el('summary','법인 연결 정정 · 원본 보존'));const label=el('label'),check=el('input');check.type='checkbox';label.append(check,doc.createTextNode(' 현재 표시한 공시 근거의 연결을 해제합니다. 원본은 보존합니다.'));clear.append(label,button('선택 공시 연결 해제',()=>run(async()=>{if(!check.checked)throw Error('연결 해제 대상을 확인하세요.');await opts.api('/api/dart/withdraw',{company_id:company.id,report_id:recent.id,confirm_withdraw:true});await load();status.textContent='선택 공시 연결을 해제하고 원본을 보존했습니다.';})));body.append(clear);}else body.append(el('p','저장한 DART 자료가 없습니다. 연결·조회 설정에서 법인·기간을 지정하세요. 미제공 수치를 0으로 채우지 않습니다.'));
      if(ws.reports.length>1){const history=el('details');history.append(el('summary',`이전 저장 근거 ${ws.reports.length-1}개`));ws.reports.slice(1).forEach(r=>showReport(r,history));body.append(history);}
      if(ws.withdrawn_reports?.length){const withdrawn=el('details');withdrawn.append(el('summary',`연결 해제한 원본 ${ws.withdrawn_reports.length}개`));ws.withdrawn_reports.forEach(r=>showReport(r,withdrawn));body.append(withdrawn);}
      const codex=el('details');codex.append(el('summary','기존 Codex DART 상세 분석으로 이어가기'));const prompt=el('textarea');prompt.readOnly=true;prompt.rows=6;prompt.value=reportPrompt(company,recent);prompt.setAttribute('aria-label','Codex DART 분석 지시문');codex.append(el('p','아래 지시문을 Codex에 전달하면 설치된 DART 스킬의 전체 리포트 작업으로 이어갈 수 있습니다. 이 버튼은 AI를 실행하거나 기존 보고서를 자동 가져오지 않습니다.'),prompt,button('지시문 선택',()=>{prompt.focus();prompt.select();}));body.append(codex);
    }
    async function load(){ws=(await opts.api('/api/dart/company?company_id='+encodeURIComponent(company.id)+'&q='+encodeURIComponent(query),undefined,'GET')).data;draw();}
    panel.append(button('DART 자료 열기·새로고침',()=>run(async()=>{await load();status.textContent='저장된 재무·공시 자료입니다. 조회만으로 읽음 처리하지 않습니다.';})),body);
    return panel;
  }
  scope.AtlasDart={mount,reportPrompt};
  if(typeof module!=='undefined')module.exports=scope.AtlasDart;
})(typeof window!=='undefined'?window:globalThis);
