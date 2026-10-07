// Local Figma development plugin. No network, account, or trading access.
async function main() {
  const fonts=await figma.listAvailableFontsAsync();
  const family=['Apple SD Gothic Neo','Pretendard','Noto Sans KR','Noto Sans CJK KR'].find(f=>fonts.some(v=>v.fontName.family===f));
  if(!family)throw new Error('Apple SD Gothic Neo, Pretendard 또는 Noto Sans KR 글꼴을 설치한 뒤 다시 실행해 주세요.');
  function choose(weight){const candidates=weight>=600?['SemiBold','Semibold','Bold','Medium','Regular']:weight>=500?['Medium','Regular']:['Regular','Medium'];return fonts.find(f=>f.fontName.family===family&&candidates.includes(f.fontName.style)&&f.fontName.style===candidates.find(v=>fonts.some(f=>f.fontName.family===family&&f.fontName.style===v))).fontName;}
  const fontMap={400:choose(400),500:choose(500),600:choose(600)};
  await Promise.all(Object.values(fontMap).map(f=>figma.loadFontAsync(f)));
  const page=figma.createPage();page.name='TradePilot / Client UI';await figma.setCurrentPageAsync(page);
  const rgb=hex=>({r:parseInt(hex.slice(1,3),16)/255,g:parseInt(hex.slice(3,5),16)/255,b:parseInt(hex.slice(5,7),16)/255});
  const collection=figma.variables.createVariableCollection('TradePilot / Monochrome');
  const vars={};
  for(const [name,value] of Object.entries(DESIGN.colors)){const v=figma.variables.createVariable('color/'+name,collection,'COLOR');v.scopes=['FRAME_FILL','SHAPE_FILL','TEXT_FILL','STROKE_COLOR'];v.setValueForMode(collection.defaultModeId,rgb(value));v.setVariableCodeSyntax('WEB','var(--tp-'+name+')');vars[name]=v;}
  function paint(key){return figma.variables.setBoundVariableForPaint({type:'SOLID',color:rgb(DESIGN.colors[key])},'color',vars[key]);}
  const links=[];const roots=[];
  async function make(d,parent,center=false){
    let n;
    if(d.type==='text'){
      n=figma.createText();n.fontName=fontMap[d.weight]||fontMap[400];n.fontSize=d.size;n.lineHeight={unit:'PIXELS',value:Math.ceil(d.size*1.5)};n.characters=d.value;n.fills=[paint(d.color)];n.textAutoResize='HEIGHT';n.resize(Math.max(1,Math.min(d.w,parent.width-d.x)),Math.ceil(d.size*1.5));if(center)n.textAlignHorizontal='CENTER';
    }else if(d.type==='rect'){n=figma.createRectangle();n.resize(d.w,d.h);n.fills=[paint(d.color)];
    }else if(d.type==='svg'){n=figma.createNodeFromSvg('<svg xmlns="http://www.w3.org/2000/svg" width="'+d.w+'" height="'+d.h+'" viewBox="0 0 '+(d.w<=24?24:d.w)+' '+(d.w<=24&&d.h<=24?24:d.h)+'">'+d.body+'</svg>');
    }else{
      n=figma.createFrame();n.resize(d.w,d.h);n.fills=[];n.clipsContent=false;
    }
    parent.appendChild(n);n.x=d.x;n.y=d.y;n.name=d.name||d.value|| (d.type==='svg'?'Chart / vector':'Divider');
    if(d.type==='group'){
      if(d.component&&d.component.startsWith('Button/')){
        n.layoutMode='HORIZONTAL';n.primaryAxisSizingMode='FIXED';n.counterAxisSizingMode='FIXED';n.counterAxisAlignItems='CENTER';n.paddingLeft=16;n.paddingRight=16;n.fills=[paint(d.component==='Button/primary'?'fg':'panel')];
        const label=d.children.find(c=>c.type==='text');const t=await make({...label,x:0,y:0,w:d.w-32},n);t.layoutSizingHorizontal='FILL';
      }else for(const child of d.children)await make(child,n,d.centerText);
    }
    if(d.target!==undefined&&d.target!==null)links.push([n,d.target]);
    return n;
  }
  for(let i=0;i<DESIGN.screens.length;i++){
    const s=DESIGN.screens[i];const root=figma.createFrame();page.appendChild(root);root.name=s.name;root.resize(s.w,s.h);root.x=200+(i%3)*450;root.y=200+Math.floor(i/3)*940;root.fills=[paint('bg')];root.clipsContent=true;roots.push(root);
    for(const d of s.children)await make(d,root);
  }
  for(const [node,target] of links)await node.setReactionsAsync([{trigger:{type:'ON_CLICK'},actions:[{type:'NODE',destinationId:roots[target].id,navigation:'NAVIGATE',transition:null}]}]);
  page.flowStartingPoints=[{nodeId:roots[0].id,name:'TradePilot · 모의투자'}];
  figma.viewport.scrollAndZoomIntoView(roots);
  const warnings=[];for(const root of roots)for(const t of root.findAll(n=>n.type==='TEXT'))if(t.height>Math.ceil(t.fontSize*1.5)+1)warnings.push(t.characters);
  figma.closePlugin('TradePilot 6개 화면 생성 완료'+(warnings.length?' · 줄바꿈 확인: '+warnings.length+'곳':''));
}
main().catch(error=>figma.closePlugin('TradePilot: '+error.message));
