"""
个股深度分析系统 - Streamlit Web UI
用法: streamlit run app.py
"""

import json
import os
import time
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="个股深度分析 - 多Agent辩论",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ================================================================
# 样式
# ================================================================
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .metric-card {
        background: #1a1d23;
        border-radius: 8px;
        padding: 16px;
        border: 1px solid #2d3139;
    }
    .bull { color: #00d4aa; }
    .bear { color: #ff6b6b; }
    .neutral { color: #ffa726; }
</style>
""", unsafe_allow_html=True)

# ================================================================
# 侧边栏
# ================================================================
with st.sidebar:
    st.title("个股深度分析系统")
    st.caption("多Agent辩论模型 · 基本面深度分析")
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

    # 股票输入
    symbol_input = st.text_input(
        "股票代码或公司名",
        value="NVDA",
        help="支持代码(NVDA, 0700.HK)或公司名(美团, Meituan, 英伟达)",
    )
    from src.utils.symbol_resolver import resolve_symbol
    symbol = resolve_symbol(symbol_input)
    if symbol != symbol_input:
        st.caption(f"{symbol_input} → **{symbol}**")

    st.divider()

    # 分析参数
    st.subheader("分析参数")
    max_rounds = st.slider("最大辩论轮数", 2, 5, 3)
    convergence = st.slider("收敛阈值", 0.5, 1.0, 0.8, 0.05)

    st.divider()

    # 开始分析
    analyze_btn = st.button(
        "开始深度分析",
        type="primary",
        use_container_width=True,
        disabled=not api_key,
    )

    if not api_key:
        st.warning("请先输入 Anthropic API Key")

    st.divider()
    st.caption("免责声明: AI分析仅供参考，不构成投资建议。")

# ================================================================
# 主区域
# ================================================================
st.title(f"个股深度分析: {symbol}")

if analyze_btn and api_key:
    from src.agents.engine import DebateEngine

    # 动态修改配置
    import yaml
    with open("config/config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config["debate"]["max_rounds"] = max_rounds
    config["debate"]["convergence_threshold"] = convergence

    # 写回临时配置
    tmp_config = "/tmp/stock_analysis_config.yaml"
    with open(tmp_config, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)

    engine = DebateEngine(config_path=tmp_config)

    # 进度容器
    progress_container = st.container()
    status_text = st.empty()
    progress_bar = st.progress(0)

    phase_progress = {
        "数据收集": 10,
        "独立分析": 30,
        "多轮辩论": 60,
        "风控审核": 80,
        "CIO 决策": 90,
        "分析完成": 100,
    }

    log_messages = []

    def on_phase(phase):
        pct = phase_progress.get(phase, 0)
        progress_bar.progress(pct)
        status_text.markdown(f"**{phase}...**")

    def on_message(msg):
        log_messages.append(msg)
        with progress_container:
            st.text(msg)

    callbacks = {
        "on_phase": on_phase,
        "on_message": on_message,
    }

    try:
        with st.spinner("正在进行深度分析，请耐心等待..."):
            result = engine.analyze(symbol, callbacks=callbacks)

        progress_bar.progress(100)
        status_text.markdown("**分析完成!**")

        # ============================================================
        # 显示结果
        # ============================================================
        st.divider()

        cio = result.get("phases", {}).get("cio_decision", {})
        risk = result.get("phases", {}).get("risk_committee", {})
        summary = result.get("data_summary", {})

        # ---- CIO 决策卡片 ----
        st.header("CIO 投资决策")
        rec = cio.get("recommendation", "HOLD")
        conf = cio.get("confidence", 0)

        color_map = {
            "STRONG_BUY": "green", "BUY": "green",
            "HOLD": "orange",
            "SELL": "red", "STRONG_SELL": "red",
        }
        rec_color = color_map.get(rec, "gray")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("建议", rec)
        col2.metric("信心", f"{conf}%")
        col3.metric("目标价", f"${cio.get('target_price', 'N/A')}")
        col4.metric("止损位", f"${cio.get('stop_loss', 'N/A')}")

        col5, col6, col7, col8 = st.columns(4)
        col5.metric("时间维度", cio.get("time_horizon", "N/A"))
        col6.metric("建议仓位", f"{cio.get('position_size_pct', 'N/A')}%")
        col7.metric("风险等级", risk.get("risk_level", "N/A"))
        col8.metric("风控结论", risk.get("verdict", "N/A"))

        # 投资结论
        st.subheader("投资结论")
        st.info(cio.get("executive_summary", "无"))

        # 多空论点
        col_bull, col_bear = st.columns(2)
        with col_bull:
            st.subheader("核心多头论点")
            for arg in cio.get("key_bull_arguments", []):
                st.success(f"+ {arg}")

        with col_bear:
            st.subheader("核心空头论点")
            for arg in cio.get("key_bear_arguments", []):
                st.error(f"- {arg}")

        # 决定性因素
        decisive = cio.get("decisive_factors", [])
        if decisive:
            st.subheader("决定性因素")
            for d in decisive:
                st.warning(f"* {d}")

        # ---- 各分析师立场 ----
        st.divider()
        st.header("各分析师最终立场")

        final_positions = result.get("phases", {}).get("final_positions", {})
        if final_positions:
            # 可视化图表
            import plotly.graph_objects as go

            agent_names = []
            positions = []
            confidences = []
            colors = []

            for agent_key, pos in final_positions.items():
                name = f"{pos.get('agent_name', '')} ({pos.get('agent_title', '')})"
                agent_names.append(name)
                p = pos.get("position", 0)
                positions.append(p)
                confidences.append(pos.get("confidence", 0))
                colors.append("#00d4aa" if p > 0 else "#ff6b6b" if p < 0 else "#ffa726")

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=agent_names,
                y=positions,
                marker_color=colors,
                text=[f"{p:+d}" for p in positions],
                textposition="outside",
            ))
            fig.update_layout(
                title="分析师立场 (-100=极空 ← → +100=极多)",
                yaxis_range=[-110, 110],
                template="plotly_dark",
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)

            # 详细信息
            for agent_key, pos in final_positions.items():
                with st.expander(f"{pos.get('agent_name', '')} - {pos.get('agent_title', '')} "
                                 f"(立场: {pos.get('position', 0):+d}, 信心: {pos.get('confidence', 0)}%)"):
                    st.markdown(pos.get("analysis", ""))
                    st.markdown("**核心论点:** " + ", ".join(pos.get("key_points", [])))
                    st.markdown("**风险:** " + ", ".join(pos.get("risks", [])))
                    st.markdown("**催化剂:** " + ", ".join(pos.get("catalysts", [])))

        # ---- 辩论统计 ----
        st.divider()
        col_stats1, col_stats2 = st.columns(2)
        with col_stats1:
            st.metric("加权综合得分", f"{result.get('weighted_score', 0):+.1f}")
        with col_stats2:
            st.metric("共识水平", result.get("consensus", "N/A"))

        # ---- 风控详情 ----
        st.divider()
        st.header("风控委员会详情")
        risk_cols = st.columns(3)
        risk_cols[0].metric("审核结论", risk.get("verdict", "N/A"))
        risk_cols[1].metric("风险等级", risk.get("risk_level", "N/A"))
        risk_cols[2].metric("最大仓位", f"{risk.get('max_position_pct', 'N/A')}%")

        conditions = risk.get("conditions", [])
        if conditions:
            st.subheader("风控条件")
            for c in conditions:
                st.warning(c)

        monitoring = risk.get("monitoring_points", [])
        if monitoring:
            st.subheader("持续监控指标")
            for m in monitoring:
                st.info(m)

        # ---- 共识 vs 反共识 ----
        cvc = cio.get("consensus_vs_contrarian", {})
        contrarian = result.get("phases", {}).get("contrarian_analysis", {})
        challenge = result.get("phases", {}).get("cio_challenge", {})

        if cvc or contrarian:
            st.divider()
            st.header("共识观点 vs 反共识观点")

            if cvc:
                col_cons, col_contra = st.columns(2)
                with col_cons:
                    cons_prob = cvc.get("consensus_probability", "?")
                    st.metric("共识观点", f"概率 {cons_prob}%")
                    st.info(cvc.get("consensus_view", "N/A"))
                with col_contra:
                    contra_prob = cvc.get("contrarian_probability", "?")
                    st.metric("反共识观点", f"概率 {contra_prob}%")
                    st.warning(cvc.get("contrarian_view", "N/A"))

                drivers = cvc.get("key_price_drivers", [])
                if drivers:
                    st.subheader("核心股价驱动变量")
                    for d in drivers:
                        st.markdown(f"- **{d}**")

                if cvc.get("what_consensus_is_missing"):
                    st.subheader("共识盲点")
                    st.warning(cvc["what_consensus_is_missing"])

                if cvc.get("cio_independent_judgment"):
                    st.subheader("CIO 独立判断")
                    st.info(cvc["cio_independent_judgment"])

            if contrarian.get("contrarian_thesis"):
                with st.expander("Devil's Advocate 反共识详细论证"):
                    st.markdown(f"**反共识立场:** {contrarian.get('contrarian_position', 'N/A')}")
                    st.markdown(f"**核心论点:** {contrarian.get('contrarian_thesis', 'N/A')}")
                    st.markdown(f"**概率评估:** {contrarian.get('probability_estimate', '?')}%")
                    st.markdown(f"**核心价格驱动:** {contrarian.get('key_price_driver', 'N/A')}")

                    evidence = contrarian.get("contrarian_evidence", [])
                    if evidence:
                        st.markdown("**证据:**")
                        for e in evidence[:3]:
                            st.markdown(f"- {e.get('point', '')}: {e.get('data_support', '')}")
                            st.caption(f"共识盲点: {e.get('consensus_blind_spot', '')}")

                    if contrarian.get("historical_parallel"):
                        st.markdown(f"**历史类比:** {contrarian['historical_parallel']}")
                    if contrarian.get("trigger_scenario"):
                        st.markdown(f"**验证场景:** {contrarian['trigger_scenario']}")

            if challenge.get("challenges"):
                with st.expander("CIO 拷问记录"):
                    st.markdown(f"**共识核心假设:** {challenge.get('core_assumption', 'N/A')}")
                    for i, ch in enumerate(challenge["challenges"], 1):
                        st.markdown(f"**Q{i}: {ch.get('question', '')}**")
                        st.caption(f"针对: {ch.get('target', '全体')} | "
                                   f"关键性: {ch.get('why_critical', '')}")

        # ---- 催化剂与风险 ----
        st.divider()
        col_cat, col_risk = st.columns(2)
        with col_cat:
            st.header("关注催化剂")
            for c in cio.get("catalysts", []):
                st.success(c)
        with col_risk:
            st.header("持续监控风险")
            for r in cio.get("risk_factors", []):
                st.error(r)

        # ---- 配对交易策略 ----
        st.divider()
        st.header("配对交易策略 (Long/Short)")
        pair = result.get("phases", {}).get("pair_trade", {})
        if pair.get("has_recommendation"):
            st.subheader(pair.get("strategy_name", ""))
            st.caption(f"类型: {pair.get('pair_type', 'N/A')}")
            st.info(pair.get("thesis", ""))

            col_long, col_short = st.columns(2)
            long_leg = pair.get("long_leg", {})
            short_leg = pair.get("short_leg", {})
            with col_long:
                st.metric("LONG", f"{long_leg.get('symbol', '?')} ({long_leg.get('weight', '')})")
                st.success(long_leg.get("rationale", ""))
            with col_short:
                st.metric("SHORT", f"{short_leg.get('symbol', '?')} ({short_leg.get('weight', '')})")
                st.error(short_leg.get("rationale", ""))

            execution = pair.get("execution", {})
            if execution:
                with st.expander("执行计划"):
                    exec_cols = st.columns(3)
                    exec_cols[0].markdown(f"**入场时机:** {execution.get('entry_timing', 'N/A')}")
                    exec_cols[1].markdown(f"**持有周期:** {execution.get('holding_period', 'N/A')}")
                    exec_cols[2].markdown(f"**配对仓位:** {execution.get('position_sizing', 'N/A')}")
                    st.markdown(f"**目标收益:** {execution.get('profit_target', 'N/A')}")
                    st.markdown(f"**止损条件:** {execution.get('stop_loss', 'N/A')}")

            risk_notes = pair.get("risk_notes", [])
            if risk_notes:
                with st.expander("配对风险"):
                    for rn in risk_notes:
                        st.warning(rn)
                    if pair.get("invalidation"):
                        st.error(f"失效条件: {pair['invalidation']}")
        else:
            st.warning(f"无配对推荐: {pair.get('no_recommendation_reason', '未给出原因')}")

        # ---- 下载报告 ----
        st.divider()
        report_text = DebateEngine.generate_report(result)
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                "下载文本报告",
                data=report_text,
                file_name=f"{symbol}_analysis_{datetime.now().strftime('%Y%m%d')}.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with col_dl2:
            clean_json = json.dumps(
                result, ensure_ascii=False, indent=2, default=str
            )
            st.download_button(
                "下载JSON数据",
                data=clean_json,
                file_name=f"{symbol}_analysis_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json",
                use_container_width=True,
            )

    except Exception as e:
        st.error(f"分析出错: {e}")
        import traceback
        st.code(traceback.format_exc())

else:
    # 未开始分析时显示说明
    st.info("请在左侧输入股票代码和 API Key，然后点击「开始深度分析」")

    st.markdown("""
    ### 系统架构

    本系统采用**多Agent辩论模型**进行个股深度分析，核心流程:

    1. **数据收集** — 获取个股财务数据、竞品对比、产业链信息、新闻资讯
    2. **独立分析** — 5位AI分析师从不同角度独立分析（防止锚定偏差）
    3. **多轮辩论** — 分析师相互质疑、回应、修正观点（收敛检测自动终止）
    4. **CIO拷问** — CIO挑战共识观点，分析师逐一回应（打破群体思维）
    5. **反共识分析** — Devil's Advocate构建最有力的反共识论证
    6. **风控审核** — 风控官审核并可行使一票否决权
    7. **CIO决策** — 综合共识与反共识观点，输出独立投资判断
    8. **配对交易** — 基于分析结论设计Long/Short配对策略

    ### 分析师团队

    | 角色 | 专注领域 |
    |------|----------|
    | Alex (多头分析师) | 成长动力、竞争优势、上行催化剂 |
    | Morgan (空头分析师) | 风险识别、竞争威胁、估值泡沫 |
    | Sarah (行业分析师) | 行业动态、竞品对比、产业链 |
    | David (财务分析师) | 财报解读、盈利质量、估值模型 |
    | Kai (宏观策略师) | 宏观环境、政策影响、资金流向 |
    | Chris (风控官) | 风险评估、仓位建议、一票否决 |

    ### 数据来源

    - **行情数据**: yfinance / AkShare / Tushare / BaoStock (多源降级)
    - **财务报表**: 利润表、资产负债表、现金流量表 (年度+季度)
    - **竞品对比**: 同行业核心指标横向对比
    - **产业链**: 上下游公司经营数据交叉验证
    - **新闻资讯**: 公司新闻、业绩预期、分析师评级
    """)
