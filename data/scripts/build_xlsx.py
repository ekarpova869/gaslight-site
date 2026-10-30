"""Книга расчётов «Газлайт» для Excel / Google Sheets: формулы + контрольные значения из Python."""
import json
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

M = json.load(open("out/metrics.json", encoding="utf-8"))
O = pd.read_csv("out/orders_view.csv", parse_dates=["created_at", "week_start"])
F = pd.read_csv("model/fact_sales.csv", parse_dates=["created_at"])
I = pd.read_csv("model/dim_item.csv"); D = pd.read_csv("model/dim_date.csv", parse_dates=["date", "week_start"])
RFM = pd.read_csv("out/rfm.csv")
LOG = pd.read_csv("etl_log.csv")
H = Font(bold=True, color="FFFFFF"); HF = PatternFill("solid", fgColor="5B3A29"); B = Font(bold=True)
wb = Workbook()

def table(ws, df, r0=1, c0=1):
    for j, c in enumerate(df.columns):
        cell = ws.cell(r0, c0 + j, c); cell.font = H; cell.fill = HF
    for i, row in enumerate(df.itertuples(index=False), 1):
        for j, v in enumerate(row):
            ws.cell(r0 + i, c0 + j, None if pd.isna(v) else (v.to_pydatetime() if hasattr(v, "to_pydatetime") else v))
    for j, c in enumerate(df.columns):
        ws.column_dimensions[get_column_letter(c0 + j)].width = max(10, min(28, len(str(c)) + 4))
    ws.freeze_panes = ws.cell(r0 + 1, c0)
    ws.auto_filter.ref = f"{get_column_letter(c0)}{r0}:{get_column_letter(c0 + len(df.columns) - 1)}{r0 + len(df)}"

# ---- README
ws = wb.active; ws.title = "README"
txt = ["Газлайт — книга расчётов (учебный проект)",
       "ДАННЫЕ СИНТЕТИЧЕСКИЕ, кроме погоды (Open-Meteo API). Генератор, ETL и анализ: generate_raw.py, etl.py, analysis.py.",
       f"Период: {M['period'][0]} — {M['period'][1]}. Валюта — рубли. Время — Europe/Moscow.",
       "Листы: Заказы (представление факта на уровне заказа), Продажи (факт, строка заказа), Справочники, KPI, Описательная,",
       "Сводная_месяц, Ожидание_час, RFM, Прогноз, ETL_журнал. Колонка «Контроль (Python)» — то же значение, посчитанное в analysis.py.",
       "Если формула и контроль расходятся — ищите ошибку в фильтре или диапазоне.",
       "Фильтры: на каждом листе с данными включён автофильтр (даты, категории, формат заказа)."]
for i, t in enumerate(txt, 1): ws.cell(i, 1, t).font = B if i == 1 else Font()
ws.column_dimensions["A"].width = 130

# ---- Заказы (A..)
ov = O[["order_id", "created_at", "month", "week_start", "hour", "is_weekend", "order_type", "customer_key", "status",
        "cancel_stage", "paid", "ready", "issued", "wait", "revenue", "margin", "lines", "weather"]].copy()
ov["created_date"] = ov.created_at.dt.normalize()
ws = wb.create_sheet("Заказы"); table(ws, ov)
N = len(ov) + 1
col = {c: get_column_letter(i + 1) for i, c in enumerate(ov.columns)}
def rng(c): return f"Заказы!${col[c]}$2:${col[c]}${N}"

# ---- Продажи (факт)
fv = F.merge(I[["item_id", "item_name", "category"]], on="item_id")[
    ["order_id", "line_no", "date_key", "created_at", "item_id", "item_name", "category", "order_type", "customer_key",
     "qty", "unit_price", "revenue", "cogs", "gross_margin", "status"]]
fv["month"] = fv.created_at.dt.strftime("%Y-%m")
ws = wb.create_sheet("Продажи"); table(ws, fv)
NF = len(fv) + 1; fcol = {c: get_column_letter(i + 1) for i, c in enumerate(fv.columns)}
def frng(c): return f"Продажи!${fcol[c]}$2:${fcol[c]}${NF}"

# ---- Справочники
ws = wb.create_sheet("Справочники"); table(ws, I)
table(ws, D[["date_key", "date", "month", "week_start", "weekday", "is_weekend", "temperature_2m_mean", "precipitation_sum", "weather_type"]], 1, 10)

