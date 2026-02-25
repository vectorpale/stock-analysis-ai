#!/usr/bin/env python3
"""
Tushare API 连通性测试脚本
用法: python tests/test_tushare.py

需要设置环境变量:
  TUSHARE_TOKEN=your_token
  TUSHARE_URL=http://lianghua.nanyangqiankun.top  (镜像地址)

或者直接加载 .env 文件
"""
import os
import sys

# 加载 .env
from pathlib import Path
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import tushare as ts


def get_pro():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    url = os.environ.get("TUSHARE_URL", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN 未设置")
        sys.exit(1)
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    if url:
        pro._DataApi__http_url = url
        print(f"使用镜像地址: {url}")
    else:
        print("使用官方地址: api.tushare.pro")
    return pro


def _print_section(name):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


def main():
    pro = get_pro()
    passed = 0
    failed = 0

    # =====================================================
    # A股测试
    # =====================================================
    _print_section("A股: 日线行情 (000001.SZ 平安银行)")
    try:
        df = pro.daily(ts_code='000001.SZ', start_date='20240101', end_date='20240131')
        if df is not None and not df.empty:
            print(df.head())
            print(f"✓ 成功 ({len(df)} 条)")
            passed += 1
        else:
            print("✗ 返回空数据")
            failed += 1
    except Exception as e:
        print(f"✗ 失败: {e}")
        failed += 1

    _print_section("A股: 每日基本指标 (daily_basic)")
    try:
        df = pro.daily_basic(ts_code='600519.SH',
                             fields='ts_code,trade_date,close,pe,pe_ttm,pb,ps_ttm,total_mv,circ_mv')
        if df is not None and not df.empty:
            print(df.head())
            print(f"✓ 成功 ({len(df)} 条)")
            passed += 1
        else:
            print("✗ 返回空数据")
            failed += 1
    except Exception as e:
        print(f"✗ 失败: {e}")
        failed += 1

    _print_section("A股: 公司信息 (stock_company)")
    try:
        df = pro.stock_company(ts_code='600519.SH')
        if df is not None and not df.empty:
            for col in df.columns:
                print(f"  {col}: {df[col].iloc[0]}")
            print(f"✓ 成功")
            passed += 1
        else:
            print("✗ 返回空数据")
            failed += 1
    except Exception as e:
        print(f"✗ 失败: {e}")
        failed += 1

    _print_section("A股: 财务指标 (fina_indicator)")
    try:
        df = pro.fina_indicator(ts_code='600519.SH')
        if df is not None and not df.empty:
            cols = [c for c in ['ts_code','end_date','eps','roe','grossprofit_margin',
                                'netprofit_margin','currentratio','debt_to_assets',
                                'or_yoy','netprofit_yoy'] if c in df.columns]
            print(df[cols].head(3))
            print(f"✓ 成功 ({len(df)} 条)")
            passed += 1
        else:
            print("✗ 返回空数据")
            failed += 1
    except Exception as e:
        print(f"✗ 失败: {e}")
        failed += 1

    _print_section("A股: 利润表 (income)")
    try:
        df = pro.income(ts_code='600519.SH')
        if df is not None and not df.empty:
            cols = [c for c in ['ts_code','end_date','revenue','operate_profit',
                                'total_profit','n_income'] if c in df.columns]
            print(df[cols].head(3))
            print(f"✓ 成功 ({len(df)} 条)")
            passed += 1
        else:
            print("✗ 返回空数据")
            failed += 1
    except Exception as e:
        print(f"✗ 失败: {e}")
        failed += 1

    _print_section("A股: 资产负债表 (balancesheet)")
    try:
        df = pro.balancesheet(ts_code='600519.SH')
        if df is not None and not df.empty:
            cols = [c for c in ['ts_code','end_date','total_assets','total_liab',
                                'total_hldr_eqy_exc_min_int','money_cap',
                                'total_share','float_share'] if c in df.columns]
            print(df[cols].head(3))
            print(f"✓ 成功 ({len(df)} 条)")
            passed += 1
        else:
            print("✗ 返回空数据")
            failed += 1
    except Exception as e:
        print(f"✗ 失败: {e}")
        failed += 1

    _print_section("A股: 现金流量表 (cashflow)")
    try:
        df = pro.cashflow(ts_code='600519.SH')
        if df is not None and not df.empty:
            cols = [c for c in ['ts_code','end_date','n_cashflow_act',
                                'n_cashflow_inv_act','n_cash_flows_fnc_act',
                                'free_cashflow'] if c in df.columns]
            print(df[cols].head(3))
            print(f"✓ 成功 ({len(df)} 条)")
            passed += 1
        else:
            print("✗ 返回空数据")
            failed += 1
    except Exception as e:
        print(f"✗ 失败: {e}")
        failed += 1

    # =====================================================
    # 港股测试
    # =====================================================
    _print_section("港股: 日线行情 (hk_daily 00700.HK 腾讯)")
    try:
        df = pro.hk_daily(ts_code='00700.HK', start_date='20240101', end_date='20240131')
        if df is not None and not df.empty:
            print(df.head())
            print(f"✓ 成功 ({len(df)} 条)")
            passed += 1
        else:
            print("✗ 返回空数据 (可能镜像不支持港股)")
            failed += 1
    except Exception as e:
        print(f"✗ 失败: {e}")
        failed += 1

    _print_section("港股: 基本信息 (hk_basic)")
    try:
        df = pro.hk_basic(ts_code='00700.HK')
        if df is not None and not df.empty:
            for col in df.columns:
                print(f"  {col}: {df[col].iloc[0]}")
            print(f"✓ 成功")
            passed += 1
        else:
            # 也试 list_status='L' 参数
            df2 = pro.hk_basic(list_status='L')
            if df2 is not None and not df2.empty:
                row = df2[df2['ts_code'] == '00700.HK']
                if not row.empty:
                    for col in row.columns:
                        print(f"  {col}: {row[col].iloc[0]}")
                    print(f"✓ 成功 (通过 list_status 查询)")
                    passed += 1
                else:
                    print("✗ 返回空数据")
                    failed += 1
            else:
                print("✗ 返回空数据")
                failed += 1
    except Exception as e:
        print(f"✗ 失败: {e}")
        failed += 1

    _print_section("港股: 复权行情 (hk_daily_adj 含市值/股本)")
    try:
        df = pro.hk_daily_adj(ts_code='00700.HK', start_date='20240101', end_date='20240131')
        if df is not None and not df.empty:
            print(df.head())
            print(f"字段: {list(df.columns)}")
            print(f"✓ 成功 ({len(df)} 条)")
            passed += 1
        else:
            print("✗ 返回空数据 (可能积分不足)")
            failed += 1
    except Exception as e:
        print(f"✗ 失败: {e}")
        failed += 1

    _print_section("港股: 财务指标 (hk_fina_indicator, 需 15000 积分)")
    try:
        df = pro.hk_fina_indicator(ts_code='00700.HK')
        if df is not None and not df.empty:
            cols = [c for c in ['ts_code','end_date','basic_eps','roe','roa',
                                'operate_income','operate_income_yoy'] if c in df.columns]
            print(df[cols].head(3) if cols else df.head(3))
            print(f"✓ 成功 ({len(df)} 条)")
            passed += 1
        else:
            print("✗ 返回空数据 (可能积分不足，需 15000 积分)")
            failed += 1
    except Exception as e:
        print(f"✗ 失败 (可能积分不足): {e}")
        failed += 1

    _print_section("说明: Tushare 不提供港股原始财报 (无 hk_income/hk_balancesheet/hk_cashflow)")
    print("  港股财报将自动降级到 AkShare 或 yfinance 获取")
    print("  这是 Tushare API 的已知限制，非程序错误")

    # =====================================================
    # 汇总
    # =====================================================
    print(f"\n{'='*60}")
    print(f"  测试结果: {passed} 通过 / {failed} 失败 / {passed+failed} 总计")
    print(f"{'='*60}")

    if failed > 0:
        print("\n提示: 部分 API 失败可能是因为:")
        print("  1. 第三方镜像未支持该接口")
        print("  2. Token 积分不足，无权访问该接口")
        print("  3. 网络连接问题")


if __name__ == "__main__":
    main()
