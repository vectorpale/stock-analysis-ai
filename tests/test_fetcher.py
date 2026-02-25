"""
DataFetcher 离线单元测试
完全不依赖网络 — 所有外部 API 均被 Mock 替换

运行: pytest tests/test_fetcher.py -v
"""

import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from tests.fixtures import sample_data as SD


# ==================================================================
# 市场检测
# ==================================================================
class TestDetectMarket:
    def test_us_stock(self):
        from src.data.fetcher import DataFetcher
        assert DataFetcher.detect_market("NVDA") == "us"
        assert DataFetcher.detect_market("AAPL") == "us"
        assert DataFetcher.detect_market("TSLA") == "us"

    def test_hk_stock(self):
        from src.data.fetcher import DataFetcher
        assert DataFetcher.detect_market("00700.HK") == "hk"
        assert DataFetcher.detect_market("09988.HK") == "hk"

    def test_a_share(self):
        from src.data.fetcher import DataFetcher
        assert DataFetcher.detect_market("600519.SH") == "a_share"
        assert DataFetcher.detect_market("000001.SZ") == "a_share"


# ==================================================================
# OHLCV 标准化
# ==================================================================
class TestNormalizeOHLCV:
    def test_tushare_format(self):
        """Tushare 返回小写 open/high/low/close → 标准化为 Open/High/Low/Close"""
        from src.data.fetcher import DataFetcher
        df = SD.tushare_daily()
        result = DataFetcher._normalize_ohlcv(df)
        assert "Open" in result.columns
        assert "High" in result.columns
        assert "Low" in result.columns
        assert "Close" in result.columns
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_yfinance_format(self):
        """yfinance 返回已标准化的 OHLCV — 应保持不变"""
        from src.data.fetcher import DataFetcher
        df = SD.yfinance_history()
        result = DataFetcher._normalize_ohlcv(df)
        assert "Close" in result.columns
        assert isinstance(result.index, pd.DatetimeIndex)
        assert result.index.is_monotonic_increasing

    def test_chinese_columns(self):
        """中文列名 (AkShare 格式) → 标准化"""
        from src.data.fetcher import DataFetcher
        df = pd.DataFrame({
            "日期": ["2025-01-10", "2025-01-11"],
            "开盘": [100.0, 101.0],
            "最高": [105.0, 106.0],
            "最低": [98.0, 99.0],
            "收盘": [103.0, 104.0],
            "成交量": [10000, 12000],
        })
        result = DataFetcher._normalize_ohlcv(df)
        assert "Open" in result.columns
        assert "Close" in result.columns


# ==================================================================
# 美股: FMP 数据获取
# ==================================================================
class TestUSStockFMP:
    def test_fmp_price(self, fetcher_us):
        """FMP 历史价格获取"""
        df = fetcher_us._fetch_fmp_price("NVDA", "1y")
        assert df is not None
        assert not df.empty
        assert "Close" in df.columns
        assert "Volume" in df.columns
        assert isinstance(df.index, pd.DatetimeIndex)

    def test_fmp_key_metrics(self, fetcher_us):
        """FMP 关键指标获取"""
        result = fetcher_us._fetch_fmp_key_metrics("NVDA")
        assert result is not None
        assert result["company_name"] == "NVIDIA Corporation"
        assert result["sector"] == "Technology"
        assert result["pe_ratio"] == 65.2
        assert result["market_cap"] == 1.8e12

    def test_fmp_financials(self, fetcher_us):
        """FMP 财务报表获取"""
        result = fetcher_us._fetch_fmp_financials("NVDA")
        assert "income_statement" in result
        assert "balance_sheet" in result
        assert "cash_flow" in result

    def test_fetch_price_data_us(self, fetcher_us):
        """美股 fetch_price_data 走 FMP 优先路径"""
        df = fetcher_us.fetch_price_data("NVDA", "1y")
        assert df is not None
        assert not df.empty
        assert "Close" in df.columns