# ---- KPI
ws = wb.create_sheet("KPI")
for j, h in enumerate(["KPI", "Формула (Excel/Sheets)", "Значение", "Контроль (Python)", "Определение"], 1):
    c = ws.cell(1, j, h); c.font = H; c.fill = HF
k = [
    ("Зарегистрировано заказов", f"=COUNTA({rng('order_id')})", M["orders_registered"], "уникальные order_id (E01/T01)"),
    ("Оплачено заказов", f"=SUM({rng('paid')})", M["orders_paid"], "успешная оплата (G03 = да)"),
    ("Выдано заказов", f"=SUM({rng('issued')})", M["orders_issued"], "E02"),
    ("Выручка выполненных заказов, ₽", f"=SUMIFS({rng('revenue')},{rng('issued')},1)", M["revenue"], "Σ qty × цена после скидки, только выданные"),
    ("Средний чек, ₽", "=C5/C4", M["avg_check"], "выручка / уникальные выданные заказы"),
    ("Валовая маржа по техкартам, %", f"=SUMIFS({rng('margin')},{rng('issued')},1)/C5", M["gross_margin_pct"] / 100, "без аренды и ФОТ"),
    ("Конверсия в оплату, %", "=C3/C2", M["conv_paid"] / 100, "когорта по created_at"),
    ("Выдача среди оплаченных, %", "=C4/C3", M["issued_of_paid"] / 100, ""),
    ("Отмены из-за отсутствия позиции, %", f'=COUNTIFS({rng("cancel_stage")},"availability")/C2', M["cancel_availability_pct"] / 100, "доля зарегистрированных заказов"),
    ("Ожидание готовности: медиана, мин", f"=MEDIAN({rng('wait')})", M["wait_median"], "ready_at − paid_at; пустые ячейки игнорируются"),
    ("Ожидание готовности: P90, мин", f"=PERCENTILE({rng('wait')},0.9)", M["wait_p90"], ""),
    ("SLA ≤ 5 мин, %", f'=COUNTIFS({rng("wait")},"<=5")/COUNT({rng("wait")})', M["sla_pct"] / 100, "τ = 5 мин — учебный норматив, согласовать с управляющим"),
    ("Покрытие идентификацией, %", f'=COUNTIFS({rng("issued")},1,{rng("customer_key")},"<>ANON")/C4', M["ident_coverage"] / 100, "доля выданных заказов с картой"),
    ("Пик будней 8–9 ч: медиана ожидания", None, M["h1_peak"]["median"], "формула массива"),
]
for i, (name, f, ctrl, d) in enumerate(k, 2):
    ws.cell(i, 1, name); ws.cell(i, 2, f or "")
    if f: ws.cell(i, 3, f)
    ws.cell(i, 4, ctrl); ws.cell(i, 5, d)
r = 1 + len(k)
ws[f"C{r}"] = ArrayFormula(f"C{r}", f"=MEDIAN(IF(({rng('is_weekend')}=0)*(({rng('hour')}=8)+({rng('hour')}=9))*({rng('wait')}<>\"\"),{rng('wait')}))")
ws[f"B{r}"] = "{=MEDIAN(IF(будни*(час 8 или 9)*(wait не пусто), wait))}"
for i in range(2, r + 1):
    fmt = "0.0%" if "%" in ws.cell(i, 1).value else "#,##0.0"
    ws.cell(i, 3).number_format = fmt; ws.cell(i, 4).number_format = fmt
for c, w in zip("ABCDE", [38, 60, 14, 16, 55]): ws.column_dimensions[c].width = w

# ---- Описательная статистика по дневной выручке
ws = wb.create_sheet("Описательная")
days = sorted(ov.created_date.unique())
ws["A1"], ws["B1"] = "Дата", "Выручка дня, ₽"; ws["C1"] = "Заказов"
for c in ("A1", "B1", "C1"): ws[c].font = H; ws[c].fill = HF
for i, d in enumerate(days, 2):
    ws.cell(i, 1, pd.Timestamp(d).to_pydatetime()).number_format = "dd.mm.yyyy"
    ws.cell(i, 2, f"=SUMIFS({rng('revenue')},{rng('created_date')},A{i},{rng('issued')},1)")
    ws.cell(i, 3, f"=COUNTIFS({rng('created_date')},A{i},{rng('issued')},1)")
