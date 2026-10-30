# Данные проекта «Газлайт»

Учебный набор: продажи, платежи, события, опрос и отзывы синтетические (generate_raw.py, seed 2026), погода реальная (Open-Meteo Archive API).

- `gaslight_calc.xlsx` — расчёты в Excel: KPI, описательная статистика, сводные, ожидание по часам, RFM, прогноз.
- `model/` — аналитическая модель «звезда»: fact_sales и 5 справочников.
- `etl_log.csv` — журнал преобразований ETL.
- `scripts/` — воспроизводимый конвейер: fetch_weather.py → generate_raw.py → etl.py → analysis.py → build_xlsx.py; engine.js и run.js — движок цифрового двойника и прогон сценариев (scenarios.json).