# ==================================================================
# A 股: Tushare 数据获取
# ==================================================================
class TestAShareTushare:
    def test_tushare_daily(self, fetcher_cn):
        """Tushare A 股日线"""
        df = fetcher_cn._fetch_tushare("600519.SH", "1y")
        assert df is not None
        assert not df.empty
        assert len(df) == 30

    def test_tushare_financials(self, fetcher_cn):
        """Tushare A 股财报"""
        result = fetcher_cn._fetch_tushare_financials("600519.SH")
        assert "income_statement" in result
        assert "balance_sheet" in result
        assert "cash_flow" in result

    def test_tushare_key_metrics(self, fetcher_cn):
        """Tushare A 股关键指标"""
        result = fetcher_cn._fetch_tushare_key_metrics("600519.SH")
        assert result is not None
        assert result["company_name"] != "600519.SH" or "error" not in result
        # 验证数值字段
        assert result.get("pe_ratio") is not None or result.get("eps") is not None

    def test_fetch_price_data_cn(self, fetcher_cn):
        """A 股 fetch_price_data 走 Tushare 优先路径"""
        df = fetcher_cn.fetch_price_data("600519.SH", "1y")
        assert df is not None
        assert not df.empty
        assert "Close" in df.columns

    def test_fetch_financials_cn(self, fetcher_cn):
        """A 股 fetch_financials 走 Tushare 路径"""
        result = fetcher_cn.fetch_financials("600519.SH")
        assert result is not None
        assert "income_statement" in result


# ==================================================================
# 港股: Tushare HK 数据获取
# ==================================================================
class TestHKStockTushare:
    def test_hk_daily(self, fetcher_hk):
        """Tushare 港股日线"""
        df = fetcher_hk._fetch_tushare_hk("00700.HK", "1y")
        assert df is not None
        assert not df.empty

    def test_hk_financials_returns_empty(self, fetcher_hk):
        """港股财报应返回空 (Tushare 不支持港股原始报表)"""
        result = fetcher_hk._fetch_tushare_hk_financials("00700.HK")
        assert result == {}

    def test_hk_key_metrics(self, fetcher_hk):
        """Tushare 港股指标 (hk_basic + hk_daily_adj + hk_fina_indicator)"""
        result = fetcher_hk._fetch_tushare_hk_key_metrics("00700.HK")
        assert result is not None
        assert result["company_name"] == "腾讯控股"
        # hk_daily_adj 提供的字段
        assert result.get("market_cap") is not None
        assert result.get("shares_outstanding") is not None
        assert result.get("float_shares") is not None
        # hk_fina_indicator 提供的字段
        assert result.get("eps") is not None
        assert result.get("roe") is not None

    def test_hk_key_metrics_52w(self, fetcher_hk):
        """港股 52 周高低点计算"""
        result = fetcher_hk._fetch_tushare_hk_key_metrics("00700.HK")
        assert result.get("52w_high") is not None
        assert result.get("52w_low") is not None
        assert result["52w_high"] >= result["52w_low"]

    def test_fetch_price_data_hk(self, fetcher_hk):
        """港股 fetch_price_data 走 Tushare 优先路径"""
        df = fetcher_hk.fetch_price_data("00700.HK", "1y")
        assert df is not None
        assert not df.empty
        assert "Close" in df.columns

    def test_hk_roe_is_ratio(self, fetcher_hk):
        """港股 ROE 应除以 100 转为小数"""
        result = fetcher_hk._fetch_tushare_hk_key_metrics("00700.HK")
        roe = result.get("roe")
        if roe is not None:
            assert roe < 1.0, "ROE 应为小数形式 (如 0.18) 而非百分比 (18)"


# ==================================================================
# 数据源降级 (Fallback) 逻辑
# ==================================================================
class TestFallbackLogic:
    def test_us_fmp_fails_yfinance_fallback(self, env_fmp_only, monkeypatch):
        """美股 FMP 失败后降级到 yfinance"""
        from tests.conftest import MockFMPResponse, MockYFTicker
        # FMP 返回 404
        monkeypatch.setattr("requests.get", lambda *a, **kw: MockFMPResponse(None, 404))

        from src.data.fetcher import DataFetcher
        fetcher = DataFetcher()

        # Mock yfinance
        with patch.dict("sys.modules", {"yfinance": MagicMock()}):
            import sys
            mock_yf = sys.modules["yfinance"]
            mock_yf.Ticker.return_value = MockYFTicker("NVDA")

            df = fetcher.fetch_price_data("NVDA", "1y")
            assert df is not None
            assert not df.empty
            assert "Close" in df.columns

    def test_cn_tushare_fails_returns_none(self, fetcher_cn):
        """A 股 Tushare 失败后，如果没有 AkShare/BaoStock 也不崩溃"""
        # 让 tushare pro 的 daily 返回空
        mock_pro = MagicMock()
        mock_pro.daily.return_value = pd.DataFrame()
        fetcher_cn._get_tushare_pro = lambda: mock_pro

        # Mock akshare 和 baostock 都不可用
        with patch.dict("sys.modules", {
            "akshare": MagicMock(**{"stock_zh_a_hist.return_value": pd.DataFrame()}),
            "baostock": MagicMock(),
        }):
            df = fetcher_cn.fetch_price_data("600519.SH", "1y")
            # 可能返回 None (所有源都失败)，但不应抛异常

    def test_hk_tushare_fails_yfinance_fallback(self, fetcher_hk, monkeypatch):
        """港股 Tushare 失败后降级到 yfinance"""
        from tests.conftest import MockYFTicker
        # 让 tushare daily 失败
        mock_pro = MagicMock()
        mock_pro.hk_daily.return_value = pd.DataFrame()
        fetcher_hk._get_tushare_pro = lambda: mock_pro

        with patch.dict("sys.modules", {"yfinance": MagicMock()}):
            import sys
            mock_yf = sys.modules["yfinance"]
            mock_yf.Ticker.return_value = MockYFTicker("00700.HK")

            df = fetcher_hk.fetch_price_data("00700.HK", "1y")
            # yfinance 作为兜底应成功
            assert df is not None

    def test_no_keys_key_metrics_yfinance(self, env_no_keys, monkeypatch):
        """无 API Key 时，fetch_key_metrics 直接走 yfinance"""
        from tests.conftest import MockYFTicker

        with patch.dict("sys.modules", {"yfinance": MagicMock()}):
            import sys
            mock_yf = sys.modules["yfinance"]
            mock_yf.Ticker.return_value = MockYFTicker("NVDA")

            from src.data.fetcher import DataFetcher
            fetcher = DataFetcher()
            result = fetcher.fetch_key_metrics("NVDA")
            assert result["company_name"] == "NVIDIA Corporation"
            assert result["sector"] == "Technology"


