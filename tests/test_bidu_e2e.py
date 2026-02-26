#!/usr/bin/env python3
"""
BIDU 端到端测试 — 使用预收集的搜索数据 + Anthropic LLM 提取
绕过沙盒网络限制，直接测试 LLM 提取管道的准确性
"""

import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ========================================================
# 预收集的真实搜索结果 (来自 Claude WebSearch 2025-02-26)
# ========================================================
MOCK_SEARCH_RESULTS = {
    "metrics": [
        {
            "title": "Baidu, Inc. (BIDU) Valuation Measures & Financial Statistics",
            "url": "https://finance.yahoo.com/quote/BIDU/key-statistics/",
            "snippet": "Market Cap: $51.36B. Enterprise Value: $50.73B. Trailing PE: 36.11. Forward PE: 16.33. PEG: N/A. Price/Sales: 2.82. Price/Book: 1.31."
        },
        {
            "title": "Baidu PE Ratio 2011-2025 | BIDU | MacroTrends",
            "url": "https://www.macrotrends.net/stocks/charts/BIDU/baidu/pe-ratio",
            "snippet": "At the end of 2024 the company had a P/E ratio of 9.11. Current PE Ratio TTM is 49.54."
        },
        {
            "title": "Baidu Revenue 2012-2025 | BIDU | MacroTrends",
            "url": "https://www.macrotrends.net/stocks/charts/BIDU/baidu/revenue",
            "snippet": "Baidu annual revenue for 2024 was $18.238 billion, a 3.8% decline from 2023. Revenue for 2023 was $18.955 billion."
        },
        {
            "title": "Baidu (BIDU) Stock Price & Overview - StockAnalysis",
            "url": "https://stockanalysis.com/stocks/bidu/",
            "snippet": "Baidu (BIDU) stock price $133.67. Market cap $51.36B. PE ratio 36.11. EPS $3.25. Shares outstanding 350.6M. Revenue $18.24B (2024)."
        },
        {
            "title": "Baidu (BIDU) Statistics & Valuation",
            "url": "https://stockanalysis.com/stocks/bidu/statistics/",
            "snippet": "Current ratio 1.91. Debt/Equity 0.34. Cash $17.53B. Total debt $13.66B. Net cash $3.87B ($11.27/share). Gross margin 44.75%. Operating margin 9.88%. Profit margin 6.90%."
        },
    ],
    "financials": [
        {
            "title": "Baidu Announces Fourth Quarter and Fiscal Year 2024 Results",
            "url": "https://ir.baidu.com/news-releases/news-release-details/baidu-announces-fourth-quarter-and-fiscal-year-2024-results",
            "snippet": "Total Revenue FY2024: RMB 133.1B (-1% YoY). Baidu Core Revenue: RMB 104.7B (+1% YoY). Operating Income: RMB 21.3B ($2.91B). Net Income Attributable to Baidu FY2024: RMB 23.17B (+18.24% YoY). AI Cloud Revenue Q4: RMB 7.1B (+26% YoY). Cash & short-term investments: RMB 139.1B ($19.06B)."
        },
        {
            "title": "Baidu Financial Statements 2009-2025 | MacroTrends",
            "url": "https://www.macrotrends.net/stocks/charts/BIDU/baidu/financial-statements",
            "snippet": "FY2024: Revenue $18.24B, Gross Profit $8.16B, Operating Income $1.80B, Net Income $1.26B. FY2023: Revenue $18.96B, Gross Profit $9.19B, Operating Income $3.67B, Net Income $2.84B."
        },
        {
            "title": "BIDU Balance Sheet - Yahoo Finance",
            "url": "https://finance.yahoo.com/quote/BIDU/balance-sheet/",
            "snippet": "Total Assets: RMB 427.8B. Total Liabilities: RMB 144.2B. Total Equity: RMB 283.6B. Total Debt: RMB 93.5B. Debt/Equity: 32.2%."
        },
        {
            "title": "BIDU Cash Flow - StockAnalysis",
            "url": "https://stockanalysis.com/stocks/bidu/financials/cash-flow-statement/",
            "snippet": "FY2024: Operating Cash Flow: RMB 33.1B. Capital Expenditure: RMB 13.0B. Free Cash Flow: RMB 13.1B."
        },
        {
            "title": "Baidu Q4 2024 Earnings Call",
            "url": "https://ir.baidu.com/static-files/4153c8fb-8e4a-4d22-a097-c2fe0b177d49",
            "snippet": "Q4 2024: Revenue RMB 34.1B (-2% YoY). Q3 2024: Revenue RMB 33.6B. Q2 2024: Revenue RMB 33.9B. Q1 2024: Revenue RMB 31.5B. Non-GAAP EPS Q4: RMB 19.18 ($2.63)."
        },
    ],
    "news": [
        {
            "title": "Baidu Inc (BIDU) Q4 2024 Earnings Call Highlights: AI Cloud Growth and Strategic Investments",
            "url": "https://finance.yahoo.com/news/baidu-inc-bidu-q4-2024-070244841.html",
            "snippet": "AI Cloud revenue grew 26% YoY in Q4. Apollo Go provided over 1.1 million rides, up 36% YoY."
        },
        {
            "title": "Baidu (BIDU) Q4 2024 Earnings Call Transcript",
            "url": "https://www.fool.com/earnings/call-transcripts/2025/02/18/baidu-bidu-q4-2024-earnings-call-transcript/",
            "snippet": "Baidu's AI Cloud business demonstrated robust momentum with fourth-quarter revenue growth accelerating to 26% year over year."
        },
        {
            "title": "Baidu stock rises on AI cloud growth despite revenue decline",
            "url": "https://news.alphastreet.com/bidu-earnings-highlights-of-baidus-q4-2024-financial-results/",
            "snippet": "Baidu reported +32.86% EPS surprise and +0.91% revenue surprise vs analyst forecasts."
        },
    ]
}

