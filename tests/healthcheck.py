#!/usr/bin/env python3
"""
数据源健康检查 — 快速诊断各 API 可用性

用法:
    python tests/healthcheck.py              # 检查全部
    python tests/healthcheck.py --source tushare   # 只检查 Tushare
    python tests/healthcheck.py --source fmp       # 只检查 FMP
    python tests/healthcheck.py --source yfinance  # 只检查 yfinance

输出格式:
    [OK]   API名称 — 描述 (耗时)
    [FAIL] API名称 — 错误原因
    [SKIP] API名称 — 跳过原因

退出码:
    0 = 全部通过
    1 = 存在失败
    2 = 配置缺失 (无 API Key)
"""

import os
import sys
import time
import argparse
from pathlib import Path

# 加载 .env
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class HealthChecker:
    def __init__(self):
        self.results = []  # (status, name, detail, elapsed_ms)

    def check(self, name: str, fn, skip_reason: str = None):
        """运行一个检查项"""
        if skip_reason:
            self.results.append(("SKIP", name, skip_reason, 0))
            return
        t0 = time.time()
        try:
            detail = fn()
            elapsed = int((time.time() - t0) * 1000)
            self.results.append(("OK", name, detail or "成功", elapsed))
        except Exception as e:
            elapsed = int((time.time() - t0) * 1000)
            self.results.append(("FAIL", name, str(e), elapsed))

    def report(self):
        """打印报告并返回退出码"""
        w = max(len(r[1]) for r in self.results) + 2
        print(f"\n{'='*70}")
        print(f"  数据源健康检查报告")
        print(f"{'='*70}\n")

        ok = fail = skip = 0
        for status, name, detail, elapsed in self.results:
            icon = {"OK": "\033[32m[OK]  \033[0m",
                    "FAIL": "\033[31m[FAIL]\033[0m",
                    "SKIP": "\033[33m[SKIP]\033[0m"}[status]
            time_str = f" ({elapsed}ms)" if elapsed > 0 else ""
            print(f"  {icon} {name:<{w}} {detail}{time_str}")
            if status == "OK": ok += 1
            elif status == "FAIL": fail += 1
            else: skip += 1

        print(f"\n{'='*70}")
        print(f"  合计: {ok} 通过 / {fail} 失败 / {skip} 跳过")
        print(f"{'='*70}\n")

        if fail > 0:
            print("  诊断建议:")
            for status, name, detail, _ in self.results:
                if status == "FAIL":
                    print(f"    - {name}: {detail}")
                    if "token" in detail.lower() or "积分" in detail or "credit" in detail.lower():
                        print(f"      → 可能需要更高 Tushare 积分等级")
                    elif "timeout" in detail.lower() or "connect" in detail.lower():
                        print(f"      → 网络连接问题，检查代理/防火墙设置")
            print()

        return 1 if fail > 0 else 0


def check_tushare(hc: HealthChecker):
    """Tushare 检查"""
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    url = os.environ.get("TUSHARE_URL", "").strip()

    if not token:
        hc.check("Tushare Token", None, skip_reason="TUSHARE_TOKEN 未设置")
        return

    import tushare as ts
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    if url:
        pro._DataApi__http_url = url
        hc.check("Tushare 镜像地址", lambda: f"使用 {url}")
    else:
        hc.check("Tushare 地址", lambda: "使用官方 api.tushare.pro")

    # A 股
    def _daily():
        df = pro.daily(ts_code="000001.SZ", start_date="20240101", end_date="20240110")
        if df is None or df.empty:
            raise ValueError("返回空数据")
        return f"{len(df)} 条, 字段: {list(df.columns)[:5]}"

    def _daily_basic():
        df = pro.daily_basic(ts_code="600519.SH")
        if df is None or df.empty:
            raise ValueError("返回空数据")
        has_pe = "pe_ttm" in df.columns
        has_mv = "total_mv" in df.columns
        return f"{len(df)} 条, PE_TTM={'有' if has_pe else '缺'}, 总市值={'有' if has_mv else '缺'}"

    def _income():
        df = pro.income(ts_code="600519.SH")
        if df is None or df.empty:
            raise ValueError("返回空数据")
        return f"{len(df)} 条"

    def _fina():
        df = pro.fina_indicator(ts_code="600519.SH")
        if df is None or df.empty:
            raise ValueError("返回空数据")
        return f"{len(df)} 条, ROE 字段={'有' if 'roe' in df.columns else '缺'}"

    hc.check("Tushare A股: daily", _daily)
    hc.check("Tushare A股: daily_basic", _daily_basic)
    hc.check("Tushare A股: income", _income)
    hc.check("Tushare A股: fina_indicator", _fina)

    # 港股
    def _hk_basic():
        df = pro.hk_basic(ts_code="00700.HK")
        if df is None or df.empty:
            df = pro.hk_basic(list_status="L")
            if df is None or df.empty:
                raise ValueError("返回空数据")
            found = len(df[df["ts_code"] == "00700.HK"])
            return f"全量 {len(df)} 只, 含 00700.HK={found > 0}"
        return f"字段: {list(df.columns)[:6]}"

    def _hk_daily():
        df = pro.hk_daily(ts_code="00700.HK", start_date="20240101", end_date="20240110")
        if df is None or df.empty:
            raise ValueError("返回空数据")
        return f"{len(df)} 条"

    def _hk_daily_adj():
        df = pro.hk_daily_adj(ts_code="00700.HK", start_date="20240101", end_date="20240110")
        if df is None or df.empty:
            raise ValueError("返回空数据 (可能积分不足)")
        has_mcap = "market_cap" in df.columns
        has_share = "total_share" in df.columns
        return f"{len(df)} 条, 市值={'有' if has_mcap else '缺'}, 股本={'有' if has_share else '缺'}"

    def _hk_fina():
        df = pro.hk_fina_indicator(ts_code="00700.HK")
        if df is None or df.empty:
            raise ValueError("返回空数据 (需要 15000 积分)")
        return f"{len(df)} 条, 字段: {list(df.columns)[:6]}"

    hc.check("Tushare 港股: hk_basic", _hk_basic)
    hc.check("Tushare 港股: hk_daily", _hk_daily)
    hc.check("Tushare 港股: hk_daily_adj", _hk_daily_adj)
    hc.check("Tushare 港股: hk_fina_indicator", _hk_fina)