# ==================================================================
# 缓存系统
# ==================================================================
class TestCache:
    def test_df_cache_roundtrip(self, fetcher_cn):
        """DataFrame 缓存写入和读取"""
        df = SD.tushare_daily()
        fetcher_cn._set_cache("TEST", "test_data", df)
        cached = fetcher_cn._get_cached("TEST", "test_data")
        assert cached is not None
        assert len(cached) == len(df)

    def test_json_cache_roundtrip(self, fetcher_cn):
        """JSON 缓存写入和读取"""
        data = {"company_name": "Test Corp", "pe_ratio": 25.3}
        fetcher_cn._set_json_cache("TEST", "test_metrics", data)
        cached = fetcher_cn._get_json_cached("TEST", "test_metrics")
        assert cached is not None
        assert cached["company_name"] == "Test Corp"

    def test_cache_isolation(self, fetcher_cn, fetcher_hk):
        """不同 fetcher 的缓存互不影响 (通过不同 symbol key)"""
        fetcher_cn._set_json_cache("600519.SH", "test", {"market": "cn"})
        fetcher_hk._set_json_cache("00700.HK", "test", {"market": "hk"})

        cn_cache = fetcher_cn._get_json_cached("600519.SH", "test")
        hk_cache = fetcher_hk._get_json_cached("00700.HK", "test")
        assert cn_cache["market"] == "cn"
        assert hk_cache["market"] == "hk"

    def test_price_data_uses_cache(self, fetcher_us):
        """第二次调用应命中缓存，不再调 API"""
        df1 = fetcher_us.fetch_price_data("NVDA", "1y")
        assert df1 is not None

        # 把 FMP 搞坏
        original = fetcher_us._fetch_fmp_price
        fetcher_us._fetch_fmp_price = lambda *a, **kw: None

        df2 = fetcher_us.fetch_price_data("NVDA", "1y")
        assert df2 is not None  # 应从缓存获取
        assert len(df2) == len(df1)

        fetcher_us._fetch_fmp_price = original


# ==================================================================
# 辅助方法
# ==================================================================
class TestHelpers:
    def test_period_to_start(self):
        from src.data.fetcher import DataFetcher
        from datetime import datetime, timedelta
        start = DataFetcher._period_to_start("1y")
        expected = datetime.now() - timedelta(days=365)
        # 允许 1 秒误差
        assert abs((start - expected).total_seconds()) < 1

    def test_period_to_start_unknown(self):
        from src.data.fetcher import DataFetcher
        from datetime import datetime, timedelta
        start = DataFetcher._period_to_start("unknown_period")
        expected = datetime.now() - timedelta(days=365)  # 默认 1 年
        assert abs((start - expected).total_seconds()) < 1

    def test_safe_float(self, fetcher_cn):
        assert fetcher_cn._safe_float(42.5) == 42.5
        assert fetcher_cn._safe_float("123.45") == 123.45
        assert fetcher_cn._safe_float(None) is None
        assert fetcher_cn._safe_float("not_a_number") is None
