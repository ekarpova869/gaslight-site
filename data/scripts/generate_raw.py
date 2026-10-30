"""Учебный генератор сырых выгрузок «Газлайта» (СИНТЕТИКА, seed фиксирован).
Реальные данные кофейни недоступны, поэтому выгрузки моделируют форматы типичных систем
(касса, эквайринг, экран заказов, лояльность, Google Sheets, Google Forms, отзывы).
Спрос зависит от реальной погоды из raw/weather_openmeteo.json.
В выгрузки намеренно добавлены дефекты, которые должен исправить ETL."""
import json, hashlib, random
import numpy as np, pandas as pd

rng = np.random.default_rng(2026)
random.seed(2026)
RAW = "raw/"

# ---------- меню и техкарты (источник 4) ----------
MENU = [  # item_id, название, категория, цена, себестоимость, холодный напиток
    ("I01", "Эспрессо", "Кофе эспрессо", 190, 38, 0), ("I02", "Американо", "Кофе эспрессо", 220, 40, 0),
    ("I03", "Капучино 0,3", "Кофе эспрессо", 290, 62, 0), ("I04", "Флэт уайт", "Кофе эспрессо", 310, 66, 0),
    ("I05", "Латте 0,4", "Кофе эспрессо", 330, 70, 0), ("I06", "Раф ванильный", "Кофе эспрессо", 360, 85, 0),
    ("I07", "Айс латте", "Холодные напитки", 350, 75, 1), ("I08", "Эспрессо-тоник", "Холодные напитки", 370, 82, 1),
    ("I09", "Колд брю", "Холодные напитки", 330, 60, 1), ("I10", "Фильтр V60", "Альтернатива", 320, 70, 0),
    ("I11", "Фильтр батч", "Альтернатива", 250, 45, 0), ("I12", "Чай листовой", "Чай и другое", 260, 35, 0),
    ("I13", "Какао", "Чай и другое", 290, 60, 0), ("I14", "Матча латте", "Чай и другое", 380, 110, 0),
    ("I15", "Круассан", "Выпечка", 210, 70, 0), ("I16", "Круассан с миндалём", "Выпечка", 270, 95, 0),
    ("I17", "Синнабон", "Выпечка", 250, 80, 0), ("I18", "Сырники", "Завтраки", 420, 120, 0),
    ("I19", "Каша овсяная", "Завтраки", 320, 60, 0), ("I20", "Тост с авокадо", "Завтраки", 480, 165, 0),
    ("I21", "Чизкейк", "Десерты", 340, 115, 0), ("I22", "Морковный торт", "Десерты", 360, 120, 0),
    ("I23", "Печенье", "Десерты", 150, 40, 0), ("I24", "Сэндвич с ветчиной", "Завтраки", 390, 140, 0),
]
PRICE_CACHE = {}
menu = pd.DataFrame(MENU, columns=["item_id", "name", "category", "price", "cost", "cold"])
DRINKS = menu[menu.category.isin(["Кофе эспрессо", "Холодные напитки", "Альтернатива", "Чай и другое"])]
FOOD = menu[~menu.index.isin(DRINKS.index)]
# цена эспрессо-напитков поднята на 20 ₽ с 1 августа (изменение прайса в техкартах)
techcards = menu.assign(valid_from="2026-04-01")
upd = menu[menu.category == "Кофе эспрессо"].assign(price=lambda d: d.price + 20, valid_from="2026-08-01")
techcards = pd.concat([techcards, upd])
with pd.ExcelWriter(RAW + "menu_techcards.xlsx") as xw:
    techcards.rename(columns={"item_id": "Код", "name": "Наименование", "category": "Группа",
                              "price": "Цена продажи", "cost": "Себестоимость по техкарте",
                              "cold": "Холодный", "valid_from": "Действует с"}).to_excel(xw, sheet_name="Прайс", index=False)

def price_on(item_id, day):
    key = (item_id, day >= pd.Timestamp("2026-08-01"))
    if key in PRICE_CACHE:
        return PRICE_CACHE[key]
    rows = techcards[(techcards.item_id == item_id) & (techcards.valid_from <= str(day.date()))]
    PRICE_CACHE[key] = int(rows.sort_values("valid_from").iloc[-1].price)
    return PRICE_CACHE[key]


