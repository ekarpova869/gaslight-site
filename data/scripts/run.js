// Прогон сценариев цифрового двойника: 30 одинаковых дней (одни и те же seed в базе и в сценарии).
// node run.js → scenarios.json рядом. Утренние сценарии считаются на будних днях, выпечка и смена до 18:00 — на выходных.
require('./engine.js'); const T = globalThis.GaslightTwin, P = T.P;
const N = 30, seedOf = (s, dayType) => s * 7919 + (dayType === 'weekend' ? 13 : 0);
const SLOW_CASHIER = { batch: .95, cold: 2.1, tea: 2.1, pastry: .95, hot: .95, food: .95 }; // кассир тратит столько же, сколько бар по техкартам
const SC = [
  ['base_wd', 'База, будни', 'weekday', {}],
  ['offload_batch', 'Разгрузка бара: батч вместо V60', 'weekday', { offload: 'batch' }],
  ['offload_full', 'Разгрузка бара: батч + кассир отпускает простые позиции, завтраки заранее', 'weekday', { offload: 'full' }],
  ['offload_full_slow', 'То же, кассир тратит на позицию столько же, сколько бар (верхняя граница)', 'weekday', { offload: 'full' }, () => { const o = P.cashierExtra; P.cashierExtra = SLOW_CASHIER; return () => { P.cashierExtra = o; }; }],
  ['barista_sep_2_5', 'Второй бариста 8:00–10:30, отдельное оборудование', 'weekday', { morningBarista: true }],
  ['barista_shared_2_5', 'Второй бариста 8:00–10:30, общая кофемашина', 'weekday', { morningBarista: true, sharedMachine: true }],
  ['barista_sep_4', 'Второй бариста 8:00–12:00 (смена 4 ч), отдельное оборудование', 'weekday', { morningBarista: true, morningShiftHours: 4 }],
  ['barista_shared_4', 'Второй бариста 8:00–12:00 (смена 4 ч), общая кофемашина', 'weekday', { morningBarista: true, sharedMachine: true, morningShiftHours: 4 }],
  ['pastry_wd11', 'Выпечка в будни 11 шт. (гость уходит без заказа в 45 % случаев)', 'weekday', { pastryRebalance: true }, () => { P.pastryStockNew.weekday = 11; return () => {}; }],
  ['pastry_wd10', 'Выпечка в будни 10 шт. (гость уходит без заказа в 45 % случаев)', 'weekday', { pastryRebalance: true }, () => { P.pastryStockNew.weekday = 10; return () => { P.pastryStockNew.weekday = 11; }; }],
  ['pastry_wd11_drink', 'Выпечка в будни 11 шт. (гость берёт напиток без выпечки)', 'weekday', { pastryRebalance: true, pastryBehavior: 'drink' }, null, { pastryBehavior: 'drink' }],
  ['pastry_wd10_drink', 'Выпечка в будни 10 шт. (гость берёт напиток без выпечки)', 'weekday', { pastryRebalance: true, pastryBehavior: 'drink' }, () => { P.pastryStockNew.weekday = 10; return () => { P.pastryStockNew.weekday = 11; }; }, { pastryBehavior: 'drink' }],
  ['base_we', 'База, выходные', 'weekend', {}],
  ['pastry_we17', 'Выпечка в выходные 17 шт. утром (гость уходит без заказа в 45 % случаев)', 'weekend', { pastryRebalance: true }],
  ['pastry_we17_drink', 'Выпечка в выходные 17 шт. утром (гость берёт напиток без выпечки)', 'weekend', { pastryRebalance: true, pastryBehavior: 'drink' }, null, { pastryBehavior: 'drink' }],
  ['weekend_late', 'Второй бариста в выходные до 18:00', 'weekend', { weekendLate: true }],
];
const F = ['orders', 'lost', 'lostBalk', 'lostStock', 'missedPastry', 'pastrySold', 'sla', 'sla89', 'sla9', 'median', 'p90', 'csat', 'revenue', 'writeOff', 'writeOffCost', 'labor', 'extraLabor', 'cogs', 'result', 'unhappy', 'churn790', 'churn1920', 'resultWith790', 'resultWith1920', 'cashierLoadMorning', 'cashierExtraPerHour', 'queueWaitMorning'];
const runs = (dayType, sc) => Array.from({ length: N }, (_, i) => T.runDay({ seed: seedOf(i + 1, dayType), dayType, scenario: sc }));
const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
const ci95 = (a) => { const m = mean(a), sd = Math.sqrt(a.reduce((x, y) => x + (y - m) ** 2, 0) / (a.length - 1)); return 1.96 * sd / Math.sqrt(a.length); };
const r3 = (v) => +v.toFixed(3);
const out = { meta: { days: N, note: 'Средние за 30 одинаковых дней; delta — разница со своей базой (те же seed), ci95 — полуширина 95 % интервала по дням для разницы', params: { extraWagePerHour: P.extraWagePerHour, wagePerHour: P.wagePerHour, pastryPrice: P.pastryPrice, pastryCost: P.pastryCost, cogsShare: P.cogsShare, futureValueData: P.futureValueData, futureValueOld: P.futureValueOld, churnUplift: P.churnUplift, pastryWalkAway: P.pastryWalkAway, pastryStock: P.pastryStock } }, scenarios: {} };
for (const [key, name, dayType, sc, setup, baseSc] of SC) {
  const undo = setup ? setup() : null;
  const base = runs(dayType, baseSc || {}), cur = runs(dayType, sc);
  if (undo) undo();
  const row = { name, dayType, scenario: sc, mean: {}, delta: {}, ci95: {} };
  for (const f of F) { row.mean[f] = r3(mean(cur.map((r) => r[f]))); const d = cur.map((r, i) => r[f] - base[i][f]); row.delta[f] = r3(mean(d)); row.ci95[f] = r3(ci95(d)); }
  row.negativeDays = { result: cur.filter((r, i) => r.result < base[i].result).length, resultWith790: cur.filter((r, i) => r.resultWith790 < base[i].resultWith790).length, resultWith1920: cur.filter((r, i) => r.resultWith1920 < base[i].resultWith1920).length };
  out.scenarios[key] = row;
}
require('fs').writeFileSync(__dirname + '/scenarios.json', JSON.stringify(out, null, 1));
const pct = (v) => (v * 100).toFixed(1) + ' %', rub = (v) => (v > 0 ? '+' : '') + Math.round(v);
console.log('сценарий | в срок день | 8–9 ч | 9 ч | довольных | отказы выпечки (уход/не хватило) | списано | Δрезультат ±95 % | Δс удерж. 790 | Δс удерж. 1920');
for (const [k, r] of Object.entries(out.scenarios)) { const m = r.mean, d = r.delta, c = r.ci95;
  console.log([k, pct(m.sla), pct(m.sla89), pct(m.sla9), pct(m.csat), m.lostStock.toFixed(2) + '/' + m.missedPastry.toFixed(2), m.writeOff.toFixed(2), rub(d.result) + ' ±' + Math.round(c.result), rub(d.resultWith790) + ' ±' + Math.round(c.resultWith790), rub(d.resultWith1920) + ' ±' + Math.round(c.resultWith1920), 'касса ' + pct(m.cashierLoadMorning) + ' очередь ' + m.queueWaitMorning.toFixed(2)].join(' | ')); }
