import os
import re
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd
import requests

from quant_app.core.logger import get_logger
from quant_app.core.market_data_center import market_data_center
from quant_app.core.mt5_client import mt5_client

logger = get_logger("CrawlerEngine")


class NewsEngine:
    """针对 FXStreet 的精准同步新闻抓取。"""

    @staticmethod
    def get_real_news(count=25):
        try:
            sources = [
                "https://www.fxstreet.com/rss/news",
                "https://www.fxstreet.com/rss/cryptocurrencies",
                "https://www.fxstreet.com/rss/analysis",
            ]
            headers = {"User-Agent": "Mozilla/5.0"}

            all_items = []
            for url in sources:
                try:
                    response = requests.get(url, headers=headers, timeout=1.5)
                    response.encoding = "utf-8"
                    items = re.findall(r"<item>(.*?)</item>", response.text, re.S)
                    all_items.extend(items)
                except Exception:
                    continue

            news_list = []
            seen_titles = set()
            for item in all_items:
                title_match = re.search(r"<title>(.*?)</title>", item)
                date_match = re.search(r"<pubDate>(.*?)</pubDate>", item)
                link_match = re.search(r"<link>(.*?)</link>", item)
                desc_match = re.search(r"<description>(.*?)</description>", item, re.S)

                if not title_match:
                    continue

                title = title_match.group(1).replace("<![CDATA[", "").replace("]]>", "").strip()
                if title in seen_titles:
                    continue
                seen_titles.add(title)

                link = link_match.group(1) if link_match else ""
                desc = (
                    desc_match.group(1).replace("<![CDATA[", "").replace("]]>", "").strip()
                    if desc_match
                    else "无摘要内容"
                )

                raw_date = date_match.group(1) if date_match else ""
                try:
                    dt = datetime.strptime(raw_date, "%a, %d %b %Y %H:%M:%S Z")
                    show_time = dt.strftime("%Y.%m.%d %H:%M")
                except Exception:
                    time_match = re.search(r"(\d{2}:\d{2})", raw_date)
                    show_time = time_match.group(1) if time_match else "实时"

                cat = "Forecast" if "Forecast" in title else "News"
                news_list.append(
                    {
                        "title": title,
                        "time": show_time,
                        "cat": cat,
                        "link": link,
                        "desc": desc,
                    }
                )
                if len(news_list) >= count:
                    break
            return news_list
        except Exception as exc:
            logger.error(f"新闻抓取失败: {exc}")
            return []


news_engine = NewsEngine()


class DataEngine:
    """数据采集与处理引擎。"""

    def __init__(self, storage_path="data/"):
        self.storage_path = storage_path
        if not os.path.exists(storage_path):
            os.makedirs(storage_path, exist_ok=True)

    def download_history(self, symbol="XAUUSD.c", timeframe=mt5.TIMEFRAME_H1, count=1000):
        """下载历史数据并保存。"""
        if not mt5_client.ensure_connected():
            return None

        logger.info(f"下载 {symbol} 历史数据 ({count} 根K线)...")
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)

        if rates is None or len(rates) == 0:
            logger.error(f"下载失败: {mt5.last_error()}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")

        filename = os.path.join(self.storage_path, f"{symbol}_{timeframe}.csv")
        df.to_csv(filename, index=False)
        return df

    def get_market_data(self, symbol, timeframe_str, count=100, start_pos=0):
        """给 UI 提供统一的实时行情数据入口。"""
        return market_data_center.get_market_data(symbol, timeframe_str, count=count, start_pos=start_pos)

    def get_multi_timeframe_context(self, symbol="XAUUSD.c", target_tf_str="M1"):
        """获取指定周期与 H1 趋势参考。"""
        df_target, df_h1 = market_data_center.get_multi_timeframe_context(symbol=symbol, target_tf_str=target_tf_str)
        if df_h1 is None or df_target is None:
            return None, None
        df_target = self.calculate_scalp_features(df_target)
        return df_target, df_h1

    def calculate_scalp_features(self, df):
        """K线特征提取。"""
        if df is None or len(df) < 2:
            return df

        df["direction"] = (df["close"] - df["open"]).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        df["body_size"] = abs(df["close"] - df["open"])
        df["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
        df["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]
        return df


data_engine = DataEngine()