# ---------- персонал и смены (источник 6) ----------
STAFF = [("E1", "Анна", "бариста"), ("E2", "Илья", "бариста"), ("E3", "Мария", "бариста"),
         ("E4", "Дмитрий", "бариста"), ("E5", "Ольга", "кассир"), ("E6", "Сергей", "кассир")]
weather = json.load(open(RAW + "weather_openmeteo.json", encoding="utf-8"))["daily"]
wdf = pd.DataFrame(weather)
wdf["time"] = pd.to_datetime(wdf["time"])
days = list(wdf["time"])

shifts = []
for i, d in enumerate(days):
    weekend = d.dayofweek >= 5
    b = ["E1", "E2", "E3", "E4"]
    shifts.append((d, "08:00", "15:00", b[i % 4], "бариста"))
    shifts.append((d, "15:00", "22:00", b[(i + 2) % 4], "бариста"))
    shifts.append((d, "08:00", "22:00", ["E5", "E6"][i % 2], "кассир"))
    if weekend:  # в выходные второй бариста на 10–16
        shifts.append((d, "10:00", "16:00", b[(i + 1) % 4], "бариста"))
sh = pd.DataFrame(shifts, columns=["date", "start", "end", "employee", "role"])
# Google Sheets: дата как текст «дд.мм», имя вместо кода
names = dict((s[0], s[1]) for s in STAFF)
sh_out = sh.assign(Дата=sh.date.dt.strftime("%d.%m"), Сотрудник=sh.employee.map(names))
sh_out[["Дата", "start", "end", "Сотрудник", "role"]].rename(
    columns={"start": "Начало", "end": "Конец", "role": "Роль"}).to_csv(RAW + "shifts_schedule_gsheets.csv", index=False)

def baristas_at(d, hour):
    s = sh[(sh.date == d) & (sh.role == "бариста")]
    return int(((s.start.str[:2].astype(int) <= hour) & (s.end.str[:2].astype(int) > hour)).sum())

# ---------- клиенты и лояльность (источник 5) ----------
N_CUST = 2600
cust_rate = rng.gamma(0.55, 1.0, N_CUST)           # интенсивность визитов: много редких, немного постоянных
cust_rate /= cust_rate.sum()
cust_dinein = rng.beta(2, 2.5, N_CUST)               # склонность сидеть в зале
cust_food = rng.beta(2, 3, N_CUST)
cust_reg = [days[0] + pd.Timedelta(days=int(x)) for x in rng.integers(-300, 200, N_CUST)]
cust_keys = [hashlib.sha1(f"phone-{i}".encode()).hexdigest()[:10] for i in range(N_CUST)]
src = rng.choice(["Яндекс Карты", "Instagram", "Друзья", "Мимо проходил(а)", "2ГИС", "Не указано"],
                 N_CUST, p=[.24, .14, .2, .22, .08, .12])
pd.DataFrame({"card_hash": cust_keys, "registered": [d.strftime("%Y-%m-%d") for d in cust_reg],
              "how_found": src, "birth_month": rng.integers(1, 13, N_CUST)}).to_csv(
    RAW + "loyalty_customers.csv", index=False)

# ---------- профиль часа ----------
HOURS = np.arange(8, 22)
HOUR_W_WD = np.array([11, 13, 8, 6, 7, 9, 8, 6, 6, 6, 5, 4, 3, 2], float)   # будни: сильный утренний пик
HOUR_W_WE = np.array([3, 6, 10, 12, 12, 11, 10, 9, 8, 7, 5, 4, 3, 2], float)
HOUR_W_WD /= HOUR_W_WD.sum(); HOUR_W_WE /= HOUR_W_WE.sum()

