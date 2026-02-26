"""
基于网络搜索的金融数据获取模块

策略:
  1. 使用 DuckDuckGo 搜索获取多源信息 (免费，无需 API Key)
  2. 抓取关键页面 (Yahoo Finance, Macrotrends, 公司 IR, SEC EDGAR 等)
  3. 使用 LLM 从原始文本中提取结构化金融数据
  4. 多源交叉验证核心数字，标注置信度

适用场景:
  - 广为人知的上市公司 (财务数据在公开网页上广泛可查)
  - 难以获取稳定金融 API 的环境
  - 需要从官方来源 (公司 IR, SEC) 验证数据
"""

import json
import hashlib
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

WEB_CACHE_DIR = Path("data/cache/web")
WEB_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ======================================================================
# LLM Prompt Templates
# ======================================================================

KEY_METRICS_SYSTEM_PROMPT = """\
You are a financial data extraction specialist. Your job is to extract \
structured financial metrics from web search results with high accuracy.

Rules:
- Return ONLY valid JSON, no other text.
- Cross-reference numbers across multiple sources. If sources disagree, \
  use the most recent and most authoritative source (SEC filings > company IR > financial portals).
- All monetary values in USD unless the company reports in another currency.
- Percentages as decimals: 25% -> 0.25, -3.5% -> -0.035.
- If a value cannot be found or verified, use null.
- Include data_confidence and extraction_notes to flag any issues."""

KEY_METRICS_USER_TEMPLATE = """\
Extract financial metrics for {symbol} ({company_hint}) from these web sources.

{combined_text}

Return this exact JSON structure:
{{
    "company_name": "Full legal company name",
    "sector": "Sector",
    "industry": "Specific industry",
    "market_cap": null,
    "enterprise_value": null,
    "pe_ratio": null,
    "forward_pe": null,
    "peg_ratio": null,
    "pb_ratio": null,
    "ps_ratio": null,
    "ev_ebitda": null,
    "ev_revenue": null,
    "profit_margin": null,
    "operating_margin": null,
    "gross_margin": null,
    "roe": null,
    "roa": null,
    "revenue_growth": null,
    "earnings_growth": null,
    "revenue": null,
    "net_income": null,
    "total_debt": null,
    "total_cash": null,
    "debt_to_equity": null,
    "current_ratio": null,
    "free_cash_flow": null,
    "operating_cash_flow": null,
    "dividend_yield": null,
    "beta": null,
    "52w_high": null,
    "52w_low": null,
    "50d_avg": null,
    "200d_avg": null,
    "avg_volume": null,
    "shares_outstanding": null,
    "float_shares": null,
    "insider_pct": null,
    "institution_pct": null,
    "short_ratio": null,
    "target_price": null,
    "analyst_rating": null,
    "num_analysts": null,
    "data_sources": ["list of source names/domains used"],
    "data_confidence": "high/medium/low",
    "extraction_notes": "any discrepancies or issues found"
}}"""

FINANCIALS_SYSTEM_PROMPT = """\
You are a financial statement extraction specialist. Extract income statement, \
balance sheet, and cash flow data from web sources.

Rules:
- Return ONLY valid JSON, no other text.
- Use the most recent 2-4 reporting periods.
- All monetary values in the company's reporting currency (state which).
- Include both annual and quarterly data if available.
- Cross-reference across sources for accuracy."""

FINANCIALS_USER_TEMPLATE = """\
Extract financial statements for {symbol} ({company_hint}) from these sources.

{combined_text}

Return this JSON structure:
{{
    "income_statement": {{
        "<period e.g. 2024-12-31>": {{
            "revenue": null,
            "costOfRevenue": null,
            "grossProfit": null,
            "operatingExpenses": null,
            "operatingIncome": null,
            "netIncome": null,
            "eps": null,
            "ebitda": null,
            "researchAndDevelopment": null
        }}
    }},
    "balance_sheet": {{
        "<period>": {{
            "totalAssets": null,
            "totalLiabilities": null,
            "totalEquity": null,
            "cash": null,
            "totalDebt": null,
            "currentAssets": null,
            "currentLiabilities": null,
            "goodwill": null,
            "intangibleAssets": null
        }}
    }},
    "cash_flow": {{
        "<period>": {{
            "operatingCashFlow": null,
            "capitalExpenditure": null,
            "freeCashFlow": null,
            "investingCashFlow": null,
            "financingCashFlow": null,
            "stockBasedCompensation": null
        }}
    }},
    "quarterly_income": {{
        "<quarter e.g. 2024-Q4>": {{
            "revenue": null,
            "netIncome": null,
            "eps": null
        }}
    }},
    "currency": "USD or CNY or other",
    "fiscal_year_end": "month name, e.g. December",
    "data_sources": ["sources"],
    "data_confidence": "high/medium/low",
    "notes": "any discrepancies or important context"
}}"""