last = len(days) + 1
stats = [("Среднее", f"=AVERAGE(B2:B{last})", M["daily_desc"]["mean"]), ("Медиана", f"=MEDIAN(B2:B{last})", M["daily_desc"]["50%"]),
         ("Ст. отклонение", f"=STDEV(B2:B{last})", M["daily_desc"]["std"]), ("Минимум", f"=MIN(B2:B{last})", M["daily_desc"]["min"]),
         ("Q1", f"=QUARTILE(B2:B{last},1)", M["daily_desc"]["25%"]), ("Q3", f"=QUARTILE(B2:B{last},3)", M["daily_desc"]["75%"]),
         ("Максимум", f"=MAX(B2:B{last})", M["daily_desc"]["max"]), ("Коэф. вариации", "=G4/G2", None)]
ws["F1"], ws["G1"], ws["H1"] = "Статистика дневной выручки", "Значение", "Контроль (Python)"
for i, (n_, f, c) in enumerate(stats, 2):
    ws.cell(i, 6, n_); ws.cell(i, 7, f).number_format = "#,##0"; ws.cell(i, 8, c)
ws.column_dimensions["A"].width = 12; ws.column_dimensions["B"].width = 16; ws.column_dimensions["F"].width = 28

# ---- Сводная месяц × категория
ws = wb.create_sheet("Сводная_месяц")
months = sorted(fv.month.unique()); cats = sorted(I.category.unique())
ws["A1"] = "Выручка, ₽: категория × месяц (SUMIFS по факту, только выданные)"; ws["A1"].font = B
ws.cell(2, 1, "Категория").font = B
for j, m in enumerate(months, 2): ws.cell(2, j, m).font = B
ws.cell(2, len(months) + 2, "Итого").font = B; ws.cell(2, len(months) + 3, "Доля").font = B
for i, c in enumerate(cats, 3):
    ws.cell(i, 1, c)
    for j, m in enumerate(months, 2):
        ws.cell(i, j, f'=SUMIFS({frng("revenue")},{frng("category")},$A{i},{frng("month")},{get_column_letter(j)}$2)').number_format = "#,##0"
    L = get_column_letter(len(months) + 1)
    ws.cell(i, len(months) + 2, f"=SUM(B{i}:{L}{i})").number_format = "#,##0"
tot = len(cats) + 3; ws.cell(tot, 1, "Итого").font = B
for j in range(2, len(months) + 3):
    L = get_column_letter(j); ws.cell(tot, j, f"=SUM({L}3:{L}{tot - 1})").number_format = "#,##0"
T = get_column_letter(len(months) + 2)
for i in range(3, tot + 1): ws.cell(i, len(months) + 3, f"={T}{i}/{T}${tot}").number_format = "0.0%"
r0 = tot + 3
ws.cell(r0, 1, "Заказы, средний чек и выдача по формату × месяц").font = B
for j, m in enumerate(months, 2): ws.cell(r0 + 1, j, m).font = B
for i, (lab, t) in enumerate([("Заказы в зале", "dine_in"), ("Заказы с собой", "takeaway")], r0 + 2):
    ws.cell(i, 1, lab)
    for j in range(2, len(months) + 2):
        ws.cell(i, j, f'=COUNTIFS({rng("order_type")},"{t}",{rng("month")},{get_column_letter(j)}${r0 + 1},{rng("issued")},1)')
for i, (lab, t) in enumerate([("Средний чек в зале", "dine_in"), ("Средний чек с собой", "takeaway")], r0 + 4):
    ws.cell(i, 1, lab)
    for j in range(2, len(months) + 2):
        L = get_column_letter(j)
        ws.cell(i, j, f'=SUMIFS({rng("revenue")},{rng("order_type")},"{t}",{rng("month")},{L}${r0 + 1},{rng("issued")},1)/{L}{i - 2}').number_format = "#,##0"
ws.column_dimensions["A"].width = 26

# ---- Ожидание по часу
ws = wb.create_sheet("Ожидание_час")
hdr = ["Час", "Будни: заказов", "Будни: медиана", "Будни: P90", "Будни: SLA≤5", "Выходные: заказов", "Выходные: медиана", "Выходные: P90", "Выходные: SLA≤5"]
for j, h in enumerate(hdr, 1): c = ws.cell(1, j, h); c.font = H; c.fill = HF
for i, h in enumerate(range(8, 22), 2):
    ws.cell(i, 1, h)
    for k_, wk in enumerate([0, 1]):
        base = 2 + 4 * k_
        cond = f"({rng('is_weekend')}={wk})*({rng('hour')}=$A{i})*({rng('wait')}<>\"\")"
        ws.cell(i, base, f'=COUNTIFS({rng("is_weekend")},{wk},{rng("hour")},$A{i},{rng("wait")},">=0")')
        for off, fn in ((1, f"MEDIAN(IF({cond},{rng('wait')}))"), (2, f"PERCENTILE(IF({cond},{rng('wait')}),0.9)")):
            ref = f"{get_column_letter(base + off)}{i}"; ws[ref] = ArrayFormula(ref, "=" + fn); ws[ref].number_format = "0.0"
        ws.cell(i, base + 3, f'=COUNTIFS({rng("is_weekend")},{wk},{rng("hour")},$A{i},{rng("wait")},"<=5")/{get_column_letter(base)}{i}').number_format = "0%"
