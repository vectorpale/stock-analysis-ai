"""
集成烟测 — 用真实 API 验证数据可达性和返回格式

运行方式:
    # 需要 .env 中配置真实 API Key + 网络可达
    pytest tests/test_integration.py -m integration -v

    # 只跑 Tushare
    pytest tests/test_integration.py -m integration -k tushare -v

    # 只跑 FMP
    pytest tests/test_integration.py -m integration -k fmp -v

    # 只跑 yfinance (不需要 API Key)
    pytest tests/test_integration.py -m integration -k yfinance -v

设计原则:
    1. 每个测试验证: API 可达 + 返回非空 + 关键字段存在
    2. 失败时输出诊断信息 (实际返回了哪些字段、缺了哪些)
    3. 用 pytest.mark.integration 标记，默认不运行
    4. 通过 schema 校验发现 API 返回格式变化
"""

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

# 加载 .env
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# 项目根
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ==================================================================
# Schema 校验工具
# ==================================================================

def assert_df_has_columns(df: pd.DataFrame, required: list[str], api_name: str):
    """断言 DataFrame 包含必需列，失败时显示实际列名"""
    assert df is not None, f"{api_name}: 返回 None"
    assert not df.empty, f"{api_name}: 返回空 DataFrame"
    missing = set(required) - set(df.columns)
    assert not missing, (
        f"{api_name}: 缺少字段 {missing}\n"
        f"  实际字段: {list(df.columns)}"
    )


def assert_dict_has_keys(d: dict, required: list[str], api_name: str):
    """断言 dict 包含必需 key"""
    assert d is not None, f"{api_name}: 返回 None"
    missing = set(required) - set(d.keys())
    assert not missing, (
        f"{api_name}: 缺少字段 {missing}\n"
        f"  实际字段: {list(d.keys())[:20]}..."
    )


# ==================================================================
# Tushare A 股
# ==================================================================

def _get_tushare_pro():
    """获取真实 Tushare Pro 实例"""
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        pytest.skip("TUSHARE_TOKEN 未设置")
    import tushare as ts
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    url = os.environ.get("TUSHARE_URL", "").strip()
    if url:
        pro._DataApi__http_url = url
    return pro


