"""
Fact-Checker — 独立数据核查 Agent (一票否决权)

核心职责:
  拦截辩论中无财报支撑的论点，杜绝数据幻觉和线性外推。

工作原理:
  1. 持有 SSOT 计算的「财务事实」作为 ground truth
  2. 逐条核查每个 Agent 声称的财务数字
  3. 偏差 > 5% 标红，> 20% 触发一票否决
  4. 检测线性外推 (如 "增速维持3年")
  5. 检测未标注来源的定性断言

使用模型: Opus 4.6 (与 CIO 同级，确保最高准确度)
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ClaimVerification:
    """单条论据的核查结果"""
    agent_name: str
    claim_text: str
    claim_type: str             # "financial_number" / "growth_projection" / "qualitative"
    ssot_reference: Optional[str]  # SSOT 中的对应数据
    ssot_value: Optional[float]    # SSOT 值
    claimed_value: Optional[float] # Agent 声称的值
    deviation_pct: Optional[float] # 偏差百分比
    verdict: str                   # "VERIFIED" / "WARNING" / "REJECTED"
    reason: str


@dataclass
class FactCheckReport:
    """核查报告"""
    verified_claims: list[ClaimVerification] = field(default_factory=list)
    warning_claims: list[ClaimVerification] = field(default_factory=list)
    rejected_claims: list[ClaimVerification] = field(default_factory=list)
    veto_triggered: bool = False
    veto_reason: Optional[str] = None
    summary: str = ""


class FactChecker:
    """
    Fact-Checker: 独立核查所有 Agent 的财务论据

    持有 SSOT 数据作为 ground truth，通过规则引擎 + LLM 辅助
    逐条验证 Agent 输出中的财务声明。
    """

    # 偏差阈值
    WARNING_THRESHOLD = 0.05   # 5% 偏差 → 警告
    REJECT_THRESHOLD = 0.20    # 20% 偏差 → 拒绝
    VETO_THRESHOLD = 0.50      # 50% 偏差 on 关键指标 → 一票否决

    # 关键指标 (偏差大则触发否决)
    CRITICAL_METRICS = {
        "pe_ratio", "pe_ttm", "ps_ratio", "ps_ttm", "market_cap",
        "revenue", "net_income", "free_cash_flow", "safety_margin",
    }

    def __init__(self, ssot_dict: dict):
        """
        Args:
            ssot_dict: get_ssot_summary_dict() 的输出
        """
        self.ssot = ssot_dict
        self.key_ratios = ssot_dict.get("key_ratios", {})
        self.valuation = ssot_dict.get("valuation", {})
        self.safety = ssot_dict.get("safety_margin", {})
        self.fcf = ssot_dict.get("fcf_analysis", {})
        self.price = ssot_dict.get("current_price", 0)

        # 构建可查找的数值映射表
        self._build_lookup()

    def _build_lookup(self):
        """构建 SSOT 数值查找表"""
        self.lookup = {}

        # 价格相关
        self.lookup["current_price"] = self.price
        self.lookup["price"] = self.price

        # 核心比率
        for k, v in self.key_ratios.items():
            if v is not None:
                self.lookup[k] = v
                # 别名
                if k == "pe_ttm":
                    self.lookup["pe_ratio"] = v
                    self.lookup["pe"] = v
                if k == "ps_ttm":
                    self.lookup["ps_ratio"] = v
                    self.lookup["ps"] = v

        # 估值
        if self.valuation:
            self.lookup["fair_value"] = self.valuation.get("fair_value")
            self.lookup["target_bull"] = self.valuation.get("target_bull")
            self.lookup["target_base"] = self.valuation.get("target_base")
            self.lookup["target_bear"] = self.valuation.get("target_bear")
            self.lookup["upside_pct"] = self.valuation.get("upside_pct")

        # 安全边际
        if self.safety:
            self.lookup["safety_margin"] = self.safety.get("margin_pct")

        # FCF
        if self.fcf:
            self.lookup["annual_fcf"] = self.fcf.get("annual_fcf")
            self.lookup["fcf_yield"] = self.fcf.get("fcf_yield")

    def _extract_numbers(self, text: str) -> list[tuple[str, float]]:
        """
        从文本中提取数字和它们的上下文

        Returns:
            list of (context_snippet, number_value)
        """
        results = []

        # 匹配模式: 各种数字格式
        patterns = [
            # PE 15.2x, PE15.2倍
            (r'(?:PE|pe|市盈率)[:\s]*(\d+\.?\d*)\s*[x倍]?', "pe"),
            # PS 3.5x
            (r'(?:PS|ps|市销率)[:\s]*(\d+\.?\d*)\s*[x倍]?', "ps"),
            # PB 2.1x
            (r'(?:PB|pb|市净率)[:\s]*(\d+\.?\d*)\s*[x倍]?', "pb"),
            # 安全边际 30%
            (r'安全边际[:\s]*(\d+\.?\d*)%', "safety_margin"),
            # 胜率 65%
            (r'胜率[:\s]*(\d+\.?\d*)%', "win_rate"),
            # 赔率 2.5:1
            (r'赔率[:\s]*(\d+\.?\d*)\s*:\s*1', "odds_ratio"),
            # 营收增速 15.2%
            (r'(?:营收增速|营收增长|收入增速)[:\s]*(\d+\.?\d*)%', "revenue_growth_pct"),
            # FCF yield 8%
            (r'(?:FCF[_ ]?yield|FCF收益率)[:\s]*(\d+\.?\d*)%', "fcf_yield_pct"),
            # ROE 20.7%
            (r'(?:ROE|roe)[:\s]*(\d+\.?\d*)%', "roe_pct"),
            # 毛利率 38.4%
            (r'毛利率[:\s]*(\d+\.?\d*)%', "gross_margin_pct"),
            # 净利率
            (r'净利率[:\s]*(\d+\.?\d*)%', "net_margin_pct"),
            # $XXX.XX or HK$XX.XX
            (r'(?:目标价|target)[:\s]*(?:HK)?\$(\d+\.?\d*)', "target_price"),
            # 市值 $XXB or ¥XXXB
            (r'市值[:\s]*(?:HK)?\$?¥?(\d+\.?\d*)\s*[BbTt]', "market_cap_ref"),
        ]

        for pattern, label in patterns:
            matches = re.finditer(pattern, text)
            for m in matches:
                try:
                    val = float(m.group(1))
                    results.append((label, val))
                except (ValueError, IndexError):
                    pass

        return results

    def _check_number(self, metric_name: str, claimed_value: float) -> ClaimVerification:
        """
        核查单个数字是否与 SSOT 一致
        """
        # 查找 SSOT 中的参考值
        ssot_value = None
        ssot_ref = None

        # 处理百分比转换
        if metric_name.endswith("_pct"):
            base_name = metric_name[:-4]
            ssot_raw = self.lookup.get(base_name)
            if ssot_raw is not None:
                ssot_value = ssot_raw * 100  # SSOT 存的是小数，转百分比
                ssot_ref = f"SSOT.{base_name} = {ssot_raw} ({ssot_value:.1f}%)"
        else:
            ssot_value = self.lookup.get(metric_name)
            if ssot_value is not None:
                ssot_ref = f"SSOT.{metric_name} = {ssot_value}"

        if ssot_value is None:
            return ClaimVerification(
                agent_name="",
                claim_text=f"{metric_name} = {claimed_value}",
                claim_type="financial_number",
                ssot_reference=None,
                ssot_value=None,
                claimed_value=claimed_value,
                deviation_pct=None,
                verdict="WARNING",
                reason=f"SSOT 中无 {metric_name} 的参考值，无法核查",
            )

        # 计算偏差
        if ssot_value == 0:
            deviation = abs(claimed_value) if claimed_value != 0 else 0
        else:
            deviation = abs(claimed_value - ssot_value) / abs(ssot_value)

        # 判定
        is_critical = metric_name.replace("_pct", "") in self.CRITICAL_METRICS

        if deviation <= self.WARNING_THRESHOLD:
            verdict = "VERIFIED"
            reason = f"偏差 {deviation*100:.1f}% ≤ 5% (达标)"
        elif deviation <= self.REJECT_THRESHOLD:
            verdict = "WARNING"
            reason = f"偏差 {deviation*100:.1f}% (5%-20%区间，需注意)"
        else:
            verdict = "REJECTED"
            reason = f"偏差 {deviation*100:.1f}% > 20% (严重偏离 SSOT)"

        return ClaimVerification(
            agent_name="",
            claim_text=f"{metric_name} = {claimed_value}",
            claim_type="financial_number",
            ssot_reference=ssot_ref,
            ssot_value=ssot_value,
            claimed_value=claimed_value,
            deviation_pct=round(deviation * 100, 1),
            verdict=verdict,
            reason=reason,
        )

    def _check_linear_extrapolation(self, text: str) -> list[ClaimVerification]:
        """检测线性外推"""
        warnings = []

        # 常见线性外推模式
        patterns = [
            (r'(?:维持|保持|持续)\s*(\d+)\s*(?:年|个季度)', "线性外推: 假设增速维持"),
            (r'(?:连续|每年)\s*(\d+)%\s*(?:增长|增速)', "线性外推: 假设固定增速"),
            (r'(?:必将|一定会|肯定能)\s*(?:实现|达到|突破)', "确定性断言: 使用了过于绝对的表述"),
        ]

        for pattern, reason in patterns:
            matches = re.finditer(pattern, text)
            for m in matches:
                warnings.append(ClaimVerification(
                    agent_name="",
                    claim_text=m.group(0),
                    claim_type="growth_projection",
                    ssot_reference=None,
                    ssot_value=None,
                    claimed_value=None,
                    deviation_pct=None,
                    verdict="WARNING",
                    reason=reason,
                ))

        return warnings

    def validate_agent_output(
        self,
        agent_name: str,
        agent_output: dict,
    ) -> list[ClaimVerification]:
        """
        核查单个 Agent 的输出

        Args:
            agent_name: Agent 名称
            agent_output: Agent 的 JSON 输出

        Returns:
            核查结果列表
        """
        results = []

        # 提取分析文本
        analysis_text = agent_output.get("analysis", "")
        key_points = agent_output.get("key_points", [])
        full_text = analysis_text + " " + " ".join(key_points)

        # 1. 提取并核查数字
        numbers = self._extract_numbers(full_text)
        for metric_name, value in numbers:
            check = self._check_number(metric_name, value)
            check.agent_name = agent_name
            results.append(check)

        # 2. 检测线性外推
        extrapolations = self._check_linear_extrapolation(full_text)
        for e in extrapolations:
            e.agent_name = agent_name
            results.append(e)

        return results

    def validate_debate_round(
        self,
        all_agent_outputs: dict[str, dict],
    ) -> FactCheckReport:
        """
        批量核查一轮辩论的所有 Agent 输出

        Args:
            all_agent_outputs: {agent_key: agent_output_dict}

        Returns:
            FactCheckReport
        """
        report = FactCheckReport()

        for agent_key, output in all_agent_outputs.items():
            agent_name = output.get("agent_name", agent_key)
            checks = self.validate_agent_output(agent_name, output)

            for c in checks:
                if c.verdict == "VERIFIED":
                    report.verified_claims.append(c)
                elif c.verdict == "WARNING":
                    report.warning_claims.append(c)
                elif c.verdict == "REJECTED":
                    report.rejected_claims.append(c)

        # 检查是否触发一票否决
        report.veto_triggered, report.veto_reason = self._check_veto(report.rejected_claims)

        # 生成摘要
        report.summary = self._generate_summary(report)

        return report

    def _check_veto(self, rejected: list[ClaimVerification]) -> tuple[bool, Optional[str]]:
        """
        检查是否触发一票否决

        条件: 关键指标偏差 > 50%
        """
        for claim in rejected:
            metric = claim.claim_text.split("=")[0].strip() if "=" in claim.claim_text else ""
            metric_base = metric.replace("_pct", "")

            if metric_base in self.CRITICAL_METRICS:
                if claim.deviation_pct and claim.deviation_pct > self.VETO_THRESHOLD * 100:
                    reason = (
                        f"一票否决: {claim.agent_name} 的 {claim.claim_text} "
                        f"与 SSOT ({claim.ssot_reference}) 偏差 {claim.deviation_pct:.1f}%"
                    )
                    logger.warning(f"Fact-Checker VETO: {reason}")
                    return True, reason

        return False, None

    def _generate_summary(self, report: FactCheckReport) -> str:
        """生成核查摘要"""
        total = (len(report.verified_claims) +
                 len(report.warning_claims) +
                 len(report.rejected_claims))

        lines = []
        lines.append(f"Fact-Checker 核查报告: 共核查 {total} 条论据")
        lines.append(f"  通过: {len(report.verified_claims)}")
        lines.append(f"  警告: {len(report.warning_claims)}")
        lines.append(f"  拒绝: {len(report.rejected_claims)}")

        if report.veto_triggered:
            lines.append(f"\n  *** 一票否决已触发 ***")
            lines.append(f"  原因: {report.veto_reason}")

        if report.rejected_claims:
            lines.append(f"\n被拒绝的论据:")
            for c in report.rejected_claims:
                lines.append(f"  - [{c.agent_name}] {c.claim_text}")
                lines.append(f"    SSOT: {c.ssot_reference}")
                lines.append(f"    偏差: {c.deviation_pct:.1f}%")

        if report.warning_claims:
            lines.append(f"\n需注意的论据:")
            for c in report.warning_claims[:5]:  # 只显示前5条
                lines.append(f"  - [{c.agent_name}] {c.reason}")

        return "\n".join(lines)


def format_fact_check_for_prompt(report: FactCheckReport) -> str:
    """
    将核查报告格式化为可嵌入 prompt 的文本
    """
    return report.summary