for j in range(1, 10): ws.column_dimensions[get_column_letter(j)].width = 17
ws["K1"] = "Условное форматирование: красным — P90 > 12 мин"
from openpyxl.formatting.rule import CellIsRule
ws.conditional_formatting.add("D2:D15", CellIsRule(operator="greaterThan", formula=["12"], fill=PatternFill("solid", fgColor="F4B6B6")))
ws.conditional_formatting.add("H2:H15", CellIsRule(operator="greaterThan", formula=["12"], fill=PatternFill("solid", fgColor="F4B6B6")))

# ---- RFM
ws = wb.create_sheet("RFM")
ws["A1"] = "Дата анализа"; ws["B1"] = pd.Timestamp(M["rfm_asof"]).to_pydatetime(); ws["B1"].number_format = "dd.mm.yyyy"
hdr = ["customer_key", "Последняя покупка", "R, дней", "F, заказов", "M, ₽", "r", "f", "m", "RFM", "Сегмент", "Контроль сегмента (Python)"]
for j, h in enumerate(hdr, 1): c = ws.cell(3, j, h); c.font = H; c.fill = HF
for i, row in enumerate(RFM.itertuples(), 4):
    ws.cell(i, 1, row.customer_key)
    ws.cell(i, 2, f'=_xlfn.MAXIFS({rng("created_at")},{rng("customer_key")},A{i},{rng("issued")},1)').number_format = "dd.mm.yyyy"
    ws.cell(i, 3, f"=INT($B$1-B{i})")
    ws.cell(i, 4, f'=COUNTIFS({rng("customer_key")},A{i},{rng("issued")},1)')
    ws.cell(i, 5, f'=SUMIFS({rng("revenue")},{rng("customer_key")},A{i},{rng("issued")},1)').number_format = "#,##0"
    ws.cell(i, 6, f"=IF(C{i}<=14,5,IF(C{i}<=30,4,IF(C{i}<=60,3,IF(C{i}<=120,2,1))))")
    ws.cell(i, 7, f"=IF(D{i}>=10,5,IF(D{i}>=5,4,IF(D{i}>=3,3,IF(D{i}>=2,2,1))))")
    ws.cell(i, 8, f"=MIN(5,1+INT(5*(RANK(E{i},$E$4:$E${len(RFM) + 3},1)-1)/COUNT($E$4:$E${len(RFM) + 3})))")
    ws.cell(i, 9, f"=F{i}&G{i}&H{i}")
    ws.cell(i, 10, f'=IF(AND(F{i}>=4,G{i}>=4),"Чемпионы",IF(AND(F{i}>=3,G{i}>=3),"Лояльные",IF(AND(F{i}>=4,G{i}<=2),"Новички",IF(AND(F{i}<=2,G{i}>=3),"Под угрозой ухода",IF(AND(F{i}=3,G{i}<=2),"Нуждаются во внимании","Спящие")))))')
    ws.cell(i, 11, row.segment)
ws.auto_filter.ref = f"A3:K{len(RFM) + 3}"; ws.freeze_panes = "A4"
segs = ["Чемпионы", "Лояльные", "Новички", "Нуждаются во внимании", "Под угрозой ухода", "Спящие"]
ws["M3"], ws["N3"], ws["O3"], ws["P3"] = "Сегмент", "Клиентов", "Выручка, ₽", "Доля выручки"
for c in ("M3", "N3", "O3", "P3"): ws[c].font = H; ws[c].fill = HF
E = len(RFM) + 3
for i, s in enumerate(segs, 4):
    ws.cell(i, 13, s); ws.cell(i, 14, f'=COUNTIF($J$4:$J${E},M{i})')
    ws.cell(i, 15, f'=SUMIF($J$4:$J${E},M{i},$E$4:$E${E})').number_format = "#,##0"
    ws.cell(i, 16, f"=O{i}/SUM($O$4:$O$9)").number_format = "0.0%"
