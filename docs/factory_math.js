'use strict';
// Independent deterministic teaching models, also usable from Node tests.
const FactoryMath={
 trend(rows,limit){
  const valid=rows.filter(r=>r.quality==='good'&&Number.isFinite(r.value)&&Number.isFinite(Date.parse(r.source_utc)));
  if(valid.length<10)return {error:'정상 품질 기록이 10개 이상 필요합니다.'};
  const origin=Date.parse(valid[0].source_utc),points=valid.map(r=>[(Date.parse(r.source_utc)-origin)/60000,r.value]);
  const mx=points.reduce((s,p)=>s+p[0],0)/points.length,my=points.reduce((s,p)=>s+p[1],0)/points.length;
  const denom=points.reduce((s,p)=>s+(p[0]-mx)**2,0);if(denom===0)return {error:'서로 다른 시각의 기록이 필요합니다.'};
  const slope=points.reduce((s,p)=>s+(p[0]-mx)*(p[1]-my),0)/denom;
  const last=valid.at(-1),remaining=last.value>=limit?0:slope>0?(limit-last.value)/slope:null;
  return {slope,current:last.value,remaining,excluded:rows.length-valid.length,latest:last.source_utc};
 },
 simulate(cycles,machines,buffer,minutes){
  if(cycles.length!==3||machines.length!==3||cycles.some(x=>!Number.isFinite(x)||x<1||x>600)||machines.some(x=>!Number.isInteger(x)||x<1||x>9)||!Number.isInteger(buffer)||buffer<1||buffer>50||!Number.isFinite(minutes)||minutes<1||minutes>480)throw Error('입력 범위를 확인하세요.');
  const horizon=minutes*60,queues=[[],[]],stations=machines.map(n=>Array.from({length:n},()=>({end:Infinity,born:0,blocked:false})));let now=0,completed=0,totalFlow=0,bornCount=0;
  function settle(){let changed;do{changed=false;
   for(let stage=2;stage>=0;stage--)for(const machine of stations[stage]){
    if(machine.blocked&&(stage===2||queues[stage].length<buffer)){
     if(stage===2){completed++;totalFlow+=now-machine.born;}else queues[stage].push(machine.born);
     machine.blocked=false;machine.end=Infinity;changed=true;
    }
    if(machine.end===Infinity&&!machine.blocked&&(stage===0||queues[stage-1].length)){
     machine.born=stage===0?now:queues[stage-1].shift();if(stage===0)bornCount++;
     machine.end=now+cycles[stage];changed=true;
    }
   }
  }while(changed);}
  settle();while(true){let next=Infinity;for(const stage of stations)for(const m of stage)next=Math.min(next,m.end);if(next>horizon||!Number.isFinite(next))break;now=next;
   for(const stage of stations)for(const m of stage)if(m.end===now){m.end=Infinity;m.blocked=true;}
   settle();
  }
  return {machines,completed,hourly:completed/minutes*60,wip:bornCount-completed,flow:completed?totalFlow/completed:0};
 },
 optimize(cycles,budget,buffer,minutes){if(!Number.isInteger(budget)||budget<3||budget>9)throw Error('총 설비 수는 3~9대입니다.');const results=[];for(let a=1;a<=budget-2;a++)for(let b=1;b<=budget-a-1;b++)results.push(this.simulate(cycles,[a,b,budget-a-b],buffer,minutes));return results.sort((a,b)=>b.completed-a.completed||a.wip-b.wip||a.flow-b.flow);}
};
if(typeof module!=='undefined')module.exports=FactoryMath;
