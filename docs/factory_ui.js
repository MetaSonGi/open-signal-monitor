'use strict';
function bars(id,series,unit='개'){
 const root=$(id);root.replaceChildren();const max=Math.max(1,...series.map(s=>s[1]));
 for(const [label,value,color] of series){const row=el('div',undefined,'bar-row');row.append(el('span',label));const track=el('div',undefined,'bar-track'),fill=el('div',undefined,'bar-fill');fill.style.width=(value/max*100)+'%';fill.style.background=color||'#16818b';track.append(fill);row.append(track,el('b',number(value,1)+' '+unit));root.append(row);}
 if(!series.length)root.append(el('p','기록이 없습니다.'));
}
function risk(){if(!data)return;const limit=Number($('riskLimit').value),root=$('riskResult');if(!Number.isFinite(limit)||$('riskLimit').value===''){root.textContent='유효한 상한 관리 기준을 입력하세요.';return;}
 const result=FactoryMath.trend(history,limit),signal=data.collector.signals.find(s=>String(s.id)===$('signalSelect').value);
 if(result.error){root.textContent=result.error;return;}
 const age=(Date.now()-Date.parse(result.latest))/1000,stale=!demo&&(!signal?.running||age>Math.max(5,(signal?.interval_s||1)*3));
 root.textContent=(demo?'[합성 예제] ':'')+(signal?.name||'센서')+' · 최근값 '+number(result.current,3)+' · 분당 변화 '+number(result.slope,4)+' · '+(stale?'데이터 지연·수집 중지: 예측 보류':result.remaining===0?'관리 기준 초과 · 점검 필요':result.remaining===null?'상승 추세 없음':number(result.remaining,1)+'분 뒤 상한 도달 추정')+' · 제외 기록 '+result.excluded+'개. 외삽 결과는 고장을 의미하지 않습니다.';
}
function factoryOverview(){if(!data)return;const jobs=data.learning.jobs,events=data.learning.events,signals=data.collector.signals;
 $('overviewNote').textContent=demo?'교육용 합성 생산·재고 예제입니다. 설비 수신 상태와 가동률은 서로 다른 지표입니다.':'실제 작업 최근 100건·POP 최근 50건 기준입니다. 전체 기간 집계가 아닙니다. 설비 상태는 통신 수신 여부이며 가동률·OEE가 아닙니다.';
 bars('productionChart',jobs.flatMap(j=>[[j.code+' 목표',j.target,'#a7bacb'],[j.code+' 양품',j.good],[j.code+' 불량',j.bad,'#d78b54']]));
 const grouped=new Map();for(const e of events){const date=new Date(e.at_utc);if(Number.isNaN(date.valueOf()))continue;date.setMinutes(0,0,0);const key=date.toISOString();const v=grouped.get(key)||[0,0];v[0]+=e.good;v[1]+=e.bad;grouped.set(key,v);}
 const hourly=demo?Array.from({length:8},(_,i)=>[String(9+i)+'시',[40+i*3, i>4?5:1]]):[...grouped].sort((a,b)=>a[0].localeCompare(b[0])).map(([t,v])=>[stamp(t),v]);
 bars('outputChart',hourly.flatMap(([t,v])=>[[t+' 양품',v[0]],[t+' 불량',v[1],'#d78b54']]));
 bars('equipmentChart',data.collector.assets.map(a=>{const connected=signals.some(s=>s.asset_code===a.code&&s.running&&Date.now()-Date.parse(s.ingested_utc)<Math.max(5,(s.interval_s||1)*3)*1000);return [a.code+(connected?' 수신 중':' 미수신·지연'),1,connected?'#16818b':'#b5bcc6'];}),'대');
 const good=jobs.reduce((s,j)=>s+j.good,0),bad=jobs.reduce((s,j)=>s+j.bad,0);bars('qualityChart',[['양품',good],['불량',bad,'#d78b54']]);$('qualityChart').append(el('p','생산 수량 기준 불량률 '+(good+bad?number(100*bad/(good+bad),2)+'%':'—')));
 const inventory=demo?[['원자재 A',800,300,200,140],['부품 B',220,150,100,60],['완제품 C',350,120,80,45]]:[];
 $('warehouseNote').textContent=demo?'합성 재고 예제 · 가용 = 현재고 − 예약, 잔여 일수 = 가용 ÷ 일 소비. 입고 예정·리드타임은 미반영입니다.':'창고 원장 연결 전입니다. 현재 수집 DB에는 입출고·재고 원장이 없어 실제 재고를 추정하지 않습니다.';
 table('warehouse',inventory.map(([name,stock,reserved,safety,daily])=>[name,stock,reserved,stock-reserved,safety,daily,number((stock-reserved)/daily,1),(stock-reserved)<safety?'안전재고 미달':'정상']));risk();
}
function simulateLine(){try{const cycles=['cycleA','cycleB','cycleC'].map(id=>Number($(id).value)),budget=Number($('machineBudget').value),buffer=Number($('bufferSize').value),minutes=Number($('simMinutes').value);const rows=FactoryMath.optimize(cycles,budget,buffer,minutes),best=rows[0],base=FactoryMath.simulate(cycles,[1,1,1],buffer,minutes);
 $('simResult').textContent='입력 조건 내 추천 '+best.machines.join(' / ')+'대 · '+number(best.completed,0)+'개 · 기본 1/1/1 대비 '+number(best.completed-base.completed,0)+'개 · 비교 '+rows.length+'개 조합 (동률이면 재공·흐름시간 순)';
 $('lineLayout').replaceChildren(...best.machines.map((n,i)=>el('div','공정 '+['A','B','C'][i]+'\n'+n+'대 × '+cycles[i]+'초','line-stage')));
 bars('simulationChart',rows.slice(0,6).map(r=>[r.machines.join('/'),r.completed]));table('simRows',rows.map(r=>[r.machines.join(' / '),r.completed,number(r.hourly),r.wip,number(r.flow)]));
 }catch(e){$('simResult').textContent=e.message;$('simRows').replaceChildren();$('simulationChart').replaceChildren();$('lineLayout').replaceChildren();}}
window.addEventListener('factory-update',factoryOverview);window.addEventListener('factory-history',risk);$('riskLimit').addEventListener('input',risk);$('simulateButton').addEventListener('click',simulateLine);simulateLine();factoryOverview();