def check_fmp(hc: HealthChecker):
    """FMP 检查"""
    import requests

    fmp_key = os.environ.get("FMP_API_KEY", "").strip()
    if not fmp_key:
        hc.check("FMP API Key", None, skip_reason="FMP_API_KEY 未设置")
        return

    base = "https://financialmodelingprep.com/api/v3"

    def _profile():
        resp = requests.get(f"{base}/profile/AAPL", params={"apikey": fmp_key}, timeout=15)
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        data = resp.json()
        if not data:
            raise ValueError("返回空")
        return f"公司: {data[0].get('companyName')}, 市值: {data[0].get('mktCap')}"

    def _income():
        resp = requests.get(f"{base}/income-statement/AAPL", params={"apikey": fmp_key, "limit": 1}, timeout=15)
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        data = resp.json()
        if not data:
            raise ValueError("返回空")
        return f"日期: {data[0].get('date')}, 收入: {data[0].get('revenue')}"

    def _historical():
        resp = requests.get(f"{base}/historical-price-full/AAPL",
                          params={"apikey": fmp_key, "from": "2024-01-01", "to": "2024-01-10"}, timeout=15)
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        data = resp.json()
        if not data or "historical" not in data:
            raise ValueError("返回格式不对")
        return f"{len(data['historical'])} 条"

    hc.check("FMP: profile", _profile)
    hc.check("FMP: income-statement", _income)
    hc.check("FMP: historical-price", _historical)


def check_yfinance(hc: HealthChecker):
    """yfinance 检查"""
    try:
        import yfinance as yf
    except ImportError:
        hc.check("yfinance", None, skip_reason="yfinance 未安装")
        return

    def _us():
        ticker = yf.Ticker("AAPL")
        df = ticker.history(period="5d")
        if df is None or df.empty:
            raise ValueError("返回空")
        return f"{len(df)} 条, 最新收盘: {df['Close'].iloc[-1]:.2f}"

    def _hk():
        ticker = yf.Ticker("0700.HK")
        df = ticker.history(period="5d")
        if df is None or df.empty:
            raise ValueError("返回空 (港股可能被限制)")
        return f"{len(df)} 条, 最新收盘: {df['Close'].iloc[-1]:.2f}"

    def _info():
        ticker = yf.Ticker("AAPL")
        info = ticker.info
        if not info:
            raise ValueError("返回空")
        return f"公司: {info.get('longName')}, PE: {info.get('trailingPE')}"

    def _financials():
        ticker = yf.Ticker("AAPL")
        df = ticker.financials
        if df is None or df.empty:
            raise ValueError("返回空")
        return f"{df.shape[0]} 行 x {df.shape[1]} 列"

    hc.check("yfinance 美股: history", _us)
    hc.check("yfinance 港股: history", _hk)
    hc.check("yfinance: info", _info)
    hc.check("yfinance: financials", _financials)


def main():
    parser = argparse.ArgumentParser(description="数据源健康检查")
    parser.add_argument("--source", choices=["tushare", "fmp", "yfinance", "all"],
                       default="all", help="检查哪个数据源")
    args = parser.parse_args()

    hc = HealthChecker()

    if args.source in ("all", "tushare"):
        check_tushare(hc)
    if args.source in ("all", "fmp"):
        check_fmp(hc)
    if args.source in ("all", "yfinance"):
        check_yfinance(hc)

    code = hc.report()
    sys.exit(code)


if __name__ == "__main__":
    main()
