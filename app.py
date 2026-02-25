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

    # API Key
    api_key = st.text_input(
        "Anthropic API Key",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        type="password",
    )
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key

    st.divider()

    # 股票输入
    symbol = st.text_input(
        "股票代码",
        value="NVDA",
        help="支持美股(NVDA)、港股(0700.HK)、A股(002230.SZ)",
    )

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
    2. **独立分析** — 6位AI分析师从不同角度独立分析（防止锚定偏差）
    3. **多轮辩论** — 分析师相互质疑、回应、修正观点（收敛检测自动终止）
    4. **风控审核** — 风控官审核并可行使一票否决权
    5. **CIO决策** — 首席投资官综合各方观点做出最终判断

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
