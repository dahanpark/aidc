(function (global) {
  'use strict';
  const list = value => Array.isArray(value) ? value : [];
  const str = value => value == null ? '' : String(value);
  const DEFAULT_BOARD = {"id":"construction","title":"국내 DC.AIDC 전략 (건설사)","analysis_brief":"회사별 DC·AIDC 사업 전략을 공개 기사 근거로 종합한다. 기사 건수가 아닌 내용 중심으로 셀당 최대 3개 말머리 단락을 작성한다. 계획/실제·준공/수주/추진·예상/확정을 구분하고 출처·날짜·정확한 인용을 연결한다. 근거가 없으면 자료 부족으로 남기며 수치나 참여를 추정하지 않는다.","companies":[{"id":"posco-enc","name":"포스코E&C","aliases":["포스코이앤씨","포스코건설"]},{"id":"dl-enc","name":"DL E&C","aliases":["DL이앤씨","디엘이앤씨"]},{"id":"hyundai-engineering","name":"현대엔지니어링","aliases":[]},{"id":"sk-ecoplant","name":"SK에코플랜트","aliases":[]},{"id":"ipark-hdc","name":"IPARK현대산업개발","aliases":["HDC현대산업개발","현대산업개발"]},{"id":"hanwha-construction","name":"한화 건설부문","aliases":["한화건설","한화 건설부문","㈜한화 건설부문"]},{"id":"samsung-cnt","name":"삼성물산","aliases":[]}],"rows":[{"id":"organization","label":"조직형태/현황","analysis_guidance":"DC·AIDC 담당 조직, 인력·전담부서 및 사업 추진 체계를 정리한다."},{"id":"strategy","label":"핵심전략","analysis_guidance":"데이터센터 시장 진출·확대 전략과 협력 방향을 정리한다."},{"id":"strengths","label":"강점(차별화)","analysis_guidance":"기사에 명시된 경쟁력과 차별화 근거를 정리한다."},{"id":"technology","label":"기술·인증·공법 키워드","analysis_guidance":"기술·인증·공법·R&D·냉각·전력 관련 키워드와 적용 상태를 구분한다."},{"id":"completed","label":"건립실적(준공)","analysis_guidance":"준공한 데이터센터 실적만 정리하고 수주·계획 실적과 구분한다."},{"id":"pipeline","label":"수주/시공/추진(파이프라인)","analysis_guidance":"수주·시공 중·추진 중인 사업을 단계와 시점별로 구분한다."},{"id":"future","label":"향후계획(시장/파이프라인)","analysis_guidance":"향후 시장·파이프라인 계획을 정리하되 예상 참여와 확정을 구분한다."},{"id":"notes","label":"비고","analysis_guidance":"주요 변동, 확인 필요 사항과 기사 간 상충 내용을 정리한다."},{"id":"dc-history","label":"주요 DC·AIDC 시공이력","analysis_guidance":"주요 DC·AIDC 시공 사업명, 위치, 참여 역할과 근거 시점을 정리한다."},{"id":"target-sites","label":"검토 중인 대상지","analysis_guidance":"검토 중이라고 명시된 대상지와 추진 단계를 정리한다."},{"id":"pc-subsidiary","label":"PC 자회사 여부","analysis_guidance":"PC(프리캐스트 콘크리트) 자회사 보유 여부를 명시 근거로 확인하며 계열 관계를 추정하지 않는다."}]};
  let sequence = 0;
  const stableId = prefix => prefix + '-' + (global.crypto && global.crypto.randomUUID ? global.crypto.randomUUID() : Date.now().toString(36) + '-' + (++sequence).toString(36));
  function mount(root, opts = {}) {
    const doc = root.ownerDocument || global.document;
    let workspace = opts.workspace || {}, board = workspace.active_board || list(workspace.boards)[0] || defaultBoard();
    if (!list(workspace.boards).length) workspace = {...workspace, boards:[board], active_board:board};
    let backendReady = opts.backendReady !== false;
    let selectedCompany = board && list(board.companies)[0] && board.companies[0].id;
    let selectedRows = [], selectedArticles = [], prepared = null, consent = false, busy = false, error = '', notice = '';
    let formKind = '', draft = '', aliases = '', guidance = '', editingId = '', from = '', to = '';
    const articles = list(opts.articles);
    const articleIndex = new Map(articles.map(a => [str(a.id), a]));
    const connection = opts.connection || {};
    const configured = () => connection.configured === true || connection.key_configured === true || connection.credential_configured === true || connection.connected === true;
    const articleLimit = () => Math.min(3, Math.max(1, Number(connection.max_articles_per_run || connection.max_articles || connection.limits?.max_articles_per_run || connection.limits?.max_articles || 3)));
    function el(tag, text, cls) { const node = doc.createElement(tag); if (text !== undefined) node.textContent = str(text); if (cls) node.className = cls; return node; }
    function attr(node, key, value) { node.setAttribute(key, str(value)); return node; }
    function button(text, action, disabled = false) { const node = el('button', text); node.type = 'button'; node.disabled = disabled; node.addEventListener('click', action); return node; }
    function field(label, node) { const wrap = el('label', undefined, 'strategy-field'); wrap.append(el('span', label), node); return wrap; }
    function input(value, action, type = 'text') { const node = el('input'); node.type = type; node.value = value; node.disabled = busy; node.addEventListener('input', () => action(node.value)); return node; }
    function startEdit(kind,item){formKind='edit-'+kind;editingId=item.id;draft=item.name||item.label||item.title;aliases=list(item.aliases).join(', ');guidance=kind==='category'?(item.analysis_brief||''):(item.analysis_guidance||'');invalidate();render();}
    function invalidate() { prepared = null; consent = false; error = ''; }
    function selection() { return {board_id: board.id, company_id: selectedCompany, row_ids: selectedRows.slice(), article_ids: selectedArticles.slice()}; }
    function accept(next) {
      if (!next) return;
      workspace = next.workspace || next;
      board = workspace.active_board || list(workspace.boards).find(b => b.id === board?.id) || list(workspace.boards)[0] || board || defaultBoard();
      backendReady = true;
      if (!list(board?.companies).some(c => c.id === selectedCompany)) selectedCompany = list(board?.companies)[0]?.id;
      selectedRows = selectedRows.filter(id => list(board?.rows).some(r => r.id === id));
    }
    async function run(action, success) {
      if (busy) return;
      busy = true; error = ''; render();
      try { const result = await action(); if (success) success(result); }
      catch (err) { error = str(err.message || err); if (/지원하지 않는 작업|API 경로가 없습니다|404/.test(error)) {backendReady=false;error='현재 실행 서버가 전략표 저장 API를 지원하지 않습니다. 기존 store를 유지하고 앱을 정상 종료한 뒤 최신 AIDC ATLAS.cmd로 다시 실행하세요. 입력은 이 화면에 유지됩니다.';} }
      finally { busy = false; render(); }
    }
    function bounded(values, id, checked, limit) {
      if (!checked) return values.filter(v => v !== id);
      if (values.includes(id)) return values;
      if (values.length >= limit) { error = '최대 ' + limit + '개까지 선택할 수 있습니다.'; return values; }
      return values.concat(id);
    }
    function check(text, checked, change, disabled = false) {
      const node = el('input'); node.type = 'checkbox'; node.checked = checked; node.disabled = disabled;
      node.addEventListener('change', () => change(node.checked));
      const label = el('label', undefined, 'strategy-check'); label.append(node, el('span', text)); return label;
    }
    function source(id) {
      const article = articleIndex.get(str(id));
      const node = button('기사: ' + (article?.title || id), () => opts.openArticles?.([id]));
      node.className = 'strategy-source'; node.disabled = !opts.openArticles;
      if (article?.published_at || article?.date) node.append(el('small', ' · ' + str(article.published_at || article.date).slice(0, 10)));
      return node;
    }
    function summaryFor(companyId, rowId) {
      return Object.values(workspace.summaries || {}).find(s => s.board_id === board.id && s.company_id === companyId && s.row_id === rowId);
    }
    function table() {
      const scroll = el('div', undefined, 'strategy-table-scroll'); attr(scroll, 'tabindex', '0'); attr(scroll, 'aria-label', '전략표 가로 스크롤');
      const grid = el('table', undefined, 'strategy-table'), caption = el('caption', board.title || '전략표');
      grid.append(caption); const head = el('thead'), tr = el('tr'); tr.append(attr(el('th', '구분'), 'scope', 'col'));
      list(board.companies).forEach(c => {const th=attr(el('th',c.name),'scope','col');th.append(button('회사 편집',()=>startEdit('company',c),busy||!opts.saveBoard||!backendReady));tr.append(th);}); head.append(tr); grid.append(head);
      const body = el('tbody');
      list(board.rows).forEach(row => {
        const line = el('tr'),heading=attr(el('th', row.label), 'scope', 'row');if(row.analysis_guidance)heading.append(el('small',row.analysis_guidance,'strategy-meta'));heading.append(button('항목·AI 기준 편집',()=>startEdit('row',row),busy||!opts.saveBoard||!backendReady));line.append(heading);
        list(board.companies).forEach(company => {
          const cell = el('td'), summary = summaryFor(company.id, row.id), paragraphs = list(summary?.paragraphs).slice(0, 3);
          if (!paragraphs.length) cell.append(el('span', summary ? '자료 부족 / 확인 필요' : '자료 부족 / AI 미실행', 'strategy-empty'));
          else {
            const bullets = el('ul'); paragraphs.forEach(p => { const li = el('li'); li.append(el('p', p.text)); if (p.quote) li.append(el('blockquote', p.quote)); if (p.article_id) li.append(source(p.article_id)); bullets.append(li); }); cell.append(bullets);
            list(summary.article_ids).filter(id => !paragraphs.some(p => p.article_id === id)).forEach(id => cell.append(source(id)));
          }
          if (summary) {
            const status = [summary.stale ? '오래된 요약 · 재점검 필요' : '', summary.updated_at, summary.provider, summary.model].filter(Boolean).join(' · ');
            if (status) cell.append(el('small', status, summary.stale ? 'strategy-stale' : 'strategy-meta'));
          }
          line.append(cell);
        }); body.append(line);
      }); grid.append(body); scroll.append(grid); return scroll;
    }
    function addForm(container) {
      if (!formKind) return;
      const form = el('form', undefined, 'strategy-add-form');
      const editing=formKind.startsWith('edit-'),kind=formKind.replace('edit-','');
      const label = {company: '회사명', row: '행 이름', category: '분류표 이름'}[kind];
      const name = input(draft, v => { draft = v; }); attr(name, 'aria-label', label); name.required = true; name.maxLength = 100;
      form.append(field(label, name));
      if (kind === 'company') form.append(field('별칭 (쉼표로 구분)', attr(input(aliases, v => { aliases = v; }),'aria-label','회사 별칭')));
      if(kind==='row'||kind==='category'){const guide=el('textarea');guide.value=guidance;guide.rows=3;guide.maxLength=kind==='row'?600:1000;guide.disabled=busy;attr(guide,'aria-label',kind==='row'?'항목 AI 분석 기준':'카테고리 AI 분석 기준');guide.addEventListener('input',()=>{guidance=guide.value;});form.append(field(kind==='row'?'항목 AI 분석 기준':'카테고리 AI 분석 기준',guide));}
      if(kind==='row'||kind==='category')form.append(el('p','공개 기사 분석 기준만 입력하세요. 기준은 전송 미리보기에 포함됩니다. 사내 메모·비밀정보는 입력하지 마세요.'));
      if (kind === 'category'&&!editing) form.append(el('p', '새 카테고리는 현재 회사·행 구성을 복사하여 시작합니다. 이후 회사·행을 추가할 수 있습니다.'));
      if(editing)form.append(el('p','이름·별칭·분석 기준을 변경해도 기존 셀과 기사 연결은 보존합니다. 기준 변경 시 기존 요약은 재점검 표시됩니다.'));
      const save = el('button', editing?'변경 저장':'추가 저장'); save.type = 'submit'; save.disabled = busy || !opts.saveBoard || !backendReady;
      form.append(save, button('취소', () => {formKind = ''; draft = ''; aliases = ''; render();}, busy));
      form.addEventListener('submit', event => {
        event.preventDefault(); if (!draft.trim() || busy || !backendReady) return;
        let payload;
        if (kind === 'category'&&!editing) payload = {id: stableId('board'), title: draft.trim(), analysis_brief:guidance||board?.analysis_brief||'', companies: list(board?.companies).map(c => ({...c, aliases: list(c.aliases).slice()})), rows: list(board?.rows).map(r => ({...r}))};
        else { payload = {...board, companies: list(board.companies).map(c => ({...c})), rows: list(board.rows).map(r => ({...r}))};
          const aliasList=aliases.split(',').map(v=>v.trim()).filter(Boolean);
          if(editing){if(kind==='category'){payload.title=draft.trim();payload.analysis_brief=guidance;}else if(kind==='company'){Object.assign(payload.companies.find(c=>c.id===editingId),{name:draft.trim(),aliases:aliasList});}else{Object.assign(payload.rows.find(r=>r.id===editingId),{label:draft.trim(),analysis_guidance:guidance});}}
          else if (kind === 'company') payload.companies.push({id: stableId('company'), name: draft.trim(), aliases: aliasList});
          else payload.rows.push({id: stableId('row'), label: draft.trim(),analysis_guidance:guidance}); }
        run(() => opts.saveBoard(payload), result => {accept(result); formKind = ''; draft = ''; aliases = ''; guidance='';editingId='';invalidate(); notice = editing?'변경 사항을 저장했습니다.':'추가 항목을 저장했습니다.';});
      }); container.append(form);
    }
    function controls(container) {
      const panel = el('section', undefined, 'strategy-analysis'); panel.append(el('h4', '선택 셀의 공개 기사 근거 요약'));
      const rules=el('details');rules.append(el('summary','기본 AI 분석 기준'),el('p',board.analysis_brief||'공개 기사 근거만으로 최대 3개 말머리 단락을 작성합니다.'));list(board.rows).forEach(r=>rules.append(el('p',r.label+' · '+(r.analysis_guidance||'해당 항목의 명시 근거만 정리'))));panel.append(rules);
      panel.append(el('p', '회사 1개 · 행 최대 3개 · 공개 기사 최대 ' + articleLimit() + '개. 미리보기와 전송 동의 후 선택 셀만 분석합니다.'));
      const select = el('select'); attr(select, 'aria-label', '분석 회사');
      list(board.companies).forEach(c => {const option = el('option', c.name); option.value = c.id; select.append(option);}); select.value = selectedCompany || ''; select.disabled = busy;
      select.addEventListener('change', () => {selectedCompany = select.value; selectedArticles = []; invalidate(); render();}); panel.append(field('회사', select));
      const rows = el('fieldset'); rows.append(el('legend', '행 선택 (최대 3개)'));
      list(board.rows).forEach(r => rows.append(check(r.label, selectedRows.includes(r.id), checked => {invalidate(); selectedRows = bounded(selectedRows, r.id, checked, 3); render();}, busy))); panel.append(rows);
      const dates = el('div', undefined, 'strategy-dates');
      dates.append(field('기사 시작일', input(from, value => {from = value; selectedArticles = []; invalidate(); render();}, 'date')), field('기사 종료일', input(to, value => {to = value; selectedArticles = []; invalidate(); render();}, 'date'))); panel.append(dates);
      const refs = el('fieldset'); refs.append(el('legend', '공개 기사 선택'));
      const related = list(workspace.company_articles?.[selectedCompany]);
      const candidates = articles.filter(a => related.includes(a.id)).filter(a => {const date = str(a.published_at || a.date).slice(0,10); return (!from || date >= from) && (!to || date <= to);});
      if (!candidates.length) refs.append(el('p', '자료 부족 · 이 회사에 연결된 공개 기사가 없습니다.'));
      candidates.forEach(a => refs.append(check((a.published_at || a.date || '').slice(0,10) + ' ' + a.title, selectedArticles.includes(a.id), checked => {invalidate(); selectedArticles = bounded(selectedArticles, a.id, checked, articleLimit()); render();}, busy))); panel.append(refs);
      panel.append(el('p', configured() ? 'AI 연결 설정 있음 · 전송 전 실제 입력 확인' : '연결 필요 · SETTINGS에서 개인 AI 키를 연결하세요.', 'strategy-connection'));
      const valid = selectedCompany && selectedRows.length && selectedArticles.length && (!from || !to || from <= to);
      panel.append(button('전송 표본 미리보기', () => run(() => opts.preview(selection()), result => {prepared = result; consent = false;}), busy || !valid || !opts.preview || !configured()));
      if (prepared) {
        const preview = el('section', undefined, 'strategy-preview'); preview.append(el('h5', '실제 전송 준비된 공개 기사'));
        const context=prepared.input_data||{};preview.append(el('h5','실제 전송 회사·항목·AI 분석 기준'),el('pre',JSON.stringify({company:context.company||null,rows:context.rows||prepared.rows||[],analysis_brief:context.analysis_brief||''},null,2)));
        list(prepared.articles).forEach(a => {const article = el('article'); article.append(el('strong', a.title || a.id), el('p', a.text || a.public_text || a.content || a.summary || a.excerpt || '')); preview.append(article);});
        ['limits', 'input_chars', 'input_char_count', 'max_input_chars', 'max_output_tokens', 'output_tokens', 'provider', 'model'].forEach(key => {if (prepared[key] !== undefined) preview.append(el('p', key + ': ' + (typeof prepared[key] === 'object' ? JSON.stringify(prepared[key]) : prepared[key])));});
        preview.append(check('위 공개 기사 메타데이터 전송과 개인 API 사용량 발생에 동의합니다.', consent, checked => {consent = checked; render();}, busy));
        preview.append(button('선택 셀 AI 분석 실행', () => {
          if (!consent || !configured() || !prepared || !valid || busy) return;
          run(() => opts.analyse({...selection(), consent_public_metadata: true}), result => {accept(result); invalidate(); notice = '선택 셀 분석 결과를 갱신했습니다.';});
        }, busy || !consent || !configured() || !valid || !opts.analyse)); panel.append(preview);
      }
      container.append(panel);
    }
    function render() {
      root.replaceChildren(); root.className = (root.className || '').split(/\s+/).filter(c => c && c !== 'atlas-strategy').concat('atlas-strategy').join(' ');
      attr(root, 'aria-busy', busy ? 'true' : 'false');
      root.append(el('h3', 'Con. Status — '+(board?.title||'국내 DC.AIDC 전략 (건설사)')));
      root.append(el('p', '기사 근거 기반 전략표 · PC = Precast Concrete · 계획/실제와 수주/준공은 출처 문맥을 확인하세요.', 'strategy-meta'));
      root.append(el('p','가로는 회사(열), 세로는 분석 항목(행)입니다. 건설사·발주처처럼 표를 따로 만들 때만 분류표를 추가하세요. 기본 7개 건설사·11개 분석 항목이 준비되어 있습니다.','strategy-meta'));
      if(!backendReady){const note=el('div',undefined,'strategy-error');note.append(el('p','기본 표를 표시하고 있습니다. 현재 실행 서버에는 전략표 저장 기능이 적용되지 않았습니다. 기존 store를 보존하며 정상 종료 후 최신 AIDC ATLAS.cmd로 재실행하세요.'),button('서버 적용 상태 다시 확인',()=>run(()=>opts.loadBoard('construction'),value=>{accept(value);notice='서버의 저장 표를 불러왔습니다.';}),busy||!opts.loadBoard));root.append(note);}
      if(board?.analysis_brief)root.append(el('p',board.analysis_brief,'strategy-meta'));
      const tabs = el('div', undefined, 'strategy-tabs'); attr(tabs, 'role', 'tablist'); attr(tabs, 'aria-label', '전략 카테고리');
      list(workspace.boards).forEach(b => {const tab = button(b.title, () => {
        if (!opts.loadBoard || b.id === board?.id) return;
        run(() => opts.loadBoard(b.id), result => {accept(result); selectedRows = []; selectedArticles = [];formKind='';draft='';aliases='';guidance='';editingId='';invalidate();});
      }, busy); attr(tab, 'role', 'tab'); attr(tab, 'aria-selected', b.id === board?.id); tabs.append(tab);}); root.append(tabs);
      if (error) root.append(attr(el('p', error, 'strategy-error'), 'role', 'alert'));
      const status = el('p', busy ? '처리 중…' : notice, 'strategy-status'); attr(status, 'role', 'status'); attr(status, 'aria-live', 'polite'); root.append(status);
      const toolbar = el('div', undefined, 'strategy-toolbar');
      ['company', 'row', 'category'].forEach(kind => toolbar.append(button({category:'분류표 추가',company:'열(회사) 추가',row:'행(분석 항목) 추가'}[kind], () => {formKind = kind; draft = ''; aliases = '';guidance=kind==='category'?(board?.analysis_brief||''):'';editingId=''; render();}, busy || !opts.saveBoard || !backendReady)));
      toolbar.append(button('표 이름·공통 AI 지시문 편집',()=>startEdit('category',board),busy||!board||!opts.saveBoard||!backendReady));
      toolbar.append(button('A3 가로 출력 HTML', () => run(() => opts.exportBoard(board.id), () => {notice = 'A3 가로 출력 HTML을 요청했습니다.';}), busy || !board || !opts.exportBoard)); root.append(toolbar); addForm(root);
      if (!board) {root.append(el('p', '자료 부족 · 전략 카테고리를 추가하세요.')); return;}
      root.append(table()); controls(root);
    }
    render();
    return {update(next) {accept(next); invalidate(); render();}, destroy() {root.replaceChildren();}, getSelection: selection};
  }
  function defaultBoard(){return JSON.parse(JSON.stringify(DEFAULT_BOARD));}
  global.AtlasStrategy = {mount,defaultBoard};
  if (typeof module !== 'undefined' && module.exports) module.exports = global.AtlasStrategy;
})(typeof window !== 'undefined' ? window : globalThis);
