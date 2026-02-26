#!/usr/bin/env python3
"""
Web 搜索数据源测试脚本 — 以百度 (BIDU) 为例

功能:
  1. 测试 DuckDuckGo 搜索是否可用
  2. 测试页面抓取是否可用
  3. 测试 LLM 提取关键指标 (需要 LLM API Key)
  4. 测试 LLM 提取财报数据
  5. 测试新闻搜索
  6. 测试 IR 交叉验证
  7. 与 yfinance 数据对比验证

用法:
  # 仅测试搜索和抓取 (无需 LLM)
  python tests/test_web_search.py --basic

  # 完整测试 (需要 LLM API Key)
  python tests/test_web_search.py

  # 指定股票
  python tests/test_web_search.py --symbol AAPL

  # 跳过 IR 验证 (节省时间)
  python tests/test_web_search.py --skip-ir
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# 确保项目根目录在 path 中
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def print_section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result(label: str, value, indent: int = 2):
    prefix = " " * indent
    if isinstance(value, dict):
        print(f"{prefix}{label}:")
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                print(f"{prefix}  {k}: {json.dumps(v, ensure_ascii=False)[:200]}")
            else:
                print(f"{prefix}  {k}: {v}")
    elif isinstance(value, list):
        print(f"{prefix}{label}: ({len(value)} items)")
        for i, item in enumerate(value[:5]):
            if isinstance(item, dict):
                print(f"{prefix}  [{i}] {item.get('title', item)}")
            else:
                print(f"{prefix}  [{i}] {item}")
    else:
        print(f"{prefix}{label}: {value}")


def test_basic_search(symbol: str):
    """测试 1: DuckDuckGo 搜索"""
    print_section(f"Test 1: DuckDuckGo Search — {symbol}")
    from src.data.web_search import WebSearchFetcher
    ws = WebSearchFetcher()

    query = f"{symbol} stock financial data market cap PE ratio"
    print(f"  Query: {query}")
    results = ws._web_search(query, max_results=5)

    if results:
        print(f"  OK: {len(results)} results")
        for i, r in enumerate(results):
            print(f"    [{i}] {r['title'][:60]}")
            print(f"        {r['url'][:80]}")
        return True
    else:
        print("  FAIL: No search results")
        return False


def test_page_fetch(symbol: str):
    """测试 2: 页面抓取"""
    print_section(f"Test 2: Page Fetch — Yahoo Finance")
    from src.data.web_search import WebSearchFetcher
    ws = WebSearchFetcher()

    # 先搜索找到页面
    results = ws._web_search(f"{symbol} stock quote yahoo finance", max_results=3)
    if not results:
        print("  SKIP: No search results to fetch")
        return False

    url = results[0]["url"]
    print(f"  Fetching: {url}")
    text = ws._fetch_page_text(url, max_chars=5000)

    if text and len(text) > 100:
        print(f"  OK: Got {len(text)} chars")
        # 显示前几行
        for line in text[:500].split("\n")[:10]:
            if line.strip():
                print(f"    | {line.strip()[:80]}")
        return True
    else:
        print(f"  FAIL: Only got {len(text) if text else 0} chars")
        return False


def build_llm_client():
    """构建 LLM 客户端"""
    from src.utils.llm_client import LLMClient, build_provider_from_config
    import yaml

    config_path = project_root / "config" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    provider = build_provider_from_config(config)
    llm = LLMClient(provider)
    data_model = provider.get_model("data")
    return llm, data_model


def test_key_metrics(symbol: str):
    """测试 3: LLM 提取关键指标"""
    print_section(f"Test 3: Key Metrics Extraction — {symbol}")
    from src.data.web_search import WebSearchFetcher

    llm, data_model = build_llm_client()
    ws = WebSearchFetcher(llm_client=llm, data_model=data_model, cache_hours=0)

    print("  Searching and extracting key metrics...")
    metrics = ws.fetch_key_metrics(symbol)

    if metrics.get("error"):
        print(f"  FAIL: {metrics['error']}")
        return None

    print(f"  OK: {metrics.get('company_name', '?')}")
    print(f"  Confidence: {metrics.get('data_confidence', '?')}")

    important_fields = [
        "company_name", "sector", "industry", "market_cap",
        "pe_ratio", "revenue", "net_income", "profit_margin",
        "roe", "revenue_growth", "data_confidence",
    ]
    for field in important_fields:
        val = metrics.get(field)
        if val is not None:
            if isinstance(val, float) and abs(val) > 1e6:
                print(f"    {field}: ${val/1e9:.2f}B" if val > 1e9 else f"    {field}: ${val/1e6:.0f}M")
            elif isinstance(val, float) and abs(val) < 100:
                print(f"    {field}: {val:.4f}")
            else:
                print(f"    {field}: {val}")
        else:
            print(f"    {field}: null")

    if metrics.get("data_sources"):
        print(f"  Sources: {', '.join(metrics['data_sources'][:5])}")
    if metrics.get("extraction_notes"):
        print(f"  Notes: {metrics['extraction_notes'][:200]}")

    return metrics


def test_financials(symbol: str):
    """测试 4: LLM 提取财报"""
    print_section(f"Test 4: Financial Statements — {symbol}")
    from src.data.web_search import WebSearchFetcher

    llm, data_model = build_llm_client()
    ws = WebSearchFetcher(llm_client=llm, data_model=data_model, cache_hours=0)

    print("  Searching and extracting financials...")
    fin = ws.fetch_financials(symbol)

    if not fin:
        print("  FAIL: Empty result")
        return None

    for section in ("income_statement", "balance_sheet", "cash_flow", "quarterly_income"):
        data = fin.get(section, {})
        if data and not isinstance(data, str):
            periods = list(data.keys())[:3]
            print(f"  {section}: {len(data)} periods — {', '.join(periods)}")
        else:
            print(f"  {section}: (empty)")

    print(f"  Currency: {fin.get('currency', '?')}")
    print(f"  Confidence: {fin.get('data_confidence', '?')}")

    return fin


def test_news(symbol: str):
    """测试 5: 新闻搜索"""
    print_section(f"Test 5: News Search — {symbol}")
    from src.data.web_search import WebSearchFetcher
    ws = WebSearchFetcher()

    news = ws.fetch_news(symbol, company_name="Baidu", max_items=10)

    if news:
        print(f"  OK: {len(news)} articles")
        for i, n in enumerate(news[:5]):
            print(f"    [{i}] {n['title'][:70]}")
            print(f"        ({n['publisher']})")
        return True
    else:
        print("  FAIL: No news found")
        return False


def test_ir_verification(symbol: str, existing_metrics: dict):
    """测试 6: IR 交叉验证"""
    print_section(f"Test 6: IR Cross-Verification — {symbol}")
    from src.data.web_search import WebSearchFetcher

    if not existing_metrics or existing_metrics.get("error"):
        print("  SKIP: No metrics to verify")
        return None

    llm, data_model = build_llm_client()
    ws = WebSearchFetcher(llm_client=llm, data_model=data_model, cache_hours=0)

    print("  Searching IR pages and verifying...")
    verification = ws.search_and_verify_from_ir(
        symbol, existing_metrics,
        company_name=existing_metrics.get("company_name", ""),
    )

    print(f"  Verified fields: {len(verification.get('verified_fields', []))}")
    if verification.get("verified_fields"):
        print(f"    {', '.join(verification['verified_fields'][:8])}")

    corrections = verification.get("corrected_fields", {})
    print(f"  Corrected fields: {len(corrections)}")
    for field, info in corrections.items():
        print(f"    {field}: {info.get('old_value')} → {info.get('new_value')}")

    additional = verification.get("additional_data", {})
    print(f"  Additional data: {len(additional)}")
    for field, val in list(additional.items())[:5]:
        print(f"    +{field}: {val}")

    print(f"  IR confidence: {verification.get('verification_confidence', '?')}")
    return verification


def test_yfinance_comparison(symbol: str, web_metrics: dict):
    """测试 7: 与 yfinance 数据对比"""
    print_section(f"Test 7: yfinance Comparison — {symbol}")

    if not web_metrics or web_metrics.get("error"):
        print("  SKIP: No web metrics to compare")
        return

    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
    except Exception as e:
        print(f"  SKIP: yfinance unavailable ({e})")
        return

    comparisons = {
        "market_cap": ("marketCap", lambda x: f"${x/1e9:.1f}B" if x and x > 1e9 else str(x)),
        "pe_ratio": ("trailingPE", lambda x: f"{x:.1f}" if x else "null"),
        "revenue": ("totalRevenue", lambda x: f"${x/1e9:.1f}B" if x and x > 1e9 else str(x)),
        "profit_margin": ("profitMargins", lambda x: f"{x*100:.1f}%" if x else "null"),
        "roe": ("returnOnEquity", lambda x: f"{x*100:.1f}%" if x else "null"),
        "beta": ("beta", lambda x: f"{x:.2f}" if x else "null"),
    }

    print(f"  {'Field':<18} {'Web Search':<20} {'yfinance':<20} {'Match?'}")
    print(f"  {'-'*18} {'-'*20} {'-'*20} {'-'*6}")

    for web_key, (yf_key, fmt) in comparisons.items():
        web_val = web_metrics.get(web_key)
        yf_val = info.get(yf_key)

        web_str = fmt(web_val) if web_val is not None else "null"
        yf_str = fmt(yf_val) if yf_val is not None else "null"

        # 判断是否大致匹配 (允许 20% 误差)
        match = "?"
        if web_val is not None and yf_val is not None:
            try:
                if yf_val != 0:
                    diff = abs(float(web_val) - float(yf_val)) / abs(float(yf_val))
                    match = "OK" if diff < 0.20 else f"~{diff:.0%}"
                else:
                    match = "OK" if float(web_val) == 0 else "DIFF"
            except (ValueError, TypeError):
                match = "?"
        elif web_val is None and yf_val is None:
            match = "both null"
        else:
            match = "one null"

        print(f"  {web_key:<18} {web_str:<20} {yf_str:<20} {match}")


def main():
    parser = argparse.ArgumentParser(description="Web Search 数据源测试")
    parser.add_argument("--symbol", default="BIDU", help="测试股票代码 (默认 BIDU)")
    parser.add_argument("--basic", action="store_true", help="仅测试搜索和抓取 (无需 LLM)")
    parser.add_argument("--skip-ir", action="store_true", help="跳过 IR 验证")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    args = parser.parse_args()

    setup_logging(args.verbose)
    symbol = args.symbol.upper()

    print(f"\nWeb Search Data Source Test — {symbol}")
    print(f"Mode: {'basic' if args.basic else 'full'}")
    print(f"Time: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}

    # Test 1 & 2: 基础搜索和抓取
    results["search"] = test_basic_search(symbol)
    results["fetch"] = test_page_fetch(symbol)

    if args.basic:
        # Test 5: 新闻也不需要 LLM
        results["news"] = test_news(symbol)
        print_section("Summary (Basic Mode)")
        for k, v in results.items():
            status = "PASS" if v else "FAIL"
            print(f"  {k}: {status}")
        return

    # Test 3-7: 完整测试 (需要 LLM)
    try:
        metrics = test_key_metrics(symbol)
        results["key_metrics"] = metrics is not None and not metrics.get("error")
    except Exception as e:
        print(f"  ERROR: {e}")
        metrics = None
        results["key_metrics"] = False

    try:
        fin = test_financials(symbol)
        results["financials"] = fin is not None and bool(fin)
    except Exception as e:
        print(f"  ERROR: {e}")
        results["financials"] = False

    results["news"] = test_news(symbol)

    if not args.skip_ir:
        try:
            verification = test_ir_verification(symbol, metrics)
            results["ir_verification"] = verification is not None
        except Exception as e:
            print(f"  ERROR: {e}")
            results["ir_verification"] = False
    else:
        print_section("Test 6: IR Verification — SKIPPED")
        results["ir_verification"] = "skipped"

    test_yfinance_comparison(symbol, metrics)

    # Summary
    print_section("Final Summary")
    for k, v in results.items():
        if v is True:
            status = "PASS"
        elif v is False:
            status = "FAIL"
        else:
            status = str(v).upper()
        print(f"  {k:<20} {status}")

    # 保存完整结果
    output_dir = project_root / "data" / "test_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"web_search_{symbol}_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    full_output = {"symbol": symbol, "results": {k: str(v) for k, v in results.items()}}
    if metrics and not isinstance(metrics, bool):
        full_output["metrics"] = metrics
    output_file.write_text(json.dumps(full_output, ensure_ascii=False, indent=2))
    print(f"\n  Results saved to: {output_file}")


if __name__ == "__main__":
    main()
