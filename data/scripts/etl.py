"""ETL «Газлайт»: raw/ -> clean/ + model/ (звезда) + etl_log.csv + rejected.csv.
Воспроизводимо: python etl.py (исходники в raw/ не изменяются)."""
import glob, json, os, re
import numpy as np, pandas as pd

os.makedirs("clean", exist_ok=True); os.makedirs("model", exist_ok=True)
LOG, REJ = [], []
def log(step, source, rule, rows_in, rows_out, note=""):
    LOG.append(dict(step=step, source=source, rule=rule, rows_in=rows_in, rows_out=rows_out,
                    affected=rows_in - rows_out if rows_out <= rows_in else rows_out - rows_in, note=note))
def reject(df, source, reason):
    if len(df):
        REJ.append(df.astype(str).assign(_source=source, _reason=reason)
                   .apply(lambda r: pd.Series({"source": r._source, "reason": r._reason,
                                               "record": "; ".join(f"{k}={v}" for k, v in r.items() if not k.startswith("_"))}), axis=1))

# ===== EXTRACT =====
pos = pd.concat([pd.read_csv(f, sep=";", encoding="cp1251", dtype=str).assign(_file=os.path.basename(f))
                 for f in sorted(glob.glob("raw/pos_export/*.csv"))], ignore_index=True)
techcards = pd.read_excel("raw/menu_techcards.xlsx", sheet_name="Прайс")
pay = pd.read_csv("raw/payments_acquiring.csv")
ev = pd.read_csv("raw/order_events_kds.csv")
loy = pd.read_csv("raw/loyalty_customers.csv")
shifts = pd.read_csv("raw/shifts_schedule_gsheets.csv", dtype=str)
survey = pd.read_csv("raw/survey_gforms.csv")
rv_y, rv_g = pd.read_csv("raw/reviews_yandex.csv"), pd.read_csv("raw/reviews_2gis.csv")
obs = pd.read_csv("raw/queue_observations_manual.csv")
w = json.load(open("raw/weather_openmeteo.json", encoding="utf-8"))
log("E", "pos_export", "склейка 30 недельных файлов", 0, len(pos))

# ===== TRANSFORM: касса =====
n = len(pos)
pos = pos.rename(columns={"Чек": "order_id", "Строка": "line_no", "Товар": "item_name_raw", "Кол-во": "qty",
                          "Цена": "unit_price", "Скидка": "discount", "Дата/время": "dt_raw",
                          "Тип заказа": "order_type_raw", "Карта": "customer_key", "Статус": "status", "Кассир": "cashier"})
# 1. даты: два формата (ISO до августа, дд.мм.гггг после обновления кассы)
iso = pd.to_datetime(pos.dt_raw, format="%Y-%m-%d %H:%M:%S", errors="coerce")
ru = pd.to_datetime(pos.dt_raw, format="%d.%m.%Y %H:%M:%S", errors="coerce")
pos["created_at"] = iso.fillna(ru)
log("T1", "pos_export", "дата: 2 формата -> datetime", n, int(pos.created_at.notna().sum()),
    f"ISO {iso.notna().sum()}, дд.мм.гггг {ru.notna().sum()}")
# 2. числа: десятичная запятая
pos["unit_price"] = pos.unit_price.str.replace(",", ".").astype(float)
pos[["qty", "discount"]] = pos[["qty", "discount"]].astype(float)
pos[["order_id", "line_no"]] = pos[["order_id", "line_no"]].astype(int)
# 3. дубли из-за перекрытия выгрузок
d = pos.duplicated(["order_id", "line_no"], keep="first")
reject(pos[d].drop(columns="_file"), "pos_export", "дубль строки (перекрытие недельных выгрузок)")
pos = pos[~d]; log("T2", "pos_export", "удаление дублей по (order_id, line_no)", n, len(pos))
# 4. тестовые чеки
t = (pos.cashier == "TEST") | (pos.item_name_raw.str.upper() == "ТЕСТ")
reject(pos[t].drop(columns="_file"), "pos_export", "тестовый чек")
k = len(pos); pos = pos[~t]; log("T3", "pos_export", "исключение тестовых чеков", k, len(pos))
# 5. возвраты (qty<0) — в отдельную таблицу, не в выручку
returns = pos[pos.qty < 0].copy(); k = len(pos); pos = pos[pos.qty > 0]
returns.drop(columns="_file").to_csv("clean/returns.csv", index=False)
log("T4", "pos_export", "возвраты qty<0 вынесены в clean/returns.csv", k, len(pos))
# 6. справочник названий: нормализация к item_id
cur = techcards.sort_values("Действует с").drop_duplicates("Код", keep="last")
canon = {re.sub(r"\s+", " ", n.strip().lower()).replace(".", ","): c for n, c in zip(cur["Наименование"], cur["Код"])}
canon["cappuccino 0,3"] = "I03"
pos["item_id"] = (pos.item_name_raw.str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
                  .str.replace(".", ",", regex=False).map(canon))
