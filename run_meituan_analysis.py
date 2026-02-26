#!/usr/bin/env python3
"""
美团 (3690.HK) 完整多Agent辩论分析 v2 — SSOT + Fact-Checker + 互斥角色

数据时间: 2026年2月
核心看点: 2024年利润暴涨158% → 2025年外卖大战巨亏 → 2026年估值修复?

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
# 预收集的美团金融数据 (来源: Yahoo Finance, StockAnalysis, 美团IR, 新浪财经)
# 数据采集日期: 2026-02-26
# ======================================================================

def load_key_metrics():
    """美团 key_metrics (港元/人民币混合，与 fetcher 返回格式一致)"""
    # 汇率近似: 1 USD ≈ 7.3 RMB ≈ 7.8 HKD; 1 HKD ≈ 0.935 RMB
    current_price_hkd = 82.70
    shares = 6_110_000_000  # 61.1亿股
    market_cap_hkd = current_price_hkd * shares  # ~5048亿港元
    market_cap_usd = market_cap_hkd / 7.8  # ~$64.7B

    # FY2024 数据 (强劲年份)
    revenue_rmb = 337_600_000_000  # 3376亿 RMB
    revenue_usd = revenue_rmb / 7.3  # ~$46.2B
    net_income_rmb = 35_808_000_000  # 358亿 RMB (FY2024)
    net_income_usd = net_income_rmb / 7.3

    # 注: 2025年TTM数据已转亏, P/E为负
    # 此处用 FY2024 利润算 "历史PE" 供参考, 同时标注 TTM 为负
    pe_fy2024 = market_cap_hkd / (net_income_rmb / 0.935)  # ~13.2x (基于FY2024利润)
    # 2026E PE = 88x (国信证券预测 26E利润71亿元)
    forward_pe_26e = 88.0

    metrics = {
        "company_name": "Meituan (美团)",
        "sector": "Consumer Cyclical",
        "industry": "Internet Content & Information / Local Services",
        "market_cap": market_cap_usd,  # $64.7B
        "enterprise_value": market_cap_usd - (98_400_000_000 / 7.3),  # 减去净现金
        "pe_ratio": pe_fy2024,  # ~13.2x 基于FY2024利润
        "forward_pe": forward_pe_26e,  # 88x 基于2026E
        "peg_ratio": None,  # 2025亏损无法计算
        "pb_ratio": market_cap_hkd / (172_600_000_000 / 0.935),  # ~2.73x
        "ps_ratio": market_cap_usd / revenue_usd,  # ~1.40x
        "ev_ebitda": None,
        "ev_revenue": (market_cap_usd - 98_400_000_000 / 7.3) / revenue_usd,
        "profit_margin": net_income_rmb / revenue_rmb,  # 10.6% (FY2024)
        "operating_margin": 34_026_555_000 / revenue_rmb,  # 10.1% (FY2024 operating income)
        "gross_margin": 0.3844,  # 38.44% (FY2024)
        "roe": net_income_rmb / 172_600_000_000,  # ~20.7%
        "roa": net_income_rmb / 324_400_000_000,  # ~11.0%
        "revenue_growth": 0.2199,  # FY2024 YoY +22%
        "earnings_growth": 1.5843,  # FY2024 YoY +158%
        "revenue": revenue_usd,
        "net_income": net_income_usd,
        "total_debt": 55_800_000_000 / 7.3,  # ~$7.6B
        "total_cash": 154_400_000_000 / 7.3,  # ~$21.2B
        "debt_to_equity": 0.323,
        "current_ratio": 1.85,  # 估算
        "free_cash_flow": 25_000_000_000 / 7.3,  # FY2024 ~$3.4B 估算
        "operating_cash_flow": 40_000_000_000 / 7.3,  # FY2024 ~$5.5B 估算
        "dividend_yield": 0,
        "beta": 1.49,
        "52w_high": 189.60,  # HKD
        "52w_low": 79.25,  # HKD
        "50d_avg": current_price_hkd,
        "200d_avg": 110.0,  # 估算
        "avg_volume": None,
        "shares_outstanding": shares,
        "float_shares": None,
        "insider_pct": None,
        "institution_pct": None,
        "short_ratio": None,
        "target_price": 119.24,  # HKD 分析师平均目标价
        "analyst_rating": "Buy",
        "num_analysts": 30,
        "data_sources": ["Yahoo Finance", "StockAnalysis", "美团IR", "国信证券", "摩根大通"],
        "data_confidence": "high",
        "extraction_notes": (
            "FY2024是盈利大年(净利润+158%)，但2025年因外卖大战急剧转亏。"
            "TTM PE为负(2025H2亏损)，此处pe_ratio使用FY2024利润计算(~13x)作为参考。"
            "forward_pe 88x为国信证券2026E预测(预计利润仅71亿元)。"
            "2025全年预亏233-243亿元。"
            "股价HKD 82.70距52周高点189.60跌幅56%。"
        ),
        # 额外字段
        "annual_transaction_users": 7_700_000_000,  # 7.7亿
        "annual_active_merchants": 14_500_000,  # 1450万
        "employees": 108_900,
        "food_delivery_market_share_2024": 0.70,
        "food_delivery_market_share_2025q3": 0.50,
        "currency_note": "Stock in HKD, financials in RMB. 1 USD ≈ 7.3 RMB ≈ 7.8 HKD",
    }

    return metrics, current_price_hkd


def build_financials():
    """美团财务报表 (RMB, 与 fetcher.fetch_financials 返回格式一致)"""
    return {
        "income_statement": {
            "FY2024": {
                "revenue": 337_600_000_000,
                "costOfRevenue": 207_807_000_000,
                "grossProfit": 129_785_000_000,
                "operatingIncome": 34_027_000_000,
                "netIncome": 35_808_000_000,
                "eps": 5.85,  # HKD
                "ebitda": 42_000_000_000,  # 估算
                "sellingExpenses": 51_000_000_000,
                "rdExpenses": 20_000_000_000,
                "note": "盈利大年，净利润+158% YoY",
            },
            "FY2023": {
                "revenue": 276_740_000_000,
                "costOfRevenue": 179_500_000_000,
                "grossProfit": 97_240_000_000,
                "operatingIncome": 13_400_000_000,
                "netIncome": 13_856_000_000,
                "eps": 2.28,  # HKD
                "ebitda": 20_000_000_000,
            },
        },
        "balance_sheet": {
            "2024-12-31": {
                "totalAssets": 324_400_000_000,
                "totalLiabilities": 151_800_000_000,
                "totalEquity": 172_600_000_000,
                "cash": 154_400_000_000,
                "totalDebt": 55_800_000_000,
                "netCash": 98_400_000_000,
            },
            "2025-09-30": {
                "totalAssets": 310_000_000_000,  # 估算
                "totalLiabilities": 160_000_000_000,
                "totalEquity": 150_000_000_000,
                "cash": 141_300_000_000,  # 截至2025年9月
                "totalDebt": 55_000_000_000,
                "note": "外卖大战消耗现金",
            },
        },
        "cash_flow": {
            "FY2024": {
                "operatingCashFlow": 40_000_000_000,
                "capitalExpenditure": -15_000_000_000,
                "freeCashFlow": 25_000_000_000,
                "dividendsPaid": 0,
                "shareRepurchases": -10_000_000_000,
            },
        },
        "quarterly_income": {
            "2025-Q3": {
                "revenue": 95_500_000_000,
                "grossProfit": 25_200_000_000,
                "netIncome": -18_632_000_000,
                "sellingExpenses": 34_270_000_000,
                "note": "外卖大战最惨烈季度，上市以来最大单季亏损",
            },
            "2025-Q2": {
                "revenue": 93_000_000_000,
                "netIncome": -12_000_000_000,
                "note": "外卖价格战升级，利润急剧恶化",
            },
            "2025-Q1": {
                "revenue": 90_000_000_000,
                "netIncome": 5_000_000_000,
                "note": "Q1尚有盈利，竞争压力初现",
            },
            "2024-Q4": {
                "revenue": 88_487_000_000,
                "netIncome": 6_222_000_000,
                "operatingIncome": 6_693_000_000,
                "note": "FY2024 Q4 盈利，外卖大战尚未全面爆发",
            },
        },
        "currency": "RMB",
        "data_source": "web_search_verified",
        "important_note": (
            "2024年为盈利高峰。2025年因阿里/京东入局外卖引发价格战，"
            "美团Q3单季亏损186亿(上市以来最大)。全年预亏233-243亿元。"
            "2026年关键变量: 竞争投入边际收缩，利润能否修复。"
        ),
    }


def build_competitive_comparison(key_metrics):
    """竞品对比 (港股互联网)"""
    target = {
        "symbol": "3690.HK",
        "company_name": "Meituan (美团)",
        "market_cap": key_metrics.get("market_cap", 64_700_000_000),
        "pe_ratio": key_metrics.get("pe_ratio", 13.2),
        "ps_ratio": key_metrics.get("ps_ratio", 1.40),
        "pb_ratio": key_metrics.get("pb_ratio", 2.73),
        "profit_margin": key_metrics.get("profit_margin", 0.106),
        "revenue_growth": key_metrics.get("revenue_growth", 0.22),
        "gross_margin": key_metrics.get("gross_margin", 0.384),
        "debt_to_equity": key_metrics.get("debt_to_equity", 0.323),
        "note": "FY2024盈利数据; 2025年已转亏",
    }

    competitors = [
        {
            "symbol": "0700.HK", "company_name": "Tencent (腾讯)",
            "market_cap": 728_700_000_000, "pe_ratio": 19.0, "ps_ratio": 8.5,
            "pb_ratio": 5.2, "profit_margin": 0.30, "revenue_growth": 0.08,
            "gross_margin": 0.53, "debt_to_equity": 0.38,
        },
        {
            "symbol": "9988.HK", "company_name": "Alibaba (阿里巴巴)",
            "market_cap": 351_600_000_000, "pe_ratio": 18.0, "ps_ratio": 2.6,
            "pb_ratio": 2.1, "profit_margin": 0.12, "revenue_growth": 0.06,
            "gross_margin": 0.38, "debt_to_equity": 0.18,
            "note": "外卖大战主要进攻方; 淘宝闪购份额从30%升至42%",
        },
        {
            "symbol": "9618.HK", "company_name": "JD.com (京东)",
            "market_cap": 40_700_000_000, "pe_ratio": 10.0, "ps_ratio": 0.25,
            "pb_ratio": 1.5, "profit_margin": 0.025, "revenue_growth": 0.04,
            "gross_margin": 0.10, "debt_to_equity": 0.25,
            "note": "2025年2月入局外卖后快速收缩",
        },
        {
            "symbol": "9626.HK", "company_name": "Bilibili (哔哩哔哩)",
            "market_cap": 8_000_000_000, "pe_ratio": 50.0, "ps_ratio": 1.9,
            "pb_ratio": 2.8, "profit_margin": 0.01, "revenue_growth": 0.20,
            "gross_margin": 0.30, "debt_to_equity": 0.80,
        },
    ]

    return {
        "target": target,
        "industry": {
            "key": "hk_internet",
            "name": "港股互联网",
            "symbols": ["0700.HK", "9988.HK", "3690.HK", "9618.HK", "1024.HK", "9626.HK"],
        },
        "comparison_table": [target] + competitors,
        "supply_chain_upstream": [
            {
                "symbol": "0981.HK", "company_name": "SMIC (中芯国际)",
                "market_cap": 50_000_000_000, "revenue_growth": 0.25,
                "profit_margin": 0.10,
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
    """美团最新新闻 (2025-2026年)"""
    return {
        "news": [
            {
                "title": "美团预警2025全年亏损233-243亿元，外卖大战代价惨烈",
                "publisher": "美团公告/路透社",
                "link": "https://www.meituan.com/en-US/investor-relations",
                "published": "2026-02-13",
                "summary": (
                    "美团发布盈利预警，预计2025年全年净亏损233-243亿元(约$3.5B)，"
                    "与2024年净利润358亿元形成近600亿元的剧烈反转。"
                    "核心本地商业业务由盈转亏，主要因为行业非理性竞争加剧。"
                ),
            },
            {
                "title": "外卖大战烧掉2200亿: 美团Q3录得上市以来最大单季亏损186亿",
                "publisher": "新浪财经/澎湃新闻",
                "link": "https://finance.sina.com.cn/stock/t/2025-12-04/",
                "published": "2025-12-01",
                "summary": (
                    "2025年Q3美团营收955亿(+2% YoY)，但净亏损186亿，创上市以来最大亏损。"
                    "销售营销费用同比暴增90.9%至343亿，毛利率从38%降至26%。"
                    "三家巨头(美团/阿里/京东)Q2-Q3合计市场投入超2200亿。"
                ),
            },
            {
                "title": "阿里内部: '淘宝闪购三年不惧亏损'，2026年继续猛攻即时零售",
                "publisher": "腾讯新闻/晚点LatePost",
                "link": "https://news.qq.com/rain/a/20260214A03SZC00",
                "published": "2026-02-14",
                "summary": (
                    "阿里核心管理层在内部会议上表态: 继续加大投入淘宝闪购，三年不惧亏损。"
                    "2026年即时零售第一优先级是建仓。"
                    "据摩根大通调研，美团外卖份额从70%降至约50%，淘宝闪购升至42%。"
                ),
            },
            {
                "title": "外卖大战'分水岭': 阿里京东暂缓烧钱，美团亏损见底?",
                "publisher": "澎湃新闻/21世纪经济报道",
                "link": "https://m.thepaper.cn/newsDetail_forward_32096925",
                "published": "2025-11-29",
                "summary": (
                    "三家电话会议口风同时转向: 不再强调规模，开始讨论'效率''成本'和'健康增长'。"
                    "美团守住高价值领域: 实付超15元订单占2/3以上，超30元订单占70%以上。"
                    "美团Q4亏损低于Q3，低于高盛/中金预期。亏损可能已见底。"
                ),
            },
            {
                "title": "美团收购叮咚买菜，7.17亿美元加码即时零售",
                "publisher": "Bloomberg/路透社",
                "link": "https://m.thepaper.cn/newsDetail_forward_32551933",
                "published": "2026-02-20",
                "summary": (
                    "美团同意以7.17亿美元收购叮咚买菜100%股权，巩固在即时零售领域的布局。"
                    "叮咚买菜是中国领先的社区生鲜电商平台。"
                    "此举被视为美团在竞争压力下的防御性收购。"
                ),
            },
            {
                "title": "美团2024年财报: 全年营收3376亿创新高，净利润暴涨158%",
                "publisher": "美团IR",
                "link": "https://www.meituan.com/news/NN250321082001991",
                "published": "2025-03-21",
                "summary": (
                    "美团2024年全年营收3376亿元(+22%)，净利润358亿元(+158%)。"
                    "年交易用户7.7亿创新高，年活跃商户1450万。"
                    "核心本地商业营收2502亿(+21%)，经营利润524亿(+35%)。"
                    "到店业务订单量+65%，即时配送日峰值9800万单。"
                ),
            },
        ],
        "earnings": {
            "analyst_target_price": 119.24,  # HKD
            "analyst_target_high": 155.02,
            "analyst_target_low": 69.38,
            "analyst_recommendation": "Buy",
            "num_analysts": 30,
            "buy_count": 27,
            "sell_count": 3,
            "earnings_date": "2026-03-20",
            "last_eps_surprise_pct": -15.50,  # FY2024 EPS低于预期
            "upside_potential_pct": 44.19,
        },
        "industry_news": [
            {
                "title": "2026外卖大战: 阿里猛攻不止, 美团守住高客单价阵地",
                "publisher": "腾讯新闻",
                "published": "2026-02-14",
                "summary": (
                    "2026年外卖战进入新阶段。阿里声称三年不惧亏损继续进攻。"
                    "但三家巨头电话会议口风已从'扩张'转向'效率'。"
                    "美团在高客单价(>15元)领域份额仍然遥遥领先。"
                ),
            },
            {
                "title": "国信证券: 港股互联网2026年投资策略 — 美团估值修复需等利润拐点",
                "publisher": "国信证券研报",
                "published": "2025-12-30",
                "summary": (
                    "2026E预测: 腾讯PE 19x, 阿里PE 18x, 拼多多PE 12x, 京东PE 10x, 美团PE 88x。"
                    "美团高PE因2025年巨亏拖累。若2026年竞争投入收缩，利润修复空间巨大。"
                    "港股互联网板块南向资金持续流入。"
                ),
            },
        ],
    }


def format_news_text(news_data):
    """格式化新闻为文本"""
    lines = ["## 公司新闻"]
    for n in news_data.get("news", [])[:10]:
        lines.append(f"- [{n.get('published', '')}] {n['title']}")
        lines.append(f"  {n.get('summary', '')[:250]}")

    earnings = news_data.get("earnings", {})
    if earnings:
        lines.append("\n## 分析师预期")
        if earnings.get("analyst_target_price"):
            lines.append(f"- 目标价: HK${earnings['analyst_target_price']:.2f} "
                        f"(高 HK${earnings.get('analyst_target_high', 0):.0f} / "
                        f"低 HK${earnings.get('analyst_target_low', 0):.0f})")
        if earnings.get("analyst_recommendation"):
            lines.append(f"- 评级: {earnings['analyst_recommendation']} "
                        f"({earnings.get('buy_count', 0)}买 / {earnings.get('sell_count', 0)}卖)")
        if earnings.get("upside_potential_pct"):
            lines.append(f"- 上涨空间: +{earnings['upside_potential_pct']}%")
        if earnings.get("earnings_date"):
            lines.append(f"- 下次财报: {earnings['earnings_date']}")

    for n in news_data.get("industry_news", [])[:5]:
        lines.append(f"\n## 行业新闻")
        lines.append(f"- [{n.get('published', '')}] {n['title']}")
        lines.append(f"  {n.get('summary', '')[:250]}")

    return "\n".join(lines)


def format_comparison_text(comparison):
    """格式化竞品对比为文本"""
    lines = ["## 同业对比 (港股互联网)\n"]
    lines.append(f"{'公司':<30} {'市值':>10} {'PE':>8} {'PS':>8} {'毛利率':>8} {'净利率':>8} {'营收增速':>8}")
    lines.append("-" * 90)

    for c in comparison.get("comparison_table", []):
        name = c.get("company_name", c.get("symbol", ""))[:29]
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
        lines.append(f"{name:<30} {mc_str:>10} {pe_str:>8} {ps_str:>8} {gm_str:>8} {pm_str:>8} {rg_str:>8}")

    # 添加关键说明
    lines.append("")
    lines.append("注: 美团PE基于FY2024利润(~13x)。2025年已巨亏，TTM PE为负。")
    lines.append("    2026E前瞻PE: 腾讯19x, 阿里18x, 拼多多12x, 京东10x, 美团88x。")

    return "\n".join(lines)


def build_data_pack(engine):
    """构建完整的 data_pack"""
    key_metrics, current_price_hkd = load_key_metrics()
    financials = build_financials()
    comparison = build_competitive_comparison(key_metrics)
    news_data = build_news_data()

    # 技术指标 (港元)
    technical = {
        "current_price": current_price_hkd,  # HKD 82.70
        "sma_20": 84.50,
        "sma_50": 90.00,
        "sma_200": 120.00,
        "rsi_14": 32.0,  # 超卖区域
        "macd": -3.5,
        "macd_signal": -2.0,
        "macd_histogram": -1.5,
        "bb_upper": 95.0,
        "bb_middle": 85.0,
        "bb_lower": 75.0,
        "atr_14": 5.0,
        "adx": 35.0,  # 趋势较强(下行趋势)
        "pct_from_52w_high": ((current_price_hkd / 189.60) - 1) * 100,  # -56.4%
        "pct_from_52w_low": ((current_price_hkd / 79.25) - 1) * 100,   # +4.4%
        "volume_ratio": 1.35,  # 放量
    }

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

    news_text = format_news_text(news_data)

    data_pack = {
        "symbol": "3690.HK",
        "key_metrics": key_metrics,
        "price_data": None,
        "financials": financials,
        "technical_indicators": technical,
        "competitive_comparison": comparison,
        "competitive_text": competitive_text,
        "supply_chain_text": supply_chain_text,
        "news_data": news_data,
        "news_text": news_text,
    }

    # 量化估值
    # 注: 估值模块需要 50d_avg 作为当前价格
    # 美团以 HKD 交易，key_metrics 中的 50d_avg 已设为 HKD 价格
    valuation = run_valuation(key_metrics, financials, comparison)
    if valuation:
        data_pack["valuation"] = valuation
        data_pack["valuation_text"] = format_valuation_text(valuation)
        console.print(f"  [green]估值完成: {valuation.valuation_grade}, "
                      f"公允 HK${valuation.fair_value:.2f} "
                      f"(当前 HK${valuation.current_price:.2f}, {valuation.upside_pct:+.1f}%)[/green]")
    else:
        data_pack["valuation"] = None
        data_pack["valuation_text"] = (
            "（量化估值受限：2025年巨亏导致TTM PE为负，传统估值模型失效。\n"
            "参考：FY2024利润PE ~13x，2026E前瞻PE 88x。\n"
            "PS=1.4x在互联网公司中属于极低水平。净现金$13.5B提供安全边际。）"
        )
        console.print("  [yellow]估值跳过: 2025亏损导致传统模型受限[/yellow]")

    data_pack["data_quality_note"] = DebateEngine._assess_data_quality(data_pack)
    data_pack["market_context"] = engine._get_market_context("3690.HK")

    return data_pack


def main():
    console.print(Panel(
        "[bold cyan]美团 (3690.HK) 完整多Agent辩论分析[/bold cyan]\n"
        "[dim]数据: Web搜索预收集+IR | LLM: Anthropic Claude[/dim]\n"
        "\n[bold yellow]3690.HK — Meituan (美团)[/bold yellow]\n"
        "[dim]核心看点: FY2024盈利+158% → 2025外卖大战巨亏 → 2026利润修复?[/dim]",
        title="Stock Deep Analysis (Sandbox Mode)",
        border_style="cyan",
    ))

    provider = LLMProvider(provider="anthropic")
    console.print(f"  LLM: CIO={provider.get_model('cio')}, "
                  f"Analyst={provider.get_model('analyst')}, "
                  f"Data={provider.get_model('data')}")

    engine = DebateEngine(
        config_path="config/config.yaml",
        provider_override=provider,
    )

    console.print("\n[bold green]>>> 数据准备 (预收集数据)[/bold green]")
    data_pack = build_data_pack(engine)
    console.print(f"  key_metrics: {len(data_pack['key_metrics'])} 字段")
    console.print(f"  financials: {len(data_pack['financials'])} 报表")
    console.print(f"  竞品: {len(data_pack['competitive_comparison'].get('comparison_table', [])) - 1} 家")
    console.print(f"  新闻: {len(data_pack['news_data'].get('news', []))} 条")
    if data_pack.get("data_quality_note"):
        console.print(f"  [yellow]{data_pack['data_quality_note'][:120]}[/yellow]")
    else:
        console.print("  [green]数据质量: 良好[/green]")

    # Monkey-patch _collect_data
    def patched_collect_data(self, symbol):
        return data_pack

    engine._collect_data = MethodType(patched_collect_data, engine)

    # 回调
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

    console.print("\n" + "=" * 60)
    console.print("[bold]开始完整多Agent辩论分析...[/bold]")
    console.print("=" * 60)

    try:
        result = engine.analyze("3690.HK", callbacks=callbacks)
    except Exception as e:
        console.print(f"\n[red]分析过程出错: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Token 用量
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

    report = DebateEngine.generate_report(result)
    console.print(f"\n{report}")

    # 保存
    output_dir = Path("data/test_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / "meituan_analysis_report.txt"
    report_path.write_text(report, encoding="utf-8")
    console.print(f"\n[green]报告已保存: {report_path}[/green]")

    json_path = output_dir / "meituan_analysis_result.json"
    clean_result = _clean_for_json(result)
    json_path.write_text(
        json.dumps(clean_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    console.print(f"[green]JSON已保存: {json_path}[/green]")


def _clean_for_json(obj):
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
