"""Аналитика по модели: KPI, гипотезы H1–H4, RFM, прогноз. -> out/metrics.json, out/dashboard_data.json"""
import json, os
import numpy as np, pandas as pd
os.makedirs("out", exist_ok=True)
F = pd.read_csv("model/fact_sales.csv", parse_dates=["created_at"])
D = pd.read_csv("model/dim_date.csv", parse_dates=["date", "week_start"])
I = pd.read_csv("model/dim_item.csv")
S = pd.read_csv("clean/survey.csv", parse_dates=["ts"]); R = pd.read_csv("clean/reviews.csv", parse_dates=["date"])
Q = pd.read_csv("clean/queue_observations.csv", parse_dates=["arrival_at"])
F = F.merge(I[["item_id", "category", "food_or_drink"]], on="item_id").merge(D[["date_key", "month", "week_start", "is_weekend", "weather_type", "temperature_2m_mean"]], on="date_key")
O = F.groupby("order_id").agg(created_at=("created_at", "first"), date_key=("date_key", "first"), hour=("hour", "first"),
                              order_type=("order_type", "first"), customer_key=("customer_key", "first"), status=("status", "first"),
                              cancel_stage=("cancel_stage", "first"), paid=("paid_flag", "max"), ready=("ready_flag", "max"),
                              issued=("issued_flag", "max"), wait=("wait_min", "first"), revenue=("revenue", "sum"),
                              margin=("gross_margin", "sum"), lines=("line_no", "count"), month=("month", "first"),
                              week_start=("week_start", "first"), is_weekend=("is_weekend", "first"), weather=("weather_type", "first"))
O.to_csv("out/orders_view.csv")
M = {}
iss = O[O.issued == 1]
M["period"] = [str(O.created_at.min().date()), str(O.created_at.max().date())]
M["orders_registered"] = int(len(O)); M["orders_paid"] = int(O.paid.sum()); M["orders_ready"] = int(O.ready.sum()); M["orders_issued"] = int(len(iss))
M["revenue"] = round(float(iss.revenue.sum())); M["avg_check"] = round(float(iss.revenue.mean()), 1)
M["gross_margin_pct"] = round(100 * float(iss.margin.sum() / iss.revenue.sum()), 1)
M["conv_paid"] = round(100 * O.paid.mean(), 2); M["issued_of_paid"] = round(100 * iss.shape[0] / O.paid.sum(), 2)
M["cancel_by_stage"] = O[O.status != "issued"].cancel_stage.value_counts().to_dict()
M["cancel_availability_pct"] = round(100 * (O.cancel_stage == "availability").mean(), 2)
wv = O.wait.dropna()
M["wait_median"] = round(float(wv.median()), 2); M["wait_p90"] = round(float(wv.quantile(.9)), 2); M["wait_n"] = int(len(wv))
M["wait_missing"] = int(O[O.issued == 1].wait.isna().sum())
TAU = 5
M["sla_tau"] = TAU; M["sla_pct"] = round(100 * float((wv <= TAU).mean()), 1)
M["csat"] = round(100 * float((S.score >= 4).mean()), 1); M["csat_n"] = int(len(S))
ident = iss.customer_key.ne("ANON"); M["ident_coverage"] = round(100 * float(ident.mean()), 1)
M["daily_desc"] = iss.groupby(iss.created_at.dt.date).revenue.sum().describe().round(0).to_dict()
M["check_desc"] = iss.revenue.describe().round(0).to_dict()

# H1: ожидание по часу × будни/выходные
O["daytype"] = np.where(O.is_weekend == 1, "выходные", "будни")
h1 = O.dropna(subset=["wait"]).groupby(["daytype", "hour"]).agg(n=("wait", "size"), median=("wait", "median"),
        p90=("wait", lambda s: s.quantile(.9)), sla=("wait", lambda s: 100 * (s <= TAU).mean())).round(2).reset_index()