log("T5", "pos_export", "названия -> item_id по справочнику", len(pos), int(pos.item_id.notna().sum()),
    f"уникальных написаний {pos.item_name_raw.nunique()} -> {pos.item_id.nunique()} товаров")
# 7. аномальные цены: > 3× прайса — опечатка ×10, восстанавливаем по прайсу на дату
tc = techcards.rename(columns={"Код": "item_id", "Цена продажи": "list_price", "Действует с": "valid_from"})
tc["valid_from"] = pd.to_datetime(tc.valid_from)
pos = pos.sort_values("created_at")
pos = pd.merge_asof(pos, tc[["item_id", "list_price", "valid_from"]].sort_values("valid_from"),
                    left_on="created_at", right_on="valid_from", by="item_id")
expected = (pos.list_price * (1 - pos.discount)).round()
anom = pos.unit_price > expected * 3
reject(pos[anom][["order_id", "line_no", "item_id", "unit_price"]], "pos_export", "цена >3× прайса: исправлена на прайс со скидкой")
pos.loc[anom, "unit_price"] = expected[anom]
log("T6", "pos_export", "аномальная цена (>3× прайса) -> прайс", len(pos), len(pos), f"исправлено {anom.sum()}")
# 8. формат заказа
pos["order_type"] = pos.order_type_raw.map({"В зале": "dine_in", "С собой": "takeaway"})
miss = pos.groupby("order_id").order_type.transform(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan)
filled = pos.order_type.isna() & miss.notna()
pos["order_type"] = pos.order_type.fillna(miss).fillna("unknown")
log("T7", "pos_export", "пропуск формата: из других строк чека, иначе 'unknown'", len(pos), len(pos),
    f"восстановлено {filled.sum()}, unknown {(pos.order_type == 'unknown').sum()}")
pos["customer_key"] = pos.customer_key.fillna("ANON")

# ===== платежи: UTC -> Europe/Moscow =====
pay["ts"] = pd.to_datetime(pay.ts_utc, utc=True).dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
log("T8", "payments", "время UTC -> МСК (+3 ч)", len(pay), len(pay))
paid = pay[pay.result == "success"].groupby("order_id").ts.min().rename("paid_at")
attempts = pay.groupby("order_id").size().rename("payment_attempts")
pay.to_csv("clean/payments.csv", index=False)

# ===== события =====
k = len(ev); ev = ev.drop_duplicates(); log("T9", "order_events", "удаление повторно отправленных событий", k, len(ev))
ev["ts"] = pd.to_datetime(ev.ts)
evw = ev.pivot_table(index="order_id", columns="event", values="ts", aggfunc="min")
evw.columns = [c + "_at" for c in evw.columns]
orders = (pos.groupby("order_id").agg(created_at=("created_at", "min"), order_type=("order_type", "first"),
                                      customer_key=("customer_key", "first"), status=("status", "first"),
                                      cashier=("cashier", "first"))
          .join(evw.drop(columns=["created_at", "paid_at"]), how="left").join(paid).join(attempts))
orders["wait_min"] = (orders.ready_at - orders.paid_at).dt.total_seconds() / 60
neg = orders.wait_min < 0
reject(orders[neg].reset_index()[["order_id", "paid_at", "ready_at"]], "order_events", "отрицательный интервал ready-paid (сбой часов) -> wait=NaN")
orders.loc[neg, "wait_min"] = np.nan
log("T10", "order_events", "отрицательные интервалы ожидания -> пропуск", len(orders), len(orders),
    f"{neg.sum()} заказов; ready_at отсутствует у {orders.ready_at.isna().sum()}")
