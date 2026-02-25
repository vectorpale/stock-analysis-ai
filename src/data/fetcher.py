"""
数据获取模块 - 多源行情与财务数据
支持美股、港股、A股，带缓存和降级策略

数据源优先级:
  美股: FMP → yfinance → AkShare
  港股: AkShare → yfinance
  A股: AkShare → Tushare → BaoStock
"""

import json
import os
import logging
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# JSON 缓存目录 (给 FMP 等非 DataFrame 数据用)
JSON_CACHE_DIR = Path("data/cache/json")
JSON_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class DataFetcher:
    """多源股票数据获取器"""

    def __init__(self, cache_hours: int = 6):
        self.cache_hours = cache_hours
        self.fmp_key = os.environ.get("FMP_API_KEY", "").strip()
        self._fmp_base = "https://financialmodelingprep.com/api/v3"

    # ------------------------------------------------------------------
    # 市场检测
    # ------------------------------------------------------------------
    @staticmethod
    def detect_market(symbol: str) -> str:
        if symbol.endswith(".HK"):
            return "hk"
        if symbol.endswith((".SH", ".SZ")):
            return "a_share"
        return "us"

    # ------------------------------------------------------------------
    # 缓存 (DataFrame)
    # ------------------------------------------------------------------
    def _cache_key(self, symbol: str, data_type: str) -> Path:
        h = hashlib.md5(f"{symbol}_{data_type}".encode()).hexdigest()[:12]
        return CACHE_DIR / f"{h}.parquet"

    def _get_cached(self, symbol: str, data_type: str) -> Optional[pd.DataFrame]:
        path = self._cache_key(symbol, data_type)
        if path.exists():
            age = datetime.now().timestamp() - path.stat().st_mtime
            if age < self.cache_hours * 3600:
                try:
                    return pd.read_parquet(path)
                except Exception:
                    pass
        return None

    def _set_cache(self, symbol: str, data_type: str, df: pd.DataFrame):
        try:
            path = self._cache_key(symbol, data_type)
            df.to_parquet(path)
        except Exception as e:
            logger.warning(f"缓存写入失败: {e}")

    # ------------------------------------------------------------------
    # 缓存 (JSON - FMP 等)
    # ------------------------------------------------------------------
    def _json_cache_path(self, symbol: str, data_type: str) -> Path:
        h = hashlib.md5(f"{symbol}_{data_type}".encode()).hexdigest()[:12]
        return JSON_CACHE_DIR / f"{h}.json"

    def _get_json_cached(self, symbol: str, data_type: str):
        path = self._json_cache_path(symbol, data_type)
        if path.exists():
            age = datetime.now().timestamp() - path.stat().st_mtime
            if age < self.cache_hours * 3600:
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return None

    def _set_json_cache(self, symbol: str, data_type: str, data):
        try:
            path = self._json_cache_path(symbol, data_type)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"JSON 缓存写入失败: {e}")

    # ------------------------------------------------------------------
    # FMP API 调用
    # ------------------------------------------------------------------
    def _fmp_get(self, endpoint: str, params: dict = None) -> Optional[list | dict]:
        """调用 FMP API，返回 JSON 数据"""
        if not self.fmp_key:
            return None
        url = f"{self._fmp_base}/{endpoint}"
        all_params = {"apikey": self.fmp_key}
        if params:
            all_params.update(params)
        try:
            resp = requests.get(url, params=all_params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("Error Message"):
                    logger.warning(f"FMP 错误: {data['Error Message']}")
                    return None
                return data
            else:
                logger.warning(f"FMP HTTP {resp.status_code}: {endpoint}")
                return None
        except Exception as e:
            logger.warning(f"FMP 请求失败 {endpoint}: {e}")
            return None

    # ------------------------------------------------------------------
    # 价格数据
    # ------------------------------------------------------------------
    def fetch_price_data(self, symbol: str, period: str = "1y") -> Optional[pd.DataFrame]:
        """获取 OHLCV 价格数据"""
        cached = self._get_cached(symbol, f"price_{period}")
        if cached is not None:
            return cached

        market = self.detect_market(symbol)
        df = None

        if market == "us":
            df = self._fetch_fmp_price(symbol, period)
            if df is None:
                df = self._fetch_yfinance(symbol, period)
            if df is None:
                df = self._fetch_akshare_us(symbol, period)
        elif market == "hk":
            df = self._fetch_akshare_hk(symbol, period)
            if df is None:
                df = self._fetch_yfinance(symbol, period)
        elif market == "a_share":
            df = self._fetch_akshare_cn(symbol, period)
            if df is None:
                df = self._fetch_tushare(symbol, period)
            if df is None:
                df = self._fetch_baostock(symbol, period)

        if df is not None and not df.empty:
            df = self._normalize_ohlcv(df)
            self._set_cache(symbol, f"price_{period}", df)
        return df

    # ------------------------------------------------------------------
    # 财务数据
    # ------------------------------------------------------------------
    def fetch_financials(self, symbol: str) -> dict:
        """获取财务报表数据: 利润表、资产负债表、现金流量表"""
        cached = self._get_cached(symbol, "financials")
        if cached is not None:
            return {"_cached": True, "data": cached}

        market = self.detect_market(symbol)

        # FMP 优先 (美股)
        if market == "us" and self.fmp_key:
            result = self._fetch_fmp_financials(symbol)
            if result and any(v for v in result.values() if v):
                return result

        # yfinance 兜底
        result = {}
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            result["income_statement"] = self._df_to_dict(ticker.financials)
            result["balance_sheet"] = self._df_to_dict(ticker.balance_sheet)
            result["cash_flow"] = self._df_to_dict(ticker.cashflow)
            result["quarterly_income"] = self._df_to_dict(ticker.quarterly_financials)
            result["quarterly_balance"] = self._df_to_dict(ticker.quarterly_balance_sheet)
            result["quarterly_cashflow"] = self._df_to_dict(ticker.quarterly_cashflow)
            logger.info(f"yfinance 财报数据获取成功: {symbol}")
        except Exception as e:
            logger.warning(f"yfinance 财报获取失败 {symbol}: {e}")

        return result

    def fetch_key_metrics(self, symbol: str) -> dict:
        """获取关键估值与经营指标"""
        market = self.detect_market(symbol)

        # FMP 优先 (美股)
        if market == "us" and self.fmp_key:
            result = self._fetch_fmp_key_metrics(symbol)
            if result and not result.get("error"):
                return result

        # yfinance 兜底
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            return {
                "company_name": info.get("longName", info.get("shortName", symbol)),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
                "market_cap": info.get("marketCap"),
                "enterprise_value": info.get("enterpriseValue"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "pb_ratio": info.get("priceToBook"),
                "ps_ratio": info.get("priceToSalesTrailing12Months"),
                "ev_ebitda": info.get("enterpriseToEbitda"),
                "ev_revenue": info.get("enterpriseToRevenue"),
                "profit_margin": info.get("profitMargins"),
                "operating_margin": info.get("operatingMargins"),
                "gross_margin": info.get("grossMargins"),
                "roe": info.get("returnOnEquity"),
                "roa": info.get("returnOnAssets"),
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "revenue": info.get("totalRevenue"),
                "net_income": info.get("netIncomeToCommon"),
                "total_debt": info.get("totalDebt"),
                "total_cash": info.get("totalCash"),
                "debt_to_equity": info.get("debtToEquity"),
                "current_ratio": info.get("currentRatio"),
                "free_cash_flow": info.get("freeCashflow"),
                "operating_cash_flow": info.get("operatingCashflow"),
                "dividend_yield": info.get("dividendYield"),
                "beta": info.get("beta"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "50d_avg": info.get("fiftyDayAverage"),
                "200d_avg": info.get("twoHundredDayAverage"),
                "avg_volume": info.get("averageVolume"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "float_shares": info.get("floatShares"),
                "insider_pct": info.get("heldPercentInsiders"),
                "institution_pct": info.get("heldPercentInstitutions"),
                "short_ratio": info.get("shortRatio"),
                "target_price": info.get("targetMeanPrice"),
                "analyst_rating": info.get("recommendationKey"),
                "num_analysts": info.get("numberOfAnalystOpinions"),
            }
        except Exception as e:
            logger.warning(f"关键指标获取失败 {symbol}: {e}")
            return {"company_name": symbol, "error": str(e)}

    def fetch_news(self, symbol: str, max_items: int = 20) -> list[dict]:
        """获取个股新闻"""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            news = ticker.news or []
            results = []
            for item in news[:max_items]:
                content = item.get("content", {})
                results.append({
                    "title": content.get("title", item.get("title", "")),
                    "publisher": content.get("provider", {}).get("displayName", ""),
                    "link": content.get("canonicalUrl", {}).get("url", item.get("link", "")),
                    "published": content.get("pubDate", ""),
                    "summary": content.get("summary", ""),
                })
            return results
        except Exception as e:
            logger.warning(f"新闻获取失败 {symbol}: {e}")
            return []

    # ==================================================================
    # FMP 数据源实现
    # ==================================================================
    def _fetch_fmp_price(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        """FMP 历史价格数据"""
        start = self._period_to_start(period)
        data = self._fmp_get(
            f"historical-price-full/{symbol}",
            {"from": start.strftime("%Y-%m-%d")},
        )
        if not data or "historical" not in data:
            return None
        try:
            df = pd.DataFrame(data["historical"])
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            df = df.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
            df = df[["Open", "High", "Low", "Close", "Volume"]]
            df = df.sort_index()
            logger.info(f"FMP 价格数据获取成功: {symbol} ({len(df)} 条)")
            return df
        except Exception as e:
            logger.warning(f"FMP 价格解析失败 {symbol}: {e}")
            return None

    def _fetch_fmp_financials(self, symbol: str) -> dict:
        """FMP 财务报表 (利润表、资产负债表、现金流)"""
        cached = self._get_json_cached(symbol, "fmp_financials")
        if cached:
            logger.info(f"FMP 财报 (缓存): {symbol}")
            return cached

        result = {}
        endpoints = {
            "income_statement": f"income-statement/{symbol}",
            "balance_sheet": f"balance-sheet-statement/{symbol}",
            "cash_flow": f"cash-flow-statement/{symbol}",
            "quarterly_income": f"income-statement/{symbol}",
            "quarterly_balance": f"balance-sheet-statement/{symbol}",
            "quarterly_cashflow": f"cash-flow-statement/{symbol}",
        }
        quarterly_keys = {"quarterly_income", "quarterly_balance", "quarterly_cashflow"}

        for key, endpoint in endpoints.items():
            params = {"limit": 8}
            if key in quarterly_keys:
                params["period"] = "quarter"
            data = self._fmp_get(endpoint, params)
            if data and isinstance(data, list):
                result[key] = self._fmp_statements_to_dict(data)

        if any(v for v in result.values() if v):
            logger.info(f"FMP 财报获取成功: {symbol}")
            self._set_json_cache(symbol, "fmp_financials", result)
        return result

    def _fetch_fmp_key_metrics(self, symbol: str) -> dict:
        """FMP 公司概要 + 关键指标"""
        cached = self._get_json_cached(symbol, "fmp_metrics")
        if cached:
            logger.info(f"FMP 指标 (缓存): {symbol}")
            return cached

        # 1. 公司 profile
        profile_data = self._fmp_get(f"profile/{symbol}")
        if not profile_data or not isinstance(profile_data, list) or len(profile_data) == 0:
            return {"company_name": symbol, "error": "FMP profile not found"}
        p = profile_data[0]

        # 2. key-metrics-ttm
        km_data = self._fmp_get(f"key-metrics-ttm/{symbol}")
        km = km_data[0] if km_data and isinstance(km_data, list) and len(km_data) > 0 else {}

        # 3. ratios-ttm
        ratios_data = self._fmp_get(f"ratios-ttm/{symbol}")
        r = ratios_data[0] if ratios_data and isinstance(ratios_data, list) and len(ratios_data) > 0 else {}

        # 4. analyst estimates (如有)
        est_data = self._fmp_get(f"analyst-estimates/{symbol}", {"limit": 1})
        est = est_data[0] if est_data and isinstance(est_data, list) and len(est_data) > 0 else {}

        result = {
            "company_name": p.get("companyName", symbol),
            "sector": p.get("sector", "Unknown"),
            "industry": p.get("industry", "Unknown"),
            "market_cap": p.get("mktCap"),
            "enterprise_value": km.get("enterpriseValueTTM"),
            "pe_ratio": r.get("peRatioTTM"),
            "forward_pe": km.get("peRatioTTM"),  # FMP TTM as proxy
            "peg_ratio": r.get("pegRatioTTM"),
            "pb_ratio": r.get("priceToBookRatioTTM"),
            "ps_ratio": r.get("priceToSalesRatioTTM"),
            "ev_ebitda": km.get("enterpriseValueOverEBITDATTM"),
            "ev_revenue": r.get("enterpriseValueMultipleTTM"),
            "profit_margin": r.get("netProfitMarginTTM"),
            "operating_margin": r.get("operatingProfitMarginTTM"),
            "gross_margin": r.get("grossProfitMarginTTM"),
            "roe": r.get("returnOnEquityTTM"),
            "roa": r.get("returnOnAssetsTTM"),
            "revenue_growth": km.get("revenuePerShareTTM"),  # 需要后续计算
            "earnings_growth": None,
            "revenue": km.get("revenuePerShareTTM"),
            "net_income": km.get("netIncomePerShareTTM"),
            "total_debt": km.get("totalDebtToCapitalizationTTM"),
            "total_cash": km.get("cashPerShareTTM"),
            "debt_to_equity": r.get("debtEquityRatioTTM"),
            "current_ratio": r.get("currentRatioTTM"),
            "free_cash_flow": km.get("freeCashFlowPerShareTTM"),
            "operating_cash_flow": km.get("operatingCashFlowPerShareTTM"),
            "dividend_yield": r.get("dividendYielTTM"),  # FMP typo in their API
            "beta": p.get("beta"),
            "52w_high": p.get("range", "").split("-")[-1].strip() if p.get("range") else None,
            "52w_low": p.get("range", "").split("-")[0].strip() if p.get("range") else None,
            "50d_avg": p.get("price"),  # proxy
            "200d_avg": None,
            "avg_volume": p.get("volAvg"),
            "shares_outstanding": km.get("marketCapTTM") / p.get("price", 1) if p.get("price") else None,
            "float_shares": None,
            "insider_pct": None,
            "institution_pct": None,
            "short_ratio": None,
            "target_price": p.get("dcf"),
            "analyst_rating": None,
            "num_analysts": est.get("numberAnalystEstimatedRevenue"),
        }

        # FMP 返回 margin/ratio 已经是小数 (0.xx)，与 yfinance 一致
        # 尝试从 income-statement 计算增长率
        try:
            income = self._fmp_get(f"income-statement/{symbol}", {"limit": 2})
            if income and len(income) >= 2:
                rev_new = income[0].get("revenue", 0)
                rev_old = income[1].get("revenue", 1)
                if rev_old and rev_old != 0:
                    result["revenue_growth"] = (rev_new - rev_old) / abs(rev_old)
                result["revenue"] = rev_new
                result["net_income"] = income[0].get("netIncome")

                ni_new = income[0].get("netIncome", 0)
                ni_old = income[1].get("netIncome", 1)
                if ni_old and ni_old != 0:
                    result["earnings_growth"] = (ni_new - ni_old) / abs(ni_old)
        except Exception:
            pass

        # 清理 52w high/low 为 float
        for key in ("52w_high", "52w_low"):
            if isinstance(result[key], str):
                try:
                    result[key] = float(result[key])
                except (ValueError, TypeError):
                    result[key] = None

        self._set_json_cache(symbol, "fmp_metrics", result)
        logger.info(f"FMP 指标获取成功: {symbol}")
        return result

    @staticmethod
    def _fmp_statements_to_dict(records: list) -> dict:
        """将 FMP 报表记录列表转为 {date: {item: value}} 格式"""
        result = {}
        skip_keys = {"date", "symbol", "reportedCurrency", "cik", "fillingDate",
                      "acceptedDate", "calendarYear", "period", "link", "finalLink"}
        for record in records[:4]:  # 最近4期
            date_key = record.get("date", "unknown")
            items = {}
            for k, v in record.items():
                if k not in skip_keys and v is not None:
                    # 转换 camelCase 为可读名
                    items[k] = float(v) if isinstance(v, (int, float)) else v
            if items:
                result[date_key] = items
        return result

    # ==================================================================
    # 技术指标
    # ==================================================================
    def compute_technical_indicators(self, df: pd.DataFrame) -> dict:
        """计算常用技术指标"""
        if df is None or df.empty:
            return {}

        try:
            indicators = {}

            close = df["Close"]
            high = df["High"]
            low = df["Low"]

            # 移动均线
            indicators["sma_20"] = round(close.rolling(20).mean().iloc[-1], 2)
            indicators["sma_50"] = round(close.rolling(50).mean().iloc[-1], 2)
            indicators["sma_200"] = round(close.rolling(200).mean().iloc[-1], 2) if len(df) >= 200 else None

            # RSI (Wilder smoothing)
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = (-delta.clip(upper=0))
            avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
            avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
            rs = avg_gain / avg_loss.replace(0, float('nan'))
            rsi = 100 - (100 / (1 + rs))
            indicators["rsi_14"] = round(rsi.iloc[-1], 2) if not pd.isna(rsi.iloc[-1]) else None

            # MACD (12, 26, 9)
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            macd_hist = macd_line - signal_line
            indicators["macd"] = round(macd_line.iloc[-1], 4)
            indicators["macd_signal"] = round(signal_line.iloc[-1], 4)
            indicators["macd_histogram"] = round(macd_hist.iloc[-1], 4)

            # Bollinger Bands (20, 2)
            sma20 = close.rolling(20).mean()
            std20 = close.rolling(20).std()
            indicators["bb_upper"] = round((sma20 + 2 * std20).iloc[-1], 2)
            indicators["bb_middle"] = round(sma20.iloc[-1], 2)
            indicators["bb_lower"] = round((sma20 - 2 * std20).iloc[-1], 2)

            # ATR (14)
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            indicators["atr_14"] = round(atr.iloc[-1], 4) if not pd.isna(atr.iloc[-1]) else None

            # ADX (14)
            plus_dm = high.diff().clip(lower=0)
            minus_dm = (-low.diff()).clip(lower=0)
            plus_dm[plus_dm < minus_dm] = 0
            minus_dm[minus_dm < plus_dm] = 0
            atr14 = tr.ewm(alpha=1/14, min_periods=14).mean()
            plus_di = 100 * (plus_dm.ewm(alpha=1/14, min_periods=14).mean() / atr14)
            minus_di = 100 * (minus_dm.ewm(alpha=1/14, min_periods=14).mean() / atr14)
            dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float('nan')))
            adx = dx.ewm(alpha=1/14, min_periods=14).mean()
            indicators["adx"] = round(adx.iloc[-1], 2) if not pd.isna(adx.iloc[-1]) else None

            # 价格位置
            current = df["Close"].iloc[-1]
            high_52w = df["High"].tail(252).max()
            low_52w = df["Low"].tail(252).min()
            indicators["current_price"] = round(current, 2)
            indicators["pct_from_52w_high"] = round((current / high_52w - 1) * 100, 2)
            indicators["pct_from_52w_low"] = round((current / low_52w - 1) * 100, 2)

            # 成交量
            indicators["volume_ratio"] = round(
                df["Volume"].iloc[-5:].mean() / df["Volume"].iloc[-20:].mean(), 2
            ) if df["Volume"].iloc[-20:].mean() > 0 else None

            return indicators
        except Exception as e:
            logger.warning(f"技术指标计算失败: {e}")
            return {"current_price": round(df["Close"].iloc[-1], 2)}

    # ------------------------------------------------------------------
    # 数据源实现 (yfinance / akshare / tushare / baostock)
    # ------------------------------------------------------------------
    def _fetch_yfinance(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period)
            if df is not None and not df.empty:
                logger.info(f"yfinance 数据获取成功: {symbol}")
                return df
        except Exception as e:
            logger.warning(f"yfinance 失败 {symbol}: {e}")
        return None

    def _fetch_akshare_us(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
            if df is not None and not df.empty:
                df = self._filter_by_period(df, period)
                logger.info(f"akshare US 数据获取成功: {symbol}")
                return df
        except Exception as e:
            logger.warning(f"akshare US 失败 {symbol}: {e}")
        return None

    def _fetch_akshare_hk(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            code = symbol.replace(".HK", "")
            df = ak.stock_hk_daily(symbol=code, adjust="qfq")
            if df is not None and not df.empty:
                df = self._filter_by_period(df, period)
                logger.info(f"akshare HK 数据获取成功: {symbol}")
                return df
        except Exception as e:
            logger.warning(f"akshare HK 失败 {symbol}: {e}")
        return None

    def _fetch_akshare_cn(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            code = symbol.replace(".SH", "").replace(".SZ", "")
            df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
            if df is not None and not df.empty:
                df = self._filter_by_period(df, period)
                logger.info(f"akshare CN 数据获取成功: {symbol}")
                return df
        except Exception as e:
            logger.warning(f"akshare CN 失败 {symbol}: {e}")
        return None

    def _fetch_tushare(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            return None
        try:
            import tushare as ts
            pro = ts.pro_api(token)
            ts_code = symbol.replace(".SH", ".SH").replace(".SZ", ".SZ")
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = self._period_to_start(period).strftime("%Y%m%d")
            df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                logger.info(f"tushare 数据获取成功: {symbol}")
                return df
        except Exception as e:
            logger.warning(f"tushare 失败 {symbol}: {e}")
        return None

    def _fetch_baostock(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        try:
            import baostock as bs
            bs.login()
            code = symbol.replace(".SH", ".sh").replace(".SZ", ".sz")
            start = self._period_to_start(period).strftime("%Y-%m-%d")
            rs = bs.query_history_k_data_plus(
                code, "date,open,high,low,close,volume",
                start_date=start, frequency="d", adjustflag="2",
            )
            data_list = []
            while rs.error_code == "0" and rs.next():
                data_list.append(rs.get_row_data())
            bs.logout()
            if data_list:
                df = pd.DataFrame(data_list, columns=rs.fields)
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df["date"] = pd.to_datetime(df["date"])
                df.set_index("date", inplace=True)
                logger.info(f"baostock 数据获取成功: {symbol}")
                return df
        except Exception as e:
            logger.warning(f"baostock 失败 {symbol}: {e}")
        return None

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        col_map = {}
        for col in df.columns:
            cl = col.lower()
            if cl in ("open", "开盘"):
                col_map[col] = "Open"
            elif cl in ("high", "最高"):
                col_map[col] = "High"
            elif cl in ("low", "最低"):
                col_map[col] = "Low"
            elif cl in ("close", "收盘"):
                col_map[col] = "Close"
            elif cl in ("volume", "成交量"):
                col_map[col] = "Volume"
        if col_map:
            df = df.rename(columns=col_map)

        for c in ["Open", "High", "Low", "Close", "Volume"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        if not isinstance(df.index, pd.DatetimeIndex):
            for col_name in ["date", "日期", "trade_date"]:
                if col_name in df.columns:
                    df[col_name] = pd.to_datetime(df[col_name])
                    df.set_index(col_name, inplace=True)
                    break

        return df.sort_index()

    @staticmethod
    def _period_to_start(period: str) -> datetime:
        mapping = {
            "1mo": 30, "3mo": 90, "6mo": 180,
            "1y": 365, "2y": 730, "5y": 1825,
        }
        days = mapping.get(period, 365)
        return datetime.now() - timedelta(days=days)

    def _filter_by_period(self, df: pd.DataFrame, period: str) -> pd.DataFrame:
        start = self._period_to_start(period)
        if not isinstance(df.index, pd.DatetimeIndex):
            for col_name in ["date", "日期", "trade_date"]:
                if col_name in df.columns:
                    df[col_name] = pd.to_datetime(df[col_name])
                    df.set_index(col_name, inplace=True)
                    break
        if isinstance(df.index, pd.DatetimeIndex):
            df = df[df.index >= start]
        return df

    @staticmethod
    def _df_to_dict(df: Optional[pd.DataFrame]) -> Optional[dict]:
        if df is None or df.empty:
            return None
        result = {}
        for col in df.columns:
            col_key = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
            result[col_key] = {}
            for idx in df.index:
                val = df.loc[idx, col]
                if pd.notna(val):
                    result[col_key][str(idx)] = float(val)
        return result
