"""
行业分析模块 - 竞品识别、产业链映射、行业数据收集
"""

import logging
from typing import Optional

import yaml

from src.data.fetcher import DataFetcher

logger = logging.getLogger(__name__)


class IndustryAnalyzer:
    """行业/竞品/产业链分析器"""

    def __init__(self, config_path: str = "config/config.yaml",
                 web_search_fetcher=None):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.industry_mapping = self.config.get("industry_mapping", {})
        self.fetcher = DataFetcher(
            cache_hours=self.config.get("data", {}).get("cache_hours", 6),
            web_search_fetcher=web_search_fetcher,
        )

    def find_industry(self, symbol: str) -> Optional[dict]:
        """查找个股所属行业，返回行业信息"""
        for industry_key, industry_info in self.industry_mapping.items():
            if symbol in industry_info.get("symbols", []):
                return {
                    "key": industry_key,
                    "name": industry_info["name"],
                    "symbols": industry_info["symbols"],
                    "upstream": industry_info.get("upstream", []),
                    "downstream": industry_info.get("downstream", []),
                }
        # 尝试通过 yfinance 获取行业信息
        metrics = self.fetcher.fetch_key_metrics(symbol)
        if metrics.get("sector"):
            return {
                "key": "auto_detected",
                "name": f"{metrics.get('sector', '')} - {metrics.get('industry', '')}",
                "symbols": [symbol],
                "upstream": [],
                "downstream": [],
            }
        return None

    def get_competitors(self, symbol: str, max_count: int = 5) -> list[str]:
        """获取竞品列表"""
        industry = self.find_industry(symbol)
        if not industry:
            return []
        competitors = [s for s in industry["symbols"] if s != symbol]
        return competitors[:max_count]

    def get_supply_chain(self, symbol: str) -> dict:
        """获取产业链上下游公司"""
        industry = self.find_industry(symbol)
        if not industry:
            return {"upstream": [], "downstream": []}
        return {
            "upstream": industry.get("upstream", []),
            "downstream": industry.get("downstream", []),
        }

    def fetch_competitor_metrics(self, symbol: str, max_count: int = 5) -> list[dict]:
        """获取竞品的关键财务指标用于对比"""
        competitors = self.get_competitors(symbol, max_count)
        results = []
        for comp in competitors:
            metrics = self.fetcher.fetch_key_metrics(comp)
            if metrics and not metrics.get("error"):
                metrics["symbol"] = comp
                results.append(metrics)
            else:
                logger.warning(f"竞品指标获取失败: {comp}")
        return results

    def fetch_supply_chain_metrics(self, symbol: str) -> dict:
        """获取产业链上下游公司的关键指标"""
        chain = self.get_supply_chain(symbol)
        result = {"upstream": [], "downstream": []}

        for direction in ["upstream", "downstream"]:
            for comp in chain[direction][:3]:  # 每个方向最多3家
                metrics = self.fetcher.fetch_key_metrics(comp)
                if metrics and not metrics.get("error"):
                    metrics["symbol"] = comp
                    result[direction].append(metrics)
        return result

    def build_competitive_comparison(self, symbol: str) -> dict:
        """构建完整的竞争对比数据包"""
        target_metrics = self.fetcher.fetch_key_metrics(symbol)
        competitor_metrics = self.fetch_competitor_metrics(symbol)
        supply_chain = self.fetch_supply_chain_metrics(symbol)
        industry = self.find_industry(symbol)

        # 构建对比表
        comparison_fields = [
            "market_cap", "pe_ratio", "forward_pe", "peg_ratio",
            "ps_ratio", "pb_ratio", "ev_ebitda",
            "profit_margin", "operating_margin", "gross_margin",
            "roe", "roa", "revenue_growth", "earnings_growth",
            "debt_to_equity", "current_ratio", "free_cash_flow",
            "dividend_yield", "beta",
        ]

        comparison_table = []
        all_companies = [{"symbol": symbol, **target_metrics}] + competitor_metrics
        for company in all_companies:
            row = {"symbol": company.get("symbol", ""),
                   "name": company.get("company_name", "")}
            for field in comparison_fields:
                val = company.get(field)
                if val is not None:
                    row[field] = round(val, 4) if isinstance(val, float) else val
                else:
                    row[field] = None
            comparison_table.append(row)

        return {
            "target": target_metrics,
            "industry": industry,
            "comparison_table": comparison_table,
            "supply_chain_upstream": supply_chain["upstream"],
            "supply_chain_downstream": supply_chain["downstream"],
        }

    def format_comparison_text(self, comparison: dict) -> str:
        """将竞争对比数据格式化为文本，供Agent分析"""
        lines = []
        target = comparison["target"]
        industry = comparison.get("industry", {})

        lines.append(f"## 目标公司: {target.get('company_name', '')} ({target.get('sector', '')})")
        lines.append(f"所属行业: {industry.get('name', target.get('industry', 'N/A'))}")
        lines.append("")

        # 核心指标对比表
        lines.append("### 竞品核心指标对比")
        table = comparison.get("comparison_table", [])
        if table:
            header_fields = ["symbol", "name", "market_cap", "pe_ratio", "ps_ratio",
                             "revenue_growth", "profit_margin", "roe", "debt_to_equity"]
            lines.append("| " + " | ".join(header_fields) + " |")
            lines.append("| " + " | ".join(["---"] * len(header_fields)) + " |")
            for row in table:
                vals = []
                for f in header_fields:
                    v = row.get(f)
                    if v is None:
                        vals.append("N/A")
                    elif isinstance(v, float):
                        if f == "market_cap":
                            vals.append(f"${v/1e9:.1f}B")
                        elif f in ("revenue_growth", "profit_margin", "roe"):
                            vals.append(f"{v*100:.1f}%")
                        else:
                            vals.append(f"{v:.2f}")
                    else:
                        vals.append(str(v))
                lines.append("| " + " | ".join(vals) + " |")

        # 产业链信息
        upstream = comparison.get("supply_chain_upstream", [])
        downstream = comparison.get("supply_chain_downstream", [])

        if upstream:
            lines.append("")
            lines.append("### 上游供应商")
            for comp in upstream:
                name = comp.get("company_name", comp.get("symbol", ""))
                rev_growth = comp.get("revenue_growth")
                margin = comp.get("profit_margin")
                lines.append(
                    f"- {name}: 营收增速 {f'{rev_growth*100:.1f}%' if rev_growth else 'N/A'}, "
                    f"利润率 {f'{margin*100:.1f}%' if margin else 'N/A'}"
                )

        if downstream:
            lines.append("")
            lines.append("### 下游客户/渠道")
            for comp in downstream:
                name = comp.get("company_name", comp.get("symbol", ""))
                rev_growth = comp.get("revenue_growth")
                margin = comp.get("profit_margin")
                lines.append(
                    f"- {name}: 营收增速 {f'{rev_growth*100:.1f}%' if rev_growth else 'N/A'}, "
                    f"利润率 {f'{margin*100:.1f}%' if margin else 'N/A'}"
                )

        return "\n".join(lines)