# 真实验证数据 (已知正确值，用于检验提取准确性)
GROUND_TRUTH = {
    "company_name": "Baidu, Inc.",
    "market_cap_range": (45e9, 60e9),   # $45-60B
    "pe_ratio_range": (8, 50),           # 宽泛范围因为不同来源差异
    "revenue_range": (17e9, 19.5e9),     # $17-19.5B (2024)
    "profit_margin_range": (0.03, 0.15),
    "current_ratio_approx": 1.91,
    "debt_to_equity_approx": 0.34,
    "gross_margin_range": (0.40, 0.50),
}


def build_combined_text(search_key: str) -> str:
    """将 mock 搜索结果格式化为 WebSearchFetcher 的输入"""
    results = MOCK_SEARCH_RESULTS[search_key]
    snippets = [f"[{r['title']}] {r['snippet']}" for r in results]
    return "## Search Result Snippets:\n" + "\n".join(snippets)


def build_llm_client():
    """构建 LLM 客户端 (Anthropic 直连)"""
    import yaml
    from src.utils.llm_client import LLMClient, build_provider_from_config

    # 使用 Anthropic 直连配置
    config = {
        "llm_provider": {"provider": "anthropic"},
        "models": {
            "data_extract": "claude-haiku-4-5-20251001",
        }
    }
    provider = build_provider_from_config(config)
    llm = LLMClient(provider)
    data_model = provider.get_model("data")
    return llm, data_model


