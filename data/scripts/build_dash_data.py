"""Агрегаты для BI: все сочетания фильтров период × формат × категория -> out/dash/*.json"""
import json, os
import numpy as np, pandas as pd
os.makedirs("out/dash", exist_ok=True)
O = pd.read_csv("out/orders_view.csv", parse_dates=["created_at", "week_start"])
F = pd.read_csv("model/fact_sales.csv", parse_dates=["created_at"]).merge(pd.read_csv("model/dim_item.csv")[["item_id", "category"]], on="item_id")
S = pd.read_csv("clean/survey.csv", parse_dates=["ts"]); R = pd.read_csv("clean/reviews.csv", parse_dates=["date"])
Q = pd.read_csv("clean/queue_observations.csv", parse_dates=["arrival_at"])
M = json.load(open("out/metrics.json", encoding="utf-8"))
LOY = pd.read_csv("raw/loyalty_customers.csv")
maps_share = round(LOY.how_found.isin(["Яндекс Карты", "2ГИС"]).mean(), 3)
TAU = 5
P = {  # период: (начало, конец, начало пред., конец пред., подпись)
    "all": ("2026-04-01", "2026-10-25", None, None, "1 апр — 25 окт"),
    "last4w": ("2026-09-28", "2026-10-25", "2026-08-31", "2026-09-27", "28 сен — 25 окт"),
    "q3": ("2026-07-01", "2026-09-30", "2026-04-01", "2026-06-30", "июль — сентябрь"),
    "sep": ("2026-09-01", "2026-09-30", "2026-08-01", "2026-08-31", "сентябрь"),
    "aug": ("2026-08-01", "2026-08-31", "2026-07-01", "2026-07-31", "август"),
    "jul": ("2026-07-01", "2026-07-31", "2026-06-01", "2026-06-30", "июль"),
}
TYPES = ["all", "dine_in", "takeaway"]
CATS = ["all"] + sorted(F.category.unique())
def win(df, col, a, b):
    return df[(df[col] >= a) & (df[col] < pd.Timestamp(b) + pd.Timedelta(days=1))]
def by_type(df, t): return df if t == "all" else df[df.order_type == t]

def kpis(a, b, t, c):
    o = by_type(win(O, "created_at", a, b), t); f = by_type(win(F, "created_at", a, b), t)
    iss = o[o.issued == 1]; fi = f[f.issued_flag == 1]
    if c != "all": fi = fi[fi.category == c]
    rev = fi.revenue.sum(); n_ord = fi.order_id.nunique()
    w = o.wait.dropna()
    s = win(S, "ts", a, b)
    if t != "all": s = s.iloc[0:0] if False else s     # опрос не знает формат — общий
    return dict(revenue=round(rev), orders=int(n_ord), avg_check=round(rev / n_ord, 1) if n_ord else None,
                margin_pct=round(fi.gross_margin.sum() / rev, 4) if rev else None,
                registered=int(len(o)), conv_paid=round(o.paid.mean(), 4) if len(o) else None,
                avail_cancel=round((o.cancel_stage == "availability").mean(), 4) if len(o) else None,
                wait_median=round(w.median(), 2) if len(w) else None, wait_p90=round(w.quantile(.9), 2) if len(w) else None,
                sla=round((w <= TAU).mean(), 4) if len(w) else None,
                csat=round((s.score >= 4).mean(), 4) if len(s) else None, csat_n=int(len(s)),
                ident=round((iss.customer_key != "ANON").mean(), 4) if len(iss) else None)

rows = []
for p, (a, b, pa, pb, lab) in P.items():
    for t in TYPES:
        for c in CATS:
            cur = kpis(a, b, t, c); prev = kpis(pa, pb, t, c) if pa else {}
            r = dict(period=p, order_type=t, category=c, period_label=lab, **cur)
            for k in ("revenue", "orders", "avg_check", "sla", "wait_median", "csat", "avail_cancel", "conv_paid"):
                pv = prev.get(k); r["prev_" + k] = pv
                r["d_" + k] = None if (pv in (None, 0) or cur[k] is None) else (round(cur[k] / pv - 1, 4) if k in ("revenue", "orders", "avg_check") else round(cur[k] - pv, 4))
            rows.append(r)
json.dump(rows, open("out/dash/kpi.json", "w", encoding="utf-8"), ensure_ascii=False)

# недельная динамика + прогноз
wk = []
for t in TYPES:
    for c in CATS:
        fi = by_type(F[F.issued_flag == 1], t)
        if c != "all": fi = fi[fi.category == c]
        fi = fi.assign(week=fi.created_at.dt.to_period("W-SUN").dt.start_time)
        g = fi.groupby("week").revenue.sum()
        g = g[(g.index >= "2026-04-06") & (g.index <= "2026-10-19")]
        for k, v in g.items():
            wk.append(dict(order_type=t, category=c, week=str(k.date()), revenue=round(v), kind="факт"))
for r in M["forecast"]["series"]:
    if r["ma4"] is not None:
        wk.append(dict(order_type="all", category="all", week=r["week"], revenue=r["ma4"], kind="MA(4)"))
