(function (global) {
  'use strict';
  const list = value => Array.isArray(value) ? value : [];
  const str = value => value == null ? '' : String(value);
  const unique = values => [...new Set(values.filter(v => typeof v === 'string' && v))];
  const codes = {missing_reference:'원본 참조를 찾을 수 없음',stale_reference:'기사 근거가 변경되었거나 원본 식별이 모호함',non_public_or_missing_evidence:'공개 근거 기사가 없거나 누락됨',member_name_not_evidenced:'선택 기사에 해당 명칭 근거가 없음',member_already_grouped:'다른 대표 사업 묶음에 이미 연결됨',cities_conflict:'도시 충돌',countries_conflict:'국가 충돌',phase_conflict:'단계 충돌',site_ids_conflict:'사업지 충돌',program_ids_conflict:'프로그램 충돌',entity_level_conflict:'program/site/phase 수준 충돌',unknown_identity_attribute:'위치 또는 program/site/phase 수준 미확인',units_roles_and_direct_contract_not_identity_proof:'단위·역할·직접 계약 여부는 동일 사업 연결로 확정되지 않음',stale_or_invalid_basis:'근거가 변경되었거나 유효하지 않음'};
  function mount(root, opts = {}) {
    const doc = root.ownerDocument || global.document;
    const articleIndex = new Map(list(opts.articles).map(a => [a.id,a]));
    let workspace = opts.workspace || {}, candidates = list(opts.candidates || workspace.targets || workspace.refs);
    let selected = unique(list(opts.selection?.member_refs || opts.selected_refs)), representative = opts.selection?.canonical_ref || selected[0] || '';
    let prepared = null, consent = false, busy = false, error = '', notice = '', pendingUndo = '';
    let search = '', page = 1;
    const pageSize = 50;
    let catalog = new Map(candidates.map(c => [c.ref,c]));
    const index = () => catalog;
    function el(tag, text, cls) {const node = doc.createElement(tag); if (text !== undefined) node.textContent = str(text); if (cls) node.className = cls; return node;}
    function attr(node, key, value) {node.setAttribute(key, str(value)); return node;}
    function button(text, fn, disabled = false) {const node = el('button', text); node.type = 'button'; node.disabled = disabled; node.addEventListener('click', fn); return node;}
    function check(text, checked, fn, disabled = false) {
      const label = el('label', undefined, 'identity-check'), input = el('input'); input.type = 'checkbox'; input.checked = checked; input.disabled = disabled;
      input.addEventListener('change', () => fn(input.checked)); label.append(input, el('span', text)); return label;
    }
    function invalidate() {prepared = null; consent = false; error = '';}
    function articleIds() {const catalog = index(); return unique(selected.flatMap(ref => list(catalog.get(ref)?.article_ids)));}
    function payload() {const value = {member_refs:selected.slice(), canonical_ref:representative, evidence_article_ids:articleIds()}; ['run_id','match_id','group_id'].forEach(key => {if (opts.selection?.[key]) value[key] = opts.selection[key];}); return value;}
    function valid() {return selected.length >= 2 && selected.length <= 30 && articleIds().length > 0 && articleIds().length <= 100 && selected.every(ref => index().has(ref)) && selected.includes(representative);}
    function source(ids, label = '근거 기사 열기') {
      const known = unique(list(ids));
      return button(label + ' (' + known.length + ')', () => opts.openArticles?.(known), !known.length || !opts.openArticles);
    }
    function apply(next) {
      if (!next) return;
      const value = next.workspace || next;
      // Successful writes may return a status only. Keep the loaded groups until
      // the host callback supplies its refreshed workspace.
      if (Array.isArray(value.groups) || Array.isArray(value.targets) || Array.isArray(value.refs)) workspace = value;
      if (Array.isArray(value.targets) || Array.isArray(value.refs)) candidates = value.targets || value.refs;
      if (Array.isArray(next.candidates)) candidates = next.candidates;
      catalog = new Map(candidates.map(c => [c.ref,c]));
      selected = selected.filter(ref => index().has(ref));
      if (!selected.includes(representative)) representative = selected[0] || '';
    }
    function message(err) {
      if ([404,503].includes(Number(err?.status || err?.statusCode)) || /\b(?:404|503)\b/.test(str(err?.message))) return '서버 적용 대기 · 동일 사업 연결 API를 아직 사용할 수 없습니다. 기존 사업과 근거는 유지됩니다.';
      return str(err?.message || err || '요청을 처리하지 못했습니다.');
    }
    async function run(action, onSuccess) {
      if (busy) return;
      busy = true; error = ''; render();
      try {const result = await action(); if (onSuccess) onSuccess(result);}
      catch (err) {error = message(err);}
      finally {busy = false; render();}
    }
    function values(node, label, items) {
      const strings = list(items).map(item => typeof item === 'string' || typeof item === 'number' ? str(item) : str(item?.label || item?.name || item?.value)).filter(Boolean);
      if (strings.length) node.append(el('p', label + ': ' + strings.join(' · ')));
    }
    function candidateDetails(candidate, node) {
      const details = [candidate.kind, candidate.location, candidate.stage || candidate.phase, candidate.published_at || candidate.observed_at].filter(v => typeof v === 'string' && v);
      if (details.length) node.append(el('small', details.join(' · '), 'identity-meta'));
      [['도시',candidate.cities],['국가',candidate.countries],['단계',Array.isArray(candidate.phase)?candidate.phase:[]]].forEach(([label,items]) => values(node,label,items));
      if (candidate.entity_level) node.append(el('small','사업 수준: ' + (candidate.entity_level === 'unknown' ? '미확인' : candidate.entity_level),'identity-meta'));
      if (candidate.stale) node.append(el('small','기사 근거 변경 · 재확인 필요','identity-meta'));
      node.append(el('small',candidate.kind === 'project' || candidate.identity_status === 'registered_source' ? '등록 사업 원본' : candidate.kind === 'mention' || candidate.identity_status === 'article_name_candidate' ? '기사 명칭 후보 · 등록 사업과 별도' : '원본 유형 미확인','identity-meta'));
      const date = latestDate(candidate);
      if (date) node.append(el('small','최신 근거 기사: ' + date.slice(0,10),'identity-meta'));
    }
    function latestDate(candidate) {return [candidate.published_at,candidate.observed_at,...list(candidate.article_ids).map(id => articleIndex.get(id)?.published_at || articleIndex.get(id)?.date)].filter(v => typeof v === 'string').sort().at(-1) || '';}
    function removeSelection(ref) {selected = selected.filter(value => value !== ref); if (!selected.includes(representative)) representative = selected[0] || ''; invalidate(); render();}
    function renderSelection(parent) {
      if (!selected.length) return;
      const selectedPanel = el('section',undefined,'identity-selected'); selectedPanel.append(el('h4','선택한 원본 (' + selected.length + ')'));
      selected.forEach(ref => {const candidate = catalog.get(ref), item = el('article',undefined,'identity-candidate'); item.append(el('strong',(ref === representative ? '대표: ' : '') + (candidate?.label || candidate?.name || ref))); if(candidate) candidateDetails(candidate,item);item.append(source(candidate?.article_ids),button('선택 해제: ' + (candidate?.label || candidate?.name || ref),() => removeSelection(ref),busy)); selectedPanel.append(item);});parent.append(selectedPanel);
    }
    function renderCandidates(parent) {
      const controls = el('div',undefined,'identity-search');
      const label = el('label'); label.append(el('span','원본 검색 '));
      const input = el('input'); input.type = 'search'; input.value = search; input.disabled = busy; attr(input,'aria-label','원본 검색');
      input.addEventListener('input',() => {const cursor = input.selectionStart;search = input.value;page = 1;render();const replacement = root.querySelector ? root.querySelector('input[type="search"]') : null;if(replacement?.focus)replacement.focus();if(replacement?.setSelectionRange && cursor !== null)replacement.setSelectionRange(cursor,cursor);});label.append(input);controls.append(label);
      const query = search.trim().toLocaleLowerCase();
      const matched = candidates.filter(c => !query || [c.label,c.name,c.ref,c.location,...list(c.aliases),...list(c.cities),...list(c.countries)].filter(v => typeof v === 'string').join(' ').toLocaleLowerCase().includes(query)).map(c => ({candidate:c,date:latestDate(c)})).sort((a,b) => b.date.localeCompare(a.date) || str(a.candidate.label || a.candidate.name).localeCompare(str(b.candidate.label || b.candidate.name),'ko') || str(a.candidate.ref).localeCompare(str(b.candidate.ref)));
      const totalPages = Math.max(1,Math.ceil(matched.length / pageSize));page = Math.max(1,Math.min(page,totalPages));
      controls.append(el('p','검색 결과 ' + matched.length + '개 / 전체 ' + candidates.length + '개 · 최신 근거 기사순, 이름순 · 페이지당 50개 · 검색과 페이지 이동은 선택을 유지합니다.'));
      controls.append(button('이전 원본 페이지',() => {page--;render();},busy || page === 1),attr(el('span',page + ' / ' + totalPages),'aria-current','page'),button('다음 원본 페이지',() => {page++;render();},busy || page >= totalPages));parent.append(controls);
      const selector = el('fieldset'); selector.append(el('legend','연결할 원본 사업·명칭 후보 (2–30개 · 고유 근거 최대 100개)'));
      if (!matched.length) selector.append(el('p',candidates.length ? '검색 결과가 없습니다. 기존 선택은 유지됩니다.' : '자료 부족 · 연결할 원본 사업이나 명칭 후보가 없습니다.'));
      matched.slice((page-1)*pageSize,page*pageSize).forEach(({candidate}) => {
        const item = el('div',undefined,'identity-candidate');
        item.append(check(candidate.label || candidate.name || candidate.ref,selected.includes(candidate.ref),checked => {
          if (checked && selected.length >= 30) {error = '연결 원본은 최대 30개입니다.';render();return;}
          if (checked) selected = unique([...selected,candidate.ref]);else selected = selected.filter(ref => ref !== candidate.ref);
          if (!selected.includes(representative)) representative = selected[0] || '';
          invalidate();render();
        },busy));candidateDetails(candidate,item);item.append(source(candidate.article_ids));selector.append(item);
      });parent.append(selector);
    }
    function issueText(issue) {return typeof issue === 'string' ? issue : [codes[issue.code] || issue.message || issue.reason || issue.code, issue.field, issue.ref, list(issue.values).map(value => typeof value === 'string' ? value : value?.value || value?.label).filter(Boolean).join(' / ')].filter(Boolean).join(' · ');}
    function conflicts(parent, result) {
      const block = el('section', undefined, 'identity-evidence');
      block.append(el('h5', '충돌·미확인 정보'));
      const issues = list(result.conflicts);
      if (!issues.length) block.append(el('p', '보고된 충돌 없음 · 동일성의 자동 확정을 뜻하지 않습니다.'));
      issues.forEach(issue => {
        const text = issueText(issue);
        block.append(el('p', '충돌: ' + text));
        if (typeof issue === 'object') block.append(source(issue.article_ids));
      });
      const unknowns = result.unknowns || result.unresolved;
      if (Array.isArray(unknowns) && unknowns.length) unknowns.forEach(issue => block.append(el('p', '미확인: ' + (typeof issue === 'string' ? issue : issue.label || issue.message || issue.field || '근거 확인 필요'))));
      else block.append(el('p', '미확인: 역할·수치·단계는 개별 기사 근거를 확인하세요.'));
      list(result.warnings).forEach(warning => block.append(el('p', '확인 필요: ' + issueText(warning))));
      parent.append(block);
    }
    function renderPreview(parent) {
      if (!prepared) return;
      const panel = el('section', undefined, 'identity-preview'); panel.append(el('h4', '동일 사업 연결 미리보기'));
      panel.append(el('p', '원본 사업·명칭 후보·기사·역할은 보존합니다. 선택한 원본을 대표 사업 아래 묶어 표시하며, 같은 기사와 명시 역할을 새 사실로 만들지 않습니다.'));
      const catalog = index();
      selected.forEach(ref => {const c = catalog.get(ref), item = el('article'); item.append(el('strong', (ref === representative ? '대표: ' : '원본: ') + (c?.label || ref))); if(c) candidateDetails(c,item); item.append(source(c?.article_ids)); panel.append(item);});
      list(prepared.sources || prepared.articles).forEach(article => {const item = el('article'); item.append(el('strong', article.title || article.label || article.id), el('small', str(article.published_at || article.observed_at || article.date), 'identity-meta')); if(article.id) item.append(source([article.id])); panel.append(item);});
      if (!list(prepared.sources || prepared.articles).length) articleIds().forEach(id => {const a = articleIndex.get(id), item = el('article');item.append(el('strong',a?.title || id),el('small',a?.published_at || a?.date || '기사 시점 미제공','identity-meta'),source([id]));panel.append(item);});
      conflicts(panel, prepared);
      panel.append(check('근거를 확인했고 같은 사업으로 연결합니다', consent, checked => {consent = checked; render();}, busy));
      panel.append(button('동일 사업 연결 확정', () => {
        if (!valid() || !consent || !prepared?.input_hash || busy || prepared.applicable === false || prepared.can_confirm === false || prepared.blocking === true) return;
        const request = {...payload(), consent_user_confirmed:true};
        if (prepared.input_hash) request.input_hash = prepared.input_hash;
        if (prepared.preview_token) request.preview_token = prepared.preview_token;
        run(() => opts.confirm(request), result => {apply(result); invalidate(); notice = '동일 사업 연결을 저장했습니다. 원본은 보존됩니다.';});
      }, busy || !valid() || !consent || !opts.confirm || !prepared.input_hash || prepared.applicable === false || prepared.can_confirm === false || prepared.blocking === true)); parent.append(panel);
    }
    function renderGroups(parent) {
      const section = el('section', undefined, 'identity-groups'); section.append(el('h4', '대표 사업 연결 기록'));
      if (!list(workspace.groups).length) section.append(el('p', '저장된 동일 사업 연결이 없습니다.'));
      list(workspace.groups).forEach(group => {
        const item = el('article', undefined, 'identity-group');
        const title = group.canonical_title || group.canonical_name || group.title || group.label || index().get(group.canonical_ref)?.label || group.id;
        item.append(el('h5', title));
        const revoked = group.state === 'revoked' || group.status === 'undone';
        const state = revoked ? '해제됨 · 원본 보존' : group.active === false || group.stale ? '현재 통합 표시 보류 · 근거 재확인 필요 · 원본 보존' : '대표 사업 통합 표시 · 원본 보존'; item.append(el('p', state));
        values(item, '별칭', group.aliases);
        values(item, '연결 원본', group.member_refs || list(group.members).map(m => typeof m === 'string' ? m : m.label || m.ref));
        const ids = unique(list(group.article_ids || group.evidence_article_ids)); item.append(el('p', '고유 근거 기사 ' + ids.length + '개'), source(ids));
        if (group.updated_at || group.created_at) item.append(el('small', group.updated_at || group.created_at, 'identity-meta'));
        values(item, '미확인 역할', group.unresolved_roles || group.unknown_roles);
        if (list(group.conflicts).length) conflicts(item, group);
        if (!revoked) {
          if (pendingUndo === group.id) {
            item.append(el('p', '대표 사업 묶음 표시를 해제합니다. 원본 기사·사업·후보와 이력은 보존됩니다.'));
            item.append(button('연결 해제 실행', () => run(() => opts.undo({group_id:group.id,consent_user_confirmed:true}), result => {apply(result); pendingUndo = ''; notice = '동일 사업 연결을 해제했습니다. 원본은 보존됩니다.';}), busy || !opts.undo), button('해제 취소', () => {pendingUndo = ''; render();}, busy));
          } else item.append(button('연결 해제', () => {pendingUndo = group.id; render();}, busy || !opts.undo));
        }
        section.append(item);
      }); parent.append(section);
    }
    function render() {
      root.replaceChildren(); root.className = 'atlas-project-identity'; attr(root, 'aria-busy', busy);
      root.append(el('h3', '동일 사업 연결 · 대표 사업 통합 표시'));
      root.append(el('p', '명칭·지역·단계와 기사 근거를 검토한 뒤 직접 연결합니다. 원본을 삭제하거나 AI 판정만으로 자동 연결하지 않습니다. 유료 AI 호출은 발생하지 않습니다.'));
      if (error) root.append(attr(el('p', error, 'identity-error'), 'role', 'alert'));
      root.append(attr(el('p', busy ? '처리 중…' : notice), 'role', 'status'));
      renderSelection(root);renderCandidates(root);
      const label = el('label', undefined, 'identity-representative'); label.append(el('span','대표 사업 선택 '));
      const select = el('select'); attr(select,'aria-label','대표 사업'); select.disabled = busy || !selected.length;
      selected.forEach(ref => {const option = el('option',index().get(ref)?.label || ref); option.value = ref; select.append(option);}); select.value = representative;
      select.addEventListener('change', () => {representative = select.value; invalidate(); render();}); label.append(select); root.append(label);
      root.append(el('p', '선택한 원본 ' + selected.length + '개 · 고유 근거 기사 ' + articleIds().length + '개'));
      if (articleIds().length > 100) root.append(attr(el('p','고유 근거가 100개를 초과했습니다. 연결할 원본 범위를 줄이세요.'),'role','alert'));
      root.append(button('동일 사업 연결 미리보기', () => {
        if (!valid() || busy || !opts.preview) return;
        run(() => opts.preview(payload()), result => {prepared = result?.data || result; consent = false;});
      }, busy || !valid() || !opts.preview));
      renderPreview(root); renderGroups(root);
    }
    render();
    return {update(next) {apply(next); invalidate(); render();}, destroy() {root.replaceChildren();}, getSelection:payload};
  }
  global.AtlasProjectIdentity = {mount};
  if (typeof module !== 'undefined' && module.exports) module.exports = global.AtlasProjectIdentity;
})(typeof window !== 'undefined' ? window : globalThis);
