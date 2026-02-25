#!/usr/bin/env python3
"""
个股深度分析 CLI 入口
用法: python analyze.py NVDA
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

load_dotenv()

from src.agents.engine import DebateEngine
from src.utils.symbol_resolver import resolve_symbol
from src.utils.secure_key import ensure_api_key, cleanup_api_keys, SensitiveFilter

console = Console()


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(
        description="个股深度分析系统 - 多Agent辩论模型",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python analyze.py NVDA              # 分析英伟达 (代码)
  python analyze.py 美团              # 分析美团 (中文名 → 3690.HK)
  python analyze.py Meituan           # 分析美团 (英文名 → 3690.HK)
  python analyze.py 0700.HK           # 分析腾讯
  python analyze.py 002230.SZ         # 分析科大讯飞
  python analyze.py NVDA -o report    # 保存报告到文件
        """,
    )
    parser.add_argument("symbol", help="股票代码或公司名 (如 NVDA, 美团, Meituan, 0700.HK)")
    parser.add_argument("-o", "--output", help="输出文件路径 (不含扩展名)")
    parser.add_argument("--json", action="store_true", help="输出完整JSON结果")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")
    args = parser.parse_args()

    setup_logging(args.verbose)

    # 日志脱敏过滤器
    logging.getLogger().addFilter(SensitiveFilter())

    # 确保 API Key (环境变量 → .env → 交互输入)
    if not ensure_api_key():
        console.print("[red]未提供 API Key，退出[/red]")
        sys.exit(1)

    # 解析股票代码 (支持公司名)
    symbol = resolve_symbol(args.symbol, config_path=args.config)
    if symbol != args.symbol:
        console.print(f"[dim]符号解析: {args.symbol} → {symbol}[/dim]")

    console.print(Panel(
        f"[bold cyan]个股深度分析系统[/bold cyan]\n"
        f"[dim]多Agent辩论模型 · 基本面深度分析[/dim]\n"
        f"\n目标: [bold yellow]{symbol}[/bold yellow]",
        title="Stock Deep Analysis",
        border_style="cyan",
    ))

    # 创建引擎
    try:
        engine = DebateEngine(config_path=args.config)
    except Exception as e:
        console.print(f"[red]引擎初始化失败: {e}[/red]")
        sys.exit(1)

    # 回调函数: 实时显示进度
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

    # 执行分析
    try:
        result = engine.analyze(symbol, callbacks=callbacks)
    except KeyboardInterrupt:
        console.print("\n[yellow]分析已中断[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]分析过程出错: {e}[/red]")
        if args.verbose:
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

    # 输出报告
    report = DebateEngine.generate_report(result)
    console.print(f"\n{report}")

    # 保存结果
    if args.output:
        # 保存文本报告
        report_path = f"{args.output}.txt"
        Path(report_path).write_text(report, encoding="utf-8")
        console.print(f"\n[green]报告已保存: {report_path}[/green]")

        # 保存JSON
        json_path = f"{args.output}.json"
        # 清理不可序列化的数据
        clean_result = _clean_for_json(result)
        Path(json_path).write_text(
            json.dumps(clean_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        console.print(f"[green]JSON已保存: {json_path}[/green]")

    if args.json:
        clean_result = _clean_for_json(result)
        print(json.dumps(clean_result, ensure_ascii=False, indent=2))

    # 清理 API Key (从环境变量和内存中擦除)
    cleanup_api_keys()


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
