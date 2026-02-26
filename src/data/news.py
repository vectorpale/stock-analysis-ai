"""
新闻与业绩会数据收集模块
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class NewsCollector:
    """新闻、业绩会纪要、行业资讯收集器"""

    def __init__(self, web_search_fetcher=None):
        self.news_api_key = os.environ.get("NEWS_API_KEY")
        self._web_search = web_search_fetcher

    def collect_all_news(
        self, symbol: str, company_name: str = "", industry: str = "", max_items: int = 20
    ) -> dict:
        """收集全部新闻资料"""
        result = {
            "company_news": [],
            "industry_news": [],
            "earnings_info": {},
        }

        # 1. 公司新闻 (yfinance)
        result["company_news"] = self._fetch_yfinance_news(symbol, max_items)

        # 1b. Web 搜索补充新闻 (如 yfinance 为空)
        if not result["company_news"] and self._web_search:
            logger.info(f"yfinance 新闻为空，尝试 Web 搜索: {symbol}")
            result["company_news"] = self._web_search.fetch_news(
                symbol, company_name, max_items
            )

        # 2. 业绩日历/预期
        result["earnings_info"] = self._fetch_earnings_info(symbol)

        # 3. 行业新闻 (如有 NewsAPI key)
        if self.news_api_key and (company_name or industry):
            industry_news = self._fetch_newsapi(company_name or industry, max_items // 2)
            result["industry_news"] = industry_news
        # 3b. Web 搜索行业新闻 (如无 NewsAPI key)
        elif self._web_search and (company_name or industry):
            result["industry_news"] = self._web_search.fetch_news(
                "", company_name=industry or company_name, max_items=max_items // 2
            )

        return result

    def _fetch_yfinance_news(self, symbol: str, max_items: int = 20) -> list[dict]:
        """通过 yfinance 获取公司新闻"""
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
            logger.warning(f"yfinance 新闻获取失败 {symbol}: {e}")
            return []

    def _fetch_earnings_info(self, symbol: str) -> dict:
        """获取业绩相关信息: 下次财报日、分析师预期等"""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            result = {
                "earnings_date": None,
                "revenue_estimate": info.get("revenueEstimate"),
                "earnings_estimate": info.get("earningsEstimate"),
                "analyst_target_price": info.get("targetMeanPrice"),
                "analyst_target_high": info.get("targetHighPrice"),
                "analyst_target_low": info.get("targetLowPrice"),
                "recommendation": info.get("recommendationKey"),
                "num_analysts": info.get("numberOfAnalystOpinions"),
            }

            # 尝试获取下次财报日
            try:
                cal = ticker.calendar
                if cal is not None:
                    if isinstance(cal, dict):
                        earnings = cal.get("Earnings Date", [])
                        if earnings:
                            result["earnings_date"] = str(earnings[0])
            except Exception:
                pass

            return result
        except Exception as e:
            logger.warning(f"业绩信息获取失败 {symbol}: {e}")
            return {}

    def _fetch_newsapi(self, query: str, max_items: int = 10) -> list[dict]:
        """通过 NewsAPI 获取新闻"""
        if not self.news_api_key:
            return []
        try:
            import requests
            from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": query,
                "from": from_date,
                "sortBy": "relevancy",
                "pageSize": max_items,
                "apiKey": self.news_api_key,
                "language": "en",
            }
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                articles = resp.json().get("articles", [])
                return [
                    {
                        "title": a.get("title", ""),
                        "publisher": a.get("source", {}).get("name", ""),
                        "link": a.get("url", ""),
                        "published": a.get("publishedAt", ""),
                        "summary": a.get("description", ""),
                    }
                    for a in articles
                ]
        except Exception as e:
            logger.warning(f"NewsAPI 获取失败: {e}")
        return []

    def format_news_text(self, news_data: dict) -> str:
        """格式化新闻数据为文本"""
        lines = []

        # 公司新闻
        company_news = news_data.get("company_news", [])
        if company_news:
            lines.append("### 公司近期新闻")
            for i, n in enumerate(company_news[:10], 1):
                lines.append(f"{i}. [{n['published'][:10] if n['published'] else 'N/A'}] "
                             f"**{n['title']}** ({n['publisher']})")
                if n.get("summary"):
                    lines.append(f"   摘要: {n['summary'][:200]}")

        # 行业新闻
        industry_news = news_data.get("industry_news", [])
        if industry_news:
            lines.append("")
            lines.append("### 行业近期新闻")
            for i, n in enumerate(industry_news[:5], 1):
                lines.append(f"{i}. [{n['published'][:10] if n['published'] else 'N/A'}] "
                             f"**{n['title']}** ({n['publisher']})")

        # 业绩信息
        earnings = news_data.get("earnings_info", {})
        if earnings and any(v is not None for v in earnings.values()):
            lines.append("")
            lines.append("### 业绩/分析师预期")
            if earnings.get("earnings_date"):
                lines.append(f"- 下次财报日: {earnings['earnings_date']}")
            if earnings.get("analyst_target_price"):
                lines.append(
                    f"- 分析师目标价: ${earnings['analyst_target_price']:.2f} "
                    f"(区间: ${earnings.get('analyst_target_low', 'N/A')} - "
                    f"${earnings.get('analyst_target_high', 'N/A')})"
                )
            if earnings.get("recommendation"):
                lines.append(f"- 综合评级: {earnings['recommendation']} "
                             f"({earnings.get('num_analysts', 'N/A')} 位分析师)")

        return "\n".join(lines) if lines else "暂无新闻数据"