for c, w in zip("ABCDEFGHIJKLMNOP", [14, 16, 9, 10, 11, 5, 5, 5, 7, 24, 24, 2, 24, 10, 13, 12]): ws.column_dimensions[c].width = w

# ---- Прогноз
ws = wb.create_sheet("Прогноз")
fs = M["forecast"]["series"]
hdr = ["№", "Неделя (пн)", "Выручка, ₽", "Выборка", "Линейный тренд (обучение)", "MA(4)", "Наивный (t−1)", "|ошибка| тренд", "|ошибка| MA4", "|ошибка| наивный"]
for j, h in enumerate(hdr, 1): c = ws.cell(1, j, h); c.font = H; c.fill = HF
n = len(fs); tr_end = 1 + M["forecast"]["train"]
for i, r in enumerate(fs, 2):
    ws.cell(i, 1, i - 1); ws.cell(i, 2, pd.Timestamp(r["week"]).to_pydatetime()).number_format = "dd.mm.yyyy"
    ws.cell(i, 3, f'=SUMIFS({rng("revenue")},{rng("week_start")},B{i},{rng("issued")},1)').number_format = "#,##0"
    ws.cell(i, 4, "обучение" if i <= tr_end else "проверка")
    ws.cell(i, 5, f"=FORECAST(A{i},$C$2:$C${tr_end},$A$2:$A${tr_end})").number_format = "#,##0"
    if i >= 6: ws.cell(i, 6, f"=AVERAGE(C{i - 4}:C{i - 1})").number_format = "#,##0"
    if i >= 3: ws.cell(i, 7, f"=C{i - 1}").number_format = "#,##0"
    if i > tr_end:
        for j, src in ((8, "E"), (9, "F"), (10, "G")):
            ws.cell(i, j, f"=ABS(C{i}-{src}{i})/C{i}").number_format = "0.0%"
lr = n + 1
ws.cell(lr + 2, 7, "MAPE на 4 неделях проверки:").font = B
for j, key in ((8, "mape_linear"), (9, "mape_ma4"), (10, "mape_naive")):
    L = get_column_letter(j)
    ws.cell(lr + 2, j, f"=AVERAGE({L}{tr_end + 1}:{L}{lr})").number_format = "0.0%"
    ws.cell(lr + 3, j, M["forecast"][key] / 100).number_format = "0.0%"
ws.cell(lr + 3, 7, "Контроль (Python):")
ws.cell(lr + 5, 1, "Прогноз на 4 недели вперёд").font = B
for j, h in enumerate(["№", "Неделя", "MA(4) — основной", "Линейный тренд (вся история)", "Нижняя граница 95%", "Верхняя граница 95%"], 1):
    c = ws.cell(lr + 6, j, h); c.font = H; c.fill = HF
sd_ref = f"$C${lr + 12}"
for k_ in range(4):
    i = lr + 7 + k_
    ws.cell(i, 1, n + 1 + k_)
    ws.cell(i, 2, f"=B{lr}+7*{k_ + 1}").number_format = "dd.mm.yyyy"
    ws.cell(i, 3, f"=AVERAGE($C${lr - 3}:$C${lr})").number_format = "#,##0"
    ws.cell(i, 4, f"=FORECAST(A{i},$C$2:$C${lr},$A$2:$A${lr})").number_format = "#,##0"
    ws.cell(i, 5, f"=C{i}-1.96*{sd_ref}").number_format = "#,##0"
    ws.cell(i, 6, f"=C{i}+1.96*{sd_ref}").number_format = "#,##0"
ws.cell(lr + 12, 1, "Ст. откл. ошибки MA(4) на истории"); ws.cell(lr + 12, 3, f"=STDEV(I{tr_end + 1}:I{lr})*AVERAGE(C{tr_end + 1}:C{lr})").number_format = "#,##0"
ws.cell(lr + 13, 1, "Наклон тренда, ₽/нед"); ws.cell(lr + 13, 3, f"=SLOPE(C2:C{lr},A2:A{lr})").number_format = "#,##0"
ws.cell(lr + 14, 1, "R² тренда"); ws.cell(lr + 14, 3, f"=RSQ(C2:C{lr},A2:A{lr})").number_format = "0.00"
for c, w in zip("ABCDEFGHIJ", [6, 12, 16, 12, 22, 14, 22, 14, 14, 16]): ws.column_dimensions[c].width = w

# ---- ETL журнал
ws = wb.create_sheet("ETL_журнал"); table(ws, LOG)
wb.save("out/Газлайт_расчёты.xlsx")
print("saved")
