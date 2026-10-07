import fs from 'node:fs/promises';
import { Presentation, PresentationFile } from '@oai/artifact-tool';
import { finalizePresentation } from '/Users/mumyon/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations/container_tools/artifact_tool_utils.mjs';
const ROOT='/Users/mumyon/Documents/TradePilot';
const TMP=ROOT+'/tmp/presentation-build';
const SKILL='/Users/mumyon/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations';
const FONT='Apple SD Gothic Neo';
const p=Presentation.create({slideSize:{width:1280,height:720}});
const C={bg:'#0A0A0B',fg:'#F5F5F2',muted:'#A1A1A6',mint:'#F5F5F2',warn:'#A1A1A6'};
const source='출처: 사용자 제공 「인공3학년_병진_tradePilot_기능명세.pdf」';
function text(s,str,x,y,w,h,size=28,color=C.fg,bold=false){
 const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 t.text=str;t.text.style={typeface:FONT,fontSize:size,color,bold,autoFit:'none',verticalAlignment:'middle'};return t;
}
function rect(s,x,y,w,h,color){return s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:color,line:{fill:'none',width:0}});}
function slide(title,notes,pages){
 const s=p.slides.add();s.background.fill=C.bg;
 if(title){text(s,title,64,46,1152,75,44,C.fg,true);rect(s,64,129,1152,1,'#303034');rect(s,64,127,92,3,C.fg);}
 text(s,String(p.slides.items.length).padStart(2,'0'),1172,671,50,24,16,C.muted);
 s.speakerNotes.textFrame.setText(notes+'\n\n'+source+' '+pages+'쪽.\nUI 원본: https://www.figma.com/design/b9uH4rQvpLYpiBjCGgEGZB/TradePilot?node-id=0-1');return s;
}
async function ui(s,n){const bytes=await fs.readFile(ROOT+`/output/TradePilot-Figma-UI/screen-${n}.png`);s.images.add({blob:new Uint8Array(bytes),contentType:'image/png',alt:'TradePilot UI 견본',fit:'contain',position:{left:886,top:136,width:250,height:541}});}
function pair(s,label,body,y,{x=64,w=730}={}){text(s,label,x,y,w,39,29,C.mint,true);text(s,body,x,y+47,w,75,25,C.fg);}
function table(s,values,widths,y=168,height=395){const tb=s.tables.add({rows:values.length,columns:values[0].length,left:64,top:y,width:1152,height,columnWidths:widths,values});tb.borders.assign({fill:'#303034',width:1});for(let r=0;r<values.length;r++){tb.rows[r].height=r===0?57:(height-57)/(values.length-1);for(let c=0;c<values[0].length;c++){const cell=tb.getCell(r,c);cell.fill=r===0?'#151516':C.bg;cell.text.style={typeface:FONT,fontSize:r===0?23:24,color:r===0?C.fg:C.fg,bold:r===0};}}return tb;}
// 1
let s=slide('', '안녕하세요. 병진 팀의 TradePilot을 소개하겠습니다. 주식 예측과 사용자의 거래 전 행동 점검을 결합한 의사결정 보조 시스템입니다. 오늘은 AI가 어떤 기준으로 예측을 제시하는지, 그리고 공포매도와 같은 뇌동매매를 어떻게 구분할지 중심으로 설명하겠습니다.', '1');
rect(s,64,143,80,3,C.fg);
text(s,'TradePilot',64,170,1152,125,96,C.fg,true);
text(s,'AI 주식 예측과 뇌동매매 방지',69,320,1100,65,40,C.mint);
text(s,'캡스톤디자인 핵심 기능 발표',70,401,1100,42,26,C.muted);
rect(s,64,538,1152,1,'#303034');
text(s,'병진 팀\n팀장 202252046 조병익    팀원 202252016 이영진',70,562,1100,78,24,C.fg);
// 2
s=slide('개발 배경', '초보 투자자는 급등한 종목을 뒤늦게 매수하거나 급락 때 계획 없이 매도할 수 있습니다. 손실을 만회하려는 반복 주문도 발생할 수 있습니다. 예측 확률만 제공하면 사용자가 AI 신호에 과도하게 의존할 수 있으므로, 주문 이유와 사전 계획을 함께 점검하는 구조를 설계했습니다. 이 내용은 문제 설정이며 사용자 실험의 결과는 아닙니다.', '1');
text(s,'시장의 움직임과 거래자의 행동을\n함께 확인해야 합니다',64,156,1120,135,43,C.mint,true);
pair(s,'급등 직후 매수','진입 계획보다 상승세를 따라가는 거래',338,{w:530});
pair(s,'급락 직후 매도','손절 원칙을 확인하지 않은 급한 청산',338,{x:672,w:540});
text(s,'TradePilot은 주문 직전에 거래 이유와 계획 준수 여부를 확인합니다.',64,579,1140,70,29,C.fg);
//3
s=slide('핵심 서비스 흐름', '사용자는 종목을 선택해 시세와 AI 예측을 확인합니다. 주문을 입력하면 뇌동매매 점검과 별도의 위험 검사를 거칩니다. 최종 확인 이후 모의주문을 접수하고, 체결 여부와 거래 당시 판단을 일지에 저장합니다. 로그인과 사용자 계획 및 위험한도 설정은 기본 지원 기능입니다. 초기 범위는 모의투자이며 실계좌 연결은 후속 확장입니다.', '1, 7, 9');
const flow=[['01','종목 조회와 AI 예측','가격 방향의 확률과 근거 확인'],['02','주문 입력과 거래 전 점검','행동 패턴과 위험 규칙 검사'],['03','최종 확인과 모의주문','사용자 확인 후 접수 및 체결 관리'],['04','매매일지와 피드백','당시 판단과 이후 결과 비교']];
flow.forEach((a,i)=>{let y=155+i*116;text(s,a[0],64,y,100,62,43,C.mint,true);text(s,a[1],191,y,1010,46,31,C.fg,true);text(s,a[2],191,y+49,1010,40,25,C.muted);});
//4
s=slide('AI 예측 화면', '관심 종목을 선택하거나 주문하기 전에 사용하는 화면입니다. 가격과 거래량, 이동평균, RSI, MACD 등을 입력으로 활용합니다. 상승, 중립, 하락 확률과 생성 시각, 예측 대상 기간, 모델 버전을 제공하도록 설계했습니다. 현재 화면의 62%는 UI 예시입니다. 최대 확률 65% 기준을 적용하면 방향 판단 보류로 표시합니다. 화면에 없는 세 방향 확률과 기준 시각은 구현 시 보완합니다.', '2~3');
pair(s,'입력 데이터','가격과 거래량\n이동평균, RSI, MACD 등 기술지표',163);
pair(s,'사용자가 확인할 정보','상승·중립·하락 확률\n예측 기간, 생성 시각, 주요 판단 근거',335);
text(s,'견본의 62%는 제안 기준상 ‘판단 보류’\n화면의 수치는 예시이며 실제 예측 성과가 아닙니다.',64,540,750,92,25,C.warn);await ui(s,2);
//5
s=slide('AI 예측 기준과 검증', '초기안은 완성된 5분봉으로 다음 1시간을 예측하는 것입니다. 학습 정답은 기준 종가 대비 12개 봉 이후 수익률이 0.5% 초과면 상승, 마이너스 0.5% 미만이면 하락, 사이 구간이면 중립입니다. 세 방향 중 최대 확률이 65% 미만이면 판단을 보류합니다. 중립과 판단 보류는 다른 개념입니다. 모든 수치는 초기 제안값으로 검증 후 최종 시험 전에 고정합니다. 데이터는 시간 순서로 분리하고, 정답 구간이 겹치는 표본을 경계에서 제외하여 미래 정보 유입을 방지합니다. 단순 기준모델과 비교하고 확률 검증, 기간별 성능, 클래스별 성능을 함께 보고합니다. 시세가 부족하거나 지연되면 분석 불가, 장 마감까지 1시간이 남지 않으면 신규 예측을 제공하지 않는 초기 정책입니다.', '2');
table(s,[['항목','초기 설계 기준'],['예측 단위','완성된 5분봉을 사용해 다음 1시간 예측'],['학습 정답','수익률 > +0.5% 상승, < -0.5% 하락, 나머지 중립'],['방향 표시','최대 확률 65% 이상이면 방향 표시, 미만이면 보류']], [220,932],158,303);
text(s,'시간 순서로 검증하고 단순 기준모델과 비교',64,495,1140,55,32,C.mint,true);
text(s,'초기 제안값은 검증 후 확정합니다. 데이터 부족·지연 시 ‘분석 불가’로 표시합니다.',64,589,1140,62,24,C.warn);
//6
s=slide('뇌동매매 4종의 탐지 기준', '네 가지 패턴을 주문 직전에 검사합니다. 급등 추격은 최근 10분간 3% 이상 상승한 종목의 매수 요청입니다. 공포매도는 10분간 3% 이상 하락하고 보유 평가손익이 손실인 상태에서 매도를 요청하는 경우입니다. 복수매매는 세 번 연속 손실 청산 후 30분 안의 신규 또는 추가 매수입니다. 과매매는 현재 주문을 포함해 60분 내 접수 주문이 다섯 건 이상인 경우입니다. 이 수치들은 초기 검증용 제안입니다. 사전에 등록한 계획에 따른 거래와 손실을 줄이는 매도 등은 예외를 적용합니다. 재전송은 중복 집계하지 않고 거절 주문은 제외합니다. 부분 체결은 같은 청산 주문 단위로 합산합니다.', '4~5');
table(s,[['유형','1차 조건','점수'],['급등 추격','매수 + 최근 10분 상승률 ≥ 3%','+30'],['공포매도','매도 + 10분 하락률 ≤ -3% + 보유 평가손실','+30'],['복수매매','3건 연속 손실 청산 + 30분 내 신규·추가 매수','+25'],['과매매','현재 주문 포함 60분 내 접수 주문 ≥ 5건','+20']],[200,832,120],160,395);
text(s,'사전에 저장한 계획에 따른 거래는 예외를 확인합니다.',64,586,1150,45,28,C.mint,true);
text(s,'수치 기준은 초기 제안이며, 감정을 확정하는 진단이 아닌 행동 경고입니다.',64,636,1110,30,21,C.muted);
//7
s=slide('공포매도와 계획된 손절의 구분', '같은 하락 상황에서도 사전에 정한 계획에 따라 결과가 달라집니다. 최근 10분 동안 3.5% 하락했고 보유 평가수익률이 마이너스 2%인 종목의 매도 요청을 가정합니다. 계획된 청산 조건이 확인되지 않으면 공포매도 가능성으로 30점을 부여합니다. 급락 이전에 저장한 손절 조건을 실제로 충족했다면 계획된 손절로 처리하여 해당 점수를 부여하지 않습니다. 주문 직전 입력한 이유만으로 경고가 자동 해제되지는 않습니다. 계획 미등록은 계획 위반으로 단정하지 않습니다. 이 예시는 다른 경고가 없는 경우의 공포매도 항목만 비교한 것입니다.', '4~5');
text(s,'-3.5%',64,150,420,112,76,C.warn,true);text(s,'최근 10분 가격 변화',66,274,450,43,26,C.muted);
text(s,'-2%',685,150,450,112,76,C.fg,true);text(s,'보유 평가수익률',687,274,450,43,26,C.muted);
text(s,'청산 계획이 확인되지 않음',64,380,548,50,31,C.fg,true);text(s,'공포매도 가능성  +30점',64,450,548,61,34,C.warn,true);
text(s,'사전 손절 조건을 충족함',685,380,530,50,31,C.fg,true);text(s,'계획된 손절  해당 항목 0점',685,450,530,61,32,C.mint,true);
text(s,'주문 직전에 작성한 이유만으로 경고를 자동 해제하지 않습니다.',64,597,1150,53,27,C.muted);
//8
s=slide('거래 전 경고와 추가 확인', '각 유형의 점수를 주문당 한 번만 합산하고 100점으로 제한합니다. 네 패턴 외에 사전에 저장한 거래 계획을 위반하면 20점을 더합니다. 0~29점은 일반 확인, 30~59점은 거래 이유 재확인, 60점 이상은 추가 확인 단계입니다. 이 점수는 감정 매매일 확률이 아닙니다. 자료가 부족하면 일부 판단 불가를 함께 표시합니다. 고위험 경고를 확인했더라도 별도 위험 규칙을 위반하면 주문은 실행할 수 없습니다. 견본은 30분간 상승률을 표시하지만 실제 구현에서는 명세의 10분 기준으로 통일하고 총점과 유형별 점수를 보완합니다.', '5~6');
pair(s,'0~29점   낮음','탐지 근거 표시 후 일반 확인',163);
pair(s,'30~59점   주의','탐지 유형과 수치를 확인하고 거래 이유 재확인',301);
pair(s,'60~100점   높음','계획과 주문 내용을 다시 확인한 후 진행 선택',439);
text(s,'계획 위반 +20점, 합계 최대 100점\n행동 경고와 주문 차단은 별도로 판단합니다.',64,585,750,75,24,C.warn);await ui(s,3);
//9
s=slide('위험 검사와 모의주문', '행동 경고를 확인한 다음에는 실제 주문을 실행할 수 있는지 별도로 검사합니다. 1회 주문한도, 일일 손실한도, 중복 주문, 쿨다운, 거래 정지가 핵심 다섯 가지입니다. 손실한도에 도달하면 신규 매수를 막고 보유량을 줄이는 매도는 허용하는 초기 정책을 제안합니다. 동일 주문 식별자는 재실행하지 않습니다. 최종 확인 시 잔액과 보유 수량, 시세를 다시 검사합니다. 지정가 주문은 조건 충족 시 체결하며 접수와 체결을 구분합니다. 오른쪽은 데모 UI로 실제 거래 엔진의 완료 상태를 의미하지 않습니다.', '7~8');
text(s,'5가지 위험 규칙',64,165,750,58,36,C.mint,true);
text(s,'1회 주문한도와 일일 손실한도\n중복주문 방지와 주문 쿨다운\n장애 또는 사용자 요청에 따른 거래 정지',64,248,750,168,29,C.fg);
pair(s,'최종 확인 시 다시 검사','가상 잔액, 보유 수량, 최신 시세 확인\n주문 접수와 체결 상태를 구분하여 기록',445);
text(s,'위험 규칙 위반은 사용자 확인만으로 해제되지 않습니다.',64,615,755,42,23,C.warn);await ui(s,6);
//10
s=slide('매매일지와 개인별 피드백', '거래 당시의 AI 예측, 사용자의 거래 이유, 적용 계획과 경고, 주문 상태를 함께 저장합니다. AI 예측은 실제 1시간 후 가격과 비교하고 사용자의 보유 기간에 따른 손익과는 구분합니다. 원칙 준수율은 계획이 있고 평가할 수 있는 거래를 기준으로 계산하며, 계획 미등록은 별도 표시합니다. 반복 경고와 경고 이후 취소 또는 진행 여부를 통해 다음 거래에서 확인할 점을 알려줍니다. UI의 AI 모의전략 수익률은 초기 버전에서 당시 예측과 실제 변화 비교로 대체합니다. 수익률 비교는 동일 기간, 자금, 비용, 체결 조건을 갖춘 시뮬레이션이 있을 때 사용합니다.', '9~10');
pair(s,'예측과 실제 가격','당시 1시간 예측과 이후 가격 방향 비교',163);
pair(s,'원칙 준수율','평가 가능한 계획 등록 거래를 기준으로 계산',319);
pair(s,'반복 행동 피드백','경고 유형과 주문 취소·진행 여부를 함께 기록',475);
text(s,'화면 수익률은 예시입니다. 초기 버전은 예측·실제 가격 비교를 제공합니다.',64,628,755,42,21,C.muted);await ui(s,5);
//11
s=slide('검증 계획과 완료 목표', '여기 제시한 수치는 달성 결과가 아니라 완료 목표입니다. AI는 시간 순서 기반 시험에서 단순 기준모델과 비교하고 방향 분류 성능, 확률 검증, 판단 보류 비율을 보고합니다. 뇌동매매는 네 패턴의 정상, 위험, 경계값, 계획 예외 사례를 검증하고 시나리오 재현율 90% 이상을 목표로 하며 정밀도와 오탐률도 함께 공개합니다. 모의주문은 100건 이상에서 정확 처리율 99% 이상과 중복 체결 0건을 목표로 합니다. 시세는 데이터 수신 이후 반영 시간을 측정합니다. 사용자 10명 이상에게 기능 만족도를 평가받습니다.', '11');
table(s,[['평가 항목','완료 목표'],['AI 예측','기준모델 비교, 방향 성능·확률 검증·판단 보류 비율 보고'],['뇌동매매 탐지','시나리오 재현율 ≥ 90%, 오탐률·정밀도 함께 보고'],['모의주문','100건 이상, 정확 처리율 ≥ 99%, 중복 체결 0건'],['시세 반영','데이터 수신 후 화면·분석 반영 평균 2초 이내'],['사용자 경험','10명 이상, 만족도 평균 4.0 / 5.0 이상']],[230,922],157,434);
text(s,'모든 수치는 개발 완료 목표이며, 현재 달성한 성과를 의미하지 않습니다.',64,618,1150,42,24,C.warn);
//12
s=slide('초기 구현 범위와 기대효과', '초기에는 AI 방향 예측, 거래 전 점검, 모의주문, 매매일지까지 한 흐름으로 구현합니다. 자동매매, 실계좌 연결, 복잡한 전략 편집은 이후 확장합니다. 최종 목표는 예측 확률과 근거를 이해하고, 자신의 매매 계획을 점검하며, 반복 행동을 기록으로 돌아볼 수 있게 하는 것입니다. 수익률 10% 증가를 필수 완료 기준으로 삼지 않습니다. UI는 Figma 견본에서 시연할 수 있으며 실제 시장 데이터 또는 거래 엔진의 구현 완료를 의미하지는 않습니다. 이상으로 발표를 마치겠습니다. 질문 받겠습니다.', '1, 11~12');
pair(s,'우선 구현','AI 예측, 뇌동매매 점검\n위험 검사, 모의주문, 매매일지',169,{w:1120});
pair(s,'후속 확장','자동매매, 실계좌 연동, 고급 전략 편집',353,{w:1120});
rect(s,64,498,1152,142,'#151516');rect(s,64,498,3,142,C.fg);
text(s,'거래의 근거를 확인하고,\n자신의 매매 습관을 기록으로 돌아봅니다',64,513,1110,115,40,C.mint,true);
await (await PresentationFile.exportPptx(p)).save(TMP+'/candidate.pptx');
for(let i=0;i<p.slides.items.length;i++){
 const sl=p.slides.items[i];const b=await p.export({slide:sl,format:'png',scale:1});await fs.writeFile(TMP+`/slide-${String(i+1).padStart(2,'0')}.png`,new Uint8Array(await b.arrayBuffer()));
 console.log('Rendered',i+1);
}
const result=await finalizePresentation({workspaceDir:ROOT,candidatePath:TMP+'/candidate.pptx',finalPath:ROOT+'/output/presentations/TradePilot-캡스톤-발표.pptx',pythonExecutable:'/Users/mumyon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',integrityValidatorPath:SKILL+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:SKILL+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','5','--require-native-table-slide','6','--require-native-table-slide','11'],requiredNativeTableOwnerSlides:[5,6,11],fontPolicy:{basis:'user_request',families:[FONT]},verifyArtifactToolImport:true,receiptPath:TMP+'/validation.json'});console.log(JSON.stringify(result));
