"""
中概/港股特定定价因子

核心职责:
  强制引入中概股特有的定价变量，避免分析师忽略这些关键风险因素。

因子:
  1. 地缘政治折价 — VIE 结构风险、ADR 退市风险
  2. 监管周期评估 — 宽松/收紧/稳定
  3. 南向资金流向 — 港股通买入卖出信号
  4. ADR 折溢价 — 港股 vs ADR 价差
  5. 综合风险因子清单

这些因子在 SSOT 中预计算，作为硬性输入传给 Agent。
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ======================================================================
# 地缘政治折价
# ======================================================================

# 行业→地缘敏感度评分 (0-100, 100=最敏感)
GEOPOLITICAL_SENSITIVITY = {
    # 高敏感
    "semiconductor": 90,
    "defense": 95,
    "telecom": 80,
    "ai": 75,
    "cloud_computing": 70,
    "autonomous_driving": 70,
    "surveillance": 90,
    "quantum_computing": 85,
    # 中敏感
    "e-commerce": 40,
    "social_media": 50,
    "gaming": 45,
    "fintech": 55,
    "edtech": 60,
    # 低敏感
    "food_delivery": 20,
    "local_services": 15,
    "consumer": 25,
    "entertainment": 30,
    "logistics": 35,
}

# 中概 ADR 结构风险
ADR_STRUCTURE_RISK = {
    "vie_standard": 10,     # 标准 VIE 结构 (多数中概)
    "vie_restricted": 20,   # 受限 VIE (教培/金融)
    "direct_listing": 5,    # 直接上市
    "dual_primary": 3,      # 双重主要上市 (BABA, JD)
    "secondary_hk": 5,      # 港股二次上市
}


@dataclass
class GeopoliticalDiscount:
    """地缘政治折价"""
    base_discount_pct: float        # 基础折价 %
    sector_sensitivity: int         # 行业敏感度 (0-100)
    adr_structure_risk: float       # ADR 结构风险 %
    total_discount_pct: float       # 总折价 %
    risk_level: str                 # LOW / MEDIUM / HIGH / CRITICAL
    factors: list[str]              # 具体风险因素


def compute_geopolitical_discount(
    symbol: str,
    sector: str,
    industry: str = "",
    adr_structure: str = "vie_standard",
    is_on_entity_list: bool = False,
) -> GeopoliticalDiscount:
    """
    计算地缘政治折价

    折价模型:
    - 基础折价: 所有中概股 5%
    - 行业敏感度折价: 0-15% (基于行业)
    - ADR 结构风险: 3-20% (基于上市结构)
    - 实体清单: +20%
    """
    # 判断是否是中概/港股
    sym = symbol.upper().strip()
    is_china = (
        sym.endswith(".HK") or sym.endswith(".SH") or sym.endswith(".SZ")
        or sym in {"BIDU", "BABA", "PDD", "JD", "NTES", "TME", "BILI", "IQ",
                   "NIO", "XPEV", "LI", "ZTO", "VIPS", "DIDI", "FUTU", "MNSO"}
    )

    if not is_china:
        return GeopoliticalDiscount(
            base_discount_pct=0,
            sector_sensitivity=0,
            adr_structure_risk=0,
            total_discount_pct=0,
            risk_level="LOW",
            factors=[],
        )

    # 基础折价
    base = 5.0

    # 行业敏感度
    text = f"{sector} {industry}".lower()
    sensitivity = 30  # 默认中等
    for kw, score in GEOPOLITICAL_SENSITIVITY.items():
        if kw.replace("_", " ") in text or kw in text:
            sensitivity = max(sensitivity, score)
            break

    sector_discount = sensitivity * 0.15  # 最大 15%

    # ADR 结构
    structure_risk = ADR_STRUCTURE_RISK.get(adr_structure, 10)

    # 实体清单
    entity_penalty = 20.0 if is_on_entity_list else 0.0

    total = round(base + sector_discount + structure_risk + entity_penalty, 1)

    # 风险等级
    if total >= 30:
        level = "CRITICAL"
    elif total >= 20:
        level = "HIGH"
    elif total >= 10:
        level = "MEDIUM"
    else:
        level = "LOW"

    # 风险因素清单
    factors = []
    factors.append(f"中概基础折价 {base}%")
    factors.append(f"行业敏感度 {sensitivity}/100 → 折价 {sector_discount:.1f}%")
    factors.append(f"ADR结构({adr_structure}) → 风险 {structure_risk}%")
    if is_on_entity_list:
        factors.append(f"实体清单 → 额外折价 {entity_penalty}%")

    return GeopoliticalDiscount(
        base_discount_pct=base,
        sector_sensitivity=sensitivity,
        adr_structure_risk=structure_risk,
        total_discount_pct=total,
        risk_level=level,
        factors=factors,
    )


# ======================================================================
# 监管周期
# ======================================================================

@dataclass
class RegulatoryScore:
    """监管周期评估"""
    cycle_phase: str        # TIGHTENING / STABLE / LOOSENING
    score: int              # -100 (极度收紧) ~ +100 (极度宽松)
    key_policies: list[str] # 近期关键政策
    outlook: str            # 前瞻判断


# 行业→当前监管状态 (截止 2025Q1)
REGULATORY_CYCLE_MAP = {
    "internet_platform": {
        "phase": "STABLE",
        "score": 20,
        "policies": [
            "2024: 平台经济常态化监管基本完成",
            "2025: 支持平台企业'走出去'",
            "反垄断执法力度趋于温和",
        ],
        "outlook": "监管框架基本成型，不确定性下降。政策重心转向促消费。",
    },
    "gaming": {
        "phase": "LOOSENING",
        "score": 30,
        "policies": [
            "2024: 版号发放提速，月均80+",
            "AI 游戏内容审核标准化",
        ],
        "outlook": "版号审批正常化，但AI相关新规可能带来变数。",
    },
    "fintech": {
        "phase": "TIGHTENING",
        "score": -20,
        "policies": [
            "蚂蚁集团重组持续",
            "跨境支付监管趋严",
        ],
        "outlook": "金融科技监管仍在收紧周期。",
    },
    "edtech": {
        "phase": "STABLE",
        "score": -40,
        "policies": [
            "双减政策持续执行",
            "职业教育鼓励发展",
        ],
        "outlook": "K-12赛道永久受限，转型期。",
    },
    "ev_auto": {
        "phase": "LOOSENING",
        "score": 40,
        "policies": [
            "新能源汽车补贴延续",
            "智能驾驶路测政策放宽",
            "以旧换新消费刺激",
        ],
        "outlook": "政策强支持，但产能过剩可能引发行业整合。",
    },
    "ai_technology": {
        "phase": "LOOSENING",
        "score": 35,
        "policies": [
            "AI 产业扶持政策加码",
            "大模型备案审批流程简化",
            "AI+ 产业融合鼓励",
        ],
        "outlook": "政策鼓励创新，但数据安全审查仍严格。",
    },
    "default": {
        "phase": "STABLE",
        "score": 0,
        "policies": [],
        "outlook": "监管环境中性。",
    },
}


def compute_regulatory_cycle(
    industry: str,
    sector: str = "",
) -> RegulatoryScore:
    """
    评估当前监管周期阶段

    基于行业映射返回监管评分和关键政策
    """
    text = f"{sector} {industry}".lower()

    matched = REGULATORY_CYCLE_MAP["default"]
    for key, data in REGULATORY_CYCLE_MAP.items():
        if key == "default":
            continue
        if key.replace("_", " ") in text or key in text:
            matched = data
            break

    # 模糊匹配
    if matched == REGULATORY_CYCLE_MAP["default"]:
        keyword_map = {
            "internet_platform": ["internet", "e-commerce", "platform", "local service",
                                  "food delivery", "ride-hailing"],
            "gaming": ["gaming", "game", "entertainment"],
            "fintech": ["fintech", "financial", "payment"],
            "ev_auto": ["auto", "ev", "vehicle", "electric", "driving"],
            "ai_technology": ["ai", "artificial intelligence", "machine learning",
                              "cloud", "technology"],
        }
        for key, keywords in keyword_map.items():
            if any(kw in text for kw in keywords):
                matched = REGULATORY_CYCLE_MAP[key]
                break

    return RegulatoryScore(
        cycle_phase=matched["phase"],
        score=matched["score"],
        key_policies=matched["policies"],
        outlook=matched["outlook"],
    )


# ======================================================================
# 南向资金信号 (简化模型)
# ======================================================================

@dataclass
class SouthboundFlowSignal:
    """南向资金流向信号"""
    signal: str         # STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL
    net_flow_description: str
    top_bought: list[str]
    top_sold: list[str]


def compute_southbound_flow_signal(
    net_buy_data: Optional[dict] = None,
) -> SouthboundFlowSignal:
    """
    南向资金流向分析

    注: 在没有实时数据时返回 NEUTRAL + 说明
    """
    if not net_buy_data:
        return SouthboundFlowSignal(
            signal="NEUTRAL",
            net_flow_description="无实时南向资金数据",
            top_bought=[],
            top_sold=[],
        )

    net_flow = net_buy_data.get("net_flow_hkd", 0)
    top_b = net_buy_data.get("top_bought", [])
    top_s = net_buy_data.get("top_sold", [])

    if net_flow > 5e9:
        signal = "STRONG_BUY"
        desc = f"南向净买入 HK${net_flow/1e9:.1f}B (强势流入)"
    elif net_flow > 1e9:
        signal = "BUY"
        desc = f"南向净买入 HK${net_flow/1e9:.1f}B"
    elif net_flow < -5e9:
        signal = "STRONG_SELL"
        desc = f"南向净卖出 HK${abs(net_flow)/1e9:.1f}B (大幅流出)"
    elif net_flow < -1e9:
        signal = "SELL"
        desc = f"南向净卖出 HK${abs(net_flow)/1e9:.1f}B"
    else:
        signal = "NEUTRAL"
        desc = f"南向资金流向中性 (HK${net_flow/1e9:.1f}B)"

    return SouthboundFlowSignal(
        signal=signal,
        net_flow_description=desc,
        top_bought=top_b[:5],
        top_sold=top_s[:5],
    )


# ======================================================================
# ADR 折溢价
# ======================================================================

@dataclass
class ADRDiscount:
    """ADR 折溢价"""
    hk_price_hkd: Optional[float]
    adr_price_usd: Optional[float]
    adr_ratio: int                  # 1 ADR = N 港股
    discount_pct: Optional[float]   # 正=ADR溢价, 负=ADR折价
    signal: str                     # ADR折价→买ADR, ADR溢价→买港股


def compute_adr_discount(
    hk_price_hkd: Optional[float] = None,
    adr_price_usd: Optional[float] = None,
    adr_ratio: int = 1,
    usd_hkd_rate: float = 7.80,
) -> ADRDiscount:
    """
    ADR 折溢价计算

    discount = (ADR等价 - 港股价) / 港股价 × 100
    正 = ADR 溢价 (买港股更便宜)
    负 = ADR 折价 (买ADR更便宜)
    """
    if not hk_price_hkd or not adr_price_usd:
        return ADRDiscount(
            hk_price_hkd=hk_price_hkd,
            adr_price_usd=adr_price_usd,
            adr_ratio=adr_ratio,
            discount_pct=None,
            signal="无数据",
        )

    # ADR 等价港币价 = ADR价格(USD) × 汇率 / ADR比率
    adr_hkd_equiv = adr_price_usd * usd_hkd_rate / adr_ratio
    discount = round((adr_hkd_equiv - hk_price_hkd) / hk_price_hkd * 100, 2)

    if discount > 2:
        signal = f"ADR溢价{discount:.1f}% → 买港股"
    elif discount < -2:
        signal = f"ADR折价{abs(discount):.1f}% → 买ADR"
    else:
        signal = f"ADR/港股平价 (差异{discount:.1f}%)"

    return ADRDiscount(
        hk_price_hkd=hk_price_hkd,
        adr_price_usd=adr_price_usd,
        adr_ratio=adr_ratio,
        discount_pct=discount,
        signal=signal,
    )


# ======================================================================
# 综合: 获取所有中概/港股风险因子
# ======================================================================

@dataclass
class ChinaHKRiskFactors:
    """中概/港股综合风险因子"""
    is_china_related: bool
    geopolitical: GeopoliticalDiscount
    regulatory: RegulatoryScore
    southbound: SouthboundFlowSignal
    adr_discount: Optional[ADRDiscount]
    summary_risks: list[str]        # 风险清单 (传给 Agent)
    total_china_discount_pct: float # 总折价 %


def get_china_hk_risk_factors(
    symbol: str,
    sector: str = "",
    industry: str = "",
    hk_price: Optional[float] = None,
    adr_price: Optional[float] = None,
    adr_ratio: int = 1,
    southbound_data: Optional[dict] = None,
) -> ChinaHKRiskFactors:
    """
    获取中概/港股完整风险因子清单

    Returns:
        ChinaHKRiskFactors — 传给 SSOT 引擎和 Agent
    """
    sym = symbol.upper().strip()
    is_china = (
        sym.endswith(".HK") or sym.endswith(".SH") or sym.endswith(".SZ")
        or sym in {"BIDU", "BABA", "PDD", "JD", "NTES", "TME", "BILI", "IQ",
                   "NIO", "XPEV", "LI", "ZTO", "VIPS", "DIDI", "FUTU", "MNSO"}
    )

    # 地缘
    geo = compute_geopolitical_discount(symbol, sector, industry)

    # 监管
    reg = compute_regulatory_cycle(industry, sector)

    # 南向
    sb = compute_southbound_flow_signal(southbound_data)

    # ADR
    adr = None
    if hk_price or adr_price:
        adr = compute_adr_discount(hk_price, adr_price, adr_ratio)

    # 汇总风险清单
    risks = []
    if is_china:
        risks.append(f"地缘政治风险: {geo.risk_level} (折价 {geo.total_discount_pct:.1f}%)")
        risks.append(f"监管周期: {reg.cycle_phase} (评分 {reg.score})")
        if reg.key_policies:
            for p in reg.key_policies[:3]:
                risks.append(f"  - {p}")
        risks.append(f"南向资金: {sb.signal}")
        if adr and adr.discount_pct is not None:
            risks.append(f"ADR折溢价: {adr.signal}")

    total_discount = geo.total_discount_pct if is_china else 0.0

    return ChinaHKRiskFactors(
        is_china_related=is_china,
        geopolitical=geo,
        regulatory=reg,
        southbound=sb,
        adr_discount=adr,
        summary_risks=risks,
        total_china_discount_pct=total_discount,
    )


def format_china_hk_factors(factors: ChinaHKRiskFactors) -> str:
    """格式化中概/港股风险因子为文本"""
    if not factors.is_china_related:
        return ""

    lines = []
    lines.append("\n--- 中概/港股特定风险因子 ---")

    # 地缘
    g = factors.geopolitical
    lines.append(f"\n地缘政治: {g.risk_level}")
    for f in g.factors:
        lines.append(f"  {f}")
    lines.append(f"  总折价: {g.total_discount_pct:.1f}%")

    # 监管
    r = factors.regulatory
    lines.append(f"\n监管周期: {r.cycle_phase} (评分: {r.score})")
    for p in r.key_policies:
        lines.append(f"  - {p}")
    lines.append(f"  前瞻: {r.outlook}")

    # 南向
    lines.append(f"\n南向资金: {factors.southbound.signal}")
    lines.append(f"  {factors.southbound.net_flow_description}")

    # ADR
    if factors.adr_discount and factors.adr_discount.discount_pct is not None:
        lines.append(f"\nADR折溢价: {factors.adr_discount.signal}")

    return "\n".join(lines)