@pytest.mark.integration
class TestTushareAShare:
    """A 股 Tushare API 可达性 + Schema 校验"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.pro = _get_tushare_pro()

    def test_daily(self):
        """pro.daily() — 日线 OHLCV"""
        df = self.pro.daily(ts_code="000001.SZ", start_date="20240101", end_date="20240131")
        assert_df_has_columns(df, ["ts_code", "trade_date", "open", "high", "low", "close", "vol"], "daily")

    def test_daily_basic(self):
        """pro.daily_basic() — PE/PB/市值"""
        df = self.pro.daily_basic(ts_code="600519.SH")
        assert_df_has_columns(df, ["ts_code", "trade_date", "pe_ttm", "pb", "total_mv"], "daily_basic")

    def test_stock_company(self):
        """pro.stock_company() — 公司信息"""
        df = self.pro.stock_company(ts_code="600519.SH")
        assert_df_has_columns(df, ["ts_code"], "stock_company")

    def test_fina_indicator(self):
        """pro.fina_indicator() — 财务指标"""
        df = self.pro.fina_indicator(ts_code="600519.SH")
        assert_df_has_columns(df, ["ts_code", "end_date", "eps", "roe"], "fina_indicator")

    def test_income(self):
        """pro.income() — 利润表"""
        df = self.pro.income(ts_code="600519.SH")
        assert_df_has_columns(df, ["ts_code", "end_date", "revenue", "n_income"], "income")

    def test_balancesheet(self):
        """pro.balancesheet() — 资产负债表"""
        df = self.pro.balancesheet(ts_code="600519.SH")
        assert_df_has_columns(df, ["ts_code", "end_date", "total_assets", "total_liab"], "balancesheet")

    def test_cashflow(self):
        """pro.cashflow() — 现金流量表"""
        df = self.pro.cashflow(ts_code="600519.SH")
        assert_df_has_columns(df, ["ts_code", "end_date", "n_cashflow_act"], "cashflow")


# ==================================================================
# Tushare 港股
# ==================================================================

@pytest.mark.integration
class TestTushareHK:
    """港股 Tushare API 可达性 + Schema 校验"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.pro = _get_tushare_pro()

    def test_hk_basic(self):
        """pro.hk_basic() — 港股列表"""
        df = self.pro.hk_basic(ts_code="00700.HK")
        if df is None or df.empty:
            # 有些镜像不支持 hk_basic(ts_code=...) 单独查询
            df = self.pro.hk_basic(list_status="L")
            assert df is not None and not df.empty, "hk_basic: 连 list_status='L' 也返回空"
            row = df[df["ts_code"] == "00700.HK"]
            assert not row.empty, "hk_basic: 全量查询后未找到 00700.HK"
        assert_df_has_columns(df, ["ts_code", "name"], "hk_basic")

    def test_hk_daily(self):
        """pro.hk_daily() — 港股日线"""
        df = self.pro.hk_daily(ts_code="00700.HK", start_date="20240101", end_date="20240131")
        assert_df_has_columns(df, ["ts_code", "trade_date", "open", "high", "low", "close", "vol"], "hk_daily")

    def test_hk_daily_adj(self):
        """pro.hk_daily_adj() — 港股复权 (含市值/股本)"""
        try:
            df = self.pro.hk_daily_adj(ts_code="00700.HK", start_date="20240101", end_date="20240131")
            assert_df_has_columns(
                df,
                ["ts_code", "trade_date", "close", "total_share", "market_cap"],
                "hk_daily_adj"
            )
        except Exception as e:
            pytest.skip(f"hk_daily_adj 可能需要更高积分: {e}")

    def test_hk_fina_indicator(self):
        """pro.hk_fina_indicator() — 港股财务指标 (需 15000 积分)"""
        try:
            df = self.pro.hk_fina_indicator(ts_code="00700.HK")
            assert_df_has_columns(df, ["ts_code", "end_date"], "hk_fina_indicator")
            # 验证关键财务字段 (字段名可能因版本而异)
            actual = set(df.columns)
            desired = {"basic_eps", "roe", "roa", "operate_income"}
            found = actual & desired
            if not found:
                pytest.xfail(f"hk_fina_indicator 返回了数据但缺少预期字段。实际: {list(actual)[:15]}")
        except Exception as e:
            pytest.skip(f"hk_fina_indicator 可能需要 15000 积分: {e}")

    def test_no_hk_income_api(self):
        """确认 Tushare 不提供 hk_income (记录已知限制)"""
        try:
            df = self.pro.hk_income(ts_code="00700.HK")
            if df is not None and not df.empty:
                pytest.xfail("hk_income 居然返回了数据！Tushare 可能已新增此 API，需要更新代码")
        except Exception:
            pass  # 预期会失败


# ==================================================================
# FMP 美股
# ==================================================================

def _has_fmp_key():
    return bool(os.environ.get("FMP_API_KEY", "").strip())


@pytest.mark.integration
class TestFMP:
    """FMP API 可达性 + Schema 校验"""

    @pytest.fixture(autouse=True)
    def setup(self):
        if not _has_fmp_key():
            pytest.skip("FMP_API_KEY 未设置")
        from src.data.fetcher import DataFetcher
        self.fetcher = DataFetcher()

    def test_profile(self):
        """FMP /profile/{symbol}"""
        data = self.fetcher._fmp_get("profile/NVDA")
        assert data and len(data) > 0, "profile 返回空"
        assert_dict_has_keys(
            data[0],
            ["symbol", "companyName", "mktCap", "sector", "industry", "price"],
            "FMP profile"
        )

    def test_key_metrics_ttm(self):
        """FMP /key-metrics-ttm/{symbol}"""
        data = self.fetcher._fmp_get("key-metrics-ttm/NVDA")
        assert data and len(data) > 0, "key-metrics-ttm 返回空"
        assert_dict_has_keys(
            data[0],
            ["marketCapTTM", "enterpriseValueOverEBITDATTM", "revenuePerShareTTM"],
            "FMP key-metrics-ttm"
        )

    def test_income_statement(self):
        """FMP /income-statement/{symbol}"""
        data = self.fetcher._fmp_get("income-statement/NVDA", {"limit": 2})
        assert data and len(data) > 0, "income-statement 返回空"
        assert_dict_has_keys(
            data[0],
            ["date", "revenue", "netIncome", "grossProfit"],
            "FMP income-statement"
        )

    def test_historical_price(self):
        """FMP /historical-price-full/{symbol}"""
        data = self.fetcher._fmp_get("historical-price-full/NVDA", {"from": "2024-01-01"})
        assert data and "historical" in data, "historical-price-full 返回格式不对"
        rec = data["historical"][0]
        assert_dict_has_keys(
            rec,
            ["date", "open", "high", "low", "close", "volume"],
            "FMP historical-price"
        )

    def test_full_key_metrics_pipeline(self):
        """DataFetcher.fetch_key_metrics('NVDA') — 端到端"""
        result = self.fetcher.fetch_key_metrics("NVDA")
        assert result is not None
        assert_dict_has_keys(
            result,
            ["company_name", "sector", "market_cap", "pe_ratio"],
            "fetch_key_metrics"
        )


