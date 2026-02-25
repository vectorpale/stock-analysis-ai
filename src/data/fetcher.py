"""
数据获取模块 - 多源行情与财务数据
支持美股、港股、A股，带缓存和降级策略
"""

import os
import logging
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class DataFetcher:
    """多源股票数据获取器"""

    def __init__(self, cache_hours: int = 6):
        self.cache_hours = cache_hours

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
    # 缓存
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

    # ------------------------------------------------------------------
    # 技术指标
    # ------------------------------------------------------------------
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
    # 数据源实现
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
