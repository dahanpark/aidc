/* One-shot submit; polling/reconnect are GET only. No retry of inference. */
(function () {
  'use strict';
  const previews = new Map();
  const terminal = new Set(['completed', 'cached', 'failed', 'blocked', 'uncertain']);
  const labels = {queued:'대기',submitted:'저장·분석 진행 중',completed:'완료',cached:'기존 결과 재사용',failed:'실패',blocked:'전송 전 중단',uncertain:'완료 여부 확인 필요'};
  function selection(payload) { const clean={}; ['article_ids','board_id','company_id','row_ids'].forEach(k=>{if(payload[k]!==undefined)clean[k]=payload[k];}); return clean; }
  function key(task,payload) {return JSON.stringify([task,selection(payload)]);}
  function data(response) {return response.data||response;}
  function message(record) {return `AI 작업 ${record.id} · ${labels[record.status]||record.status} · 자동 재전송 없음`;}
  function progress(record) {const box=document.getElementById('aiJobStatus');if(box){box.hidden=false;box.textContent=message(record);}}
  async function preview(api,task,payload) {
    let sample;
    try {sample=data(await api('/api/ai/jobs/preview',{task,selection:selection(payload)}));}
    catch(error) {if(/지원하지 않는 작업|API 경로가 없습니다|404/.test(error.message||''))throw Error('현재 실행 서버에는 작업형 AI가 적용되지 않았습니다. 수집을 보존하고 정상 종료 후 최신 CMD로 재실행하세요. AI 호출은 하지 않았습니다.');throw error;}
    previews.set(key(task,payload),sample); return sample;
  }
  async function status(api,id) {return data(await api('/api/ai/jobs?job_id='+encodeURIComponent(id),undefined,'GET'));}
  async function wait(api,id) {
    for (;;) {
      const record=await status(api,id); progress(record);
      if(terminal.has(record.status)) {
        if(!['completed','cached'].includes(record.status))throw Error(`${message(record)}. 진행·결과에서 기존 기록을 확인하세요.`);
        const result=record.run_id?data(await api('/api/ai/run?run_id='+encodeURIComponent(record.run_id),undefined,'GET')):null;
        return {...record,job_id:record.id,result,run_id:record.run_id};
      }
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
  }
  async function run(api,task,payload) {
    const sample=previews.get(key(task,payload));
    if(payload.consent_public_metadata!==true||!sample)throw Error('전송 표본을 미리보고 API 사용량에 동의하세요.');
    let record;
    try {record=data(await api('/api/ai/jobs/submit',{preview_id:sample.preview_id,consent_digest:sample.consent_digest,consent_public_metadata:true}));}
    catch(error) {throw Error((error.message||'시작 응답 확인 실패')+' · AI 작업 진행·결과를 먼저 확인하세요. 자동 재전송하지 않습니다.');}
    progress(record);return wait(api,record.id);
  }
  async function mount(root,api,openRun) {
    const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
    root.replaceChildren(el('p','화면 재접속·상태 조회는 AI를 실행하지 않습니다. 실패·확인 필요 작업은 자동 재호출하지 않습니다.'));
    const refresh=el('button','진행 상태 새로고침'), rows=el('div'); refresh.className='button';root.append(refresh,rows);
    async function load() {
      refresh.disabled=true;
      try {
        const response=data(await api('/api/ai/jobs',undefined,'GET')),records=response.jobs||[];
        if(response.issue)throw Error(response.issue.message);
        rows.replaceChildren();
        if(!records.length)rows.append(el('p','저장된 작업이 없습니다. 미리보기와 동의 후 분석을 시작하세요.'));
        records.forEach(record=>{
          const row=el('section');row.className='callout';row.append(el('p',message(record)),el('p',`${record.task} · ${record.provider} / ${record.model} · 출력 상한 ${record.max_output_tokens}토큰`));
          if(record.run_id) {const b=el('button','저장 결과 확인');b.className='button';b.onclick=async()=>{try{const r=data(await api('/api/ai/run?run_id='+encodeURIComponent(record.run_id),undefined,'GET'));openRun(r);}catch(e){row.append(el('p',e.message));}};row.append(b);}
          rows.append(row);
        });
      }catch(e){rows.replaceChildren(el('p',e.message||'작업 조회 실패'));}finally{refresh.disabled=false;}
    }
    refresh.onclick=load;await load();
  }
  window.AtlasAIJobs={preview,run,status,mount,wait};
})();
