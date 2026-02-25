"""
决策记忆系统 (FinMem)
三层记忆: 短期(近5次) + 长期(30天) + 反思(从错误中学习)
参考: FinMem (2024), Reflexion (NeurIPS 2023)
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MEMORY_DIR = Path("data/memory")
MEMORY_DIR.mkdir(parents=True, exist_ok=True)


class AnalysisMemory:
    """个股分析决策记忆"""

    def __init__(self):
        self._cache: dict[str, list[dict]] = {}

    def _file_path(self, symbol: str) -> Path:
        return MEMORY_DIR / f"{symbol.replace('.', '_')}.json"

    def _load(self, symbol: str) -> list[dict]:
        if symbol in self._cache:
            return self._cache[symbol]
        path = self._file_path(symbol)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    records = json.load(f)
                self._cache[symbol] = records
                return records
            except Exception as e:
                logger.warning(f"记忆加载失败 {symbol}: {e}")
        return []

    def _save(self, symbol: str, records: list[dict]):
        self._cache[symbol] = records
        path = self._file_path(symbol)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"记忆保存失败 {symbol}: {e}")

    def store_analysis(self, symbol: str, analysis_result: dict):
        """存储一次分析结果"""
        records = self._load(symbol)
        record = {
            "timestamp": datetime.now().isoformat(),
            "recommendation": analysis_result.get("recommendation", "N/A"),
            "confidence": analysis_result.get("confidence", 0),
            "target_price": analysis_result.get("target_price"),
            "executive_summary": analysis_result.get("executive_summary", ""),
            "key_bull_arguments": analysis_result.get("key_bull_arguments", []),
            "key_bear_arguments": analysis_result.get("key_bear_arguments", []),
            "price_at_analysis": analysis_result.get("price_at_analysis"),
            "outcome": None,  # 后续更新
        }
        records.append(record)
        # 保留最近30条
        records = records[-30:]
        self._save(symbol, records)

    def update_outcome(self, symbol: str, price_now: float):
        """更新历史分析的实际结果"""
        records = self._load(symbol)
        updated = False
        for record in records:
            if record.get("outcome") is None and record.get("price_at_analysis"):
                price_then = record["price_at_analysis"]
                actual_return = (price_now / price_then - 1) * 100
                recommendation = record.get("recommendation", "")
                was_correct = (
                    (actual_return > 0 and recommendation in ("BUY", "STRONG_BUY"))
                    or (actual_return < 0 and recommendation in ("SELL", "STRONG_SELL"))
                    or (abs(actual_return) < 5 and recommendation == "HOLD")
                )
                record["outcome"] = {
                    "price_now": price_now,
                    "actual_return_pct": round(actual_return, 2),
                    "was_correct": was_correct,
                    "evaluated_at": datetime.now().isoformat(),
                }
                updated = True
        if updated:
            self._save(symbol, records)

    def get_context_for_analysis(self, symbol: str) -> str:
        """获取历史分析上下文，注入到CIO决策中"""
        records = self._load(symbol)
        if not records:
            return "无历史分析记录。"

        lines = ["## 历史分析记录"]

        # 短期记忆: 最近5次
        recent = records[-5:]
        lines.append("\n### 近期分析 (最近5次)")
        for r in recent:
            ts = r["timestamp"][:10]
            rec = r.get("recommendation", "N/A")
            conf = r.get("confidence", 0)
            lines.append(f"- [{ts}] {rec} (信心: {conf}%)")
            if r.get("executive_summary"):
                lines.append(f"  摘要: {r['executive_summary'][:100]}...")
            outcome = r.get("outcome")
            if outcome:
                ret = outcome.get("actual_return_pct", 0)
                correct = "正确" if outcome.get("was_correct") else "错误"
                lines.append(f"  实际回报: {ret:+.1f}% ({correct})")

        # 反思记忆: 从错误中学习
        errors = [r for r in records if r.get("outcome", {}).get("was_correct") is False]
        if errors:
            lines.append("\n### 反思: 历史错误判断")
            for r in errors[-3:]:  # 最近3次错误
                ts = r["timestamp"][:10]
                rec = r.get("recommendation", "N/A")
                ret = r.get("outcome", {}).get("actual_return_pct", 0)
                lines.append(f"- [{ts}] 判断 {rec}，实际回报 {ret:+.1f}%")
                if r.get("key_bull_arguments"):
                    lines.append(f"  当时的多头论点: {r['key_bull_arguments'][0]}")
                if r.get("key_bear_arguments"):
                    lines.append(f"  当时的空头论点: {r['key_bear_arguments'][0]}")

        # 统计
        with_outcome = [r for r in records if r.get("outcome") is not None]
        if with_outcome:
            correct_count = sum(1 for r in with_outcome if r["outcome"].get("was_correct"))
            total = len(with_outcome)
            win_rate = correct_count / total * 100
            lines.append(f"\n### 历史统计")
            lines.append(f"- 总分析次数: {len(records)}")
            lines.append(f"- 已验证: {total} 次, 正确率: {win_rate:.0f}%")

        return "\n".join(lines)