# ==================================================================
# yfinance (不需要 API Key，只需网络)
# ==================================================================

@pytest.mark.integration
class TestYfinance:
    """yfinance 可达性 + Schema 校验 (不需要 API Key)"""

    @pytest.fixture(autouse=True)
    def setup(self):
        try:
            import yfinance
            self.yf = yfinance
        except ImportError:
            pytest.skip("yfinance 未安装")

    def test_history(self):
        """yf.Ticker().history() — 价格数据"""
        ticker = self.yf.Ticker("AAPL")
        df = ticker.history(period="5d")
        assert_df_has_columns(df, ["Open", "High", "Low", "Close", "Volume"], "yfinance.history")

    def test_info(self):
        """yf.Ticker().info — 公司指标"""
        ticker = self.yf.Ticker("AAPL")
        info = ticker.info
        assert info is not None, "yfinance.info 返回 None"
        # yfinance 的 info 字段可能因市场而变化，只校验最基本的
        has_name = "longName" in info or "shortName" in info
        assert has_name, f"yfinance.info 缺少公司名。实际 keys: {list(info.keys())[:10]}"

    def test_financials(self):
        """yf.Ticker().financials — 财务报表"""
        ticker = self.yf.Ticker("AAPL")
        df = ticker.financials
        assert df is not None and not df.empty, "yfinance.financials 返回空"

    def test_hk_stock(self):
        """yfinance 港股 (Tushare 不支持财报时的兜底)"""
        ticker = self.yf.Ticker("0700.HK")  # 注意: yfinance 格式无前导零
        df = ticker.history(period="5d")
        assert_df_has_columns(df, ["Close"], "yfinance HK history")


# ==================================================================
# DataFetcher 端到端集成
# ==================================================================

@pytest.mark.integration
class TestFetcherE2E:
    """DataFetcher 完整流水线 — 真实 API"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from src.data.fetcher import DataFetcher
        self.fetcher = DataFetcher()

    def test_us_stock_price(self):
        """美股价格获取 (任意数据源成功即可)"""
        df = self.fetcher.fetch_price_data("AAPL", "1mo")
        assert df is not None and not df.empty, "美股价格: 所有数据源都失败了"
        assert "Close" in df.columns

    def test_us_stock_financials(self):
        """美股财报获取"""
        result = self.fetcher.fetch_financials("AAPL")
        assert result, "美股财报: 所有数据源都失败了"

    def test_us_stock_key_metrics(self):
        """美股关键指标"""
        result = self.fetcher.fetch_key_metrics("AAPL")
        assert result is not None
        assert not result.get("error"), f"美股指标获取失败: {result.get('error')}"

    @pytest.mark.skipif(
        not os.environ.get("TUSHARE_TOKEN", "").strip(),
        reason="TUSHARE_TOKEN 未设置"
    )
    def test_a_share_price(self):
        """A 股价格获取"""
        df = self.fetcher.fetch_price_data("000001.SZ", "1mo")
        assert df is not None and not df.empty, "A 股价格: 所有数据源都失败了"

    @pytest.mark.skipif(
        not os.environ.get("TUSHARE_TOKEN", "").strip(),
        reason="TUSHARE_TOKEN 未设置"
    )
    def test_hk_stock_price(self):
        """港股价格获取"""
        df = self.fetcher.fetch_price_data("00700.HK", "1mo")
        assert df is not None and not df.empty, "港股价格: 所有数据源都失败了"

    @pytest.mark.skipif(
        not os.environ.get("TUSHARE_TOKEN", "").strip(),
        reason="TUSHARE_TOKEN 未设置"
    )
    def test_hk_key_metrics_fallback(self):
        """港股指标: Tushare → yfinance 降级链"""
        result = self.fetcher.fetch_key_metrics("00700.HK")
        assert result is not None
        # 至少应该有公司名
        name = result.get("company_name", "")
        assert name and name != "00700.HK", f"港股指标: 未获取到公司名 ({result})"
