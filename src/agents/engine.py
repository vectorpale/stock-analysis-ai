"""
多Agent辩论引擎 - 个股深度分析
四阶段流水线: 独立分析 → 多轮辩论 → 风控审核 → CIO 决策

参考:
- Du et al. "Improving Factuality and Reasoning in LLMs through Multi-Agent Debate" (2023)
- TradingAgents: Multi-Agents LLM Financial Trading Framework (2024)
- FinMem: A Performance-Enhanced LLM Trading Agent with Layered Memory (2024)
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

import yaml
from anthropic import Anthropic

from src.agents.definitions import (
    AGENT_ROLES,
    CHALLENGE_RESPONSE_PROMPT,
    CIO_CHALLENGE_PROMPT,
    CIO_CHALLENGE_SYSTEM_PROMPT,
    CIO_DECISION_PROMPT,
    CIO_SYSTEM_PROMPT,
    CONTRARIAN_ANALYSIS_PROMPT,
    CONTRARIAN_SYSTEM_PROMPT,
    DEBATE_ROUND_PROMPT,
    INDEPENDENT_ANALYSIS_PROMPT,
    PAIR_TRADE_PROMPT,
    PAIR_TRADE_SYSTEM_PROMPT,
    RISK_COMMITTEE_PROMPT,
)
from src.agents.memory import AnalysisMemory
from src.data.fetcher import DataFetcher
from src.data.industry import IndustryAnalyzer
from src.data.news import NewsCollector
from src.utils.helpers import (
    compute_consensus_label,
    compute_convergence_score,
    format_financials_text,
    format_metrics_text,
    format_technical_text,
    parse_json_response,
    weighted_score_aggregation,
)

logger = logging.getLogger(__name__)


class DebateEngine:
    """多Agent辩论引擎"""

    def __init__(self, config_path: str = "config/config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ValueError(
                "未设置 ANTHROPIC_API_KEY 环境变量。\n"
                "请通过以下方式之一设置:\n"
                "  1. 创建 .env 文件: echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env\n"
                "  2. 导出环境变量: export ANTHROPIC_API_KEY=sk-ant-...\n"
                "  3. GitHub Codespace: Settings → Secrets → 添加 ANTHROPIC_API_KEY"
            )
        self.client = Anthropic(api_key=api_key)

        # 模型配置
        models = self.config.get("models", {})
        self.cio_model = models.get("cio", "claude-opus-4-20250514")
        self.analyst_model = models.get("analyst", "claude-sonnet-4-20250514")
        self.data_model = models.get("data_extract", "claude-haiku-4-5-20251001")

        # 辩论参数
        debate_cfg = self.config.get("debate", {})
        self.max_rounds = debate_cfg.get("max_rounds", 3)
        self.convergence_threshold = debate_cfg.get("convergence_threshold", 0.80)

        # Agent 权重
        self.agent_weights = self.config.get("agent_weights", {})

        # 子模块
        data_cfg = self.config.get("data", {})
        self.fetcher = DataFetcher(cache_hours=data_cfg.get("cache_hours", 6))
        self.industry_analyzer = IndustryAnalyzer(config_path)
        self.news_collector = NewsCollector()
        self.memory = AnalysisMemory()

        # Agent 键列表 (不含 risk_manager, CIO 独立)
        self.debate_agent_keys = [
            "fundamental_bull",
            "fundamental_bear",
            "industry_analyst",
            "financial_analyst",
            "macro_strategist",
        ]

    # ==================================================================
    # 主入口
    # ==================================================================
    def analyze(self, symbol: str, callbacks: Optional[dict] = None) -> dict:
        """
        对指定个股进行完整的多Agent深度分析

        Args:
            symbol: 股票代码 (如 NVDA, 0700.HK, 002230.SZ)
            callbacks: 可选的回调函数 dict，用于实时通知进度
                - on_phase(phase_name: str)
                - on_agent(agent_name: str, agent_title: str)
                - on_round(round_num: int)
                - on_message(message: str)

        Returns:
            完整分析结果字典
        """
        cb = callbacks or {}
        notify = lambda phase: cb.get("on_phase", lambda x: None)(phase)
        msg = lambda text: cb.get("on_message", lambda x: None)(text)

        result = {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "phases": {},
        }

        # ============================================================
        # Phase 0: 数据收集
        # ============================================================
        notify("数据收集")
        msg("正在收集个股数据...")
        data_pack = self._collect_data(symbol)
        result["data_summary"] = {
            "company_name": data_pack["key_metrics"].get("company_name", symbol),
            "sector": data_pack["key_metrics"].get("sector", ""),
            "industry": data_pack["key_metrics"].get("industry", ""),
            "current_price": data_pack["technical_indicators"].get("current_price"),
            "competitors_count": len(data_pack["competitive_comparison"].get("comparison_table", [])) - 1,
        }
        msg(f"数据收集完成: {result['data_summary']['company_name']}")

        # ============================================================
        # Phase 1: 独立分析 (防止锚定偏差)
        # ============================================================
        notify("独立分析")
        msg("各分析师正在独立分析...")
        agent_results = {}
        for agent_key in self.debate_agent_keys:
            agent_info = AGENT_ROLES[agent_key]
            agent_cb = cb.get("on_agent")
            if agent_cb:
                agent_cb(agent_info["name"], agent_info["title"])

            analysis = self._run_agent_analysis(
                agent_key=agent_key,
                data_pack=data_pack,
            )
            agent_results[agent_key] = analysis
            msg(f"  {agent_info['name']}({agent_info['title']}): "
                f"立场 {analysis.get('position', 0):+d}, "
                f"信心 {analysis.get('confidence', 0)}%")

        result["phases"]["independent_analysis"] = agent_results

        # ============================================================
        # Phase 2: 多轮辩论 (Read-Critique-Update)
        # ============================================================
        notify("多轮辩论")
        debate_history = []
        for round_num in range(2, self.max_rounds + 1):
            round_cb = cb.get("on_round")
            if round_cb:
                round_cb(round_num)
            msg(f"辩论第 {round_num} 轮...")

            round_results = {}
            for agent_key in self.debate_agent_keys:
                agent_info = AGENT_ROLES[agent_key]
                updated = self._run_debate_round(
                    agent_key=agent_key,
                    round_num=round_num,
                    my_previous=agent_results[agent_key],
                    all_results=agent_results,
                )
                round_results[agent_key] = updated
                msg(f"  {agent_info['name']}: "
                    f"立场 {updated.get('position', 0):+d}, "
                    f"信心 {updated.get('confidence', 0)}%")

            agent_results = round_results
            debate_history.append(round_results)

            # 收敛检测
            convergence = compute_convergence_score(
                [agent_results[k] for k in self.debate_agent_keys]
            )
            msg(f"  收敛分数: {convergence:.3f} (阈值: {self.convergence_threshold})")
            if convergence >= self.convergence_threshold:
                msg("辩论已收敛，提前结束。")
                break

        result["phases"]["debate_rounds"] = debate_history
        result["phases"]["final_positions"] = agent_results

        # 计算加权得分和共识
        weighted_score = weighted_score_aggregation(
            [agent_results[k] for k in self.debate_agent_keys],
            self.agent_weights,
            self.debate_agent_keys,
        )
        consensus = compute_consensus_label(
            [agent_results[k] for k in self.debate_agent_keys]
        )
        result["weighted_score"] = weighted_score
        result["consensus"] = consensus
        msg(f"加权综合得分: {weighted_score:+.1f}, 共识: {consensus}")

        # ============================================================
        # Phase 3: CIO 拷问 (Challenge)
        # ============================================================
        notify("CIO 拷问")
        msg("CIO 正在审视共识并提出拷问...")
        cio_challenge = self._run_cio_challenge(
            agent_results=agent_results,
            weighted_score=weighted_score,
            consensus=consensus,
        )
        result["phases"]["cio_challenge"] = cio_challenge
        num_q = len(cio_challenge.get("challenges", []))
        msg(f"CIO 提出 {num_q} 个拷问，核心假设: "
            f"{cio_challenge.get('core_assumption', 'N/A')[:60]}")

        # ============================================================
        # Phase 3b: 分析师应答 CIO 拷问
        # ============================================================
        notify("分析师应答")
        msg("分析师正在回应 CIO 拷问...")
        challenged_results = {}
        for agent_key in self.debate_agent_keys:
            agent_info = AGENT_ROLES[agent_key]
            responded = self._run_challenge_response(
                agent_key=agent_key,
                current_analysis=agent_results[agent_key],
                cio_challenge=cio_challenge,
            )
            challenged_results[agent_key] = responded
            prev_pos = agent_results[agent_key].get("position", 0)
            new_pos = responded.get("position", 0)
            delta = new_pos - prev_pos
            if abs(delta) >= 5:
                msg(f"  {agent_info['name']}: {prev_pos:+d} → {new_pos:+d} (变化 {delta:+d})")
            else:
                msg(f"  {agent_info['name']}: {new_pos:+d} (立场未变)")

        agent_results = challenged_results
        result["phases"]["post_challenge_positions"] = agent_results

        # 重算加权得分
        weighted_score = weighted_score_aggregation(
            [agent_results[k] for k in self.debate_agent_keys],
            self.agent_weights,
            self.debate_agent_keys,
        )
        consensus = compute_consensus_label(
            [agent_results[k] for k in self.debate_agent_keys]
        )
        result["weighted_score"] = weighted_score
        result["consensus"] = consensus
        msg(f"拷问后加权得分: {weighted_score:+.1f}, 共识: {consensus}")

        # ============================================================
        # Phase 3c: 反共识分析 (Devil's Advocate)
        # ============================================================
        notify("反共识分析")
        msg("Devil's Advocate 正在构建反共识论证...")
        contrarian = self._run_contrarian_analysis(
            agent_results=agent_results,
            weighted_score=weighted_score,
            consensus=consensus,
            cio_challenge=cio_challenge,
            data_pack=data_pack,
        )
        result["phases"]["contrarian_analysis"] = contrarian
        msg(f"反共识立场: {contrarian.get('contrarian_position', 'N/A')}")
        msg(f"  概率评估: {contrarian.get('probability_estimate', '?')}%")
        msg(f"  核心价格驱动: {contrarian.get('key_price_driver', 'N/A')[:60]}")

        # ============================================================
        # Phase 4: 风控审核
        # ============================================================
        notify("风控审核")
        msg("风控官正在审核...")
        risk_verdict = self._run_risk_committee(
            agent_results=agent_results,
            weighted_score=weighted_score,
            consensus=consensus,
            data_pack=data_pack,
        )
        result["phases"]["risk_committee"] = risk_verdict
        msg(f"风控结论: {risk_verdict.get('verdict', 'N/A')}, "
            f"风险等级: {risk_verdict.get('risk_level', 'N/A')}")

        # ============================================================
        # Phase 5: CIO 最终决策 (增强版)
        # ============================================================
        notify("CIO 决策")
        msg("CIO 正在做最终决策...")
        cio_decision = self._run_cio_decision(
            symbol=symbol,
            company_name=data_pack["key_metrics"].get("company_name", symbol),
            agent_results=agent_results,
            weighted_score=weighted_score,
            risk_verdict=risk_verdict,
            data_pack=data_pack,
            cio_challenge=cio_challenge,
            contrarian=contrarian,
        )
        cio_decision["price_at_analysis"] = data_pack["technical_indicators"].get("current_price")
        result["phases"]["cio_decision"] = cio_decision
        result["recommendation"] = cio_decision.get("recommendation", "HOLD")
        result["confidence"] = cio_decision.get("confidence", 0)
        msg(f"CIO 决策: {result['recommendation']}, 信心: {result['confidence']}%")

        # ============================================================
        # Phase 5: 配对交易分析
        # ============================================================
        notify("配对交易分析")
        msg("正在评估配对交易机会...")
        pair_trade = self._run_pair_trade_analysis(
            symbol=symbol,
            company_name=data_pack["key_metrics"].get("company_name", symbol),
            cio_decision=cio_decision,
            data_pack=data_pack,
        )
        result["phases"]["pair_trade"] = pair_trade
        if pair_trade.get("has_recommendation"):
            long_sym = pair_trade.get("long_leg", {}).get("symbol", "?")
            short_sym = pair_trade.get("short_leg", {}).get("symbol", "?")
            msg(f"配对策略: Long {long_sym} / Short {short_sym}")
            msg(f"  逻辑: {pair_trade.get('thesis', '')}")
        else:
            msg(f"无配对推荐: {pair_trade.get('no_recommendation_reason', '未给出原因')}")

        # ============================================================
        # 存储记忆
        # ============================================================
        self.memory.store_analysis(symbol, cio_decision)

        # 更新历史分析的实际结果
        current_price = data_pack["technical_indicators"].get("current_price")
        if current_price:
            self.memory.update_outcome(symbol, current_price)

        notify("分析完成")
        return result

    # ==================================================================
    # 数据质量评估
    # ==================================================================
    @staticmethod
    def _assess_data_quality(data_pack: dict) -> str:
        """评估数据完整性，返回提示文本"""
        missing = []
        metrics = data_pack.get("key_metrics", {})
        if not metrics.get("market_cap"):
            missing.append("市值")
        if not metrics.get("pe_ratio"):
            missing.append("PE")
        if not metrics.get("revenue"):
            missing.append("营收")
        if not data_pack.get("technical_indicators", {}).get("current_price"):
            missing.append("当前价格")
        if not data_pack.get("financials"):
            missing.append("财务报表")
        comp_table = data_pack.get("competitive_comparison", {}).get("comparison_table", [])
        if len(comp_table) <= 1:
            missing.append("竞品数据")
        news = data_pack.get("news_data", {})
        if not news.get("news") and not news.get("earnings"):
            missing.append("新闻资讯")

        if not missing:
            return ""

        note = (
            "⚠️ **数据质量警告**: 以下数据未能成功获取: "
            + "、".join(missing) + "。\n"
            "这可能是因为数据源暂时不可用或网络问题。"
            "请你务必利用自身对该公司和行业的专业知识进行分析，"
            "不要因为数据缺失就放弃给出有价值的判断。"
            "你对这家公司的了解比数据源提供的内容更多——请充分展示。"
        )
        return note

    def _get_market_context(self, symbol: str) -> str:
        """从配置文件中获取与该股票相关的行业热点事件"""
        market_ctx = self.config.get("market_context", {})
        if not market_ctx:
            return "无预设行业事件。请基于你自身的行业知识补充近期重大事件。"

        relevant = []

        # 全局事件
        for event in market_ctx.get("global", []):
            relevant.append(f"- [全局] {event}")

        # 查找该股票所属行业
        industry_mapping = self.config.get("industry_mapping", {})
        stock_industries = []
        for industry_key, industry_info in industry_mapping.items():
            all_symbols = (
                industry_info.get("symbols", [])
                + industry_info.get("upstream", [])
                + industry_info.get("downstream", [])
            )
            if symbol in all_symbols:
                stock_industries.append(industry_key)

        # 行业事件
        for ind_key in stock_industries:
            for event in market_ctx.get(ind_key, []):
                relevant.append(f"- [{industry_mapping.get(ind_key, {}).get('name', ind_key)}] {event}")

        # 个股事件
        for event in market_ctx.get(symbol, []):
            relevant.append(f"- [{symbol}] {event}")

        if not relevant:
            return "无预设行业事件。请基于你自身的行业知识补充近期重大事件。"

        return "\n".join(relevant)

    # ==================================================================
    # Phase 1: 独立分析
    # ==================================================================
    def _run_agent_analysis(self, agent_key: str, data_pack: dict) -> dict:
        """单个Agent的独立分析"""
        agent = AGENT_ROLES[agent_key]
        prompt = INDEPENDENT_ANALYSIS_PROMPT.format(
            symbol=data_pack["symbol"],
            company_name=data_pack["key_metrics"].get("company_name", data_pack["symbol"]),
            key_metrics=format_metrics_text(data_pack["key_metrics"]),
            financial_data=format_financials_text(data_pack["financials"]),
            competitive_comparison=data_pack["competitive_text"],
            supply_chain_info=data_pack["supply_chain_text"],
            news_data=data_pack["news_text"],
            technical_indicators=format_technical_text(data_pack["technical_indicators"]),
            market_context=data_pack.get("market_context", ""),
            data_quality_note=data_pack.get("data_quality_note", ""),
            agent_role=f"{agent['name']} - {agent['title']}",
        )

        response = self._call_llm(
            model=self.analyst_model,
            system=agent["system_prompt"],
            user_message=prompt,
        )

        result = parse_json_response(response)
        if result is None:
            result = {
                "position": 0,
                "confidence": 30,
                "analysis": response[:500] if response else "分析失败",
                "key_points": [],
                "risks": [],
                "catalysts": [],
            }
        result["agent_key"] = agent_key
        result["agent_name"] = agent["name"]
        result["agent_title"] = agent["title"]
        return result

    # ==================================================================
    # Phase 2: 辩论轮次
    # ==================================================================
    def _run_debate_round(
        self,
        agent_key: str,
        round_num: int,
        my_previous: dict,
        all_results: dict,
    ) -> dict:
        """单个Agent的辩论轮次"""
        agent = AGENT_ROLES[agent_key]

        # 格式化其他Agent的观点
        other_texts = []
        for other_key, other_result in all_results.items():
            if other_key == agent_key:
                continue
            other_agent = AGENT_ROLES[other_key]
            other_texts.append(
                f"### {other_agent['name']} ({other_agent['title']})\n"
                f"- 立场: {other_result.get('position', 0):+d}\n"
                f"- 信心: {other_result.get('confidence', 0)}%\n"
                f"- 分析: {other_result.get('analysis', 'N/A')}\n"
                f"- 核心论点: {', '.join(other_result.get('key_points', []))}\n"
            )

        prompt = DEBATE_ROUND_PROMPT.format(
            round_num=round_num,
            my_previous_analysis=json.dumps(
                {k: v for k, v in my_previous.items()
                 if k not in ("agent_key", "agent_name", "agent_title")},
                ensure_ascii=False, indent=2,
            ),
            other_analyses="\n".join(other_texts),
        )

        response = self._call_llm(
            model=self.analyst_model,
            system=agent["system_prompt"],
            user_message=prompt,
        )

        result = parse_json_response(response)
        if result is None:
            result = my_previous.copy()
        result["agent_key"] = agent_key
        result["agent_name"] = agent["name"]
        result["agent_title"] = agent["title"]
        return result

    # ==================================================================
    # Phase 3: CIO 拷问
    # ==================================================================
    def _run_cio_challenge(
        self,
        agent_results: dict,
        weighted_score: float,
        consensus: str,
    ) -> dict:
        """CIO 对分析师共识提出尖锐质疑"""
        positions_text = []
        for agent_key in self.debate_agent_keys:
            r = agent_results[agent_key]
            agent_info = AGENT_ROLES[agent_key]
            positions_text.append(
                f"### {agent_info['name']} ({agent_info['title']})\n"
                f"- 立场: {r.get('position', 0):+d}, 信心: {r.get('confidence', 0)}%\n"
                f"- 核心论点: {', '.join(r.get('key_points', []))}\n"
                f"- 风险: {', '.join(r.get('risks', []))}"
            )

        prompt = CIO_CHALLENGE_PROMPT.format(
            final_positions="\n".join(positions_text),
            weighted_score=f"{weighted_score:+.1f}",
            consensus_direction=consensus,
        )

        response = self._call_llm(
            model=self.cio_model,
            system=CIO_CHALLENGE_SYSTEM_PROMPT,
            user_message=prompt,
        )

        result = parse_json_response(response)
        if result is None:
            result = {
                "consensus_summary": "解析失败",
                "consensus_direction": consensus,
                "core_assumption": "未知",
                "challenges": [],
            }
        return result

    # ==================================================================
    # Phase 3b: 分析师应答拷问
    # ==================================================================
    def _run_challenge_response(
        self,
        agent_key: str,
        current_analysis: dict,
        cio_challenge: dict,
    ) -> dict:
        """分析师回应 CIO 拷问"""
        agent = AGENT_ROLES[agent_key]

        # 格式化拷问
        challenges_text = []
        for i, ch in enumerate(cio_challenge.get("challenges", []), 1):
            challenges_text.append(
                f"{i}. **{ch.get('question', '')}**\n"
                f"   针对: {ch.get('target', '全体')}\n"
                f"   关键性: {ch.get('why_critical', '')}"
            )

        prompt = CHALLENGE_RESPONSE_PROMPT.format(
            my_current_analysis=json.dumps(
                {k: v for k, v in current_analysis.items()
                 if k not in ("agent_key", "agent_name", "agent_title")},
                ensure_ascii=False, indent=2,
            ),
            challenges="\n\n".join(challenges_text) if challenges_text else "无拷问",
        )

        response = self._call_llm(
            model=self.analyst_model,
            system=agent["system_prompt"],
            user_message=prompt,
        )

        result = parse_json_response(response)
        if result is None:
            result = current_analysis.copy()
        result["agent_key"] = agent_key
        result["agent_name"] = agent["name"]
        result["agent_title"] = agent["title"]
        return result

    # ==================================================================
    # Phase 3c: 反共识分析
    # ==================================================================
    def _run_contrarian_analysis(
        self,
        agent_results: dict,
        weighted_score: float,
        consensus: str,
        cio_challenge: dict,
        data_pack: dict,
    ) -> dict:
        """Devil's Advocate 反共识分析"""
        positions_text = []
        for agent_key in self.debate_agent_keys:
            r = agent_results[agent_key]
            agent_info = AGENT_ROLES[agent_key]
            positions_text.append(
                f"- {agent_info['name']}({agent_info['title']}): "
                f"立场 {r.get('position', 0):+d}, "
                f"论点: {', '.join(r.get('key_points', [])[:2])}"
            )

        # 找出被拷问后暴露的弱点
        weak_points = []
        for agent_key in self.debate_agent_keys:
            r = agent_results[agent_key]
            responses = r.get("responses", [])
            for resp in responses:
                if resp.get("conceded"):
                    weak_points.append(
                        f"- {r.get('agent_name', '')}: "
                        f"承认了「{resp.get('question', '')[:40]}」"
                    )

        prompt = CONTRARIAN_ANALYSIS_PROMPT.format(
            consensus_summary=cio_challenge.get("consensus_summary", consensus),
            consensus_direction=cio_challenge.get("consensus_direction", consensus),
            weighted_score=f"{weighted_score:+.1f}",
            core_assumption=cio_challenge.get("core_assumption", "未知"),
            final_positions="\n".join(positions_text),
            weak_points="\n".join(weak_points) if weak_points else "未发现明显弱点",
            key_data=format_metrics_text(data_pack["key_metrics"]),
        )

        response = self._call_llm(
            model=self.analyst_model,
            system=CONTRARIAN_SYSTEM_PROMPT,
            user_message=prompt,
        )

        result = parse_json_response(response)
        if result is None:
            result = {
                "contrarian_position": "无法生成反共识观点",
                "contrarian_thesis": response[:300] if response else "",
                "probability_estimate": 0,
            }
        return result

    # ==================================================================
    # Phase 4: 风控审核
    # ==================================================================
    def _run_risk_committee(
        self,
        agent_results: dict,
        weighted_score: float,
        consensus: str,
        data_pack: dict,
    ) -> dict:
        """风控委员会审核"""
        risk_agent = AGENT_ROLES["risk_manager"]

        # 格式化各分析师最终立场
        positions_text = []
        for agent_key in self.debate_agent_keys:
            r = agent_results[agent_key]
            agent_info = AGENT_ROLES[agent_key]
            positions_text.append(
                f"- {agent_info['name']}({agent_info['title']}): "
                f"立场 {r.get('position', 0):+d}, 信心 {r.get('confidence', 0)}%\n"
                f"  核心论点: {', '.join(r.get('key_points', []))}\n"
                f"  风险: {', '.join(r.get('risks', []))}"
            )

        # 关键数据摘要
        metrics = data_pack["key_metrics"]
        key_data = (
            f"- 当前价格: {data_pack['technical_indicators'].get('current_price', 'N/A')}\n"
            f"- 市值: {format_metrics_text({'market_cap': metrics.get('market_cap')}).strip('- 市值: ') if metrics.get('market_cap') else 'N/A'}\n"
            f"- PE: {metrics.get('pe_ratio', 'N/A')}\n"
            f"- 负债权益比: {metrics.get('debt_to_equity', 'N/A')}\n"
            f"- Beta: {metrics.get('beta', 'N/A')}\n"
            f"- 距52周高点: {data_pack['technical_indicators'].get('pct_from_52w_high', 'N/A')}%"
        )

        prompt = RISK_COMMITTEE_PROMPT.format(
            final_positions="\n".join(positions_text),
            weighted_score=f"{weighted_score:+.1f}",
            consensus_level=consensus,
            key_data_summary=key_data,
        )

        response = self._call_llm(
            model=self.analyst_model,
            system=risk_agent["system_prompt"],
            user_message=prompt,
        )

        result = parse_json_response(response)
        if result is None:
            result = {
                "verdict": "APPROVE_WITH_CONDITIONS",
                "risk_level": "MEDIUM",
                "max_position_pct": 5,
                "conditions": ["默认风控条件: 建议小仓位"],
            }
        return result

    # ==================================================================
    # Phase 4: CIO 决策
    # ==================================================================
    def _run_cio_decision(
        self,
        symbol: str,
        company_name: str,
        agent_results: dict,
        weighted_score: float,
        risk_verdict: dict,
        data_pack: dict,
        cio_challenge: Optional[dict] = None,
        contrarian: Optional[dict] = None,
    ) -> dict:
        """CIO 最终投资决策 (增强版: 含拷问结果和反共识)"""

        # 格式化各分析师最终立场
        positions_text = []
        for agent_key in self.debate_agent_keys:
            r = agent_results[agent_key]
            agent_info = AGENT_ROLES[agent_key]
            positions_text.append(
                f"### {agent_info['name']} ({agent_info['title']})\n"
                f"- 立场: {r.get('position', 0):+d}, 信心: {r.get('confidence', 0)}%\n"
                f"- 分析: {r.get('analysis', 'N/A')}\n"
                f"- 核心论点: {', '.join(r.get('key_points', []))}\n"
                f"- 风险: {', '.join(r.get('risks', []))}\n"
                f"- 催化剂: {', '.join(r.get('catalysts', []))}"
            )

        # 识别关键分歧
        bull_positions = [r for k, r in agent_results.items()
                          if r.get("position", 0) > 20]
        bear_positions = [r for k, r in agent_results.items()
                          if r.get("position", 0) < -20]
        disagreements = "多空观点概述:\n"
        if bull_positions:
            disagreements += "多头论据:\n"
            for r in bull_positions:
                disagreements += f"- {r.get('agent_name', '')}: {', '.join(r.get('key_points', [])[:2])}\n"
        if bear_positions:
            disagreements += "空头论据:\n"
            for r in bear_positions:
                disagreements += f"- {r.get('agent_name', '')}: {', '.join(r.get('key_points', [])[:2])}\n"

        # CIO 拷问摘要
        challenge_summary = "无拷问记录"
        if cio_challenge and cio_challenge.get("challenges"):
            lines = [f"核心假设: {cio_challenge.get('core_assumption', 'N/A')}"]
            for ch in cio_challenge["challenges"]:
                lines.append(f"- 拷问: {ch.get('question', '')}")
            # 分析师回应中的让步
            for agent_key in self.debate_agent_keys:
                r = agent_results[agent_key]
                for resp in r.get("responses", []):
                    if resp.get("conceded"):
                        lines.append(
                            f"- {r.get('agent_name', '')} 承认: {resp.get('answer', '')[:60]}..."
                        )
            challenge_summary = "\n".join(lines)

        # 反共识分析摘要
        contrarian_text = "无反共识分析"
        if contrarian:
            contrarian_text = (
                f"反共识立场: {contrarian.get('contrarian_position', 'N/A')}\n"
                f"反共识论点: {contrarian.get('contrarian_thesis', 'N/A')}\n"
                f"概率评估: {contrarian.get('probability_estimate', '?')}%\n"
                f"核心价格驱动: {contrarian.get('key_price_driver', 'N/A')}\n"
            )
            evidence = contrarian.get("contrarian_evidence", [])
            if evidence:
                contrarian_text += "证据:\n"
                for e in evidence[:3]:
                    contrarian_text += f"  - {e.get('point', '')}: {e.get('data_support', '')}\n"
            if contrarian.get("historical_parallel"):
                contrarian_text += f"历史类比: {contrarian['historical_parallel']}\n"

        # 风控意见
        risk_text = (
            f"- 审核结论: {risk_verdict.get('verdict', 'N/A')}\n"
            f"- 风险等级: {risk_verdict.get('risk_level', 'N/A')}\n"
            f"- 最大仓位: {risk_verdict.get('max_position_pct', 'N/A')}%\n"
            f"- 条件: {', '.join(risk_verdict.get('conditions', []))}\n"
        )
        if risk_verdict.get("veto_reason"):
            risk_text += f"- 否决理由: {risk_verdict['veto_reason']}\n"

        # 历史记忆
        memory_context = self.memory.get_context_for_analysis(symbol)

        prompt = CIO_DECISION_PROMPT.format(
            symbol=symbol,
            company_name=company_name,
            final_positions="\n".join(positions_text),
            key_disagreements=disagreements,
            weighted_score=f"{weighted_score:+.1f}",
            challenge_summary=challenge_summary,
            contrarian_analysis=contrarian_text,
            risk_committee_verdict=risk_text,
            memory_context=memory_context,
        )

        response = self._call_llm(
            model=self.cio_model,
            system=CIO_SYSTEM_PROMPT,
            user_message=prompt,
        )

        result = parse_json_response(response)
        if result is None:
            result = {
                "recommendation": "HOLD",
                "confidence": 30,
                "executive_summary": response[:500] if response else "决策生成失败",
            }

        # 如果风控否决，强制 HOLD
        if risk_verdict.get("verdict") == "VETO":
            result["recommendation"] = "HOLD"
            result["executive_summary"] = (
                f"[风控否决] {risk_verdict.get('veto_reason', '')}。"
                f"原始CIO判断: {result.get('executive_summary', '')}"
            )

        return result

    # ==================================================================
    # Phase 5: 配对交易
    # ==================================================================
    def _run_pair_trade_analysis(
        self,
        symbol: str,
        company_name: str,
        cio_decision: dict,
        data_pack: dict,
    ) -> dict:
        """配对交易 (Long/Short) 策略分析"""

        # 构建候选池: 竞品 + 产业链上下游
        comparison = data_pack["competitive_comparison"]
        candidates = []

        # 竞品
        comp_table = comparison.get("comparison_table", [])
        for row in comp_table:
            s = row.get("symbol", "")
            if s and s != symbol:
                name = row.get("name", s)
                pe = row.get("pe_ratio")
                growth = row.get("revenue_growth")
                margin = row.get("profit_margin")
                candidates.append(
                    f"- {s} ({name}): PE={pe or 'N/A'}, "
                    f"营收增速={f'{growth*100:.1f}%' if growth else 'N/A'}, "
                    f"净利率={f'{margin*100:.1f}%' if margin else 'N/A'} [竞品]"
                )

        # 上游
        for comp in comparison.get("supply_chain_upstream", []):
            s = comp.get("symbol", "")
            name = comp.get("company_name", s)
            pe = comp.get("pe_ratio")
            growth = comp.get("revenue_growth")
            candidates.append(
                f"- {s} ({name}): PE={pe or 'N/A'}, "
                f"营收增速={f'{growth*100:.1f}%' if growth else 'N/A'} [上游]"
            )

        # 下游
        for comp in comparison.get("supply_chain_downstream", []):
            s = comp.get("symbol", "")
            name = comp.get("company_name", s)
            pe = comp.get("pe_ratio")
            growth = comp.get("revenue_growth")
            candidates.append(
                f"- {s} ({name}): PE={pe or 'N/A'}, "
                f"营收增速={f'{growth*100:.1f}%' if growth else 'N/A'} [下游]"
            )

        candidate_text = "\n".join(candidates) if candidates else "候选池为空（未找到相关标的）"

        prompt = PAIR_TRADE_PROMPT.format(
            symbol=symbol,
            company_name=company_name,
            recommendation=cio_decision.get("recommendation", "N/A"),
            confidence=cio_decision.get("confidence", 0),
            bull_arguments=", ".join(cio_decision.get("key_bull_arguments", [])),
            bear_arguments=", ".join(cio_decision.get("key_bear_arguments", [])),
            competitive_comparison=data_pack["competitive_text"],
            supply_chain_info=data_pack["supply_chain_text"],
            candidate_pool=candidate_text,
        )

        response = self._call_llm(
            model=self.analyst_model,
            system=PAIR_TRADE_SYSTEM_PROMPT,
            user_message=prompt,
        )

        result = parse_json_response(response)
        if result is None:
            result = {
                "has_recommendation": False,
                "no_recommendation_reason": "配对交易分析未能生成有效结果",
            }
        return result

    # ==================================================================
    # 数据收集
    # ==================================================================
    def _collect_data(self, symbol: str) -> dict:
        """收集分析所需的全部数据"""
        data_cfg = self.config.get("data", {})

        # 基础数据
        key_metrics = self.fetcher.fetch_key_metrics(symbol)
        price_data = self.fetcher.fetch_price_data(
            symbol, period=data_cfg.get("price_lookback", "1y")
        )
        financials = self.fetcher.fetch_financials(symbol)
        technical = self.fetcher.compute_technical_indicators(price_data)

        # 竞品与产业链
        comparison = self.industry_analyzer.build_competitive_comparison(symbol)
        competitive_text = self.industry_analyzer.format_comparison_text(comparison)

        # 产业链文本
        supply_chain_lines = []
        for direction, label in [("supply_chain_upstream", "上游"), ("supply_chain_downstream", "下游")]:
            companies = comparison.get(direction, [])
            if companies:
                supply_chain_lines.append(f"\n### 产业链{label}")
                for c in companies:
                    rg = c.get('revenue_growth')
                    pm = c.get('profit_margin')
                    rg_str = f"{rg*100:.1f}%" if rg else "N/A"
                    pm_str = f"{pm*100:.1f}%" if pm else "N/A"
                    supply_chain_lines.append(
                        f"- {c.get('company_name', c.get('symbol', ''))}: "
                        f"营收增速 {rg_str}, 利润率 {pm_str}"
                    )
        supply_chain_text = "\n".join(supply_chain_lines) if supply_chain_lines else "无产业链数据"

        # 新闻
        news_data = self.news_collector.collect_all_news(
            symbol=symbol,
            company_name=key_metrics.get("company_name", ""),
            industry=key_metrics.get("industry", ""),
            max_items=data_cfg.get("max_news_items", 20),
        )
        news_text = self.news_collector.format_news_text(news_data)

        data_pack = {
            "symbol": symbol,
            "key_metrics": key_metrics,
            "price_data": price_data,
            "financials": financials,
            "technical_indicators": technical,
            "competitive_comparison": comparison,
            "competitive_text": competitive_text,
            "supply_chain_text": supply_chain_text,
            "news_data": news_data,
            "news_text": news_text,
        }

        # 数据质量评估
        data_pack["data_quality_note"] = self._assess_data_quality(data_pack)

        # 行业热点事件
        data_pack["market_context"] = self._get_market_context(symbol)

        return data_pack

    # ==================================================================
    # LLM 调用
    # ==================================================================
    def _call_llm(self, model: str, system: str, user_message: str) -> str:
        """调用 Anthropic LLM"""
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
            # 统计 token 用量
            usage = response.usage
            input_tokens = getattr(usage, "input_tokens", 0)
            output_tokens = getattr(usage, "output_tokens", 0)
            if not hasattr(self, "_token_usage"):
                self._token_usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "by_model": {}}
            self._token_usage["calls"] += 1
            self._token_usage["input_tokens"] += input_tokens
            self._token_usage["output_tokens"] += output_tokens
            if model not in self._token_usage["by_model"]:
                self._token_usage["by_model"][model] = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
            self._token_usage["by_model"][model]["calls"] += 1
            self._token_usage["by_model"][model]["input_tokens"] += input_tokens
            self._token_usage["by_model"][model]["output_tokens"] += output_tokens
            logger.debug(f"Token: +{input_tokens}in/{output_tokens}out ({model.split('-')[1]})")
            return response.content[0].text
        except Exception as e:
            error_msg = str(e)
            if "authentication" in error_msg.lower() or "api_key" in error_msg.lower() or "auth_token" in error_msg.lower():
                logger.error(f"API 认证失败: {e}\n请检查 ANTHROPIC_API_KEY 是否正确设置")
            else:
                logger.error(f"LLM 调用失败 ({model}): {e}")
            return ""

    def get_token_usage(self) -> dict:
        """返回累计 token 用量统计"""
        return getattr(self, "_token_usage", {"calls": 0, "input_tokens": 0, "output_tokens": 0, "by_model": {}})

    # ==================================================================
    # 报告生成
    # ==================================================================
    @staticmethod
    def generate_report(result: dict) -> str:
        """生成完整的分析报告文本"""
        lines = []
        summary = result.get("data_summary", {})
        cio = result.get("phases", {}).get("cio_decision", {})
        risk = result.get("phases", {}).get("risk_committee", {})

        lines.append("=" * 60)
        lines.append(f"个股深度分析报告")
        lines.append("=" * 60)
        lines.append(f"公司: {summary.get('company_name', result.get('symbol', ''))}")
        lines.append(f"代码: {result.get('symbol', '')}")
        lines.append(f"行业: {summary.get('sector', '')} - {summary.get('industry', '')}")
        lines.append(f"分析时间: {result.get('timestamp', '')[:19]}")
        lines.append(f"当前价格: ${summary.get('current_price', 'N/A')}")
        lines.append(f"对比竞品数: {summary.get('competitors_count', 0)}")
        lines.append("")

        # CIO 决策摘要
        lines.append("-" * 40)
        lines.append("CIO 投资决策")
        lines.append("-" * 40)
        lines.append(f"建议: {cio.get('recommendation', 'N/A')}")
        lines.append(f"信心: {cio.get('confidence', 0)}%")
        lines.append(f"目标价: {cio.get('target_price', 'N/A')}")
        lines.append(f"止损位: {cio.get('stop_loss', 'N/A')}")
        lines.append(f"时间维度: {cio.get('time_horizon', 'N/A')}")
        lines.append(f"建议仓位: {cio.get('position_size_pct', 'N/A')}%")
        lines.append("")
        lines.append(f"投资结论:")
        lines.append(cio.get("executive_summary", "无"))
        lines.append("")

        # 多空论点
        bull_args = cio.get("key_bull_arguments", [])
        if bull_args:
            lines.append("核心多头论点:")
            for a in bull_args:
                lines.append(f"  + {a}")

        bear_args = cio.get("key_bear_arguments", [])
        if bear_args:
            lines.append("核心空头论点:")
            for a in bear_args:
                lines.append(f"  - {a}")

        decisive = cio.get("decisive_factors", [])
        if decisive:
            lines.append("决定性因素:")
            for d in decisive:
                lines.append(f"  * {d}")

        lines.append("")

        # 共识 vs 反共识
        cvc = cio.get("consensus_vs_contrarian", {})
        contrarian = result.get("phases", {}).get("contrarian_analysis", {})
        challenge = result.get("phases", {}).get("cio_challenge", {})
        if cvc or contrarian:
            lines.append("=" * 60)
            lines.append("共识观点 vs 反共识观点")
            lines.append("=" * 60)
            if cvc:
                lines.append(f"共识观点 (概率 {cvc.get('consensus_probability', '?')}%):")
                lines.append(f"  {cvc.get('consensus_view', 'N/A')}")
                lines.append(f"反共识观点 (概率 {cvc.get('contrarian_probability', '?')}%):")
                lines.append(f"  {cvc.get('contrarian_view', 'N/A')}")
                lines.append("")
                drivers = cvc.get("key_price_drivers", [])
                if drivers:
                    lines.append("核心股价驱动变量:")
                    for d in drivers:
                        lines.append(f"  >> {d}")
                if cvc.get("what_consensus_is_missing"):
                    lines.append(f"共识盲点: {cvc['what_consensus_is_missing']}")
                if cvc.get("cio_independent_judgment"):
                    lines.append(f"CIO独立判断: {cvc['cio_independent_judgment']}")
            lines.append("")

            if contrarian.get("contrarian_thesis"):
                lines.append("-" * 40)
                lines.append("Devil's Advocate 反共识详细论证")
                lines.append("-" * 40)
                lines.append(f"反共识立场: {contrarian.get('contrarian_position', 'N/A')}")
                lines.append(f"核心论点: {contrarian.get('contrarian_thesis', 'N/A')}")
                lines.append(f"概率评估: {contrarian.get('probability_estimate', '?')}%")
                lines.append(f"核心价格驱动: {contrarian.get('key_price_driver', 'N/A')}")
                evidence = contrarian.get("contrarian_evidence", [])
                if evidence:
                    lines.append("证据:")
                    for e in evidence[:3]:
                        lines.append(f"  - {e.get('point', '')}")
                        lines.append(f"    数据: {e.get('data_support', '')}")
                        lines.append(f"    共识盲点: {e.get('consensus_blind_spot', '')}")
                if contrarian.get("historical_parallel"):
                    lines.append(f"历史类比: {contrarian['historical_parallel']}")
                if contrarian.get("trigger_scenario"):
                    lines.append(f"验证场景: {contrarian['trigger_scenario']}")

            if challenge.get("challenges"):
                lines.append("")
                lines.append("-" * 40)
                lines.append("CIO 拷问记录")
                lines.append("-" * 40)
                lines.append(f"共识核心假设: {challenge.get('core_assumption', 'N/A')}")
                for i, ch in enumerate(challenge["challenges"], 1):
                    lines.append(f"  Q{i}: {ch.get('question', '')}")
            lines.append("")

        # 风控意见
        lines.append("-" * 40)
        lines.append("风控委员会意见")
        lines.append("-" * 40)
        lines.append(f"结论: {risk.get('verdict', 'N/A')}")
        lines.append(f"风险等级: {risk.get('risk_level', 'N/A')}")
        lines.append(f"最大仓位: {risk.get('max_position_pct', 'N/A')}%")
        conditions = risk.get("conditions", [])
        if conditions:
            lines.append("条件:")
            for c in conditions:
                lines.append(f"  - {c}")
        lines.append("")

        # 各分析师最终立场 (经CIO拷问后)
        lines.append("-" * 40)
        lines.append("各分析师最终立场 (经CIO拷问后)")
        lines.append("-" * 40)
        final_positions = result.get("phases", {}).get("post_challenge_positions",
                          result.get("phases", {}).get("final_positions", {}))
        for agent_key, pos in final_positions.items():
            lines.append(
                f"{pos.get('agent_name', '')} ({pos.get('agent_title', '')}): "
                f"立场 {pos.get('position', 0):+d}, 信心 {pos.get('confidence', 0)}%"
            )
            points = pos.get("key_points", [])
            if points:
                for p in points[:2]:
                    lines.append(f"  - {p}")

        lines.append("")
        lines.append(f"加权综合得分: {result.get('weighted_score', 0):+.1f}")
        lines.append(f"共识水平: {result.get('consensus', 'N/A')}")

        # 催化剂与风险
        catalysts = cio.get("catalysts", [])
        if catalysts:
            lines.append("")
            lines.append("需关注的催化剂:")
            for c in catalysts:
                lines.append(f"  >> {c}")

        risk_factors = cio.get("risk_factors", [])
        if risk_factors:
            lines.append("")
            lines.append("持续监控的风险:")
            for r in risk_factors:
                lines.append(f"  !! {r}")

        # 交易信号与策略
        signal = cio.get("trading_signal", {})
        if signal:
            lines.append("")
            lines.append("=" * 60)
            lines.append("交易信号与执行策略")
            lines.append("=" * 60)
            lines.append(f"交易动作: {signal.get('action', 'N/A')}")
            lines.append(f"紧迫程度: {signal.get('urgency', 'N/A')}")
            lines.append(f"建议入场价: {signal.get('entry_price', 'N/A')}")
            lines.append("")
            lines.append(f"入场策略:")
            lines.append(f"  {signal.get('entry_strategy', 'N/A')}")
            lines.append("")
            lines.append(f"仓位管理:")
            lines.append(f"  {signal.get('position_plan', 'N/A')}")
            lines.append("")

            exit_plan = signal.get("exit_plan", {})
            if exit_plan:
                lines.append("退出计划:")
                tp1 = exit_plan.get("take_profit_1", {})
                tp2 = exit_plan.get("take_profit_2", {})
                sl = exit_plan.get("stop_loss", {})
                if tp1:
                    lines.append(f"  止盈1: 价格 {tp1.get('price', 'N/A')} → 减仓 {tp1.get('sell_pct', 'N/A')}%")
                if tp2:
                    lines.append(f"  止盈2: 价格 {tp2.get('price', 'N/A')} → 减仓 {tp2.get('sell_pct', 'N/A')}%")
                if sl:
                    lines.append(f"  止损:  价格 {sl.get('price', 'N/A')} → 清仓 {sl.get('sell_pct', 'N/A')}%")

            triggers = signal.get("review_triggers", [])
            if triggers:
                lines.append("")
                lines.append("重新评估触发条件:")
                for t in triggers:
                    lines.append(f"  -> {t}")

        # 配对交易策略
        pair = result.get("phases", {}).get("pair_trade", {})
        lines.append("")
        lines.append("=" * 60)
        lines.append("配对交易策略 (Long/Short)")
        lines.append("=" * 60)
        if pair.get("has_recommendation"):
            lines.append(f"策略: {pair.get('strategy_name', 'N/A')}")
            lines.append(f"类型: {pair.get('pair_type', 'N/A')}")
            lines.append(f"核心逻辑: {pair.get('thesis', 'N/A')}")
            lines.append("")

            long_leg = pair.get("long_leg", {})
            short_leg = pair.get("short_leg", {})
            lines.append(f"  LONG  {long_leg.get('symbol', '?')} ({long_leg.get('company_name', '')}) "
                         f"权重 {long_leg.get('weight', 'N/A')}")
            lines.append(f"    理由: {long_leg.get('rationale', 'N/A')}")
            lines.append(f"  SHORT {short_leg.get('symbol', '?')} ({short_leg.get('company_name', '')}) "
                         f"权重 {short_leg.get('weight', 'N/A')}")
            lines.append(f"    理由: {short_leg.get('rationale', 'N/A')}")
            lines.append("")

            execution = pair.get("execution", {})
            if execution:
                lines.append("执行计划:")
                lines.append(f"  入场时机: {execution.get('entry_timing', 'N/A')}")
                lines.append(f"  持有周期: {execution.get('holding_period', 'N/A')}")
                lines.append(f"  目标收益: {execution.get('profit_target', 'N/A')}")
                lines.append(f"  止损条件: {execution.get('stop_loss', 'N/A')}")
                lines.append(f"  配对仓位: {execution.get('position_sizing', 'N/A')}")

            risk_notes = pair.get("risk_notes", [])
            if risk_notes:
                lines.append("")
                lines.append("配对风险:")
                for rn in risk_notes:
                    lines.append(f"  !! {rn}")

            if pair.get("invalidation"):
                lines.append(f"  失效条件: {pair['invalidation']}")
        else:
            lines.append(f"无配对推荐")
            lines.append(f"原因: {pair.get('no_recommendation_reason', '未给出原因')}")

        # 报告指标说明
        lines.append("")
        lines.append("=" * 60)
        lines.append("报告指标说明")
        lines.append("=" * 60)
        lines.append("")
        lines.append("一、分析师立场 (Position: -100 ~ +100)")
        lines.append("  +100 = 极度看多    +50 = 中度看多    +20 = 轻度看多")
        lines.append("    0  = 中性")
        lines.append("  -20  = 轻度看空    -50 = 中度看空   -100 = 极度看空")
        lines.append("")
        lines.append("二、信心度 (Confidence: 0% ~ 100%)")
        lines.append("  90-100% 极高确信 | 70-89% 高确信 | 50-69% 中等确信")
        lines.append("  30-49%  低确信   | 0-29%  极低确信")
        lines.append("  注: 立场和信心是独立维度。'+80/信心40%'=倾向看多但很不确定。")
        lines.append("")
        lines.append("三、加权综合得分 = Σ(立场 × 角色权重 × 信心) / Σ(角色权重 × 信心)")
        lines.append("  > +40 整体偏多 | +15~+40 温和偏多 | -15~+15 中性")
        lines.append("  -40~-15 温和偏空 | < -40 整体偏空")
        lines.append("")
        lines.append("四、CIO 建议: STRONG_BUY > BUY > HOLD > SELL > STRONG_SELL")
        lines.append("五、风控: APPROVE / APPROVE_WITH_CONDITIONS / VETO(否决→强制HOLD)")

        lines.append("")
        lines.append("=" * 60)
        lines.append("免责声明: 本分析由AI生成，仅供参考，不构成投资建议。")
        lines.append("=" * 60)

        return "\n".join(lines)
