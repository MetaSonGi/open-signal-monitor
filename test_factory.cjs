const assert=require('node:assert/strict');const f=require('./docs/factory_math.js');
const r=f.simulate([10,10,10],[1,1,1],5,1);assert.equal(r.completed,4);assert.equal(r.flow,30);assert(r.wip>=0);
const rows=f.optimize([35,55,28],5,5,60);assert.equal(rows.length,6);assert(rows.every(r=>r.machines.reduce((s,x)=>s+x,0)===5));assert.equal(rows[0].completed,Math.max(...rows.map(r=>r.completed)));
assert.throws(()=>f.optimize([1,2,3],2,5,60));assert.throws(()=>f.simulate([0,2,3],[1,1,1],5,60));
const samples=Array.from({length:12},(_,i)=>({quality:'good',value:10+i,source_utc:new Date(i*60000).toISOString()}));const t=f.trend(samples,30);assert.equal(t.slope,1);assert.equal(t.remaining,9);assert.equal(f.trend(samples,20).remaining,0);assert(f.trend(samples.slice(0,3),20).error);
console.log('Simulation and trend assertions passed',rows[0]);
