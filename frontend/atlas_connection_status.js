(function (root) {
  'use strict';
  function mount(host, opts = {}) {
    const doc = host.ownerDocument || root.document;
    const status = doc.createElement('p'); status.className = 'muted'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const check = doc.createElement('button'); check.type = 'button'; check.className = 'button small'; check.textContent = '등록 상태 확인';
    host.append(status, check);
    const clock = opts.clock || Date.now, schedule = opts.schedule || setInterval, cancel = opts.cancel || clearInterval;
    let timer = null, started = 0, busy = false, confirmed = false, disposed = false;
    async function inspect() {
      if (check.disabled || disposed) return;
      check.disabled = true;
      try {
        const result = await opts.check();
        if (disposed) return;
        status.textContent = result.connected ? '서버에 사용 가능한 AI 연결이 확인됐습니다. 기존 연결일 수 있어 이번에 입력한 키의 저장 성공을 뜻하지는 않습니다. 기사 분석은 별도 실행합니다.' :
          result.credential_present ? '보관된 키가 있으나 AI 연결은 완료되지 않았습니다. 모델 선택·연결 상태를 확인하세요.' :
          result.credential_error ? 'Windows 보안 저장소 접근 상태를 확인해야 합니다. 키가 틀렸다고 판단하지 마세요.' :
          '아직 등록 완료를 확인하지 못했습니다. 인증·저장 요청이 진행 중일 수 있으므로 저장을 반복하지 마세요.';
      } catch (_) {
        if (!disposed) status.textContent = '서버 상태 조회가 지연되거나 실패했습니다. 키 오류로 확정할 수 없습니다. 저장을 반복하지 마세요.';
      } finally { if (!disposed) check.disabled = false; }
    }
    check.addEventListener('click', inspect);
    function update() {
      if (!busy || disposed) return;
      const dialog = host.closest && host.closest('dialog');
      if (dialog && !dialog.open) { stop(); return; }
      const seconds = Math.max(0, Math.floor((clock() - started) / 1000));
      status.textContent = confirmed ? '키 인증·설정 저장 완료 · 화면을 갱신하는 중입니다.' :
        `키 인증 및 설정 저장 응답 대기 · ${seconds}초. ` + (seconds >= 60 ? '응답이 지연되고 있습니다. 창을 닫아도 서버 작업은 취소되지 않습니다. 등록 상태를 확인하고 중복 저장하지 마세요.' :
          seconds >= 10 ? '모델 인증 또는 JSON 저장이 지연될 수 있습니다. 중복 저장하지 마세요.' : '모델 목록 조회·Windows 보안 저장·JSON 저장을 기다립니다. 기사 분석은 실행하지 않습니다.');
    }
    function stop() { busy = false; if (timer !== null) cancel(timer); timer = null; }
    return {
      start() { stop(); disposed = false; busy = true; confirmed = false; started = clock(); update(); timer = schedule(update, 1000); },
      confirmed() { confirmed = true; update(); },
      stop,
      destroy() { stop(); disposed = true; },
      inspect
    };
  }
  root.AtlasConnectionStatus = {mount};
  if (typeof module !== 'undefined' && module.exports) module.exports = {mount};
})(typeof window !== 'undefined' ? window : globalThis);