M["h1_wait_by_hour"] = h1.to_dict("records")
peak = O[(O.daytype == "будни") & O.hour.isin([8, 9])].wait.dropna(); rest = O[~((O.daytype == "будни") & O.hour.isin([8, 9]))].wait.dropna()
M["h1_peak"] = dict(n=int(len(peak)), median=round(peak.median(), 2), p90=round(peak.quantile(.9), 2), sla=round(100 * (peak <= TAU).mean(), 1))
M["h1_rest"] = dict(n=int(len(rest)), median=round(rest.median(), 2), p90=round(rest.quantile(.9), 2), sla=round(100 * (rest <= TAU).mean(), 1))
corr = O.dropna(subset=["wait"]).groupby([O.created_at.dt.date, "hour"]).agg(n=("wait", "size"), w=("wait", "median"))
M["h1_corr_load_wait"] = round(float(corr.n.rank().corr(corr.w.rank())), 3)
# H2: выпечка и отмены по наличию
pastry = F[F.category == "Выпечка"].order_id.unique()
av = O[O.cancel_stage == "availability"]
M["h2_avail_cancel_by_daytype_hour"] = (O.assign(av=(O.cancel_stage == "availability").astype(int)).groupby(["daytype", pd.cut(O.hour, [7, 11, 14, 22], labels=["8–11", "12–14", "15–21"])])
                                        .av.mean().mul(100).round(2).reset_index().rename(columns={"av": "pct"}).astype(str).to_dict("records"))
F["pastry_sold"] = (F.category == "Выпечка") & (F.issued_flag == 1)
ps = F[F.pastry_sold].assign(t=lambda d: d.created_at.dt.hour + d.created_at.dt.minute / 60).groupby("date_key").t.max()
ps = ps.to_frame().join(D.set_index("date_key").is_weekend)
M["h2_last_pastry_sale_hour_median"] = ps.groupby("is_weekend").t.median().round(2).to_dict()
# H3: формат
M["h3_format"] = iss.groupby("order_type").agg(orders=("revenue", "size"), avg_check=("revenue", "mean"), lines=("lines", "mean")).round(1).reset_index().to_dict("records")
cat_fmt = F[F.issued_flag == 1].groupby(["order_type", "category"]).revenue.sum().unstack(0)
M["h3_cat_share"] = (100 * cat_fmt / cat_fmt.sum()).round(1).fillna(0).reset_index().to_dict("records")
# H4: опрос ожидание vs намерение
M["h4_intent_by_waited"] = (S.groupby("waited_long").apply(lambda d: pd.Series({"n": len(d), "intent_yes": round(100 * (d.intent == "Да").mean(), 1), "csat": round(100 * (d.score >= 4).mean(), 1)}))
                            .reset_index().to_dict("records"))
M["survey_goal"] = S.goal.value_counts(normalize=True).mul(100).round(1).to_dict()
M["survey_reason"] = S.reason.value_counts(normalize=True).mul(100).round(1).to_dict()
M["reviews_theme"] = R.groupby("theme").agg(n=("rating", "size"), avg=("rating", "mean"), neg=("rating", lambda s: round(100 * (s <= 3).mean(), 1))).round(2).reset_index().to_dict("records")
M["queue_obs"] = dict(n=int(Q.observation_id.count()), left=int(Q.left_without_order.sum()),
                      median_weekday_morning=round(float(Q[(Q.arrival_at.dt.dayofweek < 5) & (Q.arrival_at.dt.hour < 10)].queue_min.median()), 2),
                      median_other=round(float(Q[~((Q.arrival_at.dt.dayofweek < 5) & (Q.arrival_at.dt.hour < 10))].queue_min.median()), 2))