orders, lines, events, pays, obs = [], [], [], [], []
oid = 100000
pid = 500000
for i, d in enumerate(days):
    w = wdf.iloc[i]
    weekend = d.dayofweek >= 5
    trend = 1 + 0.0009 * i                                   # плавный рост базы
    season = 1 + 0.08 * np.sin((d.dayofyear - 120) / 365 * 2 * np.pi)
    rain = w.precipitation_sum > 2
    base = (122 if weekend else 98) * trend * season * (1.08 if rain and weekend else 1) * (0.93 if rain and not weekend else 1)
    if d.month == 8:  # отпуск части постоянных гостей
        base *= 0.9
    n = rng.poisson(base)
    hw = HOUR_W_WE if weekend else HOUR_W_WD
    hours = rng.choice(HOURS, n, p=hw)
    tss = sorted(d + pd.Timedelta(hours=int(h), minutes=float(m)) for h, m in zip(hours, rng.uniform(0, 60, n)))
    croissant_left = 11 if weekend else 12                   # запас выпечки на день
    queue_free = {}                                           # время освобождения барист
    for ts in tss:
        h = ts.hour
        oid += 1
        identified = rng.random() < 0.47
        c = int(rng.choice(N_CUST, p=cust_rate)) if identified else None
        p_din = cust_dinein[c] if c is not None else 0.42
        p_din = p_din * (0.55 if (not weekend and h < 11) else 1.25 if weekend else 1) * (1.2 if rain else 1)
        order_type = "dine_in" if rng.random() < min(p_din, 0.9) else "takeaway"
        # состав заказа
        k = 1 + rng.poisson(0.35 if order_type == "takeaway" else 0.8)
        items = []
        cold_share = np.clip((w.temperature_2m_mean - 8) / 25, 0.02, 0.45)
        for j in range(k):
            pf = (cust_food[c] if c is not None else 0.35) * (1.4 if order_type == "dine_in" else 0.8)
            if j > 0 and rng.random() < min(pf, 0.85):
                f = FOOD
                if h <= 12:
                    f = FOOD[FOOD.category.isin(["Выпечка", "Завтраки"])]
                it = f.sample(1, random_state=int(rng.integers(1e9))).iloc[0]
            else:
                pool = DRINKS[DRINKS.cold == 1] if rng.random() < cold_share else DRINKS[DRINKS.cold == 0]
                wts = np.where(pool.item_id.isin(["I03", "I05", "I02", "I04"]), 3, 1).astype(float)
                it = pool.sample(1, weights=wts, random_state=int(rng.integers(1e9))).iloc[0]
            items.append(it)
        # наличие: выпечка заканчивается к полудню выходного
        status, stage, reason = "issued", None, None
        unavailable = None
        for it in items:
            if it.category == "Выпечка":
                if croissant_left <= 0:
                    unavailable = it.item_id
                else:
                    croissant_left -= 1
        if unavailable is None and rng.random() < 0.006:
            unavailable = items[0].item_id   # прочие стоп-листы
        replaced = None
        if unavailable is not None:
            if rng.random() < 0.55:
                replaced = True
                items = [x for x in items if x.item_id != unavailable] or [DRINKS.iloc[2]]
            else:
                replaced = False
                status, stage, reason = "cancelled", "availability", "нет позиции"
        disc = 0.1 if (c is not None and rng.random() < 0.25) else 0.0   # бонусы лояльности
        amount = sum(round(price_on(it.item_id, d) * (1 - disc)) for it in items)
        created = ts
        # оплата
        paid_at = None
        if status == "issued":
            t = created + pd.Timedelta(seconds=float(rng.uniform(40, 120)))
            attempts = 1 + (rng.random() < 0.025) + (rng.random() < 0.004)
            for a in range(attempts):
                pid += 1
                ok = a == attempts - 1 and not (attempts == 3 and rng.random() < 0.6)
                pays.append((pid, oid, t, amount, rng.choice(["card", "sbp", "cash"], p=[.78, .15, .07]),
                             "success" if ok else "declined", None if ok else rng.choice(["недостаточно средств", "ошибка связи", "отмена клиентом"])))
                t += pd.Timedelta(seconds=float(rng.uniform(20, 60)))
            if pays[-1][5] == "success":
                paid_at = pays[-1][2]
            else:
                status, stage, reason = "cancelled", "payment", "оплата не прошла"
        # приготовление с очередью
        ready_at = issued_at = prep_start = None
        if status == "issued":
            nb = max(1, baristas_at(d, int(h)))
            work = sum(rng.uniform(1.6, 2.6) if it.category in ("Кофе эспрессо", "Холодные напитки", "Чай и другое")
                       else rng.uniform(3, 5) if it.item_id in ("I10", "I18", "I20") else rng.uniform(0.6, 1.3)
                       for it in items)
            slots = queue_free.setdefault(d, [created, created])
            s_idx = 0 if nb == 1 else min((0, 1), key=lambda k: slots[k])
            prep_start = max(paid_at, slots[s_idx]) + pd.Timedelta(seconds=float(rng.uniform(5, 30)))
            ready_at = prep_start + pd.Timedelta(minutes=float(work))
            slots[s_idx] = ready_at
            if rng.random() < 0.004:
                status, stage, reason = "not_picked", "issue", "не забрали"
            else:
                issued_at = ready_at + pd.Timedelta(seconds=float(rng.exponential(40 if order_type == "takeaway" else 25)))
        emp_cash = sh[(sh.date == d) & (sh.role == "кассир")].employee.iloc[0]
        bs = sh[(sh.date == d) & (sh.role == "бариста")]
        emp_bar = bs[(bs.start.str[:2].astype(int) <= h) & (bs.end.str[:2].astype(int) > h)].employee
        emp_bar = emp_bar.iloc[0] if len(emp_bar) else bs.employee.iloc[0]
        orders.append(dict(order_id=oid, created_at=created, order_type=order_type,
                           customer=cust_keys[c] if c is not None else None, status=status, stage=stage,
                           reason=reason, cashier=emp_cash, barista=emp_bar, unavailable=unavailable,
                           replaced=replaced, amount=amount, discount=disc))
        for ln, it in enumerate(items, 1):
            lines.append((oid, ln, it.item_id, it["name"], 1, round(price_on(it.item_id, d) * (1 - disc)), disc))
        events.append((oid, "created", created))
        if paid_at is not None: events.append((oid, "paid", paid_at))
        if prep_start is not None: events.append((oid, "prep_started", prep_start))
        if ready_at is not None:
            events.append((oid, "ready", ready_at)); events.append((oid, "notified", ready_at + pd.Timedelta(seconds=float(rng.uniform(2, 15)))))
        if issued_at is not None: events.append((oid, "issued", issued_at))
        if status == "cancelled": events.append((oid, "cancelled", created + pd.Timedelta(minutes=float(rng.uniform(1, 3)))))

