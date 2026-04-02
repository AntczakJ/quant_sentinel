"""
data_sources.py — interfejs dla różnych dostawców danych.
"""

import os
import pandas as pd
import requests
import time
from typing import Optional
from src.config import TD_API_KEY, ALPHA_VANTAGE_KEY
from src.logger import logger

class DataProvider:
    def get_candles(self, symbol: str, interval: str, count: int) -> Optional[pd.DataFrame]:
        raise NotImplementedError
    def get_current_price(self, symbol: str) -> Optional[float]:
        raise NotImplementedError
    def get_exchange_rate(self, base: str, target: str) -> Optional[float]:
        raise NotImplementedError

class TwelveDataProvider(DataProvider):
    def __init__(self, api_key):
        self.api_key = api_key
        self.base = "https://api.twelvedata.com"
    def _req(self, endpoint, params):
        params['apikey'] = self.api_key
        try:
            r = requests.get(f"{self.base}/{endpoint}", params=params, timeout=10)
            return r.json()
        except Exception as e:
            logger.error(f"TwelveData request error: {e}")
            return {}
    def get_candles(self, symbol, interval, count):
        td_interval = interval if 'min' in interval else interval.replace('m', 'min')
        data = self._req('time_series', {'symbol': symbol, 'interval': td_interval, 'outputsize': count})
        if 'values' not in data:
            return None
        df = pd.DataFrame(data['values'])
        df[['open','high','low','close']] = df[['open','high','low','close']].apply(pd.to_numeric)
        df = df.iloc[::-1].reset_index(drop=True)
        return df
    def get_current_price(self, symbol):
        data = self._req('price', {'symbol': symbol})
        if 'price' in data:
            return float(data['price'])
        return None
    def get_exchange_rate(self, base, target):
        data = self._req('price', {'symbol': f'{base}/{target}'})
        if 'price' in data:
            return float(data['price'])
        return None

class AlphaVantageProvider(DataProvider):
    def __init__(self, api_key):
        self.api_key = api_key
        self.base = "https://www.alphavantage.co/query"
    def _req(self, function, params):
        params['apikey'] = self.api_key
        params['function'] = function
        try:
            r = requests.get(self.base, params=params, timeout=10)
            return r.json()
        except Exception as e:
            logger.error(f"AlphaVantage error: {e}")
            return {}
    def get_candles(self, symbol, interval, count):
        interval_map = {'5m':'5min','15m':'15min','1h':'60min','4h':'60min'}
        av_interval = interval_map.get(interval, '60min')
        data = self._req('TIME_SERIES_INTRADAY', {'symbol': symbol, 'interval': av_interval, 'outputsize': 'full'})
        key = f'Time Series ({av_interval})'
        if key not in data:
            return None
        df = pd.DataFrame.from_dict(data[key], orient='index')
        df.index = pd.to_datetime(df.index)
        df = df.sort_index().tail(count)
        df[['1. open','2. high','3. low','4. close']] = df[['1. open','2. high','3. low','4. close']].apply(pd.to_numeric)
        df.columns = ['open','high','low','close','volume']
        return df.reset_index(drop=True)
    def get_current_price(self, symbol):
        data = self._req('GLOBAL_QUOTE', {'symbol': symbol})
        if 'Global Quote' in data and '05. price' in data['Global Quote']:
            return float(data['Global Quote']['05. price'])
        return None
    def get_exchange_rate(self, base, target):
        data = self._req('CURRENCY_EXCHANGE_RATE', {'from_currency': base, 'to_currency': target})
        if 'Realtime Currency Exchange Rate' in data:
            return float(data['Realtime Currency Exchange Rate']['5. Exchange Rate'])
        return None

def get_provider(name=None):
    name = name or os.getenv('DATA_PROVIDER', 'twelve_data')
    if name == 'twelve_data':
        return TwelveDataProvider(TD_API_KEY)
    elif name == 'alpha_vantage':
        return AlphaVantageProvider(ALPHA_VANTAGE_KEY)
    else:
        return TwelveDataProvider(TD_API_KEY)