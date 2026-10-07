import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const dir=new URL('.',import.meta.url),design=JSON.parse(fs.readFileSync(new URL('design.json',dir)));
assert.equal(new Set(design.screens.map(s=>s.name)).size,design.screens.length,'unique state names are required for rerun updates');
const edges=new Map();let count=0;
function walk(n,f){f(n);for(const c of n.children||[])walk(c,f);}
design.screens.forEach((s,i)=>{edges.set(i,[]);function geometry(n,x=0,y=0){const nx=x+(n.x||0),ny=y+(n.y||0);if(n.type!=='text'){assert(nx>=0&&ny>=0&&nx+n.w<=391&&ny+n.h<=845,'outside screen: '+i+' '+n.name);}if(n.target!=null){assert(design.screens[n.target],'missing target');edges.get(i).push(n.target);if(n.target!==i)count++;if(n.action==='OVERLAY'||n.action==='SWAP')assert(design.screens[n.target].overlay,'popup must target an overlay');}else if(n.action==='CLOSE')count++;for(const c of n.children||[])geometry(c,nx,ny);}for(const n of s.children)geometry(n);});
const visited=new Set();function visit(i){if(visited.has(i))return;visited.add(i);for(const j of edges.get(i))visit(j);}visit(0);assert.equal(visited.size,design.screens.length,'all prototype states reachable');
// Execute the shipped plugin against an API test double. This verifies staging,
// persistence, actual saved actions and rerun behavior, not native Figma rendering.
let next=0;const all=new Map();let failures=false;
class Node{
 constructor(type){this.type=type;this.id=String(++next);all.set(this.id,this);this.children=[];this.x=0;this.y=0;this.width=100;this.height=100;this.name='';this.fills=[];this.reactions=[];this.removed=false;}
 appendChild(n){if(n.parent)n.parent.children=n.parent.children.filter(c=>c!==n);n.parent=this;this.children.push(n);}
 resize(w,h){assert(w>0&&h>0);this.width=w;this.height=h;}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);this.removed=true;}
 findAll(fn){const a=[];for(const c of this.children){if(fn(c))a.push(c);a.push(...c.findAll(fn));}return a;}
 clone(){const c=new Node(this.type);for(const k of ['x','y','width','height','name','fills','reactions','fontSize','characters'])c[k]=this[k];for(const ch of this.children)c.appendChild(ch.clone());return c;}
 async setReactionsAsync(rs){if(failures)throw Error('injected reaction storage failure');for(const r of rs){assert.equal(r.trigger.type,'ON_CLICK');for(const a of r.actions){assert(['NODE','CLOSE'].includes(a.type));if(a.type==='NODE'){assert(['OVERLAY','SWAP','NAVIGATE'].includes(a.navigation));const destination=all.get(a.destinationId);assert(destination?.type==='FRAME');let source=this;while(source.parent&&source.parent.type!=='PAGE')source=source.parent;if(a.navigation==='NAVIGATE'&&(destination.removed||destination.id===source.id||destination.parent?.type!=='PAGE'||destination.parent?.id!==source.parent?.id))throw Error('NAVIGATE destinations must be a different top-level frame on the same page');if(a.overlayRelativePosition!==undefined&&(a.navigation!=='OVERLAY'||destination.overlayPositionType!=='MANUAL'))throw 'Actions only support overlayRelativePosition when navigation is "OVERLAY" and the destination is a frame with overlayPosition equal to "MANUAL"';}}}this.reactions=structuredClone(rs);}
}
const page=new Node('PAGE');page.name='TradePilot / Client UI';page.flowStartingPoints=[];
const root=new Node('DOCUMENT');root.appendChild(page);
const originalIds=design.screens.slice(0,6).map(s=>{const n=new Node('FRAME');n.name=s.name;page.appendChild(n);n.appendChild(new Node('TEXT'));return n.id;});
let ui='';const collections=[],variables=[];
const api={root,currentPage:page,async setCurrentPageAsync(p){this.currentPage=p;},async listAvailableFontsAsync(){return ['Regular','Medium','Bold'].map(style=>({fontName:{family:'Apple SD Gothic Neo',style}}));},async loadFontAsync(){},createFrame:()=>new Node('FRAME'),createText:()=>new Node('TEXT'),createRectangle:()=>new Node('RECTANGLE'),createNodeFromSvg:()=>new Node('FRAME'),viewport:{scrollAndZoomIntoView(){}},showUI(html){ui=html;},ui:{},variables:{async getLocalVariableCollectionsAsync(){return collections;},createVariableCollection(name){const c={id:'collection-'+collections.length,name,defaultModeId:'mode'};collections.push(c);return c;},async getLocalVariablesAsync(){return variables;},createVariable(name,c){const v={id:'var-'+variables.length,name,variableCollectionId:c.id,setValueForMode(){},setVariableCodeSyntax(){}};variables.push(v);return v;},setBoundVariableForPaint(p){return p;}}};
const source=fs.readFileSync(new URL('code.js',dir),'utf8');
const selfProbe=new Node('RECTANGLE');all.get(originalIds[0]).appendChild(selfProbe);
await assert.rejects(()=>selfProbe.setReactionsAsync([{trigger:{type:'ON_CLICK'},actions:[{type:'NODE',destinationId:originalIds[0],navigation:'NAVIGATE',transition:null}]}]),/different top-level frame/);
selfProbe.remove();
// Reproduce the exact reported Figma constraint against the previous action builder.
const legacySource=source.replace('transition:null};}',"transition:null};if(d.action==='OVERLAY')action.overlayRelativePosition={x:0,y:0};}");
assert.notEqual(legacySource,source);
const beforeLegacy=originalIds.map(id=>all.get(id).children.map(c=>c.id));
await vm.runInNewContext(legacySource,{figma:api,console:{error(){}}});
assert(ui.includes('Actions only support overlayRelativePosition'));
assert(ui.includes('05 / 버튼 연결 저장'));
assert.deepEqual(originalIds.map(id=>all.get(id).children.map(c=>c.id)),beforeLegacy);
async function run(){ui='';await vm.runInNewContext(source,{figma:api,console});assert(ui.includes('TradePilot v2 적용 완료'),ui);}
await run();assert.equal(page.flowStartingPoints.length,2);for(let i=0;i<6;i++)assert.equal(page.children.find(n=>n.name===design.screens[i].name).id,originalIds[i]);
function checkSaved(){let n=0;for(const s of design.screens){const f=page.children.find(n=>n.name===s.name);assert(f);const tap=f.children.filter(c=>c.name.startsWith('Tap / '));n+=tap.length;for(const t of tap){assert.equal(t.reactions.length,1);for(const a of t.reactions[0].actions)if(a.type==='NODE'){const dest=all.get(a.destinationId);assert(!dest.removed);assert.equal(dest.parent.id,page.id);assert.notEqual(dest.id,f.id,'self-targets must be omitted after final reparenting');}}}assert.equal(n,count);}
checkSaved();const ids=design.screens.map(s=>page.children.find(n=>n.name===s.name).id);await run();checkSaved();assert.deepEqual(design.screens.map(s=>page.children.find(n=>n.name===s.name).id),ids);assert.equal(collections.length,1);assert.equal(variables.length,Object.keys(design.colors).length);
const before=ids.map(id=>all.get(id).children.map(c=>c.id));failures=true;await vm.runInNewContext(source,{figma:api,console});assert(ui.includes('injected reaction storage failure'));assert.deepEqual(ids.map(id=>all.get(id).children.map(c=>c.id)),before);
assert(ui.includes('05 / 버튼 연결 저장'),'reaction errors identify the failed phase');
assert(ui.includes('setReactionsAsync'),'reaction errors identify the failed API');
const originalFonts=api.listAvailableFontsAsync;
for(const thrown of ['plain-string failure <script>alert(1)</script>',{code:'FONT_FAILED',detail:'font unavailable'},undefined,null]){
 api.listAvailableFontsAsync=async()=>{throw thrown;};
 await vm.runInNewContext(source,{figma:api,console:{error(){}}});
 assert(ui.includes('2.0.3 생성 중 오류'));
 assert(ui.includes('01 / 사용 가능한 글꼴 확인'));
 assert(ui.includes('figma.listAvailableFontsAsync'));
 assert(!ui.includes('<script>'),'error payload is displayed as inert text');
 if(typeof thrown==='string')assert(ui.includes('plain-string failure &lt;script&gt;'));
 else if(thrown&&thrown.code)assert(ui.includes('FONT_FAILED'));
 else assert(!ui.includes('원본 오류:\nundefined'));
}
api.listAvailableFontsAsync=originalFonts;
// Also cover installation into an empty file: no existing destination frames.
failures=false;const freshPage=new Node('PAGE');freshPage.name='Page 1';freshPage.flowStartingPoints=[];
const freshDocument=new Node('DOCUMENT');freshDocument.appendChild(freshPage);api.root=freshDocument;api.currentPage=freshPage;
await run();const freshScreens=freshPage.children.filter(n=>n.type==='FRAME');assert.equal(freshScreens.length,design.screens.length);
let freshLinks=0;for(const frame of freshScreens)for(const tap of frame.children.filter(n=>n.name.startsWith('Tap / '))){freshLinks++;for(const a of tap.reactions[0].actions)if(a.type==='NODE'){const dest=all.get(a.destinationId);assert.notEqual(dest.id,frame.id);assert.equal(dest.parent.id,freshPage.id);}}
assert.equal(freshLinks,count);
const report={build:'2.0.3',screens:design.screens.length,connections:count,reachableStates:visited.size,checks:['self NAVIGATE rejected by test API','no self navigation or self SWAP in final tree','NAVIGATE targets different top-level frame on same page','reproduced previous MANUAL-overlay constraint failure','all current actions pass overlay coordinate constraint','graph reachability','popup targets','geometry','stored reactions','preserve existing frame IDs','idempotent rerun','single token collection','failure leaves original content intact','string/object/null/undefined errors retain diagnostics','error HTML escaped','reaction errors report phase and API'],nativeFigmaVerified:false};
fs.writeFileSync(new URL('verification.json',dir),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