IR_VERIFICATION_SYSTEM_PROMPT = """\
You are verifying financial data by cross-referencing with official \
Investor Relations content. Compare the provided data against the IR page \
content and flag any discrepancies.

Return ONLY valid JSON."""

IR_VERIFICATION_USER_TEMPLATE = """\
We have the following extracted financial data for {symbol}:

{existing_data}

Now verify and supplement this data using the official IR page content:

{ir_content}

Return:
{{
    "verified_fields": ["list of fields that match IR data"],
    "corrected_fields": {{
        "<field_name>": {{
            "old_value": "...",
            "new_value": "...",
            "source": "IR page URL or description"
        }}
    }},
    "additional_data": {{
        "<new_field>": "value from IR page not in original data"
    }},
    "verification_confidence": "high/medium/low",
    "notes": "any important observations"
}}"""


class WebSearchFetcher:
    """基于网络搜索 + LLM 提取的金融数据获取器

    工作流:
      1. 构造多个针对性搜索查询
      2. 抓取搜索结果 + 排名靠前的页面内容
      3. 将所有信息喂给 LLM 提取结构化数据
      4. 搜索公司 IR 页面进行交叉验证
      5. 返回验证后的结构化数据
    """

    def __init__(
        self,
        llm_client=None,
        data_model: str = "",
        cache_hours: int = 6,
    ):
        """
        Args:
            llm_client: LLMClient 实例 (用于数据提取)
            data_model: LLM 模型名 (建议用 Haiku 级别，快速便宜)
            cache_hours: 缓存时效 (小时)
        """
        self.llm = llm_client
        self.data_model = data_model
        self.cache_hours = cache_hours
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    # ==================================================================
    # 底层: 搜索
    # ==================================================================
    def _web_search(self, query: str, max_results: int = 8) -> list[dict]:
        """DuckDuckGo 文本搜索"""
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })
            logger.debug(f"搜索 '{query}' → {len(results)} 条结果")
            return results
        except ImportError:
            logger.error("需要安装 duckduckgo-search: pip install duckduckgo-search")
            return []
        except Exception as e:
            logger.warning(f"搜索失败 '{query[:50]}': {e}")
            return []

    # ==================================================================
    # 底层: 页面抓取
    # ==================================================================
    def _fetch_page_text(self, url: str, max_chars: int = 15000) -> str:
        """获取网页内容并转为纯文本"""
        try:
            resp = self._session.get(url, timeout=15, allow_redirects=True)
            resp.raise_for_status()
            html = resp.text

            # 优先使用 html2text (质量最好)
            try:
                import html2text
                h = html2text.HTML2Text()
                h.ignore_links = True
                h.ignore_images = True
                h.body_width = 0
                text = h.handle(html)
            except ImportError:
                # 降级到 BeautifulSoup
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, "html.parser")
                    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                        tag.decompose()
                    text = soup.get_text(separator="\n", strip=True)
                except ImportError:
                    # 最后手段: 正则去标签
                    text = re.sub(r"<[^>]+>", " ", html)
                    text = re.sub(r"\s+", " ", text)

            # 去除连续空行
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text[:max_chars]
        except Exception as e:
            logger.debug(f"页面获取失败 {url}: {e}")
            return ""

    # ==================================================================
    # 底层: LLM 提取
    # ==================================================================
    def _llm_extract(self, system_prompt: str, user_content: str) -> Optional[dict]:
        """用 LLM 从文本中提取结构化 JSON"""
        if not self.llm:
            logger.warning("WebSearchFetcher: 未配置 LLM 客户端，无法提取数据")
            return None

        response = self.llm.call(
            model=self.data_model,
            system=system_prompt,
            user_message=user_content,
        )

        if not response:
            return None

        # 解析 JSON
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # 从 markdown 代码块中提取
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 提取第一个 JSON 对象
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(f"LLM 返回无法解析为 JSON: {response[:300]}")
        return None

    # ==================================================================
    # 底层: 缓存
    # ==================================================================
    def _cache_path(self, key: str) -> Path:
        h = hashlib.md5(key.encode()).hexdigest()[:12]
        return WEB_CACHE_DIR / f"{h}.json"

    def _get_cached(self, key: str):
        path = self._cache_path(key)
        if path.exists():
            age = datetime.now().timestamp() - path.stat().st_mtime
            if age < self.cache_hours * 3600:
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return None

    def _set_cache(self, key: str, data):
        try:
            path = self._cache_path(key)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Web 缓存写入失败: {e}")

    # ==================================================================
    # 搜索 + 抓取内容整合
    # ==================================================================
    def _search_and_collect(
        self,
        queries: list[str],
        max_results_per_query: int = 5,
        max_pages_per_query: int = 2,
        max_page_chars: int = 5000,
        preferred_domains: list[str] = None,
    ) -> str:
        """执行多个搜索查询，抓取排名靠前的页面，返回合并文本"""
        all_snippets = []
        page_texts = []
        seen_urls = set()

        for query in queries:
            results = self._web_search(query, max_results=max_results_per_query)

            for r in results:
                all_snippets.append(f"[{r['title']}] {r['snippet']}")

            # 按优先域名排序
            if preferred_domains:
                def domain_priority(r):
                    url = r.get("url", "").lower()
                    for i, d in enumerate(preferred_domains):
                        if d in url:
                            return i
                    return len(preferred_domains)
                results.sort(key=domain_priority)

            # 抓取排名靠前的页面
            pages_fetched = 0
            for r in results:
                if pages_fetched >= max_pages_per_query:
                    break
                url = r.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                text = self._fetch_page_text(url, max_chars=max_page_chars)
                if text and len(text) > 200:
                    domain = self._extract_domain(url)
                    page_texts.append(
                        f"=== Source: {r['title']} ({domain}) ===\n{text}"
                    )
                    pages_fetched += 1

            time.sleep(0.5)  # 搜索频率控制

        # 合并
        combined = "## Search Result Snippets:\n" + "\n".join(all_snippets[:25])
        if page_texts:
            combined += "\n\n## Detailed Page Content:\n\n" + "\n\n".join(page_texts[:6])

        # 限制总长度 (留 buffer 给 LLM prompt 的其他部分)
        if len(combined) > 40000:
            combined = combined[:40000] + "\n... (content truncated)"

        return combined

    # ==================================================================
    # Public API: 关键财务指标
    # ==================================================================
    def fetch_key_metrics(self, symbol: str, company_name: str = "") -> dict:
        """通过网络搜索获取关键财务指标

        搜索策略:
          1. 估值指标 (PE, PB, PS, EV/EBITDA)
          2. 盈利能力 (margins, ROE, ROA)
          3. 增长数据 (revenue growth, earnings growth)
          4. 公司概况 (sector, industry, market cap)
        """
        cache_key = f"web_metrics_{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            logger.info(f"Web 指标 (缓存): {symbol}")
            return cached

        company_hint = company_name or symbol
        queries = [
            f"{symbol} stock financial data market cap PE ratio revenue 2024 2025",
            f"{symbol} {company_hint} profit margin ROE earnings growth",
            f'"{symbol}" valuation PEG ratio price-to-book EV/EBITDA',
            f"{symbol} stock analyst rating target price consensus",
        ]

        preferred = [
            "finance.yahoo.com", "macrotrends.net", "wsj.com",
            "stockanalysis.com", "simplywall.st", "gurufocus.com",
        ]

        combined_text = self._search_and_collect(
            queries, max_results_per_query=5, max_pages_per_query=2,
            max_page_chars=5000, preferred_domains=preferred,
        )

        if not combined_text or len(combined_text) < 100:
            logger.warning(f"Web 搜索未返回足够数据: {symbol}")
            return {"company_name": company_hint, "error": "web_search_no_results"}

        user_msg = KEY_METRICS_USER_TEMPLATE.format(
            symbol=symbol,
            company_hint=company_hint,
            combined_text=combined_text,
        )

        result = self._llm_extract(KEY_METRICS_SYSTEM_PROMPT, user_msg)
        if result and result.get("company_name"):
            self._set_cache(cache_key, result)
            confidence = result.get("data_confidence", "unknown")
            logger.info(f"Web 搜索指标获取成功: {symbol} (置信度: {confidence})")
            return result

        logger.warning(f"Web 搜索指标 LLM 提取失败: {symbol}")
        return {"company_name": company_hint, "error": "web_search_extraction_failed"}

    # ==================================================================
    # Public API: 财务报表
    # ==================================================================
    def fetch_financials(self, symbol: str, company_name: str = "") -> dict:
        """通过网络搜索获取财务报表数据

        搜索策略:
          1. 利润表 (income statement)
          2. 资产负债表 (balance sheet)
          3. 现金流量表 (cash flow statement)
          4. 季度数据 (quarterly results)
        """
        cache_key = f"web_financials_{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            logger.info(f"Web 财报 (缓存): {symbol}")
            return cached

        company_hint = company_name or symbol
        queries = [
            f"{symbol} income statement annual 2023 2024 revenue net income",
            f"{symbol} balance sheet total assets liabilities equity 2024",
            f"{symbol} cash flow statement operating free cash flow 2024",
            f"{symbol} {company_hint} quarterly earnings results EPS",
        ]

        preferred = [
            "macrotrends.net", "stockanalysis.com", "wsj.com",
            "finance.yahoo.com", "sec.gov", "simplywall.st",
        ]

        combined_text = self._search_and_collect(
            queries, max_results_per_query=5, max_pages_per_query=2,
            max_page_chars=6000, preferred_domains=preferred,
        )

        if not combined_text or len(combined_text) < 100:
            logger.warning(f"Web 搜索财报未返回足够数据: {symbol}")
            return {}

        user_msg = FINANCIALS_USER_TEMPLATE.format(
            symbol=symbol,
            company_hint=company_hint,
            combined_text=combined_text,
        )

        result = self._llm_extract(FINANCIALS_SYSTEM_PROMPT, user_msg)
        if result and any(
            result.get(k) for k in ("income_statement", "balance_sheet", "cash_flow")
        ):
            self._set_cache(cache_key, result)
            confidence = result.get("data_confidence", "unknown")
            logger.info(f"Web 搜索财报获取成功: {symbol} (置信度: {confidence})")
            return result

        logger.warning(f"Web 搜索财报 LLM 提取失败: {symbol}")
        return {}

    # ==================================================================
    # Public API: 新闻
    # ==================================================================
    def fetch_news(
        self, symbol: str, company_name: str = "", max_items: int = 15
    ) -> list[dict]:
        """通过网络搜索获取最近新闻"""
        queries = [
            f"{symbol} {company_name} stock news latest 2025",
            f"{company_name or symbol} earnings results analysis recent",
        ]

        all_results = []
        seen_titles = set()

        for query in queries:
            results = self._web_search(query, max_results=max_items)
            for r in results:
                title = r.get("title", "").strip()
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    all_results.append({
                        "title": title,
                        "publisher": self._extract_domain(r.get("url", "")),
                        "link": r.get("url", ""),
                        "published": "",
                        "summary": r.get("snippet", ""),
                    })
            time.sleep(0.3)

        return all_results[:max_items]

    # ==================================================================
    # Public API: Investor Relations 搜索与交叉验证
    # ==================================================================
    def search_and_verify_from_ir(
        self,
        symbol: str,
        existing_data: dict,
        company_name: str = "",
    ) -> dict:
        """搜索公司 Investor Relations 页面，与已有数据交叉验证

        Args:
            symbol: 股票代码
            existing_data: 已提取的财务数据 (将与 IR 数据对比)
            company_name: 公司名

        Returns:
            验证结果 dict，包含 verified_fields, corrected_fields, additional_data
        """
        company_hint = company_name or existing_data.get("company_name", symbol)

        # 搜索 IR 页面
        ir_queries = [
            f'"{company_hint}" investor relations financial results press release',
            f'"{company_hint}" annual report 20-F 10-K SEC filing',
            f"site:ir.{company_hint.lower().replace(' ', '')}.com OR "
            f"site:investor.{company_hint.lower().replace(' ', '')}.com",
        ]

        ir_content_parts = []
        for query in ir_queries:
            results = self._web_search(query, max_results=5)
            for r in results:
                url = r.get("url", "").lower()
                # 识别 IR / SEC 页面
                if any(kw in url for kw in (
                    "investor", "ir.", "/ir/", "annual-report", "sec.gov",
                    "edgar", "press-release", "earnings",
                )):
                    text = self._fetch_page_text(r["url"], max_chars=10000)
                    if text and len(text) > 300:
                        domain = self._extract_domain(r["url"])
                        ir_content_parts.append(
                            f"=== {r['title']} ({domain}) ===\n{text[:8000]}"
                        )
            time.sleep(0.5)

        if not ir_content_parts:
            logger.info(f"未找到 {symbol} 的 IR 页面")
            return {
                "verified_fields": [],
                "corrected_fields": {},
                "additional_data": {},
                "verification_confidence": "low",
                "notes": "No IR pages found for verification",
            }

        ir_content = "\n\n".join(ir_content_parts[:3])

        # 简化 existing_data 避免 prompt 过长
        data_summary = {
            k: v for k, v in existing_data.items()
            if k not in ("data_sources", "extraction_notes") and v is not None
        }

        user_msg = IR_VERIFICATION_USER_TEMPLATE.format(
            symbol=symbol,
            existing_data=json.dumps(data_summary, ensure_ascii=False, indent=2),
            ir_content=ir_content,
        )

        result = self._llm_extract(IR_VERIFICATION_SYSTEM_PROMPT, user_msg)
        if result:
            logger.info(
                f"IR 验证完成: {symbol}, "
                f"验证 {len(result.get('verified_fields', []))} 项, "
                f"修正 {len(result.get('corrected_fields', {}))} 项"
            )
            return result

        return {
            "verified_fields": [],
            "corrected_fields": {},
            "additional_data": {},
            "verification_confidence": "low",
            "notes": "IR verification LLM extraction failed",
        }

    def apply_verification(self, original_data: dict, verification: dict) -> dict:
        """将 IR 验证结果应用到原始数据

        修正逻辑: IR 验证结果中的 corrected_fields 会覆盖原始值，
        additional_data 会补充缺失字段。
        """
        result = dict(original_data)

        # 应用修正
        for field, correction in verification.get("corrected_fields", {}).items():
            new_val = correction.get("new_value")
            if new_val is not None and field in result:
                old_val = result[field]
                result[field] = new_val
                logger.info(f"IR 修正 {field}: {old_val} → {new_val}")

        # 补充缺失数据
        for field, value in verification.get("additional_data", {}).items():
            if value is not None and (field not in result or result.get(field) is None):
                result[field] = value
                logger.info(f"IR 补充 {field}: {value}")

        # 更新置信度标注
        verified = verification.get("verified_fields", [])
        if verified:
            notes = result.get("extraction_notes", "")
            result["extraction_notes"] = (
                f"{notes} | IR verified: {', '.join(verified[:5])}"
            ).strip(" |")

        ir_confidence = verification.get("verification_confidence", "")
        if ir_confidence == "high":
            result["data_confidence"] = "high"

        return result

    # ==================================================================
    # 完整流程: 获取 + 验证
    # ==================================================================
    def fetch_verified_key_metrics(
        self, symbol: str, company_name: str = ""
    ) -> dict:
        """完整流程: 搜索关键指标 → IR 交叉验证 → 返回验证后数据"""
        # Step 1: 搜索提取
        metrics = self.fetch_key_metrics(symbol, company_name)
        if metrics.get("error"):
            return metrics

        # Step 2: IR 验证
        verification = self.search_and_verify_from_ir(
            symbol, metrics, company_name or metrics.get("company_name", "")
        )

        # Step 3: 应用验证
        verified = self.apply_verification(metrics, verification)
        verified["_ir_verification"] = {
            "verified_count": len(verification.get("verified_fields", [])),
            "corrected_count": len(verification.get("corrected_fields", {})),
            "ir_confidence": verification.get("verification_confidence", "unknown"),
        }

        return verified

    # ==================================================================
    # 工具
    # ==================================================================
    @staticmethod
    def _extract_domain(url: str) -> str:
        """从 URL 提取域名"""
        try:
            return urlparse(url).netloc.replace("www.", "")
        except Exception:
            return url[:50]
