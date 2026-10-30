"""Источник 10: Open-Meteo Archive API (автоматизированный сбор).
Запуск: python fetch_weather.py 2026-04-01 2026-10-25 -> raw/weather_openmeteo.json"""
import json, sys, ssl, urllib.request, datetime as dt
import certifi
LAT, LON = 59.9446, 30.3035   # Биржевой пер., 2 (Васильевский остров)
start, end = sys.argv[1], sys.argv[2]
url = ("https://archive-api.open-meteo.com/v1/archive"
       f"?latitude={LAT}&longitude={LON}&start_date={start}&end_date={end}"
       "&daily=temperature_2m_mean,temperature_2m_max,precipitation_sum,rain_sum,snowfall_sum,wind_speed_10m_max"
       "&timezone=Europe%2FMoscow")
with urllib.request.urlopen(url, timeout=60, context=ssl.create_default_context(cafile=certifi.where())) as r:
    data = json.load(r)
data["_meta"] = {"source": "open-meteo archive api", "url": url,
                 "fetched_at": dt.datetime.now().isoformat(timespec="seconds")}
json.dump(data, open("raw/weather_openmeteo.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("days:", len(data["daily"]["time"]), "| first:", data["daily"]["time"][0], "| last:", data["daily"]["time"][-1])
