"""
交易执行器 - 将 CIO 分析信号映射为实际交易动作
"""

import logging
from typing import Optional

from src.paper_trading.portfolio import PortfolioManager

logger = logging.getLogger(__name__)

# CIO recommendation -> 交易动作映射
ACTION_MAP = {
    "STRONG_BUY": "buy",
    "BUY": "buy",
    "HOLD": "hold",
    "SELL": "sell",
    "STRONG_SELL": "sell",
}


class Trader:
    """根据 CIO 决策自动执行模拟交易"""

    def __init__(self, portfolio: PortfolioManager):
        self.portfolio = portfolio

    def execute_signal(
        self,
        symbol: str,
        analysis_result: dict,
        current_price: float,
    ) -> dict:
        """
        根据分析结果执行交易

        Returns:
            {action_taken, details, ...}
        """
        cio = analysis_result.get("phases", {}).get("cio_decision", {})
        risk = analysis_result.get("phases", {}).get("risk_committee", {})

        recommendation = cio.get("recommendation", "HOLD")
        confidence = cio.get("confidence", 0)
        target_price = cio.get("target_price")
        stop_loss = cio.get("stop_loss")
        position_size_pct = cio.get("position_size_pct", 0)
        risk_verdict = risk.get("verdict", "APPROVED")

        action = ACTION_MAP.get(recommendation, "hold")

        # 风控否决
        if risk_verdict == "VETOED":
            logger.warning(f"{symbol}: 风控否决，跳过交易")
            return {"action_taken": "VETOED", "reason": "风控一票否决"}

        # 信心过低不交易
        if confidence < 50 and action == "buy":
            logger.info(f"{symbol}: 信心 {confidence}% < 50%，不买入")
            return {"action_taken": "SKIP", "reason": f"信心不足 ({confidence}%)"}

        position = self.portfolio.get_position(symbol)
        has_position = position["shares"] > 0

        result = {"symbol": symbol, "recommendation": recommendation, "confidence": confidence}

        if action == "buy":
            result.update(
                self._handle_buy(symbol, current_price, position_size_pct,
                                 recommendation, confidence, cio)
            )
        elif action == "sell":
            if has_position:
                result.update(
                    self._handle_sell(symbol, current_price, recommendation,
                                     confidence, cio)
                )
            else:
                result["action_taken"] = "SKIP"
                result["reason"] = f"无持仓，忽略 {recommendation} 信号"
        else:
            # HOLD - 检查是否需要止损/止盈
            if has_position:
                result.update(
                    self._check_exit_conditions(symbol, current_price, position,
                                                target_price, stop_loss)
                )
            else:
                result["action_taken"] = "HOLD"
                result["reason"] = "维持观望"

        return result

    def _handle_buy(
        self,
        symbol: str,
        price: float,
        position_size_pct: float,
        recommendation: str,
        confidence: int,
        cio: dict,
    ) -> dict:
        """处理买入信号"""
        portfolio_value = self.portfolio.cash
        # 加上现有持仓的估值作为组合总值基础
        all_positions = self.portfolio.get_all_positions()
        for p in all_positions:
            portfolio_value += p["shares"] * p["avg_cost"]  # 近似值

        # 计算目标仓位金额
        target_amount = portfolio_value * (position_size_pct / 100)

        # 检查已有持仓
        existing = self.portfolio.get_position(symbol)
        existing_value = existing["shares"] * existing["avg_cost"] if existing["shares"] > 0 else 0

        # 需要增加的金额
        add_amount = target_amount - existing_value
        if add_amount <= 0:
            return {
                "action_taken": "SKIP",
                "reason": f"已持有 ${existing_value:,.0f}，目标 ${target_amount:,.0f}，无需加仓",
            }

        # 不超过可用现金
        add_amount = min(add_amount, self.portfolio.cash * 0.95)  # 保留5%现金
        if add_amount < 100:
            return {"action_taken": "SKIP", "reason": "可分配金额过小"}

        shares = int(add_amount / price)
        if shares <= 0:
            return {"action_taken": "SKIP", "reason": "可买入股数不足1股"}

        reason = f"{recommendation} (信心{confidence}%) | {cio.get('executive_summary', '')[:100]}"
        trade = self.portfolio.buy(
            symbol=symbol,
            shares=shares,
            price=price,
            recommendation=recommendation,
            confidence=confidence,
            reason=reason,
        )
        trade["action_taken"] = "BUY"
        return trade

    def _handle_sell(
        self,
        symbol: str,
        price: float,
        recommendation: str,
        confidence: int,
        cio: dict,
    ) -> dict:
        """处理卖出信号"""
        position = self.portfolio.get_position(symbol)

        if recommendation == "STRONG_SELL":
            # 全部清仓
            sell_shares = position["shares"]
            reason = f"STRONG_SELL 清仓 (信心{confidence}%)"
        else:
            # SELL: 减半
            sell_shares = int(position["shares"] / 2)
            if sell_shares <= 0:
                sell_shares = position["shares"]
            reason = f"SELL 减仓 (信心{confidence}%)"

        reason += f" | {cio.get('executive_summary', '')[:100]}"
        trade = self.portfolio.sell(
            symbol=symbol,
            shares=sell_shares,
            price=price,
            recommendation=recommendation,
            confidence=confidence,
            reason=reason,
        )
        trade["action_taken"] = "SELL"
        return trade

    def _check_exit_conditions(
        self,
        symbol: str,
        current_price: float,
        position: dict,
        target_price: Optional[float],
        stop_loss: Optional[float],
    ) -> dict:
        """检查止损/止盈条件"""
        avg_cost = position["avg_cost"]

        # 止损
        if stop_loss and current_price <= stop_loss:
            trade = self.portfolio.sell(
                symbol=symbol,
                shares=position["shares"],
                price=current_price,
                reason=f"触发止损: 当前 ${current_price:.2f} <= 止损 ${stop_loss:.2f}",
            )
            trade["action_taken"] = "STOP_LOSS"
            return trade

        # 止盈 (到达目标价)
        if target_price and current_price >= target_price:
            # 止盈卖出一半
            sell_shares = max(1, int(position["shares"] / 2))
            trade = self.portfolio.sell(
                symbol=symbol,
                shares=sell_shares,
                price=current_price,
                reason=f"到达目标价: 当前 ${current_price:.2f} >= 目标 ${target_price:.2f}",
            )
            trade["action_taken"] = "TAKE_PROFIT"
            return trade

        return {"action_taken": "HOLD", "reason": "未触发止损/止盈条件"}

    def check_all_stops(self, prices: dict[str, float]) -> list[dict]:
        """检查所有持仓的止损/止盈（可在每日快照时调用）"""
        results = []
        positions = self.portfolio.get_all_positions()
        for pos in positions:
            sym = pos["symbol"]
            price = prices.get(sym)
            if price is None:
                continue

            # 从最近分析日志获取止损/止盈
            logs = self.portfolio.get_analysis_log(symbol=sym, limit=1)
            if not logs:
                continue

            latest = logs[0]
            result = self._check_exit_conditions(
                symbol=sym,
                current_price=price,
                position=pos,
                target_price=latest.get("target_price"),
                stop_loss=latest.get("stop_loss"),
            )
            if result["action_taken"] != "HOLD":
                results.append(result)

        return results
