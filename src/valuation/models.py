"""
估值建模模块 - 基于利润表的多方法量化估值

针对不同行业/股票自动匹配最合适的估值方法:
  - PE 估值法 (成熟盈利企业)
  - PS 估值法 (高增长/亏损企业)
  - PEG 估值法 (成长股)
  - EV/EBITDA 估值法 (重资产/高杠杆)
  - DCF 简化估值 (基于 FCF 或 Owner Earnings)
  - 股息折现 (高股息价值股)

每种方法输出: 目标价 + 关键假设 + 敏感性分析
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ValuationResult:
    """单一估值方法的结果"""
    method: str                    # 估值方法名
    target_price: float            # 目标价
    upside_pct: float              # 上涨空间 %
    weight: float                  # 该方法的适用权重 (0-1)
    assumptions: dict              # 核心假设
    sensitivity: dict              # 敏感性: {参数名: {low: price, mid: price, high: price}}
    reasoning: str                 # 估值逻辑简述


@dataclass
class ValuationSummary:
    """综合估值结果"""
    current_price: float
    fair_value: float                       # 加权公允价值
    target_price_bull: float                # 牛市目标价
    target_price_base: float                # 基准目标价
    target_price_bear: float                # 熊市目标价
    upside_pct: float                       # 基准上涨空间
    methods_used: list[ValuationResult]     # 各方法详情
    primary_method: str                     # 主要估值方法
    valuation_grade: str                    # 估值等级: CHEAP / FAIR / EXPENSIVE / BUBBLE
    methodology_note: str                   # 方法论说明


# ====================================================================
# 行业-估值方法匹配规则
# ====================================================================

INDUSTRY_VALUATION_RULES = {
    # 科技成长股: PE + PS + PEG + DCF
    "tech_growth": {
        "keywords": ["software", "cloud", "saas", "ai", "semiconductor", "internet",
                      "technology", "it services", "electronic", "social media"],
        "methods": ["pe_relative", "ps_relative", "peg", "dcf_simplified"],
        "primary": "pe_relative",
        "pe_peer_range": (15, 60),
        "ps_peer_range": (3, 25),
    },
    # 消费/零售: PE + PEG
    "consumer": {
        "keywords": ["consumer", "retail", "food", "beverage", "apparel",
                      "restaurant", "e-commerce", "entertainment"],
        "methods": ["pe_relative", "peg", "ev_ebitda"],
        "primary": "pe_relative",
        "pe_peer_range": (12, 35),
    },
    # 金融: PB + PE + 股息
    "financial": {
        "keywords": ["bank", "insurance", "financial", "capital markets",
                      "asset management", "fintech"],
        "methods": ["pb_relative", "pe_relative", "dividend_discount"],
        "primary": "pb_relative",
        "pb_peer_range": (0.5, 3.0),
    },
    # 医药/生物: PS + EV/EBITDA (亏损用PS，盈利用PE)
    "healthcare": {
        "keywords": ["pharma", "biotech", "medical", "healthcare", "drug",
                      "therapeutics", "diagnostics"],
        "methods": ["ps_relative", "pe_relative", "ev_ebitda"],
        "primary": "ps_relative",
        "ps_peer_range": (3, 30),
    },
    # 重资产/工业: EV/EBITDA + PE
    "industrial": {
        "keywords": ["industrial", "manufacturing", "auto", "aerospace",
                      "defense", "machinery", "energy", "mining", "oil",
                      "utility", "utilities", "infrastructure"],
        "methods": ["ev_ebitda", "pe_relative", "dcf_simplified"],
        "primary": "ev_ebitda",
        "ev_ebitda_peer_range": (5, 15),
    },
    # 房地产: PB + 股息
    "real_estate": {
        "keywords": ["real estate", "reit", "property"],
        "methods": ["pb_relative", "dividend_discount", "pe_relative"],
        "primary": "pb_relative",
        "pb_peer_range": (0.3, 2.0),
    },
    # 默认
    "default": {
        "methods": ["pe_relative", "ev_ebitda", "dcf_simplified"],
        "primary": "pe_relative",
        "pe_peer_range": (10, 30),
    },
}


def _match_industry(sector: str, industry: str) -> dict:
    """根据行业分类匹配估值规则"""
    text = f"{sector} {industry}".lower()
    for rule_key, rule in INDUSTRY_VALUATION_RULES.items():
        if rule_key == "default":
            continue
        keywords = rule.get("keywords", [])
        if any(kw in text for kw in keywords):
            return rule
    return INDUSTRY_VALUATION_RULES["default"]


# ====================================================================
# 估值方法实现
# ====================================================================

def pe_relative_valuation(
    current_price: float,
    eps_ttm: float,
    forward_pe: Optional[float],
    peer_pe_avg: Optional[float],
    revenue_growth: Optional[float],
    industry_pe_range: tuple = (10, 30),
) -> Optional[ValuationResult]:
    """
    PE 相对估值法

    逻辑: 基于当前 EPS × 合理 PE 倍数
    合理PE = 综合考虑: 同行平均PE / 历史PE / 增长率隐含PE
    """
    if not eps_ttm or eps_ttm <= 0:
        return None
    if not current_price or current_price <= 0:
        return None

    current_pe = current_price / eps_ttm
    pe_low, pe_high = industry_pe_range

    # 计算合理 PE
    pe_estimates = []

    # 1. 同行平均PE
    if peer_pe_avg and peer_pe_avg > 0:
        pe_estimates.append(("同行平均", peer_pe_avg))

    # 2. Forward PE (分析师一致预期)
    if forward_pe and forward_pe > 0:
        pe_estimates.append(("远期PE", forward_pe))

    # 3. 增长率隐含 PE (Peter Lynch: 合理PE ≈ 增速×100)
    if revenue_growth and revenue_growth > 0:
        growth_implied_pe = min(revenue_growth * 100, pe_high * 1.2)
        growth_implied_pe = max(growth_implied_pe, pe_low * 0.8)
        pe_estimates.append(("增速隐含", round(growth_implied_pe, 1)))

    if not pe_estimates:
        # 无参考，取行业中位
        fair_pe = (pe_low + pe_high) / 2
        pe_estimates.append(("行业中位", fair_pe))

    # 加权平均
    fair_pe = sum(v for _, v in pe_estimates) / len(pe_estimates)
    fair_pe = max(pe_low * 0.8, min(fair_pe, pe_high * 1.2))  # 限制在合理范围

    target = round(eps_ttm * fair_pe, 2)
    upside = round((target / current_price - 1) * 100, 1)

    # 敏感性
    target_low = round(eps_ttm * (fair_pe * 0.8), 2)
    target_high = round(eps_ttm * (fair_pe * 1.2), 2)

    assumptions = {
        "当前EPS(TTM)": round(eps_ttm, 2),
        "当前PE": round(current_pe, 1),
        "合理PE": round(fair_pe, 1),
        "PE参考来源": {k: round(v, 1) for k, v in pe_estimates},
        "行业PE区间": f"{pe_low}-{pe_high}x",
    }

    return ValuationResult(
        method="PE相对估值",
        target_price=target,
        upside_pct=upside,
        weight=1.0,
        assumptions=assumptions,
        sensitivity={
            "PE倍数": {"保守": target_low, "基准": target, "乐观": target_high},
        },
        reasoning=f"基于EPS ${eps_ttm:.2f} × 合理PE {fair_pe:.1f}x = ${target:.2f}",
    )


def ps_relative_valuation(
    current_price: float,
    revenue_per_share: float,
    peer_ps_avg: Optional[float],
    revenue_growth: Optional[float],
    profit_margin: Optional[float],
    industry_ps_range: tuple = (3, 20),
) -> Optional[ValuationResult]:
    """
    PS 相对估值法

    适用: 高增长/尚未盈利企业
    逻辑: Revenue per Share × 合理 PS 倍数
    PS倍数与增速、利润率正相关
    """
    if not revenue_per_share or revenue_per_share <= 0:
        return None
    if not current_price or current_price <= 0:
        return None

    current_ps = current_price / revenue_per_share
    ps_low, ps_high = industry_ps_range

    # 合理 PS 估算
    ps_estimates = []

    if peer_ps_avg and peer_ps_avg > 0:
        ps_estimates.append(("同行平均", peer_ps_avg))

    # 增速+利润率隐含PS (Rule of 40: growth + margin > 40% 值得溢价)
    if revenue_growth is not None and profit_margin is not None:
        rule_of_40 = (revenue_growth or 0) * 100 + (profit_margin or 0) * 100
        # Rule of 40 映射到 PS 倍数
        if rule_of_40 > 60:
            implied_ps = ps_high * 0.9
        elif rule_of_40 > 40:
            implied_ps = (ps_low + ps_high) / 2
        elif rule_of_40 > 20:
            implied_ps = ps_low * 1.2
        else:
            implied_ps = ps_low
        ps_estimates.append(("Rule of 40 隐含", round(implied_ps, 1)))
    elif revenue_growth and revenue_growth > 0.3:
        ps_estimates.append(("高增长溢价", (ps_low + ps_high) / 2))

    if not ps_estimates:
        fair_ps = (ps_low + ps_high) / 2
    else:
        fair_ps = sum(v for _, v in ps_estimates) / len(ps_estimates)

    fair_ps = max(ps_low * 0.7, min(fair_ps, ps_high * 1.2))

    target = round(revenue_per_share * fair_ps, 2)
    upside = round((target / current_price - 1) * 100, 1)

    target_low = round(revenue_per_share * (fair_ps * 0.75), 2)
    target_high = round(revenue_per_share * (fair_ps * 1.25), 2)

    assumptions = {
        "每股营收": round(revenue_per_share, 2),
        "当前PS": round(current_ps, 1),
        "合理PS": round(fair_ps, 1),
        "营收增速": f"{revenue_growth*100:.1f}%" if revenue_growth else "N/A",
        "净利率": f"{profit_margin*100:.1f}%" if profit_margin else "N/A",
        "PS参考来源": {k: round(v, 1) for k, v in ps_estimates},
    }

    return ValuationResult(
        method="PS相对估值",
        target_price=target,
        upside_pct=upside,
        weight=0.8,
        assumptions=assumptions,
        sensitivity={
            "PS倍数": {"保守": target_low, "基准": target, "乐观": target_high},
        },
        reasoning=f"基于每股营收 ${revenue_per_share:.2f} × 合理PS {fair_ps:.1f}x = ${target:.2f}",
    )


def peg_valuation(
    current_price: float,
    eps_ttm: float,
    earnings_growth: Optional[float],
    revenue_growth: Optional[float],
) -> Optional[ValuationResult]:
    """
    PEG 估值法

    Peter Lynch 法则: PEG = PE / (增长率×100)
    PEG < 1 低估, PEG = 1 合理, PEG > 2 高估
    合理 PE = 增长率 × 100 × 合理PEG(1.0-1.5)
    """
    if not eps_ttm or eps_ttm <= 0 or not current_price:
        return None

    # 使用 earnings growth 优先，否则用 revenue growth
    growth = earnings_growth if earnings_growth and earnings_growth > 0 else revenue_growth
    if not growth or growth <= 0:
        return None

    growth_pct = growth * 100  # 转为百分比数字
    if growth_pct < 5:
        return None  # 增速太低不适用PEG

    current_pe = current_price / eps_ttm
    current_peg = current_pe / growth_pct if growth_pct > 0 else None

    # 合理 PE = growth_pct × 合理PEG
    # 成熟企业 PEG ≈ 1.0, 高增长 PEG 可到 1.5
    if growth_pct > 30:
        fair_peg = 1.2
    elif growth_pct > 15:
        fair_peg = 1.0
    else:
        fair_peg = 0.9

    fair_pe = growth_pct * fair_peg
    fair_pe = max(8, min(fair_pe, 80))  # 合理范围限制

    target = round(eps_ttm * fair_pe, 2)
    upside = round((target / current_price - 1) * 100, 1)

    target_low = round(eps_ttm * growth_pct * 0.8, 2)
    target_high = round(eps_ttm * growth_pct * 1.5, 2)

    assumptions = {
        "EPS(TTM)": round(eps_ttm, 2),
        "增长率": f"{growth_pct:.1f}%",
        "当前PE": round(current_pe, 1),
        "当前PEG": round(current_peg, 2) if current_peg else "N/A",
        "合理PEG": fair_peg,
        "合理PE": round(fair_pe, 1),
    }

    return ValuationResult(
        method="PEG估值",
        target_price=target,
        upside_pct=upside,
        weight=0.7,
        assumptions=assumptions,
        sensitivity={
            "PEG倍数": {"PEG=0.8": target_low, f"PEG={fair_peg}": target, "PEG=1.5": target_high},
        },
        reasoning=f"增长率{growth_pct:.0f}% × PEG {fair_peg} → 合理PE {fair_pe:.0f}x → ${target:.2f}",
    )


def ev_ebitda_valuation(
    current_price: float,
    ev_ebitda: float,
    enterprise_value: float,
    market_cap: float,
    peer_ev_ebitda_avg: Optional[float],
    revenue_growth: Optional[float],
    industry_ev_ebitda_range: tuple = (5, 20),
) -> Optional[ValuationResult]:
    """
    EV/EBITDA 估值法

    适用: 重资产、高杠杆、跨国比较
    逻辑: 合理EV = EBITDA × 合理倍数, 扣除净债务得到股权价值
    """
    if not ev_ebitda or ev_ebitda <= 0 or not enterprise_value or not market_cap:
        return None
    if not current_price or current_price <= 0:
        return None

    ebitda = enterprise_value / ev_ebitda  # 反推 EBITDA
    net_debt = enterprise_value - market_cap  # 净债务

    ev_low, ev_high = industry_ev_ebitda_range

    # 合理 EV/EBITDA
    ev_estimates = []
    if peer_ev_ebitda_avg and peer_ev_ebitda_avg > 0:
        ev_estimates.append(("同行平均", peer_ev_ebitda_avg))

    if revenue_growth and revenue_growth > 0.15:
        ev_estimates.append(("增长溢价", ev_high * 0.8))
    elif revenue_growth and revenue_growth < 0:
        ev_estimates.append(("衰退折价", ev_low * 1.1))

    if not ev_estimates:
        fair_ev_multiple = (ev_low + ev_high) / 2
    else:
        fair_ev_multiple = sum(v for _, v in ev_estimates) / len(ev_estimates)

    fair_ev_multiple = max(ev_low * 0.8, min(fair_ev_multiple, ev_high * 1.3))

    fair_ev = ebitda * fair_ev_multiple
    fair_equity = fair_ev - net_debt
    if fair_equity <= 0:
        return None

    shares = market_cap / current_price
    target = round(fair_equity / shares, 2)
    upside = round((target / current_price - 1) * 100, 1)

    target_low = round((ebitda * fair_ev_multiple * 0.8 - net_debt) / shares, 2)
    target_high = round((ebitda * fair_ev_multiple * 1.2 - net_debt) / shares, 2)

    assumptions = {
        "EBITDA": f"${ebitda/1e9:.2f}B" if ebitda > 1e9 else f"${ebitda/1e6:.0f}M",
        "当前EV/EBITDA": round(ev_ebitda, 1),
        "合理EV/EBITDA": round(fair_ev_multiple, 1),
        "净债务": f"${net_debt/1e9:.2f}B" if abs(net_debt) > 1e9 else f"${net_debt/1e6:.0f}M",
        "EV/EBITDA参考": {k: round(v, 1) for k, v in ev_estimates},
    }

    return ValuationResult(
        method="EV/EBITDA估值",
        target_price=target,
        upside_pct=upside,
        weight=0.9,
        assumptions=assumptions,
        sensitivity={
            "EV/EBITDA": {"保守": target_low, "基准": target, "乐观": target_high},
        },
        reasoning=f"EBITDA × {fair_ev_multiple:.1f}x - 净债务 = ${target:.2f}",
    )


def pb_relative_valuation(
    current_price: float,
    pb_ratio: float,
    roe: Optional[float],
    peer_pb_avg: Optional[float],
    industry_pb_range: tuple = (0.5, 3.0),
) -> Optional[ValuationResult]:
    """
    PB 相对估值法

    适用: 银行、保险、房地产等重资产行业
    Gordon Growth 简化: 合理PB ≈ ROE / (r - g)
    """
    if not pb_ratio or pb_ratio <= 0 or not current_price:
        return None

    bvps = current_price / pb_ratio  # 每股净资产
    pb_low, pb_high = industry_pb_range

    pb_estimates = []
    if peer_pb_avg and peer_pb_avg > 0:
        pb_estimates.append(("同行平均", peer_pb_avg))

    # ROE 隐含合理 PB (高ROE值得更高PB)
    if roe and roe > 0:
        roe_implied_pb = roe * 10  # 简化: ROE 10% → PB 1x
        roe_implied_pb = max(pb_low, min(roe_implied_pb, pb_high * 1.2))
        pb_estimates.append(("ROE隐含", round(roe_implied_pb, 2)))

    if not pb_estimates:
        fair_pb = (pb_low + pb_high) / 2
    else:
        fair_pb = sum(v for _, v in pb_estimates) / len(pb_estimates)

    fair_pb = max(pb_low * 0.7, min(fair_pb, pb_high * 1.3))

    target = round(bvps * fair_pb, 2)
    upside = round((target / current_price - 1) * 100, 1)

    target_low = round(bvps * fair_pb * 0.8, 2)
    target_high = round(bvps * fair_pb * 1.2, 2)

    assumptions = {
        "每股净资产": round(bvps, 2),
        "当前PB": round(pb_ratio, 2),
        "合理PB": round(fair_pb, 2),
        "ROE": f"{roe*100:.1f}%" if roe else "N/A",
        "PB参考": {k: round(v, 2) for k, v in pb_estimates},
    }

    return ValuationResult(
        method="PB相对估值",
        target_price=target,
        upside_pct=upside,
        weight=0.8,
        assumptions=assumptions,
        sensitivity={
            "PB倍数": {"保守": target_low, "基准": target, "乐观": target_high},
        },
        reasoning=f"每股净资产 ${bvps:.2f} × 合理PB {fair_pb:.2f}x = ${target:.2f}",
    )


def dcf_simplified_valuation(
    current_price: float,
    free_cash_flow: Optional[float],
    net_income: Optional[float],
    revenue_growth: Optional[float],
    shares_outstanding: float,
    discount_rate: float = 0.10,
    terminal_growth: float = 0.03,
    projection_years: int = 5,
) -> Optional[ValuationResult]:
    """
    DCF 简化估值 (基于 FCF 或 Owner Earnings)

    假设:
    - 未来5年 FCF 按增速递减增长
    - 终值使用 Gordon Growth 模型
    - 折现率 10% (典型权益成本)
    """
    # 使用 FCF，若无则用 Net Income 近似
    base_cf = free_cash_flow or net_income
    if not base_cf or base_cf <= 0 or not shares_outstanding:
        return None
    if not current_price or current_price <= 0:
        return None

    growth = revenue_growth if revenue_growth and revenue_growth > 0 else 0.05
    growth = min(growth, 0.40)  # 增速上限40%

    # 增速逐年递减至终值增长率
    growth_rates = []
    for i in range(projection_years):
        # 线性递减: year1 = growth, year5 接近 terminal_growth*2
        yr_growth = growth - (growth - terminal_growth * 2) * (i / projection_years)
        growth_rates.append(max(yr_growth, terminal_growth))

    # 投射未来现金流
    projected_cf = []
    cf = base_cf
    for g in growth_rates:
        cf = cf * (1 + g)
        projected_cf.append(cf)

    # 折现
    pv_cf = sum(cf / (1 + discount_rate) ** (i + 1) for i, cf in enumerate(projected_cf))

    # 终值 (Gordon Growth)
    terminal_cf = projected_cf[-1] * (1 + terminal_growth)
    terminal_value = terminal_cf / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / (1 + discount_rate) ** projection_years

    total_value = pv_cf + pv_terminal
    per_share = round(total_value / shares_outstanding, 2)
    upside = round((per_share / current_price - 1) * 100, 1)

    # 敏感性 (WACC ±2%)
    def _dcf_at_rate(r):
        pv = sum(projected_cf[i] / (1 + r) ** (i + 1) for i in range(len(projected_cf)))
        tv = projected_cf[-1] * (1 + terminal_growth) / (r - terminal_growth)
        pvt = tv / (1 + r) ** projection_years
        return round((pv + pvt) / shares_outstanding, 2)

    target_low = _dcf_at_rate(discount_rate + 0.02)
    target_high = _dcf_at_rate(discount_rate - 0.02)

    cf_label = "FCF" if free_cash_flow and free_cash_flow > 0 else "净利润"
    assumptions = {
        f"基期{cf_label}": f"${base_cf/1e9:.2f}B" if base_cf > 1e9 else f"${base_cf/1e6:.0f}M",
        "初始增速": f"{growth*100:.1f}%",
        "增速路径": [f"Y{i+1}: {g*100:.1f}%" for i, g in enumerate(growth_rates)],
        "折现率(WACC)": f"{discount_rate*100:.0f}%",
        "永续增长率": f"{terminal_growth*100:.1f}%",
        "终值占比": f"{pv_terminal/(pv_cf+pv_terminal)*100:.0f}%",
    }

    return ValuationResult(
        method="DCF简化估值",
        target_price=per_share,
        upside_pct=upside,
        weight=0.6,  # 简化DCF权重稍低
        assumptions=assumptions,
        sensitivity={
            "折现率": {
                f"WACC {(discount_rate+0.02)*100:.0f}%": target_low,
                f"WACC {discount_rate*100:.0f}%": per_share,
                f"WACC {(discount_rate-0.02)*100:.0f}%": target_high,
            },
        },
        reasoning=f"基于{cf_label}${base_cf/1e9:.2f}B, {projection_years}年增长折现 → ${per_share:.2f}",
    )


def dividend_discount_valuation(
    current_price: float,
    dividend_yield: Optional[float],
    dividend_growth: Optional[float],
    discount_rate: float = 0.10,
) -> Optional[ValuationResult]:
    """
    股息折现模型 (Gordon Growth Model)

    P = D₁ / (r - g)
    适用: 稳定分红的价值股
    """
    if not dividend_yield or dividend_yield <= 0 or not current_price:
        return None
    if dividend_yield < 0.01:  # 低于1%不适用
        return None

    dps = current_price * dividend_yield  # 当前每股股息
    g = dividend_growth if dividend_growth and dividend_growth > 0 else 0.03
    g = min(g, 0.08)  # 股息增长率上限8%

    if discount_rate <= g:
        return None

    d1 = dps * (1 + g)
    target = round(d1 / (discount_rate - g), 2)
    upside = round((target / current_price - 1) * 100, 1)

    target_low = round(d1 / (discount_rate + 0.02 - g), 2)
    target_high = round(d1 / (discount_rate - 0.02 - g), 2) if discount_rate - 0.02 > g else target * 1.3

    assumptions = {
        "当前股息率": f"{dividend_yield*100:.2f}%",
        "每股股息": f"${dps:.2f}",
        "股息增长率": f"{g*100:.1f}%",
        "要求回报率": f"{discount_rate*100:.0f}%",
    }

    return ValuationResult(
        method="股息折现(DDM)",
        target_price=target,
        upside_pct=upside,
        weight=0.5,
        assumptions=assumptions,
        sensitivity={
            "要求回报率": {
                f"r={int((discount_rate+0.02)*100)}%": target_low,
                f"r={int(discount_rate*100)}%": target,
                f"r={int((discount_rate-0.02)*100)}%": target_high,
            },
        },
        reasoning=f"D₁=${d1:.2f} / (r={discount_rate*100:.0f}% - g={g*100:.1f}%) = ${target:.2f}",
    )


# ====================================================================
# 综合估值引擎
# ====================================================================

def run_valuation(
    key_metrics: dict,
    financials: dict,
    competitive_comparison: dict,
) -> Optional[ValuationSummary]:
    """
    综合估值入口: 自动匹配行业估值方法，计算多方法目标价

    Args:
        key_metrics: fetch_key_metrics() 的返回值
        financials: fetch_financials() 的返回值
        competitive_comparison: build_competitive_comparison() 的返回值

    Returns:
        ValuationSummary 或 None (数据不足时)
    """
    sector = key_metrics.get("sector", "")
    industry = key_metrics.get("industry", "")
    current_price = key_metrics.get("52w_high")  # 先取个placeholder
    shares = key_metrics.get("shares_outstanding")

    # 从 technical indicators 或 key_metrics 获取当前价格
    # 这里用 50d_avg 作为近似 (在 engine 中会传入准确价格)
    price = key_metrics.get("50d_avg") or key_metrics.get("52w_high")

    if not price or price <= 0:
        logger.warning("估值失败: 无法获取当前价格")
        return None

    # 匹配行业估值规则
    rules = _match_industry(sector, industry)
    methods = rules.get("methods", ["pe_relative"])
    primary_method = rules.get("primary", "pe_relative")

    # 从竞品数据计算同行平均指标
    peer_metrics = _compute_peer_averages(competitive_comparison, key_metrics.get("company_name", ""))

    # 提取关键指标
    eps_ttm = None
    if key_metrics.get("pe_ratio") and key_metrics["pe_ratio"] > 0:
        eps_ttm = price / key_metrics["pe_ratio"]
    elif key_metrics.get("net_income") and shares:
        eps_ttm = key_metrics["net_income"] / shares

    revenue_per_share = None
    if key_metrics.get("revenue") and shares:
        revenue_per_share = key_metrics["revenue"] / shares
    elif key_metrics.get("ps_ratio") and key_metrics["ps_ratio"] > 0:
        revenue_per_share = price / key_metrics["ps_ratio"]

    # 执行各估值方法
    results = []

    if "pe_relative" in methods:
        r = pe_relative_valuation(
            current_price=price,
            eps_ttm=eps_ttm or 0,
            forward_pe=key_metrics.get("forward_pe"),
            peer_pe_avg=peer_metrics.get("avg_pe"),
            revenue_growth=key_metrics.get("revenue_growth"),
            industry_pe_range=rules.get("pe_peer_range", (10, 30)),
        )
        if r:
            results.append(r)

    if "ps_relative" in methods:
        r = ps_relative_valuation(
            current_price=price,
            revenue_per_share=revenue_per_share or 0,
            peer_ps_avg=peer_metrics.get("avg_ps"),
            revenue_growth=key_metrics.get("revenue_growth"),
            profit_margin=key_metrics.get("profit_margin"),
            industry_ps_range=rules.get("ps_peer_range", (3, 20)),
        )
        if r:
            results.append(r)

    if "peg" in methods:
        r = peg_valuation(
            current_price=price,
            eps_ttm=eps_ttm or 0,
            earnings_growth=key_metrics.get("earnings_growth"),
            revenue_growth=key_metrics.get("revenue_growth"),
        )
        if r:
            results.append(r)

    if "ev_ebitda" in methods:
        r = ev_ebitda_valuation(
            current_price=price,
            ev_ebitda=key_metrics.get("ev_ebitda", 0) or 0,
            enterprise_value=key_metrics.get("enterprise_value", 0) or 0,
            market_cap=key_metrics.get("market_cap", 0) or 0,
            peer_ev_ebitda_avg=peer_metrics.get("avg_ev_ebitda"),
            revenue_growth=key_metrics.get("revenue_growth"),
            industry_ev_ebitda_range=rules.get("ev_ebitda_peer_range", (5, 20)),
        )
        if r:
            results.append(r)

    if "pb_relative" in methods:
        r = pb_relative_valuation(
            current_price=price,
            pb_ratio=key_metrics.get("pb_ratio", 0) or 0,
            roe=key_metrics.get("roe"),
            peer_pb_avg=peer_metrics.get("avg_pb"),
            industry_pb_range=rules.get("pb_peer_range", (0.5, 3.0)),
        )
        if r:
            results.append(r)

    if "dcf_simplified" in methods:
        r = dcf_simplified_valuation(
            current_price=price,
            free_cash_flow=key_metrics.get("free_cash_flow"),
            net_income=key_metrics.get("net_income"),
            revenue_growth=key_metrics.get("revenue_growth"),
            shares_outstanding=shares or 1,
        )
        if r:
            results.append(r)

    if "dividend_discount" in methods:
        r = dividend_discount_valuation(
            current_price=price,
            dividend_yield=key_metrics.get("dividend_yield"),
            dividend_growth=key_metrics.get("revenue_growth"),  # 近似
        )
        if r:
            results.append(r)

    if not results:
        logger.warning(f"估值失败: 无有效估值方法 ({sector}/{industry})")
        return None

    # 加权计算公允价值
    total_weight = sum(r.weight for r in results)
    fair_value = sum(r.target_price * r.weight for r in results) / total_weight
    fair_value = round(fair_value, 2)

    # Bull / Base / Bear 场景
    all_targets = [r.target_price for r in results]
    all_highs = [v for r in results for v in r.sensitivity.values() for k, v in (v if isinstance(v, dict) else {}).items() if "乐观" in k or "high" in k.lower()]
    all_lows = [v for r in results for v in r.sensitivity.values() for k, v in (v if isinstance(v, dict) else {}).items() if "保守" in k or "low" in k.lower()]

    # 从敏感性分析中提取 bull/bear
    sensitivity_highs = []
    sensitivity_lows = []
    for r in results:
        for param, values in r.sensitivity.items():
            if isinstance(values, dict):
                vals = list(values.values())
                if vals:
                    sensitivity_highs.append(max(v for v in vals if isinstance(v, (int, float))))
                    sensitivity_lows.append(min(v for v in vals if isinstance(v, (int, float))))

    target_bull = round(max(sensitivity_highs) if sensitivity_highs else fair_value * 1.2, 2)
    target_bear = round(min(sensitivity_lows) if sensitivity_lows else fair_value * 0.8, 2)
    target_base = fair_value

    upside = round((fair_value / price - 1) * 100, 1)

    # 估值等级
    if upside > 30:
        grade = "CHEAP"
    elif upside > 5:
        grade = "FAIR"
    elif upside > -15:
        grade = "EXPENSIVE"
    else:
        grade = "BUBBLE"

    # 主要方法名
    primary_name = next((r.method for r in results if r.method.lower().replace("相对估值", "").replace("估值", "").strip()
                         in primary_method.lower()), results[0].method)

    method_names = [r.method for r in results]
    methodology_note = (
        f"基于{sector}/{industry}行业特征，综合采用 {', '.join(method_names)} "
        f"共{len(results)}种方法进行估值。主要参考方法: {primary_name}。"
    )

    return ValuationSummary(
        current_price=price,
        fair_value=fair_value,
        target_price_bull=target_bull,
        target_price_base=target_base,
        target_price_bear=target_bear,
        upside_pct=upside,
        methods_used=results,
        primary_method=primary_name,
        valuation_grade=grade,
        methodology_note=methodology_note,
    )


def _compute_peer_averages(competitive_comparison: dict, target_name: str) -> dict:
    """从竞品数据计算同行平均指标 (排除目标公司自身)"""
    table = competitive_comparison.get("comparison_table", [])
    if not table:
        return {}

    pe_vals, ps_vals, pb_vals, ev_vals = [], [], [], []
    for row in table:
        # 排除自身
        if row.get("name") == target_name or row.get("symbol") == target_name:
            continue
        if row.get("pe_ratio") and 0 < row["pe_ratio"] < 200:
            pe_vals.append(row["pe_ratio"])
        if row.get("ps_ratio") and 0 < row["ps_ratio"] < 100:
            ps_vals.append(row["ps_ratio"])
        if row.get("pb_ratio") and 0 < row["pb_ratio"] < 50:
            pb_vals.append(row["pb_ratio"])
        if row.get("ev_ebitda") and 0 < row["ev_ebitda"] < 100:
            ev_vals.append(row["ev_ebitda"])

    result = {}
    if pe_vals:
        result["avg_pe"] = round(sum(pe_vals) / len(pe_vals), 1)
        result["median_pe"] = round(sorted(pe_vals)[len(pe_vals) // 2], 1)
    if ps_vals:
        result["avg_ps"] = round(sum(ps_vals) / len(ps_vals), 1)
    if pb_vals:
        result["avg_pb"] = round(sum(pb_vals) / len(pb_vals), 2)
    if ev_vals:
        result["avg_ev_ebitda"] = round(sum(ev_vals) / len(ev_vals), 1)

    return result


# ====================================================================
# 估值结果格式化 (供 Agent prompt 使用)
# ====================================================================

def format_valuation_text(summary: ValuationSummary) -> str:
    """将估值结果格式化为文本，嵌入 Agent 分析 prompt"""
    lines = []
    lines.append("## 量化估值分析")
    lines.append("")
    lines.append(f"**估值等级: {summary.valuation_grade}** | "
                 f"当前价 ${summary.current_price:.2f} | "
                 f"公允价值 ${summary.fair_value:.2f} "
                 f"({summary.upside_pct:+.1f}%)")
    lines.append("")
    lines.append(f"| 情景 | 目标价 | 涨跌幅 |")
    lines.append(f"|------|--------|--------|")
    lines.append(f"| 牛市 | ${summary.target_price_bull:.2f} | "
                 f"{(summary.target_price_bull/summary.current_price-1)*100:+.1f}% |")
    lines.append(f"| 基准 | ${summary.target_price_base:.2f} | "
                 f"{(summary.target_price_base/summary.current_price-1)*100:+.1f}% |")
    lines.append(f"| 熊市 | ${summary.target_price_bear:.2f} | "
                 f"{(summary.target_price_bear/summary.current_price-1)*100:+.1f}% |")
    lines.append("")

    lines.append("### 各方法估值详情")
    for r in summary.methods_used:
        lines.append(f"\n**{r.method}** (权重: {r.weight:.1f})")
        lines.append(f"  目标价: ${r.target_price:.2f} ({r.upside_pct:+.1f}%)")
        lines.append(f"  逻辑: {r.reasoning}")
        lines.append(f"  核心假设:")
        for k, v in r.assumptions.items():
            if isinstance(v, dict):
                lines.append(f"    - {k}: {', '.join(f'{kk}={vv}' for kk, vv in v.items())}")
            elif isinstance(v, list):
                lines.append(f"    - {k}: {', '.join(str(x) for x in v[:4])}")
            else:
                lines.append(f"    - {k}: {v}")
        lines.append(f"  敏感性分析:")
        for param, vals in r.sensitivity.items():
            if isinstance(vals, dict):
                items = [f"{k}: ${v:.2f}" for k, v in vals.items()]
                lines.append(f"    - {param}: {' / '.join(items)}")

    lines.append(f"\n{summary.methodology_note}")
    return "\n".join(lines)
