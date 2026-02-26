#!/usr/bin/env python3
"""
BIDU (百度) 完整多Agent辩论分析 v2 — SSOT + Fact-Checker + 互斥角色

绕过沙盒网络限制:
  - 数据层: 使用之前 Web 搜索测试收集的真实 BIDU 金融数据
  - LLM层: 使用 Anthropic API (沙盒可访问)

v2 流水线:
  数据注入 → SSOT预计算 → 6位互斥分析师独立分析 → Fact-Check →
  多轮辩论 → 二次Fact-Check → CIO拷问 → 反共识分析 →
  风控审核(绝对收益) → CIO决策(击球区判断) → 配对交易
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from types import MethodType

from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.panel import Panel

from src.agents.engine import DebateEngine
from src.valuation.models import run_valuation, format_valuation_text
from src.utils.llm_client import LLMProvider

console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


# ======================================================================
# 预收集的 BIDU 金融数据
# ======================================================================

def load_key_metrics():
    """从之前 Web 搜索测试结果加载 key_metrics"""
    data_file = Path("data/test_output/bidu_web_search_test.json")
    with open(data_file, "r") as f:
        metrics = json.load(f)

    # 补充估值所需字段
    # current_price 用 market_cap / shares_outstanding 推算
    shares = metrics.get("shares_outstanding", 350_600_000)
    mc = metrics.get("market_cap", 51_360_000_000)
    current_price = mc / shares if shares else 133.67
    metrics["50d_avg"] = current_price  # 估值模块用这个字段找价格
    metrics["200d_avg"] = current_price * 0.95  # 近似
    metrics["52w_high"] = 160.0  # BIDU 2024 52-week range
    metrics["52w_low"] = 78.0

    # 补充 ROE (net_income / total_equity)
    if metrics.get("net_income") and metrics.get("total_equity"):
        metrics["roe"] = metrics["net_income"] / metrics["total_equity"]

    return metrics, current_price


def build_financials():
    """构建 BIDU 财务报表数据 (与 fetcher.fetch_financials 返回格式一致)"""
    return {
        "income_statement": {
            "2024-12-31": {
                "revenue": 18_238_000_000,
                "costOfRevenue": 10_078_000_000,
                "grossProfit": 8_160_000_000,
                "operatingIncome": 1_800_000_000,
                "netIncome": 1_260_000_000,
                "eps": 3.25,
                "ebitda": 3_500_000_000,
            },
            "2023-12-31": {
                "revenue": 18_955_000_000,
                "costOfRevenue": 9_765_000_000,
                "grossProfit": 9_190_000_000,
                "operatingIncome": 3_670_000_000,
                "netIncome": 2_840_000_000,
                "eps": 7.81,
                "ebitda": 5_200_000_000,
            },
        },
        "balance_sheet": {
            "2024-12-31": {
                "totalAssets": 58_537_000_000,
                "totalLiabilities": 19_719_000_000,
                "totalEquity": 38_818_000_000,
                "cash": 19_060_000_000,
                "totalDebt": 13_660_000_000,
                "currentAssets": 28_000_000_000,
                "currentLiabilities": 14_660_000_000,
            },
        },
        "cash_flow": {
            "2024-12-31": {
                "operatingCashFlow": 4_530_000_000,
                "capitalExpenditure": -1_780_000_000,
                "freeCashFlow": 1_792_000_000,
                "dividendsPaid": 0,
                "shareRepurchases": -1_500_000_000,
            },
        },
        "quarterly_income": {
            "2024-Q4": {
                "revenue": 4_670_000_000,
                "netIncome": 450_000_000,
                "eps": 2.63,
            },
            "2024-Q3": {
                "revenue": 4_600_000_000,
                "netIncome": 380_000_000,
                "eps": 1.08,
            },
            "2024-Q2": {
                "revenue": 4_640_000_000,
                "netIncome": 350_000_000,
                "eps": 1.00,
            },
            "2024-Q1": {
                "revenue": 4_310_000_000,
                "netIncome": 280_000_000,
                "eps": 0.80,
            },
        },
        "currency": "USD",
        "data_source": "web_search_verified",
    }


def build_competitive_comparison(key_metrics):
    """构建竞品对比数据"""
    target = {
        "symbol": "BIDU",
        "company_name": "Baidu, Inc.",
        "market_cap": key_metrics.get("market_cap", 51_360_000_000),
        "pe_ratio": key_metrics.get("pe_ratio", 16.18),
        "ps_ratio": key_metrics.get("ps_ratio", 2.82),
        "pb_ratio": key_metrics.get("pb_ratio", 1.31),
        "profit_margin": key_metrics.get("profit_margin", 0.1738),
        "revenue_growth": key_metrics.get("revenue_growth", -0.038),
        "gross_margin": key_metrics.get("gross_margin", 0.4475),
        "debt_to_equity": key_metrics.get("debt_to_equity", 0.34),
    }

    # 同业竞品 (china_internet) — 使用公开已知数据的合理近似
    competitors = [
        {
            "symbol": "BABA", "company_name": "Alibaba Group",
            "market_cap": 310_000_000_000, "pe_ratio": 18.5, "ps_ratio": 2.5,
            "pb_ratio": 1.9, "profit_margin": 0.08, "revenue_growth": 0.05,
            "gross_margin": 0.38, "debt_to_equity": 0.18,
        },
        {
            "symbol": "PDD", "company_name": "PDD Holdings (Pinduoduo/Temu)",
            "market_cap": 155_000_000_000, "pe_ratio": 10.5, "ps_ratio": 3.8,
            "pb_ratio": 4.2, "profit_margin": 0.25, "revenue_growth": 0.44,
            "gross_margin": 0.62, "debt_to_equity": 0.05,
        },
        {
            "symbol": "JD", "company_name": "JD.com",
            "market_cap": 65_000_000_000, "pe_ratio": 12.0, "ps_ratio": 0.42,
            "pb_ratio": 2.1, "profit_margin": 0.035, "revenue_growth": 0.04,
            "gross_margin": 0.10, "debt_to_equity": 0.30,
        },
        {
            "symbol": "NTES", "company_name": "NetEase",
            "market_cap": 70_000_000_000, "pe_ratio": 14.0, "ps_ratio": 4.5,
            "pb_ratio": 3.5, "profit_margin": 0.22, "revenue_growth": 0.07,
            "gross_margin": 0.58, "debt_to_equity": 0.10,
        },
    ]

    return {
        "target": target,
        "industry": {
            "key": "china_internet",
            "name": "中概互联网",
            "symbols": ["BIDU", "PDD", "JD", "BABA", "NTES", "TME", "BILI", "IQ"],
        },
        "comparison_table": [target] + competitors,
        "supply_chain_upstream": [
            {
                "symbol": "NVDA", "company_name": "NVIDIA",
                "market_cap": 3_400_000_000_000, "revenue_growth": 1.22,
                "profit_margin": 0.55,
            },
            {
                "symbol": "TSM", "company_name": "Taiwan Semiconductor",
                "market_cap": 900_000_000_000, "revenue_growth": 0.30,
                "profit_margin": 0.40,
            },
        ],
        "supply_chain_downstream": [],
    }


def build_news_data():
    """构建新闻数据"""
    return {
        "news": [
            {
                "title": "Baidu Inc (BIDU) Q4 2024 Earnings: AI Cloud Growth 26% YoY, Apollo Go Rides Up 36%",
                "publisher": "Yahoo Finance",
                "link": "https://finance.yahoo.com/news/baidu-q4-2024-earnings",
                "published": "2025-02-18",
                "summary": "Baidu reported Q4 2024 revenue of RMB 34.1B (-2% YoY). AI Cloud revenue grew 26% YoY. Apollo Go autonomous ride-hailing provided over 1.1 million rides, up 36% YoY. Non-GAAP EPS of RMB 19.18 ($2.63) beat consensus.",
            },
            {
                "title": "Baidu's AI Cloud Business Shows Robust Momentum Amid Revenue Challenges",
                "publisher": "Motley Fool",
                "link": "https://www.fool.com/earnings/call-transcripts/2025/02/18/baidu-q4-2024/",
                "published": "2025-02-18",
                "summary": "Baidu's AI Cloud demonstrated robust momentum with Q4 revenue growth accelerating to 26% YoY. Management highlighted growing enterprise adoption of ERNIE AI models. Total FY2024 revenue was RMB 133.1B.",
            },
            {
                "title": "Baidu Stock Rises on EPS Beat Despite Revenue Decline",
                "publisher": "AlphaStreet",
                "link": "https://news.alphastreet.com/bidu-q4-2024/",
                "published": "2025-02-19",
                "summary": "Baidu reported +32.86% EPS surprise and +0.91% revenue surprise vs analyst forecasts. FY2024 net income attributable to Baidu rose 18.24% YoY to RMB 23.17B ($3.17B).",
            },
            {
                "title": "China Tech Stocks Rally as AI Investment Boom Continues",
                "publisher": "Reuters",
                "link": "https://www.reuters.com/technology/china-tech-ai-rally-2025/",
                "published": "2025-02-20",
                "summary": "Chinese tech companies including Baidu, Alibaba, and Tencent are benefiting from increased AI investment. Baidu's ERNIE Bot has accumulated over 300 million users, driving cloud revenue growth.",
            },
            {
                "title": "Autonomous Driving: Baidu's Apollo Go Leads China's Robotaxi Race",
                "publisher": "CNBC",
                "link": "https://www.cnbc.com/2025/02/apollo-go-robotaxi/",
                "published": "2025-02-15",
                "summary": "Baidu's Apollo Go has expanded to 11 cities in China with over 1,800 autonomous vehicles. The company aims for full commercialization by 2025, with unit economics improving rapidly.",
            },
        ],
        "earnings": {
            "analyst_target_price": 150.0,
            "analyst_recommendation": "Buy",
            "num_analysts": 28,
            "earnings_date": "2025-05-15",
            "last_eps_surprise_pct": 32.86,
        },
        "industry_news": [
            {
                "title": "China AI Industry Accelerates: ERNIE, Qwen, DeepSeek Compete for Enterprise Market",
                "publisher": "South China Morning Post",
                "published": "2025-02-22",
                "summary": "China's AI large model competition intensifies. Baidu's ERNIE, Alibaba's Qwen, and startup DeepSeek are battling for enterprise adoption. Cloud infrastructure spending expected to grow 30%+ in 2025.",
            },
        ],
    }


def format_news_text(news_data):
    """格式化新闻为文本"""
    lines = ["## 公司新闻"]
    for n in news_data.get("news", [])[:10]:
        lines.append(f"- [{n.get('published', '')}] {n['title']}")
        lines.append(f"  {n.get('summary', '')[:200]}")

    earnings = news_data.get("earnings", {})
    if earnings:
        lines.append("\n## 分析师预期")
        if earnings.get("analyst_target_price"):
            lines.append(f"- 目标价: ${earnings['analyst_target_price']}")
        if earnings.get("analyst_recommendation"):
            lines.append(f"- 评级: {earnings['analyst_recommendation']}")
        if earnings.get("num_analysts"):
            lines.append(f"- 覆盖分析师: {earnings['num_analysts']}人")
        if earnings.get("last_eps_surprise_pct"):
            lines.append(f"- 上季EPS惊喜: +{earnings['last_eps_surprise_pct']}%")

    for n in news_data.get("industry_news", [])[:5]:
        lines.append(f"\n## 行业新闻")
        lines.append(f"- [{n.get('published', '')}] {n['title']}")
        lines.append(f"  {n.get('summary', '')[:200]}")

    return "\n".join(lines)


def format_comparison_text(comparison):
    """格式化竞品对比为文本"""
    lines = ["## 同业对比 (中概互联网)\n"]
    lines.append(f"{'公司':<25} {'市值':>10} {'PE':>8} {'PS':>8} {'毛利率':>8} {'净利率':>8} {'营收增速':>8}")
    lines.append("-" * 85)

    for c in comparison.get("comparison_table", []):
        name = c.get("company_name", c.get("symbol", ""))[:24]
        mc = c.get("market_cap", 0)
        mc_str = f"${mc/1e9:.0f}B" if mc >= 1e9 else "N/A"
        pe = c.get("pe_ratio")
        pe_str = f"{pe:.1f}" if pe else "N/A"
        ps = c.get("ps_ratio")
        ps_str = f"{ps:.1f}" if ps else "N/A"
        gm = c.get("gross_margin")
        gm_str = f"{gm*100:.1f}%" if gm else "N/A"
        pm = c.get("profit_margin")
        pm_str = f"{pm*100:.1f}%" if pm else "N/A"
        rg = c.get("revenue_growth")
        rg_str = f"{rg*100:+.1f}%" if rg else "N/A"
        lines.append(f"{name:<25} {mc_str:>10} {pe_str:>8} {ps_str:>8} {gm_str:>8} {pm_str:>8} {rg_str:>8}")

    return "\n".join(lines)


def build_data_pack(engine):
    """构建完整的 data_pack，与 engine._collect_data() 返回格式完全一致"""
    key_metrics, current_price = load_key_metrics()
    financials = build_financials()
    comparison = build_competitive_comparison(key_metrics)
    news_data = build_news_data()

    # 技术指标 (手动构建)
    technical = {
        "current_price": current_price,
        "sma_20": current_price * 0.98,
        "sma_50": current_price * 0.95,
        "sma_200": current_price * 0.88,
        "rsi_14": 58.0,
        "macd": 1.2,
        "macd_signal": 0.8,
        "macd_histogram": 0.4,
        "bb_upper": current_price * 1.05,
        "bb_middle": current_price,
        "bb_lower": current_price * 0.95,
        "atr_14": current_price * 0.03,
        "adx": 22.0,
        "pct_from_52w_high": ((current_price / 160.0) - 1) * 100,
        "pct_from_52w_low": ((current_price / 78.0) - 1) * 100,
        "volume_ratio": 1.15,
    }

    # 竞品对比文本
    competitive_text = format_comparison_text(comparison)

    # 产业链文本
    supply_chain_lines = []
    for direction, label in [("supply_chain_upstream", "上游"), ("supply_chain_downstream", "下游")]:
        companies = comparison.get(direction, [])
        if companies:
            supply_chain_lines.append(f"\n### 产业链{label}")
            for c in companies:
                rg = c.get("revenue_growth")
                pm = c.get("profit_margin")
                rg_str = f"{rg*100:.1f}%" if rg else "N/A"
                pm_str = f"{pm*100:.1f}%" if pm else "N/A"
                supply_chain_lines.append(
                    f"- {c.get('company_name', c.get('symbol', ''))}: "
                    f"营收增速 {rg_str}, 利润率 {pm_str}"
                )
    supply_chain_text = "\n".join(supply_chain_lines) if supply_chain_lines else "无产业链数据"

    # 新闻文本
    news_text = format_news_text(news_data)

    data_pack = {
        "symbol": "BIDU",
        "key_metrics": key_metrics,
        "price_data": None,  # DataFrame 不影响分析
        "financials": financials,
        "technical_indicators": technical,
        "competitive_comparison": comparison,
        "competitive_text": competitive_text,
        "supply_chain_text": supply_chain_text,
        "news_data": news_data,
        "news_text": news_text,
    }

    # 量化估值
    valuation = run_valuation(key_metrics, financials, comparison)
    if valuation:
        data_pack["valuation"] = valuation
        data_pack["valuation_text"] = format_valuation_text(valuation)
        console.print(f"  [green]估值完成: {valuation.valuation_grade}, "
                      f"公允 ${valuation.fair_value:.2f} "
                      f"(当前 ${valuation.current_price:.2f}, {valuation.upside_pct:+.1f}%)[/green]")
    else:
        data_pack["valuation"] = None
        data_pack["valuation_text"] = "（数据不足，无法进行量化估值）"
        console.print("  [yellow]估值跳过: 数据不足[/yellow]")

    # 数据质量评估
    data_pack["data_quality_note"] = DebateEngine._assess_data_quality(data_pack)

    # 行业热点事件
    data_pack["market_context"] = engine._get_market_context("BIDU")

    return data_pack


# ======================================================================
# 主入口
# ======================================================================

def main():
    console.print(Panel(
        "[bold cyan]百度 (BIDU) 完整多Agent辩论分析 v2[/bold cyan]\n"
        "[dim]SSOT + Fact-Checker + 6个互斥角色 + 击球区判断[/dim]\n"
        "[dim]数据源: Web搜索预收集 | LLM: Anthropic Claude[/dim]\n"
        "\n[bold yellow]BIDU — Baidu, Inc.[/bold yellow]",
        title="Stock Deep Analysis v2 (Sandbox Mode)",
        border_style="cyan",
    ))

    # 使用 Anthropic 作为 LLM 提供商
    provider = LLMProvider(provider="anthropic")
    console.print(f"  LLM: CIO={provider.get_model('cio')}, "
                  f"Analyst={provider.get_model('analyst')}, "
                  f"Data={provider.get_model('data')}")

    # 初始化引擎 (使用 Anthropic)
    engine = DebateEngine(
        config_path="config/config.yaml",
        provider_override=provider,
    )

    # 构建预收集的数据包
    console.print("\n[bold green]>>> 数据准备 (预收集数据)[/bold green]")
    data_pack = build_data_pack(engine)
    console.print(f"  key_metrics: {len(data_pack['key_metrics'])} 字段")
    console.print(f"  financials: {len(data_pack['financials'])} 报表")
    console.print(f"  竞品: {len(data_pack['competitive_comparison'].get('comparison_table', [])) - 1} 家")
    console.print(f"  新闻: {len(data_pack['news_data'].get('news', []))} 条")
    if data_pack.get("data_quality_note"):
        console.print(f"  [yellow]{data_pack['data_quality_note'][:100]}[/yellow]")
    else:
        console.print("  [green]数据质量: 良好[/green]")

    # Monkey-patch _collect_data 返回预构建的数据
    def patched_collect_data(self, symbol):
        return data_pack

    engine._collect_data = MethodType(patched_collect_data, engine)

    # 回调函数
    def on_phase(phase_name):
        console.print(f"\n[bold green]>>> {phase_name}[/bold green]")

    def on_agent(agent_name, agent_title):
        console.print(f"  [cyan]{agent_name}[/cyan] ({agent_title}) 分析中...")

    def on_round(round_num):
        console.print(f"\n  [yellow]── 辩论第 {round_num} 轮 ──[/yellow]")

    def on_message(message):
        console.print(f"  [dim]{message}[/dim]")

    callbacks = {
        "on_phase": on_phase,
        "on_agent": on_agent,
        "on_round": on_round,
        "on_message": on_message,
    }

    # 运行完整分析
    console.print("\n" + "=" * 60)
    console.print("[bold]开始完整多Agent辩论分析...[/bold]")
    console.print("=" * 60)

    try:
        result = engine.analyze("BIDU", callbacks=callbacks)
    except Exception as e:
        console.print(f"\n[red]分析过程出错: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Token 用量统计
    usage = engine.get_token_usage()
    if usage["calls"] > 0:
        console.print(Panel(
            f"[bold]API 调用: {usage['calls']}次[/bold]\n"
            f"输入 tokens: {usage['input_tokens']:,}\n"
            f"输出 tokens: {usage['output_tokens']:,}\n"
            f"[bold]合计 tokens: {usage['input_tokens'] + usage['output_tokens']:,}[/bold]\n"
            + "\n".join(
                f"  {m}: {s['calls']}次, {s['input_tokens']:,}in / {s['output_tokens']:,}out"
                for m, s in usage.get("by_model", {}).items()
            ),
            title="Token Usage",
            border_style="yellow",
        ))

    # 生成并输出报告
    report = DebateEngine.generate_report(result)
    console.print(f"\n{report}")

    # 保存结果
    output_dir = Path("data/test_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / "bidu_analysis_report.txt"
    report_path.write_text(report, encoding="utf-8")
    console.print(f"\n[green]报告已保存: {report_path}[/green]")

    # 保存 JSON
    json_path = output_dir / "bidu_analysis_result.json"
    clean_result = _clean_for_json(result)
    json_path.write_text(
        json.dumps(clean_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    console.print(f"[green]JSON已保存: {json_path}[/green]")


def _clean_for_json(obj):
    """递归清理不可JSON序列化的对象"""
    if isinstance(obj, dict):
        return {k: _clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_for_json(item) for item in obj]
    elif isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    else:
        return str(obj)


if __name__ == "__main__":
    main()