O = pd.DataFrame(orders)
L = pd.DataFrame(lines, columns=["order_id", "line_no", "item_id", "item_name", "qty", "unit_price", "discount"])
print("orders", len(O), "lines", len(L), "days", len(days))

# ---------- кассовая выгрузка (источник 1): еженедельные файлы с дефектами ----------
pos = L.merge(O[["order_id", "created_at", "order_type", "customer", "status", "cashier"]], on="order_id")
pos["item_name"] = pos.item_name.where(rng.random(len(pos)) > 0.04,
                                       pos.item_name.str.lower() + " ")             # разный регистр/пробелы
pos.loc[pos.item_id == "I03", "item_name"] = np.where(rng.random((pos.item_id == "I03").sum()) < 0.3,
                                                      "Cappuccino 0.3", "Капучино 0,3")
pos["order_type"] = pos.order_type.map({"dine_in": "В зале", "takeaway": "С собой"})
pos.loc[rng.random(len(pos)) < 0.02, "order_type"] = None                          # пропуски формата
typo = rng.random(len(pos)) < 0.0015
pos.loc[typo, "unit_price"] = pos.loc[typo, "unit_price"] * 10                      # опечатка в цене
ret = pos[(pos.status == "issued") & (rng.random(len(pos)) < 0.003)].copy()
ret["qty"] = -1; ret["line_no"] = ret.line_no + 50                                 # возвраты строкой с минусом
test = pd.DataFrame({"order_id": range(900001, 900041), "line_no": 1, "item_id": "I01", "item_name": "ТЕСТ",
                     "qty": 1, "unit_price": 1, "discount": 0,
                     "created_at": [days[int(x)] + pd.Timedelta(hours=7, minutes=50) for x in rng.integers(0, len(days), 40)],
                     "order_type": None, "customer": None, "status": "issued", "cashier": "TEST"})
