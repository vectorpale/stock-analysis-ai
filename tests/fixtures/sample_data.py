"""
离线测试夹具数据 — 模拟各数据源 API 返回格式
无需网络连接，可在任何环境下运行
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def _dates(n: int, end=None):
    """生成 n 个交易日的日期列表 (倒序，最新在前)"""
    end = end or datetime(2025, 1, 15)
    return [(end - timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


# ==================== Tushare A 股格式 ====================

def tushare_daily(ts_code="600519.SH", n=30):
    """模拟 pro.daily() 返回的 A 股日线数据"""
    dates = _dates(n)
    np.random.seed(42)
    base = 1800.0
    closes = base + np.cumsum(np.random.randn(n) * 15)
    return pd.DataFrame({
        "ts_code": ts_code,
        "trade_date": dates,
        "open": closes - np.random.uniform(5, 15, n),
        "high": closes + np.random.uniform(5, 20, n),
        "low": closes - np.random.uniform(10, 25, n),
        "close": closes,
        "pre_close": np.roll(closes, 1),
        "change": np.random.randn(n) * 10,
        "pct_chg": np.random.randn(n) * 0.5,
        "vol": np.random.uniform(20000, 50000, n),
        "amount": np.random.uniform(3e8, 8e8, n),
    })


def tushare_daily_basic(ts_code="600519.SH", n=5):
    """模拟 pro.daily_basic() 返回数据"""
    dates = _dates(n)
    return pd.DataFrame({
        "ts_code": ts_code,
        "trade_date": dates,
        "pe": [35.2, 34.8, 35.5, 36.1, 34.0],
        "pe_ttm": [34.5, 34.1, 35.0, 35.6, 33.5],
        "pb": [12.1, 11.9, 12.3, 12.5, 11.8],
        "ps": [15.6, 15.3, 15.8, 16.0, 15.1],
        "ps_ttm": [15.2, 14.9, 15.5, 15.7, 14.8],
        "total_mv": [2.25e7, 2.22e7, 2.28e7, 2.30e7, 2.20e7],
        "circ_mv": [2.10e7, 2.08e7, 2.13e7, 2.15e7, 2.06e7],
        "total_share": [12560.0] * 5,
        "float_share": [11740.0] * 5,
        "turnover_rate": [0.35, 0.42, 0.38, 0.45, 0.33],
    })


def tushare_income(ts_code="600519.SH"):
    """模拟 pro.income() 返回的 A 股利润表"""
    return pd.DataFrame({
        "ts_code": ts_code,
        "ann_date": ["20240430", "20240330", "20231028", "20230429"],
        "end_date": ["20231231", "20230630", "20230930", "20221231"],
        "revenue": [1.5e11, 7.2e10, 1.1e11, 1.27e11],
        "operate_profit": [1.05e11, 5.0e10, 7.8e10, 8.9e10],
        "n_income": [7.5e10, 3.6e10, 5.5e10, 6.3e10],
        "n_income_attr_p": [7.4e10, 3.5e10, 5.4e10, 6.2e10],
    })


def tushare_balancesheet(ts_code="600519.SH"):
    """模拟 pro.balancesheet() 返回"""
    return pd.DataFrame({
        "ts_code": ts_code,
        "end_date": ["20231231", "20230630", "20221231", "20220630"],
        "total_assets": [2.5e11, 2.3e11, 2.2e11, 2.0e11],
        "total_liab": [1.0e11, 9.5e10, 9.0e10, 8.5e10],
        "total_hldr_eqy_exc_min_int": [1.45e11, 1.3e11, 1.25e11, 1.1e11],
        "money_cap": [8.0e10, 7.5e10, 7.0e10, 6.5e10],
        "total_share": [12560.0, 12560.0, 12560.0, 12560.0],
    })


def tushare_cashflow(ts_code="600519.SH"):
    """模拟 pro.cashflow() 返回"""
    return pd.DataFrame({
        "ts_code": ts_code,
        "end_date": ["20231231", "20230630", "20221231", "20220630"],
        "n_cashflow_act": [5.5e10, 2.8e10, 4.8e10, 2.3e10],
        "n_cashflow_inv_act": [-1.2e10, -6.0e9, -1.0e10, -5.0e9],
        "n_cash_flows_fnc_act": [-3.5e10, -1.8e10, -3.0e10, -1.5e10],
        "free_cashflow": [4.3e10, 2.2e10, 3.8e10, 1.8e10],
    })


def tushare_fina_indicator(ts_code="600519.SH"):
    """模拟 pro.fina_indicator() 返回"""
    return pd.DataFrame({
        "ts_code": ts_code,
        "end_date": ["20231231", "20230630"],
        "eps": [59.49, 28.56],
        "roe": [33.85, 16.21],
        "grossprofit_margin": [91.96, 92.15],
        "netprofit_margin": [49.5, 48.6],
        "current_ratio": [3.78, 3.65],
        "debt_to_assets": [40.1, 41.3],
    })


def tushare_stock_company(ts_code="600519.SH"):
    """模拟 pro.stock_company() 返回"""
    return pd.DataFrame({
        "ts_code": [ts_code],
        "exchange": ["SSE"],
        "chairman": ["丁雄军"],
        "manager": ["王莉"],
        "province": ["贵州"],
        "city": ["遵义"],
        "introduction": ["贵州茅台酒股份有限公司是一家主要从事酒类生产和销售的公司。"],
        "employees": [28000],
        "main_business": ["白酒生产与销售"],
        "business_scope": ["酒类产品的生产经营"],
    })


# ==================== Tushare 港股格式 ====================

def tushare_hk_basic(ts_code="00700.HK"):
    """模拟 pro.hk_basic() 返回"""
    return pd.DataFrame({
        "ts_code": [ts_code],
        "name": ["腾讯控股"],
        "fullname": ["腾讯控股有限公司"],
        "enname": ["Tencent Holdings Limited"],
        "market": ["主板"],
        "list_status": ["L"],
        "list_date": ["20040616"],
        "industry": ["信息技术"],
        "curr_type": ["HKD"],
    })


def tushare_hk_daily(ts_code="00700.HK", n=30):
    """模拟 pro.hk_daily() 返回"""
    dates = _dates(n)
    np.random.seed(99)
    base = 380.0
    closes = base + np.cumsum(np.random.randn(n) * 5)
    return pd.DataFrame({
        "ts_code": ts_code,
        "trade_date": dates,
        "open": closes - np.random.uniform(1, 5, n),
        "high": closes + np.random.uniform(2, 8, n),
        "low": closes - np.random.uniform(3, 10, n),
        "close": closes,
        "pre_close": np.roll(closes, 1),
        "change": np.random.randn(n) * 3,
        "pct_chg": np.random.randn(n) * 0.8,
        "vol": np.random.uniform(1e7, 3e7, n),
        "amount": np.random.uniform(3e9, 1e10, n),
    })


def tushare_hk_daily_adj(ts_code="00700.HK", n=30):
    """模拟 pro.hk_daily_adj() 返回 (含市值/股本)"""
    df = tushare_hk_daily(ts_code, n)
    df["adj_factor"] = 1.0
    df["turnover_ratio"] = np.random.uniform(0.1, 0.5, n)
    df["total_share"] = 95000.0
    df["float_share"] = 92000.0
    df["market_cap"] = df["close"] * 95000
    return df


def tushare_hk_fina_indicator(ts_code="00700.HK"):
    """模拟 pro.hk_fina_indicator() 返回"""
    return pd.DataFrame({
        "ts_code": ts_code,
        "end_date": ["20231231", "20230630"],
        "basic_eps": [14.83, 6.28],
        "roe": [18.52, 8.91],
        "roa": [9.65, 4.73],
        "operate_income": [6.09e11, 2.93e11],
        "operate_income_yoy": [10.4, 11.2],
    })


# ==================== FMP 美股格式 ====================

def fmp_profile(symbol="NVDA"):
    """模拟 FMP /profile/{symbol} 返回"""
    return [{
        "symbol": symbol,
        "companyName": "NVIDIA Corporation",
        "currency": "USD",
        "exchangeShortName": "NASDAQ",
        "industry": "Semiconductors",
        "sector": "Technology",
        "mktCap": 1.8e12,
        "price": 730.0,
        "beta": 1.65,
        "volAvg": 42000000,
        "lastDiv": 0.16,
        "range": "400.0-950.0",
        "description": "NVIDIA Corporation is a visual computing company.",
    }]


def fmp_key_metrics(symbol="NVDA"):
    """模拟 FMP /key-metrics-ttm/{symbol} 返回"""
    return [{
        "peRatioTTM": 65.2,
        "pegRatioTTM": 1.35,
        "priceToBookRatioTTM": 45.8,
        "priceToSalesRatioTTM": 32.1,
        "enterpriseValueTTM": 1.75e12,
        "enterpriseValueOverEBITDATTM": 55.3,
        "marketCapTTM": 1.8e12,
        "debtToEquityTTM": 0.41,
        "currentRatioTTM": 4.17,
        "returnOnEquityTTM": 0.69,
        "returnOnAssetsTTM": 0.38,
        "dividendYieldTTM": 0.02,
        "revenuePerShareTTM": 22.7,
        "netIncomePerShareTTM": 11.2,
        "freeCashFlowPerShareTTM": 8.5,
        "operatingCashFlowPerShareTTM": 10.2,
        "cashPerShareTTM": 2.96,
        "totalDebtToCapitalizationTTM": 0.18,
    }]


def fmp_ratios(symbol="NVDA"):
    """模拟 FMP /ratios-ttm/{symbol} 返回"""
    return [{
        "peRatioTTM": 65.2,
        "pegRatioTTM": 1.35,
        "priceToBookRatioTTM": 45.8,
        "priceToSalesRatioTTM": 32.1,
        "enterpriseValueMultipleTTM": 28.7,
        "netProfitMarginTTM": 0.49,
        "operatingProfitMarginTTM": 0.54,
        "grossProfitMarginTTM": 0.73,
        "returnOnEquityTTM": 0.69,
        "returnOnAssetsTTM": 0.38,
        "debtEquityRatioTTM": 0.226,
        "currentRatioTTM": 4.17,
        "dividendYielTTM": 0.0002,
    }]


def fmp_analyst_estimates(symbol="NVDA"):
    """模拟 FMP /analyst-estimates/{symbol} 返回"""
    return [{
        "date": "2025-01-28",
        "estimatedRevenueAvg": 7.5e10,
        "estimatedEpsAvg": 15.2,
        "numberAnalystEstimatedRevenue": 38,
        "numberAnalystsEstimatedEps": 42,
    }]


def fmp_income_statement(symbol="NVDA"):
    """模拟 FMP /income-statement/{symbol} 返回"""
    return [
        {
            "date": "2024-01-28",
            "revenue": 6.097e10,
            "grossProfit": 4.426e10,
            "operatingIncome": 3.296e10,
            "netIncome": 2.978e10,
            "eps": 11.93,
        },
        {
            "date": "2023-01-29",
            "revenue": 2.697e10,
            "grossProfit": 1.560e10,
            "operatingIncome": 4.224e9,
            "netIncome": 4.368e9,
            "eps": 1.74,
        },
    ]


def fmp_balance_sheet(symbol="NVDA"):
    """模拟 FMP /balance-sheet-statement/{symbol} 返回"""
    return [
        {
            "date": "2024-01-28",
            "totalAssets": 6.5e10,
            "totalLiabilities": 2.2e10,
            "totalStockholdersEquity": 4.3e10,
            "cashAndCashEquivalents": 7.28e9,
            "totalDebt": 9.71e9,
        },
    ]


def fmp_cash_flow(symbol="NVDA"):
    """模拟 FMP /cash-flow-statement/{symbol} 返回"""
    return [
        {
            "date": "2024-01-28",
            "operatingCashFlow": 2.84e10,
            "capitalExpenditure": -1.07e9,
            "freeCashFlow": 2.73e10,
        },
    ]


def fmp_historical_price(symbol="NVDA", n=30):
    """模拟 FMP /historical-price-full/{symbol} 返回"""
    np.random.seed(77)
    base = 700.0
    closes = base + np.cumsum(np.random.randn(n) * 12)
    dates = _dates(n)
    historical = []
    for i in range(n):
        historical.append({
            "date": f"{dates[i][:4]}-{dates[i][4:6]}-{dates[i][6:]}",
            "open": float(closes[i] - np.random.uniform(3, 10)),
            "high": float(closes[i] + np.random.uniform(5, 15)),
            "low": float(closes[i] - np.random.uniform(8, 20)),
            "close": float(closes[i]),
            "volume": int(np.random.uniform(3e7, 6e7)),
        })
    return {"symbol": symbol, "historical": historical}


# ==================== yfinance 格式 ====================

def yfinance_history(symbol="NVDA", n=30):
    """模拟 yf.Ticker(symbol).history() 返回"""
    np.random.seed(55)
    base = 700.0
    closes = base + np.cumsum(np.random.randn(n) * 10)
    end = datetime(2025, 1, 15)
    dates = pd.date_range(end=end, periods=n, freq="B")
    return pd.DataFrame({
        "Open": closes - np.random.uniform(3, 10, n),
        "High": closes + np.random.uniform(5, 15, n),
        "Low": closes - np.random.uniform(8, 20, n),
        "Close": closes,
        "Volume": np.random.uniform(3e7, 6e7, n).astype(int),
    }, index=dates)


def yfinance_info(symbol="NVDA"):
    """模拟 yf.Ticker(symbol).info 返回"""
    return {
        "longName": "NVIDIA Corporation",
        "shortName": "NVIDIA",
        "sector": "Technology",
        "industry": "Semiconductors",
        "marketCap": 1800000000000,
        "enterpriseValue": 1750000000000,
        "trailingPE": 65.2,
        "forwardPE": 38.5,
        "pegRatio": 1.35,
        "priceToBook": 45.8,
        "priceToSalesTrailing12Months": 32.1,
        "enterpriseToEbitda": 55.3,
        "enterpriseToRevenue": 28.7,
        "profitMargins": 0.49,
        "operatingMargins": 0.54,
        "grossMargins": 0.73,
        "returnOnEquity": 0.69,
        "returnOnAssets": 0.38,
        "revenueGrowth": 1.22,
        "earningsGrowth": 5.81,
        "totalRevenue": 60970000000,
        "netIncomeToCommon": 29780000000,
        "totalDebt": 9710000000,
        "totalCash": 7280000000,
        "debtToEquity": 22.6,
        "currentRatio": 4.17,
        "freeCashflow": 27300000000,
        "operatingCashflow": 28400000000,
        "dividendYield": 0.0002,
        "beta": 1.65,
        "fiftyTwoWeekHigh": 950.0,
        "fiftyTwoWeekLow": 400.0,
        "fiftyDayAverage": 720.0,
        "twoHundredDayAverage": 650.0,
        "averageVolume": 42000000,
        "sharesOutstanding": 24600000000,
        "floatShares": 24200000000,
        "heldPercentInsiders": 0.041,
        "heldPercentInstitutions": 0.67,
        "shortRatio": 1.21,
        "targetMeanPrice": 850.0,
        "recommendationKey": "buy",
        "numberOfAnalystOpinions": 45,
    }
