require('./engine.js'); const T = globalThis.GaslightTwin;
const scen = {base:{}, morning:{morningBarista:true}, pastry:{morePastry:true}, late:{weekendLate:true}, all:{morningBarista:true,morePastry:true,weekendLate:true}};
const out = {};
for (const dayType of ['weekday','weekend']) for (const [k,sc] of Object.entries(scen)) {
  const rs = []; for (let s=1;s<=30;s++) rs.push(T.runDay({seed:s*7919+(dayType==='weekend'?13:0), dayType, scenario:sc}));
  const avg = (f) => rs.reduce((a,r)=>a+r[f],0)/rs.length;
  out[dayType+'/'+k] = Object.fromEntries(['orders','arrived','lost','lostBalk','lostStock','noSeat','sla','median','p90','revenue','avgCheck','csat','writeOff','writeOffCost','labor','result','unhappy','churnRisk','resultWithChurn'].map(f=>[f, +avg(f).toFixed(3)]));
}
// SLA в 9:00 будней, база
let s9=[0,0]; for (let s=1;s<=30;s++){ const st=T.createDay({seed:s*7919,dayType:'weekday'}); while(!st.done) T.step(st,5); s9[0]+=st.hourly[1].inSla; s9[1]+=st.hourly[1].withWait; }
out.sla9_base = +(s9[0]/s9[1]).toFixed(3);
s9=[0,0]; for (let s=1;s<=30;s++){ const st=T.createDay({seed:s*7919,dayType:'weekday',scenario:{morningBarista:true}}); while(!st.done) T.step(st,5); s9[0]+=st.hourly[1].inSla; s9[1]+=st.hourly[1].withWait; }
out.sla9_morning = +(s9[0]/s9[1]).toFixed(3);
console.log(JSON.stringify(out,null,1)); require('fs').writeFileSync('scenarios.json', JSON.stringify(out,null,1));