orders["issue_lag_min"] = (orders.issued_at - orders.ready_at).dt.total_seconds() / 60
orders["cancel_stage"] = np.select([orders.status.eq("issued"), orders.status.eq("not_picked"), orders.payment_attempts.notna()],
                                   ["", "not_picked", "payment"], default="availability")

# ===== обогащение факта =====
f = pos.merge(orders[["paid_at", "ready_at", "issued_at", "wait_min", "cancel_stage", "payment_attempts"]],
              left_on="order_id", right_index=True, how="left")
f["revenue"] = (f.qty * f.unit_price).where(f.status == "issued", 0.0)
cost = pd.merge_asof(f.sort_values("created_at"), tc[["item_id", "valid_from", "Себестоимость по техкарте"]].sort_values("valid_from"),
                     left_on="created_at", right_on="valid_from", by="item_id", suffixes=("", "_c"))
f = cost.rename(columns={"Себестоимость по техкарте": "unit_cost"})
f["cogs"] = (f.qty * f.unit_cost).where(f.status == "issued", 0.0)
f["gross_margin"] = f.revenue - f.cogs
f["date_key"] = f.created_at.dt.strftime("%Y%m%d").astype(int)
f["hour"] = f.created_at.dt.hour
f["paid_flag"] = f.paid_at.notna().astype(int)
f["ready_flag"] = f.ready_at.notna().astype(int) | (f.status == "issued").astype(int)
f["issued_flag"] = (f.status == "issued").astype(int)
f["employee_key"] = f.cashier
fact = f[["order_id", "line_no", "date_key", "created_at", "hour", "item_id", "customer_key", "order_type", "employee_key",
          "qty", "unit_price", "discount", "revenue", "cogs", "gross_margin", "status", "cancel_stage",
          "paid_flag", "ready_flag", "issued_flag", "wait_min", "payment_attempts"]].sort_values(["created_at", "line_no"])

# ===== справочники =====
dates = pd.DataFrame({"date": pd.to_datetime(w["daily"]["time"])})
wd = pd.DataFrame(w["daily"]).rename(columns={"time": "date"}); wd["date"] = pd.to_datetime(wd.date)
dates = dates.merge(wd, on="date")
dates["date_key"] = dates.date.dt.strftime("%Y%m%d").astype(int)
dates["month"] = dates.date.dt.strftime("%Y-%m"); dates["week_start"] = dates.date.dt.to_period("W-SUN").dt.start_time
dates["weekday"] = dates.date.dt.day_name(); dates["is_weekend"] = (dates.date.dt.dayofweek >= 5).astype(int)
dates["weather_type"] = np.select([dates.precipitation_sum > 2, dates.temperature_2m_mean >= 18], ["дождь", "тепло"], "сухо")
dim_item = cur.rename(columns={"Код": "item_id", "Наименование": "item_name", "Группа": "category",
                               "Цена продажи": "price_current", "Себестоимость по техкарте": "unit_cost", "Холодный": "is_cold"}
                      )[["item_id", "item_name", "category", "price_current", "unit_cost", "is_cold"]]
dim_item["food_or_drink"] = np.where(dim_item.category.isin(["Выпечка", "Завтраки", "Десерты"]), "еда", "напиток")
loy = loy.rename(columns={"card_hash": "customer_key"})
dim_customer = pd.concat([loy, pd.DataFrame([{"customer_key": "ANON", "registered": None, "how_found": "анонимный"}])])
staff = {"E1": "Анна", "E2": "Илья", "E3": "Мария", "E4": "Дмитрий", "E5": "Ольга", "E6": "Сергей"}
dim_employee = pd.DataFrame({"employee_key": list(staff), "name": list(staff.values()),
                             "role": ["бариста"] * 4 + ["кассир"] * 2})
dim_channel = pd.DataFrame({"order_type": ["dine_in", "takeaway", "unknown"],
                            "order_type_ru": ["В зале", "С собой", "Не указан"]})

# ===== справочные очищенные наборы =====
survey = survey.rename(columns={"Отметка времени": "ts", "Оцените визит (1-5)": "score", "Цель визита": "goal",
                                "Придёте снова?": "intent", "Главная причина вернуться": "reason",
                                "Номер карты (по желанию)": "customer_key", "Ждали дольше, чем ожидали?": "waited_long"})