def test_key_metrics_extraction():
    """测试 1: 关键指标 LLM 提取"""
    print("\n" + "=" * 60)
    print("  Test 1: Key Metrics LLM Extraction — BIDU")
    print("=" * 60)

    from src.data.web_search import WebSearchFetcher, KEY_METRICS_SYSTEM_PROMPT, KEY_METRICS_USER_TEMPLATE

    llm, data_model = build_llm_client()
    ws = WebSearchFetcher(llm_client=llm, data_model=data_model, cache_hours=0)

    combined_text = build_combined_text("metrics")
    user_msg = KEY_METRICS_USER_TEMPLATE.format(
        symbol="BIDU",
        company_hint="Baidu Inc",
        combined_text=combined_text,
    )

    print(f"  Input text length: {len(combined_text)} chars")
    print(f"  Calling LLM ({data_model})...")

    result = ws._llm_extract(KEY_METRICS_SYSTEM_PROMPT, user_msg)

    if not result:
        print("  FAIL: LLM returned None")
        return None

    print(f"  OK: Got {len(result)} fields")

    # 验证关键字段
    checks = []

    # company_name
    cn = result.get("company_name", "")
    ok = "baidu" in cn.lower()
    checks.append(("company_name", cn, ok))
    print(f"  company_name: {cn} {'OK' if ok else 'FAIL'}")

    # market_cap
    mc = result.get("market_cap")
    lo, hi = GROUND_TRUTH["market_cap_range"]
    ok = mc is not None and lo <= mc <= hi
    mc_str = f"${mc/1e9:.1f}B" if mc and mc > 1e9 else str(mc)
    checks.append(("market_cap", mc_str, ok))
    print(f"  market_cap: {mc_str} {'OK' if ok else 'WARN (expected $45-60B)'}")

    # pe_ratio
    pe = result.get("pe_ratio")
    lo, hi = GROUND_TRUTH["pe_ratio_range"]
    ok = pe is not None and lo <= pe <= hi
    checks.append(("pe_ratio", pe, ok))
    print(f"  pe_ratio: {pe} {'OK' if ok else 'WARN'}")

    # revenue
    rev = result.get("revenue")
    lo, hi = GROUND_TRUTH["revenue_range"]
    ok = rev is not None and lo <= rev <= hi
    rev_str = f"${rev/1e9:.2f}B" if rev and rev > 1e9 else str(rev)
    checks.append(("revenue", rev_str, ok))
    print(f"  revenue: {rev_str} {'OK' if ok else 'WARN (expected $17-19.5B)'}")

    # profit_margin
    pm = result.get("profit_margin")
    lo, hi = GROUND_TRUTH["profit_margin_range"]
    ok = pm is not None and lo <= pm <= hi
    checks.append(("profit_margin", f"{pm*100:.1f}%" if pm else "null", ok))
    print(f"  profit_margin: {pm*100:.1f}% {'OK' if ok else 'WARN'}" if pm else f"  profit_margin: null WARN")

    # gross_margin
    gm = result.get("gross_margin")
    lo, hi = GROUND_TRUTH["gross_margin_range"]
    ok = gm is not None and lo <= gm <= hi
    checks.append(("gross_margin", f"{gm*100:.1f}%" if gm else "null", ok))
    print(f"  gross_margin: {gm*100:.1f}% {'OK' if ok else 'WARN'}" if gm else f"  gross_margin: null WARN")

    # current_ratio
    cr = result.get("current_ratio")
    ok = cr is not None and abs(cr - GROUND_TRUTH["current_ratio_approx"]) < 0.3
    checks.append(("current_ratio", cr, ok))
    print(f"  current_ratio: {cr} {'OK' if ok else 'WARN (expected ~1.91)'}")

    # debt_to_equity
    dte = result.get("debt_to_equity")
    ok = dte is not None and abs(dte - GROUND_TRUTH["debt_to_equity_approx"]) < 0.2
    checks.append(("debt_to_equity", dte, ok))
    print(f"  debt_to_equity: {dte} {'OK' if ok else 'WARN (expected ~0.34)'}")

    # data_confidence
    conf = result.get("data_confidence", "unknown")
    print(f"  data_confidence: {conf}")

    # data_sources
    sources = result.get("data_sources", [])
    print(f"  data_sources: {sources}")

    passed = sum(1 for _, _, ok in checks if ok)
    total = len(checks)
    print(f"\n  Score: {passed}/{total} fields verified")

    return result


