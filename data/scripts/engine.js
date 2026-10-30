// Движок «цифрового двойника» кофейни Газлайт. Время — минуты от 0:00.
// Параметры откалиброваны по учебному набору (01.04–25.10.2026).
(function (root) {
  function rng(seed) { let s = seed >>> 0; return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  const HOUR_WD = [11, 13, 8, 6, 7, 9, 8, 6, 6, 6, 5, 4, 3, 2], HOUR_WE = [3, 6, 10, 12, 12, 11, 10, 9, 8, 7, 5, 4, 3, 2];
  const SEGMENTS = [['Чемпионы', .355], ['Лояльные', .208], ['Под угрозой ухода', .084], ['Новички', .081], ['Нуждаются во внимании', .064], ['Спящие', .208]];
  const P = {
    openMin: 8 * 60, closeMin: 22 * 60,
    ordersPerDay: { weekday: 98, weekend: 122 },
    pastryStock: { weekday: 12, weekend: 11 }, pastryProb: { weekday: .095, weekend: .115 },
    extraPastry: 6, secondDeliveryAt: 14 * 60, pastryCost: 80, pastryPrice: 230,
    checkTakeaway: 413, checkDineIn: 553, cogsShare: .226, wagePerHour: 350,
    churnUplift: .07, futureValue: 1920, seats: 8, balkQueue: 5, balkProb: .5, payFail: .008, replaceAccept: .55, identified: .47, sla: 5,
  };
  function baristasAt(min, dayType, sc) {
    let n = 1;
    if (dayType === 'weekend' && min >= 600 && min < (sc.weekendLate ? 1080 : 960)) n = 2;
    if (dayType === 'weekday' && sc.morningBarista && min >= 480 && min < 630) n = 2;
    return n;
  }
  function staffHours(dayType, sc) { // кассир 14 ч + бариста 14 ч + доп. смены
    let h = 28;
    if (dayType === 'weekend') h += sc.weekendLate ? 8 : 6;
    if (dayType === 'weekday' && sc.morningBarista) h += 2.5;
    return h;
  }

  function createDay(opts) {
    const dayType = opts.dayType || 'weekday', sc = Object.assign({ morningBarista: false, morePastry: false, weekendLate: false }, opts.scenario || {});
    const R = rng(opts.seed || 1);
    const w = dayType === 'weekend' ? HOUR_WE : HOUR_WD, ws = w.reduce((a, b) => a + b, 0);
    // приходы гостей (Пуассон по часам)
    const arrivals = [];
    w.forEach((wh, i) => { const lam = P.ordersPerDay[dayType] * 1.04 * wh / ws; let k = 0, p = Math.exp(-lam), s = p, u = R(); while (u > s) { k++; p *= lam / k; s += p; }
      for (let j = 0; j < k; j++) { let m = R() * 60; if (dayType === 'weekday' && i <= 1) m = i === 0 ? 15 + R() * 45 : R() * 55; arrivals.push(P.openMin + i * 60 + m); } });
    arrivals.sort((a, b) => a - b);
    let gid = 0;
    const guests = arrivals.map((t) => {
      const h = Math.floor(t / 60), morningWd = dayType === 'weekday' && h < 11;
      const ident = R() < P.identified;
      let seg = null; if (ident) { let u = R(), c = 0; for (const [n, p] of SEGMENTS) { c += p; if (u <= c) { seg = n; break; } } seg = seg || 'Спящие'; }
      const dineP = (morningWd ? .25 : dayType === 'weekend' ? .55 : .42);
      const dine = R() < dineP;
      const items = 1 + (R() < (dine ? .6 : .3) ? 1 : 0) + (R() < (dine ? .2 : .05) ? 1 : 0);
      const wantsPastry = R() < P.pastryProb[dayType] * (dine ? 1.3 : .8) * 1.1;
      let prep = 0; for (let i = 0; i < items; i++) { const u = R(); prep += i === 0 ? 1.8 + R() * 1.0 : u < .45 ? .6 + R() * .7 : u < .85 ? 1.9 + R() * 1.1 : 3 + R() * 2; }
      const check = (dine ? P.checkDineIn : P.checkTakeaway) * (.8 + R() * .4) + (wantsPastry ? P.pastryPrice : 0);
      return { id: ++gid, order: 100000 + gid, t, dine, items, wantsPastry, prep, check: Math.round(check), seg, ident,
        phase: 'outside', mood: 1, events: [], seatTime: 15 + R() * 30, rnd: R() };
    });
    const st = {
      dayType, sc, t: P.openMin - 5, guests, queue: [], cashier: null, cashierFreeAt: 0, kitchen: [], baristas: [],
      waiting: [], seated: [], stock: P.pastryStock[dayType], stockLog: [], delivered2: false,
      log: [], counters: { arrived: 0, registered: 0, paid: 0, ready: 0, issued: 0, lostBalk: 0, lostStock: 0, lostPay: 0, noSeat: 0, replaced: 0 },
      revenue: 0, waits: [], hourly: Array.from({ length: 14 }, () => ({ orders: 0, inSla: 0, withWait: 0, revenue: 0 })),
      writeOff: 0, done: false, R,
    };
    st.stockLog.push([st.t, st.stock]);
    return st;
  }
  const hhmm = (m) => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(Math.floor(m % 60)).padStart(2, '0');
  function ev(st, g, step, source, text) { const r = { t: st.t, order: g ? g.order : null, step, source, text }; st.log.push(r); if (g) g.events.push(r); return r; }

  function step(st, dt) {
    if (st.done) return;
    const end = st.t + dt;
    while (st.t < end && !st.done) {
      const tick = Math.min(.25, end - st.t); st.t += tick; const t = st.t; const R = st.R;
      // поставки
      if (st.sc.morePastry && !st.delivered2 && t >= P.secondDeliveryAt) { st.delivered2 = true; st.stock += P.extraPastry; ev(st, null, 'Склад', 'Склад', `Вторая поставка выпечки: +${P.extraPastry} шт.`); st.stockLog.push([t, st.stock]); }
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
        else if (g.cancelStock) { g.phase = 'left'; g.mood = 0; g.lost = 'выпечка'; st.counters.lostStock++; ev(st, g, 'T07', 'Касса', 'Нет выпечки, замену не принял — отмена'); }
        else {
          g.paidAt = t; st.counters.paid++; st.revenue += 0; g.phase = 'waitPrep'; st.kitchen.push(g); st.waiting.push(g);
          ev(st, g, 'T03', 'Эквайринг', `Оплата ${g.check} ₽ прошла`);
        }
      }
      if (!st.cashier && st.queue.length) {
        const g = st.queue.shift(); st.cashier = g; g.phase = 'order'; st.counters.registered++;
        const qWait = t - g.qAt; if (qWait > 4) g.mood = Math.min(g.mood, .5);
        ev(st, g, 'T01', 'Касса', `Заказ #${g.order}: ${g.items} поз., ${g.dine ? 'в зале' : 'с собой'}${g.seg ? ', карта: ' + g.seg : ''}`);
        let dur = 1.1 + R() * 1.0;
        if (g.wantsPastry) {
          if (st.stock > 0) { st.stock--; st.stockLog.push([t, st.stock]); ev(st, g, 'G01', 'Склад', `Выпечка есть, осталось ${st.stock} шт.`); }
          else { dur += .5; g.mood = Math.min(g.mood, .5); ev(st, g, 'T02', 'Касса', 'Выпечки нет — предложили замену');
            if (R() < P.replaceAccept) { st.counters.replaced++; g.check -= P.pastryPrice - 150; } else { g.cancelStock = true; } }
        }
        if (!g.cancelStock && R() < P.payFail) g.payFailed = true;
        st.cashierFreeAt = t + dur;
      }
      // бар: T04 → T05
      const nb = baristasAt(t, st.dayType, st.sc);
      while (st.baristas.length < nb) st.baristas.push({ freeAt: t, cur: null });
      st.baristas.forEach((b, i) => {
        if (b.cur && t >= b.freeAt) { const g = b.cur; b.cur = null; g.readyAt = t; g.phase = 'pickup'; st.counters.ready++;
          const wait = g.readyAt - g.paidAt; st.waits.push(wait); const hi = Math.min(13, Math.floor(g.paidAt / 60) - 8); const hr = st.hourly[hi]; hr.withWait++; if (wait <= P.sla) hr.inSla++;
          if (wait > 8) g.mood = Math.min(g.mood, .2); else if (wait > P.sla) g.mood = Math.min(g.mood, .55);
          ev(st, g, 'T05', 'Экран заказов', `Готово через ${wait.toFixed(1)} мин`); g.issueAt = t + .3 + R() * .6; }
        if (!b.cur && i < nb && st.kitchen.length) { const g = st.kitchen.shift(); b.cur = g; g.phase = 'prep'; g.prepStart = t; b.freeAt = t + g.prep; ev(st, g, 'T04', 'Экран заказов', `Бариста ${i + 1} готовит`); }
      });
      if (st.baristas.length > nb) st.baristas = st.baristas.filter((b, i) => i < nb || b.cur);
      // выдача T06, зал C5, уход C6
      for (const g of st.waiting) {
        if (g.phase === 'pickup' && t >= g.issueAt) {
          g.phase = 'issued'; st.counters.issued++; st.revenue += g.check; const hi = Math.min(13, Math.floor(g.t / 60) - 8); st.hourly[hi].orders++; st.hourly[hi].revenue += g.check;
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
  function summary(st) {
    const w = st.waits.slice().sort((a, b) => a - b), med = w.length ? w[Math.floor(w.length / 2)] : 0;
    const c = st.counters, lost = c.lostBalk + c.lostStock + c.lostPay;
    const issued = st.guests.filter((g) => g.phase === 'issued' || g.phase === 'seated' || (g.phase === 'left' && !g.lost));
    const happy = issued.filter((g) => g.mood >= .5).length, unhappy = issued.length - happy + lost + c.noSeat;
    const churnRisk = unhappy * P.churnUplift * P.futureValue;
    const labor = staffHours(st.dayType, st.sc) * P.wagePerHour, writeOffCost = st.writeOff * P.pastryCost, cogs = st.revenue * P.cogsShare;
    return { orders: c.issued, arrived: c.arrived, lost, lostBalk: c.lostBalk, lostStock: c.lostStock, lostPay: c.lostPay, noSeat: c.noSeat, replaced: c.replaced,
      sla: w.length ? w.filter((x) => x <= P.sla).length / w.length : 0, median: med, p90: w.length ? w[Math.floor(w.length * .9)] : 0,
      revenue: st.revenue, avgCheck: c.issued ? st.revenue / c.issued : 0, csat: issued.length ? happy / issued.length : 0,
      writeOff: st.writeOff, writeOffCost, labor, cogs, result: st.revenue - cogs - writeOffCost - labor, unhappy, churnRisk,
      resultWithChurn: st.revenue - cogs - writeOffCost - labor - churnRisk };
  }
  function runDay(opts) { const st = createDay(opts); while (!st.done && st.t < 26 * 60) step(st, 5); return summary(st); }
  root.GaslightTwin = { createDay, step, summary, runDay, baristasAt, hhmm, P, SEGMENTS };
})(typeof window !== 'undefined' ? window : globalThis);