pos = pd.concat([pos, ret, test]).sort_values(["created_at", "order_id", "line_no"])
pos["week"] = pos.created_at.dt.to_period("W-SUN").dt.start_time
pos["Дата/время"] = np.where(pos.created_at.dt.month >= 8, pos.created_at.dt.strftime("%d.%m.%Y %H:%M:%S"),
                             pos.created_at.dt.strftime("%Y-%m-%d %H:%M:%S"))   # смена формата после обновления кассы
pos["Цена"] = pos.unit_price.astype(str).str.replace(".", ",", regex=False)
out_cols = {"order_id": "Чек", "line_no": "Строка", "item_name": "Товар", "qty": "Кол-во", "Цена": "Цена",
            "discount": "Скидка", "Дата/время": "Дата/время", "order_type": "Тип заказа",
            "customer": "Карта", "status": "Статус", "cashier": "Кассир"}
import os
os.makedirs(RAW + "pos_export", exist_ok=True)
weeks = sorted(pos.week.unique())
for wi, wk in enumerate(weeks):
    part = pos[pos.week == wk]
    if wi > 0:  # перекрытие выгрузок: последний день прошлой недели повторно попадает в файл
        prev = pos[(pos.week == weeks[wi - 1]) & (pos.created_at.dt.day_of_week == 6)]
        part = pd.concat([prev.sample(frac=0.25, random_state=wi), part])
    part[list(out_cols)].rename(columns=out_cols).to_csv(
        RAW + f"pos_export/sales_{pd.Timestamp(wk):%Y%m%d}.csv", sep=";", index=False, encoding="cp1251")

# ---------- эквайринг (источник 2): время в UTC ----------
P = pd.DataFrame(pays, columns=["payment_id", "order_id", "ts", "amount", "method", "result", "decline_reason"])
P["ts_utc"] = (P.ts - pd.Timedelta(hours=3)).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
P.drop(columns="ts").to_csv(RAW + "payments_acquiring.csv", index=False)

# ---------- экран заказов / журнал статусов (источник 3) ----------
E = pd.DataFrame(events, columns=["order_id", "event", "ts"])
drop = (E.event == "ready") & (rng.random(len(E)) < 0.05)                            # бариста не нажал «готово»
E = E[~drop]
skew = (E.event == "ready") & (rng.random(len(E)) < 0.004)
E.loc[skew, "ts"] = E.loc[skew, "ts"] - pd.Timedelta(minutes=15)                     # сбой часов планшета
E = pd.concat([E, E.sample(frac=0.006, random_state=1)])                             # повторная отправка события
E["ts"] = E.ts.dt.strftime("%Y-%m-%d %H:%M:%S")
E.sample(frac=1, random_state=2).to_csv(RAW + "order_events_kds.csv", index=False)

# ---------- ручные хронометражи очереди (источник 11): 2 недели ----------
obs_days = [d for d in days if pd.Timestamp("2026-10-12") <= d <= pd.Timestamp("2026-10-25")]
oo = O[O.created_at.dt.normalize().isin(obs_days) & (O.created_at.dt.hour.isin([8, 9, 13, 14, 18]))]
oo = oo.sample(frac=0.6, random_state=3)
q = []
for _, r in oo.iterrows():
    h = r.created_at.hour; wk = r.created_at.day_of_week >= 5
    wait = rng.gamma(2, 1.2 if (h < 10 and not wk) else 0.5)
    q.append((f"OB{len(q)+1:04d}", r.created_at - pd.Timedelta(minutes=wait), r.created_at, r.order_id, "Наблюдатель 1" if len(q) % 2 else "Наблюдатель 2"))
walk = rng.integers(0, len(oo), 40)
for x in walk:  # ушли, не сделав заказ
    r = oo.iloc[x]
    q.append((f"OB{len(q)+1:04d}", r.created_at - pd.Timedelta(minutes=2), None, None, "Наблюдатель 1"))
pd.DataFrame(q, columns=["observation_id", "arrival_at", "service_started_at", "order_id", "observer"]).to_csv(
    RAW + "queue_observations_manual.csv", index=False)

