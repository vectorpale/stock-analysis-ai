"""
全局测试配置 — Mock 外部 API，实现离线测试
所有网络调用被 Mock 数据替换，无需真实 API Key
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures import sample_data as SD


# ==================================================================
# 缓存目录隔离 — 每次测试使用临时目录
# ==================================================================
@pytest.fixture(autouse=True)
def isolate_cache(tmp_path, monkeypatch):
    """将 fetcher 模块的 CACHE_DIR / JSON_CACHE_DIR 重定向到临时目录"""
    cache_dir = tmp_path / "cache"
    json_cache_dir = tmp_path / "cache" / "json"
    cache_dir.mkdir(parents=True)
    json_cache_dir.mkdir(parents=True)

    import src.data.fetcher as fetcher_mod
    monkeypatch.setattr(fetcher_mod, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(fetcher_mod, "JSON_CACHE_DIR", json_cache_dir)


# ==================================================================
# 环境变量 Mock — 模拟有 API Key
# ==================================================================
@pytest.fixture
def env_all_keys(monkeypatch):
    """设置所有 API Key 环境变量 (假值)"""
    monkeypatch.setenv("FMP_API_KEY", "test_fmp_key_123")
    monkeypatch.setenv("TUSHARE_TOKEN", "test_tushare_token_456")
    monkeypatch.setenv("TUSHARE_URL", "http://mock.tushare.local")
    monkeypatch.setenv("NEWS_API_KEY", "test_news_key_789")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_anthropic_key")


@pytest.fixture
def env_fmp_only(monkeypatch):
    """只有 FMP API Key"""
    monkeypatch.setenv("FMP_API_KEY", "test_fmp_key_123")
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)


@pytest.fixture
def env_tushare_only(monkeypatch):
    """只有 Tushare Token"""
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("TUSHARE_TOKEN", "test_tushare_token_456")
    monkeypatch.setenv("TUSHARE_URL", "http://mock.tushare.local")


@pytest.fixture
def env_no_keys(monkeypatch):
    """无任何 API Key — 测试全降级到 yfinance"""
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_URL", raising=False)
    monkeypatch.delenv("NEWS_API_KEY", raising=False)


# ==================================================================
# Tushare Pro Mock
# ==================================================================
class MockTusharePro:
    """模拟 tushare.pro_api() 返回的对象"""

    def daily(self, ts_code=None, trade_date=None, start_date=None, end_date=None):
        return SD.tushare_daily(ts_code or "600519.SH")

    def daily_basic(self, ts_code=None, trade_date=None, start_date=None, end_date=None):
        return SD.tushare_daily_basic(ts_code or "600519.SH")

    def income(self, ts_code=None, period=None, report_type=None):
        return SD.tushare_income(ts_code or "600519.SH")

    def balancesheet(self, ts_code=None, period=None, report_type=None):
        return SD.tushare_balancesheet(ts_code or "600519.SH")

    def cashflow(self, ts_code=None, period=None, report_type=None):
        return SD.tushare_cashflow(ts_code or "600519.SH")

    def fina_indicator(self, ts_code=None, period=None, report_type=None):
        return SD.tushare_fina_indicator(ts_code or "600519.SH")

    def stock_company(self, ts_code=None, exchange=None):
        return SD.tushare_stock_company(ts_code or "600519.SH")

    # 港股
    def hk_basic(self, ts_code=None, list_status=None):
        return SD.tushare_hk_basic(ts_code or "00700.HK")

    def hk_daily(self, ts_code=None, trade_date=None, start_date=None, end_date=None):
        return SD.tushare_hk_daily(ts_code or "00700.HK")

    def hk_daily_adj(self, ts_code=None, trade_date=None, start_date=None, end_date=None):
        return SD.tushare_hk_daily_adj(ts_code or "00700.HK")

    def hk_fina_indicator(self, ts_code=None, period=None, report_type=None, fields=None):
        return SD.tushare_hk_fina_indicator(ts_code or "00700.HK")


@pytest.fixture
def mock_tushare_pro():
    """提供 MockTusharePro 实例"""
    return MockTusharePro()


# ==================================================================
# FMP Mock — 拦截 requests.get
# ==================================================================
class MockFMPResponse:
    """模拟 requests.get() 返回的 Response 对象"""

    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json


def fmp_router(url, params=None, timeout=None):
    """根据 URL 路由返回不同的 Mock 数据"""
    url = url.lower()
    if "/profile/" in url:
        return MockFMPResponse(SD.fmp_profile())
    elif "/key-metrics-ttm/" in url:
        return MockFMPResponse(SD.fmp_key_metrics())
    elif "/ratios-ttm/" in url:
        return MockFMPResponse(SD.fmp_ratios())
    elif "/analyst-estimates/" in url:
        return MockFMPResponse(SD.fmp_analyst_estimates())
    elif "/income-statement/" in url:
        return MockFMPResponse(SD.fmp_income_statement())
    elif "/balance-sheet-statement/" in url:
        return MockFMPResponse(SD.fmp_balance_sheet())
    elif "/cash-flow-statement/" in url:
        return MockFMPResponse(SD.fmp_cash_flow())
    elif "/historical-price-full/" in url:
        return MockFMPResponse(SD.fmp_historical_price())
    else:
        return MockFMPResponse(None, 404)


# ==================================================================
# yfinance Mock
# ==================================================================
class MockYFTicker:
    """模拟 yfinance.Ticker 对象"""

    def __init__(self, symbol="NVDA"):
        self.symbol = symbol
        self._info = SD.yfinance_info(symbol)
        self._history = SD.yfinance_history(symbol)

    @property
    def info(self):
        return self._info

    def history(self, period="1y", **kwargs):
        return self._history

    @property
    def financials(self):
        return pd.DataFrame({"2024-01-28": {"Total Revenue": 6.1e10, "Net Income": 2.98e10}})

    @property
    def balance_sheet(self):
        return pd.DataFrame({"2024-01-28": {"Total Assets": 6.5e10, "Total Debt": 9.7e9}})

    @property
    def cashflow(self):
        return pd.DataFrame({"2024-01-28": {"Free Cash Flow": 2.73e10}})

    @property
    def quarterly_financials(self):
        return pd.DataFrame({"2024-01-28": {"Total Revenue": 2.2e10}})

    @property
    def quarterly_balance_sheet(self):
        return pd.DataFrame({"2024-01-28": {"Total Assets": 6.5e10}})

    @property
    def quarterly_cashflow(self):
        return pd.DataFrame({"2024-01-28": {"Free Cash Flow": 8.5e9}})


# ==================================================================
# 综合 DataFetcher fixture — 完全离线
# ==================================================================
@pytest.fixture
def fetcher_us(env_fmp_only, monkeypatch):
    """美股 DataFetcher — FMP mock + yfinance mock"""
    monkeypatch.setattr("requests.get", fmp_router)

    from src.data.fetcher import DataFetcher
    df = DataFetcher()
    return df


@pytest.fixture
def fetcher_cn(env_tushare_only):
    """A 股 DataFetcher — Tushare mock"""
    from src.data.fetcher import DataFetcher
    df = DataFetcher()
    # 直接替换 _get_tushare_pro 方法
    df._get_tushare_pro = lambda: MockTusharePro()
    return df


@pytest.fixture
def fetcher_hk(env_tushare_only):
    """港股 DataFetcher — Tushare HK mock"""
    from src.data.fetcher import DataFetcher
    df = DataFetcher()
    df._get_tushare_pro = lambda: MockTusharePro()
    return df


@pytest.fixture
def fetcher_no_keys(env_no_keys):
    """无 API Key — 测试降级逻辑"""
    from src.data.fetcher import DataFetcher
    return DataFetcher()
