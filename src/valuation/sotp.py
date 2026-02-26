"""
SOTP 分部估值模块 — Sum of the Parts

核心职责:
  对多业务线公司进行分部估值，强制绑定定性优势与估值数字。

设计原则:
  1. 每个业务线必须有独立的营收、利润率、增速、适用倍数
  2. 倍数选择有据可依 (同行可比公司)
  3. 最终合计 → 扣除净债务 → 除以股数 → 每股价值
  4. 输出带正确货币符号

预设模板:
  - 美团 (外卖+到店+闪购+新业务)
  - 阿里 (电商+云+本地生活)
  - 百度 (搜索+AI Cloud+Apollo)
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from src.valuation.currency import CurrencyContext, format_currency

logger = logging.getLogger(__name__)


@dataclass
class SotpSegment:
    """单个业务分部"""
    name: str                      # 业务名
    revenue: float                 # 营收 (报告货币)
    operating_profit: Optional[float] = None  # 经营利润
    operating_margin: Optional[float] = None  # 经营利润率
    growth_rate: Optional[float] = None       # 营收增速
    valuation_multiple: float = 0.0           # 适用倍数 (PS 或 PE)
    multiple_type: str = "PS"                 # 倍数类型: "PS" 或 "PE"
    comparable_companies: list[str] = field(default_factory=list)  # 可比公司
    segment_value: float = 0.0               # 业务估值 (=营收×PS 或 利润×PE)
    note: str = ""                            # 备注


@dataclass
class SotpResult:
    """SOTP 估值结果"""
    segments: list[SotpSegment]
    total_segment_value: float     # 各部分加总
    net_debt: float                # 净债务 (正=有债务, 负=有净现金)
    equity_value: float            # 股权价值 = 加总 - 净债务
    shares_outstanding: float
    per_share_value: float         # 每股价值
    current_price: float
    upside_pct: float
    currency: str                  # 结果货币
    methodology_note: str = ""


def compute_segment_value(segment: SotpSegment) -> SotpSegment:
    """计算单个分部的估值"""
    if segment.multiple_type == "PE":
        base = segment.operating_profit or 0
    else:
        base = segment.revenue

    segment.segment_value = round(base * segment.valuation_multiple, 0)
    return segment


def compute_sotp(
    segments: list[SotpSegment],
    net_debt: float,
    shares_outstanding: float,
    current_price: float,
    currency: str = "USD",
) -> SotpResult:
    """
    SOTP 估值主计算

    Args:
        segments: 业务分部列表
        net_debt: 净债务 (正=有债务, 负=净现金)
        shares_outstanding: 总股本
        current_price: 当前价格
        currency: 结果货币

    Returns:
        SotpResult
    """
    # 计算每个分部
    for seg in segments:
        compute_segment_value(seg)

    total = sum(s.segment_value for s in segments)
    equity = total - net_debt
    per_share = round(equity / shares_outstanding, 2) if shares_outstanding > 0 else 0

    upside = round((per_share / current_price - 1) * 100, 1) if current_price > 0 else 0

    # 生成方法论说明
    seg_notes = []
    for s in segments:
        seg_notes.append(
            f"{s.name}: {format_currency(s.revenue, currency, 'large')} × "
            f"{s.valuation_multiple:.1f}x {s.multiple_type} = "
            f"{format_currency(s.segment_value, currency, 'large')}"
        )
    note = " | ".join(seg_notes)

    return SotpResult(
        segments=segments,
        total_segment_value=total,
        net_debt=net_debt,
        equity_value=equity,
        shares_outstanding=shares_outstanding,
        per_share_value=per_share,
        current_price=current_price,
        upside_pct=upside,
        currency=currency,
        methodology_note=note,
    )


def format_sotp_report(result: SotpResult) -> str:
    """格式化 SOTP 结果为文本"""
    ccy = result.currency
    lines = []
    lines.append("--- SOTP 分部估值 ---")
    lines.append("")

    # 分部表格
    lines.append(f"{'业务':<16} {'营收':<14} {'增速':<8} "
                 f"{'倍数':<10} {'估值':<14} {'可比公司'}")
    lines.append("-" * 80)

    for s in result.segments:
        rev_str = format_currency(s.revenue, ccy, "large")
        growth_str = f"{s.growth_rate*100:.0f}%" if s.growth_rate else "N/A"
        mult_str = f"{s.valuation_multiple:.1f}x {s.multiple_type}"
        val_str = format_currency(s.segment_value, ccy, "large")
        comps = ", ".join(s.comparable_companies[:3]) if s.comparable_companies else "-"
        lines.append(f"{s.name:<16} {rev_str:<14} {growth_str:<8} "
                     f"{mult_str:<10} {val_str:<14} {comps}")

    lines.append("-" * 80)
    lines.append(f"{'分部加总':<16} {'':14} {'':8} {'':10} "
                 f"{format_currency(result.total_segment_value, ccy, 'large')}")
    lines.append(f"{'净债务':<16} {'':14} {'':8} {'':10} "
                 f"{format_currency(result.net_debt, ccy, 'large')}")
    lines.append(f"{'股权价值':<16} {'':14} {'':8} {'':10} "
                 f"{format_currency(result.equity_value, ccy, 'large')}")
    lines.append(f"{'总股本':<16} {'':14} {'':8} {'':10} "
                 f"{result.shares_outstanding/1e9:.2f}B股")
    lines.append("")
    lines.append(f"SOTP 每股价值: {format_currency(result.per_share_value, ccy)} "
                 f"(当前: {format_currency(result.current_price, ccy)}, "
                 f"{result.upside_pct:+.1f}%)")

    return "\n".join(lines)


# ======================================================================
# 预设 SOTP 模板
# ======================================================================

def build_meituan_sotp(
    food_delivery_rev: float,
    instore_rev: float,
    flash_buy_rev: float,
    new_initiatives_rev: float,
    net_debt: float,
    shares: float,
    current_price: float,
) -> SotpResult:
    """
    美团 SOTP 模板

    业务线:
    1. 外卖: 成熟现金牛, PS 2-3x (对标 DoorDash/Grab)
    2. 到店/酒旅: 高毛利高增长, PS 5-8x (对标 Booking)
    3. 闪购: 即时零售, PS 1.5-3x (对标 Instacart)
    4. 新业务: 社区团购/出行等, PS 0.5-1x (亏损折价)
    """
    segments = [
        SotpSegment(
            name="外卖",
            revenue=food_delivery_rev,
            growth_rate=0.10,
            valuation_multiple=2.5,
            multiple_type="PS",
            comparable_companies=["DoorDash", "Grab", "Delivery Hero"],
            note="成熟业务, 规模优势明显",
        ),
        SotpSegment(
            name="到店/酒旅",
            revenue=instore_rev,
            growth_rate=0.25,
            valuation_multiple=6.0,
            multiple_type="PS",
            comparable_companies=["Booking", "Airbnb", "Trip.com"],
            note="高毛利高增长, 核心利润来源",
        ),
        SotpSegment(
            name="闪购/即时零售",
            revenue=flash_buy_rev,
            growth_rate=0.30,
            valuation_multiple=2.0,
            multiple_type="PS",
            comparable_companies=["Instacart", "Gopuff"],
            note="高增长赛道, 尚未盈利",
        ),
        SotpSegment(
            name="新业务",
            revenue=new_initiatives_rev,
            growth_rate=-0.10,
            valuation_multiple=0.5,
            multiple_type="PS",
            comparable_companies=[],
            note="社区团购/出行, 持续亏损收缩",
        ),
    ]
    return compute_sotp(segments, net_debt, shares, current_price, currency="HKD")


def build_baidu_sotp(
    search_ad_rev: float,
    ai_cloud_rev: float,
    apollo_rev: float,
    other_rev: float,
    net_debt: float,
    shares: float,
    current_price: float,
) -> SotpResult:
    """
    百度 SOTP 模板

    业务线:
    1. 搜索广告: 成熟但衰退, PE 8-12x
    2. AI Cloud: 高增长, PS 3-6x (对标阿里云/AWS)
    3. Apollo/智能驾驶: 早期, PS 2-4x (对标 Waymo 估值折价)
    4. 其他(爱奇艺/小度等): PS 0.5-1x
    """
    segments = [
        SotpSegment(
            name="搜索广告",
            revenue=search_ad_rev,
            growth_rate=-0.05,
            valuation_multiple=2.0,
            multiple_type="PS",
            comparable_companies=["Google (搜索)", "Naver"],
            note="核心现金牛, 增速放缓",
        ),
        SotpSegment(
            name="AI Cloud",
            revenue=ai_cloud_rev,
            growth_rate=0.26,
            valuation_multiple=4.0,
            multiple_type="PS",
            comparable_companies=["阿里云", "AWS", "Azure"],
            note="高增长, ERNIE 赋能",
        ),
        SotpSegment(
            name="Apollo/智能驾驶",
            revenue=apollo_rev,
            growth_rate=0.40,
            valuation_multiple=3.0,
            multiple_type="PS",
            comparable_companies=["Waymo (折价)", "Cruise"],
            note="Robotaxi 商业化先驱",
        ),
        SotpSegment(
            name="其他",
            revenue=other_rev,
            growth_rate=0.0,
            valuation_multiple=0.5,
            multiple_type="PS",
            comparable_companies=["iQIYI", "小度"],
            note="非核心业务",
        ),
    ]
    return compute_sotp(segments, net_debt, shares, current_price, currency="USD")


def build_alibaba_sotp(
    ecommerce_rev: float,
    cloud_rev: float,
    local_services_rev: float,
    digital_media_rev: float,
    cainiao_rev: float,
    net_debt: float,
    shares: float,
    current_price: float,
) -> SotpResult:
    """
    阿里巴巴 SOTP 模板

    业务线:
    1. 电商 (淘天+国际): PS 2-4x
    2. 阿里云: PS 4-7x (对标 AWS/Azure)
    3. 本地生活 (饿了么+高德): PS 1-2x (亏损)
    4. 数字媒体 (优酷/阿里影业): PS 0.5-1x
    5. 菜鸟物流: PS 1-2x
    """
    segments = [
        SotpSegment(
            name="电商(淘天+国际)",
            revenue=ecommerce_rev,
            growth_rate=0.06,
            valuation_multiple=2.5,
            multiple_type="PS",
            comparable_companies=["PDD", "JD", "Amazon"],
            note="核心业务, 增速放缓",
        ),
        SotpSegment(
            name="阿里云",
            revenue=cloud_rev,
            growth_rate=0.20,
            valuation_multiple=5.0,
            multiple_type="PS",
            comparable_companies=["AWS", "Azure", "Google Cloud"],
            note="AI 驱动增长",
        ),
        SotpSegment(
            name="本地生活",
            revenue=local_services_rev,
            growth_rate=0.15,
            valuation_multiple=1.0,
            multiple_type="PS",
            comparable_companies=["美团", "DoorDash"],
            note="持续亏损, 竞争激烈",
        ),
        SotpSegment(
            name="数字媒体",
            revenue=digital_media_rev,
            growth_rate=0.0,
            valuation_multiple=0.5,
            multiple_type="PS",
            comparable_companies=["iQIYI", "Bilibili"],
            note="非核心",
        ),
        SotpSegment(
            name="菜鸟物流",
            revenue=cainiao_rev,
            growth_rate=0.10,
            valuation_multiple=1.5,
            multiple_type="PS",
            comparable_companies=["SF Express", "ZTO"],
            note="独立上市预期",
        ),
    ]
    return compute_sotp(segments, net_debt, shares, current_price, currency="USD")
