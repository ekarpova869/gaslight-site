// Движок «цифрового двойника» кофейни Газлайт. Время — минуты от 0:00.
// Параметры откалиброваны по учебному набору (01.04–25.10.2026): поток, состав заказа и время
// приготовления взяты из генератора учебных данных (generate_raw.py) и проверены по fact_sales.
(function (root) {
  function rng(seed) { let s = seed >>> 0; return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  const HOUR_WD = [11, 13, 8, 6, 7, 9, 8, 6, 6, 6, 5, 4, 3, 2], HOUR_WE = [3, 6, 10, 12, 12, 11, 10, 9, 8, 7, 5, 4, 3, 2];
  const SEGMENTS = [['Чемпионы', .355], ['Лояльные', .208], ['Под угрозой ухода', .084], ['Новички', .081], ['Нуждаются во внимании', .064], ['Спящие', .208]];
  // Напитки: доли среди проданных напитков в будни 8:00–10:30 (fact_sales). esp — эспрессо-машина (I01–I08, какао, матча).
  const DRINK_MIX = [['esp', .799], ['cold', .073], ['v60', .043], ['batch', .045], ['tea', .041]];
  // Время работы бара по техкартам генератора, мин: [от, до]
  const PREP = { esp: [1.6, 2.6], cold: [1.6, 2.6], tea: [1.6, 2.6], v60: [3, 5], batch: [.6, 1.3], pastry: [.6, 1.3], hot: [3, 5], food: [.6, 1.3] };
  const KIND_RU = { esp: 'кофе', cold: 'колд брю', tea: 'чай', v60: 'V60', batch: 'батч', pastry: 'выпечка', hot: 'сырники/тост', food: 'еда' };
  const P = {
    openMin: 8 * 60, closeMin: 22 * 60,
    ordersPerDay: { weekday: 106, weekend: 141 },          // все заказы в день по данным (вкл. отмены)
    dayCV: { weekday: .064, weekend: .076 },                 // разброс спроса между днями сверх Пуассона (рост за период, сезон, дождь)
    dineShare: { morningWd: .25, weekend: .55, other: .42 },
    extraItems: { dine: .8, takeaway: .35 },                 // число позиций = 1 + Пуассон (как в генераторе)
    foodProb: { dine: .52, takeaway: .31 },                  // доля еды среди доп. позиций (fact_sales, утро будней)
    pastryShareFood: { morning: 3 / 7, day: 3 / 10 },        // выпечка среди еды: до 13:00 — 3 из 7 позиций, после — 3 из 10
    pastryDemandK: { weekday: 1.03, weekend: 1.09 },        // поправка спроса на выпечку: продажи 8,3 / 10,6 шт., отказы 1,9 в выходной
    hotShareFood: { morning: 2 / 7, day: 2 / 10 },           // сырники и тост (3–5 мин на баре)
    setupMin: [5 / 60, 30 / 60],                             // пауза между оплатой и стартом приготовления (генератор: 5–30 с)
    pastryStock: { weekday: 12, weekend: 11 },
    pastryStockNew: { weekday: 11, weekend: 17 },            // сценарий «перераспределить запас»
    pastryCost: 82, pastryPrice: 241, batchPrice: 250, v60Price: 320,
    checkTakeaway: 405, checkDineIn: 522,                    // чек без выпечки (выпечка добавляется по 241 ₽)
    cogsShare: .221,                                         // себестоимость без выпечки; вместе с выпечкой по 82 ₽ выходит 22,6 %
    wagePerHour: 350, extraWagePerHour: 455,                 // доп. смены: 350 ₽/ч + 30 % взносов
    morningShiftHours: 2.5, weekendLateHours: 2,
    pastryWalkAway: .45,                                     // доля гостей, отказавшихся от всего заказа при нехватке (учебные данные)
    churnUplift: .07, futureValueData: 790, futureValueOld: 1920,
    seats: 8, balkQueue: 5, balkProb: .5, payFail: .008, identified: .47, sla: 5,
    cashierMin: [40 / 60, 120 / 60],                         // приём заказа и оплата, мин (генератор: 40–120 с)
    offloadFrom: 8 * 60, offloadTo: 10.5 * 60,
    cashierExtra: { batch: .5, cold: .5, tea: .8, pastry: .4, hot: .4, food: .4 }, // работа кассира за позицию, мин
  };
  const DEFAULT_SC = { offload: 'none', morningBarista: false, sharedMachine: false, morningShiftHours: null, pastryRebalance: false, weekendLate: false, pastryBehavior: 'walkaway' };
  const scOf = (s) => Object.assign({}, DEFAULT_SC, s || {});
  const morningEnd = (sc) => 480 + 60 * (sc.morningShiftHours || P.morningShiftHours);
  function baristasAt(min, dayType, sc) {
    sc = scOf(sc); let n = 1;
    if (dayType === 'weekend' && min >= 600 && min < (sc.weekendLate ? 1080 : 960)) n = 2;
    if (dayType === 'weekday' && sc.morningBarista && min >= 480 && min < morningEnd(sc)) n = 2;
    return n;
  }
  function staffCost(dayType, sc) { // кассир 14 ч + бариста 14 ч (+ 6 ч второго бариста в выходные) по 350 ₽; доп. смены по 455 ₽
    sc = scOf(sc);
    const baseH = 28 + (dayType === 'weekend' ? 6 : 0);
    let extraH = 0;
    if (dayType === 'weekend' && sc.weekendLate) extraH += P.weekendLateHours;
    if (dayType === 'weekday' && sc.morningBarista) extraH += sc.morningShiftHours || P.morningShiftHours;
    return { baseH, extraH, cost: baseH * P.wagePerHour + extraH * P.extraWagePerHour };
  }
  const pick = (R, mix) => { let u = R(), c = 0; for (const [k, p] of mix) { c += p; if (u <= c) return k; } return mix[mix.length - 1][0]; };
  const unif = (R, [a, b]) => a + R() * (b - a);
  function poisson(R, lam) { let k = 0, p = Math.exp(-lam), s = p; const u = R(); while (u > s) { k++; p *= lam / k; s += p; } return k; }

  function createDay(opts) {
    const dayType = opts.dayType || 'weekday', sc = scOf(opts.scenario);
    const R = rng(opts.seed || 1);
    const w = dayType === 'weekend' ? HOUR_WE : HOUR_WD, ws = w.reduce((a, b) => a + b, 0);
    // приходы гостей (Пуассон по часам, внутри часа равномерно — как в генераторе)
    const arrivals = [], z = Math.sqrt(-2 * Math.log(1 - R())) * Math.cos(2 * Math.PI * R());
    const dayK = opts.dayFactor || Math.max(.7, 1 + P.dayCV[dayType] * z);
    w.forEach((wh, i) => { const k = poisson(R, P.ordersPerDay[dayType] * dayK * wh / ws); for (let j = 0; j < k; j++) arrivals.push(P.openMin + i * 60 + R() * 60); });
    arrivals.sort((a, b) => a - b);
    let gid = 0;
    const guests = arrivals.map((t) => {
      const h = Math.floor(t / 60), morningWd = dayType === 'weekday' && h < 11;
      const ident = R() < P.identified;
      let seg = null; if (ident) { let u = R(), c = 0; for (const [n, p] of SEGMENTS) { c += p; if (u <= c) { seg = n; break; } } seg = seg || 'Спящие'; }
      const dineP = morningWd ? P.dineShare.morningWd : dayType === 'weekend' ? P.dineShare.weekend : P.dineShare.other;
      const dine = R() < dineP;
      const n = 1 + poisson(R, dine ? P.extraItems.dine : P.extraItems.takeaway);
      const per = h <= 12 ? 'morning' : 'day';
      const kinds = [pick(R, DRINK_MIX)];
      for (let i = 1; i < n; i++) {
        if (R() < P.foodProb[dine ? 'dine' : 'takeaway']) {
          const u = R(), ps = P.pastryShareFood[per] * P.pastryDemandK[dayType], hs = P.hotShareFood[per];
          kinds.push(u < ps ? 'pastry' : u < ps + hs ? 'hot' : 'food');
        } else kinds.push(pick(R, DRINK_MIX));
      }
      const times = kinds.map((k) => unif(R, PREP[k]));
      const nPastry = kinds.filter((k) => k === 'pastry').length;
      const base = (dine ? P.checkDineIn : P.checkTakeaway) * (.8 + R() * .4);
      return { id: ++gid, order: 100000 + gid, t, dine, items: n, kinds, times, wantsPastry: nPastry > 0, nPastry, setup: unif(R, P.setupMin),
        check: Math.round(base + nPastry * P.pastryPrice), seg, ident, phase: 'outside', mood: 1, events: [], seatTime: 15 + R() * 30, rnd: R(), u: [R(), R()] };
    });
    const st = {
      dayType, sc, t: P.openMin - 5, guests, queue: [], cashier: null, cashierFreeAt: 0, kitchen: [], baristas: [], machineFreeAt: 0,
      waiting: [], seated: [], stock: (sc.pastryRebalance ? P.pastryStockNew : P.pastryStock)[dayType], stockLog: [],
      log: [], counters: { arrived: 0, registered: 0, paid: 0, ready: 0, issued: 0, lostBalk: 0, lostStock: 0, lostPay: 0, noSeat: 0, replaced: 0, missedPastry: 0, pastrySold: 0, v60ToBatch: 0, offloaded: 0 },
      revenue: 0, pastryRevenue: 0, cashierBusyMorning: 0, cashierExtraMorning: 0, qWaitMorning: [0, 0], waits: [],
      hourly: Array.from({ length: 14 }, () => ({ orders: 0, inSla: 0, withWait: 0, revenue: 0 })),
      writeOff: 0, done: false, R,
    };
    st.stockLog.push([st.t, st.stock]);
    return st;
  }
  const hhmm = (m) => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(Math.floor(m % 60)).padStart(2, '0');
  function ev(st, g, step, source, text) { const r = { t: st.t, order: g ? g.order : null, step, source, text }; st.log.push(r); if (g) g.events.push(r); return r; }

  // Разгрузка бара в будни 8:00–10:30: меняет состав работы бара и добавляет работу кассиру
  function applyOffload(st, g, t) {
    const sc = st.sc; let extra = 0;
    if (st.dayType !== 'weekday' || sc.offload === 'none' || t < P.offloadFrom || t >= P.offloadTo) return 0;
    g.kinds = g.kinds.map((k, i) => { if (k !== 'v60') return k; st.counters.v60ToBatch++; g.check -= P.v60Price - P.batchPrice; g.times[i] = unif(st.R, PREP.batch); return 'batch'; });
    if (sc.offload === 'full') {
      g.kinds.forEach((k, i) => { if (P.cashierExtra[k] != null && g.times[i] > 0) { extra += P.cashierExtra[k]; g.times[i] = 0; st.counters.offloaded++; } });
    }
    return extra;
  }

  function step(st, dt) {
    if (st.done) return;
    const end = st.t + dt;
    while (st.t < end && !st.done) {
      const tick = Math.min(.25, end - st.t); st.t += tick; const t = st.t; const R = st.R;
      // приходы
      for (const g of st.guests) {
        if (g.phase !== 'outside' || g.t > t) continue;
        st.counters.arrived++;
        if (st.queue.length >= P.balkQueue && R() < P.balkProb) { g.phase = 'left'; g.mood = 0; g.lost = 'очередь'; st.counters.lostBalk++; ev(st, g, 'C2', 'Хронометраж', 'Увидел очередь и ушёл без заказа'); continue; }
        g.phase = 'queue'; g.qAt = t; st.queue.push(g); ev(st, g, 'C1→C2', 'Хронометраж', 'Пришёл, встал в очередь');
      }
      // касса: T01 → G01 → (T02) → T03/G03
      if (st.cashier && t >= st.cashierFreeAt) {
        const g = st.cashier; st.cashier = null;
        if (g.payFailed) { g.phase = 'left'; g.mood = 0; g.lost = 'оплата'; st.counters.lostPay++; ev(st, g, 'T07', 'Эквайринг', 'Оплата не прошла, заказ отменён'); }
        else if (g.cancelStock) { g.phase = 'left'; g.mood = 0; g.lost = 'выпечка'; st.counters.lostStock++; ev(st, g, 'T07', 'Касса', 'Нет выпечки, гость отказался от всего заказа'); }
        else {
          g.paidAt = t; st.counters.paid++; g.phase = 'waitPrep'; st.waiting.push(g);
          ev(st, g, 'T03', 'Эквайринг', `Оплата ${g.check} ₽ прошла`);
          if (g.times.reduce((a, x) => a + x, 0) <= 0) finish(st, g, t); // всё отпустил кассир: бар не нужен, гость не ждёт очереди к бару
          else st.kitchen.push(g);
        }
      }
      if (!st.cashier && st.queue.length) {
        const g = st.queue.shift(); st.cashier = g; g.phase = 'order'; st.counters.registered++;
        const qWait = t - g.qAt; if (qWait > 4) g.mood = Math.min(g.mood, .5);
        if (g.t >= P.offloadFrom && g.t < P.offloadTo) { st.qWaitMorning[0] += qWait; st.qWaitMorning[1]++; }
        ev(st, g, 'T01', 'Касса', `Заказ #${g.order}: ${g.kinds.map((k) => KIND_RU[k]).join(', ')}, ${g.dine ? 'в зале' : 'с собой'}${g.seg ? ', карта: ' + g.seg : ''}`);
        let dur = unif(R, P.cashierMin);
        if (g.nPastry) {
          const got = Math.min(st.stock, g.nPastry), miss = g.nPastry - got;
          if (got) { st.stock -= got; st.stockLog.push([t, st.stock]); ev(st, g, 'G01', 'Склад', `Выпечка есть, осталось ${st.stock} шт.`); }
          if (miss) {
            dur += .5; g.mood = Math.min(g.mood, .5); st.counters.missedPastry++;
            if (st.sc.pastryBehavior === 'walkaway' && g.u[0] < P.pastryWalkAway) {
              g.cancelStock = true; if (got) { st.stock += got; st.stockLog.push([t, st.stock]); }
              ev(st, g, 'T02', 'Касса', 'Выпечки нет');
            } else {
              st.counters.replaced++; let left = miss;
              for (let i = g.kinds.length - 1; i >= 0 && left; i--) if (g.kinds[i] === 'pastry') { g.kinds.splice(i, 1); g.times.splice(i, 1); left--; }
              g.items = g.kinds.length; g.nPastry = got; g.check -= miss * P.pastryPrice;
              ev(st, g, 'T02', 'Касса', 'Выпечки нет, взял заказ без неё');
            }
          }
        }
        if (!g.cancelStock) {
          const extra = applyOffload(st, g, t); dur += extra;
          if (t >= P.offloadFrom && t < P.offloadTo) st.cashierExtraMorning += extra;
          if (R() < P.payFail) g.payFailed = true;
        }
        if (t >= P.offloadFrom && t < P.offloadTo) st.cashierBusyMorning += dur;
        st.cashierFreeAt = t + dur;
      }
      // бар: T04 → T05
      const nb = baristasAt(t, st.dayType, st.sc);
      while (st.baristas.length < nb) st.baristas.push({ freeAt: t, cur: null });
      st.baristas.forEach((b, i) => {
        if (b.cur && t >= b.freeAt) { const g = b.cur; b.cur = null; finish(st, g, t); }
        if (!b.cur && i < nb && st.kitchen.length) {
          const g = st.kitchen.shift(); const work = g.times.reduce((a, x) => a + x, 0);
          if (work <= 0) { finish(st, g, t); return; }       // всё отпустил кассир, бар не нужен
          b.cur = g; g.phase = 'prep'; g.prepStart = t;
          const start = t + g.setup;
          if (st.sc.sharedMachine && st.dayType === 'weekday') { // общая кофемашина: эспрессо-часть заказа идёт по очереди
            const m = g.kinds.reduce((a, k, j) => a + (k === 'esp' ? g.times[j] : 0), 0), rest = work - m;
            if (m > 0) { const ms = Math.max(start + rest, st.machineFreeAt); st.machineFreeAt = ms + m; b.freeAt = ms + m; }
            else b.freeAt = start + work;                      // в заказе нет эспрессо — машина не нужна
          } else b.freeAt = start + work;
          ev(st, g, 'T04', 'Экран заказов', `Бариста ${i + 1} готовит`);
        }
      });
      if (st.baristas.length > nb) st.baristas = st.baristas.filter((b, i) => i < nb || b.cur);
      // выдача T06, зал C5, уход C6
      for (const g of st.waiting) {
        if (g.phase === 'pickup' && t >= g.issueAt) {
          g.phase = 'issued'; st.counters.issued++; st.revenue += g.check; st.counters.pastrySold += g.nPastry; st.pastryRevenue += g.nPastry * P.pastryPrice;
          const hi = Math.min(13, Math.floor(g.t / 60) - 8); st.hourly[hi].orders++; st.hourly[hi].revenue += g.check;
          ev(st, g, 'T06', 'Экран заказов', `Выдан, ${g.check} ₽`);
          if (g.dine) { if (st.seated.length < P.seats) { g.phase = 'seated'; g.leaveAt = t + g.seatTime; st.seated.push(g); ev(st, g, 'C5', 'Касса', 'Сел за стол'); }
            else { g.phase = 'left'; g.mood = Math.min(g.mood, .4); st.counters.noSeat++; ev(st, g, 'C5', 'Опрос', 'Нет свободных мест — ушёл с заказом'); g.done = true; } }
          else { g.phase = 'left'; g.done = true; }
          if (g.phase === 'left') ev(st, g, 'C6', 'Опрос', g.mood >= .8 ? 'Доволен: оценка 5' : g.mood >= .5 ? 'Оценка 4' : 'Недоволен: оценка 2');
        }
        if (g.phase === 'seated' && t >= g.leaveAt) { g.phase = 'left'; g.done = true; st.seated = st.seated.filter((x) => x !== g); ev(st, g, 'C6', 'Опрос', g.mood >= .8 ? 'Доволен: оценка 5' : g.mood >= .5 ? 'Оценка 4' : 'Недоволен: оценка 2'); }
      }
      st.waiting = st.waiting.filter((g) => !g.done);
      if (t >= P.closeMin && !st.queue.length && !st.cashier && !st.kitchen.length && st.baristas.every((b) => !b.cur) && !st.waiting.some((g) => g.phase !== 'seated')) {
        st.writeOff = st.stock; if (st.stock > 0) ev(st, null, 'Склад', 'Склад', `Закрытие: списано ${st.stock} шт. выпечки`);
        st.done = true;
      }
    }
  }
  function finish(st, g, t) {
    g.readyAt = t; g.phase = 'pickup'; st.counters.ready++;
    const wait = g.readyAt - g.paidAt; st.waits.push(wait); const hi = Math.min(13, Math.floor(g.paidAt / 60) - 8); const hr = st.hourly[hi]; hr.withWait++; if (wait <= P.sla) hr.inSla++;
    if (wait > 8) g.mood = Math.min(g.mood, .2); else if (wait > P.sla) g.mood = Math.min(g.mood, .55);
    ev(st, g, 'T05', 'Экран заказов', `Готово через ${wait.toFixed(1)} мин`); g.issueAt = t + .3 + st.R() * .6;
  }
  function summary(st) {
    const w = st.waits.slice().sort((a, b) => a - b), med = w.length ? w[Math.floor(w.length / 2)] : 0;
    const c = st.counters, lost = c.lostBalk + c.lostStock + c.lostPay;
    const issued = st.guests.filter((g) => g.phase === 'issued' || g.phase === 'seated' || (g.phase === 'left' && !g.lost));
    const happy = issued.filter((g) => g.mood >= .5).length, unhappy = issued.length - happy + lost + c.noSeat;
    const hs = (a, b) => { let i = 0, n = 0; for (let h = a; h <= b; h++) { i += st.hourly[h].inSla; n += st.hourly[h].withWait; } return n ? i / n : 0; };
    const sc = staffCost(st.dayType, st.sc), labor = sc.cost, extraLabor = sc.extraH * P.extraWagePerHour;
    const writeOffCost = st.writeOff * P.pastryCost, cogs = (st.revenue - st.pastryRevenue) * P.cogsShare + c.pastrySold * P.pastryCost;
    const result = st.revenue - cogs - writeOffCost - labor;
    const churn790 = unhappy * P.churnUplift * P.futureValueData, churn1920 = unhappy * P.churnUplift * P.futureValueOld;
    return { orders: c.issued, arrived: c.arrived, lost, lostBalk: c.lostBalk, lostStock: c.lostStock, lostPay: c.lostPay, noSeat: c.noSeat, replaced: c.replaced,
      missedPastry: c.missedPastry, pastrySold: c.pastrySold, v60ToBatch: c.v60ToBatch, offloaded: c.offloaded,
      sla: w.length ? w.filter((x) => x <= P.sla).length / w.length : 0, sla89: hs(0, 1), sla9: hs(1, 1), median: med, p90: w.length ? w[Math.floor(w.length * .9)] : 0,
      revenue: st.revenue, avgCheck: c.issued ? st.revenue / c.issued : 0, csat: issued.length ? happy / issued.length : 0,
      cashierLoadMorning: st.cashierBusyMorning / 150, cashierExtraPerHour: st.cashierExtraMorning / 2.5, queueWaitMorning: st.qWaitMorning[1] ? st.qWaitMorning[0] / st.qWaitMorning[1] : 0,
      writeOff: st.writeOff, writeOffCost, labor, extraLabor, cogs, result, unhappy,
      churn790, churn1920, resultWith790: result - churn790, resultWith1920: result - churn1920 };
  }
  function runDay(opts) { const st = createDay(opts); while (!st.done && st.t < 26 * 60) step(st, 5); return summary(st); }
  root.GaslightTwin = { createDay, step, summary, runDay, baristasAt, staffCost, hhmm, P, SEGMENTS, KIND_RU, DEFAULT_SC };
})(typeof window !== 'undefined' ? window : globalThis);
