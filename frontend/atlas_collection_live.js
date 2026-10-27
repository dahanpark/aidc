(function(global){
  'use strict';
  function failureMessage(job={}){
    if(job.error_code==='tls_certificate'){
      if(job.error_transport==='windows_system')return 'Windows 기본 인증서 검증도 실패했습니다. PC 날짜·시간과 회사 인증서 신뢰 구성을 확인하세요. 브라우저 RSS 연결과 프로그램 연결 결과는 다를 수 있습니다.';
      if(job.error_transport==='windows_unavailable')return 'Windows 인증서 재시도 경로를 실행할 수 없습니다. 최신 실행본과 회사 PowerShell 실행 정책을 확인하세요.';
      return 'HTTPS 인증서 검증 실패로 중지했습니다. 최신 실행본의 사내망 수집 연결 진단에서 Windows 경로 사용 여부를 확인하세요.';
    }
    return '연속 연결 오류로 일시 중지했습니다. 네트워크 진단 후 남은 구간을 재개하세요.';
  }
  function controlState(busy,jobs=[],live){
    if(busy)return {disabled:true,label:'수집 시작 확인 중…'};
    if(live?.tracked){
      if(live.active)return {disabled:true,label:live.phase==='running'?'기사 수집 중…':'수집 상태 확인 중…'};
      return {disabled:false,label:'기간 기사 수집 ↻'};
    }
    const running=jobs.some(j=>['running','queued'].includes(j.status));
    return {disabled:running,label:running?'기사 수집 중…':'기간 기사 수집 ↻'};
  }
  function mount(root,opts={}){
    let active=false,target=null,timer=null,controller=null,sequence=0,tracked=false,phase='idle';
    const getState=()=>({active,tracked,phase});
    function notify(){opts.onState?.(getState());}
    const fetcher=opts.fetch||global.fetch.bind(global),later=opts.setTimeout||global.setTimeout.bind(global),cancel=opts.clearTimeout||global.clearTimeout.bind(global);
    function stop(message){active=false;phase='idle';sequence++;if(timer)cancel(timer);controller?.abort();if(message){root.hidden=false;root.textContent=message;}notify();}
    async function refresh(){
      if(!active)return;const seq=++sequence;controller?.abort();controller=new AbortController();
      const current=controller,limit=later(()=>current.abort(),8000);
      try{
        const r=await fetcher('/api/collection/status',{method:'GET',cache:'no-store',signal:controller.signal});
        if(!r.ok){if(r.status===404){stop('실행 중인 백엔드가 구버전입니다. 최신 파일과 실제 실행 서버 적용 상태를 확인하세요.');return;}throw Error('status');}
        const envelope=await r.json();if(seq!==sequence||!active)return;
        const d=envelope.data||envelope,j=(d.jobs||[]).find(j=>j.id===target),p=d.progress||{};
        const stage=(!target||p.job_id===target)?p.stage:null;
        const labels={requesting:'공개 RSS 연결·응답 대기',parsing:'응답 기사 검토',saving:'기사·근거 JSON 저장',source_error:'출처 연결 실패 · 다음 구간 확인',completed:'조회 작업 종료',partial:'일부 수집 · 재개 가능',failed:'수집 실패',cancelled:'사용자 중단'};
        phase=j&&['running','queued'].includes(j.status)&&d.worker_alive?'running':'checking';notify();
        root.hidden=false;root.textContent=`${labels[stage]||'수집 준비·저장소 확인 중'}${p.source_name?' · '+p.source_name:''} · 신규 ${j?.new_articles??p.new_articles??0}건 · 요청 ${j?.request_count??p.request_count??0}회 · RSS 요청 전체 제한 ${p.request_deadline_seconds||20}초`;
        if(j&&(!d.worker_alive&&!d.collection_lock_held||!['running','queued'].includes(j.status))){
          const message=j.stop_reason==='network_blocked'?failureMessage(j):j.worker_missing?'진행 상태만 남았고 실제 작업이 없습니다. 수집 진단에서 원래 조건으로 재개하세요.':labels[j.status]||j.status;
          root.textContent=`${message} · 신규 ${j.new_articles||0}건 · 오류 ${j.error_code||'없음'}`;
          active=false;phase='finished';notify();opts.onFinish?.(d);return;
        }
      }catch(error){if(seq===sequence&&active){phase='checking';notify();root.hidden=false;root.textContent='진행 상태 응답이 지연됩니다. 수집 요청을 다시 누르지 말고 네트워크·저장소 진단을 확인하세요.';}}
      finally{cancel(limit);if(seq===sequence&&active)timer=later(refresh,2000);}
    }
    root.setAttribute('role','status');root.setAttribute('aria-live','polite');root.hidden=true;
    return {start(id=null){stop();target=id;tracked=true;active=true;phase='checking';notify();refresh();},setJob(id){target=id;},stop,refresh,isActive:()=>active,getState};
  }
  global.AtlasCollectionLive={mount,controlState,failureMessage};if(typeof module!=='undefined'&&module.exports)module.exports=global.AtlasCollectionLive;
})(typeof window!=='undefined'?window:globalThis);
