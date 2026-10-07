// Extend the original six screens; all target IDs are resolved from this model.
export function extendPrototype({screens,C,text,rect,group,svg,icon,button,base}) {
  const clone=o=>JSON.parse(JSON.stringify(o));
  const add=s=>{screens.push(s);return screens.length-1;};
  const hit=(name,x,y,w,h,target,action='NAVIGATE')=>({type:'hotspot',name,x,y,w,h,target,action});
  const close=()=>group('닫기',322,16,44,44,[text('×',12,5,26,'fg',400,28)],{action:'CLOSE'});
  const menu=add(base('07 · 전체 메뉴','전체 메뉴','YOUR WORKSPACE / 나의 투자 도구',4));
  const search=add({name:'08 · 종목 검색',w:390,h:844,overlay:true,children:[]});
  const chartTemplate=clone(screens[1]);
  const skChart=add({...clone(chartTemplate),name:'09 · SK하이닉스 차트'});
  function nav(active){return group('Bottom navigation',0,751,390,93,[rect(0,0,390,93,'bg'),rect(0,0,390,1),...[['watch','관심종목',0],['chart','차트',1],['auto','자동매매',3],['journal','매매일지',4],['watch','전체 메뉴',menu]].map(([ic,label,target],i)=>group('Tab / '+label,i*78,0,78,70,[icon(ic,28,14,i===active?'fg':'quiet',22),text(label,0,43,10,i===active?'fg':'quiet',i===active?600:400,78)],{target,centerText:true})),rect(132,80,126,4,'fg')]);}
  function replaceNav(s,active){s.children=s.children.filter(c=>c.name!=='Bottom navigation');s.children.push(nav(active));}
  [0,1,1,2,3,1,4].forEach((a,i)=>replaceNav(screens[i],a));
  const rows=[['종목 검색','이름 또는 종목코드로 찾기',search,'OVERLAY'],['관심종목','나의 시장 목록',0],['자동매매','전략 · 백테스트 · 위험관리',3],['매매일지','거래 기록과 AI 피드백',4]];
  screens[menu].children.push(group('Paper account',24,132,342,92,[rect(0,0,342,92,'panel'),text('PAPER ACCOUNT',16,12,10,'muted',600),text('나의 모의투자 계좌',16,34,19,'fg',600),text('평가금액  10,248,600원',16,64,12,'muted')]));
  rows.forEach(([title,sub,target,action],i)=>screens[menu].children.push(group('Menu / '+title,24,257+i*88,342,78,[text(title,0,8,17,'fg',600),text(sub,0,37,12,'muted'),icon('arrow',314,21,'muted',20),rect(0,77,342,1)],{target,action:action||'NAVIGATE'})));
  screens[menu].children.push(text('TradePilot',24,659,15,'fg',600),text('모의투자 프로토타입  /  v2',24,685,11,'muted'));
  function sheet(name,y,children,previewBase=1){return {name,w:390,h:844,overlay:true,previewBase,children:[{...rect(0,0,390,844,'bg'),opacity:.76},hit('바깥 영역 닫기',0,0,390,y,null,'CLOSE'),group('Popup panel',0,y,390,844-y,[rect(0,0,390,844-y,'panel'),rect(0,0,390,1,'line'),...children,close()])]};}
  screens[search]={...sheet('08 · 종목 검색',96,[text('종목 검색',24,26,23,'fg',600),group('Search field',24,83,342,48,[rect(0,0,342,48,'bg'),icon('search',12,13,'muted',22),text('종목명 또는 코드',44,13,14,'muted',400,270)]),text('최근 검색 · 종목을 선택하세요',24,154,12,'muted'),group('Search result / 삼성전자',24,194,342,77,[text('삼성전자',0,7,17,'fg',600),text('005930 · KRX',0,37,12,'muted'),text('72,800',238,9,17,'fg',500,104),rect(0,76,342,1)],{target:1}),group('Search result / SK하이닉스',24,283,342,77,[text('SK하이닉스',0,7,17,'fg',600),text('000660 · KRX',0,37,12,'muted'),text('173,500',238,9,17,'fg',500,104),rect(0,76,342,1)],{target:skChart}),text('예시 종목 2개로 검색 흐름을 체험할 수 있어요.',24,400,12,'muted',400,342)]),name:'08 · 종목 검색'};
  // A field click leads to a concrete filtered-result state.
  const filtered=clone(screens[search]);filtered.name='검색 결과 · 삼성';
  const fp=filtered.children.find(c=>c.name==='Popup panel');
  fp.children=fp.children.filter(c=>c.name!=='Search result / SK하이닉스');
  fp.children.find(c=>c.name==='Search field').children.find(c=>c.type==='text').value='삼성';
  fp.children.find(c=>c.value==='최근 검색 · 종목을 선택하세요').value='검색 결과  1';
  const filteredIndex=add(filtered);
  screens[search].children.find(c=>c.name==='Popup panel').children.find(c=>c.name==='Search field').target=filteredIndex;
  screens[search].children.find(c=>c.name==='Popup panel').children.find(c=>c.name==='Search field').action='SWAP';
  const filteredField=fp.children.find(c=>c.name==='Search field');filteredField.target=search;filteredField.action='SWAP';
  const stocks=[{name:'삼성전자',code:'005930',price:72800,chart:1},{name:'SK하이닉스',code:'000660',price:173500,chart:skChart}];
  function format(n){return n.toLocaleString('en-US');}
  function receipt(stock,side,quantity){const r=base('완료 · '+stock.name+' '+side+' '+quantity+'주', '모의주문을 접수했어요','PAPER ORDER / 주문 접수',1);r.children.push(icon('check',24,155,'fg',24),text(stock.name+' '+side,24,220,26,'fg',600),text(quantity+'주 · 지정가 '+format(stock.price)+'원',24,265,15,'muted'),text('주문금액  '+format(quantity*stock.price)+'원',24,306,20,'fg',500),text('접수 상태 · 아직 체결되지 않았습니다.',24,375,13,'muted'),text('실제 자금이 사용되지 않는 시연입니다.',24,401,12,'muted'),button('차트로 돌아가기',623,stock.chart),button('매매일지 보기',682,4,'secondary'));replaceNav(r,1);return add(r);}
  for(const stock of stocks){
    const chart=screens[stock.chart];chart.children=clone(chartTemplate.children).filter(c=>c.name!=='Bottom navigation');
    chart.children=chart.children.filter(c=>![55,76,85,126,145,176,205].includes(c.y));
    chart.children=chart.children.filter(c=>c.name!=='매수 전 점검하기  →');
    chart.children.push(group('Chart / Search field',24,54,342,44,[rect(0,0,342,44,'panel'),icon('search',12,11,'muted',20),text('종목명 또는 코드 검색',43,11,13,'muted',400,280)],{target:search,action:'OVERLAY'}),text(stock.name,24,113,23,'fg',600),text(stock.code+' · KRX',24,145,11,'muted'),text(format(stock.price),24,171,32,'fg',500),text('KRW · 모의 시세',199,190,11,'muted',400,160),text('▲ 1.68%   ·   15분봉',24,218,12,'muted'));
    for(const side of ['매수','매도']){
      const modalIndices=[];
      for(const quantity of [1,5]){
        const done=receipt(stock,side,quantity);
        const confirm=base('확인 · '+stock.name+' '+side+' '+quantity+'주','주문을 확인해 주세요','PAPER ORDER / 최종 확인',1,true);
        confirm.children.find(c=>c.name==='Back').target=stock.chart;
        confirm.children.push(text(stock.name+' · '+side,24,146,24,'fg',600),text('지정가 '+format(stock.price)+'원 × '+quantity+'주',24,192,16,'muted'),text('예상 주문금액',24,261,12,'muted'),text(format(stock.price*quantity)+'원',24,291,34,'fg',500),group('Order check',24,383,342,133,[rect(0,0,342,133,'panel'),text('주문 전 확인',16,16,14,'fg',600),text(side==='매수'?'1회 주문한도 100만원 이내':'보유수량 10주 이내',16,50,13,'muted'),text('중복주문 없음 · 모의계좌',16,80,13,'muted')]),text('실제 거래로 전송되지 않는 데모 주문입니다.',24,634,12,'muted'),button('모의 '+side+' 접수하기',692,done));replaceNav(confirm,1);const confirmIndex=add(confirm);
        const modal=sheet(stock.name+' / '+side+' 상세 / '+quantity+'주',244,[text(side+' 주문',24,26,23,'fg',600),text(stock.name+'  ·  '+stock.code,24,70,14,'muted'),text('주문 유형',24,118,12,'muted'),text('지정가',246,118,14,'fg',500,120),rect(24,153,342,1),text('주문 가격',24,174,12,'muted'),text(format(stock.price)+'원',224,171,20,'fg',500,142),text(side==='매수'?'주문 가능 금액 1,000,000원':'보유수량 10주 · 매도 가능 10주',24,211,11,'muted'),text('수량',24,250,12,'muted'),text(quantity+'주',190,250,18,'fg',500,100),group('Quantity / minus',132,241,44,44,[rect(0,0,44,44,'bg'),text('−',15,8,22,'fg',400,22)]),group('Quantity / plus',298,241,44,44,[rect(0,0,44,44,'bg'),text('+',14,8,22,'fg',400,22)]),rect(24,306,342,1),text('예상 주문금액',24,327,13,'muted'),text(format(stock.price*quantity)+'원',185,324,23,'fg',500,181),text('수수료 미반영 · 모의주문',24,376,11,'muted'),button(side+' 주문 확인',424,confirmIndex),text('입력값은 시연용 1주 / 5주로 전환됩니다.',24,495,11,'muted')],stock.chart);
        modalIndices.push(add(modal));
      }
      modalIndices.forEach(idx=>{const p=screens[idx].children.find(c=>c.name==='Popup panel');p.children.find(c=>c.name==='Quantity / minus').target=modalIndices[0];p.children.find(c=>c.name==='Quantity / minus').action='SWAP';p.children.find(c=>c.name==='Quantity / plus').target=modalIndices[1];p.children.find(c=>c.name==='Quantity / plus').action='SWAP';});
      chart.children.push({...button(side,697,modalIndices[0],side==='매수'?'primary':'secondary',side==='매수'?24:201,165),action:'OVERLAY'});
    }
    if(stock.chart===skChart){const axis=chart.children.find(c=>c.name==='Candlestick chart');for(const t of axis.children){if(t.value==='74,000')t.value='176,000';if(t.value==='72,800')t.value='173,500';if(t.value==='71,000')t.value='170,000';}}
    replaceNav(chart,1);
  }
  // Keep only the two supported symbol rows interactive, so selection never opens the wrong stock.
  for(const n of screens[0].children){if(n.name==='Stock / SK하이닉스')n.target=skChart;if(['Stock / NAVER','Stock / Apple'].includes(n.name))delete n.target;if(n.name==='Watchlist tools')n.children.push(hit('관심종목 검색',260,0,82,38,search,'OVERLAY'));}
  // Retain the previous check screen and repair its terminal button.
  const originalDone=receipt(stocks[0],'매수',10);
  screens[5].children.find(c=>c.name==='모의 매수 확인 (데모)').target=originalDone;
  screens[menu].children.push(group('Menu / 거래 전 점검',24,615,342,40,[text('거래 전 점검 체험',0,8,13,'fg',500),icon('arrow',314,7,'muted',20)],{target:2}));
  screens.forEach((s,i)=>{s.key='screen-'+i;});
}