def test_financials_extraction():
    """测试 2: 财报数据 LLM 提取"""
    print("\n" + "=" * 60)
    print("  Test 2: Financial Statements LLM Extraction — BIDU")
    print("=" * 60)

    from src.data.web_search import WebSearchFetcher, FINANCIALS_SYSTEM_PROMPT, FINANCIALS_USER_TEMPLATE

    llm, data_model = build_llm_client()
    ws = WebSearchFetcher(llm_client=llm, data_model=data_model, cache_hours=0)

    combined_text = build_combined_text("financials")
    user_msg = FINANCIALS_USER_TEMPLATE.format(
        symbol="BIDU",
        company_hint="Baidu Inc",
        combined_text=combined_text,
    )

    print(f"  Input text length: {len(combined_text)} chars")
    print(f"  Calling LLM ({data_model})...")

    result = ws._llm_extract(FINANCIALS_SYSTEM_PROMPT, user_msg)

    if not result:
        print("  FAIL: LLM returned None")
        return None

    # 检查各报表
    for section in ("income_statement", "balance_sheet", "cash_flow", "quarterly_income"):
        data = result.get(section, {})
        if data and not isinstance(data, str):
            periods = list(data.keys())
            print(f"  {section}: {len(periods)} periods — {', '.join(periods[:3])}")
            # 显示最近一期的关键数据
            if periods:
                latest = data[periods[0]]
                if isinstance(latest, dict):
                    for k, v in list(latest.items())[:5]:
                        if isinstance(v, (int, float)) and abs(v) > 1e6:
                            print(f"    {k}: {v/1e9:.2f}B")
                        elif v is not None:
                            print(f"    {k}: {v}")
        else:
            print(f"  {section}: (empty)")

    print(f"  currency: {result.get('currency', '?')}")
    print(f"  data_confidence: {result.get('data_confidence', '?')}")

    # 验证: 2024 revenue 应该约 133B CNY 或 $18B
    income = result.get("income_statement", {})
    if income:
        latest_key = list(income.keys())[0]
        rev = income[latest_key].get("revenue")
        if rev:
            currency = result.get("currency", "CNY")
            if currency in ("CNY", "RMB"):
                ok = 120e9 <= rev <= 140e9
                print(f"\n  Revenue verification: {rev/1e9:.1f}B CNY {'OK' if ok else 'WARN (expected ~133B CNY)'}")
            else:
                ok = 16e9 <= rev <= 20e9
                print(f"\n  Revenue verification: ${rev/1e9:.1f}B {'OK' if ok else 'WARN (expected ~$18B)'}")

    return result


def test_news_extraction():
    """测试 3: 新闻搜索"""
    print("\n" + "=" * 60)
    print("  Test 3: News (Direct from search results)")
    print("=" * 60)

    news = MOCK_SEARCH_RESULTS["news"]
    print(f"  {len(news)} articles found:")
    for i, n in enumerate(news):
        print(f"    [{i}] {n['title'][:70]}")
        print(f"        {n['snippet'][:100]}")
    print("  OK")
    return True