# ---------- опрос по QR на чеке (источник 7) ----------
O2 = O[O.status == "issued"].merge(E[E.event == "ready"].assign(ts=lambda d: pd.to_datetime(d.ts)).drop_duplicates("order_id")[["order_id", "ts"]], on="order_id", how="left")
O2 = O2.merge(P[P.result == "success"][["order_id", "ts"]].rename(columns={"ts": "paid"}), on="order_id", how="left")
O2["wait"] = (O2.ts - O2.paid).dt.total_seconds() / 60
sv = O2[(O2.created_at >= "2026-07-01")].sample(frac=0.035, random_state=4)
resp = []
for _, r in sv.iterrows():
    wt = r.wait if pd.notna(r.wait) else 4
    sc = np.clip(round(rng.normal(4.7 - 0.13 * max(wt - 4, 0), 0.6)), 1, 5)
    ret_int = "Да" if rng.random() < (0.35 + 0.12 * sc) else rng.choice(["Нет", "Не знаю"])
    reason = rng.choice(["вкусный кофе", "атмосфера", "рядом с работой/домом", "бариста", "цены", "ожидание"],
                        p=[.32, .22, .2, .14, .06, .06])
    resp.append((r.created_at + pd.Timedelta(minutes=float(rng.uniform(5, 300))), int(sc),
                 rng.choice(["Взять кофе по пути", "Посидеть/поработать", "Встреча", "Позавтракать"], p=[.42, .24, .16, .18]),
                 ret_int, reason, r.customer if (r.customer is not None and rng.random() < 0.5) else None,
                 "Да" if wt > 7 and rng.random() < 0.6 else "Нет"))
S = pd.DataFrame(resp, columns=["Отметка времени", "Оцените визит (1-5)", "Цель визита", "Придёте снова?",
                                "Главная причина вернуться", "Номер карты (по желанию)", "Ждали дольше, чем ожидали?"])
S.loc[S.sample(frac=0.03, random_state=5).index, "Оцените визит (1-5)"] = None
S["Отметка времени"] = S["Отметка времени"].dt.strftime("%d.%m.%Y %H:%M:%S")
S.to_csv(RAW + "survey_gforms.csv", index=False)

# ---------- отзывы (источники 8, 9): синтетические формулировки по темам ----------
THEMES = {
    "кофе": ["Очень вкусный фильтр, бариста подсказал зерно", "Капучино идеальный, плотная пена", "Кофе кислый, не моё"],
    "атмосфера": ["Уютно, книги и настолки, хочется остаться", "Маленький зал, вечером не было мест"],
    "ожидание": ["Утром ждала кофе минут 10, очередь до двери", "Долго готовят, когда людей много", "Быстро сделали даже в час пик"],
    "выпечка": ["В воскресенье к обеду не осталось круассанов", "Свежие круассаны, очень рекомендую"],
    "персонал": ["Бариста приветливые, помнят мой заказ", "Кассир был невнимателен, перепутали молоко"],
    "цены": ["Цены выше, чем в сетевых, но качество того стоит", "После подорожания стала заходить реже"],
}
def reviews(n, platform, seed):
    r = np.random.default_rng(seed); out = []
    for k in range(n):
        th = r.choice(list(THEMES), p=[.3, .2, .18, .1, .14, .08]); txt = r.choice(THEMES[th])
        neg = any(w in txt for w in ["ждала", "Долго", "не осталось", "невнимателен", "кислый", "не было мест", "реже"])
        rating = int(r.choice([1, 2, 3], p=[.2, .4, .4])) if neg else int(r.choice([4, 5], p=[.25, .75]))
        dd = days[int(r.integers(0, len(days)))]
        out.append((f"{platform[:2].upper()}{k+1:04d}", dd.strftime("%d %B %Y") if platform == "2gis" else dd.strftime("%Y-%m-%d"), rating, txt))
    return pd.DataFrame(out, columns=["review_id", "date", "rating", "text"])
rv_y = reviews(190, "yandex", 11); rv_y.to_csv(RAW + "reviews_yandex.csv", index=False)
rv_g = reviews(70, "2gis", 12)
rv_g = pd.concat([rv_g, rv_y.sample(6, random_state=7).assign(review_id=lambda d: "2G_DUP" + d.review_id.str[-4:])])  # перепубликованные
rv_g.to_csv(RAW + "reviews_2gis.csv", index=False)
print("pos files", len(weeks), "payments", len(P), "events", len(E), "survey", len(S), "obs", len(q))
