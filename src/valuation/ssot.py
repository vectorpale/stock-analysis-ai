"""
SSOT 引擎 — 统一财务真理层 (Single Source of Truth)

核心原则:
  1. 剥离 LLM 一切计算权限 — 所有财务指标由 Python 硬算
  2. Agent 只能引用 SSOT 输出的数字，禁止自行计算
  3. 格式化输出带正确货币符号 (集成 currency.py)
  4. 包含安全边际、胜率赔率等投资决策硬指标

输出:
  SSOTReport — 纯数字的「财务事实清单」，作为只读输入传给所有 Agent
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

from src.valuation.currency import (
    CurrencyContext,
    detect_currency,
    format_currency,
    validate_currency_consistency,
)
from src.valuation.models import run_valuation, ValuationSummary

logger = logging.getLogger(__name__)


# ======================================================================
# 数据结构
# ======================================================================

@dataclass
class SafetyMargin:
    """安全边际"""
    current_price: float
    fair_value: float
    margin_pct: float           # (fair_value - current_price) / fair_value × 100
    meets_threshold: bool       # 是否达到 30% 安全边际要求
    threshold_pct: float = 30.0


@dataclass
class WinRateOdds:
    """胜率赔率模型"""
    upside_pct: float       # 目标价上涨空间 %
    downside_pct: float     # 止损下跌空间 %
    win_rate: float         # 胜率 (0-1)
    odds_ratio: float       # 赔率 = upside / downside
    expected_value: float   # 期望值 = win_rate × upside - (1-win_rate) × downside
    meets_criteria: bool    # 是否满足 胜率>60% AND 赔率>2:1


@dataclass
class FCFBurnRate:
    """现金消耗速率"""
    cash_and_equivalents: float
    quarterly_fcf: float        # 最近一季度 FCF (负 = 烧钱)
    annual_fcf: float           # TTM FCF
    quarters_of_runway: Optional[float]  # 按当前速率能撑几个季度 (烧钱时)
    fcf_yield: float            # FCF / 市值
    is_burning_cash: bool


@dataclass
class UnitEconomics:
    """单均经济模型"""
    revenue: float
    orders: Optional[float]
    users: Optional[float]
    revenue_per_order: Optional[float]
    revenue_per_user: Optional[float]
    gross_profit_per_order: Optional[float]


@dataclass
class KeyRatios:
    """核心财务比率 (Python 硬算)"""
    pe_ttm: Optional[float]
    pe_forward: Optional[float]
    ps_ttm: Optional[float]
    pb: Optional[float]
    ev_ebitda: Optional[float]
    peg: Optional[float]
    roe: Optional[float]
    roa: Optional[float]
    gross_margin: Optional[float]
    operating_margin: Optional[float]
    net_margin: Optional[float]
    revenue_growth: Optional[float]
    earnings_growth: Optional[float]
    debt_to_equity: Optional[float]
    current_ratio: Optional[float]
    dividend_yield: Optional[float]
    fcf_yield: Optional[float]


@dataclass
class SSOTReport:
    """SSOT 完整输出 — 财务事实清单"""
    symbol: str
    currency_ctx: CurrencyContext
    current_price: float

    # 核心指标 (Python 硬算)
    key_ratios: KeyRatios

    # 估值 (调用 models.py)
    valuation: Optional[ValuationSummary]

    # 安全边际
    safety_margin: Optional[SafetyMargin]

    # 胜率赔率
    win_rate_odds: Optional[WinRateOdds]

    # 现金消耗
    fcf_burn: Optional[FCFBurnRate]

    # 单均经济
    unit_economics: Optional[UnitEconomics]

    # 货币校验警告
    currency_warnings: list[str] = field(default_factory=list)

    # 原始数据摘要 (供追溯)
    data_snapshot: dict = field(default_factory=dict)


# ======================================================================
# 核心计算函数
# ======================================================================

def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """安全除法，避免 ZeroDivisionError"""
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def _safe_float(val) -> Optional[float]:
    """安全转换为 float"""
    if val is None:
        return None
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (ValueError, TypeError):
        return None


def compute_key_ratios(key_metrics: dict, current_price: float) -> KeyRatios:
    """
    从 key_metrics 提取并校验核心财务比率

    不信任 API 直接返回的比率 — 尽可能用原始数据重新计算
    """
    market_cap = _safe_float(key_metrics.get("market_cap"))
    revenue = _safe_float(key_metrics.get("revenue"))
    net_income = _safe_float(key_metrics.get("net_income"))
    shares = _safe_float(key_metrics.get("shares_outstanding"))
    fcf = _safe_float(key_metrics.get("free_cash_flow"))

    # EPS 计算
    eps_ttm = _safe_div(net_income, shares) if net_income and shares else None

    # PE — 用 price / EPS 重算
    pe_ttm = _safe_div(current_price, eps_ttm) if eps_ttm and eps_ttm > 0 else None
    # 如果重算不了，回退到 API 值
    if pe_ttm is None:
        pe_ttm = _safe_float(key_metrics.get("pe_ratio"))

    pe_forward = _safe_float(key_metrics.get("forward_pe"))

    # PS — price × shares / revenue = market_cap / revenue
    ps_ttm = _safe_div(market_cap, revenue) if market_cap and revenue else None
    if ps_ttm is None:
        ps_ttm = _safe_float(key_metrics.get("ps_ratio"))

    # PB
    pb = _safe_float(key_metrics.get("pb_ratio"))

    # EV/EBITDA
    ev_ebitda = _safe_float(key_metrics.get("ev_ebitda"))

    # PEG
    rev_growth = _safe_float(key_metrics.get("revenue_growth"))
    earn_growth = _safe_float(key_metrics.get("earnings_growth"))
    growth_for_peg = earn_growth if earn_growth and earn_growth > 0 else rev_growth
    peg = None
    if pe_ttm and pe_ttm > 0 and growth_for_peg and growth_for_peg > 0:
        peg = round(pe_ttm / (growth_for_peg * 100), 2)

    # FCF Yield
    fcf_yield = _safe_div(fcf, market_cap) if fcf and market_cap else None

    return KeyRatios(
        pe_ttm=round(pe_ttm, 2) if pe_ttm else None,
        pe_forward=round(pe_forward, 2) if pe_forward else None,
        ps_ttm=round(ps_ttm, 2) if ps_ttm else None,
        pb=round(pb, 2) if pb else None,
        ev_ebitda=round(ev_ebitda, 2) if ev_ebitda else None,
        peg=peg,
        roe=_safe_float(key_metrics.get("roe")),
        roa=_safe_float(key_metrics.get("roa")),
        gross_margin=_safe_float(key_metrics.get("gross_margin")),
        operating_margin=_safe_float(key_metrics.get("operating_margin")),
        net_margin=_safe_float(key_metrics.get("profit_margin")),
        revenue_growth=rev_growth,
        earnings_growth=earn_growth,
        debt_to_equity=_safe_float(key_metrics.get("debt_to_equity")),
        current_ratio=_safe_float(key_metrics.get("current_ratio")),
        dividend_yield=_safe_float(key_metrics.get("dividend_yield")),
        fcf_yield=round(fcf_yield, 4) if fcf_yield else None,
    )


def compute_safety_margin(
    current_price: float,
    fair_value: float,
    threshold_pct: float = 30.0,
) -> SafetyMargin:
    """
    安全边际 = (公允价值 - 当前价) / 公允价值 × 100

    巴菲特原则: 要求至少 30% 安全边际才考虑买入
    """
    if fair_value <= 0:
        margin_pct = 0.0
    else:
        margin_pct = round((fair_value - current_price) / fair_value * 100, 1)

    return SafetyMargin(
        current_price=current_price,
        fair_value=fair_value,
        margin_pct=margin_pct,
        meets_threshold=margin_pct >= threshold_pct,
        threshold_pct=threshold_pct,
    )


def compute_win_rate_odds(
    current_price: float,
    target_price: float,
    stop_loss: Optional[float] = None,
    bear_target: Optional[float] = None,
    bull_probability: float = 0.5,
) -> WinRateOdds:
    """
    胜率赔率模型

    赔率 = 上涨空间 / 下跌空间
    期望值 = 胜率 × 上涨 - (1-胜率) × 下跌

    CIO 买入门槛: 胜率 > 60% AND 赔率 > 2:1
    """
    upside_pct = round((target_price / current_price - 1) * 100, 1) if current_price > 0 else 0

    # 下行空间: 优先用止损位，否则用熊市目标
    downside_ref = stop_loss or bear_target or (current_price * 0.7)
    downside_pct = round(abs((current_price - downside_ref) / current_price * 100), 1)

    # 赔率
    odds_ratio = round(upside_pct / downside_pct, 2) if downside_pct > 0 else 0.0

    # 期望值
    ev = round(bull_probability * upside_pct - (1 - bull_probability) * downside_pct, 1)

    # 是否满足买入标准
    meets = bull_probability >= 0.60 and odds_ratio >= 2.0

    return WinRateOdds(
        upside_pct=upside_pct,
        downside_pct=downside_pct,
        win_rate=bull_probability,
        odds_ratio=odds_ratio,
        expected_value=ev,
        meets_criteria=meets,
    )


def compute_fcf_burn_rate(
    key_metrics: dict,
    market_cap: Optional[float] = None,
) -> Optional[FCFBurnRate]:
    """
    现金消耗速率分析

    关键: 如果 FCF 为负 (烧钱)，计算还能撑几个季度
    """
    fcf = _safe_float(key_metrics.get("free_cash_flow"))
    cash = _safe_float(key_metrics.get("cash_and_equivalents"))
    # 如果没有现金数据，尝试其他来源
    if cash is None:
        cash = _safe_float(key_metrics.get("total_cash"))

    if fcf is None:
        return None

    annual_fcf = fcf
    quarterly_fcf = fcf / 4  # 近似

    is_burning = fcf < 0

    # 跑道计算 (仅在烧钱时有意义)
    quarters_runway = None
    if is_burning and cash and cash > 0:
        quarterly_burn = abs(quarterly_fcf)
        if quarterly_burn > 0:
            quarters_runway = round(cash / quarterly_burn, 1)

    mc = market_cap or _safe_float(key_metrics.get("market_cap")) or 0
    fcf_yield = round(fcf / mc, 4) if mc > 0 else 0.0

    return FCFBurnRate(
        cash_and_equivalents=cash or 0,
        quarterly_fcf=round(quarterly_fcf, 0),
        annual_fcf=round(annual_fcf, 0),
        quarters_of_runway=quarters_runway,
        fcf_yield=fcf_yield,
        is_burning_cash=is_burning,
    )


def compute_unit_economics(
    key_metrics: dict,
    extra_data: Optional[dict] = None,
) -> Optional[UnitEconomics]:
    """
    单均经济模型 (UE)

    适用于平台型公司: 外卖、电商、打车等
    """
    revenue = _safe_float(key_metrics.get("revenue"))
    if revenue is None:
        return None

    extra = extra_data or {}
    orders = _safe_float(extra.get("total_orders"))
    users = _safe_float(extra.get("active_users")) or _safe_float(extra.get("monthly_active_users"))

    gross_margin = _safe_float(key_metrics.get("gross_margin"))

    rev_per_order = _safe_div(revenue, orders) if orders else None
    rev_per_user = _safe_div(revenue, users) if users else None
    gp_per_order = None
    if rev_per_order and gross_margin:
        gp_per_order = round(rev_per_order * gross_margin, 2)

    return UnitEconomics(
        revenue=revenue,
        orders=orders,
        users=users,
        revenue_per_order=round(rev_per_order, 2) if rev_per_order else None,
        revenue_per_user=round(rev_per_user, 2) if rev_per_user else None,
        gross_profit_per_order=gp_per_order,
    )


# ======================================================================
# 主入口: 一次性计算所有 SSOT 指标
# ======================================================================

def compute_ssot(
    symbol: str,
    key_metrics: dict,
    financials: dict,
    competitive_comparison: dict,
    current_price: Optional[float] = None,
    extra_data: Optional[dict] = None,
) -> SSOTReport:
    """
    SSOT 主入口 — 一次性预计算所有财务指标

    Args:
        symbol: 股票代码 (如 "BIDU", "3690.HK")
        key_metrics: 来自 DataFetcher 的关键指标
        financials: 来自 DataFetcher 的财报数据
        competitive_comparison: 竞品对比表
        current_price: 当前价格 (可覆盖 key_metrics 中的价格)
        extra_data: 额外数据 (如订单量、用户数)

    Returns:
        SSOTReport — 完整的财务事实清单
    """
    # 1. 货币检测
    currency_ctx = detect_currency(symbol)
    tc = currency_ctx.trading_currency
    rc = currency_ctx.reporting_currency
    logger.info(f"SSOT [{symbol}] 货币: 交易={tc}, 报告={rc}")

    # 2. 确定当前价格
    price = current_price
    if price is None:
        for price_key in ("current_price", "50d_avg", "target_price", "200d_avg"):
            v = _safe_float(key_metrics.get(price_key))
            if v and v > 0:
                price = v
                break
    if price is None:
        hi = _safe_float(key_metrics.get("52w_high"))
        lo = _safe_float(key_metrics.get("52w_low"))
        if hi and lo:
            price = (hi + lo) / 2

    if price is None or price <= 0:
        logger.error(f"SSOT [{symbol}] 无法确定当前价格")
        price = 0

    # 3. 核心比率计算
    key_ratios = compute_key_ratios(key_metrics, price)

    # 4. 估值 (调用已有 models.py)
    valuation = None
    try:
        valuation = run_valuation(key_metrics, financials, competitive_comparison)
    except Exception as e:
        logger.warning(f"SSOT [{symbol}] 估值计算失败: {e}")

    # 5. 安全边际
    safety_margin = None
    if valuation and valuation.fair_value > 0:
        safety_margin = compute_safety_margin(price, valuation.fair_value)

    # 6. 胜率赔率 (初步估算 — CIO 可覆盖)
    win_rate_odds = None
    if valuation:
        win_rate_odds = compute_win_rate_odds(
            current_price=price,
            target_price=valuation.target_price_base,
            bear_target=valuation.target_price_bear,
            bull_probability=0.5,  # 默认50%，CIO 决策时会调整
        )

    # 7. 现金消耗
    fcf_burn = compute_fcf_burn_rate(key_metrics)

    # 8. 单均经济
    unit_econ = compute_unit_economics(key_metrics, extra_data)

    # 9. 货币校验
    data_pack = {"key_metrics": key_metrics, "financials": financials}
    currency_warnings = validate_currency_consistency(data_pack, currency_ctx)

    # 10. 数据快照 (供追溯)
    snapshot = {
        "price": price,
        "market_cap": _safe_float(key_metrics.get("market_cap")),
        "revenue": _safe_float(key_metrics.get("revenue")),
        "net_income": _safe_float(key_metrics.get("net_income")),
        "fcf": _safe_float(key_metrics.get("free_cash_flow")),
        "shares": _safe_float(key_metrics.get("shares_outstanding")),
        "currency_trading": tc,
        "currency_reporting": rc,
    }

    report = SSOTReport(
        symbol=symbol,
        currency_ctx=currency_ctx,
        current_price=price,
        key_ratios=key_ratios,
        valuation=valuation,
        safety_margin=safety_margin,
        win_rate_odds=win_rate_odds,
        fcf_burn=fcf_burn,
        unit_economics=unit_econ,
        currency_warnings=currency_warnings,
        data_snapshot=snapshot,
    )

    logger.info(f"SSOT [{symbol}] 计算完成: "
                f"PE={key_ratios.pe_ttm}, "
                f"安全边际={safety_margin.margin_pct if safety_margin else 'N/A'}%, "
                f"赔率={win_rate_odds.odds_ratio if win_rate_odds else 'N/A'}")

    return report


# ======================================================================
# 格式化: 生成纯数字「财务事实清单」
# ======================================================================

def format_ssot_report(report: SSOTReport) -> str:
    """
    将 SSOT 结果格式化为文本 — 传给所有 Agent 作为只读数据

    格式设计:
    - 纯数字 + 货币符号，无叙事
    - 明确标注哪些是「硬事实」(从财报数据计算)
    - 明确标注哪些是「模型输出」(从估值模型计算)
    """
    ctx = report.currency_ctx
    tc = ctx.trading_currency
    rc = ctx.reporting_currency
    ts = ctx.trading_symbol
    rs = ctx.reporting_symbol

    lines = []
    lines.append("=" * 60)
    lines.append(f"  SSOT 财务事实清单 — {report.symbol}")
    lines.append(f"  交易货币: {tc} ({ts})  |  报告货币: {rc} ({rs})")
    lines.append("=" * 60)

    # --- 1. 当前价格 ---
    lines.append(f"\n当前价格: {format_currency(report.current_price, tc)}")

    # --- 2. 核心比率 ---
    kr = report.key_ratios
    lines.append("\n--- 核心比率 (Python 硬算) ---")

    ratio_items = [
        ("PE(TTM)", kr.pe_ttm, "x"),
        ("PE(Forward)", kr.pe_forward, "x"),
        ("PS(TTM)", kr.ps_ttm, "x"),
        ("PB", kr.pb, "x"),
        ("EV/EBITDA", kr.ev_ebitda, "x"),
        ("PEG", kr.peg, ""),
    ]
    for label, val, suffix in ratio_items:
        if val is not None:
            lines.append(f"  {label}: {val:.2f}{suffix}")

    pct_items = [
        ("ROE", kr.roe),
        ("ROA", kr.roa),
        ("毛利率", kr.gross_margin),
        ("营业利润率", kr.operating_margin),
        ("净利率", kr.net_margin),
        ("营收增速", kr.revenue_growth),
        ("盈利增速", kr.earnings_growth),
        ("股息率", kr.dividend_yield),
        ("FCF Yield", kr.fcf_yield),
    ]
    for label, val in pct_items:
        if val is not None:
            lines.append(f"  {label}: {val*100:.1f}%")

    other_items = [
        ("负债/权益", kr.debt_to_equity),
        ("流动比率", kr.current_ratio),
    ]
    for label, val in other_items:
        if val is not None:
            lines.append(f"  {label}: {val:.2f}")

    # --- 3. 估值模型输出 ---
    lines.append("\n--- 估值模型输出 ---")
    if report.valuation:
        v = report.valuation
        lines.append(f"  估值等级: {v.valuation_grade}")
        lines.append(f"  公允价值: {format_currency(v.fair_value, tc)} "
                     f"({v.upside_pct:+.1f}%)")
        lines.append(f"  牛市目标: {format_currency(v.target_price_bull, tc)}")
        lines.append(f"  基准目标: {format_currency(v.target_price_base, tc)}")
        lines.append(f"  熊市目标: {format_currency(v.target_price_bear, tc)}")
        lines.append(f"  主要方法: {v.primary_method}")
        lines.append(f"  使用方法数: {len(v.methods_used)}")
        for m in v.methods_used:
            lines.append(f"    [{m.method}] 目标: {format_currency(m.target_price, tc)} "
                         f"({m.upside_pct:+.1f}%, 权重={m.weight})")
    else:
        lines.append("  [估值数据不足，无法计算]")

    # --- 4. 安全边际 ---
    lines.append("\n--- 安全边际 ---")
    if report.safety_margin:
        sm = report.safety_margin
        status = "PASS" if sm.meets_threshold else "FAIL"
        lines.append(f"  安全边际: {sm.margin_pct:+.1f}% "
                     f"(门槛: {sm.threshold_pct}%) → {status}")
        lines.append(f"  当前价: {format_currency(sm.current_price, tc)} "
                     f"→ 公允: {format_currency(sm.fair_value, tc)}")
    else:
        lines.append("  [无法计算安全边际]")

    # --- 5. 胜率赔率 ---
    lines.append("\n--- 胜率赔率模型 ---")
    if report.win_rate_odds:
        wo = report.win_rate_odds
        status = "满足买入条件" if wo.meets_criteria else "未达买入门槛"
        lines.append(f"  上涨空间: {wo.upside_pct:+.1f}%")
        lines.append(f"  下跌风险: -{wo.downside_pct:.1f}%")
        lines.append(f"  胜率: {wo.win_rate*100:.0f}%  (门槛: 60%)")
        lines.append(f"  赔率: {wo.odds_ratio:.2f}:1  (门槛: 2.0:1)")
        lines.append(f"  期望值: {wo.expected_value:+.1f}%")
        lines.append(f"  结论: {status}")
    else:
        lines.append("  [无法计算胜率赔率]")

    # --- 6. 现金消耗 ---
    lines.append("\n--- 现金流分析 ---")
    if report.fcf_burn:
        fb = report.fcf_burn
        lines.append(f"  年度FCF: {format_currency(fb.annual_fcf, rc, 'large')}")
        lines.append(f"  季度FCF: {format_currency(fb.quarterly_fcf, rc, 'large')}")
        if fb.cash_and_equivalents > 0:
            lines.append(f"  现金储备: {format_currency(fb.cash_and_equivalents, rc, 'large')}")
        if fb.is_burning_cash:
            lines.append(f"  ⚠ 正在烧钱!")
            if fb.quarters_of_runway:
                lines.append(f"  剩余跑道: {fb.quarters_of_runway:.1f} 个季度")
        else:
            lines.append(f"  FCF 为正 (健康)")
        if fb.fcf_yield:
            lines.append(f"  FCF Yield: {fb.fcf_yield*100:.1f}%")
    else:
        lines.append("  [无FCF数据]")

    # --- 7. 单均经济 ---
    if report.unit_economics and (report.unit_economics.orders or report.unit_economics.users):
        ue = report.unit_economics
        lines.append("\n--- 单均经济模型 ---")
        lines.append(f"  总营收: {format_currency(ue.revenue, rc, 'large')}")
        if ue.orders:
            lines.append(f"  总订单: {ue.orders/1e9:.2f}B" if ue.orders > 1e9
                         else f"  总订单: {ue.orders/1e6:.0f}M")
        if ue.users:
            lines.append(f"  活跃用户: {ue.users/1e6:.0f}M")
        if ue.revenue_per_order:
            lines.append(f"  单均收入: {format_currency(ue.revenue_per_order, rc)}")
        if ue.revenue_per_user:
            lines.append(f"  用户ARPU: {format_currency(ue.revenue_per_user, rc)}")
        if ue.gross_profit_per_order:
            lines.append(f"  单均毛利: {format_currency(ue.gross_profit_per_order, rc)}")

    # --- 8. 货币校验 ---
    if report.currency_warnings:
        lines.append("\n--- ⚠ 货币校验警告 ---")
        for w in report.currency_warnings:
            lines.append(f"  ⚠ {w}")

    lines.append("\n" + "=" * 60)
    lines.append("以上数据由 SSOT 引擎预计算 (Python)。")
    lines.append("Agent 只能引用以上数字，禁止自行计算估值或财务比率。")
    lines.append("=" * 60)

    return "\n".join(lines)


def format_ssot_for_agent(report: SSOTReport, agent_role: str) -> str:
    """
    按 Agent 角色过滤 SSOT 数据

    不同 Agent 只能看到其「允许讨论」范围内的数据:
    - moat_analyst: 全量指标 (但禁止宏观)
    - reflexivity_analyst: 仅估值 + 胜率赔率 + 安全边际
    - forensic_accountant: 全量财务指标 + FCF + UE
    - red_team: 全量指标 (用于攻击)
    - macro_strategist: 仅估值等级 + 汇率
    - sotp_valuator: 全量估值 + 安全边际 + 胜率赔率
    """
    # 所有角色都看完整 SSOT (由 Agent prompt 控制讨论边界)
    # 这样设计是因为 Fact-Checker 需要完整数据来校验
    return format_ssot_report(report)


def get_ssot_summary_dict(report: SSOTReport) -> dict:
    """
    将 SSOT 输出转为 dict，供 JSON 序列化和 CIO 决策使用
    """
    result = {
        "symbol": report.symbol,
        "current_price": report.current_price,
        "trading_currency": report.currency_ctx.trading_currency,
        "reporting_currency": report.currency_ctx.reporting_currency,
    }

    # 核心比率
    kr = report.key_ratios
    result["key_ratios"] = {
        "pe_ttm": kr.pe_ttm,
        "pe_forward": kr.pe_forward,
        "ps_ttm": kr.ps_ttm,
        "pb": kr.pb,
        "ev_ebitda": kr.ev_ebitda,
        "peg": kr.peg,
        "roe": kr.roe,
        "gross_margin": kr.gross_margin,
        "net_margin": kr.net_margin,
        "revenue_growth": kr.revenue_growth,
        "fcf_yield": kr.fcf_yield,
    }

    # 估值
    if report.valuation:
        v = report.valuation
        result["valuation"] = {
            "grade": v.valuation_grade,
            "fair_value": v.fair_value,
            "target_bull": v.target_price_bull,
            "target_base": v.target_price_base,
            "target_bear": v.target_price_bear,
            "upside_pct": v.upside_pct,
            "primary_method": v.primary_method,
        }

    # 安全边际
    if report.safety_margin:
        sm = report.safety_margin
        result["safety_margin"] = {
            "margin_pct": sm.margin_pct,
            "meets_threshold": sm.meets_threshold,
        }

    # 胜率赔率
    if report.win_rate_odds:
        wo = report.win_rate_odds
        result["win_rate_odds"] = {
            "upside_pct": wo.upside_pct,
            "downside_pct": wo.downside_pct,
            "win_rate": wo.win_rate,
            "odds_ratio": wo.odds_ratio,
            "expected_value": wo.expected_value,
            "meets_criteria": wo.meets_criteria,
        }

    # FCF
    if report.fcf_burn:
        fb = report.fcf_burn
        result["fcf_analysis"] = {
            "annual_fcf": fb.annual_fcf,
            "is_burning_cash": fb.is_burning_cash,
            "quarters_runway": fb.quarters_of_runway,
            "fcf_yield": fb.fcf_yield,
        }

    # 警告
    if report.currency_warnings:
        result["currency_warnings"] = report.currency_warnings

    return result
