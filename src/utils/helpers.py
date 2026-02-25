"""
工具函数模块
"""

import json
import re
import logging
import statistics
from typing import Optional

logger = logging.getLogger(__name__)


def parse_json_response(text: str) -> Optional[dict]:
    """从 LLM 回复中提取 JSON"""
    if not text:
        return None

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 中的内容
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试提取 { ... } 中的内容
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning(f"JSON 解析失败，原文前200字: {text[:200]}")
    return None


def compute_convergence_score(agent_results: list[dict]) -> float:
    """计算辩论收敛分数 (0-1)，1 = 完全一致"""
    if not agent_results:
        return 0.0

    positions = [r.get("position", 0) for r in agent_results]
    if len(positions) < 2:
        return 1.0

    # 基于标准差计算收敛度
    std = statistics.stdev(positions)
    max_std = 100.0  # 理论最大标准差 (全部在 -100 到 +100 之间)
    convergence = max(0.0, 1.0 - std / max_std)
    return round(convergence, 3)


def compute_consensus_label(agent_results: list[dict]) -> str:
    """计算共识标签"""
    if not agent_results:
        return "无数据"

    positions = [r.get("position", 0) for r in agent_results]
    avg = statistics.mean(positions)
    std = statistics.stdev(positions) if len(positions) > 1 else 0

    # 判断共识级别
    if std < 15:
        if avg > 30:
            return "高度一致看多"
        elif avg < -30:
            return "高度一致看空"
        else:
            return "高度一致中性"
    elif std < 35:
        if avg > 20:
            return "偏多，有分歧"
        elif avg < -20:
            return "偏空，有分歧"
        else:
            return "中性，有分歧"
    else:
        return "意见严重分歧"


def weighted_score_aggregation(
    agent_results: list[dict],
    agent_weights: dict,
    agent_keys: list[str],
) -> float:
    """加权得分聚合"""
    if not agent_results or not agent_keys:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0
    for key, result in zip(agent_keys, agent_results):
        weight = agent_weights.get(key, 1.0)
        position = result.get("position", 0)
        confidence = result.get("confidence", 50) / 100.0
        adjusted_weight = weight * confidence
        weighted_sum += position * adjusted_weight
        total_weight += adjusted_weight

    if total_weight == 0:
        return 0.0
    return round(weighted_sum / total_weight, 2)


def format_metrics_text(metrics: dict) -> str:
    """格式化关键指标为文本"""
    if not metrics:
        return "无数据"

    lines = []
    field_labels = {
        "company_name": "公司名称",
        "sector": "行业板块",
        "industry": "细分行业",
        "market_cap": "市值",
        "pe_ratio": "市盈率(TTM)",
        "forward_pe": "前瞻市盈率",
        "peg_ratio": "PEG",
        "pb_ratio": "市净率",
        "ps_ratio": "市销率",
        "ev_ebitda": "EV/EBITDA",
        "profit_margin": "净利率",
        "operating_margin": "营业利润率",
        "gross_margin": "毛利率",
        "roe": "ROE",
        "roa": "ROA",
        "revenue_growth": "营收增速",
        "earnings_growth": "盈利增速",
        "revenue": "总营收",
        "debt_to_equity": "负债权益比",
        "current_ratio": "流动比率",
        "free_cash_flow": "自由现金流",
        "dividend_yield": "股息率",
        "beta": "Beta",
        "52w_high": "52周最高",
        "52w_low": "52周最低",
        "analyst_rating": "分析师评级",
        "target_price": "目标价",
    }

    for key, label in field_labels.items():
        val = metrics.get(key)
        if val is None:
            continue
        if key == "market_cap":
            if val >= 1e12:
                lines.append(f"- {label}: ${val/1e12:.2f}T")
            elif val >= 1e9:
                lines.append(f"- {label}: ${val/1e9:.2f}B")
            else:
                lines.append(f"- {label}: ${val/1e6:.0f}M")
        elif key in ("revenue", "free_cash_flow"):
            if abs(val) >= 1e9:
                lines.append(f"- {label}: ${val/1e9:.2f}B")
            else:
                lines.append(f"- {label}: ${val/1e6:.0f}M")
        elif key in ("profit_margin", "operating_margin", "gross_margin",
                      "roe", "roa", "revenue_growth", "earnings_growth", "dividend_yield"):
            lines.append(f"- {label}: {val*100:.1f}%")
        elif isinstance(val, float):
            lines.append(f"- {label}: {val:.2f}")
        else:
            lines.append(f"- {label}: {val}")

    return "\n".join(lines) if lines else "无数据"


def format_financials_text(financials: dict) -> str:
    """格式化财务报表数据为文本摘要"""
    if not financials:
        return "无财务数据"

    lines = []

    # 提取最近几个季度的关键数据
    for report_name, report_data in financials.items():
        if report_data is None or report_name.startswith("_"):
            continue
        lines.append(f"\n#### {report_name}")
        if isinstance(report_data, dict):
            periods = list(report_data.keys())[:4]  # 最近4期
            for period in periods:
                period_data = report_data[period]
                if isinstance(period_data, dict):
                    items = list(period_data.items())[:10]  # 每期最多10项
                    lines.append(f"\n**{period}**")
                    for item_name, item_val in items:
                        if isinstance(item_val, (int, float)):
                            if abs(item_val) >= 1e9:
                                lines.append(f"  - {item_name}: ${item_val/1e9:.2f}B")
                            elif abs(item_val) >= 1e6:
                                lines.append(f"  - {item_name}: ${item_val/1e6:.0f}M")
                            else:
                                lines.append(f"  - {item_name}: {item_val:,.0f}")

    text = "\n".join(lines)
    # 限制长度避免 prompt 过长
    if len(text) > 5000:
        text = text[:5000] + "\n... (数据已截断)"
    return text


def format_technical_text(indicators: dict) -> str:
    """格式化技术指标为文本"""
    if not indicators:
        return "无技术指标"

    lines = []
    label_map = {
        "current_price": "当前价格",
        "sma_20": "20日均线",
        "sma_50": "50日均线",
        "sma_200": "200日均线",
        "rsi_14": "RSI(14)",
        "macd": "MACD",
        "macd_signal": "MACD信号线",
        "macd_histogram": "MACD柱",
        "bb_upper": "布林上轨",
        "bb_middle": "布林中轨",
        "bb_lower": "布林下轨",
        "atr_14": "ATR(14)",
        "adx": "ADX",
        "pct_from_52w_high": "距52周高点",
        "pct_from_52w_low": "距52周低点",
        "volume_ratio": "量比(5日/20日)",
    }

    for key, label in label_map.items():
        val = indicators.get(key)
        if val is None:
            continue
        if key.startswith("pct_"):
            lines.append(f"- {label}: {val:+.1f}%")
        elif isinstance(val, float):
            lines.append(f"- {label}: {val:.2f}")
        else:
            lines.append(f"- {label}: {val}")

    return "\n".join(lines) if lines else "无技术指标"
