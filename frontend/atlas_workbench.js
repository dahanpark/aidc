/* Reparent the existing controls, preserving listeners and private state. */
'use strict';
(() => {
  const views=new Set(['overview','companies','projects','regions']);
  const create=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;};
  function restore(home,controls=[]){if(home)controls.filter(Boolean).forEach(node=>home.append(node));}
  function compose(root,{view,controls=[]}={}){
    if(!views.has(view))return null;
    const visual=root.querySelector('.workspace-network')||(view==='regions'?root.querySelector('.business-map-panel'):null);
    if(!visual)return null;
    const shell=create('section','graph-workbench'),primary=create('div','workbench-primary'),sidebar=create('aside','workbench-sidebar');
    shell.dataset.view=view;sidebar.setAttribute('aria-label','분류·검색·선택·현황과 근거');
    sidebar.append(create('h2','workbench-sidebar-title','탐색 조건 · 현황'));
    const common=create('div','workbench-common-controls');controls.filter(Boolean).forEach(node=>common.append(node));sidebar.append(common);
    for(const selector of ['.company-workspace-controls','.project-workspace-controls','.company-profile-strip','.company-project-legend','.dashboard-stats','.workspace-count-note','.project-context-summary']){
      const node=root.querySelector(selector);if(node)sidebar.append(node);
    }
    const heading=[...visual.children].find(node=>node.classList.contains('section-head'));
    if(heading){heading.classList.add('workbench-explanation');sidebar.append(heading);}
    const mapControls=visual.querySelector('.map-workspace-controls');if(mapControls)sidebar.append(mapControls);
    const inspector=visual.querySelector('.network-inspector')||visual.querySelector('.atlas-map-detail');if(inspector)sidebar.append(inspector);
    primary.append(visual);shell.append(primary,sidebar);root.prepend(shell);
    const toggle=create('button','workbench-tools-toggle','조건 · 현황');toggle.type='button';toggle.addEventListener('click',()=>sidebar.scrollIntoView({block:'start',behavior:'smooth'}));primary.append(toggle);
    return shell;
  }
  window.AtlasWorkbench=Object.freeze({restore,compose});
})();
