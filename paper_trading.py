"""
模拟盘仪表盘 - Streamlit Web UI
用法: streamlit run paper_trading.py
"""

import json
import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.data.fetcher import DataFetcher
from src.paper_trading.portfolio import PortfolioManager
from src.paper_trading.trader import Trader
from src.utils.symbol_resolver import resolve_symbol

# 默认自选股
DEFAULT_WATCHLIST = ["LI", "3690.HK", "JOBY", "1810.HK", "GOOGL"]

st.set_page_config(
    page_title="模拟盘 - 多Agent辩论",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .metric-positive { color: #00d4aa; }
    .metric-negative { color: #ff6b6b; }
</style>
""", unsafe_allow_html=True)

# ==================================================================
# 初始化
# ==================================================================
portfolio = PortfolioManager()
trader = Trader(portfolio)
fetcher = DataFetcher(cache_hours=1)

# 确保有自选股
if not portfolio.get_watchlist():
    portfolio.set_watchlist(DEFAULT_WATCHLIST)


def get_prices(symbols: list[str]) -> dict[str, float]:
    """获取当前价格"""
    prices = {}
    for sym in symbols:
        try:
            df = fetcher.fetch_price_data(sym, period="5d")
            if df is not None and not df.empty:
                prices[sym] = round(float(df["Close"].iloc[-1]), 2)
        except Exception:
            pass
    return prices


# ==================================================================
# 侧边栏
# ==================================================================
with st.sidebar:
    st.title("模拟盘系统")
    st.caption("多Agent辩论 · 自动交易验证")
    st.divider()

    # API Key (仅存于内存，不落盘)
    has_env_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if has_env_key:
        st.success("API Key 已从环境变量加载")
        api_key = os.environ["ANTHROPIC_API_KEY"]
    else:
        api_key = st.text_input(
            "Anthropic API Key",
            type="password",
            help="Key 仅在本次会话中使用，不会保存到文件",
        )
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key

    st.divider()

    # 自选股管理
    st.subheader("自选股管理")
    current_watchlist = portfolio.get_watchlist()
    watchlist_text = st.text_area(
        "股票代码或公司名 (每行一个)",
        value="\n".join(current_watchlist),
        height=150,
        help="支持代码(NVDA)或公司名(美团, Meituan)",
    )
    if st.button("更新自选股"):
        raw_list = [s.strip() for s in watchlist_text.strip().split("\n") if s.strip()]
        new_list = [resolve_symbol(s) for s in raw_list]
        portfolio.set_watchlist(new_list)
        resolved_info = [f"{r}←{o}" for o, r in zip(raw_list, new_list) if o != r]
        msg = f"已更新: {new_list}"
        if resolved_info:
            msg += f" (解析: {', '.join(resolved_info)})"
        st.success(msg)
        st.rerun()

    st.divider()

    # 操作按钮
    st.subheader("操作")
    col_a, col_b = st.columns(2)
    with col_a:
        run_analysis = st.button("运行分析", type="primary", use_container_width=True,
                                 disabled=not api_key)
    with col_b:
        snapshot_btn = st.button("更新快照", use_container_width=True)

    dry_run = st.checkbox("试运行 (不实际交易)", value=False)

    st.divider()
    if st.button("重置模拟盘", type="secondary"):
        st.session_state["confirm_reset"] = True

    if st.session_state.get("confirm_reset"):
        st.warning("确认要重置所有数据？")
        c1, c2 = st.columns(2)
        if c1.button("确认重置"):
            portfolio.reset()
            st.session_state["confirm_reset"] = False
            st.success("已重置")
            st.rerun()
        if c2.button("取消"):
            st.session_state["confirm_reset"] = False
            st.rerun()

    st.divider()
    st.caption("免责声明: 模拟盘仅供验证分析系统有效性，不构成投资建议。")

# ==================================================================
# 获取数据
# ==================================================================
watchlist = portfolio.get_watchlist()
prices = get_prices(watchlist)
portfolio_data = portfolio.get_portfolio_value(prices)

# ==================================================================
# 主区域 - 标签页
# ==================================================================
tab_overview, tab_positions, tab_trades, tab_analysis, tab_performance = st.tabs(
    ["组合总览", "持仓明细", "交易记录", "分析日志", "绩效统计"]
)

# ==================================================================
# Tab 1: 组合总览
# ==================================================================
with tab_overview:
    st.header("组合总览")

    # 核心指标卡片
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("组合总值", f"${portfolio_data['total_value']:,.2f}")
    col2.metric(
        "总PnL",
        f"${portfolio_data['total_pnl']:+,.2f}",
        delta=f"{portfolio_data['total_return_pct']:+.2f}%",
    )
    col3.metric("可用现金", f"${portfolio_data['cash']:,.2f}")
    col4.metric("持仓市值", f"${portfolio_data['positions_value']:,.2f}")

    # 净值曲线
    snapshots = portfolio.get_snapshots()
    if snapshots:
        st.subheader("净值曲线")
        df_snap = pd.DataFrame(snapshots)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_snap["date"],
            y=df_snap["total_value"],
            mode="lines+markers",
            name="组合净值",
            line=dict(color="#00d4aa", width=2),
            fill="tozeroy",
            fillcolor="rgba(0, 212, 170, 0.1)",
        ))

        # 初始资金线
        initial = float(portfolio._get_meta("initial_capital") or 1_000_000)
        fig.add_hline(
            y=initial, line_dash="dash", line_color="gray",
            annotation_text=f"初始资金 ${initial:,.0f}",
        )

        fig.update_layout(
            template="plotly_dark",
            height=400,
            yaxis_title="组合价值 ($)",
            xaxis_title="日期",
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

        # 每日PnL柱状图
        if len(df_snap) > 1:
            fig_pnl = go.Figure()
            colors = ["#00d4aa" if x >= 0 else "#ff6b6b" for x in df_snap["daily_pnl"]]
            fig_pnl.add_trace(go.Bar(
                x=df_snap["date"],
                y=df_snap["daily_pnl"],
                marker_color=colors,
                name="日PnL",
            ))
            fig_pnl.update_layout(
                template="plotly_dark",
                height=250,
                yaxis_title="日PnL ($)",
                title="每日盈亏",
            )
            st.plotly_chart(fig_pnl, use_container_width=True)
    else:
        st.info("暂无净值数据。点击「更新快照」或运行每日分析后生成。")

    # 持仓分布饼图
    if portfolio_data["positions"]:
        st.subheader("持仓分布")
        labels = [p["symbol"] for p in portfolio_data["positions"]] + ["现金"]
        values = [p["market_value"] for p in portfolio_data["positions"]] + [portfolio_data["cash"]]

        fig_pie = go.Figure(go.Pie(
            labels=labels,
            values=values,
            hole=0.4,
            marker=dict(colors=["#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A", "#19D3F3"]),
        ))
        fig_pie.update_layout(template="plotly_dark", height=350, title="资产配置")
        st.plotly_chart(fig_pie, use_container_width=True)

# ==================================================================
# Tab 2: 持仓明细
# ==================================================================
with tab_positions:
    st.header("当前持仓")

    if portfolio_data["positions"]:
        for pos in portfolio_data["positions"]:
            pnl_color = "green" if pos["unrealized_pnl"] >= 0 else "red"
            with st.container():
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric(pos["symbol"], f"${pos['current_price']:.2f}")
                c2.metric("持仓", f"{pos['shares']:.0f} 股")
                c3.metric("成本", f"${pos['avg_cost']:.2f}")
                c4.metric("市值", f"${pos['market_value']:,.2f}")
                c5.metric(
                    "浮动盈亏",
                    f"${pos['unrealized_pnl']:+,.2f}",
                    delta=f"{pos['pnl_pct']:+.1f}%",
                )
                st.divider()
    else:
        st.info("暂无持仓")

    # 行情速览
    st.subheader("自选股行情")
    if prices:
        price_data = []
        for sym in watchlist:
            p = prices.get(sym)
            pos = next((x for x in portfolio_data["positions"] if x["symbol"] == sym), None)
            price_data.append({
                "股票": sym,
                "当前价": f"${p:.2f}" if p else "N/A",
                "持仓": f"{pos['shares']:.0f}" if pos else "0",
                "市值": f"${pos['market_value']:,.0f}" if pos else "-",
                "盈亏%": f"{pos['pnl_pct']:+.1f}%" if pos else "-",
            })
        st.dataframe(pd.DataFrame(price_data), use_container_width=True, hide_index=True)

# ==================================================================
# Tab 3: 交易记录
# ==================================================================
with tab_trades:
    st.header("交易记录")
    trades = portfolio.get_trade_history(limit=100)
    if trades:
        df_trades = pd.DataFrame(trades)
        display_cols = ["timestamp", "symbol", "action", "shares", "price", "total_amount", "reason"]
        available_cols = [c for c in display_cols if c in df_trades.columns]
        df_display = df_trades[available_cols].copy()
        df_display.columns = ["时间", "股票", "操作", "数量", "价格", "金额", "原因"][:len(available_cols)]
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.info("暂无交易记录")

# ==================================================================
# Tab 4: 分析日志
# ==================================================================
with tab_analysis:
    st.header("分析日志")

    filter_sym = st.selectbox("筛选股票", ["全部"] + watchlist)
    sym_filter = None if filter_sym == "全部" else filter_sym
    logs = portfolio.get_analysis_log(symbol=sym_filter, limit=50)

    if logs:
        for log in logs:
            rec = log.get("recommendation", "N/A")
            conf = log.get("confidence", 0)
            rec_color = {
                "STRONG_BUY": "🟢", "BUY": "🟢",
                "HOLD": "🟡",
                "SELL": "🔴", "STRONG_SELL": "🔴",
            }.get(rec, "⚪")

            header = (
                f"{rec_color} {log['symbol']} | {rec} (信心 {conf}%) | "
                f"分析价 ${log.get('price_at_analysis', 0) or 0:.2f} | "
                f"{log['timestamp'][:16]}"
            )

            # 回测：分析时价格 vs 当前价格
            analysis_price = log.get("price_at_analysis", 0) or 0
            current = prices.get(log["symbol"], 0)
            if analysis_price > 0 and current > 0:
                actual_return = (current / analysis_price - 1) * 100
                header += f" | 实际: {actual_return:+.1f}%"

            with st.expander(header):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("建议", rec)
                c2.metric("目标价", f"${log.get('target_price', 0) or 0:.2f}")
                c3.metric("止损位", f"${log.get('stop_loss', 0) or 0:.2f}")
                c4.metric("执行动作", log.get("action_taken", "N/A"))

                st.markdown(f"**摘要:** {log.get('executive_summary', 'N/A')}")

                if analysis_price > 0 and current > 0:
                    direction_correct = (
                        (rec in ("STRONG_BUY", "BUY") and current > analysis_price) or
                        (rec in ("SELL", "STRONG_SELL") and current < analysis_price) or
                        (rec == "HOLD")
                    )
                    if direction_correct:
                        st.success(f"方向正确: 分析价 ${analysis_price:.2f} → 当前 ${current:.2f} ({actual_return:+.1f}%)")
                    else:
                        st.error(f"方向错误: 分析价 ${analysis_price:.2f} → 当前 ${current:.2f} ({actual_return:+.1f}%)")
    else:
        st.info("暂无分析记录。点击「运行分析」开始。")

# ==================================================================
# Tab 5: 绩效统计
# ==================================================================
with tab_performance:
    st.header("绩效统计")

    stats = portfolio.get_performance_stats()
    if stats["total_trades"] > 0:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("总交易数", stats["total_trades"])
        c2.metric("胜率", f"{stats['win_rate']:.1f}%")
        c3.metric("盈亏比", f"{stats['profit_factor']:.2f}")
        c4.metric("最大回撤", f"{stats['max_drawdown_pct']:.1f}%")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("盈利次数", stats["wins"])
        c6.metric("亏损次数", stats["losses"])
        c7.metric("平均盈利", f"${stats['avg_win']:,.2f}")
        c8.metric("平均亏损", f"${stats['avg_loss']:,.2f}")

        st.metric("已实现总PnL", f"${stats['total_realized_pnl']:+,.2f}")

        # 信号准确率
        st.divider()
        st.subheader("信号准确率")
        logs = portfolio.get_analysis_log(limit=200)
        if logs:
            correct = 0
            total_checked = 0
            for log in logs:
                ap = log.get("price_at_analysis", 0) or 0
                cur = prices.get(log["symbol"], 0)
                rec = log.get("recommendation", "HOLD")
                if ap > 0 and cur > 0 and rec != "HOLD":
                    total_checked += 1
                    if (rec in ("STRONG_BUY", "BUY") and cur > ap) or \
                       (rec in ("SELL", "STRONG_SELL") and cur < ap):
                        correct += 1

            if total_checked > 0:
                acc = correct / total_checked * 100
                st.metric(
                    "方向准确率",
                    f"{acc:.1f}% ({correct}/{total_checked})",
                )
            else:
                st.info("需要更多数据才能计算准确率")
    else:
        st.info("暂无已平仓交易，绩效指标将在有卖出记录后计算。")

# ==================================================================
# 分析执行（在侧边栏按钮触发后运行）
# ==================================================================
if snapshot_btn:
    with st.spinner("正在更新快照..."):
        portfolio.take_snapshot(prices)
    st.success("快照已更新")
    st.rerun()

if run_analysis and api_key:
    from src.agents.engine import DebateEngine

    st.divider()
    st.header("正在执行分析...")

    progress_bar = st.progress(0)
    status_text = st.empty()
    results_container = st.container()

    engine = DebateEngine()
    total = len(watchlist)

    for i, symbol in enumerate(watchlist):
        status_text.markdown(f"**正在分析 {symbol} ({i+1}/{total})...**")
        progress_bar.progress((i) / total)

        try:
            with st.spinner(f"分析 {symbol}..."):
                result = engine.analyze(symbol)

            cio = result.get("phases", {}).get("cio_decision", {})
            rec = cio.get("recommendation", "HOLD")
            conf = cio.get("confidence", 0)
            price = cio.get("price_at_analysis", 0)

            with results_container:
                st.markdown(f"### {symbol}: **{rec}** (信心 {conf}%)")

                if dry_run:
                    st.info(f"[试运行] 不执行交易")
                    action_taken = f"DRY_RUN: {rec}"
                else:
                    trade_result = trader.execute_signal(
                        symbol=symbol,
                        analysis_result=result,
                        current_price=price,
                    )
                    action_taken = trade_result.get("action_taken", "NONE")
                    if trade_result.get("success"):
                        if trade_result.get("action") == "BUY":
                            st.success(
                                f"买入 {trade_result['shares']}股 @ ${price:.2f}, "
                                f"金额 ${trade_result['total']:,.2f}"
                            )
                        elif trade_result.get("action") == "SELL":
                            st.warning(
                                f"卖出 {trade_result['shares']}股 @ ${price:.2f}, "
                                f"PnL ${trade_result.get('pnl', 0):+,.2f}"
                            )
                    else:
                        st.info(f"动作: {action_taken} - {trade_result.get('reason', '')}")

                portfolio.log_analysis(symbol, result, action_taken=action_taken)

        except Exception as e:
            with results_container:
                st.error(f"{symbol} 分析失败: {e}")

    progress_bar.progress(100)
    status_text.markdown("**全部分析完成!**")

    # 更新快照
    prices = get_prices(watchlist)
    portfolio.take_snapshot(prices)

    # token 用量
    usage = engine.get_token_usage()
    if usage["calls"] > 0:
        with results_container:
            st.divider()
            st.markdown(
                f"**API 用量:** {usage['calls']}次调用, "
                f"{usage['input_tokens'] + usage['output_tokens']:,} tokens"
            )
