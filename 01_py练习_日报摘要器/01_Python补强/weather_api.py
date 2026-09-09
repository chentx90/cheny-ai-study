import requests
import json
from datetime import datetime
from time import time

from logger import Logger
from pathlib import Path
from urllib.parse import quote

#尝试请求API，处理可能出现的异常

#进行数据验证，进行数据解析获取目标数据

#打印，输出json

log = Logger(file_path=Path("logs/weather.log"), to_console=True)

# 缓存层
_cache:dict[str, tuple[dict, float]] = {}
CACHE_TTL = 60 * 5

def fetch_weather(city: str) -> dict | None:
    """
    获取天气原始json
    Args：
        city：城市名，例如 "beijing"
    Returns:
        成功返回原始JSON，失败返回None
    """
    city = quote(city)
    url = f"https://wttr.in/{city}?format=j1"
    log.info(f"开始请求{city}")
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        log.error(f"请求超时：{city}")
        return None
    except requests.exceptions.ConnectionError:
        log.error(f"网络连接错误：{city}")
        return None
    except requests.exceptions.HTTPError as e:
        log.error(f"HTTP错误 {e.response.status_code}:{city}")
        return None
    except json.JSONDecodeError:
        log.error(f"JSON 解析错误：{city}")
        return None

def parse_weather(raw: dict) -> dict:
    """
    从原始 JSON 提取目标的字段。
    """
    city = raw["nearest_area"][0]["areaName"][0]["value"]   # 城市名
    temp_c = raw["current_condition"][0]["temp_C"]            # 温度
    feels_like_c = raw["current_condition"][0]["FeelsLikeC"]        # 体感温度
    weather_desc = raw["current_condition"][0]["weatherDesc"][0]["value"]  # 中文天气描述
    humidity = raw["current_condition"][0]["humidity"]          # 湿度
    wind_speed_kmph = raw["current_condition"][0]["windspeedKmph"]     # 风速
    return {
        "city": city,
        "temp_c": temp_c,
        "feels_like_c": feels_like_c,
        "weather_desc": weather_desc,
        "humidity": humidity,
        "wind_speed_kmph": wind_speed_kmph,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

def display (weather: dict) -> None:
    """可读格式打印到控制台。"""
    print((f"""\
        城市：{weather["city"]}
        温度：{weather["temp_c"]}
        体感温度：{weather["feels_like_c"]}
        天气情况：{weather["weather_desc"]}
        湿度：{weather["humidity"]}
        风速：{weather["wind_speed_kmph"]}
        数据时间：{weather["fetched_at"]}
    """).strip())

def get_weather_cached(city: str) -> dict | None:
    """带缓存的天气查询。

    Returns:
        成功返回 weather dict；失败返回 None。
    """
    now = time()

    if city in _cache:
        cached_weather, cached_at = _cache[city]
        if now - cached_at < CACHE_TTL:
            log.info(f"缓存命中：{city}（{int(now-cached_at)}秒前）")
            return cached_weather

    log.info(f"缓存未命中：{city}，发起请求")
    raw = fetch_weather(city)
    if raw is None:
        return None
    weather = parse_weather(raw)
    _cache[city] = (weather, now)
    return weather


def fetch_many(cities: list[str]) -> list[dict]:
    """批量获取多个城市天气。

    一个城市失败不影响其他。
    """
    results = []
    for city in cities:
        weather = get_weather_cached(city)
        if weather is None:
            log.warn(f"跳过 {city}（请求失败）")
            continue
        results.append(weather)
    return results


def save_json(results: list[dict], output_path: Path) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info(f"天气数据已存入：{str(output_path)}")

def main():
    cities = ["Beijing", "上海", "Shanghai", "Beijing"]

    weathers = fetch_many(cities)

    for weather in weathers:
        display(weather)

    save_json(weathers, Path("weather_many.json"))
    log.info(f"完成：共 {len(weathers)}/{len(cities)} 个城市")

if __name__ == "__main__":
    main()