# погода
dd = iss.groupby(iss.created_at.dt.date).agg(rev=("revenue", "sum"), n=("revenue", "size"))
dd.index = pd.to_datetime(dd.index); dd = dd.join(D.set_index("date")[["weather_type", "is_weekend", "temperature_2m_mean"]])
M["weather"] = dd.groupby(["is_weekend", "weather_type"]).agg(days=("rev", "size"), orders=("n", "mean"), rev=("rev", "mean")).round(0).reset_index().to_dict("records")
cold = F[(F.issued_flag == 1) & (F.food_or_drink == "напиток")].assign(cold=lambda d: d.category.eq("Холодные напитки"))
M["cold_share_by_month"] = cold.groupby("month").cold.mean().mul(100).round(1).to_dict()

# ===== RFM =====
asof = O.created_at.max().normalize() + pd.Timedelta(days=1)
C = iss[iss.customer_key != "ANON"].groupby("customer_key").agg(last=("created_at", "max"), F=("revenue", "size"), M=("revenue", "sum"), dinein=("order_type", lambda s: (s == "dine_in").mean()))
C["R"] = (asof - C["last"]).dt.days
C["r"] = pd.cut(C.R, [-1, 14, 30, 60, 120, 10**5], labels=[5, 4, 3, 2, 1]).astype(int)
C["f"] = pd.cut(C.F, [0, 1, 2, 4, 9, 10**5], labels=[1, 2, 3, 4, 5]).astype(int)
C["m"] = pd.qcut(C.M.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
def seg(r):
    if r.r >= 4 and r.f >= 4: return "Чемпионы"
    if r.r >= 3 and r.f >= 3: return "Лояльные"
    if r.r >= 4 and r.f <= 2: return "Новички"
    if r.r <= 2 and r.f >= 3: return "Под угрозой ухода"
    if r.r == 3 and r.f <= 2: return "Нуждаются во внимании"
    return "Спящие"
C["segment"] = C.apply(seg, axis=1)
C.reset_index().to_csv("out/rfm.csv", index=False)
segt = C.groupby("segment").agg(customers=("R", "size"), R_med=("R", "median"), F_avg=("F", "mean"), M_sum=("M", "sum"), M_avg=("M", "mean"), dinein=("dinein", "mean")).round(1)
segt["share_cust"] = (100 * segt.customers / segt.customers.sum()).round(1)
segt["share_rev"] = (100 * segt.M_sum / segt.M_sum.sum()).round(1)
M["rfm"] = segt.reset_index().to_dict("records"); M["rfm_asof"] = str(asof.date()); M["rfm_customers"] = int(len(C))
M["rfm_rev_share_of_total"] = round(100 * C.M.sum() / iss.revenue.sum(), 1)
# повтор за 30 дней (когорта первой наблюдаемой покупки, полное окно)
first = iss[iss.customer_key != "ANON"].groupby("customer_key").created_at.min()
full = first[first <= O.created_at.max() - pd.Timedelta(days=30)]
nxt = iss[iss.customer_key.isin(full.index)].merge(full.rename("first"), left_on="customer_key", right_index=True)
rep = nxt[(nxt.created_at > nxt["first"]) & (nxt.created_at <= nxt["first"] + pd.Timedelta(days=30))].customer_key.nunique()
M["repeat30"] = round(100 * rep / len(full), 1); M["repeat30_n"] = int(len(full))
# повтор по формату первой покупки
fo = iss[iss.customer_key.isin(full.index)].sort_values("created_at").groupby("customer_key").order_type.first()
rep_set = set(nxt[(nxt.created_at > nxt["first"]) & (nxt.created_at <= nxt["first"] + pd.Timedelta(days=30))].customer_key)
M["repeat30_by_first_format"] = fo.to_frame().assign(rep=lambda d: d.index.isin(rep_set)).groupby("order_type").rep.agg(["size", "mean"]).assign(mean=lambda d: (100 * d["mean"]).round(1)).reset_index().to_dict("records")

# ===== прогноз: недельная выручка =====
wk = iss.groupby("week_start").revenue.sum()
wk = wk[(wk.index >= "2026-04-06") & (wk.index <= "2026-10-19")]       # только полные недели (пн–вс)
train, test = wk.iloc[:-4], wk.iloc[-4:]
x = np.arange(len(wk)); a, b = np.polyfit(x[:-4], train.values, 1)
lin = a * x + b
ma4 = wk.rolling(4).mean().shift(1)
naive = wk.shift(1)
def mape(p, t): return round(float(np.mean(np.abs((t - p) / t)) * 100), 2)
M["forecast"] = dict(weeks=len(wk), train=len(train), test=len(test), slope_per_week=round(a), intercept=round(b),
                     mape_linear=mape(lin[-4:], test.values), mape_ma4=mape(ma4.iloc[-4:].values, test.values),
                     mape_naive=mape(naive.iloc[-4:].values, test.values))
a2, b2 = np.polyfit(x, wk.values, 1)
fx = np.arange(len(wk), len(wk) + 4)
fut = pd.date_range(wk.index[-1] + pd.Timedelta(days=7), periods=4, freq="7D")
resid = wk.values - (a2 * x + b2); sd = resid.std(ddof=2)
M["forecast"]["next4"] = [dict(week=str(d.date()), forecast=round(a2 * i + b2), lo=round(a2 * i + b2 - 1.96 * sd), hi=round(a2 * i + b2 + 1.96 * sd)) for d, i in zip(fut, fx)]
M["forecast"]["slope_full"] = round(a2); M["forecast"]["resid_sd"] = round(sd)
M["forecast"]["series"] = [dict(week=str(k.date()), revenue=round(v), linear=round(l), ma4=None if np.isnan(m) else round(m)) for k, v, l, m in zip(wk.index, wk.values, lin, ma4.values)]
# сравнение периодов: сентябрь vs август, последние 4 недели vs предыдущие 4
mo = iss.groupby("month").agg(revenue=("revenue", "sum"), orders=("revenue", "size"), avg_check=("revenue", "mean")).round(0)
M["monthly"] = mo.reset_index().to_dict("records")
json.dump(M, open("out/metrics.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)

# ===== агрегаты для дашборда (день × категория × формат) =====
agg = F.groupby([F.created_at.dt.date.astype(str), "category", "order_type"]).agg(
    rev=("revenue", "sum"), mar=("gross_margin", "sum")).reset_index().rename(columns={"created_at": "d"})
oagg = O.assign(d=O.created_at.dt.date.astype(str)).groupby(["d", "order_type"]).agg(
    reg=("paid", "size"), paid=("paid", "sum"), ready=("ready", "sum"), iss=("issued", "sum"),
    av=("cancel_stage", lambda s: int((s == "availability").sum())),
    wn=("wait", "count"), wsla=("wait", lambda s: int((s <= TAU).sum())), wsum=("wait", "sum"),
    rev=("revenue", "sum")).reset_index()
wh = O.dropna(subset=["wait"]).assign(d=O.created_at.dt.date.astype(str)).groupby(["d", "order_type", "hour"]).wait.apply(lambda s: [round(v, 1) for v in s]).reset_index()
dash = dict(metrics=M, sales=agg.round(0).values.tolist(), orders=oagg.round(1).values.tolist(), waits=wh.values.tolist(),
            categories=sorted(F.category.unique().tolist()),
            survey=S.assign(d=S.ts.dt.date.astype(str))[["d", "score", "intent", "waited_long"]].values.tolist(),
            reviews=R.assign(d=R.date.dt.date.astype(str))[["d", "theme", "rating", "cjm_stage"]].values.tolist())
json.dump(dash, open("out/dashboard_data.json", "w", encoding="utf-8"), ensure_ascii=False, default=str)
print(json.dumps({k: v for k, v in M.items() if k not in ("h1_wait_by_hour", "forecast", "h3_cat_share")}, ensure_ascii=False, indent=0, default=str)[:6000])
print(json.dumps({k: v for k, v in M["forecast"].items() if k != "series"}, ensure_ascii=False))