last4 = [r["revenue"] for r in M["forecast"]["series"][-4:]]; ma = round(sum(last4) / 4)
sd = np.std([r["revenue"] - (r["ma4"] or r["revenue"]) for r in M["forecast"]["series"][4:]], ddof=1)
for r in M["forecast"]["next4"]:
    wk.append(dict(order_type="all", category="all", week=r["week"], revenue=ma, kind="прогноз",
                   lo=round(ma - 1.96 * sd), hi=round(ma + 1.96 * sd)))
json.dump(wk, open("out/dash/weekly.json", "w", encoding="utf-8"), ensure_ascii=False)

# воронка и отмены
fun, can, waits, cats, cjm = [], [], [], [], []
STEPS = [("1", "Зарегистрирован (T01)", "registered"), ("2", "Оплачен (G03)", "paid"), ("3", "Готов (T04)", "ready"), ("4", "Выдан (E02)", "issued")]
for p, (a, b, pa, pb, lab) in P.items():
    for t in TYPES:
        o = by_type(win(O, "created_at", a, b), t)
        op = by_type(win(O, "created_at", pa, pb), t) if pa else None
        vals = dict(registered=len(o), paid=o.paid.sum(), ready=o.ready.sum(), issued=o.issued.sum())
        pvals = dict(registered=len(op), paid=op.paid.sum(), ready=op.ready.sum(), issued=op.issued.sum()) if op is not None else {}
        for sid, name, key in STEPS:
            fun.append(dict(period=p, order_type=t, step=sid, step_name=name, n=int(vals[key]),
                            share=round(vals[key] / vals["registered"], 4), prev_share=round(pvals[key] / pvals["registered"], 4) if pvals else None))
        for reason, lab2 in (("availability", "Нет позиции, замена не принята"), ("payment", "Оплата не прошла"), ("not_picked", "Готов, но не забрали")):
            can.append(dict(period=p, order_type=t, reason=lab2, n=int((o.cancel_stage == reason).sum())))
        ow = o.dropna(subset=["wait"]).assign(daytype=lambda d: np.where(d.is_weekend == 1, "Выходные", "Будни"))
        for (dt, h), g in ow.groupby(["daytype", "hour"]):
            waits.append(dict(period=p, order_type=t, daytype=dt, hour=int(h), n=int(len(g)), median=round(g.wait.median(), 1),
                              p90=round(g.wait.quantile(.9), 1), sla=round((g.wait <= TAU).mean(), 3)))
        fi = by_type(win(F, "created_at", a, b), t); fi = fi[fi.issued_flag == 1]
        cg = fi.groupby("category").agg(revenue=("revenue", "sum"), margin=("gross_margin", "sum"))
        for c, r in cg.iterrows():
            cats.append(dict(period=p, order_type=t, category=c, revenue=round(r.revenue), share=round(r.revenue / cg.revenue.sum(), 4),
                             margin_pct=round(r.margin / r.revenue, 4)))
        # CJM
        k = kpis(a, b, t, "all")
        s = win(S, "ts", a, b); rv = win(R, "date", a, b); q = win(Q, "arrival_at", a, b)
        iss = o[o.issued == 1]
        neg_all = round((rv.rating <= 3).mean(), 3) if len(rv) else None
        neg = lambda th: round((rv[rv.theme == th].rating <= 3).mean(), 3) if (rv.theme == th).any() else None
        def st(v, good, bad, higher=True):
            if v is None: return "нет данных"
            return ("норма" if v >= good else "внимание" if v >= bad else "проблема") if higher else ("норма" if v <= good else "внимание" if v <= bad else "проблема")
        stages = [
            ("C1", "Поиск", "Доля гостей, нашедших кофейню через карты (Яндекс, 2ГИС)", maps_share, "pct", st(maps_share, 0.3, 0.2)),
            ("C2", "Вход и выбор", "Отмены из-за отсутствия позиции", k["avail_cancel"], "pct", st(k["avail_cancel"], 0.005, 0.01, False)),
            ("C3", "Заказ и оплата", "Конверсия в оплату", k["conv_paid"], "pct", st(k["conv_paid"], 0.99, 0.98)),
            ("C4", "Ожидание", "Заказы, готовые за 5 мин после оплаты", k["sla"], "pct", st(k["sla"], 0.8, 0.6)),
            ("C5", "Получение и опыт", "CSAT (оценки 4–5)", k["csat"], "pct", st(k["csat"], 0.85, 0.75)),
            ("C6", "Оценка и повтор", "Отзывы с оценкой ≤ 3 (все темы)", neg_all, "pct", st(neg_all, 0.3, 0.45, False)),
        ]
        for sid, name, kpi, v, fmt, status in stages:
            cjm.append(dict(period=p, order_type=t, stage=sid, stage_name=name, kpi=kpi, value=v, status=status))
json.dump(fun, open("out/dash/funnel.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(can, open("out/dash/cancels.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(waits, open("out/dash/waits.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(cats, open("out/dash/categories.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(cjm, open("out/dash/cjm.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump([dict(segment=r["segment"], customers=r["customers"], share_cust=round(r["share_cust"] / 100, 4), share_rev=round(r["share_rev"] / 100, 4),
                r_median=r["R_med"], f_avg=r["F_avg"], m_avg=round(r["M_avg"])) for r in sorted(M["rfm"], key=lambda r: -r["share_rev"])],
          open("out/dash/rfm.json", "w", encoding="utf-8"), ensure_ascii=False)
for f in sorted(os.listdir("out/dash")): print(f, os.path.getsize("out/dash/" + f))
