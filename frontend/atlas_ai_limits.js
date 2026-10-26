(function (global) {
  'use strict';
  const fields = [
    ['max_articles_per_run', '한 번에 선택할 공개 기사', 3, 1, 20],
    ['daily_call_limit', '일일 호출 상한 (실패 포함)', 10, 1, 500],
    ['max_input_chars', '총 입력 문자 상한', 8000, 4000, 40000],
    ['max_output_tokens', '출력 토큰 상한', 1200, 300, 4000],
    ['article_text_chars', '기사별 문자 상한', 1200, 200, 2400]
  ];
  const tasks = [['extract', '공개 기사 근거 후보 추출'], ['compare', '유사 사업 비교'], ['briefing', '최신 동향 요약'], ['classify', '미분류 근거 점검'], ['strategy', '전략표 선택 셀 요약']];
  function mount(root, options = {}) {
    const doc = root.ownerDocument || global.document;
    let profile = options.profile || {}, busy = false, error = '', notice = '';
    const initial = profile.limits || profile;
    let values = Object.fromEntries(fields.map(([key, , fallback]) => [key, initial[key] ?? fallback]));
    let selected = new Set(Array.isArray(initial.enabled_tasks) ? initial.enabled_tasks : tasks.map(([key]) => key));
    function el(tag, text) {const node = doc.createElement(tag); if (text !== undefined) node.textContent = String(text); return node;}
    function render() {
      root.replaceChildren(); root.className = 'atlas-ai-limits'; root.setAttribute('aria-busy', String(busy));
      root.append(el('h3', 'AI 역할과 사용량 한도'));
      root.append(el('h4', 'AI 미연결 상태의 역할'), el('p', '기사 수집·조회·검색·수동 분류·근거 확인을 유지합니다. 개인 API 키가 연결되지 않은 상태에서는 AI 분석을 실행하지 않습니다.'));
      root.append(el('h4', '개인 AI 연결 후 명시 실행하는 역할'));
      const descriptions = el('ul');
      ['미분류: 국내외와 AI 관련성을 명시 근거로 점검하며 근거가 없으면 식별 보류합니다.', '유사 사업: 명칭·지역·단계 충돌을 비교하여 동일 사업 후보를 검토합니다. 자동 원본 병합은 하지 않습니다.', '전략표: 회사 1개·기사 최대 3개·행 최대 3개를 선택하고 셀당 근거 기반 최대 3개 말머리 단락으로 요약합니다.', '최신 동향: 선택한 공개 기사 표본에 대한 해석이며 전체 시장 통계나 사실 확정을 뜻하지 않습니다.'].forEach(text => descriptions.append(el('li', text))); root.append(descriptions);
      root.append(el('p', '입력 문자는 정확한 토큰 수나 금액이 아닙니다. 출력 토큰 상한에는 제공사에 따라 reasoning 토큰이 포함될 수 있습니다. 실패한 호출도 일일 상한에 포함하며 자동 재시도하지 않습니다. 실제 전송 표본과 사용량 발생에 동의한 뒤 실행합니다.'));
      if (error) {const alert = el('p', error); alert.setAttribute('role', 'alert'); root.append(alert);}
      const status = el('p', busy ? '저장 중…' : notice); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); root.append(status);
      const form = el('form'), inputs = {};
      fields.forEach(([key, label, fallback, min, max]) => {
        const wrap = el('label'), name = el('span', label + ' (' + min + '–' + max + ') '), input = el('input');
        input.type = 'number'; input.name = key; input.value = values[key]; input.min = String(min); input.max = String(max); input.step = '1'; input.required = true; input.disabled = busy;
        input.setAttribute('aria-label', label); input.addEventListener('input', () => {values[key] = input.value;});
        wrap.append(name, input); form.append(wrap, el('br')); inputs[key] = input;
      });
      const taskFields = el('fieldset'); taskFields.append(el('legend', '허용 분석 작업 (최소 1개)'));
      tasks.forEach(([key, label]) => {const wrap = el('label'), input = el('input'); input.type = 'checkbox'; input.name = 'enabled_tasks'; input.value = key; input.checked = selected.has(key); input.disabled = busy; input.addEventListener('change', () => {if (input.checked) selected.add(key); else selected.delete(key);}); wrap.append(input, el('span', label)); taskFields.append(wrap, el('br'));}); form.append(taskFields);
      const submit = el('button', 'AI 한도 저장'); submit.type = 'submit'; submit.disabled = busy || !options.save; form.append(submit);
      form.addEventListener('submit', async event => {
        event.preventDefault(); if (busy || !options.save) return;
        error = ''; notice = '';
        const payload = {};
        for (const [key, label, , min, max] of fields) {
          const value = Number(values[key]);
          if (!String(values[key]).trim() || !Number.isInteger(value) || value < min || value > max) {error = label + '은 ' + min + '–' + max + ' 범위의 정수여야 합니다.'; render(); return;}
          payload[key] = value;
        }
        payload.enabled_tasks = tasks.map(([key]) => key).filter(key => selected.has(key));
        if (!payload.enabled_tasks.length) {error = '허용 분석 작업을 최소 1개 선택하세요.'; render(); return;}
        busy = true; render();
        try {const result = await options.save(payload); if (result) profile = result.profile || result; notice = 'AI 한도를 저장했습니다.';}
        catch (err) {error = String(err.message || err);}
        finally {busy = false; render();}
      }); root.append(form);
    }
    render(); return {destroy() {root.replaceChildren();}};
  }
  global.AtlasAILimits = {mount};
  if (typeof module !== 'undefined' && module.exports) module.exports = global.AtlasAILimits;
})(typeof window !== 'undefined' ? window : globalThis);