survey["ts"] = pd.to_datetime(survey.ts, format="%d.%m.%Y %H:%M:%S")
k = len(survey); survey = survey[survey.score.between(1, 5)]
log("T11", "survey", "исключены ответы без оценки", k, len(survey))
survey.to_csv("clean/survey.csv", index=False)
rv_g["date"] = pd.to_datetime(rv_g.date, format="%d %B %Y", errors="coerce").fillna(pd.to_datetime(rv_g.date, format="%Y-%m-%d", errors="coerce")); rv_y["date"] = pd.to_datetime(rv_y.date)
rv = pd.concat([rv_y.assign(platform="Яндекс Карты"), rv_g.assign(platform="2ГИС")])
k = len(rv); dup = rv.duplicated(["text", "date", "rating"], keep="first")
reject(rv[dup], "reviews", "перепубликованный отзыв (тот же текст, дата, оценка)")
rv = rv[~dup]; log("T12", "reviews", "удаление перепубликаций между площадками", k, len(rv))
THEME = {"ожидание": r"ждал|долго|очеред|быстро", "выпечка": r"круассан", "кофе": r"кофе|капучино|фильтр|зерно",
         "атмосфера": r"уютно|зал|мест|книг", "персонал": r"бариста|кассир", "цены": r"цен|подорож"}
rv["theme"] = rv.text.str.lower().apply(lambda t: next((k for k, p in THEME.items() if re.search(p, t)), "прочее"))
rv["cjm_stage"] = rv.theme.map({"ожидание": "C4", "выпечка": "C2", "кофе": "C5", "атмосфера": "C5",
                                "персонал": "C3", "цены": "C6"})
rv.to_csv("clean/reviews.csv", index=False)
obs["arrival_at"] = pd.to_datetime(obs.arrival_at); obs["service_started_at"] = pd.to_datetime(obs.service_started_at)
obs["queue_min"] = (obs.service_started_at - obs.arrival_at).dt.total_seconds() / 60
obs["left_without_order"] = obs.service_started_at.isna().astype(int)
obs.to_csv("clean/queue_observations.csv", index=False)
shifts["date"] = pd.to_datetime(shifts["Дата"] + ".2026", format="%d.%m.%Y")
shifts["employee_key"] = shifts["Сотрудник"].map({v: k for k, v in staff.items()})
log("T13", "shifts", "дата дд.мм + год, имя -> employee_key", len(shifts), int(shifts.employee_key.notna().sum()))
shifts.to_csv("clean/shifts.csv", index=False)

# ===== LOAD + сверки =====
fact.to_csv("model/fact_sales.csv", index=False)
dates.to_csv("model/dim_date.csv", index=False); dim_item.to_csv("model/dim_item.csv", index=False)
dim_customer.to_csv("model/dim_customer.csv", index=False); dim_employee.to_csv("model/dim_employee.csv", index=False)
dim_channel.to_csv("model/dim_order_type.csv", index=False)
orders.reset_index().to_csv("clean/orders.csv", index=False)
checks = {
    "ключ (order_id,line_no) уникален": not fact.duplicated(["order_id", "line_no"]).any(),
    "все item_id есть в dim_item": fact.item_id.isin(dim_item.item_id).all(),
    "все date_key есть в dim_date": fact.date_key.isin(dates.date_key).all(),
    "все customer_key есть в dim_customer": fact.customer_key.isin(dim_customer.customer_key).all(),
    "выручка только у выданных": (fact.loc[fact.status != "issued", "revenue"] == 0).all(),
    "оплачено == сумме успешных платежей ±1%": abs(fact.groupby("order_id").revenue.sum().sum() /
                                                    pay[pay.result == "success"].amount.sum() - 1) < 0.01,
}
for k_, v in checks.items(): log("L", "model", "проверка: " + k_, 0, 0, "OK" if v else "FAIL")
pd.DataFrame(LOG).to_csv("etl_log.csv", index=False)
pd.concat(REJ).to_csv("rejected.csv", index=False)
print(pd.DataFrame(LOG).to_string())
print("fact rows", len(fact), "orders", fact.order_id.nunique())
