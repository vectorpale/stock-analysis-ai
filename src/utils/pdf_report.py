"""
PDF 分析报告生成器 — 中文支持 (文泉驿正黑)
"""

import logging
import os
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

logger = logging.getLogger(__name__)

# 字体路径
_FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
_FALLBACK_FONT = "/usr/share/fonts/opentype/unifont/unifont.otf"


class StockReportPDF(FPDF):
    """个股深度分析报告 PDF"""

    def __init__(self, symbol: str, company_name: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.symbol = symbol
        self.company_name = company_name
        self._setup_fonts()
        self.set_auto_page_break(auto=True, margin=20)

    def _setup_fonts(self):
        font_path = _FONT_PATH if os.path.exists(_FONT_PATH) else _FALLBACK_FONT
        self.add_font("zh", "", font_path, uni=True)
        self.add_font("zh", "B", font_path, uni=True)

    def header(self):
        self.set_font("zh", "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, f"{self.symbol} ({self.company_name}) — 多Agent深度分析报告 v2", ln=True, align="C")
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font("zh", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"第 {self.page_no()}/{{nb}} 页  |  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="C")

    def add_title_page(self, result: dict):
        """封面页"""
        self.add_page()
        self.ln(30)

        # 大标题
        self.set_font("zh", "B", 28)
        self.set_text_color(30, 30, 80)
        self.cell(0, 15, f"{self.symbol}", ln=True, align="C")

        self.set_font("zh", "B", 18)
        self.set_text_color(60, 60, 60)
        self.cell(0, 12, self.company_name, ln=True, align="C")

        self.ln(8)
        self.set_font("zh", "", 12)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "多Agent辩论深度分析报告 (v2: SSOT + Fact-Checker)", ln=True, align="C")
        self.cell(0, 8, f"分析时间: {result.get('timestamp', '')[:19]}", ln=True, align="C")

        # CIO 决策 大字
        cio = result.get("phases", {}).get("cio_decision", {})
        rec = cio.get("recommendation", "HOLD")
        conf = cio.get("confidence", 0)

        self.ln(15)
        color_map = {
            "STRONG_BUY": (0, 150, 0), "BUY": (0, 120, 0),
            "HOLD": (180, 150, 0), "SELL": (200, 50, 0), "STRONG_SELL": (200, 0, 0),
        }
        r, g, b = color_map.get(rec, (100, 100, 100))
        self.set_font("zh", "B", 36)
        self.set_text_color(r, g, b)
        self.cell(0, 20, rec, ln=True, align="C")

        self.set_font("zh", "B", 16)
        self.set_text_color(60, 60, 60)
        self.cell(0, 10, f"信心度: {conf}%", ln=True, align="C")

        # 价格和目标
        summary = result.get("data_summary", {})
        cp = summary.get("current_price")
        tp = cio.get("target_price")
        if cp:
            self.ln(5)
            self.set_font("zh", "", 13)
            self.cell(0, 8, f"当前价格: {cp}", ln=True, align="C")
        if tp:
            self.cell(0, 8, f"目标价格: {tp}", ln=True, align="C")

        # SSOT 击球区
        ssot = result.get("ssot_summary", {})
        sm = ssot.get("safety_margin", {})
        wro = ssot.get("win_rate_odds", {})
        if sm or wro:
            self.ln(10)
            self.set_font("zh", "B", 12)
            self.set_text_color(30, 30, 80)
            self.cell(0, 8, "击球区判断", ln=True, align="C")
            self.set_font("zh", "", 11)
            self.set_text_color(60, 60, 60)
            if sm:
                status = "达标" if sm.get("meets_threshold") else "不达标"
                self.cell(0, 7, f"安全边际: {sm.get('margin_pct', 'N/A')}% ({status}, 阈值≥30%)", ln=True, align="C")
            if wro:
                wr = wro.get("win_rate", 0) * 100
                od = wro.get("odds_ratio", 0)
                self.cell(0, 7, f"胜率: {wr}% ({'达标' if wr >= 60 else '不达标'}) | 赔率: {od}:1 ({'达标' if od >= 2 else '不达标'})", ln=True, align="C")

    def _section_title(self, title: str, color=(30, 30, 80)):
        self.ln(5)
        self.set_font("zh", "B", 14)
        self.set_text_color(*color)
        self.cell(0, 10, title, ln=True)
        self.set_draw_color(30, 30, 80)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)

    def _sub_title(self, title: str):
        self.set_font("zh", "B", 11)
        self.set_text_color(40, 40, 40)
        self.cell(0, 8, title, ln=True)

    def _body_text(self, text: str):
        self.set_font("zh", "", 10)
        self.set_text_color(30, 30, 30)
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                self.ln(2)
                continue
            self.set_x(self.l_margin)
            try:
                self.multi_cell(0, 5.5, line)
            except Exception:
                self.ln()
                self.set_x(self.l_margin)
                self.multi_cell(0, 5.5, line[:200])

    def _key_value(self, key: str, value, bold_value=False):
        self.set_x(self.l_margin)
        self.set_font("zh", "B", 10)
        self.set_text_color(60, 60, 60)
        kw = min(self.get_string_width(f"{key}: ") + 2, 60)
        self.cell(kw, 6, f"{key}: ")
        style = "B" if bold_value else ""
        self.set_font("zh", style, 10)
        self.set_text_color(30, 30, 30)
        remaining_w = self.w - self.get_x() - self.r_margin
        if remaining_w < 30:
            self.ln()
            self.set_x(self.l_margin + 5)
        try:
            self.multi_cell(0, 6, str(value))
        except Exception:
            self.ln()
            self.set_x(self.l_margin + 5)
            self.multi_cell(0, 6, str(value)[:200])

    def _bullet(self, text: str, indent=5):
        self.set_x(self.l_margin + indent)
        self.set_font("zh", "", 10)
        self.set_text_color(30, 30, 30)
        try:
            self.multi_cell(0, 5.5, f"  {text}")
        except Exception:
            self.ln()
            self.set_x(self.l_margin + indent)
            self.multi_cell(0, 5.5, text[:200])

    def add_ssot_page(self, result: dict):
        """SSOT 财务事实清单页"""
        self.add_page()
        self._section_title("SSOT 财务事实清单 (Python 预计算)")

        ssot = result.get("ssot_summary", {})
        if not ssot:
            self._body_text("SSOT 数据不可用")
            return

        self._sub_title("核心比率")
        kr = ssot.get("key_ratios", {})
        for k, label in [("pe_ttm", "PE(TTM)"), ("pe_forward", "前瞻PE"),
                         ("ps_ttm", "PS(TTM)"), ("pb", "PB"),
                         ("roe", "ROE"), ("gross_margin", "毛利率"),
                         ("net_margin", "净利率"), ("revenue_growth", "营收增速"),
                         ("fcf_yield", "FCF Yield")]:
            v = kr.get(k)
            if v is not None:
                if k in ("gross_margin", "net_margin", "revenue_growth", "fcf_yield", "roe"):
                    self._key_value(label, f"{v*100:.1f}%")
                else:
                    self._key_value(label, f"{v:.2f}")

        sm = ssot.get("safety_margin", {})
        if sm:
            self.ln(3)
            self._sub_title("安全边际")
            self._key_value("安全边际", f"{sm.get('margin_pct', 'N/A')}%", bold_value=True)
            self._key_value("公允价值", sm.get("fair_value", "N/A"))
            self._key_value("达标", "是" if sm.get("meets_threshold") else "否 (阈值≥30%)")

        wro = ssot.get("win_rate_odds", {})
        if wro:
            self.ln(3)
            self._sub_title("胜率赔率模型")
            self._key_value("胜率", f"{wro.get('win_rate', 0)*100:.0f}% (阈值≥60%)")
            self._key_value("赔率", f"{wro.get('odds_ratio', 'N/A')}:1 (阈值≥2:1)")

        fcf = ssot.get("fcf_analysis", {})
        if fcf:
            self.ln(3)
            self._sub_title("自由现金流分析")
            for k, label in [("fcf", "FCF"), ("operating_cf", "经营现金流"),
                              ("capex", "资本支出"), ("cf_to_ni_ratio", "CF/NI比率")]:
                v = fcf.get(k)
                if v is not None:
                    self._key_value(label, f"{v:,.0f}" if abs(v) > 100 else f"{v:.2f}")

    def add_fact_checker_page(self, result: dict):
        """Fact-Checker 核查报告页"""
        fc1 = result.get("phases", {}).get("fact_check_round_1", {})
        fc2 = result.get("phases", {}).get("fact_check_round_2", {})
        if not fc1 and not fc2:
            return

        self.add_page()
        self._section_title("Fact-Checker 核查报告")

        for label, fc in [("第一轮核查 (独立分析后)", fc1), ("第二轮核查 (辩论后)", fc2)]:
            if not fc:
                continue
            self._sub_title(label)
            self._key_value("通过", fc.get("verified", 0))
            self._key_value("警告", fc.get("warnings", 0))
            self._key_value("拒绝", fc.get("rejected", 0))
            if fc.get("veto_triggered"):
                self.set_font("zh", "B", 11)
                self.set_text_color(200, 0, 0)
                self.cell(0, 8, "*** 一票否决已触发 ***", ln=True)
            if fc.get("summary"):
                self._body_text(fc["summary"])
            self.ln(5)

    def add_cio_decision_page(self, result: dict):
        """CIO 投资决策详情页"""
        self.add_page()
        cio = result.get("phases", {}).get("cio_decision", {})
        self._section_title("CIO 投资决策")

        rec = cio.get("recommendation", "N/A")
        color_map = {
            "STRONG_BUY": (0, 150, 0), "BUY": (0, 120, 0),
            "HOLD": (180, 150, 0), "SELL": (200, 50, 0), "STRONG_SELL": (200, 0, 0),
        }
        r, g, b = color_map.get(rec, (100, 100, 100))
        self.set_font("zh", "B", 16)
        self.set_text_color(r, g, b)
        self.cell(0, 10, f"建议: {rec}  |  信心: {cio.get('confidence', 0)}%", ln=True)
        self.set_text_color(30, 30, 30)

        self.ln(3)
        for k, label in [("target_price", "目标价"), ("stop_loss", "止损位"),
                         ("time_horizon", "时间维度"), ("position_size_pct", "建议仓位%")]:
            v = cio.get(k)
            if v:
                self._key_value(label, v)

        es = cio.get("executive_summary", "")
        if es:
            self.ln(3)
            self._sub_title("投资结论")
            self._body_text(es)

        for label, key in [("核心多头论点", "key_bull_arguments"),
                           ("核心空头论点", "key_bear_arguments"),
                           ("决定性因素", "decisive_factors")]:
            items = cio.get(key, [])
            if items:
                self.ln(3)
                self._sub_title(label)
                for item in items:
                    self._bullet(str(item))

        # 交易信号
        signal = cio.get("trading_signal", {})
        if signal:
            self.ln(3)
            self._sub_title("交易信号")
            self._key_value("交易动作", signal.get("action", "N/A"))
            self._key_value("紧迫程度", signal.get("urgency", "N/A"))
            if signal.get("entry_strategy"):
                self._key_value("入场策略", signal["entry_strategy"])
            exit_plan = signal.get("exit_plan", {})
            if exit_plan:
                tp1 = exit_plan.get("take_profit_1", {})
                tp2 = exit_plan.get("take_profit_2", {})
                sl = exit_plan.get("stop_loss", {})
                if tp1:
                    self._key_value("止盈1", f"价格 {tp1.get('price', 'N/A')} → 减仓 {tp1.get('sell_pct', 'N/A')}%")
                if tp2:
                    self._key_value("止盈2", f"价格 {tp2.get('price', 'N/A')} → 减仓 {tp2.get('sell_pct', 'N/A')}%")
                if sl:
                    self._key_value("止损", f"价格 {sl.get('price', 'N/A')} → 清仓 {sl.get('sell_pct', 'N/A')}%")

    def add_analysts_page(self, result: dict):
        """各分析师立场详情页"""
        self.add_page()
        self._section_title("各分析师最终立场 (经CIO拷问后)")

        final_pos = result.get("phases", {}).get("post_challenge_positions",
                    result.get("phases", {}).get("final_positions", {}))

        for agent_key, pos in final_pos.items():
            name = pos.get("agent_name", agent_key)
            title = pos.get("agent_title", "")
            position = pos.get("position", 0)
            confidence = pos.get("confidence", 0)

            # 颜色
            if position > 20:
                self.set_text_color(0, 120, 0)
            elif position < -20:
                self.set_text_color(200, 50, 0)
            else:
                self.set_text_color(180, 150, 0)

            self.set_font("zh", "B", 11)
            self.cell(0, 7, f"{name} ({title}):  立场 {position:+d},  信心 {confidence}%", ln=True)
            self.set_text_color(30, 30, 30)

            analysis = pos.get("analysis", "")
            if analysis:
                self.set_font("zh", "", 9)
                self.multi_cell(0, 5, analysis[:500])

            points = pos.get("key_points", [])
            if points:
                self.set_font("zh", "", 9)
                for p in points[:3]:
                    self._bullet(str(p), indent=3)

            self.ln(4)

        # 共识
        self.ln(3)
        self._key_value("加权综合得分", f"{result.get('weighted_score', 0):+.1f}")
        self._key_value("共识水平", result.get("consensus", "N/A"))

    def add_contrarian_page(self, result: dict):
        """反共识分析 + CIO拷问页"""
        contrarian = result.get("phases", {}).get("contrarian_analysis", {})
        challenge = result.get("phases", {}).get("cio_challenge", {})
        if not contrarian and not challenge:
            return

        self.add_page()
        self._section_title("共识 vs 反共识分析")

        # CIO 共识/反共识判断
        cvc = result.get("phases", {}).get("cio_decision", {}).get("consensus_vs_contrarian", {})
        if cvc:
            self._sub_title("CIO 共识/反共识判断")
            self._key_value("共识观点", f"({cvc.get('consensus_probability', '?')}%) {cvc.get('consensus_view', 'N/A')}")
            self._key_value("反共识观点", f"({cvc.get('contrarian_probability', '?')}%) {cvc.get('contrarian_view', 'N/A')}")
            if cvc.get("cio_independent_judgment"):
                self._key_value("CIO独立判断", cvc["cio_independent_judgment"])
            self.ln(5)

        # Devil's Advocate
        if contrarian.get("contrarian_thesis"):
            self._sub_title("Devil's Advocate 反共识论证")
            self._key_value("反共识立场", contrarian.get("contrarian_position", "N/A"))
            self._key_value("概率评估", f"{contrarian.get('probability_estimate', '?')}%")
            prob_just = contrarian.get("probability_justification", "")
            if prob_just:
                self._key_value("概率依据", prob_just)
            # 证据质量评级
            eq = contrarian.get("evidence_quality_summary", {})
            if eq:
                grade = eq.get("overall_evidence_grade", "未评级")
                s = eq.get("strong_count", 0)
                m = eq.get("moderate_count", 0)
                w = eq.get("weak_count", 0)
                self._key_value("证据质量", f"{grade} (strong:{s} / moderate:{m} / weak:{w})")
                honest = eq.get("honest_assessment", "")
                if honest:
                    self._key_value("诚实自评", honest)
            self._key_value("核心价格驱动", contrarian.get("key_price_driver", "N/A"))
            self._body_text(contrarian.get("contrarian_thesis", ""))
            self.ln(5)

        # CIO 拷问
        if challenge.get("challenges"):
            self._sub_title("CIO 拷问记录")
            self._key_value("核心假设", challenge.get("core_assumption", "N/A"))
            for i, ch in enumerate(challenge["challenges"], 1):
                self.set_x(self.l_margin)
                self.set_font("zh", "B", 10)
                self.set_text_color(30, 30, 80)
                q_text = ch.get('question', '') if isinstance(ch, dict) else str(ch)
                self.multi_cell(0, 6, f"Q{i}: {q_text}")
                if isinstance(ch, dict):
                    self.set_x(self.l_margin + 3)
                    self.set_font("zh", "", 9)
                    self.set_text_color(100, 100, 100)
                    self.multi_cell(0, 5, f"  针对: {ch.get('target', '全体')} | 关键性: {ch.get('why_critical', '')}")
                self.ln(2)

    def add_risk_page(self, result: dict):
        """风控审核页"""
        risk = result.get("phases", {}).get("risk_committee", {})
        if not risk:
            return

        self.add_page()
        self._section_title("风控委员会审核 (绝对收益基准)")

        verdict = risk.get("verdict", "N/A")
        rl = risk.get("risk_level", "N/A")

        v_color = {"APPROVE": (0, 120, 0), "APPROVE_WITH_CONDITIONS": (180, 150, 0), "VETO": (200, 0, 0)}
        r, g, b = v_color.get(verdict, (100, 100, 100))
        self.set_font("zh", "B", 14)
        self.set_text_color(r, g, b)
        self.cell(0, 10, f"审核结论: {verdict}  |  风险等级: {rl}", ln=True)
        self.set_text_color(30, 30, 30)
        self.ln(3)

        self._key_value("最大仓位", f"{risk.get('max_position_pct', 'N/A')}%")
        if risk.get("veto_reason"):
            self._key_value("否决理由", risk["veto_reason"])
        if risk.get("safety_margin_check"):
            self._key_value("安全边际检查", risk["safety_margin_check"])
        if risk.get("win_rate_odds_check"):
            self._key_value("胜率赔率检查", risk["win_rate_odds_check"])
        if risk.get("absolute_return_assessment"):
            self._key_value("绝对收益评估", risk["absolute_return_assessment"])
        if risk.get("max_drawdown_estimate"):
            self._key_value("最大回撤估算", risk["max_drawdown_estimate"])

        conditions = risk.get("conditions", [])
        if conditions:
            self.ln(3)
            self._sub_title("建仓条件")
            for c in conditions:
                self._bullet(str(c))

        monitoring = risk.get("monitoring_points", [])
        if monitoring:
            self.ln(3)
            self._sub_title("持续监控")
            for m in monitoring:
                self._bullet(str(m))

    def add_pair_trade_page(self, result: dict):
        """配对交易策略页"""
        pair = result.get("phases", {}).get("pair_trade", {})
        if not pair:
            return

        self.add_page()
        self._section_title("配对交易策略 (Long/Short)")

        if not pair.get("has_recommendation"):
            self._body_text(f"无配对推荐: {pair.get('no_recommendation_reason', '未给出原因')}")
            return

        self._key_value("策略名称", pair.get("strategy_name", "N/A"))
        self._key_value("配对类型", pair.get("pair_type", "N/A"))
        self._key_value("核心逻辑", pair.get("thesis", "N/A"))
        self.ln(3)

        long_leg = pair.get("long_leg", {})
        short_leg = pair.get("short_leg", {})

        self.set_font("zh", "B", 11)
        self.set_text_color(0, 120, 0)
        self.cell(0, 7, f"LONG  {long_leg.get('symbol', '?')} ({long_leg.get('company_name', '')})", ln=True)
        self.set_text_color(30, 30, 30)
        self.set_font("zh", "", 10)
        self._body_text(f"  理由: {long_leg.get('rationale', 'N/A')}")

        self.set_font("zh", "B", 11)
        self.set_text_color(200, 50, 0)
        self.cell(0, 7, f"SHORT {short_leg.get('symbol', '?')} ({short_leg.get('company_name', '')})", ln=True)
        self.set_text_color(30, 30, 30)
        self.set_font("zh", "", 10)
        self._body_text(f"  理由: {short_leg.get('rationale', 'N/A')}")

        execution = pair.get("execution", {})
        if execution:
            self.ln(3)
            self._sub_title("执行计划")
            for k, label in [("entry_timing", "入场时机"), ("holding_period", "持有周期"),
                             ("profit_target", "目标收益"), ("stop_loss", "止损条件")]:
                v = execution.get(k)
                if v:
                    self._key_value(label, v)


def generate_pdf_report(result: dict, output_path: str) -> str:
    """
    从分析结果生成 PDF 报告

    Args:
        result: DebateEngine.analyze() 返回的完整结果字典
        output_path: 输出 PDF 文件路径

    Returns:
        输出文件路径
    """
    symbol = result.get("symbol", "UNKNOWN")
    company_name = result.get("data_summary", {}).get("company_name", symbol)

    pdf = StockReportPDF(symbol, company_name)
    pdf.alias_nb_pages()

    # 1. 封面
    pdf.add_title_page(result)

    # 2. SSOT 财务事实清单
    pdf.add_ssot_page(result)

    # 3. Fact-Checker 核查
    pdf.add_fact_checker_page(result)

    # 4. CIO 投资决策
    pdf.add_cio_decision_page(result)

    # 5. 各分析师立场
    pdf.add_analysts_page(result)

    # 6. 反共识 + CIO 拷问
    pdf.add_contrarian_page(result)

    # 7. 风控审核
    pdf.add_risk_page(result)

    # 8. 配对交易
    pdf.add_pair_trade_page(result)

    # 输出
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(output_path)
    logger.info(f"PDF 报告已生成: {output_path}")
    return output_path