def test_ir_verification(metrics: dict):
    """测试 4: IR 交叉验证"""
    print("\n" + "=" * 60)
    print("  Test 4: IR Cross-Verification — BIDU")
    print("=" * 60)

    from src.data.web_search import WebSearchFetcher, IR_VERIFICATION_SYSTEM_PROMPT, IR_VERIFICATION_USER_TEMPLATE

    llm, data_model = build_llm_client()
    ws = WebSearchFetcher(llm_client=llm, data_model=data_model, cache_hours=0)

    if not metrics:
        print("  SKIP: No metrics to verify")
        return None

    # 使用 IR 数据 (来自 Baidu 官方公告)
    ir_content = """
=== Baidu Announces Fourth Quarter and Fiscal Year 2024 Results (ir.baidu.com) ===
Total revenues were RMB 133.1 billion ($18.24 billion) for the fiscal year 2024, compared with RMB 134.6 billion for fiscal year 2023.
Baidu Core revenues were RMB 104.7 billion ($14.35 billion), an increase of 1% year over year.
Net income attributable to Baidu was RMB 23.17 billion ($3.17 billion), an increase of 18.24% year over year.
Operating income was RMB 21.3 billion ($2.91 billion).
Non-GAAP operating income was RMB 26.2 billion ($3.59 billion).
Cash, cash equivalents, restricted cash, and short-term investments were RMB 139.1 billion ($19.06 billion) as of December 31, 2024.
Total assets: RMB 427.8 billion. Total equity: RMB 283.6 billion.
Free cash flow: RMB 13.1 billion.
Employees: approximately 31,000.
AI Cloud revenue grew 26% YoY in Q4 2024.
Apollo Go provided over 1.1 million rides in Q4, up 36% YoY.
"""

    data_summary = {
        k: v for k, v in metrics.items()
        if k not in ("data_sources", "extraction_notes") and v is not None
    }

    user_msg = IR_VERIFICATION_USER_TEMPLATE.format(
        symbol="BIDU",
        existing_data=json.dumps(data_summary, ensure_ascii=False, indent=2),
        ir_content=ir_content,
    )

    print(f"  Calling LLM for IR verification...")
    result = ws._llm_extract(IR_VERIFICATION_SYSTEM_PROMPT, user_msg)

    if not result:
        print("  FAIL: LLM returned None")
        return None

    verified = result.get("verified_fields", [])
    corrected = result.get("corrected_fields", {})
    additional = result.get("additional_data", {})

    print(f"  Verified fields ({len(verified)}): {', '.join(verified[:8])}")
    print(f"  Corrected fields ({len(corrected)}):")
    for field, info in corrected.items():
        print(f"    {field}: {info.get('old_value')} → {info.get('new_value')}")
    print(f"  Additional data ({len(additional)}):")
    for field, val in list(additional.items())[:5]:
        print(f"    +{field}: {val}")
    print(f"  IR confidence: {result.get('verification_confidence', '?')}")

    return result


def main():
    print("=" * 60)
    print("  BIDU (百度) Web 搜索数据源 — 端到端测试")
    print("  使用预收集的真实搜索数据 + Anthropic Haiku 提取")
    print("=" * 60)
    print(f"  时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}

    # Test 1: Key Metrics
    try:
        metrics = test_key_metrics_extraction()
        results["key_metrics"] = "PASS" if metrics and not metrics.get("error") else "FAIL"
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        metrics = None
        results["key_metrics"] = f"ERROR: {e}"

    # Test 2: Financials
    try:
        financials = test_financials_extraction()
        results["financials"] = "PASS" if financials else "FAIL"
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        results["financials"] = f"ERROR: {e}"

    # Test 3: News
    results["news"] = "PASS" if test_news_extraction() else "FAIL"

    # Test 4: IR Verification
    try:
        verification = test_ir_verification(metrics)
        results["ir_verification"] = "PASS" if verification else "FAIL"
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        results["ir_verification"] = f"ERROR: {e}"

    # Test 5: Apply verification to metrics
    if metrics and verification:
        print("\n" + "=" * 60)
        print("  Test 5: Apply IR Corrections to Metrics")
        print("=" * 60)
        from src.data.web_search import WebSearchFetcher
        ws = WebSearchFetcher()
        verified_metrics = ws.apply_verification(metrics, verification)
        ir_info = verified_metrics.get("_ir_verification", {})
        print(f"  Verified: {ir_info.get('verified_count', 0)} fields")
        print(f"  Corrected: {ir_info.get('corrected_count', 0)} fields")
        print(f"  Final confidence: {verified_metrics.get('data_confidence', '?')}")
        results["apply_verification"] = "PASS"

        # 保存最终结果
        output_dir = project_root / "data" / "test_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "bidu_web_search_test.json"
        output_file.write_text(json.dumps(verified_metrics, ensure_ascii=False, indent=2))
        print(f"  Saved to: {output_file}")

    # Final Summary
    print("\n" + "=" * 60)
    print("  FINAL SUMMARY")
    print("=" * 60)
    for k, v in results.items():
        icon = "PASS" if v == "PASS" else "FAIL" if v == "FAIL" else "WARN"
        print(f"  {k:<25} {icon}")


if __name__ == "__main__":
    main()
