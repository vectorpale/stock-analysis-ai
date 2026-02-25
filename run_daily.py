#!/usr/bin/env python3
"""
模拟盘每日执行脚本
用法:
  python run_daily.py                      # 分析所有自选股并执行交易
  python run_daily.py --symbols NVDA GOOGL  # 指定股票
  python run_daily.py --snapshot-only       # 仅更新快照，不分析
  python run_daily.py --dry-run             # 试运行，不实际交易

定时任务 (cron):
  # 每天美东 7:30 (开盘前) 运行
  30 11 * * 1-5 cd /path/to/project && python run_daily.py >> logs/daily.log 2>&1
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.agents.engine import DebateEngine
from src.data.fetcher import DataFetcher
from src.paper_trading.portfolio import PortfolioManager
from src.paper_trading.trader import Trader
from src.utils.secure_key import ensure_api_key, cleanup_api_keys, SensitiveFilter

# 默认自选股列表
DEFAULT_WATCHLIST = ["LI", "3690.HK", "JOBY", "1810.HK", "GOOGL"]

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_DIR / f"daily_{datetime.now().strftime('%Y%m%d')}.log"),
        ],
    )


def get_current_prices(symbols: list[str]) -> dict[str, float]:
    """获取所有股票当前价格"""
    fetcher = DataFetcher(cache_hours=1)
    prices = {}
    for sym in symbols:
        try:
            indicators = fetcher.compute_technical_indicators(
                fetcher.fetch_price_data(sym, period="5d")
            )
            price = indicators.get("current_price")
            if price:
                prices[sym] = price
        except Exception as e:
            logging.warning(f"获取 {sym} 价格失败: {e}")
    return prices


def run_analysis_and_trade(
    symbols: list[str],
    portfolio: PortfolioManager,
    trader: Trader,
    engine: DebateEngine,
    dry_run: bool = False,
):
    """对每只股票执行分析并交易"""
    logger = logging.getLogger("daily")

    for symbol in symbols:
        logger.info(f"\n{'='*60}")
        logger.info(f"开始分析: {symbol}")
        logger.info(f"{'='*60}")

        try:
            result = engine.analyze(symbol)
        except Exception as e:
            logger.error(f"{symbol} 分析失败: {e}")
            continue

        cio = result.get("phases", {}).get("cio_decision", {})
        rec = cio.get("recommendation", "HOLD")
        conf = cio.get("confidence", 0)
        price = cio.get("price_at_analysis", 0)

        logger.info(f"{symbol} 分析完成: {rec} (信心 {conf}%), 分析价 ${price}")

        if dry_run:
            logger.info(f"[DRY RUN] 跳过交易执行")
            action_taken = f"DRY_RUN: {rec}"
        else:
            # 执行交易
            trade_result = trader.execute_signal(
                symbol=symbol,
                analysis_result=result,
                current_price=price,
            )
            action_taken = trade_result.get("action_taken", "NONE")
            logger.info(f"{symbol} 交易结果: {action_taken}")
            if trade_result.get("shares"):
                logger.info(f"  {trade_result.get('action', '')} {trade_result['shares']}股 @ ${price:.2f}")

        # 记录分析日志
        portfolio.log_analysis(symbol, result, action_taken=action_taken)


def main():
    parser = argparse.ArgumentParser(description="模拟盘每日执行")
    parser.add_argument(
        "--symbols", nargs="+", default=None,
        help="股票代码列表 (默认使用自选股)",
    )
    parser.add_argument("--snapshot-only", action="store_true", help="仅更新净值快照")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不实际交易")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    parser.add_argument(
        "--init-watchlist", action="store_true",
        help="初始化自选股列表后退出",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger("daily")
    logging.getLogger().addFilter(SensitiveFilter())

    # 确保 API Key (快照模式不需要 LLM)
    if not args.snapshot_only and not args.init_watchlist:
        if not ensure_api_key():
            logger.error("未提供 API Key，退出")
            sys.exit(1)

    # 初始化组合
    portfolio = PortfolioManager()
    trader = Trader(portfolio)

    # 初始化自选股
    if args.init_watchlist:
        portfolio.set_watchlist(DEFAULT_WATCHLIST)
        logger.info(f"自选股已初始化: {DEFAULT_WATCHLIST}")
        return

    # 确定股票列表
    symbols = args.symbols
    if not symbols:
        symbols = portfolio.get_watchlist()
    if not symbols:
        portfolio.set_watchlist(DEFAULT_WATCHLIST)
        symbols = DEFAULT_WATCHLIST
        logger.info(f"首次运行，初始化自选股: {symbols}")

    logger.info(f"日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info(f"目标股票: {symbols}")

    # 获取当前价格
    logger.info("获取当前价格...")
    prices = get_current_prices(symbols)
    for sym, price in prices.items():
        logger.info(f"  {sym}: ${price:.2f}")

    if not prices:
        logger.error("无法获取任何价格数据，退出")
        sys.exit(1)

    # 快照模式
    if args.snapshot_only:
        logger.info("仅更新快照...")
        # 检查止损/止盈
        stop_results = trader.check_all_stops(prices)
        for sr in stop_results:
            logger.info(f"  自动交易: {sr}")
        portfolio.take_snapshot(prices)
        _print_summary(portfolio, prices)
        return

    # 完整分析 + 交易
    try:
        engine = DebateEngine(config_path=args.config)
    except Exception as e:
        logger.error(f"引擎初始化失败: {e}")
        sys.exit(1)

    run_analysis_and_trade(symbols, portfolio, trader, engine, dry_run=args.dry_run)

    # 更新快照
    prices = get_current_prices(symbols)  # 重新获取最新价格
    portfolio.take_snapshot(prices)

    _print_summary(portfolio, prices)
    cleanup_api_keys()
    logger.info("每日任务完成")


def _print_summary(portfolio: PortfolioManager, prices: dict):
    """打印组合摘要"""
    logger = logging.getLogger("daily")
    pv = portfolio.get_portfolio_value(prices)
    logger.info(f"\n{'='*40}")
    logger.info(f"组合摘要")
    logger.info(f"{'='*40}")
    logger.info(f"总值: ${pv['total_value']:,.2f}")
    logger.info(f"现金: ${pv['cash']:,.2f}")
    logger.info(f"持仓: ${pv['positions_value']:,.2f}")
    logger.info(f"总PnL: ${pv['total_pnl']:+,.2f} ({pv['total_return_pct']:+.2f}%)")

    for pos in pv["positions"]:
        logger.info(
            f"  {pos['symbol']}: {pos['shares']}股 @ ${pos['avg_cost']:.2f} "
            f"→ ${pos['current_price']:.2f} ({pos['pnl_pct']:+.1f}%)"
        )


if __name__ == "__main__":
    main()
