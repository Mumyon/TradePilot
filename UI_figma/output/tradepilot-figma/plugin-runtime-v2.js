// TradePilot v2. Native Figma development plugin; no network or trading access.
const TP_BUILD='2.0.3';
const tpDiagnostic={stage:'시작',screen:'',node:'',operation:'',committed:false,cleanupErrors:[]};
function describeError(error){
  if(typeof error==='string'&&error.trim())return error;
  if(error===null)return 'Figma가 null 오류를 반환했습니다.';
  if(error===undefined)return 'Figma가 상세 내용 없는 오류를 반환했습니다.';
  try{if(typeof error.message==='string'&&error.message.trim())return error.message;}catch(_){}
  try{const json=JSON.stringify(error,Object.getOwnPropertyNames(Object(error)));if(json&&json!=='{}')return json;}catch(_){}
  try{const value=String(error);if(value&&value!=='[object Object]')return value;}catch(_){}
  return '오류 객체에 메시지가 없습니다. 아래 실행 단계를 확인해 주세요.';
}
function escapeHtml(value){return String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function stage(name){tpDiagnostic.stage=name;tpDiagnostic.screen='';tpDiagnostic.node='';tpDiagnostic.operation='';}
function operation(name){tpDiagnostic.operation=name;}
function failureReport(error){
  let stack='';try{stack=error&&typeof error.stack==='string'?error.stack:'';}catch(_){}
  return 'TradePilot '+TP_BUILD+'\n단계: '+tpDiagnostic.stage+'\n화면: '+(tpDiagnostic.screen||'-')+'\n요소: '+(tpDiagnostic.node||'-')+'\n작업: '+(tpDiagnostic.operation||'-')+'\n기존 화면 갱신: '+(tpDiagnostic.committed?'시작됨':'시작 전')+'\n\n원본 오류:\n'+describeError(error)+(stack?'\n\n상세:\n'+stack:'')+(tpDiagnostic.cleanupErrors.length?'\n\n임시 화면 정리:\n'+tpDiagnostic.cleanupErrors.join('\n'):'');
}
async function main() {
  stage('01 / 사용 가능한 글꼴 확인');
  operation('figma.listAvailableFontsAsync');
  const fonts=await figma.listAvailableFontsAsync();
  const family=['Apple SD Gothic Neo','Pretendard','Noto Sans KR','Noto Sans CJK KR'].find(f=>fonts.some(v=>v.fontName.family===f));
  if(!family)throw new Error('Apple SD Gothic Neo 또는 Noto Sans KR 글꼴을 설치해 주세요.');
  function choose(weight){const styles=weight>=600?['SemiBold','Semibold','Semi Bold','Bold','Medium','Regular']:weight>=500?['Medium','Regular']:['Regular','Medium'];const match=styles.map(style=>fonts.find(f=>f.fontName.family===family&&f.fontName.style===style)).find(Boolean);if(!match)throw new Error(family+'의 기본 글꼴 스타일을 찾지 못했습니다.');return match.fontName;}
  const fontMap={400:choose(400),500:choose(500),600:choose(600)};
  operation('figma.loadFontAsync');
  await Promise.all(Object.values(fontMap).map(f=>figma.loadFontAsync(f)));
  stage('02 / 기존 페이지와 프레임 확인');
  let page=figma.currentPage;
  if(!page.children.some(n=>n.name===DESIGN.screens[0].name)){const candidate=figma.root.children.find(p=>p.name==='TradePilot / Client UI');if(candidate){page=candidate;await figma.setCurrentPageAsync(page);}}
  const existing=DESIGN.screens.map(s=>page.children.find(n=>n.type==='FRAME'&&n.name===s.name));
  const originalFlows=page.flowStartingPoints.slice();
  const staged=[],links=[];
  const rgb=hex=>({r:parseInt(hex.slice(1,3),16)/255,g:parseInt(hex.slice(3,5),16)/255,b:parseInt(hex.slice(5,7),16)/255});
  stage('03 / 색상 변수 준비');
  operation('figma.variables.getLocalVariableCollectionsAsync');
  const collections=await figma.variables.getLocalVariableCollectionsAsync();
  operation('색상 변수 컬렉션 선택 또는 생성');
  const collection=collections.find(c=>c.name==='TradePilot / Monochrome')||figma.variables.createVariableCollection('TradePilot / Monochrome');
  operation('figma.variables.getLocalVariablesAsync');
  const local=await figma.variables.getLocalVariablesAsync('COLOR');
  const vars={};
  for(const [name,value] of Object.entries(DESIGN.colors)){operation('색상 변수 / '+name);let v=local.find(v=>v.variableCollectionId===collection.id&&v.name==='color/'+name);if(!v){v=figma.variables.createVariable('color/'+name,collection,'COLOR');v.scopes=['FRAME_FILL','SHAPE_FILL','TEXT_FILL','STROKE_COLOR'];v.setValueForMode(collection.defaultModeId,rgb(value));v.setVariableCodeSyntax('WEB','var(--tp-'+name+')');}vars[name]=v;}
  function paint(key){return figma.variables.setBoundVariableForPaint({type:'SOLID',color:rgb(DESIGN.colors[key])},'color',vars[key]);}
  async function make(d,parent,center=false){
    if(d.type==='hotspot')return;
    tpDiagnostic.node=d.name||d.value||d.type;
    operation('생성 / '+d.type);
    let n;
    if(d.type==='text'){
      n=figma.createText();operation('텍스트 글꼴 설정');n.fontName=fontMap[d.weight]||fontMap[400];operation('텍스트 크기·내용·색상 설정');n.fontSize=d.size;n.lineHeight={unit:'PIXELS',value:Math.ceil(d.size*1.5)};n.characters=d.value;n.fills=[paint(d.color)];operation('텍스트 크기 조정');n.textAutoResize='HEIGHT';n.resize(Math.max(1,Math.min(d.w,parent.width-d.x)),Math.ceil(d.size*1.5));if(center)n.textAlignHorizontal='CENTER';
    }else if(d.type==='rect'){n=figma.createRectangle();n.resize(d.w,d.h);n.fills=[paint(d.color)];n.opacity=d.opacity===undefined?1:d.opacity;
    }else if(d.type==='svg'){n=figma.createNodeFromSvg('<svg xmlns="http://www.w3.org/2000/svg" width="'+d.w+'" height="'+d.h+'" viewBox="0 0 '+(d.w<=24?24:d.w)+' '+(d.w<=24&&d.h<=24?24:d.h)+'">'+d.body+'</svg>');
    }else{n=figma.createFrame();n.resize(d.w,d.h);n.fills=[];n.clipsContent=false;}
    operation('부모 프레임에 배치');parent.appendChild(n);n.x=d.x;n.y=d.y;n.name=d.name||d.value||(d.type==='svg'?'Vector':'Divider');
    if(d.type==='group'){
      if(d.component&&d.component.indexOf('Button/')===0){
        operation('버튼 Auto Layout 설정');
        n.layoutMode='HORIZONTAL';n.primaryAxisSizingMode='FIXED';n.counterAxisSizingMode='FIXED';n.counterAxisAlignItems='CENTER';n.paddingLeft=16;n.paddingRight=16;n.fills=[paint(d.component==='Button/primary'?'fg':'panel')];
        const label=d.children.find(c=>c.type==='text');const t=await make(Object.assign({},label,{x:0,y:0,w:d.w-32}),n);operation('버튼 텍스트 FILL 설정');t.layoutSizingHorizontal='FILL';
      }else for(const child of d.children)await make(child,n,d.centerText);
    }
    return n;
  }
  function collect(s){const result=[];function visit(n,x,y){const px=x+(n.x||0),py=y+(n.y||0);if((n.target!==undefined&&n.target!==null)||n.action==='CLOSE')result.push({name:n.name||n.value,x:px,y:py,w:n.w,h:n.h,target:n.target,action:n.action||'NAVIGATE'});for(const c of n.children||[])visit(c,px,py);}for(const c of s.children)visit(c,0,0);return result;}
  const maxX=page.children.reduce((x,n)=>Math.max(x,n.x+n.width),0);
  try{
    stage('04 / 화면 생성');
    // Stage all visual content before altering existing screens.
    for(let i=0;i<DESIGN.screens.length;i++){
      tpDiagnostic.screen=DESIGN.screens[i].name;tpDiagnostic.node='최상위 프레임';operation('프레임 생성');
      const s=DESIGN.screens[i],root=figma.createFrame();page.appendChild(root);root.name='Preparing / '+s.name;root.resize(s.w,s.h);root.x=maxX+200+(i%6)*450;root.y=200+Math.floor(i/6)*940;root.fills=s.overlay?[]:[paint('bg')];root.clipsContent=true;staged.push(root);
      for(const d of s.children)await make(d,root);
    }
    const roots=staged.map((s,i)=>existing[i]||s);
    stage('05 / 버튼 연결 저장');
    for(let i=0;i<staged.length;i++)for(const d of collect(DESIGN.screens[i])){
      // Active tabs and quantity endpoints are no-ops, never self-navigation.
      if(d.target===i&&d.action!=='CLOSE')continue;
      tpDiagnostic.screen=DESIGN.screens[i].name;tpDiagnostic.node=d.name;operation('클릭 영역 생성');
      if(d.target!=null){const destination=roots[d.target];if(!destination||destination.removed||destination.type!=='FRAME'||!destination.parent||destination.parent.id!==page.id)throw new Error('연결 대상이 같은 페이지의 최상위 프레임이 아닙니다: '+d.name);}
      const h=figma.createRectangle();staged[i].appendChild(h);h.name='Tap / '+d.name;h.x=d.x;h.y=d.y;h.resize(d.w,d.h);h.fills=[{type:'SOLID',color:{r:1,g:1,b:1},opacity:0.001}];
      // Use the destination frame's default overlay placement. Relative coordinates
      // are only valid for MANUAL destinations; these full-screen overlays are not MANUAL.
      let action;if(d.action==='CLOSE')action={type:'CLOSE'};else{if(!roots[d.target])throw new Error('잘못된 연결: '+d.name);action={type:'NODE',destinationId:roots[d.target].id,navigation:d.action,transition:null};}
      operation('setReactionsAsync / '+d.action+(d.target!=null?' → '+DESIGN.screens[d.target].name:''));
      await h.setReactionsAsync([{trigger:{type:'ON_CLICK'},actions:[action]}]);
      operation('저장된 reactions 읽기');
      const saved=h.reactions[0];const savedAction=saved&&((saved.actions&&saved.actions[0])||saved.action);
      if(!savedAction||savedAction.type!==action.type||(action.type==='NODE'&&(savedAction.destinationId!==action.destinationId||savedAction.navigation!==action.navigation)))throw new Error('연결 저장 실패: '+d.name);
      links.push({node:h,source:i,action});
    }
    // Keep a recoverable hidden backup before replacing matching frame contents.
    stage('06 / 기존 화면 백업');
    operation('기존 프레임 복제');
    if(existing.some(Boolean)){const backup=figma.createFrame();page.appendChild(backup);backup.name='TradePilot / backup before v2 / '+Date.now();backup.resize(1,1);for(const old of existing.filter(Boolean)){const copy=old.clone();backup.appendChild(copy);}backup.visible=false;}
    stage('07 / 기존 화면 갱신');tpDiagnostic.committed=true;
    for(let i=0;i<staged.length;i++){
      tpDiagnostic.screen=DESIGN.screens[i].name;operation('완성된 내용으로 교체');
      const newRoot=staged[i],dest=roots[i];
      if(dest!==newRoot){for(const old of dest.children.slice())old.remove();for(const child of newRoot.children.slice())dest.appendChild(child);dest.resize(DESIGN.screens[i].w,DESIGN.screens[i].h);dest.fills=newRoot.fills;dest.clipsContent=true;newRoot.remove();}
      dest.name=DESIGN.screens[i].name;
    }
    // Reparenting must leave every action valid against the final frame tree.
    operation('최종 프레임에서 연결 재검증');
    for(const link of links){
      const h=link.node,a=link.action;tpDiagnostic.node=h.name;tpDiagnostic.screen=DESIGN.screens[link.source].name;
      if(a.type==='NODE'&&a.navigation==='NAVIGATE'&&h.parent.id===a.destinationId)throw new Error('자기 화면으로 이동하는 연결이 남아 있습니다: '+h.name);
      const r=h.reactions[0],saved=r&&((r.actions&&r.actions[0])||r.action);
      if(!saved||saved.type!==a.type||(a.type==='NODE'&&(saved.destinationId!==a.destinationId||saved.navigation!==a.navigation)))await h.setReactionsAsync([{trigger:{type:'ON_CLICK'},actions:[a]}]);
      const rr=h.reactions[0],verified=rr&&((rr.actions&&rr.actions[0])||rr.action);
      if(!verified||verified.type!==a.type||(a.type==='NODE'&&(verified.destinationId!==a.destinationId||verified.navigation!==a.navigation)))throw new Error('프레임 갱신 후 연결이 유실되었습니다: '+h.name);
    }
    stage('08 / Present 시작점 설정');operation('page.flowStartingPoints');
    const flowIds=new Set(roots.map(n=>n.id));page.flowStartingPoints=[...originalFlows.filter(f=>!flowIds.has(f.nodeId)),{nodeId:roots[0].id,name:'TradePilot v2 · 시작'},{nodeId:roots[1].id,name:'TradePilot v2 · 검색과 주문'}];
    operation('시작 프레임 선택');
    page.selection=[roots[0]];figma.viewport.scrollAndZoomIntoView([roots[0],roots[1],roots[6]]);
    stage('09 / 최종 레이아웃 점검');
    const wrapped=[];for(const r of roots)for(const t of r.findAll(n=>n.type==='TEXT'))if(t.height>Math.ceil(t.fontSize*1.5)+1)wrapped.push(t.characters);
    const message='빌드 '+TP_BUILD+' · '+roots.length+'개 화면/상태 · '+links.length+'개 클릭 연결 저장 확인';
    figma.showUI('<html lang="ko"><meta charset="utf-8"><body style="margin:24px;background:#101012;color:#f5f5f2;font:13px sans-serif;line-height:1.8"><h2>TradePilot v2 적용 완료</h2><p>'+message+'</p><p>선택된 관심종목 프레임에서 오른쪽 위 ▶ Present를 누르세요.<br>기존 Present 창은 닫고 다시 열어 주세요.</p><p>검색 → 삼성전자/SK하이닉스 선택<br>매수/매도 → 상세 팝업 → 수량 1주/5주 → 확인 → 접수</p><p>검색창은 “삼성” 예시 검색을 재현합니다. 자유 입력은 아직 지원하지 않습니다.</p><p>줄바꿈 점검: '+wrapped.length+'곳</p><button style="padding:10px 24px" onclick="parent.postMessage({pluginMessage:{type:\'close\'}},\'*\')">닫기</button></body></html>',{width:430,height:410});
    figma.ui.onmessage=msg=>{if(msg.type==='close')figma.closePlugin();};
    return {screenCount:roots.length,linkCount:links.length,wrapped};
  }catch(error){for(const n of staged){try{if(!n.removed&&n.name.indexOf('Preparing / ')===0)n.remove();}catch(cleanupError){tpDiagnostic.cleanupErrors.push(describeError(cleanupError));}}throw error;}
}
main().catch(error=>{const report=failureReport(error);console.error(report);figma.showUI('<meta charset="utf-8"><div style="font:14px sans-serif;padding:20px"><h2>TradePilot '+TP_BUILD+' 생성 중 오류</h2><p>아래 내용을 복사해서 전달해 주세요.</p><textarea readonly style="box-sizing:border-box;width:100%;height:290px;font:12px monospace;line-height:1.5">'+escapeHtml(report)+'</textarea></div>',{width:560,height:425});});
