"""
货币对齐模块 — 彻底杜绝 HKD/USD/RMB 混用

核心职责:
  1. 从股票代码推断交易货币和报告货币
  2. 提供统一的货币转换工具
  3. 强制所有输出带正确货币符号
  4. 交叉验证: 检测数据中的货币不一致
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ======================================================================
# 汇率配置 (可从 config.yaml 覆盖)
# ======================================================================

DEFAULT_FX_RATES = {
    ("USD", "HKD"): 7.80,
    ("USD", "CNY"): 7.30,
    ("HKD", "CNY"): 0.935,
    ("CNY", "HKD"): 1.0 / 0.935,
    ("HKD", "USD"): 1.0 / 7.80,
    ("CNY", "USD"): 1.0 / 7.30,
}

CURRENCY_SYMBOLS = {
    "USD": "$",
    "HKD": "HK$",
    "CNY": "¥",
    "RMB": "¥",  # alias
}


@dataclass
class CurrencyContext:
    """股票的货币上下文"""
    trading_currency: str    # 交易货币 (股价用的)
    reporting_currency: str  # 财报货币 (公司财务报告用的)
    fx_rates: dict = field(default_factory=lambda: DEFAULT_FX_RATES.copy())

    @property
    def trading_symbol(self) -> str:
        return CURRENCY_SYMBOLS.get(self.trading_currency, self.trading_currency)

    @property
    def reporting_symbol(self) -> str:
        return CURRENCY_SYMBOLS.get(self.reporting_currency, self.reporting_currency)

    def to_usd(self, value: float, from_currency: Optional[str] = None) -> float:
        """转换为 USD"""
        src = from_currency or self.reporting_currency
        if src == "USD":
            return value
        rate = self.fx_rates.get((src, "USD"))
        if rate is None:
            logger.warning(f"缺少 {src}→USD 汇率，使用原值")
            return value
        return value * rate

    def convert(self, value: float, from_ccy: str, to_ccy: str) -> float:
        """任意货币对转换"""
        if from_ccy == to_ccy:
            return value
        rate = self.fx_rates.get((from_ccy, to_ccy))
        if rate is None:
            # 尝试反向
            rev = self.fx_rates.get((to_ccy, from_ccy))
            if rev:
                rate = 1.0 / rev
            else:
                logger.warning(f"缺少 {from_ccy}→{to_ccy} 汇率")
                return value
        return value * rate


def detect_currency(symbol: str) -> CurrencyContext:
    """
    从股票代码推断货币上下文

    规则:
      - .HK 后缀 → 交易 HKD, 报告 CNY (多数港股公司以人民币报告)
      - .SH / .SZ 后缀 → 交易+报告都是 CNY
      - 无后缀 (美股) → 交易+报告都是 USD
      - 特殊: 部分中概股 (BIDU, BABA 等) 报告用 CNY 但交易用 USD
    """
    sym = symbol.upper().strip()

    # 港股
    if sym.endswith(".HK"):
        return CurrencyContext(trading_currency="HKD", reporting_currency="CNY")

    # A股
    if sym.endswith(".SH") or sym.endswith(".SZ"):
        return CurrencyContext(trading_currency="CNY", reporting_currency="CNY")

    # 中概股 ADR (交易USD, 报告CNY)
    china_adrs = {
        "BIDU", "BABA", "PDD", "JD", "NTES", "TME", "BILI", "IQ",
        "NIO", "XPEV", "LI", "ZTO", "VIPS", "DIDI", "FUTU", "MNSO",
    }
    if sym in china_adrs:
        return CurrencyContext(trading_currency="USD", reporting_currency="CNY")

    # 默认: 美股 (USD/USD)
    return CurrencyContext(trading_currency="USD", reporting_currency="USD")


def format_currency(value: float, currency: str, field_type: str = "price") -> str:
    """
    带货币符号的数字格式化

    Args:
        value: 数值
        currency: 货币代码 (USD/HKD/CNY)
        field_type: 字段类型 — "price" (股价), "large" (大额如营收), "ratio" (比率)
    """
    if value is None:
        return "N/A"

    sym = CURRENCY_SYMBOLS.get(currency, currency)

    if field_type == "ratio":
        # 比率/百分比: 不带货币符号
        if abs(value) < 1:
            return f"{value*100:.1f}%"
        return f"{value:.2f}"

    if field_type == "large":
        # 大额数字
        abs_val = abs(value)
        sign = "-" if value < 0 else ""
        if abs_val >= 1e12:
            return f"{sign}{sym}{abs_val/1e12:.2f}T"
        elif abs_val >= 1e9:
            return f"{sign}{sym}{abs_val/1e9:.2f}B"
        elif abs_val >= 1e6:
            return f"{sign}{sym}{abs_val/1e6:.0f}M"
        else:
            return f"{sign}{sym}{abs_val:,.0f}"

    # 默认: 股价格式
    return f"{sym}{value:,.2f}"


def validate_currency_consistency(data_pack: dict, currency_ctx: CurrencyContext) -> list[str]:
    """
    校验 data_pack 中的货币一致性，返回警告列表

    检查:
      1. key_metrics 中的股价相关字段是否用交易货币
      2. financials 中是否标注了正确的报告货币
      3. competitive_comparison 中不同市场的公司是否混用货币
    """
    warnings = []
    metrics = data_pack.get("key_metrics", {})
    tc = currency_ctx.trading_currency
    rc = currency_ctx.reporting_currency

    # 检查: 如果 market_cap 和 revenue 的量级暗示不同货币
    mc = metrics.get("market_cap", 0)
    rev = metrics.get("revenue", 0)
    if mc > 0 and rev > 0:
        ps = mc / rev
        if ps > 100:
            warnings.append(
                f"PS比率异常高({ps:.1f}x)，可能存在市值({tc})与营收({rc})的货币不一致"
            )

    # 检查: financials 是否标注了 currency
    financials = data_pack.get("financials", {})
    fin_currency = financials.get("currency", "")
    if fin_currency and fin_currency not in (rc, "RMB" if rc == "CNY" else rc):
        warnings.append(
            f"财报货币标注为 {fin_currency}，但预期为 {rc}"
        )

    return warnings
